from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import sys
import threading
import traceback
from typing import Callable, Dict, Mapping, Sequence


SnapshotProvider = Callable[[], Mapping[str, object]]
SnapshotSink = Callable[[Mapping[str, object]], None]


@dataclass(frozen=True)
class StackFrameSnapshot:
    filename: str
    line: int
    function: str
    source: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "filename": self.filename,
            "line": self.line,
            "function": self.function,
            "source": self.source,
        }


class HeartbeatReporter:
    """Periodically sample the worker thread and publish a progress snapshot.

    The worker is deliberately observed from a separate daemon thread. This
    means a heartbeat still appears while the main search is inside a long
    Python function and no normal progress event is being emitted.
    """

    def __init__(
        self,
        *,
        interval_seconds: float,
        worker_thread_id: int,
        snapshot_provider: SnapshotProvider,
        snapshot_sink: SnapshotSink,
        stack_limit: int = 8,
    ) -> None:
        self.interval_seconds = max(0.05, float(interval_seconds))
        self.worker_thread_id = int(worker_thread_id)
        self.snapshot_provider = snapshot_provider
        self.snapshot_sink = snapshot_sink
        self.stack_limit = max(1, int(stack_limit))
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="formal-disk4-heartbeat",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=max(1.0, self.interval_seconds + 0.5))

    def _stack_snapshot(self) -> Sequence[Mapping[str, object]]:
        frame = sys._current_frames().get(self.worker_thread_id)
        if frame is None:
            return ()
        extracted = traceback.extract_stack(frame, limit=self.stack_limit)
        return tuple(
            StackFrameSnapshot(
                filename=item.filename,
                line=item.lineno,
                function=item.name,
                source=(item.line or "").strip(),
            ).to_dict()
            for item in extracted
        )

    def _publish(self) -> None:
        try:
            snapshot = dict(self.snapshot_provider())
            snapshot["heartbeat_utc"] = datetime.now(timezone.utc).isoformat()
            snapshot["stack"] = list(self._stack_snapshot())
            self.snapshot_sink(snapshot)
        except Exception as error:  # pragma: no cover - diagnostic safety net
            print(
                f"[HEARTBEAT ERROR] {type(error).__name__}: {error}",
                file=sys.stderr,
                flush=True,
            )

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            self._publish()
