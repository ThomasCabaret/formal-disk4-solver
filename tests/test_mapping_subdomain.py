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


ROOT = Path(__file__).resolve().parents[1]
FERTILE_CASES = {
    "wheel-4-half-turn-fertile-ab": ("rotation_2", 1),
    "wheel-6-half-turn-fertile-abc": ("rotation_3", 1),
}


class MappingSubdomainTests(unittest.TestCase):
    def test_fertile_cases_select_one_small_nonempty_mapping_shard(self) -> None:
        catalog = CaseCatalog.load(ROOT)
        for case_id, (rotation, expected_mass) in FERTILE_CASES.items():
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
                self.assertEqual(len(assignment_ids), 1)
                assignment = assignments.assignment_at(assignment_ids[0])
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
                self.assertEqual(
                    weak_orders._cyclic_shift_splits,
                    (shard.cyclic_shift_split,),
                )
                self.assertEqual(weak_orders.total_leaf_mass, expected_mass)
                placement = next(weak_orders.enumerate())
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
