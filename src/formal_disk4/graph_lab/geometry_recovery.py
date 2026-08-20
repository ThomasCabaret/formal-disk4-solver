from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from formal_disk4.config import load_geometry_config
from formal_disk4.geometry.runner import GeometryRunner
from formal_disk4.geometry.status import (
    NO_SOLUTION_FOUND,
    REJECTED_CERTAIN,
    SOLUTION_FOUND,
    GeometryCandidateStatus,
    read_geometry_status_records,
    remove_sqlite_files,
)
from formal_disk4.pipeline.output import atomic_write_json

from .dashboard import GraphLabDashboardServer
from .geometry_catalog import CatalogCandidate, GeometryCandidateCatalog


def _resolve(root: Path, value: object) -> Path:
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (root / path).resolve()


class GeometryRecoveryWorker:
    """Retry only inconclusive geometry failures with an isolated strong solver.

    The normal queue and this worker deliberately use different JSONL and
    SQLite files. The dashboard merges their read-only views, which makes the
    recovery pass safe to run while Graph Lab is still producing candidates.
    """

    def __init__(
        self,
        config: Mapping[str, Any],
        *,
        root: Path,
        follow: bool | None = None,
        poll_seconds: float | None = None,
        batch_size: int | None = None,
    ) -> None:
        self.root = root.resolve()
        self.config = copy.deepcopy(dict(config))
        recovery = self.config.get("recovery", {})
        recovery = recovery if isinstance(recovery, Mapping) else {}
        self.source = _resolve(
            self.root, self.config["input"]["candidates_file"]
        )
        self.output = _resolve(
            self.root, self.config["output"]["directory"]
        )
        self.primary_geometry = _resolve(
            self.root,
            recovery.get(
                "primary_geometry_directory", self.source.parent / "geometry"
            ),
        )
        self.follow = bool(recovery.get("follow", True)) if follow is None else follow
        configured_poll = float(recovery.get("poll_seconds", 2.0))
        self.poll_seconds = max(
            0.1, configured_poll if poll_seconds is None else float(poll_seconds)
        )
        configured_batch = int(recovery.get("batch_size", 1))
        self.batch_size = max(
            1, configured_batch if batch_size is None else int(batch_size)
        )
        self.ingest_lines = max(1, int(recovery.get("catalog_ingest_lines", 1000)))
        self.output.mkdir(parents=True, exist_ok=True)
        self.catalog = GeometryCandidateCatalog(
            self.output / "geometry_recovery_catalog.sqlite3", self.source
        )
        self.batch_path = self.output / "geometry_recovery_batch.jsonl"
        self.state_path = self.output / "geometry_recovery_state.json"
        self.primary_status_path = self.primary_geometry / str(
            recovery.get("primary_status_file", "geometry_status.sqlite3")
        )
        self.recovery_status_path = self.output / str(
            self.config["output"].get("status_file", "geometry_status.sqlite3")
        )
        self.started = time.perf_counter()
        self.current_started: float | None = None
        self.last_printed_snapshot: tuple[object, ...] | None = None

    def close(self) -> None:
        self.catalog.close()

    def _state(self, **values: object) -> None:
        payload: dict[str, object] = {
            "schema_version": "graph-lab-geometry-recovery-v1",
            "phase": "idle",
            "current_profile_id": None,
            "source_candidates_file": str(self.source),
            "primary_geometry_directory": str(self.primary_geometry),
            "output_directory": str(self.output),
            "updated_unix": time.time(),
        }
        if self.state_path.exists():
            try:
                previous = json.loads(self.state_path.read_text(encoding="utf-8"))
                if isinstance(previous, dict):
                    payload.update(previous)
            except (OSError, json.JSONDecodeError):
                pass
        payload.update(values)
        payload["updated_unix"] = time.time()
        # Antivirus/indexing software can briefly hold the destination on
        # Windows. Retrying keeps an observability file from killing the work.
        for attempt in range(6):
            try:
                atomic_write_json(self.state_path, payload)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * (attempt + 1))

    @staticmethod
    def _counts(
        eligible_ids: set[str], recovery_statuses: Mapping[str, GeometryCandidateStatus]
    ) -> dict[str, int]:
        completed = {
            profile_id: status
            for profile_id, status in recovery_statuses.items()
            if profile_id in eligible_ids
        }
        return {
            "eligible": len(eligible_ids),
            "completed": len(completed),
            "remaining": max(0, len(eligible_ids) - len(completed)),
            "recovered": sum(
                status.status == SOLUTION_FOUND for status in completed.values()
            ),
            "rejected_certain": sum(
                status.status == REJECTED_CERTAIN for status in completed.values()
            ),
            "still_inconclusive": sum(
                status.status == NO_SOLUTION_FOUND for status in completed.values()
            ),
        }

    @staticmethod
    def _summary_text(counts: Mapping[str, int]) -> str:
        return (
            f"done={counts['completed']}/{counts['eligible']} "
            f"remaining={counts['remaining']} recovered={counts['recovered']} "
            f"still-inconclusive={counts['still_inconclusive']} "
            f"certain={counts['rejected_certain']}"
        )

    def _write_batch(self, candidates: Sequence[CatalogCandidate]) -> None:
        with self.batch_path.open("wb") as stream:
            for candidate in candidates:
                raw = self.catalog.read_raw(candidate)
                stream.write(raw)
                if raw and not raw.endswith(b"\n"):
                    stream.write(b"\n")

    def _batch_config(self) -> dict[str, Any]:
        config = copy.deepcopy(self.config)
        config["input"]["candidates_file"] = str(self.batch_path)
        config["output"]["directory"] = str(self.output)
        config["output"]["summary_file"] = "geometry_recovery_summary.json"
        config["output"]["checkpoint_file"] = "geometry_recovery_checkpoint.json"
        config["limits"]["max_candidates"] = None
        config["limits"]["max_solutions"] = None
        config["limits"]["stop_on_first_solution"] = False
        config["checkpoint"].update(
            {"enabled": False, "resume": False, "restart": False}
        )
        return config

    def _progress(self, payload: Mapping[str, object]) -> None:
        event = str(payload.get("event", "processing"))
        profile_id = str(payload.get("formal_profile_id", ""))
        if event == "processing":
            self.current_started = time.perf_counter()
            print(
                f"[RECOVERY START] formal={profile_id} "
                f"map={payload.get('map', '')}",
                flush=True,
            )
            self._state(phase="solving", current_profile_id=profile_id)
            return
        elapsed = (
            0.0
            if self.current_started is None
            else time.perf_counter() - self.current_started
        )
        print(
            f"[RECOVERY RESULT] formal={profile_id} "
            f"status={payload.get('status')} attempts={payload.get('attempts')} "
            f"elapsed={elapsed:.2f}s reason={payload.get('reason')}",
            flush=True,
        )
        self._state(
            phase="queue",
            current_profile_id=None,
            last_profile_id=profile_id,
            last_status=payload.get("status"),
            last_reason=payload.get("reason"),
        )

    @staticmethod
    def _priority(
        candidate: CatalogCandidate,
        primary: Mapping[str, GeometryCandidateStatus],
    ) -> tuple[bool, float, str]:
        status = primary[candidate.formal_profile_id]
        return (
            status.best_cost is None,
            float("inf") if status.best_cost is None else status.best_cost,
            status.updated_utc,
        )

    def run(self) -> int:
        if not self.source.exists():
            raise FileNotFoundError(f"Geometry candidate stream not found: {self.source}")
        if not self.primary_status_path.exists():
            raise FileNotFoundError(
                f"Primary geometry status database not found: {self.primary_status_path}"
            )
        print(
            "Strong geometry recovery started\n"
            f"  candidates: {self.source}\n"
            f"  primary statuses: {self.primary_status_path}\n"
            f"  isolated output: {self.output}\n"
            f"  generic intermediate points: "
            f"{self.config['geometry']['intermediate_points_per_generic_curve']}\n"
            f"  timeout per candidate: "
            f"{self.config['geometry'].get('candidate_timeout_seconds', 0)}s\n"
            f"  mode: {'follow live input' if self.follow else 'current snapshot'}",
            flush=True,
        )
        try:
            while True:
                catalog_progress = self.catalog.ingest(
                    maximum_lines=self.ingest_lines
                )
                primary = read_geometry_status_records(self.primary_status_path)
                recovery = read_geometry_status_records(self.recovery_status_path)
                eligible_ids = {
                    profile_id
                    for profile_id, status in primary.items()
                    if status.status == NO_SOLUTION_FOUND
                }
                pending_ids = eligible_ids - set(recovery)
                pending = self.catalog.selected(pending_ids)
                pending.sort(key=lambda item: self._priority(item, primary))
                counts = self._counts(eligible_ids, recovery)
                indexed_pending = len(pending)
                awaiting_index = max(0, counts["remaining"] - indexed_pending)
                snapshot = (
                    *counts.values(),
                    catalog_progress["source_line"],
                    awaiting_index,
                )
                if snapshot != self.last_printed_snapshot:
                    print(
                        f"[RECOVERY PROGRESS] {self._summary_text(counts)} "
                        f"indexed-lines={catalog_progress['source_line']} "
                        f"awaiting-index={awaiting_index}",
                        flush=True,
                    )
                    self.last_printed_snapshot = snapshot
                self._state(
                    phase="queue" if pending else ("waiting" if self.follow else "complete"),
                    current_profile_id=None,
                    **counts,
                    indexed_lines=catalog_progress["source_line"],
                    indexed_candidates=catalog_progress["unique_candidates"],
                    awaiting_index=awaiting_index,
                    elapsed_seconds=time.perf_counter() - self.started,
                    error=None,
                )
                if pending:
                    batch = pending[: self.batch_size]
                    self._write_batch(batch)
                    summary = GeometryRunner(self._batch_config()).run(
                        progress_sink=self._progress
                    )
                    if summary.get("stop_reason") == "keyboard_interrupt":
                        self._state(phase="stopped", current_profile_id=None)
                        return 130
                    continue
                source_size = self.source.stat().st_size
                fully_indexed = catalog_progress["source_offset"] >= source_size
                if not self.follow and fully_indexed:
                    print(
                        f"[RECOVERY COMPLETE] {self._summary_text(counts)}",
                        flush=True,
                    )
                    return 0
                time.sleep(self.poll_seconds)
        except KeyboardInterrupt:
            self._state(phase="stopped", current_profile_id=None)
            print("\nStrong geometry recovery stopped; progress is saved.", flush=True)
            return 130


def _reset_output(config: Mapping[str, Any], root: Path) -> None:
    output = _resolve(root, config["output"]["directory"])
    output.mkdir(parents=True, exist_ok=True)
    names = (
        str(config["output"].get("solutions_file", "geometric_solutions.jsonl")),
        str(config["output"].get("summary_file", "geometry_recovery_summary.json")),
        str(config["output"].get("failures_file", "geometry_failures.jsonl")),
        "geometry_recovery_batch.jsonl",
        "geometry_recovery_state.json",
        "geometry_recovery_checkpoint.json",
    )
    for name in names:
        try:
            (output / name).unlink()
        except FileNotFoundError:
            pass
    remove_sqlite_files(
        output / str(config["output"].get("status_file", "geometry_status.sqlite3"))
    )
    remove_sqlite_files(output / "geometry_recovery_catalog.sqlite3")
    remove_sqlite_files(output / "geometry_recovery_dashboard_catalog.sqlite3")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Retry Graph Lab's inconclusive geometry profiles with a stronger, "
            "resumable solver and isolated output files."
        )
    )
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--config", default="config/graph_lab/geometry-recovery.json"
    )
    parser.add_argument("--restart", action="store_true")
    parser.add_argument(
        "--follow",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="keep watching the live Lab for new inconclusive profiles",
    )
    parser.add_argument("--poll-seconds", type=float)
    parser.add_argument("--batch-size", type=int)
    parser.add_argument(
        "--dashboard-port",
        type=int,
        help="also open an updated dashboard on this port",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-browser", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    config_path = _resolve(root, args.config)
    config = load_geometry_config(config_path)
    if args.restart:
        _reset_output(config, root)
    worker = GeometryRecoveryWorker(
        config,
        root=root,
        follow=args.follow,
        poll_seconds=args.poll_seconds,
        batch_size=args.batch_size,
    )
    dashboard: GraphLabDashboardServer | None = None
    if args.dashboard_port is not None:
        dashboard = GraphLabDashboardServer(
            worker.source.parent,
            host=args.host,
            port=args.dashboard_port,
            catalog_path=(
                worker.output / "geometry_recovery_dashboard_catalog.sqlite3"
            ),
        )
        dashboard.start(open_browser=not args.no_browser)
        print(f"recovery dashboard: {dashboard.url}", flush=True)
    try:
        return worker.run()
    finally:
        if dashboard is not None:
            dashboard.close()
        worker.close()


if __name__ == "__main__":
    raise SystemExit(main())
