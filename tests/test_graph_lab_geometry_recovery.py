from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from formal_disk4.geometry.status import (
    NO_SOLUTION_FOUND,
    REJECTED_CERTAIN,
    SOLUTION_FOUND,
    GeometryStatusStore,
    read_geometry_status_records,
)
from formal_disk4.graph_lab.geometry_recovery import GeometryRecoveryWorker


def _candidate(profile_id: str) -> dict[str, object]:
    return {
        "formal_profile_id": profile_id,
        "map": {"name": "test"},
        "graph_lab": {
            "generation": 1,
            "graph_id": f"dg-{profile_id}",
            "structural_candidate": {
                "tile_count": 3,
                "edges": [[-1, 0], [-1, 1], [-1, 2], [0, 1], [1, 2], [0, 2]],
                "symmetry_order": 1,
            },
        },
    }


class GraphLabGeometryRecoveryTests(unittest.TestCase):
    def test_only_inconclusive_primary_statuses_are_retried_and_resume(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "geometry_candidates.jsonl"
            source.write_text(
                "".join(
                    json.dumps(_candidate(profile_id)) + "\n"
                    for profile_id in ("fp-uncertain", "fp-certain", "fp-solved")
                ),
                encoding="utf-8",
            )
            primary = root / "geometry" / "geometry_status.sqlite3"
            with GeometryStatusStore(primary) as store:
                store.record(
                    "fp-uncertain",
                    NO_SOLUTION_FOUND,
                    reason="timeout",
                    attempts=4,
                    best_cost=0.1,
                )
                store.record(
                    "fp-certain",
                    REJECTED_CERTAIN,
                    reason="fixed geometry failed",
                    attempts=0,
                    best_cost=1.0,
                )
                store.record(
                    "fp-solved",
                    SOLUTION_FOUND,
                    reason="solved",
                    attempts=1,
                    best_cost=0.0,
                )
            output = root / "geometry-recovery"
            config = {
                "input": {"candidates_file": str(source)},
                "output": {
                    "directory": str(output),
                    "status_file": "geometry_status.sqlite3",
                },
                "geometry": {"intermediate_points_per_generic_curve": 5},
                "limits": {},
                "checkpoint": {},
                "recovery": {
                    "primary_geometry_directory": str(root / "geometry"),
                    "follow": False,
                    "batch_size": 1,
                },
            }
            attempted: list[str] = []

            class FakeRunner:
                def __init__(self, runner_config: object) -> None:
                    self.config = runner_config

                def run(self, **arguments: object) -> dict[str, object]:
                    batch = Path(self.config["input"]["candidates_file"])
                    row = json.loads(batch.read_text(encoding="utf-8"))
                    profile_id = str(row["formal_profile_id"])
                    attempted.append(profile_id)
                    sink = arguments["progress_sink"]
                    sink(
                        {
                            "event": "processing",
                            "formal_profile_id": profile_id,
                            "map": "test",
                        }
                    )
                    with GeometryStatusStore(
                        output / "geometry_status.sqlite3"
                    ) as store:
                        store.record(
                            profile_id,
                            NO_SOLUTION_FOUND,
                            reason="still no solution",
                            attempts=10,
                            best_cost=0.01,
                        )
                    sink(
                        {
                            "event": "completed",
                            "formal_profile_id": profile_id,
                            "status": NO_SOLUTION_FOUND,
                            "reason": "still no solution",
                            "attempts": 10,
                        }
                    )
                    return {"stop_reason": "completed"}

            with patch(
                "formal_disk4.graph_lab.geometry_recovery.GeometryRunner", FakeRunner
            ):
                worker = GeometryRecoveryWorker(config, root=root)
                try:
                    self.assertEqual(worker.run(), 0)
                finally:
                    worker.close()
                resumed = GeometryRecoveryWorker(config, root=root)
                try:
                    self.assertEqual(resumed.run(), 0)
                finally:
                    resumed.close()

            self.assertEqual(attempted, ["fp-uncertain"])
            statuses = read_geometry_status_records(
                output / "geometry_status.sqlite3"
            )
            self.assertEqual(set(statuses), {"fp-uncertain"})


if __name__ == "__main__":
    unittest.main()
