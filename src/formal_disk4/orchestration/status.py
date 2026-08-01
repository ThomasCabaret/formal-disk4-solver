from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
