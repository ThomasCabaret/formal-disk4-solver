from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from formal_disk4.config import load_geometry_config, load_visualization_config
from formal_disk4.geometry.model import parse_formal_geometry_problem
from formal_disk4.graph_lab.runner import GraphLabRunner


ROOT = Path(__file__).resolve().parents[1]


class GraphLabTests(unittest.TestCase):
    def test_dedicated_geometry_and_visualizer_configs_load(self) -> None:
        geometry = load_geometry_config(ROOT / "config/graph_lab/geometry.json")
        visualization = load_visualization_config(
            ROOT / "config/graph_lab/visualizer.json"
        )
        self.assertIn("graph_lab", geometry["input"]["candidates_file"])
        self.assertIn("graph_lab", visualization["input"]["solutions_file"])

    def test_training_output_budget_stops_cleanly(self) -> None:
        output_root = ROOT / "output"
        output_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output_root) as raw_output:
            runner = GraphLabRunner(
                ROOT,
                {
                    "output": {
                        "directory": raw_output,
                        "max_training_megabytes": 0.000001,
                    },
                    "space": {
                        "maximum_tiles": 13,
                        "known_seeds": [{"map": "centered-double-cycle-6"}],
                    },
                    "sampling": {"generations": 1, "batch_size": 1},
                    "learning": {
                        "hidden_size": 8,
                        "message_layers": 1,
                        "torch_threads": 1,
                    },
                    "evaluation": {
                        "base_search_config": "config/cycle_campaign/search.json"
                    },
                },
            )
            result = runner.run(restart=True)
        self.assertEqual(result.stop_reason, "max_training_output_bytes")
        self.assertEqual(result.observations, 0)

    def test_one_generation_persists_a_known_geometry_candidate(self) -> None:
        output_root = ROOT / "output"
        output_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output_root) as raw_output:
            config = {
                "output": {"directory": raw_output},
                "space": {
                    "maximum_tiles": 4,
                    "known_seeds": [{"map": "c4"}],
                },
                "sampling": {
                    "seed": 7,
                    "generations": 1,
                    "batch_size": 1,
                    "known_seeds_per_generation": 1,
                },
                "learning": {
                    "seed": 7,
                    "hidden_size": 16,
                    "message_layers": 1,
                    "steps_per_generation": 1,
                    "batch_size": 1,
                    "torch_threads": 1,
                },
                "evaluation": {
                    "base_search_config": "config/cycle_campaign/search.json",
                    "search_overrides": {
                        "limits": {
                            "max_assignments": 1,
                            "max_nodes": 5000,
                            "max_placements": 10,
                            "max_profiles": 1,
                            "time_limit_seconds": 10,
                            "stop_on_first_profile": True,
                        },
                        "solver": {
                            "max_seconds_per_word_case": 2,
                            "max_graph_nodes_per_placement": 5000,
                        },
                    },
                },
            }
            runner = GraphLabRunner(ROOT, config)
            result = runner.run(restart=True)
            output = Path(raw_output)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            generation_metrics = json.loads(
                (output / "training_metrics.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )
            candidate_path = output / "geometry_candidates.jsonl"
            candidates = candidate_path.read_text(encoding="utf-8")
            first_candidate = json.loads(candidates.splitlines()[0])
            geometry_problem = parse_formal_geometry_problem(
                first_candidate,
                source_path=candidate_path,
                source_line=1,
            )
        self.assertEqual(result.observations, 1)
        self.assertEqual(result.geometry_ready_graphs, 1)
        self.assertEqual(result.stop_reason, "completed")
        self.assertEqual(len(report["geometry_ready"]), 1)
        self.assertEqual(generation_metrics["generation"], 0)
        self.assertEqual(
            generation_metrics["selection_modes"]["known_control"]["count"], 1
        )
        self.assertIn('"graph_lab"', candidates)
        self.assertTrue(geometry_problem.segments)


if __name__ == "__main__":
    unittest.main()
