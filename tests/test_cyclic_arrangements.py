from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from formal_disk4.config import load_config
from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.enumeration.cyclic_arrangements import CyclicArrangementEnumerator
from formal_disk4.enumeration.frontier_arrangements import (
    FrontierArrangementEnumerator,
    PartialValidationResult,
)
from formal_disk4.graph_lab.free_outer_boundary import relax_outer_boundary
from formal_disk4.graph_lab.evaluator import GraphFormalEvaluator
from formal_disk4.graph_lab.space import (
    OUTSIDE,
    DualGraphCandidate,
    build_dynamic_planar_map,
    candidate_from_planar_map,
)
from formal_disk4.maps.registry import build_map
from formal_disk4.pipeline import (
    FormalSolverAPI,
    PlacementSelection,
    SolverAPIRequest,
)
from formal_disk4.preword import (
    PrewordLinearInvariantFilter,
    PrewordPruningPipeline,
    RadiusArcTopologyFilter,
)
from formal_disk4.words.compile import compile_word_case


def _square_grid_candidate() -> DualGraphCandidate:
    edges = []
    edges.extend(
        (row * 3 + column, row * 3 + column + 1)
        for row in range(3)
        for column in range(2)
    )
    edges.extend(
        (row * 3 + column, (row + 1) * 3 + column)
        for row in range(2)
        for column in range(3)
    )
    outer = (0, 1, 2, 3, 5, 6, 7, 8)
    edges.extend((OUTSIDE, tile) for tile in outer)
    return DualGraphCandidate(
        tile_count=9,
        edges=tuple(sorted(edges)),
        imposed_permutation=(2, 5, 8, 1, 4, 7, 0, 3, 6),
        origin="positive_control",
        mutation="square_grid_3x3",
        stein_center_tile=4,
    )


def _free_square_grid():
    return relax_outer_boundary(build_dynamic_planar_map(_square_grid_candidate()))


class CyclicArrangementTests(unittest.TestCase):
    def test_tile_frontier_search_adds_complete_tiles_and_reaches_same_small_case(self) -> None:
        planar_map = build_map("k3-pizza")
        visited = []

        def observe(state):
            visited.append(
                (
                    state.last_piece_index,
                    len(state.placed_piece_indices),
                    len(state.remaining_piece_indices),
                )
            )
            return PartialValidationResult(True)

        search = FrontierArrangementEnumerator(
            planar_map,
            partial_validators=(observe,),
            max_nodes=100,
        )

        placement = next(search.enumerate(), None)

        self.assertIsNotNone(placement)
        self.assertTrue(visited)
        self.assertEqual(visited[0][1:], (1, 2))
        self.assertEqual(visited[-1][1:], (3, 0))
        self.assertEqual(
            {occurrence for block in placement.blocks for occurrence in block},
            set(range(len(planar_map.occurrences()))),
        )

    def test_tile_frontier_partial_validator_prunes_before_a_complete_mapping(self) -> None:
        planar_map = build_map("k3-pizza")
        visited_depths = []

        def reject_second_tile(state):
            depth = len(state.placed_piece_indices)
            visited_depths.append(depth)
            return depth < 2

        search = FrontierArrangementEnumerator(
            planar_map,
            partial_validators=(reject_second_tile,),
            max_nodes=100,
        )

        self.assertEqual(list(search.enumerate()), [])
        self.assertIn(2, visited_depths)
        self.assertNotIn(3, visited_depths)

    def test_tile_frontier_marks_uncertified_partial_pruning(self) -> None:
        planar_map = build_map("k3-pizza")

        def bounded_numerical_screen(state):
            if len(state.placed_piece_indices) >= 2:
                return PartialValidationResult(
                    False,
                    "bounded geometry did not find a witness",
                    certified=False,
                )
            return True

        search = FrontierArrangementEnumerator(
            planar_map,
            partial_validators=(bounded_numerical_screen,),
            max_nodes=100,
        )

        self.assertEqual(list(search.enumerate()), [])
        self.assertTrue(search.heuristic_pruning_used)

    def test_tile_frontier_prefers_the_tile_closing_most_exposed_interfaces(self) -> None:
        dynamic = _free_square_grid()
        search = FrontierArrangementEnumerator(dynamic.planar_map, max_nodes=1)
        reference = search.reference_index
        remaining = tuple(
            piece
            for piece in range(len(search.piece_names))
            if piece != reference
        )

        first = search._select_next_piece((reference,), remaining)
        second = search._select_next_piece(
            (reference, first),
            tuple(piece for piece in remaining if piece != first),
        )

        self.assertIn(first, search._piece_neighbors[reference])
        self.assertGreaterEqual(
            sum(
                neighbor in {reference, first}
                for neighbor in search._piece_neighbors[second]
            ),
            1,
        )

    def test_mapping_and_weak_order_are_built_in_one_small_tree(self) -> None:
        planar_map = build_map("k3-pizza")
        search = CyclicArrangementEnumerator(planar_map, max_nodes=100)

        placement = next(search.enumerate(), None)

        self.assertIsNotNone(placement)
        self.assertLessEqual(search.statistics.nodes, 4)
        self.assertEqual(len(placement.blocks), 3)
        self.assertEqual(
            {len(block) for block in placement.blocks},
            {3},
        )

    def test_square_grid_c4_is_found_from_graph_without_mapping_seed(self) -> None:
        dynamic = _free_square_grid()
        assignments = AssignmentEnumerator(
            dynamic.planar_map, symmetry_mode="off"
        )
        rotation = assignments.transform_for_automorphism(
            dynamic.imposed_automorphism
        )
        reflections = tuple(
            assignments.transform_for_automorphism(name)
            for name in dynamic.imposed_reflections
        )
        search = CyclicArrangementEnumerator(
            dynamic.planar_map,
            required_cyclic_shift_transform=rotation,
            required_reflection_transforms=reflections,
            max_nodes=100,
        )

        placement = next(search.enumerate(), None)

        self.assertIsNotNone(placement)
        self.assertEqual(search.statistics.nodes, 2)
        self.assertEqual(len(placement.blocks), 4)
        # The four corner tiles have their two free square sides represented by
        # one free interface, so the exterior square corner is not a map
        # occurrence.  Each prototype corner block therefore contains the
        # eight marked occurrences; the free curve may contain the unmarked
        # hard point.
        self.assertEqual({len(block) for block in placement.blocks}, {8})
        compiled = compile_word_case(dynamic.planar_map, placement)
        preword = PrewordPruningPipeline(
            topology_filter=RadiusArcTopologyFilter(),
            linear_filter=PrewordLinearInvariantFilter(),
        ).analyze(dynamic.planar_map, placement, compiled)
        self.assertTrue(preword.feasible, preword.reason)

    def test_joint_placement_hands_off_to_shared_formal_kernel(self) -> None:
        planar_map = build_map("k3-pizza")
        placement = next(
            CyclicArrangementEnumerator(planar_map, max_nodes=100).enumerate()
        )
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(None)
            config["maps"] = [planar_map.name]
            config["checkpoint"]["enabled"] = False
            config["progress"]["enabled"] = False
            config["enumeration"]["symmetry_mode"] = "off"
            config["enumeration"]["track_exact_domain_size"] = False
            config["limits"].update(
                {
                    "max_nodes": 500,
                    "max_placements": 1,
                    "max_profiles": 1,
                    "time_limit_seconds": 10,
                }
            )
            config["output"]["directory"] = directory
            result = FormalSolverAPI.evaluate(
                SolverAPIRequest(
                    config=config,
                    planar_maps=(planar_map,),
                    placements=(
                        PlacementSelection(planar_map.name, (placement,)),
                    ),
                    collect_profiles=True,
                )
            )

        counters = result.summary["statistics"]["counters"]
        self.assertEqual(counters["provided_joint_arrangements"], 1)
        self.assertEqual(counters["surviving_placements"], 1)
        self.assertEqual(counters["word_cases_compiled"], 1)
        self.assertEqual(len(result.profiles), 1)

    def test_graph_lab_uses_tile_frontier_engine_without_imposed_symmetry(self) -> None:
        evaluator = GraphFormalEvaluator(
            Path.cwd(),
            {
                "base_search_config": "config/cycle_campaign/search.json",
                "joint_arrangement_search": {
                    "enabled": True,
                    "strategy": "tile_frontier",
                    "max_nodes": 100,
                    "time_limit_seconds": 10,
                },
                "mapping_search_overrides": {
                    "limits": {
                        "max_profiles": 1,
                        "time_limit_seconds": 10,
                        "stop_on_first_profile": True,
                    }
                },
            },
        )

        evaluation = evaluator.evaluate_joint_arrangements(
            candidate_from_planar_map("k3-pizza", imposed_automorphism=None)
        )

        self.assertFalse(evaluation.tainted, evaluation.error)
        self.assertEqual(
            evaluation.counters.get("arrangement_engine_tile_frontier"), 1
        )
        self.assertGreater(
            evaluation.counters.get("frontier_tile_nodes", 0), 0
        )
        self.assertGreaterEqual(len(evaluation.profiles), 1)

    def test_graph_lab_consumes_every_leaf_without_a_placement_batch_cap(self) -> None:
        evaluator = GraphFormalEvaluator(
            Path.cwd(),
            {
                "base_search_config": "config/cycle_campaign/search.json",
                "joint_arrangement_search": {
                    "enabled": True,
                    "strategy": "tile_frontier",
                    "max_nodes": 100,
                    # This retired option used to stop the live backtracker
                    # after one leaf.  Keeping it here proves it is ignored.
                    "max_placements": 1,
                    "time_limit_seconds": 10,
                },
                "mapping_search_overrides": {
                    "limits": {
                        "max_profiles": 100,
                        "time_limit_seconds": 10,
                        "stop_on_first_profile": False,
                    }
                },
            },
        )
        requests = []

        def reject_leaf(request):
            requests.append(request)
            return SimpleNamespace(
                summary={
                    "tainted": False,
                    "statistics": {
                        "counters": {
                            "provided_joint_arrangements": 1,
                            "preword_rejections": 1,
                        },
                        "stop_reason": "completed",
                    },
                },
                profiles=(),
            )

        with patch(
            "formal_disk4.graph_lab.evaluator.FormalSolverAPI.evaluate",
            side_effect=reject_leaf,
        ):
            evaluation = evaluator.evaluate_joint_arrangements(
                candidate_from_planar_map("k3-pizza", imposed_automorphism=None)
            )

        self.assertGreater(len(requests), 1)
        self.assertEqual(evaluation.stop_reason, "joint_arrangement_node_limit")
        self.assertEqual(
            evaluation.counters["joint_arrangement_kernel_calls"], len(requests)
        )
        self.assertEqual(
            evaluation.counters["joint_arrangement_placements"], len(requests)
        )
        self.assertEqual(
            evaluation.counters["preword_rejections"], len(requests)
        )
        self.assertTrue(
            all(
                len(request.placements[0].placements) == 1
                and request.config["limits"]["max_placements"] is None
                for request in requests
            )
        )

    def test_graph_lab_joint_arrangement_budgets_can_be_unbounded(self) -> None:
        evaluator = GraphFormalEvaluator(
            Path.cwd(),
            {
                "base_search_config": "config/cycle_campaign/search.json",
                "joint_arrangement_search": {
                    "enabled": True,
                    "max_nodes": None,
                    "time_limit_seconds": None,
                },
            },
        )

        self.assertIsNone(evaluator.joint_arrangement_max_nodes)
        self.assertIsNone(evaluator.joint_arrangement_time_limit_seconds)

    def test_euclidean_leaf_audit_observes_without_pruning(self) -> None:
        evaluator = GraphFormalEvaluator(
            Path.cwd(),
            {
                "base_search_config": "config/cycle_campaign/search.json",
                "joint_arrangement_search": {
                    "enabled": True,
                    "strategy": "tile_frontier",
                    "max_nodes": 100,
                    "time_limit_seconds": 10,
                    "euclidean_placement_audit": {
                        "enabled": True,
                        "max_samples": 2,
                        "restarts": 1,
                        "max_nfev": 100,
                    },
                },
                "mapping_search_overrides": {
                    "limits": {
                        "max_profiles": 100,
                        "time_limit_seconds": 10,
                        "stop_on_first_profile": False,
                    }
                },
            },
        )

        def reject_leaf(_request):
            return SimpleNamespace(
                summary={
                    "tainted": False,
                    "statistics": {
                        "counters": {"preword_rejections": 1},
                        "stop_reason": "completed",
                    },
                },
                profiles=(),
            )

        with patch(
            "formal_disk4.graph_lab.evaluator.FormalSolverAPI.evaluate",
            side_effect=reject_leaf,
        ):
            evaluation = evaluator.evaluate_joint_arrangements(
                candidate_from_planar_map("k3-pizza", imposed_automorphism=None)
            )

        self.assertEqual(
            evaluation.counters.get("euclidean_placement_audit_attempts"), 2
        )
        self.assertEqual(evaluation.counters.get("euclidean_placement_audits"), 2)
        self.assertGreater(
            evaluation.counters.get("joint_arrangement_kernel_calls", 0), 2
        )
        self.assertFalse(evaluation.tainted)

    def test_graph_lab_profile_consumer_can_stop_on_geometric_solution(self) -> None:
        evaluator = GraphFormalEvaluator(
            Path.cwd(),
            {
                "base_search_config": "config/cycle_campaign/search.json",
                "joint_arrangement_search": {
                    "enabled": True,
                    "strategy": "tile_frontier",
                    "max_nodes": None,
                    "time_limit_seconds": None,
                },
                "mapping_search_overrides": {
                    "limits": {
                        "max_profiles": None,
                        "time_limit_seconds": None,
                        "stop_on_first_profile": False,
                    }
                },
            },
        )
        consumed = []

        def emit_profile(_request):
            return SimpleNamespace(
                summary={
                    "tainted": False,
                    "statistics": {
                        "counters": {
                            "provided_joint_arrangements": 1,
                            "profiles_emitted": 1,
                        },
                        "stop_reason": "completed",
                    },
                },
                profiles=({"formal_profile_id": "fp-test"},),
            )

        with patch(
            "formal_disk4.graph_lab.evaluator.FormalSolverAPI.evaluate",
            side_effect=emit_profile,
        ):
            evaluation = evaluator.evaluate_joint_arrangements(
                candidate_from_planar_map("k3-pizza", imposed_automorphism=None),
                profile_consumer=lambda profile: consumed.append(profile) or True,
            )

        self.assertEqual(consumed, [{"formal_profile_id": "fp-test"}])
        self.assertEqual(
            evaluation.stop_reason, "joint_arrangement_external_solution"
        )

    def test_graph_lab_joint_entry_point_reaches_a_profile_on_square_grid(self) -> None:
        evaluator = GraphFormalEvaluator(
            Path.cwd(),
            {
                "base_search_config": "config/cycle_campaign/search.json",
                "free_outer_boundary": True,
                "joint_arrangement_search": {
                    "enabled": True,
                    "max_nodes": 100,
                    "time_limit_seconds": 10,
                },
                "mapping_search_overrides": {
                    "limits": {
                        "max_profiles": 1,
                        "time_limit_seconds": 5,
                        "stop_on_first_profile": True,
                    }
                },
            },
        )

        evaluation = evaluator.evaluate_joint_arrangements(
            _square_grid_candidate()
        )

        self.assertFalse(evaluation.tainted, evaluation.error)
        self.assertEqual(evaluation.stage_name, "geometry_ready")
        self.assertGreaterEqual(
            evaluation.counters.get("provided_joint_arrangements", 0), 1
        )
        self.assertGreaterEqual(len(evaluation.profiles), 1)

    def test_pointwise_double_cycle_positive_control_reaches_profile(self) -> None:
        evaluator = GraphFormalEvaluator(
            Path.cwd(),
            {
                "base_search_config": "config/cycle_campaign/search.json",
                "joint_arrangement_search": {
                    "enabled": True,
                    "max_nodes": 200_000,
                    "time_limit_seconds": 10,
                },
                "mapping_search_overrides": {
                    "limits": {
                        "max_profiles": 1,
                        "time_limit_seconds": 10,
                        "stop_on_first_profile": True,
                    },
                    "solver": {
                        "max_seconds_per_word_case": 2,
                        "max_graph_nodes_per_placement": 10_000,
                    },
                },
            },
        )
        candidate = candidate_from_planar_map(
            "double-cycle-offset-6", imposed_automorphism="rotation_1"
        )

        evaluation = evaluator.evaluate_joint_arrangements(candidate)

        self.assertFalse(evaluation.tainted, evaluation.error)
        self.assertEqual(evaluation.stage_name, "geometry_ready")
        self.assertGreaterEqual(len(evaluation.profiles), 1)
        self.assertGreater(
            evaluation.counters.get("provided_joint_arrangements", 0), 0
        )


if __name__ == "__main__":
    unittest.main()
