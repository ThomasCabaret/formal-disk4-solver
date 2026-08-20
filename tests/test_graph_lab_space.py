from __future__ import annotations

import random
import unittest
from dataclasses import replace
from pathlib import Path

import networkx as nx

from formal_disk4.constraints.angle_lp import AngleFeasibilityOracle
from formal_disk4.constraints.length_lp import LengthFeasibilityOracle
from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.enumeration.exterior_arc_repetition import (
    build_exterior_arc_repetition_constraint,
)
from formal_disk4.enumeration.weak_orders import WeakOrderEnumerator
from formal_disk4.graph_lab.space import (
    GraphSpace,
    _automorphism_permutations,
    _direct_automorphisms,
    _is_direct_automorphism,
    _permutation_power,
    build_dynamic_planar_map,
    candidate_from_planar_map,
    format_tile_count_spec,
    parse_tile_count_spec,
    parse_symmetry_order_spec,
    validate_dual_graph,
)
from formal_disk4.graph_lab.evaluator import GraphFormalEvaluator
from formal_disk4.graph_lab.mapping_model import MappingLearningModel
from formal_disk4.pipeline.filter_report import LEARNING_FILTER_IDS


class GraphLabSpaceTests(unittest.TestCase):
    def test_symmetry_order_spec_parses_ranges_from_two(self) -> None:
        self.assertEqual(parse_symmetry_order_spec("2-4,6,8"), (2, 3, 4, 6, 8))
        self.assertEqual(parse_symmetry_order_spec((8, 2, 2)), (2, 8))
        for invalid in ("", "1-3", "4-2", "2,,3", "two"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_symmetry_order_spec(invalid)
        with self.assertRaises(ValueError):
            GraphSpace(tile_counts=(5,), symmetry_orders=(2,))
        with self.assertRaises(ValueError):
            GraphSpace(
                tile_counts=(5,),
                stein_symmetric=True,
                stein_symmetry_order_decay=float("nan"),
            )

    def test_stein_mode_keeps_exactly_the_audited_tile_count_support(self) -> None:
        space = GraphSpace(tile_counts="3-13", stein_symmetric=True)

        self.assertEqual(space.requested_tile_counts, tuple(range(3, 14)))
        self.assertEqual(space.tile_counts, (5, 7, 9, 10, 11, 13))
        self.assertEqual(space._stein_feasible_symmetry_orders(5), (2,))
        self.assertEqual(space._stein_feasible_symmetry_orders(7), (2, 3))
        self.assertEqual(space._stein_feasible_symmetry_orders(13), (2, 3, 4, 6))
        with self.assertRaises(ValueError):
            GraphSpace(tile_counts="6,8,12,18", stein_symmetric=True)

    def test_stein_prior_emits_only_full_rotational_orbits_and_a_fixed_center(
        self,
    ) -> None:
        space = GraphSpace(
            tile_counts="5-13",
            stein_symmetric=True,
            symmetric_edge_subset_fraction=0.10,
        )
        rng = random.Random(20260820)
        for _sample in range(20):
            candidate = space.sample_prior(rng)
            self.assertTrue(space.allows_candidate(candidate))
            self.assertIsNotNone(candidate.stein_center_tile)
            assert candidate.imposed_permutation is not None
            assert candidate.stein_center_tile is not None
            fixed = tuple(
                index
                for index, target in enumerate(candidate.imposed_permutation)
                if index == target
            )
            self.assertEqual(fixed, (candidate.stein_center_tile,))
            graph = candidate.graph()
            self.assertFalse(graph.has_edge(-1, candidate.stein_center_tile))
            dynamic = build_dynamic_planar_map(candidate)
            self.assertTrue(
                dynamic.planar_map.hypotheses.center_strictly_inside_one_tile
            )
            self.assertEqual(
                dynamic.planar_map.reference_piece,
                f"T{candidate.stein_center_tile}",
            )
            restored = type(candidate).from_dict(candidate.to_dict())
            self.assertEqual(restored, candidate)
            self.assertEqual(restored.graph_id, candidate.graph_id)

    def test_stein_order_prior_prefers_low_orders_without_closing_high_orders(
        self,
    ) -> None:
        space = GraphSpace(
            tile_counts=(25,),
            stein_symmetric=True,
            stein_symmetry_order_decay=1.25,
        )
        rng = random.Random(20260820)
        counts = {order: 0 for order in (2, 3, 4, 6, 8, 12)}
        for _sample in range(6000):
            action = space._choose_stein_cyclic_action(25, rng)
            assert action is not None
            counts[action[0]] += 1

        self.assertTrue(all(amount > 0 for amount in counts.values()))
        self.assertGreater(counts[2], counts[6])
        self.assertGreater(counts[6], counts[12])

    def test_stein_outer_arc_matching_never_pairs_one_rotation_orbit(self) -> None:
        space = GraphSpace(tile_counts=(5,), stein_symmetric=True)
        candidate = space.sample_prior(random.Random(20260820))
        assert candidate.imposed_permutation is not None
        assert candidate.stein_center_tile is not None
        moving_orbits = tuple(
            orbit
            for orbit in space._tile_orbits(candidate.imposed_permutation)
            if orbit != (candidate.stein_center_tile,)
        )
        self.assertEqual(len(moving_orbits), 2)
        self.assertEqual(
            set(candidate.graph().neighbors(-1)),
            set(range(candidate.tile_count)) - {candidate.stein_center_tile},
        )
        self.assertTrue(
            space._has_two_orbit_stein_reflection(candidate, moving_orbits)
        )
        dynamic = build_dynamic_planar_map(candidate)
        assignments = AssignmentEnumerator(dynamic.planar_map, symmetry_mode="off")
        assignment = assignments.assignment_at(0)
        transform = assignments.transform_for_automorphism(
            dynamic.imposed_automorphism
        )
        occurrences = dynamic.planar_map.occurrences()
        constraint = build_exterior_arc_repetition_constraint(
            dynamic.planar_map,
            assignment.piece_names,
            assignment.sequences,
            {occurrence: index for index, occurrence in enumerate(occurrences)},
            enabled=True,
            imposed_piece_map=transform.piece_map,
        )

        self.assertTrue(constraint.applicable)
        self.assertTrue(constraint.candidate_pairs)
        for left, right in constraint.candidate_pairs:
            left_piece = constraint.arcs[left].piece_index
            right_piece = constraint.arcs[right].piece_index
            self.assertNotEqual(
                transform.piece_map[left_piece],
                right_piece,
            )

    def test_stein_mapping_pool_samples_only_cyclic_shift_compatible_mappings(
        self,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        candidate = GraphSpace(
            tile_counts=(5,), stein_symmetric=True
        ).sample_prior(random.Random(20260820))
        evaluator = GraphFormalEvaluator(
            root,
            {"base_search_config": "config/cycle_campaign/search.json"},
        )
        pool = evaluator.mapping_pool(candidate, random.Random(17), 12)
        self.assertGreater(len(pool), 1)
        self.assertEqual(len({item.raw_assignment_id for item in pool}), len(pool))

        dynamic = build_dynamic_planar_map(candidate)
        self.assertEqual(dynamic.imposed_equivariance_mode, "cyclic_shift")
        assignments = AssignmentEnumerator(
            dynamic.planar_map,
            allow_reflections=True,
            symmetry_mode="incremental",
        )
        transform = assignments.transform_for_automorphism(
            dynamic.imposed_automorphism
        )
        compatible_count = assignments.cyclic_shift_compatible_assignment_count(
            dynamic.imposed_automorphism
        )
        self.assertGreaterEqual(compatible_count, len(pool))
        for proposal in pool:
            weak_orders = WeakOrderEnumerator(
                dynamic.planar_map,
                assignments.assignment_at(proposal.raw_assignment_id),
                assignments.occurrence_names,
                LengthFeasibilityOracle(),
                AngleFeasibilityOracle(),
                symmetry_mode="off",
                enable_length_filter=False,
                enable_angle_filter=False,
                enable_exterior_arc_repetition_filter=False,
                track_exact_leaf_mass=False,
                required_cyclic_shift_transform=transform,
            )
            self.assertTrue(weak_orders._cyclic_shift_splits)

    def test_cyclic_shift_mapping_domain_matches_small_brute_force(self) -> None:
        candidate = GraphSpace(
            tile_counts=(5,), stein_symmetric=True
        ).sample_prior(random.Random(20260820))
        dynamic = build_dynamic_planar_map(candidate)
        assignments = AssignmentEnumerator(
            dynamic.planar_map,
            allow_reflections=True,
            symmetry_mode="incremental",
        )
        transform = assignments.transform_for_automorphism(
            dynamic.imposed_automorphism
        )

        def admits_cyclic_split(raw_assignment_id: int) -> bool:
            weak_orders = object.__new__(WeakOrderEnumerator)
            weak_orders.required_cyclic_shift_transform = transform
            weak_orders._cyclic_shift_order = WeakOrderEnumerator._permutation_order(
                transform.occurrence_map
            )
            weak_orders.piece_names = assignments.piece_names
            weak_orders.assignment = assignments.assignment_at(raw_assignment_id)
            weak_orders.occurrences = dynamic.planar_map.occurrences()
            weak_orders.mapping_subdomain = None
            return bool(weak_orders._build_cyclic_shift_splits())

        brute_force = {
            raw_assignment_id
            for raw_assignment_id in range(assignments.raw_assignment_count())
            if admits_cyclic_split(raw_assignment_id)
        }
        factored = {
            assignments.cyclic_shift_compatible_assignment_at(
                dynamic.imposed_automorphism, compatible_assignment_id
            ).assignment_id
            for compatible_assignment_id in range(
                assignments.cyclic_shift_compatible_assignment_count(
                    dynamic.imposed_automorphism
                )
            )
        }
        self.assertEqual(factored, brute_force)

    def test_stein_generator_is_positive_without_changing_its_subgroup(self) -> None:
        for order in range(2, 10):
            with self.subTest(order=order):
                tile_count = 1 + 2 * order
                candidate = GraphSpace(
                    tile_counts=(tile_count,),
                    stein_symmetric=True,
                    symmetry_orders=(order,),
                ).sample_prior(random.Random(20260820 + order))
                dynamic = build_dynamic_planar_map(candidate)
                planar_map = dynamic.planar_map
                automorphism = next(
                    item
                    for item in planar_map.automorphisms
                    if item.name == dynamic.imposed_automorphism
                )
                center_piece = planar_map.piece_map()[planar_map.reference_piece]
                contour = tuple(center_piece.contour_vertices)
                shift = len(contour) // order
                self.assertEqual(
                    tuple(automorphism.map_vertex(vertex) for vertex in contour),
                    contour[shift:] + contour[:shift],
                )

                original = tuple(candidate.imposed_permutation)
                selected = tuple(
                    int(automorphism.map_piece(f"T{index}")[1:])
                    for index in range(candidate.tile_count)
                )
                self.assertEqual(
                    {
                        _permutation_power(original, exponent)
                        for exponent in range(order)
                    },
                    {
                        _permutation_power(selected, exponent)
                        for exponent in range(order)
                    },
                )
                assignments = AssignmentEnumerator(
                    planar_map,
                    allow_reflections=True,
                    symmetry_mode="incremental",
                )
                self.assertGreater(
                    assignments.cyclic_shift_compatible_assignment_count(
                        dynamic.imposed_automorphism
                    ),
                    0,
                )

    def test_direct_automorphism_predicate_matches_small_exact_enumeration(
        self,
    ) -> None:
        space = GraphSpace(maximum_tiles=7, symmetric_prior_fraction=0.5)
        rng = random.Random(20260815)
        for _sample in range(8):
            candidate = space.sample_prior(rng)
            graph = candidate.graph()
            exact = {
                tuple(int(mapping[index]) for index in range(len(graph) - 1))
                for mapping in nx.algorithms.isomorphism.GraphMatcher(
                    graph, graph
                ).isomorphisms_iter()
                if int(mapping[-1]) == -1
            }
            permutations = set(_automorphism_permutations(graph))
            self.assertEqual(permutations, exact)
            direct = set(_direct_automorphisms(graph))
            for permutation in permutations:
                self.assertEqual(
                    _is_direct_automorphism(graph, permutation),
                    permutation in direct,
                )

    def test_discontinuous_tile_count_spec_round_trips(self) -> None:
        counts = parse_tile_count_spec("3-13,18-19")

        self.assertEqual(counts, (*range(3, 14), 18, 19))
        self.assertEqual(format_tile_count_spec(counts), "3-13,18-19")
        self.assertEqual(parse_tile_count_spec("19,3,18,3"), (3, 18, 19))
        for invalid in ("", "3-", "3-2", "2-4", "3,,4", "three"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    parse_tile_count_spec(invalid)

    def test_discontinuous_size_prior_has_exactly_the_requested_support(self) -> None:
        space = GraphSpace(
            tile_counts="3-13,18-19",
            size_growth_factor=1.4,
            exclude_rings=True,
        )
        distribution = dict(space.size_sampling_distribution())

        self.assertEqual(tuple(distribution), (*range(4, 14), 18, 19))
        self.assertFalse(set(range(14, 18)).intersection(distribution))
        self.assertAlmostEqual(
            distribution[18] / distribution[13], 1.4**5
        )
        self.assertAlmostEqual(distribution[19] / distribution[18], 1.4)
        self.assertAlmostEqual(sum(distribution.values()), 1.0)

    def test_generic_symmetric_scaffolds_support_18_and_19_tiles(self) -> None:
        space = GraphSpace(tile_counts=(18, 19), exclude_rings=True)
        for tile_count in (18, 19):
            with self.subTest(tile_count=tile_count):
                order = 6
                permutation = space._cyclic_permutation(tile_count, order)
                candidate = space._symmetric_scaffold(
                    tile_count,
                    order,
                    permutation,
                    random.Random(tile_count),
                )
                self.assertIsNotNone(candidate)
                assert candidate is not None
                self.assertEqual(candidate.tile_count, tile_count)
                self.assertEqual(candidate.symmetry_order, order)
                validate_dual_graph(candidate.graph(), maximum_tiles=19)
                dynamic = build_dynamic_planar_map(candidate)
                dynamic.planar_map.validate()
                self.assertIsNotNone(dynamic.imposed_automorphism)

    def test_mutation_never_crosses_an_omitted_tile_count_gap(self) -> None:
        space = GraphSpace(tile_counts=(13, 18), exclude_rings=True)
        parent = candidate_from_planar_map(
            "centered-double-cycle-6", imposed_automorphism="rotation_1"
        )
        rng = random.Random(20260815)

        self.assertEqual(parent.tile_count, 13)
        for _ in range(80):
            mutated = space.mutate(parent, rng)
            if mutated is not None:
                self.assertEqual(mutated.tile_count, 13)
                self.assertNotIn(mutated.tile_count, set(range(14, 18)))

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
