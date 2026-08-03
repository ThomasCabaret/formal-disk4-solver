from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from formal_disk4.mapping_lab.dashboard import build_dashboard_data


class MappingLabDashboardTests(unittest.TestCase):
    def test_build_dashboard_data_extracts_weighted_inputs_and_deep_hits(self) -> None:
        row = {
            "generation": 12,
            "timeouts": 1,
            "max_stage_index": 8,
            "seed_deepest_stage_index": 9,
            "sampling_diagnostics": {
                "pool_duplicate.model_random_pool": 3,
                "pool_duplicate.model_seed_local": 4,
                "duplicate.uniform_control": 2,
            },
            "proposal_source_comparison": {
                "learned": {
                    "count": 10,
                    "mean_stage_index": 4.0,
                    "stage_reached_counts": {
                        "prefix_topology": 10,
                        "length": 4,
                        "preword_linear": 1,
                    },
                },
                "uniform": {
                    "count": 2,
                    "mean_stage_index": 3.0,
                    "stage_reached_counts": {"prefix_topology": 2},
                },
            },
            "learning_metrics": {
                "training_loss": 0.25,
                "transitions": {"4": {"auc": 0.8}},
            },
            "proposal_strategy_comparison": {
                "model_random_pool": {
                    "count": 10,
                    "mean_stage_index": 4.25,
                    "terminal_stage_histogram": {
                        "prefix_topology": 8,
                        "preword_linear": 1,
                        "word_solver": 1,
                    },
                }
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "generations.jsonl"
            source.write_text(json.dumps(row) + "\n{unfinished", encoding="utf-8")
            data = build_dashboard_data(source)

        self.assertEqual(len(data["points"]), 1)
        point = data["points"][0]
        self.assertEqual(point["generation"], 12)
        self.assertEqual(point["strategies"]["model_random_pool"]["count"], 10)
        self.assertEqual(point["strategies"]["model_random_pool"]["depth_sum"], 42.5)
        self.assertEqual(point["strategies"]["model_random_pool"]["deep_count"], 2)
        self.assertEqual(point["strategies"]["uniform_control"]["count"], 0)
        self.assertEqual(point["duplicate_rejections"], 9)
        self.assertEqual(point["sources"]["learned"]["deep_count"], 1)
        self.assertEqual(point["sources"]["learned"]["reached"][4], 4)
        self.assertEqual(point["learning_metrics"]["training_loss"], 0.25)


if __name__ == "__main__":
    unittest.main()
