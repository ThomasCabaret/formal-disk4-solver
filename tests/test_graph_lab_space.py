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


class GraphLabSpaceTests(unittest.TestCase):
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
