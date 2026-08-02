from __future__ import annotations

import unittest
from pathlib import Path

from formal_disk4.constraints.angle_lp import AngleFeasibilityOracle
from formal_disk4.constraints.length_lp import LengthFeasibilityOracle
from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.enumeration.mapping_subdomain import MappingSubdomain
from formal_disk4.enumeration.weak_orders import WeakOrderEnumerator
from formal_disk4.maps.registry import build_map
from formal_disk4.orchestration.catalog import CaseCatalog
from formal_disk4.preword.arc_topology import RadiusArcTopologyFilter
from formal_disk4.preword.prefix_topology import PrefixRadiusArcTopologyFilter
from formal_disk4.words.compile import compile_word_case


ROOT = Path(__file__).resolve().parents[1]
FERTILE_CASES = {
    "wheel-4-half-turn-fertile-ab": ("rotation_2", 256, 41_163),
    "wheel-6-half-turn-fertile-abc": ("rotation_3", 1, 3_496_514),
}


class MappingSubdomainTests(unittest.TestCase):
    def test_wheel_6_fertile_shard_uses_outer_safe_peripheral_phases(self) -> None:
        case = CaseCatalog.load(ROOT).get("wheel-6-half-turn-fertile-abc")
        raw = case.overrides_for("search")["enumeration"]["mapping_subdomain"]
        self.assertEqual(
            raw["assignment_sequences"]["P0"],
            ["P0:O1", "P0:O0", "P0:I0", "P0:I1"],
        )
        self.assertEqual(
            raw["cyclic_shift_split"],
            {
                "C": 3,
                "P0": 4,
                "P1": 3,
                "P2": 2,
                "P3": 0,
                "P4": 1,
                "P5": 2,
            },
        )

    def test_wheel_6_outer_safe_shard_has_a_complete_topology_survivor(self) -> None:
        case = CaseCatalog.load(ROOT).get("wheel-6-half-turn-fertile-abc")
        enumeration = case.overrides_for("search")["enumeration"]
        planar_map = build_map(case.map_name)
        assignments = AssignmentEnumerator(
            planar_map, allow_reflections=True, symmetry_mode="off"
        )
        shard = MappingSubdomain.from_config(
            planar_map,
            assignments.occurrence_names,
            enumeration["mapping_subdomain"],
        )
        assert shard is not None
        assignment_ids = shard.assignment_ids(assignments)
        self.assertEqual(len(assignment_ids), 1)
        assignment = assignments.assignment_at(assignment_ids[0])
        placement = next(
            WeakOrderEnumerator(
                planar_map,
                assignment,
                assignments.occurrence_names,
                LengthFeasibilityOracle(),
                AngleFeasibilityOracle(),
                symmetry_mode="off",
                track_exact_leaf_mass=False,
                required_cyclic_shift_transform=(
                    assignments.transform_for_automorphism("rotation_3")
                ),
                prefix_topology_filter=PrefixRadiusArcTopologyFilter(
                    planar_map, assignment, max_intervals=4096
                ),
                mapping_subdomain=shard,
            ).enumerate()
        )
        result = RadiusArcTopologyFilter(max_intervals=4096).analyze(
            planar_map,
            placement,
            compile_word_case(planar_map, placement),
        )
        self.assertTrue(result.feasible, result)

    def test_fertile_cases_expose_large_exactly_counted_mapping_domains(self) -> None:
        catalog = CaseCatalog.load(ROOT)
        for case_id, (
            rotation,
            expected_assignment_count,
            expected_mass,
        ) in FERTILE_CASES.items():
            with self.subTest(case_id=case_id):
                case = catalog.get(case_id)
                enumeration = case.overrides_for("search")["enumeration"]
                self.assertEqual(enumeration["symmetry_mode"], "off")
                planar_map = build_map(case.map_name)
                assignments = AssignmentEnumerator(
                    planar_map,
                    allow_reflections=True,
                    symmetry_mode="off",
                )
                shard = MappingSubdomain.from_config(
                    planar_map,
                    assignments.occurrence_names,
                    enumeration["mapping_subdomain"],
                )
                self.assertIsNotNone(shard)
                assert shard is not None
                assignment_ids = shard.assignment_ids(assignments)
                self.assertEqual(len(assignment_ids), expected_assignment_count)
                total_mass = 0
                first_nonempty = None
                for assignment_id in assignment_ids:
                    assignment = assignments.assignment_at(assignment_id)
                    self.assertTrue(shard.allows_assignment(assignment))
                    weak_orders = WeakOrderEnumerator(
                        planar_map,
                        assignment,
                        assignments.occurrence_names,
                        LengthFeasibilityOracle(),
                        AngleFeasibilityOracle(),
                        symmetry_mode="off",
                        enable_length_filter=False,
                        enable_angle_filter=False,
                        enable_exterior_arc_repetition_filter=False,
                        track_exact_leaf_mass=True,
                        required_cyclic_shift_transform=(
                            assignments.transform_for_automorphism(rotation)
                        ),
                        mapping_subdomain=shard,
                    )
                    total_mass += weak_orders.total_leaf_mass
                    if first_nonempty is None and weak_orders.total_leaf_mass:
                        first_nonempty = weak_orders
                self.assertEqual(total_mass, expected_mass)
                self.assertIsNotNone(first_nonempty)
                assert first_nonempty is not None
                placement = next(first_nonempty.enumerate())
                self.assertTrue(shard.allows_leaf(placement.blocks))

                half = len(placement.blocks) // 2
                transform = assignments.transform_for_automorphism(rotation)
                self.assertEqual(len(placement.blocks) % 2, 0)
                for index in range(half):
                    mapped = tuple(
                        sorted(
                            transform.map_occurrence_id(item)
                            for item in placement.blocks[index]
                        )
                    )
                    self.assertEqual(mapped, placement.blocks[index + half])


if __name__ == "__main__":
    unittest.main()
