from __future__ import annotations

import copy
import json
import threading
import time
from pathlib import Path
from typing import Any, Mapping

from formal_disk4.geometry.runner import GeometryRunner
from formal_disk4.geometry.status import read_geometry_status_records
from formal_disk4.pipeline.output import atomic_write_json

from .geometry_catalog import CatalogCandidate, GeometryCandidateCatalog


class GeometryQueueWorker:
    """Tail the Lab candidate stream and solve every unique profile once."""

    def __init__(
        self,
        geometry_config: Mapping[str, Any],
        catalog: GeometryCandidateCatalog,
        *,
        poll_seconds: float = 1.0,
        batch_size: int = 16,
    ) -> None:
        self.config = copy.deepcopy(dict(geometry_config))
        self.catalog = catalog
        self.poll_seconds = max(0.1, float(poll_seconds))
        self.batch_size = max(1, int(batch_size))
        output = Path(str(self.config["output"]["directory"])).resolve()
        output.mkdir(parents=True, exist_ok=True)
        self.output = output
        self.state_path = output / "geometry_worker_state.json"
        self.batch_path = output / "geometry_queue_batch.jsonl"
        self.stop_event = threading.Event()
        self.producer_done = threading.Event()
        self.thread: threading.Thread | None = None

    def _state(self, **values: object) -> None:
        payload: dict[str, object] = {
            "schema_version": "graph-lab-geometry-worker-v1",
            "phase": "idle",
            "current_profile_id": None,
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
        atomic_write_json(self.state_path, payload)

    def start(self) -> None:
        if self.thread is not None and self.thread.is_alive():
            return
        self.thread = threading.Thread(
            target=self.run,
            name="graph-lab-geometry-worker",
            daemon=True,
        )
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def join(self, timeout: float | None = None) -> None:
        if self.thread is not None:
            self.thread.join(timeout=timeout)

    def mark_producer_done(self) -> None:
        self.producer_done.set()

    def _batch_config(self) -> dict[str, Any]:
        config = copy.deepcopy(self.config)
        config["input"]["candidates_file"] = str(self.batch_path)
        config["output"]["directory"] = str(self.output)
        config["output"]["summary_file"] = "geometry_queue_summary.json"
        config["output"]["checkpoint_file"] = "geometry_queue_checkpoint.json"
        config["limits"]["max_candidates"] = None
        config["limits"]["max_solutions"] = None
        config["limits"]["stop_on_first_solution"] = False
        config["checkpoint"].update(
            {"enabled": False, "resume": False, "restart": False}
        )
        return config

    def _write_batch(self, pending: list[CatalogCandidate]) -> None:
        with self.batch_path.open("wb") as stream:
            for candidate in pending:
                raw = self.catalog.read_raw(candidate)
                stream.write(raw)
                if raw and not raw.endswith(b"\n"):
                    stream.write(b"\n")

    def _progress(self, payload: Mapping[str, object]) -> None:
        event = str(payload.get("event", "processing"))
        if event == "processing":
            self._state(
                phase="solving",
                current_profile_id=payload.get("formal_profile_id"),
                current_map=payload.get("map"),
            )
        else:
            self._state(
                phase="queue",
                current_profile_id=None,
                last_profile_id=payload.get("formal_profile_id"),
                last_status=payload.get("status"),
                last_reason=payload.get("reason"),
            )

    def run(self) -> None:
        self._state(phase="indexing", current_profile_id=None, error=None)
        while not self.stop_event.is_set():
            try:
                # Yield the shared catalog lock regularly so dashboard requests
                # remain responsive even during the initial multi-gigabyte scan.
                progress = self.catalog.ingest(maximum_lines=500)
                statuses = read_geometry_status_records(
                    self.output / str(
                        self.config["output"].get(
                            "status_file", "geometry_status.sqlite3"
                        )
                    )
                )
                pending = self.catalog.pending(
                    set(statuses), limit=self.batch_size
                )
                self._state(
                    phase="queue" if pending else "idle",
                    current_profile_id=None,
                    indexed_candidates=progress["unique_candidates"],
                    indexed_lines=progress["source_line"],
                    pending_candidates=max(
                        0, progress["unique_candidates"] - len(statuses)
                    ),
                    considered_candidates=len(statuses),
                    error=None,
                )
                if pending:
                    self._write_batch(pending)
                    runner = GeometryRunner(self._batch_config())
                    runner.run(
                        skip_profile_ids=set(statuses),
                        progress_sink=self._progress,
                    )
                    continue
                source_size = (
                    self.catalog.source.stat().st_size
                    if self.catalog.source.exists()
                    else 0
                )
                if (
                    self.producer_done.is_set()
                    and progress["source_offset"] >= source_size
                ):
                    self._state(phase="complete", current_profile_id=None)
                    return
            except Exception as error:  # keep the queue observable and retryable
                self._state(
                    phase="error",
                    current_profile_id=None,
                    error=f"{type(error).__name__}: {error}",
                )
            self.stop_event.wait(self.poll_seconds)
        self._state(phase="stopped", current_profile_id=None)
