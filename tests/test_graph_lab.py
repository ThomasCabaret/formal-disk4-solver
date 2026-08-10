from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path

import numpy as np

from formal_disk4.config import load_geometry_config, load_visualization_config
from formal_disk4.geometry.model import parse_formal_geometry_problem
from formal_disk4.graph_lab.runner import DiversityArchive, GraphLabRunner
from formal_disk4.graph_lab.weak_model import (
    WeakOrderPrediction,
    WeakOrderRankedPolicy,
)
from formal_disk4.enumeration.weak_policy import (
    WeakOrderActionView,
    WeakOrderStateView,
)


ROOT = Path(__file__).resolve().parents[1]


class GraphLabTests(unittest.TestCase):
    def test_weak_order_action_pool_is_uniform_without_mandatory_shapes(self) -> None:
        class PoolOnlyModel:
            active_heads = np.zeros(26, dtype=bool)

            @staticmethod
            def prepare_mapping(_proposal):
                return None

        state = WeakOrderStateView(
            assignment_id=0,
            path=(),
            counters=(0,) * 13,
            targets=(2,) * 13,
            block_count=0,
            resolved_length_equations=0,
            resolved_angle_equations=0,
            available_mask=(1 << 13) - 1,
            reference_index=0,
        )
        masks = tuple(range(1, 1 << 13))
        policy = WeakOrderRankedPolicy(
            object(),
            PoolOnlyModel(),
            {"action_pool_size": 64},
            random_seed=123,
            selection_mode="exploration",
        )

        self.assertEqual(
            tuple(policy.propose_masks(state, masks)),
            tuple(random.Random(123).sample(masks, 64)),
        )

    def test_graph_candidates_can_be_revisited_for_new_descendant_rollouts(self) -> None:
        output_root = ROOT / "output"
        output_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output_root) as raw_output:
            runner = GraphLabRunner(
                ROOT,
                {
                    "output": {"directory": raw_output},
                    "space": {
                        "maximum_tiles": 3,
                        "symmetric_prior_fraction": 1.0,
                        "imposed_symmetry_bias": 0.0,
                    },
                    "sampling": {"mutation_fraction": 0.0},
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
            first = runner._candidate_pool(
                random.Random(1), DiversityArchive(()), 1
            )[0]
            second = runner._candidate_pool(
                random.Random(2), DiversityArchive(()), 1
            )[0]

        self.assertEqual(first.graph_id, second.graph_id)

    def test_weak_order_ranker_changes_the_stochastic_action_distribution(self) -> None:
        class FakeModel:
            active_heads = np.asarray([True] + [False] * 25)

            @staticmethod
            def prepare_mapping(_proposal):
                return None

            @staticmethod
            def predict_many(
                _proposal, _state, actions, *, prepared_mapping=None
            ):
                self.assertIsNone(prepared_mapping)
                probabilities = (0.05, 0.95)
                return tuple(
                    WeakOrderPrediction(
                        conditional_probabilities=(probabilities[index],)
                        + (0.5,) * 25,
                        reach_probabilities=(probabilities[index],)
                        + (0.5,) * 25,
                        utility=0.0,
                        expected_seconds=0.0,
                    )
                    for index, _action in enumerate(actions)
                )

        state = WeakOrderStateView(
            assignment_id=0,
            path=(),
            counters=(0, 0),
            targets=(2, 2),
            block_count=0,
            resolved_length_equations=0,
            resolved_angle_equations=0,
            available_mask=3,
            reference_index=0,
        )
        actions = (
            WeakOrderActionView(1, (1, 0), 1, 0, 0),
            WeakOrderActionView(3, (1, 1), 2, 0, 0),
        )
        policy = WeakOrderRankedPolicy(
            object(),  # FakeModel does not inspect the mapping proposal.
            FakeModel(),
            {
                "epsilon": 0.0,
                "temperature": 0.1,
                "deeper_utility_weight": 0.0,
                "cost_weight": 0.0,
            },
            random_seed=4,
            selection_mode="learned",
        )

        self.assertEqual(policy.select_actions(state, actions), (3,))
        self.assertEqual(policy.decisions[0].selection_mode, "learned")
        self.assertGreater(policy.decisions[0].selection_probability, 0.99)

    def test_mapping_learning_generation_persists_microfilter_observations(self) -> None:
        output_root = ROOT / "output"
        output_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output_root) as raw_output:
            runner = GraphLabRunner(
                ROOT,
                {
                    "output": {"directory": raw_output},
                    "space": {
                        "maximum_tiles": 3,
                        "known_seeds": [{"map": "c3"}],
                    },
                    "sampling": {
                        "seed": 9,
                        "generations": 1,
                        "batch_size": 1,
                        "known_seeds_per_generation": 1,
                    },
                    "learning": {
                        "hidden_size": 8,
                        "message_layers": 1,
                        "steps_per_generation": 1,
                        "batch_size": 1,
                        "torch_threads": 1,
                    },
                    "mapping_sampling": {
                        "enabled": True,
                        "mappings_per_graph": 1,
                        "pool_multiplier": 2,
                        "exploration_fraction": 0.5,
                        "rollouts_per_mapping": 1,
                    },
                    "mapping_learning": {
                        "hidden_size": 8,
                        "message_layers": 1,
                        "steps_per_generation": 1,
                        "batch_size": 1,
                        "torch_threads": 1,
                    },
                    "weak_order_sampling": {
                        "enabled": True,
                        "rollouts_per_mapping": 2,
                        "exploration_fraction": 0.5,
                        "action_pool_size": 8,
                    },
                    "weak_order_learning": {
                        "hidden_size": 8,
                        "message_layers": 1,
                        "steps_per_generation": 1,
                        "batch_size": 1,
                        "metric_decisions": 8,
                        "torch_threads": 1,
                    },
                    "evaluation": {
                        "base_search_config": "config/cycle_campaign/search.json",
                        "mapping_search_overrides": {
                            "limits": {
                                "max_nodes": 200,
                                "max_placements": 2,
                                "max_profiles": 1,
                                "time_limit_seconds": 3,
                                "stop_on_first_profile": True,
                            }
                        },
                    },
                },
            )
            result = runner.run(restart=True)
            output = Path(raw_output)
            mapping_record = json.loads(
                (output / "mapping_observations.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )
            mapping_metrics = json.loads(
                (output / "mapping_training_metrics.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )
            weak_records = [
                json.loads(line)
                for line in (output / "weak_order_rollouts.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            weak_metrics = json.loads(
                (output / "weak_order_training_metrics.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )
            coverage = json.loads(
                (output / "rollout_coverage_metrics.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )
        self.assertEqual(result.observations, 1)
        self.assertEqual(len(mapping_record["target_vector"]), 26)
        self.assertEqual(mapping_record["rollout_count"], 2)
        self.assertEqual(mapping_metrics["model"]["examples"], 1)
        self.assertEqual(mapping_metrics["selection_modes"]["exploration"]["count"], 1)
        self.assertEqual(len(weak_records), 2)
        self.assertTrue(
            all(len(record["target_vector"]) == 26 for record in weak_records)
        )
        self.assertEqual(weak_metrics["model"]["rollouts"], 2)
        self.assertEqual(
            sum(
                mode["count"]
                for mode in weak_metrics["selection_modes"].values()
            ),
            2,
        )
        self.assertTrue(coverage["semantics"]["graph_revisits_enabled"])
        self.assertTrue(coverage["semantics"]["mapping_revisits_enabled"])
        self.assertTrue(coverage["semantics"]["weak_order_revisits_enabled"])
        self.assertEqual(coverage["levels"]["graph"]["permanently_closed"], 0)
        self.assertEqual(coverage["levels"]["mapping"]["permanently_closed"], 0)
        self.assertEqual(
            coverage["levels"]["weak_order"]["permanently_closed"], 0
        )
        self.assertEqual(coverage["levels"]["mapping"]["proposals"]["count"], 2)
        self.assertEqual(coverage["levels"]["mapping"]["rollouts"]["count"], 1)

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
