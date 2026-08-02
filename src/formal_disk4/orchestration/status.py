from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from formal_disk4.geometry.status import GeometryStatusCounts, read_geometry_status
from formal_disk4.orchestration.catalog import CaseDefinition
from formal_disk4.pipeline.checkpoint import CHECKPOINT_SCHEMA_VERSION


@dataclass(frozen=True)
class CasePipelineStatus:
    search_state: str
    geometry_state: str
    formal_candidates: int
    geometry_considered: int
    rejected_certain: int
    solutions_found: int
    no_solution_found: int
    exact_geometry_counts: bool


@dataclass(frozen=True)
class SearchDiagnosticStage:
    """One readable line in the search rejection report.

    ``examined`` is deliberately optional: DFS node-pruning counters do not
    share a leaf-candidate denominator, so inventing a percentage for them
    would be misleading.
    """

    label: str
    examined: int | None
    rejected_or_result: int
    rate_percent: float | None
    details: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class SearchDiagnostics:
    source: str
    updated_utc: str | None
    completed: bool
    elapsed_seconds: float
    stages: tuple[SearchDiagnosticStage, ...]
    counters: tuple[tuple[str, int], ...]
    timings: tuple[tuple[str, float], ...]


class PipelineStatusReader:
    """Read concise case status directly from solver outputs and checkpoints."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()
        self._line_count_cache: dict[Path, tuple[int, int, int]] = {}
        self._solution_cache: dict[Path, tuple[int, int, int, int]] = {}

    def read(self, case: CaseDefinition) -> CasePipelineStatus:
        output = self.root / case.output_directory
        search_state, formal = self._read_search(output)
        geometry_state, counts, exact = self._read_geometry(output, formal, search_state)
        return CasePipelineStatus(
            search_state=search_state,
            geometry_state=geometry_state,
            formal_candidates=formal,
            geometry_considered=counts.considered,
            rejected_certain=counts.rejected_certain,
            solutions_found=counts.solution_found,
            no_solution_found=counts.no_solution_found,
            exact_geometry_counts=exact,
        )

    def read_search_diagnostics(
        self, case: CaseDefinition
    ) -> SearchDiagnostics | None:
        """Read cumulative diagnostics without disturbing an active solver.

        A running or paused checkpoint is authoritative.  Once the checkpoint
        is complete, ``run_summary.json`` is preferred because it contains the
        final timings as well as the final counters.
        """

        output = self.root / case.output_directory
        active = _active_task(output / ".active-search-pipeline-task.json")
        checkpoint = self._read_checkpoint_diagnostics(
            output / "checkpoint.sqlite3"
        )
        if active:
            # A previous run_summary may still be present while a fresh run is
            # starting. Never present that stale result as live diagnostics.
            return checkpoint
        if checkpoint is not None and not checkpoint.completed:
            return checkpoint

        summary = self._read_summary_diagnostics(output / "run_summary.json")
        if summary is not None:
            return summary
        return checkpoint

    @staticmethod
    def _read_checkpoint_diagnostics(path: Path) -> SearchDiagnostics | None:
        if not path.exists():
            return None
        try:
            connection = sqlite3.connect(str(path), timeout=0.25)
            try:
                row = connection.execute(
                    "SELECT schema_version, updated_utc, completed, stats_json "
                    "FROM search_checkpoint WHERE singleton = 1"
                ).fetchone()
            finally:
                connection.close()
        except (sqlite3.Error, OSError):
            return None
        if row is None or int(row[0]) != CHECKPOINT_SCHEMA_VERSION:
            return None
        try:
            statistics = json.loads(str(row[3]))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return _make_search_diagnostics(
            statistics,
            source="checkpoint",
            updated_utc=str(row[1]) or None,
            completed=bool(row[2]),
        )

    @staticmethod
    def _read_summary_diagnostics(path: Path) -> SearchDiagnostics | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        statistics = payload.get("statistics")
        if not isinstance(statistics, dict):
            return None
        try:
            updated_utc = datetime.fromtimestamp(
                path.stat().st_mtime, timezone.utc
            ).isoformat()
        except OSError:
            updated_utc = None
        return _make_search_diagnostics(
            statistics,
            source="final run summary",
            updated_utc=updated_utc,
            completed=True,
        )

    def _read_search(self, output: Path) -> tuple[str, int]:
        deferred = self._count_jsonl(output / "deferred_word_cases.jsonl")

        def with_deferred(state: str) -> str:
            if not deferred:
                return state
            suffix = "case" if deferred == 1 else "cases"
            return f"{state}; {deferred} word {suffix} deferred"

        active = _active_task(output / ".active-search-pipeline-task.json")
        checkpoint = output / "checkpoint.sqlite3"
        if checkpoint.exists():
            try:
                connection = sqlite3.connect(str(checkpoint), timeout=0.25)
                try:
                    row = connection.execute(
                        "SELECT schema_version, completed FROM search_checkpoint "
                        "WHERE singleton = 1"
                    ).fetchone()
                    count_row = connection.execute(
                        "SELECT COUNT(*) FROM survivors"
                    ).fetchone()
                finally:
                    connection.close()
            except (sqlite3.Error, OSError):
                row = None
                count_row = None
            if count_row is not None:
                formal = int(count_row[0])
            else:
                formal = self._count_jsonl(output / "candidates.jsonl")
            if active:
                return with_deferred("running"), formal
            if row is None:
                return with_deferred("checkpoint error"), formal
            schema_version, completed = row
            if int(schema_version) != CHECKPOINT_SCHEMA_VERSION:
                return with_deferred("incompatible"), formal
            return with_deferred(
                "complete" if bool(completed) else "paused"
            ), formal

        formal = self._count_jsonl(output / "candidates.jsonl")
        if active:
            return with_deferred("running"), formal
        if formal:
            return with_deferred("results only"), formal
        return with_deferred("not started"), 0

    def _read_geometry(
        self,
        output: Path,
        formal: int,
        search_state: str,
    ) -> tuple[str, GeometryStatusCounts, bool]:
        geometry = output / "geometry"
        active = _active_task(geometry / ".active-geometry-pipeline-task.json")
        snapshot = read_geometry_status(geometry / "geometry_status.sqlite3")
        if snapshot is not None and snapshot.history_complete:
            counts = snapshot.counts
            exact = True
        elif snapshot is not None:
            legacy_counts = self._legacy_geometry_counts(geometry)
            counts = (
                legacy_counts
                if legacy_counts.considered >= snapshot.counts.considered
                else snapshot.counts
            )
            exact = False
        else:
            counts = self._legacy_geometry_counts(geometry)
            exact = counts.considered == 0

        checkpoint_path = geometry / "geometry_checkpoint.json"
        checkpoint: dict[str, Any] = {}
        if checkpoint_path.exists():
            try:
                payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    checkpoint = payload
            except (OSError, json.JSONDecodeError):
                checkpoint = {}

        if active:
            state = "running"
        elif checkpoint_path.exists() and not checkpoint:
            state = "checkpoint error"
        elif bool(checkpoint.get("completed", False)):
            state = "complete"
        elif checkpoint or counts.considered:
            state = "paused"
        elif formal == 0 and search_state.split(";", 1)[0] not in {
            "complete",
            "results only",
        }:
            state = "waiting for search"
        elif formal == 0:
            state = "nothing to test"
        else:
            state = "not started"
        return state, counts, exact

    def _legacy_geometry_counts(self, geometry: Path) -> GeometryStatusCounts:
        checkpoint: dict[str, Any] = {}
        checkpoint_path = geometry / "geometry_checkpoint.json"
        if checkpoint_path.exists():
            try:
                payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    checkpoint = payload
            except (OSError, json.JSONDecodeError):
                checkpoint = {}

        solved, fixed_solved = self._solution_counts(
            geometry / "geometric_solutions.jsonl"
        )
        failed = max(0, int(checkpoint.get("candidates_failed", 0)))
        fixed_evaluated = max(
            0, int(checkpoint.get("fixed_candidates_evaluated", 0))
        )
        certain = max(0, min(failed, fixed_evaluated - fixed_solved))
        return GeometryStatusCounts(
            solution_found=solved,
            rejected_certain=certain,
            no_solution_found=max(0, failed - certain),
        )

    def _count_jsonl(self, path: Path) -> int:
        try:
            stat = path.stat()
        except OSError:
            return 0
        cached = self._line_count_cache.get(path)
        signature = (stat.st_size, stat.st_mtime_ns)
        if cached is not None and cached[:2] == signature:
            return cached[2]
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                count = sum(1 for line in handle if line.strip())
        except OSError:
            return 0
        self._line_count_cache[path] = (signature[0], signature[1], count)
        return count

    def _solution_counts(self, path: Path) -> tuple[int, int]:
        try:
            stat = path.stat()
        except OSError:
            return 0, 0
        cached = self._solution_cache.get(path)
        signature = (stat.st_size, stat.st_mtime_ns)
        if cached is not None and cached[:2] == signature:
            return cached[2], cached[3]
        total = 0
        fixed = 0
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    total += 1
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    optimization = (
                        record.get("geometric_solution", {}).get("optimization", {})
                        if isinstance(record, dict)
                        else {}
                    )
                    if int(optimization.get("degrees_of_freedom", -1)) == 0:
                        fixed += 1
        except OSError:
            return 0, 0
        self._solution_cache[path] = (signature[0], signature[1], total, fixed)
        return total, fixed


def _make_search_diagnostics(
    statistics: Mapping[str, Any],
    *,
    source: str,
    updated_utc: str | None,
    completed: bool,
) -> SearchDiagnostics:
    counters_payload = statistics.get("counters", {})
    timings_payload = statistics.get(
        "timings_seconds", statistics.get("timings", {})
    )
    counters = _integer_mapping(counters_payload)
    timings = _float_mapping(timings_payload)

    def value(name: str) -> int:
        return counters.get(name, 0)

    def known(name: str) -> int | None:
        return counters.get(name) if name in counters else None

    def total(*names: str) -> int:
        return sum(value(name) for name in names)

    def rate(examined: int | None, result: int) -> float | None:
        if examined is None or examined <= 0 or result > examined:
            return None
        return 100.0 * result / examined

    def details(
        *,
        names: tuple[str, ...] = (),
        prefixes: tuple[str, ...] = (),
        excluded: tuple[str, ...] = (),
    ) -> tuple[tuple[str, int], ...]:
        selected = set(names)
        selected.update(
            name
            for name in counters
            if any(name.startswith(prefix) for prefix in prefixes)
        )
        selected.difference_update(excluded)
        return tuple(
            (name, counters[name])
            for name in sorted(selected)
            if name in counters and counters[name] != 0
        )

    stages: list[SearchDiagnosticStage] = []

    def add(
        label: str,
        examined: int | None,
        result: int,
        detail: tuple[tuple[str, int], ...] = (),
    ) -> None:
        stages.append(
            SearchDiagnosticStage(
                label=label,
                examined=examined,
                rejected_or_result=result,
                rate_percent=rate(examined, result),
                details=detail,
            )
        )

    domain_reduction = total(
        "cyclic_equivariance_assignment_reduction",
        "mapping_subdomain_assignment_reduction",
    )
    add(
        "Assignment domain reduction",
        known("unrestricted_raw_assignments_in_domain"),
        domain_reduction,
        details(
            names=(
                "raw_assignments_in_domain",
                "assignment_slots_in_domain",
                "cyclic_equivariance_assignment_reduction",
                "mapping_subdomain_assignment_reduction",
            )
        ),
    )

    assignment_prunes = total(
        "symmetry_pruned_assignments", "cyclic_shift_pruned_assignments"
    )
    add(
        "Assignment symmetry / imposed shift",
        None,
        assignment_prunes,
        details(
            names=(
                "assignments_processed",
                "canonical_assignments_processed",
                "symmetry_pruned_assignments",
                "cyclic_shift_pruned_assignments",
            )
        ),
    )

    add(
        "Weak-order DFS: fertile subdomain",
        None,
        total("mapping_subdomain_pruned_nodes", "mapping_subdomain_pruned_leaves"),
        details(prefixes=("mapping_subdomain_pruned_",)),
    )
    add(
        "Weak-order DFS: exterior-arc repetition",
        None,
        total(
            "exterior_arc_repetition_pruned_assignments",
            "exterior_arc_repetition_pruned_nodes",
        ),
        details(prefixes=("exterior_arc_repetition_pruned_",)),
    )
    add(
        "Weak-order DFS: intrinsic symmetry quotient",
        None,
        total("symmetry_pruned_nodes", "symmetry_pruned_leaves"),
        details(
            names=("symmetry_pruned_nodes", "symmetry_pruned_leaves")
        ),
    )

    prefix_examined = (
        total("prefix_topology_checks", "prefix_topology_cache_hits")
        if "prefix_topology_checks" in counters
        or "prefix_topology_cache_hits" in counters
        else None
    )
    add(
        "Weak-order DFS: prefix topology",
        prefix_examined,
        value("prefix_topology_pruned_nodes"),
        details(
            names=("prefix_topology_cache_hits", "prefix_topology_errors"),
            prefixes=("prefix_topology_rejection_",),
        ),
    )
    add(
        "Weak-order DFS: length feasibility",
        known("length_checks"),
        value("length_pruned_nodes"),
    )
    add(
        "Weak-order DFS: angle feasibility",
        known("angle_checks"),
        value("angle_pruned_nodes"),
    )
    add(
        "Complete placements reaching compilation",
        None,
        value("surviving_placements"),
        details(names=("placement_nodes", "estimated_raw_weak_orders_in_domain")),
    )
    add(
        "Word-case compilation errors",
        known("surviving_placements"),
        value("compile_errors"),
        details(names=("word_cases_compiled",)),
    )

    add(
        "Pre-word pruning",
        known("preword_checks"),
        value("preword_rejections"),
        details(
            names=(
                "preword_topology_rejections",
                "preword_linear_rejections",
                "preword_errors",
            ),
            prefixes=("preword_rejection_",),
            excluded=("preword_rejections",),
        ),
    )
    add(
        "Exact word solver: proved UNSAT",
        known("solver_cases"),
        value("exact_unsat_word_cases"),
        details(
            names=(
                "residual_graph_nodes",
                "residual_graph_edges",
                "terminal_contour_pruned_branches",
            )
        ),
    )
    add(
        "Exact word solver: deferred / limited",
        known("solver_cases"),
        value("deferred_word_cases"),
        details(
            names=(
                "unsupported_language_word_cases",
                "graph_limited_word_cases",
                "residual_literal_limited_word_cases",
                "family_limited_word_cases",
                "terminal_contour_limited_word_cases",
                "externally_stopped_word_cases",
            ),
            prefixes=("deferred_word_cases_",),
            excluded=("deferred_word_cases",),
        ),
    )
    add(
        "Word cases with no family emitted (includes deferred)",
        known("solver_cases"),
        value("word_cases_without_supported_family"),
        details(prefixes=("word_family_",), excluded=("word_families",)),
    )
    add(
        "Profile decoration",
        known("family_specializations"),
        value("decoration_rejections"),
        details(
            names=("profile_build_errors",),
            prefixes=("decoration_rejection_",),
            excluded=("decoration_rejections",),
        ),
    )
    filter_examined = None
    if "family_specializations" in counters:
        filter_examined = max(
            0,
            value("family_specializations")
            - value("decoration_rejections")
            - value("profile_build_errors"),
        )
    add(
        "Formal-profile filters",
        filter_examined,
        value("profile_filter_rejections"),
        details(
            prefixes=("profile_filter_rejection_",),
            excluded=("profile_filter_rejections",),
        ),
    )
    add(
        "Duplicate formal profiles",
        None,
        value("duplicate_profiles"),
    )
    add(
        "Formal candidates emitted",
        None,
        value("profiles_emitted"),
        details(names=("word_families", "family_specializations")),
    )

    elapsed = statistics.get("elapsed_seconds", 0.0)
    try:
        elapsed_seconds = max(0.0, float(elapsed))
    except (TypeError, ValueError):
        elapsed_seconds = 0.0
    return SearchDiagnostics(
        source=source,
        updated_utc=updated_utc,
        completed=completed,
        elapsed_seconds=elapsed_seconds,
        stages=tuple(stages),
        counters=tuple(sorted(counters.items())),
        timings=tuple(sorted(timings.items())),
    )


def _integer_mapping(payload: object) -> dict[str, int]:
    if not isinstance(payload, Mapping):
        return {}
    result: dict[str, int] = {}
    for key, raw in payload.items():
        try:
            result[str(key)] = int(raw)
        except (TypeError, ValueError, OverflowError):
            continue
    return result


def _float_mapping(payload: object) -> dict[str, float]:
    if not isinstance(payload, Mapping):
        return {}
    result: dict[str, float] = {}
    for key, raw in payload.items():
        try:
            result[str(key)] = max(0.0, float(raw))
        except (TypeError, ValueError, OverflowError):
            continue
    return result


def _active_task(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        pid = int(payload.get("child_pid") or payload.get("owner_pid") or 0)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False
    return _process_is_alive(pid)


def _process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            process_query_limited_information = 0x1000
            still_active = 259
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [
                wintypes.DWORD,
                wintypes.BOOL,
                wintypes.DWORD,
            ]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetExitCodeProcess.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(wintypes.DWORD),
            ]
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel32.OpenProcess(
                process_query_limited_information, False, int(pid)
            )
            if not handle:
                return False
            try:
                exit_code = wintypes.DWORD()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return int(exit_code.value) == still_active
            finally:
                kernel32.CloseHandle(handle)
        except (AttributeError, OSError):
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
