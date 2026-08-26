from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from formal_disk4.config import load_config
from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.enumeration.cyclic_arrangements import CyclicArrangementEnumerator
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

    def test_graph_lab_joint_entry_point_reaches_a_profile_on_square_grid(self) -> None:
        evaluator = GraphFormalEvaluator(
            Path.cwd(),
            {
                "base_search_config": "config/cycle_campaign/search.json",
                "free_outer_boundary": True,
                "joint_arrangement_search": {
                    "enabled": True,
                    "max_nodes": 100,
                    "max_placements": 4,
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
                    "max_placements": 32,
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
