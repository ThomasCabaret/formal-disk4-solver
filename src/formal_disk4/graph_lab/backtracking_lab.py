from __future__ import annotations

"""Deterministic, unbounded tile-frontier benchmark over ordered graph families.

For each fixed graph the joint mapping/weak-order backtracker runs until its
tree is exhausted or one emitted formal profile obtains a geometric solution.
There is no wall-clock, node, placement, assignment, or profile limit.  Formal
resource guardrails that deliberately defer unsupported word systems remain
visible as proof gaps; they do not stop traversal of the surrounding tree.
"""

import argparse
import json
import signal
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from formal_disk4.config import load_geometry_config
from formal_disk4.geometry.runner import GeometryRunner
from formal_disk4.geometry.status import SOLUTION_FOUND, read_geometry_status_records
from formal_disk4.orchestration.catalog_diagrams import (
    build_catalog_schematic,
    catalog_schematic_svg,
)
from formal_disk4.pipeline.output import atomic_write_json
from formal_disk4.visualization.assembly import AssemblyError
from formal_disk4.visualization.svg import geometric_solution_svg

from .backtracking_dashboard import BacktrackingDashboardServer
from .evaluator import GraphFormalEvaluator, GraphEvaluation
from .exhaustive_local import atlas_candidates, center_ring_candidates
from .space import DualGraphCandidate, build_dynamic_planar_map


SCHEMA_VERSION = "fixed-graph-backtracking-lab-v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _safe_restart(output: Path) -> None:
    resolved = output.resolve()
    workspace = Path.cwd().resolve()
    if resolved in {workspace, Path(resolved.anchor)} or resolved.parent == resolved:
        raise ValueError(f"Refusing to remove unsafe output path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


def _render_graph(candidate: DualGraphCandidate, destination: Path) -> None:
    planar_map = build_dynamic_planar_map(candidate).planar_map
    svg = catalog_schematic_svg(build_catalog_schematic(planar_map))
    destination.write_text(svg, encoding="utf-8")


def _render_solution(
    source: Path, profile_id: str, destination: Path
) -> bool:
    if not source.exists():
        return False
    with source.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if str(record.get("formal_profile_id", "")) != profile_id:
                continue
            try:
                svg = geometric_solution_svg(
                    record, width=900, height=680, margin=28
                )
            except (AssemblyError, ValueError, KeyError):
                return False
            destination.write_text(svg, encoding="utf-8")
            return True
    return False


class _StatePublisher:
    def __init__(
        self,
        path: Path,
        *,
        graph_index: int,
        graph_count: int,
        candidate: DualGraphCandidate,
        graph_svg: Path,
        started_utc: str,
    ) -> None:
        self.path = path
        self.started = time.perf_counter()
        self.started_unix = time.time()
        self.last_console = 0.0
        self.payload: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "state": "running",
            "phase": "initializing",
            "current_graph_index": graph_index,
            "graph_count": graph_count,
            "current_graph": candidate.to_dict(),
            "current_graph_svg": str(graph_svg),
            "started_utc": started_utc,
            "started_unix": self.started_unix,
            "elapsed_seconds": 0.0,
            "formal_profiles": 0,
            "geometry_attempts": 0,
            "geometry_status": None,
            "solution_graph_id": None,
            "counters": {},
        }
        self.write()

    def update(self, **values: object) -> None:
        self.payload.update(values)
        self.payload["updated_utc"] = _utc_now()
        self.payload["elapsed_seconds"] = time.perf_counter() - self.started
        counters = self.payload.get("counters", {})
        leaves = (
            int(counters.get("joint_arrangement_kernel_calls", 0))
            if isinstance(counters, Mapping)
            else 0
        )
        elapsed = float(self.payload["elapsed_seconds"])
        self.payload["leaves_per_second"] = leaves / elapsed if elapsed else 0.0
        self.write()

    def write(self) -> None:
        atomic_write_json(self.path, self.payload)

    def formal_progress(self, payload: Mapping[str, object]) -> None:
        counters = payload.get("counters", {})
        counters = dict(counters) if isinstance(counters, Mapping) else {}
        self.update(
            phase=str(payload.get("phase", "formal_search")),
            counters=counters,
            formal_profiles=int(payload.get("profiles", 0)),
            search_progress=payload.get("search_progress", {}),
        )
        elapsed = time.perf_counter() - self.started
        if elapsed - self.last_console >= 5.0:
            self.last_console = elapsed
            leaves = int(counters.get("joint_arrangement_kernel_calls", 0))
            nodes = int(counters.get("arrangement_nodes", 0))
            preword = int(counters.get("preword_rejections", 0))
            solver = int(counters.get("solver_cases", 0))
            euclidean_audits = int(
                counters.get("euclidean_placement_audits", 0)
            )
            euclidean_feasible = int(
                counters.get("euclidean_placement_numerically_feasible", 0)
            )
            euclidean_partial_audits = int(
                counters.get("euclidean_partial_audits", 0)
            )
            euclidean_partial_pruned = int(
                counters.get("euclidean_partial_pruned_subtrees", 0)
            )
            print(
                "[PROGRESS] "
                f"elapsed={elapsed:.1f}s nodes={nodes} leaves={leaves} "
                f"rate={leaves / elapsed if elapsed else 0.0:.2f}/s "
                f"preword-reject={preword} solver-cases={solver} "
                f"profiles={int(payload.get('profiles', 0))} "
                f"euclidean={euclidean_feasible}/{euclidean_audits} "
                f"euclidean-pruned={euclidean_partial_pruned}/"
                f"{euclidean_partial_audits}",
                flush=True,
            )
            progress = payload.get("search_progress", {})
            if isinstance(progress, Mapping) and progress.get("engine") == "contact_types":
                charts = [frame for frame in progress.get("branch_path", [])
                          if frame.get("kind") == "chart"]
                branch = " / ".join(f"{f['tile']}:{f['choice']}/{f['choices']}" for f in charts)
                print(f"[CONTACT] charts={branch} "
                      f"incidences={progress.get('assigned_occurrences')}/{progress.get('total_occurrences')} "
                      f"length-rejected={progress.get('linear_rejections')} "
                      f"turn-rejected={progress.get('contact_turn_rejections', 0)} "
                      f"turn-seconds={float(progress.get('contact_turn_seconds', 0)):.2f} "
                      f"word-rejected={counters.get('contact_word_rejections', 0)} "
                      f"word-cache-hits={counters.get('word_cache_hits', 0)} "
                      f"word-splits={progress.get('word_propagation_splits', 0)} "
                      f"sectors={progress.get('word_sector_cases', 0)} "
                      f"levi-cases={progress.get('word_refinement_cases', 0)} "
                      f"levi-closed={progress.get('word_refinement_closed', 0)} "
                      f"word-seconds={float(progress.get('word_propagation_seconds', 0)):.2f} "
                      f"lp-seconds={float(progress.get('linear_seconds', 0)):.2f}", flush=True)


class _GeometryConsumer:
    def __init__(
        self,
        *,
        root: Path,
        candidate: DualGraphCandidate,
        graph_index: int,
        graph_output: Path,
        geometry_config_path: Path,
        publisher: _StatePublisher,
    ) -> None:
        self.root = root
        self.candidate = candidate
        self.graph_index = graph_index
        self.graph_output = graph_output
        self.publisher = publisher
        self.candidates_path = graph_output / "geometry_candidates.jsonl"
        self.geometry_output = graph_output / "geometry"
        self.geometry_output.mkdir(parents=True, exist_ok=True)
        self.solution_svg = graph_output / "solution.svg"
        self.config = load_geometry_config(geometry_config_path)
        self.config["input"]["candidates_file"] = str(self.candidates_path)
        self.config["output"].update(
            {
                "directory": str(self.geometry_output),
                "write_failures": True,
                "include_formal_candidate": True,
            }
        )
        self.config["limits"].update(
            {
                "max_candidates": None,
                "max_solutions": 1,
                "stop_on_first_solution": True,
            }
        )
        # The input JSONL grows one profile at a time.  Persistent status rows,
        # not a completed line cursor, decide which profiles need work.
        self.config["checkpoint"].update(
            {"enabled": False, "resume": False, "restart": False}
        )
        self.attempts = 0
        self.solved_profile_id: str | None = None

    @property
    def status_path(self) -> Path:
        return self.geometry_output / str(
            self.config["output"].get("status_file", "geometry_status.sqlite3")
        )

    @property
    def solutions_path(self) -> Path:
        return self.geometry_output / str(
            self.config["output"].get(
                "solutions_file", "geometric_solutions.jsonl"
            )
        )

    def _geometry_progress(self, payload: Mapping[str, object]) -> None:
        self.publisher.update(
            phase="geometry",
            geometry_attempts=self.attempts,
            geometry_status=str(payload.get("event", "processing")),
            current_formal_profile_id=payload.get("formal_profile_id"),
        )

    def __call__(self, profile: Mapping[str, object]) -> bool:
        profile_id = str(profile.get("formal_profile_id", ""))
        if not profile_id:
            raise ValueError("A geometry-ready profile has no formal_profile_id")
        enriched = dict(profile)
        enriched["graph_lab"] = {
            "generation": self.graph_index,
            "graph_id": self.candidate.graph_id,
            "structural_candidate": self.candidate.to_dict(),
            "campaign": "fixed_graph_backtracking",
        }
        with self.candidates_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(enriched, separators=(",", ":")) + "\n")
            handle.flush()

        self.attempts += 1
        self.publisher.update(
            phase="geometry",
            formal_profiles=self.attempts,
            geometry_attempts=self.attempts,
            geometry_status="queued",
            current_formal_profile_id=profile_id,
        )
        statuses = read_geometry_status_records(self.status_path)
        GeometryRunner(self.config).run(
            skip_profile_ids=set(statuses),
            progress_sink=self._geometry_progress,
        )
        statuses = read_geometry_status_records(self.status_path)
        status = statuses.get(profile_id)
        status_name = status.status if status is not None else "missing_status"
        self.publisher.update(
            phase="formal_search",
            geometry_attempts=self.attempts,
            geometry_status=status_name,
            current_formal_profile_id=None,
        )
        if status is None or status.status != SOLUTION_FOUND:
            return False
        if not _render_solution(self.solutions_path, profile_id, self.solution_svg):
            raise RuntimeError(
                "Geometry reports a solution but its SVG could not be rendered"
            )
        self.solved_profile_id = profile_id
        self.publisher.update(
            state="solution_found",
            phase="complete",
            geometry_status=SOLUTION_FOUND,
            solution_graph_id=self.candidate.graph_id,
            solution_svg=str(self.solution_svg),
        )
        return True


def _candidate_family(name: str, minimum: int, maximum: int):
    if name == "center-ring":
        return center_ring_candidates(minimum, maximum)
    return atlas_candidates(minimum, maximum)


def _proof_gaps(counters: Mapping[str, int]) -> dict[str, int]:
    prefixes = (
        "deferred_word_cases",
        "unsupported_",
        "externally_stopped_word_cases",
        "unexpected_errors",
        "solver_errors",
        "profile_build_errors",
        "profile_emission_errors",
    )
    return {
        key: int(value)
        for key, value in counters.items()
        if value and any(key == prefix or key.startswith(prefix) for prefix in prefixes)
    }


def _evaluation_config(
    formal_config: Path,
    *,
    engine: str = "tile-frontier",
    contact_word_refinement_depth: int = 0,
    contact_word_sectors: bool = False,
    euclidean_audit_samples: int = 0,
    euclidean_audit_restarts: int = 4,
    euclidean_audit_max_nfev: int = 300,
    euclidean_partial_pruning: bool = False,
    euclidean_pruning_restarts: int = 2,
    euclidean_pruning_max_nfev: int = 120,
    euclidean_pruning_minimum_depth: int = 3,
) -> dict[str, object]:
    return {
        "base_search_config": str(formal_config),
        "free_outer_boundary": True,
        "contact_word_refinement_depth": contact_word_refinement_depth,
        "contact_word_sectors": contact_word_sectors,
        "joint_arrangement_search": {
            "enabled": True,
            "strategy": engine.replace("-", "_"),
            "max_nodes": None,
            "time_limit_seconds": None,
            "euclidean_placement_audit": {
                "enabled": euclidean_audit_samples > 0,
                "max_samples": max(0, int(euclidean_audit_samples)),
                "sample_every": 1,
                "restarts": max(1, int(euclidean_audit_restarts)),
                "max_nfev": max(1, int(euclidean_audit_max_nfev)),
                "boundary_mode": "auto",
            },
            "euclidean_partial_pruning": {
                "enabled": bool(euclidean_partial_pruning),
                "restarts": max(1, int(euclidean_pruning_restarts)),
                "max_nfev": max(1, int(euclidean_pruning_max_nfev)),
                "minimum_depth": max(1, int(euclidean_pruning_minimum_depth)),
                "minimum_closed_neighbors": 2,
                "boundary_mode": "auto",
            },
        },
        "mapping_search_overrides": {
            "limits": {
                "max_assignments": None,
                "max_nodes": None,
                "max_placements": None,
                "max_profiles": None,
                "time_limit_seconds": None,
                "stop_on_first_profile": False,
            },
            "solver": {"max_seconds_per_word_case": None},
        },
    }


def run(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    output = Path(args.output_directory)
    if not output.is_absolute():
        output = root / output
    output = output.resolve()
    if args.restart:
        try:
            output.relative_to(root)
        except ValueError as error:
            raise ValueError(
                "--restart output must stay inside the selected workspace root"
            ) from error
        _safe_restart(output)
    output.mkdir(parents=True, exist_ok=True)

    candidates = _candidate_family(
        args.graph_family, args.min_tiles, args.max_tiles
    )
    previous_manifest = _read_json(output / "manifest.json")
    if previous_manifest and previous_manifest.get("engine", "tile-frontier") != args.engine:
        raise ValueError("Different search engine in this output directory; use a new directory or --restart")
    atomic_write_json(
        output / "manifest.json",
        {
            "schema_version": SCHEMA_VERSION,
            "graph_family": args.graph_family,
            "engine": args.engine,
            "contact_word_sectors": args.contact_word_sectors,
            "contact_word_refinement_depth": args.contact_word_refinement_depth,
            "minimum_tiles": args.min_tiles,
            "maximum_tiles": args.max_tiles,
            "unbounded_arrangement_time": True,
            "unbounded_arrangement_nodes": True,
            "graphs": [candidate.to_dict() for candidate in candidates],
        },
    )
    results_path = output / "results.json"
    results_payload = _read_json(results_path)
    results = dict(results_payload.get("graphs", {})) if isinstance(
        results_payload.get("graphs"), Mapping
    ) else {}

    dashboard = None
    if not args.no_dashboard:
        dashboard = BacktrackingDashboardServer(
            output, host=args.host, port=args.port
        )
        dashboard.start(open_browser=not args.no_browser)
        print(f"dashboard: {dashboard.url}", flush=True)

    formal_config = Path(args.formal_config)
    if not formal_config.is_absolute():
        formal_config = root / formal_config
    geometry_config = Path(args.geometry_config)
    if not geometry_config.is_absolute():
        geometry_config = root / geometry_config

    stop_requested = threading.Event()
    previous_sigint = signal.getsignal(signal.SIGINT)

    def request_stop(_signum: int, _frame: object) -> None:
        if stop_requested.is_set():
            # A second Ctrl+C remains an emergency interruption for a kernel
            # call that does not return promptly.  The production solver may
            # catch it to save its compact checkpoint; the outer predicate is
            # already set, so traversal still stops immediately afterwards.
            raise KeyboardInterrupt
        stop_requested.set()
        print(
            "\n[STOP REQUESTED] Fin de la feuille courante puis arrêt propre.",
            flush=True,
        )

    signal.signal(signal.SIGINT, request_stop)

    try:
        for graph_index, candidate in enumerate(candidates, 1):
            previous = results.get(candidate.graph_id)
            if isinstance(previous, Mapping) and (
                previous.get("tree_complete")
                or previous.get("status") == "geometric_solution"
            ):
                print(
                    f"[SKIP] {graph_index}/{len(candidates)} "
                    f"{candidate.graph_id} already complete",
                    flush=True,
                )
                continue
            if previous is not None:
                # An interrupted graph restarts from its deterministic root.
                # Remove the stale row while it is active so the dashboard's
                # completed table cannot present the previous partial attempt
                # as a finished result.
                results.pop(candidate.graph_id, None)
                atomic_write_json(
                    results_path,
                    {
                        "schema_version": SCHEMA_VERSION,
                        "graph_family": args.graph_family,
                        "graphs": results,
                        "updated_utc": _utc_now(),
                    },
                )
            graph_started = time.perf_counter()
            started_utc = _utc_now()
            graph_output = output / f"n{candidate.tile_count:02d}" / candidate.graph_id
            graph_output.mkdir(parents=True, exist_ok=True)
            graph_svg = graph_output / "graph.svg"
            _render_graph(candidate, graph_svg)
            publisher = _StatePublisher(
                output / "status.json",
                graph_index=graph_index,
                graph_count=len(candidates),
                candidate=candidate,
                graph_svg=graph_svg,
                started_utc=started_utc,
            )
            geometry = _GeometryConsumer(
                root=root,
                candidate=candidate,
                graph_index=graph_index,
                graph_output=graph_output,
                geometry_config_path=geometry_config,
                publisher=publisher,
            )
            print(
                f"[GRAPH {graph_index}/{len(candidates)}] "
                f"n={candidate.tile_count} edges={candidate.edge_count} "
                f"id={candidate.graph_id} limits=time:none,nodes:none,leaves:none",
                flush=True,
            )
            evaluator = GraphFormalEvaluator(
                root,
                _evaluation_config(
                    formal_config,
                    engine=args.engine,
                    contact_word_refinement_depth=args.contact_word_refinement_depth,
                    contact_word_sectors=args.contact_word_sectors,
                    euclidean_audit_samples=args.euclidean_audit_samples,
                    euclidean_audit_restarts=args.euclidean_audit_restarts,
                    euclidean_audit_max_nfev=args.euclidean_audit_max_nfev,
                    euclidean_partial_pruning=args.euclidean_partial_pruning,
                    euclidean_pruning_restarts=args.euclidean_pruning_restarts,
                    euclidean_pruning_max_nfev=args.euclidean_pruning_max_nfev,
                    euclidean_pruning_minimum_depth=(
                        args.euclidean_pruning_minimum_depth
                    ),
                ),
            )
            evaluation = evaluator.evaluate_joint_arrangements(
                candidate,
                progress_sink=publisher.formal_progress,
                progress_interval_seconds=1.0,
                profile_consumer=geometry,
                external_stop_predicate=stop_requested.is_set,
            )
            tree_complete = evaluation.stop_reason == "joint_arrangement_exhausted"
            solved = geometry.solved_profile_id is not None
            status = (
                "geometric_solution"
                if solved
                else "tree_exhausted_tainted"
                if tree_complete and evaluation.tainted
                else "tree_exhausted_with_proof_gaps"
                if tree_complete and _proof_gaps(evaluation.counters)
                else "tree_exhausted"
                if tree_complete
                else "incomplete"
            )
            completed_utc = _utc_now()
            result = {
                "schema_version": SCHEMA_VERSION,
                "graph_index": graph_index,
                "graph_count": len(candidates),
                "graph_id": candidate.graph_id,
                "tile_count": candidate.tile_count,
                "edge_count": candidate.edge_count,
                "status": status,
                "tree_complete": tree_complete,
                "stop_reason": evaluation.stop_reason,
                "tainted": evaluation.tainted,
                "error": evaluation.error,
                "started_utc": started_utc,
                "completed_utc": completed_utc,
                "wall_elapsed_seconds": time.perf_counter() - graph_started,
                "arrangement_nodes": int(
                    evaluation.counters.get("arrangement_nodes", 0)
                ),
                "kernel_calls": int(
                    evaluation.counters.get("joint_arrangement_kernel_calls", 0)
                ),
                "formal_profile_count": len(evaluation.profiles),
                "geometry_attempts": geometry.attempts,
                "solution_profile_id": geometry.solved_profile_id,
                "solution_svg": str(geometry.solution_svg) if solved else None,
                "proof_gaps": _proof_gaps(evaluation.counters),
                "counters": dict(evaluation.counters),
            }
            results[candidate.graph_id] = result
            atomic_write_json(
                results_path,
                {
                    "schema_version": SCHEMA_VERSION,
                    "graph_family": args.graph_family,
                    "graphs": results,
                    "updated_utc": completed_utc,
                },
            )
            publisher.update(
                state=status,
                phase="complete",
                counters=dict(evaluation.counters),
                formal_profiles=len(evaluation.profiles),
                geometry_attempts=geometry.attempts,
                geometry_status=(
                    SOLUTION_FOUND
                    if solved
                    else "no_solution_found"
                    if geometry.attempts
                    else "not_attempted"
                ),
                solution_graph_id=(candidate.graph_id if solved else None),
            )
            print(
                f"[GRAPH COMPLETE] n={candidate.tile_count} status={status} "
                f"elapsed={result['wall_elapsed_seconds']:.2f}s "
                f"nodes={result['arrangement_nodes']} leaves={result['kernel_calls']} "
                f"profiles={result['formal_profile_count']} "
                f"geometry={result['geometry_attempts']}",
                flush=True,
            )
            if stop_requested.is_set():
                raise KeyboardInterrupt

        requested_ids = {candidate.graph_id for candidate in candidates}
        completed = sum(
            1
            for graph_id, result in results.items()
            if graph_id in requested_ids
            and isinstance(result, Mapping)
            and (
                bool(result.get("tree_complete"))
                or result.get("status") == "geometric_solution"
            )
        )
        final_status = _read_json(output / "status.json")
        final_status.update(
            {
                "schema_version": SCHEMA_VERSION,
                "state": (
                    "completed"
                    if completed == len(candidates)
                    else "finished_with_incomplete_graphs"
                ),
                "phase": "complete",
                "graph_count": len(candidates),
                "completed_graphs": completed,
                "updated_utc": _utc_now(),
            }
        )
        atomic_write_json(output / "status.json", final_status)
        print(f"campaign complete: {results_path}", flush=True)
        if dashboard is not None and not args.exit_when_complete:
            print("Dashboard conservé ouvert; Ctrl+C pour fermer.", flush=True)
            while not stop_requested.wait(1.0):
                pass
            raise KeyboardInterrupt
    except KeyboardInterrupt:
        status = _read_json(output / "status.json")
        status.update(
            {
                "state": "interrupted",
                "phase": "interrupted",
                "updated_utc": _utc_now(),
                "resume_note": (
                    "Completed graphs are retained. The interrupted graph "
                    "restarts its deterministic backtracking tree."
                ),
            }
        )
        atomic_write_json(output / "status.json", status)
        print("\nBacktracking Lab interrompu.", flush=True)
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        if dashboard is not None:
            dashboard.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("contact-types", "tile-frontier"),
                        default="tile-frontier", help="contact-types: exact incremental contact metric search (V2)")
    parser.add_argument("--root", default=".")
    parser.add_argument("--contact-word-sectors", action="store_true",
                        help="Retain Levi decisions in DFS and terminal lengths, instead of existential lookahead")
    parser.add_argument("--contact-word-refinement-depth", type=int, default=0,
                        help="Optional exact Levi lookahead depth; 0 disables lookahead, not deterministic propagation")
    parser.add_argument(
        "--graph-family", choices=("center-ring", "atlas"), default="center-ring"
    )
    parser.add_argument("--min-tiles", type=int, default=4)
    parser.add_argument("--max-tiles", type=int, default=10)
    parser.add_argument(
        "--formal-config", default="config/local_graph_campaign/formal.json"
    )
    parser.add_argument(
        "--geometry-config", default="config/graph_lab/geometry.json"
    )
    parser.add_argument(
        "--output-directory",
        default="output/backtracking_lab/center-ring-4-10",
    )
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--no-dashboard", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--exit-when-complete", action="store_true")
    parser.add_argument(
        "--euclidean-audit-samples",
        type=int,
        default=0,
        help=(
            "Audit this many complete formal leaves with the non-pruning "
            "Euclidean incidence model (0 disables the experiment)."
        ),
    )
    parser.add_argument("--euclidean-audit-restarts", type=int, default=4)
    parser.add_argument("--euclidean-audit-max-nfev", type=int, default=300)
    parser.add_argument(
        "--euclidean-partial-pruning",
        action="store_true",
        help=(
            "Prune cycle-closing frontier nodes when a bounded Euclidean "
            "placement solve finds no witness. This is heuristic and taints "
            "negative exhaustion."
        ),
    )
    parser.add_argument("--euclidean-pruning-restarts", type=int, default=2)
    parser.add_argument("--euclidean-pruning-max-nfev", type=int, default=120)
    parser.add_argument(
        "--euclidean-pruning-minimum-depth", type=int, default=3
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.contact_word_sectors and (args.engine != "contact-types" or args.contact_word_refinement_depth < 1):
        raise SystemExit("--contact-word-sectors requires contact-types and a positive refinement depth")
    if args.contact_word_refinement_depth < 0:
        raise SystemExit("--contact-word-refinement-depth must be non-negative")
    if args.contact_word_refinement_depth and args.engine != "contact-types":
        raise SystemExit("--contact-word-refinement-depth requires --engine contact-types")
    if args.engine == "contact-types" and args.euclidean_partial_pruning:
        raise SystemExit("--euclidean-partial-pruning is a legacy tile-frontier experiment, not a contact-types constraint")
    if args.min_tiles > args.max_tiles:
        raise SystemExit("--min-tiles must not exceed --max-tiles")
    if args.graph_family == "center-ring" and args.min_tiles < 4:
        raise SystemExit("center-ring needs --min-tiles >= 4")
    if args.euclidean_audit_samples < 0:
        raise SystemExit("--euclidean-audit-samples must be non-negative")
    if args.euclidean_pruning_restarts < 1:
        raise SystemExit("--euclidean-pruning-restarts must be positive")
    if args.euclidean_pruning_max_nfev < 1:
        raise SystemExit("--euclidean-pruning-max-nfev must be positive")
    if args.euclidean_pruning_minimum_depth < 1:
        raise SystemExit("--euclidean-pruning-minimum-depth must be positive")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
