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
    def test_size_prior_tracks_tempered_combinatorial_growth(self) -> None:
        space = GraphSpace(
            maximum_tiles=13,
            size_growth_factor=1.4,
            exclude_rings=True,
        )
        distribution = dict(space.size_sampling_distribution())

        self.assertEqual(tuple(distribution), tuple(range(4, 14)))
        self.assertAlmostEqual(sum(distribution.values()), 1.0)
        self.assertTrue(all(value > 0.0 for value in distribution.values()))
        for size in range(4, 13):
            self.assertAlmostEqual(
                distribution[size + 1] / distribution[size], 1.4
            )
        self.assertLess(distribution[4], 0.02)
        self.assertGreater(distribution[12], 0.20)
        self.assertGreater(distribution[13], 0.29)

    def test_uniform_size_factor_preserves_full_size_support(self) -> None:
        space = GraphSpace(
            maximum_tiles=13,
            size_growth_factor=1.0,
            exclude_rings=True,
        )
        distribution = dict(space.size_sampling_distribution())

        self.assertEqual(len(set(distribution.values())), 1)
        rng = random.Random(20260815)
        self.assertEqual(
            {space._sample_size(rng) for _ in range(2000)}, set(range(4, 14))
        )

    def test_size_growth_factor_must_keep_full_support(self) -> None:
        for invalid in (0.0, -1.0, float("inf"), float("nan")):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "strictly positive"):
                    GraphSpace(size_growth_factor=invalid)

    def test_symmetric_prior_has_no_catalog_seed_channel(self) -> None:
        space = GraphSpace(maximum_tiles=13, symmetric_prior_fraction=1.0)
        sampled = space.sample_prior(random.Random(7))

        self.assertFalse(hasattr(space, "known_seeds"))
        self.assertEqual(sampled.origin, "prior")
        self.assertIsNone(sampled.source_map_name)
        self.assertIsNone(sampled.source_symmetry)
        self.assertNotIn("known", sampled.mutation)

    def test_ring_exclusion_retains_a_high_symmetry_nonring_prior(self) -> None:
        space = GraphSpace(
            maximum_tiles=13,
            symmetric_prior_fraction=1.0,
            imposed_symmetry_bias=1.0,
            exclude_rings=True,
        )
        rng = random.Random(119)
        samples = [space.sample_prior(rng) for _ in range(80)]

        self.assertTrue(all(not candidate.is_simple_ring for candidate in samples))
        self.assertTrue(all(candidate.symmetry_order > 1 for candidate in samples))
        self.assertGreater(len({candidate.symmetry_order for candidate in samples}), 3)
        self.assertGreater(len({candidate.graph_id for candidate in samples}), 20)
        for candidate in samples:
            validate_dual_graph(candidate.graph(), maximum_tiles=13)
            self.assertIsNotNone(
                build_dynamic_planar_map(candidate).imposed_automorphism
            )

    def test_ring_exclusion_also_filters_the_general_prior_branch(self) -> None:
        space = GraphSpace(
            maximum_tiles=8,
            symmetric_prior_fraction=0.0,
            imposed_symmetry_bias=0.0,
            exclude_rings=True,
        )
        rng = random.Random(211)

        self.assertTrue(
            all(not space.sample_prior(rng).is_simple_ring for _ in range(80))
        )

    def test_larger_cyclic_orders_receive_more_prior_mass(self) -> None:
        flat = GraphSpace(maximum_tiles=13, symmetry_order_bias=0.0)
        biased = GraphSpace(maximum_tiles=13, symmetry_order_bias=2.0)
        flat_rng = random.Random(23)
        biased_rng = random.Random(23)
        flat_orders = [flat._choose_cyclic_action(12, flat_rng)[0] for _ in range(2000)]
        biased_orders = [
            biased._choose_cyclic_action(12, biased_rng)[0] for _ in range(2000)
        ]

        self.assertGreater(
            sum(biased_orders) / len(biased_orders),
            sum(flat_orders) / len(flat_orders) + 2.0,
        )
        self.assertEqual(set(flat_orders), {2, 3, 4, 6, 11, 12})
        self.assertEqual(set(biased_orders), {2, 3, 4, 6, 11, 12})

    def test_generic_scaffolds_cover_multiple_shell_and_subgroup_shapes(self) -> None:
        space = GraphSpace(maximum_tiles=13, exclude_rings=True)
        for tile_count, order in ((8, 2), (9, 3), (12, 2), (12, 4)):
            with self.subTest(tile_count=tile_count, order=order):
                permutation = space._cyclic_permutation(tile_count, order)
                candidate = space._symmetric_scaffold(
                    tile_count,
                    order,
                    permutation,
                    random.Random(tile_count * 100 + order),
                )
                self.assertIsNotNone(candidate)
                assert candidate is not None
                self.assertEqual(candidate.symmetry_order, order)
                self.assertFalse(candidate.is_simple_ring)
                validate_dual_graph(candidate.graph(), maximum_tiles=13)
                self.assertIsNotNone(
                    build_dynamic_planar_map(candidate).imposed_automorphism
                )

    def test_known_positive_graphs_are_only_posthoc_support_oracles(self) -> None:
        """Known answers test support but are never inputs to the sampler."""

        space = GraphSpace(maximum_tiles=13)
        for name in (
            "double-cycle-6",
            "double-cycle-offset-6",
            "inner-cycle-boundary-points-6",
        ):
            with self.subTest(name=name):
                target = candidate_from_planar_map(
                    name, imposed_automorphism="rotation_1"
                )
                self.assertIsNotNone(target.imposed_permutation)
                target_edges = set(target.edges)
                reconstructed: set[tuple[int, int]] = set()
                for orbit in space._all_edge_orbits(
                    target.tile_count, target.imposed_permutation
                ):
                    overlap = target_edges.intersection(orbit)
                    self.assertIn(len(overlap), (0, len(orbit)))
                    if overlap:
                        reconstructed.update(orbit)
                self.assertEqual(reconstructed, target_edges)

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
