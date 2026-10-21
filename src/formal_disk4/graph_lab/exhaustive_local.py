from __future__ import annotations

"""Incremental, certificate-aware search over small local contact graphs.

This campaign is intentionally separate from the stochastic Graph Lab.  Its
native graph source is NetworkX's complete atlas, hence isomorph-free coverage
is guaranteed only while the dual graph (tiles plus OUTSIDE) has at most seven
vertices.  Within that range every admissible rooted graph is sent to the
production exhaustive solver with a completely free outer boundary.

The word ``certificate`` is used conservatively here.  A negative certificate
is emitted only after the discrete search completed and no word case was
deferred, unsupported, truncated, or lost to an implementation error.  A
numerical geometry failure is never a negative certificate.
"""

import argparse
import csv
import hashlib
import json
import shutil
import time
from datetime import datetime, timezone
from itertools import permutations
from pathlib import Path
from typing import Any, Mapping, Sequence

import networkx as nx

from formal_disk4.config import load_config, load_geometry_config
from formal_disk4.geometry.runner import GeometryRunner
from formal_disk4.geometry.status import read_geometry_status_records
from formal_disk4.pipeline.checkpoint import search_fingerprint
from formal_disk4.pipeline.output import atomic_replace, atomic_write_json
from formal_disk4.pipeline.runner import SolverRunner
from formal_disk4.visualization.assembly import AssemblyError
from formal_disk4.visualization.svg import geometric_solution_svg

from .free_outer_boundary import relax_outer_boundary
from .space import (
    OUTSIDE,
    DualGraphCandidate,
    build_dynamic_planar_map,
    validate_dual_graph,
)


SCHEMA_VERSION = "local-contact-graph-campaign-v2"
NATIVE_MAXIMUM_TILES = 6
GRAPH_FAMILIES = ("atlas", "center-ring")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rooted_canonical_edges(
    graph: nx.Graph, outside_vertex: int
) -> tuple[tuple[int, int], ...]:
    """Exact canonical labelling for the tiny rooted atlas graphs.

    At most six tile vertices are permuted, so the deliberately simple
    factorial canonicalizer performs no more than 720 labellings.  This is
    easier to audit than a probabilistic graph hash and makes OUTSIDE-rooted
    isomorphism removal exact.
    """

    tiles = tuple(node for node in graph if node != outside_vertex)
    best: tuple[tuple[int, int], ...] | None = None
    for order in permutations(tiles):
        labels = {outside_vertex: OUTSIDE}
        labels.update({node: index for index, node in enumerate(order)})
        edges = tuple(
            sorted(
                (min(labels[left], labels[right]), max(labels[left], labels[right]))
                for left, right in graph.edges()
            )
        )
        if best is None or edges < best:
            best = edges
    if best is None:
        raise ValueError("A rooted contact graph must contain at least one edge")
    return best


def atlas_candidates(
    minimum_tiles: int = 3, maximum_tiles: int = NATIVE_MAXIMUM_TILES
) -> tuple[DualGraphCandidate, ...]:
    """Return every admissible rooted planar graph in the native exact range.

    The unrooted atlas is isomorph-free.  Rooting every vertex accounts for
    every possible choice of the exterior cell; exact canonical labelling then
    removes roots related by an automorphism.  Three-connectivity implies the
    requested degree-at-least-three condition (including OUTSIDE) and gives a
    unique spherical embedding up to reflection.
    """

    minimum = int(minimum_tiles)
    maximum = int(maximum_tiles)
    if minimum < 3 or maximum < minimum:
        raise ValueError("Expected 3 <= minimum_tiles <= maximum_tiles")
    if maximum > NATIVE_MAXIMUM_TILES:
        raise ValueError(
            "The native isomorph-free atlas is exhaustive only through 6 tiles "
            "(7 dual vertices including OUTSIDE). Use --max-tiles 6; extending "
            "the campaign requires an audited plantri/nauty graph source."
        )

    output: list[DualGraphCandidate] = []
    globally_seen: set[tuple[int, tuple[tuple[int, int], ...]]] = set()
    for graph in nx.graph_atlas_g():
        tile_count = graph.number_of_nodes() - 1
        if not minimum <= tile_count <= maximum:
            continue
        if not nx.is_connected(graph):
            continue
        if nx.node_connectivity(graph) < 3:
            continue
        planar, _embedding = nx.check_planarity(graph, counterexample=False)
        if not planar:
            continue

        for outside_vertex in graph.nodes():
            edges = _rooted_canonical_edges(graph, outside_vertex)
            key = (tile_count, edges)
            if key in globally_seen:
                continue
            globally_seen.add(key)
            candidate = DualGraphCandidate(
                tile_count=tile_count,
                edges=edges,
                imposed_permutation=None,
                origin="networkx_graph_atlas",
                mutation="exact_rooted_enumeration",
            )
            validate_dual_graph(candidate.graph(), maximum_tiles=tile_count)
            output.append(candidate)

    return tuple(
        sorted(output, key=lambda item: (item.tile_count, item.edge_count, item.edges))
    )


def center_ring_candidates(
    minimum_tiles: int = 4, maximum_tiles: int = 10
) -> tuple[DualGraphCandidate, ...]:
    """Return the wheel-like reference family with a free outer boundary.

    Tile 0 is central.  Tiles 1..n-1 form a cycle; every cycle tile touches
    both the center and OUTSIDE.  Thus the dual graph records exactly one
    central tile surrounded by a contact ring.  No rotational symmetry is
    imposed on the mapping or prototype: graph automorphisms are used only by
    the ordinary sound quotienting machinery.
    """

    minimum = int(minimum_tiles)
    maximum = int(maximum_tiles)
    if minimum < 4 or maximum < minimum:
        raise ValueError(
            "The center-ring family expects 4 <= minimum_tiles <= maximum_tiles"
        )

    output: list[DualGraphCandidate] = []
    for tile_count in range(minimum, maximum + 1):
        ring = tuple(range(1, tile_count))
        edges: set[tuple[int, int]] = set()
        for index, tile in enumerate(ring):
            following = ring[(index + 1) % len(ring)]
            edges.add((OUTSIDE, tile))
            edges.add((0, tile))
            edges.add((min(tile, following), max(tile, following)))
        candidate = DualGraphCandidate(
            tile_count=tile_count,
            edges=tuple(sorted(edges)),
            imposed_permutation=None,
            origin="center_ring_reference_family",
            mutation="exact_family_construction",
        )
        validate_dual_graph(candidate.graph(), maximum_tiles=tile_count)
        output.append(candidate)
    return tuple(output)


def _candidate_digest(candidate: DualGraphCandidate) -> str:
    encoded = json.dumps(
        candidate.to_dict(), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return dict(payload) if isinstance(payload, Mapping) else {}


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return sum(1 for line in handle if line.strip())


def _formal_config(
    source: Path,
    *,
    planar_map_name: str,
    output: Path,
    word_seconds: float | None = None,
    graph_seconds: float | None = None,
    track_exact_domain_size: bool = True,
) -> dict[str, Any]:
    config = load_config(source)
    config["maps"] = [planar_map_name]
    enumeration = config["enumeration"]
    enumeration.update(
        {
            "allow_reflections": True,
            "symmetry_mode": "incremental",
            "track_exact_domain_size": bool(track_exact_domain_size),
        }
    )
    for name in (
        "cyclic_equivariance",
        "cyclic_shift_equivariance",
        "dihedral_equivariance",
        "mapping_subdomain",
        "joint_weak_length",
    ):
        enumeration.setdefault(name, {})["enabled"] = False

    # This campaign replaces every physical outer-circle interface by a free
    # boundary.  Consequently no atomic curve is forced to be a radius-R arc.
    # The local radius/turn variables can all be zero, while the disk-wide
    # radius, total-turn, concavity and isoperimetric identities are inapplicable
    # (see docs/ARCHITECTURE.md, section 6.2).  Keep those vacuous blocks disabled
    # here only; the ordinary closed-disk configurations retain them.  The exact
    # strictly-positive interface-length system below remains necessary.
    linear_invariants = config["filters"]["preword_pruning"]["linear_invariants"]
    linear_invariants["enable_radius_measures"] = False
    linear_invariants["enable_smooth_turns"] = False

    config["limits"].update(
        {
            "max_assignments": None,
            "max_nodes": None,
            "max_placements": None,
            "max_profiles": None,
            "time_limit_seconds": (
                None if graph_seconds is None else float(graph_seconds)
            ),
            # Geometry is attempted immediately. If it fails, the compact
            # checkpoint resumes the exhaustive formal traversal.
            "stop_on_first_profile": True,
        }
    )
    # Keep the structural/resource guardrails from the campaign config. In
    # particular max_terminal_contour_segments deliberately leaves very large
    # symbolic/nested word systems unresolved rather than spending an
    # unbounded amount of time on them. Any such cutoff is a proof gap, never
    # an UNSAT certificate.
    config["solver"]["max_seconds_per_word_case"] = (
        None if word_seconds is None else float(word_seconds)
    )
    # A finite family has an empty exponent set and is always specialized.
    # For a symbolic family, its minimum member is useful as a witness attempt,
    # but the campaign records the unexpanded remainder as a proof blocker.
    config["solver"]["family_expansion"].update(
        {
            "policy": "minimum",
            "max_specializations_per_family": None,
        }
    )
    config["output"].update(
        {
            "directory": str(output),
            "write_candidates": True,
            # Counts and exact statuses live in run_summary.json. Dumping every
            # family can grow without bound and is not needed for a certificate.
            "write_families": False,
            "write_unsupported": True,
            "write_word_cases": False,
            "write_deferred_word_cases": True,
            "write_placements": False,
            "write_errors": True,
            "max_family_records": 0,
            "max_unsupported_records": 1000,
            "max_deferred_word_case_records": 1000,
        }
    )
    config["checkpoint"].update(
        {
            "enabled": True,
            "resume": True,
            "restart": False,
            "interval_seconds": 30.0,
        }
    )
    config["progress"].update(
        {
            "enabled": True,
            "interval_seconds": 5.0,
            "heartbeat_enabled": True,
            "heartbeat_interval_seconds": 30.0,
        }
    )
    return config


def _geometry_config(source: Path, *, candidates: Path, output: Path) -> dict[str, Any]:
    config = load_geometry_config(source)
    config["input"]["candidates_file"] = str(candidates)
    config["output"].update(
        {
            "directory": str(output),
            "write_failures": True,
            "include_formal_candidate": True,
        }
    )
    config["limits"].update(
        {
            "max_candidates": None,
            "max_solutions": 1,
            "stop_on_first_solution": True,
        }
    )
    config["checkpoint"].update(
        {"enabled": True, "resume": True, "restart": False}
    )
    return config


_PROOF_BLOCKER_COUNTERS = (
    "deferred_word_cases",
    "deferred_word_cases_wall_time_budget",
    "deferred_word_cases_residual_literal_budget",
    "deferred_word_cases_residual_graph_budget",
    "deferred_word_cases_residual_expression_budget",
    "deferred_word_cases_family_budget",
    "deferred_word_cases_terminal_contour_budget",
    "externally_stopped_word_cases",
    "graph_limited_word_cases",
    "residual_literal_limited_word_cases",
    "family_limited_word_cases",
    "terminal_contour_limited_word_cases",
    "unsupported_complex_components",
    "unsupported_language_word_cases",
    # Only the minimum exponent is geometrically specialized. A symbolic
    # family therefore proves formal support, not exhaustion of all members.
    "word_family_power",
    "word_family_nested_power",
    "families_not_specialized",
    "solver_errors",
    "profile_build_errors",
    "profile_emission_errors",
    "unexpected_errors",
)


def proof_blockers(summary: Mapping[str, object]) -> dict[str, int]:
    statistics = summary.get("statistics", {})
    counters = (
        statistics.get("counters", {})
        if isinstance(statistics, Mapping)
        else {}
    )
    if not isinstance(counters, Mapping):
        return {"malformed_statistics": 1}
    return {
        name: int(counters.get(name, 0))
        for name in _PROOF_BLOCKER_COUNTERS
        if int(counters.get(name, 0)) > 0
    }


def classify_completed_formal_search(
    summary: Mapping[str, object], *, formal_profile_count: int
) -> tuple[str, dict[str, int]]:
    statistics = summary.get("statistics", {})
    stop_reason = (
        str(statistics.get("stop_reason", "unknown"))
        if isinstance(statistics, Mapping)
        else "unknown"
    )
    blockers = proof_blockers(summary)
    if stop_reason not in {"completed", "already_completed"}:
        blockers[f"stop_reason:{stop_reason}"] = 1
        return "incomplete", blockers
    if formal_profile_count:
        return "formal_exhausted_geometry_open", blockers
    if blockers:
        return "formal_exhausted_with_proof_gaps", blockers
    return "formal_unsat_certified", {}


def _render_first_assembly(solutions: Path, destination: Path) -> tuple[Path | None, list[str]]:
    failures: list[str] = []
    if not solutions.exists():
        return None, failures
    with solutions.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            try:
                svg = geometric_solution_svg(record, width=900, height=680, margin=28)
            except (AssemblyError, ValueError, KeyError) as error:
                failures.append(f"line {line_number}: {type(error).__name__}: {error}")
                continue
            destination.write_text(svg, encoding="utf-8")
            return destination, failures
    return None, failures


def _write_manifest(path: Path, candidates: Sequence[DualGraphCandidate]) -> None:
    atomic_write_json(
        path,
        {
            "schema_version": SCHEMA_VERSION,
            "graph_source": {
                "kind": "networkx_graph_atlas",
                "isomorph_free": True,
                "rooted_outside_choices_complete": True,
                "maximum_tiles": NATIVE_MAXIMUM_TILES,
            },
            "constraints": {
                "simple": True,
                "planar": True,
                "connected": True,
                "vertex_connectivity": 3,
                "minimum_tile_degree_counting_outside": 3,
                "imposed_symmetry": None,
                "outer_boundary": "free",
            },
            "graph_count": len(candidates),
            "graphs": [candidate.to_dict() for candidate in candidates],
        },
    )


def _write_timing_csv(path: Path, results: Mapping[str, object]) -> None:
    rows = []
    for graph_id, raw in results.items():
        if not isinstance(raw, Mapping):
            continue
        rows.append(
            {
                "tile_count": raw.get("tile_count"),
                "graph_index": raw.get("graph_index"),
                "graph_id": graph_id,
                "edge_count": raw.get("edge_count"),
                "status": raw.get("status"),
                "formal_elapsed_seconds": raw.get("formal_elapsed_seconds"),
                "geometry_elapsed_seconds": raw.get("geometry_elapsed_seconds"),
                "wall_elapsed_seconds": raw.get("wall_elapsed_seconds"),
                "formal_profile_count": raw.get("formal_profile_count"),
            }
        )
    rows.sort(key=lambda row: (int(row["tile_count"]), int(row["graph_index"])))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(rows[0]) if rows else (
            "tile_count", "graph_index", "graph_id", "edge_count", "status",
            "formal_elapsed_seconds", "geometry_elapsed_seconds",
            "wall_elapsed_seconds", "formal_profile_count",
        ))
        writer.writeheader()
        writer.writerows(rows)
    atomic_replace(temporary, path)


def _edge_signature(raw: Mapping[str, object]) -> str:
    edges = raw.get("edges", ())
    if not isinstance(edges, Sequence) or isinstance(edges, (str, bytes)):
        return "?"
    rendered = []
    for edge in edges:
        if not isinstance(edge, Sequence) or len(edge) != 2:
            continue
        rendered.append(f"{edge[0]}-{edge[1]}")
    return ",".join(rendered) or "?"


def _print_result_table(results: Mapping[str, object]) -> None:
    """Print the compact, human-readable timing/status survey."""

    rows = [
        raw
        for raw in results.values()
        if isinstance(raw, Mapping)
    ]
    rows.sort(
        key=lambda raw: (
            int(raw.get("tile_count", 0)),
            int(raw.get("graph_index", 0)),
        )
    )
    print(
        "idx  n  e  formal(s) geometry(s) profiles status / blockers",
        flush=True,
    )
    for raw in rows:
        blockers = raw.get("proof_blockers", {})
        blocker_text = ""
        if isinstance(blockers, Mapping) and blockers:
            blocker_text = " / " + ",".join(
                f"{name}={value}" for name, value in sorted(blockers.items())
            )
        print(
            f"{int(raw.get('graph_index', 0)):>3} "
            f"{int(raw.get('tile_count', 0)):>2} "
            f"{int(raw.get('edge_count', 0)):>2} "
            f"{float(raw.get('formal_elapsed_seconds', 0.0)):>9.2f} "
            f"{float(raw.get('geometry_elapsed_seconds', 0.0)):>11.2f} "
            f"{int(raw.get('formal_profile_count', 0)):>8} "
            f"{raw.get('status', 'unknown')}{blocker_text}",
            flush=True,
        )
        print(f"     edges: {_edge_signature(raw)}", flush=True)
        work = raw.get("formal_work", {})
        if isinstance(work, Mapping) and work:
            print(
                "     work: "
                f"placements={int(work.get('placement_nodes', 0))} "
                f"survivors={int(work.get('surviving_placements', 0))} "
                f"word_cases={int(work.get('solver_cases', 0))} "
                f"residual_nodes={int(work.get('residual_graph_nodes', 0))} "
                f"deferred={int(work.get('deferred_word_cases', 0))} "
                f"word_share={float(work.get('word_solver_time_share_percent', 0.0)):.1f}%",
                flush=True,
            )


def _safe_restart(output: Path) -> None:
    resolved = output.resolve()
    cwd = Path.cwd().resolve()
    if (
        resolved == cwd
        or resolved == Path(resolved.anchor)
        or resolved.parent == resolved
    ):
        raise ValueError(f"Refusing to recursively remove unsafe output path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


def _terminal_status(status: str) -> bool:
    return status in {
        "geometric_solution",
        "formal_unsat_certified",
        "formal_exhausted_geometry_open",
        "formal_exhausted_with_proof_gaps",
    }


def _run_one_graph(
    candidate: DualGraphCandidate,
    *,
    graph_index: int,
    graph_count: int,
    output: Path,
    formal_config_path: Path,
    geometry_config_path: Path,
    word_seconds: float | None,
    graph_seconds: float | None,
    track_exact_domain_size: bool,
) -> dict[str, object]:
    graph_started = time.perf_counter()
    graph_deadline = (
        None
        if graph_seconds is None
        else graph_started + max(0.0, float(graph_seconds))
    )
    # Graph identity, not its position in one requested range, owns the
    # checkpoint. Widening a resumed range therefore keeps prior work valid.
    graph_output = output / f"n{candidate.tile_count:02d}" / candidate.graph_id
    graph_output.mkdir(parents=True, exist_ok=True)
    atomic_write_json(graph_output / "graph.json", candidate.to_dict())

    dynamic = relax_outer_boundary(build_dynamic_planar_map(candidate))
    formal_output = graph_output / "formal"
    geometry_output = graph_output / "geometry"
    formal_config = _formal_config(
        formal_config_path,
        planar_map_name=dynamic.planar_map.name,
        output=formal_output,
        word_seconds=word_seconds,
        graph_seconds=graph_seconds,
        track_exact_domain_size=track_exact_domain_size,
    )
    geometry_config = _geometry_config(
        geometry_config_path,
        candidates=formal_output / "candidates.jsonl",
        output=geometry_output,
    )
    fingerprint = search_fingerprint(
        formal_config, planar_maps=(dynamic.planar_map,)
    )
    print(
        f"[GRAPH {graph_index}/{graph_count}] n={candidate.tile_count} "
        f"edges={candidate.edge_count} id={candidate.graph_id}",
        flush=True,
    )

    latest_summary: Mapping[str, object] = {}
    geometry_elapsed = 0.0
    assembly_failures: list[str] = []
    while True:
        if graph_deadline is not None:
            remaining_seconds = max(0.0, graph_deadline - time.perf_counter())
            formal_config["limits"]["time_limit_seconds"] = remaining_seconds
            if remaining_seconds <= 0.0:
                latest_summary = _read_json(formal_output / "run_summary.json")
                status = "incomplete"
                blockers = {"stop_reason:graph_time_slice": 1}
                break
        latest_summary = SolverRunner(
            formal_config, planar_maps=(dynamic.planar_map,)
        ).run()
        candidates_path = formal_output / "candidates.jsonl"
        formal_profile_count = _count_jsonl(candidates_path)

        svg_path, failures = _render_first_assembly(
            geometry_output / "geometric_solutions.jsonl",
            graph_output / "solution.svg",
        )
        assembly_failures.extend(failures)
        if svg_path is None and formal_profile_count:
            existing = read_geometry_status_records(
                geometry_output / "geometry_status.sqlite3"
            )
            attempted = {
                profile_id
                for profile_id, status in existing.items()
                if status.status != "solution_found"
            }
            geometry_started = time.perf_counter()
            GeometryRunner(geometry_config).run(skip_profile_ids=attempted)
            geometry_elapsed += time.perf_counter() - geometry_started
            svg_path, failures = _render_first_assembly(
                geometry_output / "geometric_solutions.jsonl",
                graph_output / "solution.svg",
            )
            assembly_failures.extend(failures)

        if svg_path is not None:
            status = "geometric_solution"
            blockers: dict[str, int] = {}
            break

        statistics = latest_summary.get("statistics", {})
        stop_reason = (
            str(statistics.get("stop_reason", "unknown"))
            if isinstance(statistics, Mapping)
            else "unknown"
        )
        if stop_reason == "first_profile":
            # The checkpoint's survivor table prevents duplicate output. On the
            # next pass the exhaustive cursor resumes; if its safe checkpoint
            # precedes the survivor, that duplicate is ignored and traversal
            # advances normally.
            if graph_deadline is None or time.perf_counter() < graph_deadline:
                continue
            status = "incomplete"
            blockers = {"stop_reason:graph_time_slice": 1}
            break
        status, blockers = classify_completed_formal_search(
            latest_summary, formal_profile_count=formal_profile_count
        )
        break

    statistics = latest_summary.get("statistics", {})
    formal_elapsed = (
        float(statistics.get("elapsed_seconds", 0.0))
        if isinstance(statistics, Mapping)
        else 0.0
    )
    formal_profile_count = _count_jsonl(formal_output / "candidates.jsonl")
    counters = (
        statistics.get("counters", {})
        if isinstance(statistics, Mapping)
        else {}
    )
    timing_shares = (
        statistics.get("timing_share_of_elapsed_percent", {})
        if isinstance(statistics, Mapping)
        else {}
    )
    if not isinstance(counters, Mapping):
        counters = {}
    if not isinstance(timing_shares, Mapping):
        timing_shares = {}
    result: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "graph_index": graph_index,
        "graph_count": graph_count,
        "graph_id": candidate.graph_id,
        "candidate_sha256": _candidate_digest(candidate),
        "tile_count": candidate.tile_count,
        "edge_count": candidate.edge_count,
        "edges": [list(edge) for edge in candidate.edges],
        "status": status,
        "proof_blockers": blockers,
        "search_fingerprint": fingerprint,
        "formal_profile_count": formal_profile_count,
        "formal_work": {
            "assignments_processed": int(counters.get("assignments_processed", 0)),
            "placement_nodes": int(counters.get("placement_nodes", 0)),
            "surviving_placements": int(counters.get("surviving_placements", 0)),
            "solver_cases": int(counters.get("solver_cases", 0)),
            "residual_graph_nodes": int(counters.get("residual_graph_nodes", 0)),
            "residual_graph_edges": int(counters.get("residual_graph_edges", 0)),
            "deferred_word_cases": int(counters.get("deferred_word_cases", 0)),
            "word_solver_time_share_percent": float(
                timing_shares.get("exact_partial_word_solver", 0.0)
            ),
        },
        "formal_elapsed_seconds": formal_elapsed,
        "geometry_elapsed_seconds": geometry_elapsed,
        "wall_elapsed_seconds": time.perf_counter() - graph_started,
        "assembly_failures": assembly_failures,
        "paths": {
            "graph": str(graph_output / "graph.json"),
            "formal_summary": str(formal_output / "run_summary.json"),
            "formal_candidates": str(formal_output / "candidates.jsonl"),
            "geometry_summary": str(geometry_output / "geometry_summary.json"),
            "solution_svg": (
                str(graph_output / "solution.svg")
                if (graph_output / "solution.svg").exists()
                else None
            ),
        },
        "completed_utc": _utc_now(),
    }
    atomic_write_json(graph_output / "result.json", result)

    certificate_path = graph_output / "formal_unsat_certificate.json"
    if status == "formal_unsat_certified":
        atomic_write_json(
            certificate_path,
            {
                "schema_version": "formal-search-exhaustion-certificate-v1",
                "claim": (
                    "No formal contour profile exists for this rooted contact "
                    "graph under the recorded solver model and hypotheses."
                ),
                "scope_warning": (
                    "This is an auditable exhaustion record, not an independently "
                    "checked mathematical proof and not a claim beyond the formal "
                    "model implemented by this solver."
                ),
                "graph": candidate.to_dict(),
                "candidate_sha256": _candidate_digest(candidate),
                "search_fingerprint": fingerprint,
                "formal_summary": str(formal_output / "run_summary.json"),
                "proof_blockers": {},
                "issued_utc": _utc_now(),
            },
        )
    elif certificate_path.exists():
        certificate_path.unlink()

    print(
        f"[GRAPH COMPLETE] {graph_index}/{graph_count} id={candidate.graph_id} "
        f"status={status} formal={formal_elapsed:.2f}s "
        f"geometry={geometry_elapsed:.2f}s profiles={formal_profile_count}",
        flush=True,
    )
    return result


def run(args: argparse.Namespace) -> int:
    output = Path(args.output_directory).resolve()
    if args.restart:
        _safe_restart(output)
    output.mkdir(parents=True, exist_ok=True)

    if args.graph_family == "atlas":
        candidates = atlas_candidates(args.min_tiles, args.max_tiles)
        catalog_label = "exact rooted graphs"
    else:
        candidates = center_ring_candidates(args.min_tiles, args.max_tiles)
        catalog_label = "center-ring reference graphs"
    _write_manifest(output / "graph_manifest.json", candidates)
    counts: dict[int, int] = {}
    for candidate in candidates:
        counts[candidate.tile_count] = counts.get(candidate.tile_count, 0) + 1
    print(
        f"[CATALOG] {catalog_label}: "
        + ", ".join(f"n={size}: {count}" for size, count in sorted(counts.items())),
        flush=True,
    )
    if args.catalog_only:
        print(f"Manifest: {output / 'graph_manifest.json'}", flush=True)
        return 0

    results_path = output / "results.json"
    stored = _read_json(results_path)
    results = dict(stored.get("graphs", {})) if isinstance(stored.get("graphs"), Mapping) else {}
    if args.report_only:
        _print_result_table(results)
        print(f"CSV: {output / 'timings.csv'}", flush=True)
        return 0
    formal_config = Path(args.formal_config).resolve()
    geometry_config = Path(args.geometry_config).resolve()

    for graph_index, candidate in enumerate(candidates, 1):
        previous = results.get(candidate.graph_id)
        if isinstance(previous, Mapping) and _terminal_status(str(previous.get("status"))):
            print(
                f"[SKIP] {graph_index}/{len(candidates)} {candidate.graph_id} "
                f"status={previous.get('status')}",
                flush=True,
            )
            continue
        atomic_write_json(
            output / "status.json",
            {
                "schema_version": SCHEMA_VERSION,
                "state": "running",
                "current_graph_index": graph_index,
                "graph_count": len(candidates),
                "current_graph": candidate.to_dict(),
                "updated_utc": _utc_now(),
            },
        )
        result = _run_one_graph(
            candidate,
            graph_index=graph_index,
            graph_count=len(candidates),
            output=output,
            formal_config_path=formal_config,
            geometry_config_path=geometry_config,
            word_seconds=args.word_seconds,
            graph_seconds=args.graph_seconds,
            # Exact weak-order-domain cardinality is useful for the tiny atlas
            # but is only a progress statistic.  On center-ring graphs its
            # combinatorial count dominates the actual search from eight tiles
            # onward, so omit it without changing a single explored candidate.
            track_exact_domain_size=args.graph_family == "atlas",
        )
        results[candidate.graph_id] = result
        atomic_write_json(
            results_path,
            {
                "schema_version": SCHEMA_VERSION,
                "requested_graph_source_complete": True,
                "graph_count": len(candidates),
                "graphs": results,
                "updated_utc": _utc_now(),
            },
        )
        _write_timing_csv(output / "timings.csv", results)
        # A finite per-graph survey is meant to expose scaling across the
        # catalog, so an inconclusive graph must not hide all later graphs.
        # Re-running the command resumes every incomplete checkpoint and gives
        # it another graph_seconds slice.

    requested_ids = {candidate.graph_id for candidate in candidates}
    completed = sum(
        1
        for graph_id, value in results.items()
        if graph_id in requested_ids
        and isinstance(value, Mapping)
        and _terminal_status(str(value.get("status")))
    )
    atomic_write_json(
        output / "status.json",
        {
            "schema_version": SCHEMA_VERSION,
            "state": "completed" if completed == len(candidates) else "paused",
            "completed_graphs": completed,
            "graph_count": len(candidates),
            "updated_utc": _utc_now(),
        },
    )
    print("\n[RESULT TABLE]", flush=True)
    _print_result_table(results)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--graph-family",
        choices=GRAPH_FAMILIES,
        default="atlas",
        help="graph source: exhaustive rooted atlas or the center-plus-ring reference family",
    )
    parser.add_argument("--min-tiles", type=int, default=3)
    parser.add_argument("--max-tiles", type=int, default=NATIVE_MAXIMUM_TILES)
    parser.add_argument(
        "--formal-config",
        default="config/local_graph_campaign/formal.json",
    )
    parser.add_argument(
        "--geometry-config",
        default="config/graph_lab/geometry.json",
    )
    parser.add_argument(
        "--output-directory",
        default="output/local_graph_campaign/atlas-3-6",
    )
    parser.add_argument("--catalog-only", action="store_true")
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="print the existing per-graph timing/status table without solving",
    )
    parser.add_argument(
        "--word-seconds",
        type=float,
        default=None,
        help=(
            "optional budget per word case; useful for a survey, but every "
            "deferred case blocks a negative certificate"
        ),
    )
    parser.add_argument(
        "--graph-seconds",
        type=float,
        default=None,
        help=(
            "optional wall-clock slice per graph and invocation; incomplete "
            "checkpoints resume on the next invocation"
        ),
    )
    parser.add_argument("--restart", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
