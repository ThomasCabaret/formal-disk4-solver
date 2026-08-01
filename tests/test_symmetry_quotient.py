from __future__ import annotations

import unittest
from collections import defaultdict

from formal_disk4.constraints.angle_lp import AngleFeasibilityOracle
from formal_disk4.constraints.length_lp import LengthFeasibilityOracle
from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.enumeration.weak_orders import WeakOrderEnumerator
from formal_disk4.maps.registry import build_map
from formal_disk4.words.compile import compile_word_case
from formal_disk4.words.exact_partial import canonicalize_residual


class MappingSymmetryQuotientTests(unittest.TestCase):
    @staticmethod
    def _placements(
        map_name: str,
        *,
        symmetry_mode: str,
        required_equivariance: str | None,
    ) -> tuple[AssignmentEnumerator, tuple[tuple[tuple[int, ...], ...], ...]]:
        planar_map = build_map(map_name)
        assignments = AssignmentEnumerator(
            planar_map,
            symmetry_mode=symmetry_mode,
            required_equivariance=required_equivariance,
        )
        blocks = []
        for assignment in assignments.enumerate():
            weak_orders = WeakOrderEnumerator(
                planar_map,
                assignment,
                assignments.occurrence_names,
                LengthFeasibilityOracle(),
                AngleFeasibilityOracle(),
                symmetry_mode=symmetry_mode,
                enable_length_filter=False,
                enable_angle_filter=False,
                enable_exterior_arc_repetition_filter=False,
                track_exact_leaf_mass=False,
                required_equivariance_transform=assignments.required_transform(
                    assignment
                ),
                equivariance_piece_orbits=assignments.equivariance_piece_orbits,
                mapping_symmetry=(
                    assignments.mapping_symmetry
                    if symmetry_mode != "off"
                    else None
                ),
            )
            blocks.extend(placement.blocks for placement in weak_orders.enumerate())
        return assignments, tuple(blocks)

    @staticmethod
    def _cyclic_shift_placements(
        map_name: str,
        *,
        symmetry_mode: str,
        automorphism: str,
    ) -> tuple[AssignmentEnumerator, tuple[tuple[tuple[int, ...], ...], ...]]:
        planar_map = build_map(map_name)
        assignments = AssignmentEnumerator(
            planar_map,
            symmetry_mode=symmetry_mode,
        )
        transform = assignments.transform_for_automorphism(automorphism)
        blocks = []
        for assignment in assignments.enumerate():
            weak_orders = WeakOrderEnumerator(
                planar_map,
                assignment,
                assignments.occurrence_names,
                LengthFeasibilityOracle(),
                AngleFeasibilityOracle(),
                symmetry_mode=symmetry_mode,
                enable_length_filter=False,
                enable_angle_filter=False,
                enable_exterior_arc_repetition_filter=False,
                track_exact_leaf_mass=False,
                required_cyclic_shift_transform=transform,
                mapping_symmetry=(
                    assignments.mapping_symmetry
                    if symmetry_mode != "off"
                    else None
                ),
            )
            blocks.extend(placement.blocks for placement in weak_orders.enumerate())
        return assignments, tuple(blocks)

    def test_exhaustive_orbit_partition_keeps_exactly_one_mapping(self) -> None:
        map_name = "inner-cycle-boundary-points-3"
        raw_assignments, raw_mappings = self._placements(
            map_name,
            symmetry_mode="off",
            required_equivariance="rotation_1",
        )
        quotient_assignments, quotient_mappings = self._placements(
            map_name,
            symmetry_mode="incremental",
            required_equivariance="rotation_1",
        )
        symmetry = quotient_assignments.mapping_symmetry
        raw_orbits = {
            symmetry.canonical_mapping_key(blocks) for blocks in raw_mappings
        }
        quotient_orbits = {
            symmetry.canonical_mapping_key(blocks) for blocks in quotient_mappings
        }

        self.assertEqual(raw_assignments.raw_assignment_count(), 24)
        self.assertEqual(len(raw_mappings), 1584)
        self.assertEqual(quotient_assignments.raw_assignment_count(), 8)
        self.assertEqual(len(raw_orbits), 528)
        self.assertEqual(len(quotient_mappings), 528)
        self.assertEqual(len(set(quotient_mappings)), 528)
        self.assertEqual(quotient_orbits, raw_orbits)

    def test_reflection_quotient_waits_for_the_complete_cyclic_mapping(self) -> None:
        raw_assignments, raw_mappings = self._cyclic_shift_placements(
            "wheel-3",
            symmetry_mode="off",
            automorphism="rotation_1",
        )
        quotient_assignments, quotient_mappings = self._cyclic_shift_placements(
            "wheel-3",
            symmetry_mode="incremental",
            automorphism="rotation_1",
        )
        symmetry = quotient_assignments.mapping_symmetry
        raw_orbits = {
            symmetry.canonical_mapping_key(blocks) for blocks in raw_mappings
        }
        quotient_orbits = {
            symmetry.canonical_mapping_key(blocks) for blocks in quotient_mappings
        }

        self.assertEqual(raw_assignments.raw_assignment_count(), 1536)
        self.assertEqual(len(raw_mappings), 8496)
        self.assertEqual(len(raw_orbits), 1454)
        self.assertEqual(len(quotient_mappings), 1454)
        self.assertEqual(len(set(quotient_mappings)), 1454)
        self.assertEqual(quotient_orbits, raw_orbits)

    def test_orbit_members_compile_to_the_same_canonical_word_system(self) -> None:
        planar_map = build_map("inner-cycle-boundary-points-3")
        raw = AssignmentEnumerator(
            planar_map,
            symmetry_mode="off",
            required_equivariance="rotation_1",
        )
        quotient = AssignmentEnumerator(
            planar_map,
            symmetry_mode="incremental",
            required_equivariance="rotation_1",
        )
        residuals_by_orbit = defaultdict(set)
        for assignment in raw.enumerate():
            weak_orders = WeakOrderEnumerator(
                planar_map,
                assignment,
                raw.occurrence_names,
                LengthFeasibilityOracle(),
                AngleFeasibilityOracle(),
                symmetry_mode="off",
                enable_length_filter=False,
                enable_angle_filter=False,
                enable_exterior_arc_repetition_filter=False,
                track_exact_leaf_mass=False,
                required_equivariance_transform=raw.required_transform(assignment),
                equivariance_piece_orbits=raw.equivariance_piece_orbits,
            )
            for placement in weak_orders.enumerate():
                orbit = quotient.mapping_symmetry.canonical_mapping_key(
                    placement.blocks
                )
                compiled = compile_word_case(planar_map, placement)
                residual = canonicalize_residual(
                    compiled.effective_solver_equations,
                    compiled.solver_variables,
                )
                residuals_by_orbit[orbit].add(
                    None if residual is None else residual.key
                )

        self.assertEqual(len(residuals_by_orbit), 528)
        self.assertTrue(
            all(len(residuals) == 1 for residuals in residuals_by_orbit.values())
        )

    def test_imposed_rotation_uses_only_commuting_intrinsic_symmetries(self) -> None:
        planar_map = build_map("double-cycle-3")
        assignments = AssignmentEnumerator(
            planar_map,
            symmetry_mode="incremental",
            required_equivariance="rotation_1",
        )
        symmetry = assignments.mapping_symmetry
        self.assertEqual(len(symmetry.group), 6)
        self.assertEqual(len(symmetry.quotient_group), 3)
        self.assertEqual(len(symmetry.mapping_actions), 1)
        required = symmetry.action_by_name("rotation_1")
        self.assertTrue(
            all(action.commutes_with(required) for action in symmetry.quotient_group)
        )
        self.assertTrue(
            any(not action.commutes_with(required) for action in symmetry.group)
        )


    def test_assignment_only_equivariance_disables_cyclic_reanchoring(self) -> None:
        planar_map = build_map("inner-cycle-boundary-points-3")
        assignments = AssignmentEnumerator(
            planar_map,
            symmetry_mode="incremental",
            required_equivariance="rotation_1",
            required_equivariance_on_weak_orders=False,
        )
        self.assertFalse(
            assignments.mapping_symmetry.complete_mapping_quotient_enabled
        )
        self.assertEqual(assignments.raw_assignment_count(), 24)

    def test_declared_automorphisms_are_certified_on_campaign_maps(self) -> None:
        names = []
        for size in (3, 4, 5):
            names.extend(
                (
                    f"double-cycle-{size}",
                    f"double-cycle-offset-{size}",
                    f"inner-cycle-boundary-points-{size}",
                    f"outer-cycle-center-points-{size}",
                )
            )
        for name in names:
            with self.subTest(name=name):
                assignments = AssignmentEnumerator(
                    build_map(name),
                    symmetry_mode="incremental",
                    required_equivariance="rotation_1",
                )
                self.assertGreaterEqual(len(assignments.mapping_symmetry.group), 1)
                self.assertGreaterEqual(
                    len(assignments.mapping_symmetry.quotient_group), 1
                )


if __name__ == "__main__":
    unittest.main()
