from __future__ import annotations

import random
import unittest
from dataclasses import replace
from pathlib import Path

from formal_disk4.graph_lab.space import (
    GraphSpace,
    build_dynamic_planar_map,
    candidate_from_planar_map,
    validate_dual_graph,
)
from formal_disk4.graph_lab.evaluator import GraphFormalEvaluator
from formal_disk4.graph_lab.mapping_model import MappingLearningModel
from formal_disk4.pipeline.filter_report import LEARNING_FILTER_IDS


class GraphLabSpaceTests(unittest.TestCase):
    def test_known_templates_are_a_statistical_prior_not_labelled_controls(self) -> None:
        space = GraphSpace(
            maximum_tiles=4,
            imposed_symmetry_bias=0.0,
            known_prior_fraction=1.0,
            known_prior_mutation_fraction=0.0,
            known_seeds=({"map": "c4"},),
        )
        template = candidate_from_planar_map(
            "c4", imposed_automorphism=None
        )
        sampled = space.sample_prior(random.Random(7))

        self.assertEqual(sampled.edges, template.edges)
        self.assertEqual(sampled.origin, "prior")
        self.assertEqual(sampled.mutation, "known_template")
        self.assertIsNone(sampled.source_map_name)

    def test_mapping_pool_ranker_and_stochastic_rollout_share_the_filter_contract(self) -> None:
        root = Path(__file__).resolve().parents[1]
        evaluator = GraphFormalEvaluator(
            root,
            {
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
        )
        candidate = candidate_from_planar_map("c3", imposed_automorphism=None)
        pool = evaluator.mapping_pool(candidate, random.Random(17), 3)
        self.assertEqual(len(pool), 3)
        self.assertEqual(len({item.mapping_id for item in pool}), 3)

        model = MappingLearningModel(
            {"hidden_size": 8, "message_layers": 1, "torch_threads": 1}
        )
        prediction = model.predict(pool[0])
        self.assertEqual(
            len(prediction.conditional_probabilities), len(LEARNING_FILTER_IDS)
        )
        observation = evaluator.evaluate_mapping(
            pool[0], rollouts=2, random_seed=123
        )
        self.assertIsNone(observation.error)
        self.assertEqual(observation.rollout_count, 2)
        self.assertEqual(
            tuple(item.filter_id for item in observation.filters.observations),
            LEARNING_FILTER_IDS,
        )

    def test_generated_graph_runs_through_the_production_solver(self) -> None:
        root = Path(__file__).resolve().parents[1]
        evaluator = GraphFormalEvaluator(
            root,
            {
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
        )
        source = candidate_from_planar_map(
            "c4", imposed_automorphism=None
        )
        candidate = replace(
            source,
            source_map_name=None,
            source_symmetry=None,
            origin="test",
            mutation="dynamic_reconstruction",
        )
        evaluation = evaluator.evaluate(candidate)
        self.assertIsNone(evaluation.error)
        self.assertGreaterEqual(evaluation.stage_index, 1)
        self.assertGreater(evaluation.counters.get("assignments_processed", 0), 0)

        centered = candidate_from_planar_map(
            "centered-double-cycle-6", imposed_automorphism="rotation_1"
        )
        centered_evaluation = evaluator.evaluate(centered)
        self.assertIsNone(centered_evaluation.error)

    def test_known_positive_dual_graphs_are_in_the_space(self) -> None:
        for name, symmetry, mode in (
            ("c3", None, None),
            ("c4", None, None),
            ("double-cycle-6", "rotation_1", "pointwise"),
            ("double-cycle-offset-6", "rotation_1", "pointwise"),
            ("centered-double-cycle-6", "rotation_1", "cyclic_shift"),
        ):
            with self.subTest(name=name):
                candidate = candidate_from_planar_map(
                    name, imposed_automorphism=symmetry
                )
                validate_dual_graph(candidate.graph(), maximum_tiles=13)
                dynamic = build_dynamic_planar_map(candidate)
                dynamic.planar_map.validate()
                self.assertEqual(len(dynamic.planar_map.pieces), candidate.tile_count)
                self.assertEqual(dynamic.imposed_automorphism, symmetry)
                self.assertEqual(dynamic.imposed_equivariance_mode, mode)

    def test_reconstructed_polyhedral_map_is_formally_valid(self) -> None:
        source = candidate_from_planar_map(
            "double-cycle-offset-4", imposed_automorphism="rotation_1"
        )
        generated = replace(
            source,
            source_map_name=None,
            source_symmetry=None,
            origin="test",
            mutation="reconstruct",
        )
        dynamic = build_dynamic_planar_map(generated)
        dynamic.planar_map.validate()
        self.assertIsNotNone(dynamic.imposed_automorphism)
        self.assertEqual(len(dynamic.planar_map.pieces), 8)

    def test_prior_and_mutations_stay_valid_and_bounded(self) -> None:
        space = GraphSpace(
            maximum_tiles=13,
            symmetric_prior_fraction=0.5,
            imposed_symmetry_bias=0.75,
        )
        rng = random.Random(12345)
        candidate = space.sample_prior(rng)
        for _ in range(20):
            validate_dual_graph(candidate.graph(), maximum_tiles=13)
            build_dynamic_planar_map(candidate).planar_map.validate()
            mutated = space.mutate(candidate, rng)
            if mutated is not None:
                candidate = mutated


if __name__ == "__main__":
    unittest.main()
