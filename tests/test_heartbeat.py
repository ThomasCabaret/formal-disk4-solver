from __future__ import annotations

import threading
import time
import unittest

from formal_disk4.pipeline.heartbeat import HeartbeatReporter


class HeartbeatReporterTests(unittest.TestCase):
    def test_reporter_samples_worker_stack_and_snapshot(self) -> None:
        received: list[dict[str, object]] = []
        ready = threading.Event()

        def sink(snapshot):
            received.append(dict(snapshot))
            ready.set()

        reporter = HeartbeatReporter(
            interval_seconds=0.05,
            worker_thread_id=threading.get_ident(),
            snapshot_provider=lambda: {"stage": "unit_test", "counter": 7},
            snapshot_sink=sink,
            stack_limit=6,
        )
        reporter.start()
        try:
            self.assertTrue(ready.wait(1.0))
        finally:
            reporter.stop()

        self.assertTrue(received)
        snapshot = received[0]
        self.assertEqual(snapshot["stage"], "unit_test")
        self.assertEqual(snapshot["counter"], 7)
        self.assertIn("heartbeat_utc", snapshot)
        self.assertTrue(snapshot["stack"])
        top = snapshot["stack"][-1]
        self.assertIn("filename", top)
        self.assertIn("function", top)


if __name__ == "__main__":
    unittest.main()
