from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from formal_disk4.graph_lab.dashboard import build_dashboard_data


def _mode(eligible: int, passed: int, predicted: float) -> dict[str, object]:
    transitions = {}
    for stage in (
        "assignment",
        "placement",
        "preword_pass",
        "word_family",
        "geometry_ready",
    ):
        transitions[stage] = {
            "eligible": eligible,
            "passed": passed,
            "prediction_sum": predicted * eligible,
            "prediction_count": eligible,
        }
    return {"count": eligible, "transitions": transitions}


class GraphLabDashboardTests(unittest.TestCase):
    def test_compares_initial_recent_random_and_learned_conditionally(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "training_metrics.jsonl"
            rows = [
                {
                    "generation": 0,
                    "evaluated": 20,
                    "geometry_ready": 1,
                    "training_output_bytes": 100,
                    "max_training_bytes": 1000,
                    "selection_modes": {
                        "exploration": _mode(10, 2, 0.2),
                        "learned": _mode(10, 3, 0.3),
                    },
                    "model": {"training_loss": 1.0, "transitions": {}},
                },
                {
                    "generation": 1,
                    "evaluated": 20,
                    "geometry_ready": 2,
                    "training_output_bytes": 200,
                    "max_training_bytes": 1000,
                    "selection_modes": {
                        "exploration": _mode(10, 4, 0.4),
                        "learned": _mode(10, 9, 0.8),
                    },
                    "model": {"training_loss": 0.5, "transitions": {}},
                },
            ]
            source.write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
            )
            data = build_dashboard_data(source, window_generations=1)

        first = data["transitions"][0]
        self.assertAlmostEqual(first["baseline"]["rate"], 0.2)
        self.assertAlmostEqual(first["recent_random"]["rate"], 0.4)
        self.assertAlmostEqual(first["recent_learned"]["rate"], 0.9)
        self.assertAlmostEqual(first["learned_vs_random_pp"], 50.0)
        self.assertEqual(data["summary"]["evaluated"], 40)
        self.assertEqual(data["summary"]["geometry_ready"], 3)


if __name__ == "__main__":
    unittest.main()
