from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from formal_disk4.geometry.status import GeometryCandidateStatus
from formal_disk4.graph_lab.geometry_catalog import CatalogCandidate
from formal_disk4.graph_lab.geometry_queue import GeometryQueueWorker


class _FakeCatalog:
    def __init__(self, source: Path) -> None:
        self.source = source
        self.pending_calls = 0

    def ingest(self, *, maximum_lines: int | None = None) -> dict[str, int]:
        del maximum_lines
        return {
            "source_offset": self.source.stat().st_size,
            "source_line": 1,
            "unique_candidates": 1,
        }

    def pending(
        self, considered_ids: set[str], *, limit: int
    ) -> list[CatalogCandidate]:
        del limit
        self.pending_calls += 1
        if "fp-test" in considered_ids:
            return []
        return [CatalogCandidate("fp-test", 0, self.source.stat().st_size)]

    def read_raw(self, candidate: CatalogCandidate) -> bytes:
        del candidate
        return self.source.read_bytes()


class GraphLabGeometryQueueTests(unittest.TestCase):
    def test_worker_persists_batch_and_reaches_complete(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "geometry_candidates.jsonl"
            source.write_text(
                json.dumps({"formal_profile_id": "fp-test"}) + "\n",
                encoding="utf-8",
            )
            output = root / "geometry"
            config = {
                "input": {"candidates_file": str(source)},
                "output": {
                    "directory": str(output),
                    "status_file": "geometry_status.sqlite3",
                },
                "limits": {},
                "checkpoint": {},
            }
            catalog = _FakeCatalog(source)
            status = GeometryCandidateStatus(
                "fp-test", "solution_found", "solved", 1, 0.0, "now"
            )
            status_reads = [{}, {"fp-test": status}]

            class FakeRunner:
                def __init__(self, runner_config: object) -> None:
                    self.runner_config = runner_config

                def run(self, **arguments: object) -> dict[str, object]:
                    sink = arguments["progress_sink"]
                    sink(
                        {
                            "event": "processing",
                            "formal_profile_id": "fp-test",
                            "map": "test",
                        }
                    )
                    sink(
                        {
                            "event": "completed",
                            "formal_profile_id": "fp-test",
                            "status": "solution_found",
                            "reason": "solved",
                        }
                    )
                    return {}

            worker = GeometryQueueWorker(config, catalog, poll_seconds=0.01)
            worker.mark_producer_done()
            with (
                patch(
                    "formal_disk4.graph_lab.geometry_queue."
                    "read_geometry_status_records",
                    side_effect=status_reads,
                ),
                patch(
                    "formal_disk4.graph_lab.geometry_queue.GeometryRunner",
                    FakeRunner,
                ),
            ):
                worker.run()

            state = json.loads(worker.state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["phase"], "complete")
            self.assertIn("fp-test", worker.batch_path.read_text(encoding="utf-8"))
            self.assertEqual(catalog.pending_calls, 2)


if __name__ == "__main__":
    unittest.main()
