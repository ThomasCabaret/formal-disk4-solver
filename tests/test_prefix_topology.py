from __future__ import annotations

import unittest

from formal_disk4.constraints.angle_lp import AngleFeasibilityOracle
from formal_disk4.constraints.length_lp import LengthFeasibilityOracle
from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.enumeration.weak_orders import WeakOrderEnumerator
from formal_disk4.maps.registry import build_map
from formal_disk4.preword.arc_topology import RadiusArcTopologyFilter
from formal_disk4.preword.prefix_topology import PrefixRadiusArcTopologyFilter
from formal_disk4.words.compile import compile_word_case


class PrefixRadiusArcTopologyTests(unittest.TestCase):
    def test_prefix_pruning_only_removes_complete_topology_rejections(self) -> None:
        planar_map = build_map("inner-cycle-boundary-points-3")
        assignments = AssignmentEnumerator(
            planar_map,
            symmetry_mode="incremental",
            required_equivariance="rotation_1",
        )
        assignment = next(assignments.enumerate())
        common = dict(
            planar_map=planar_map,
            assignment=assignment,
            occurrence_names=assignments.occurrence_names,
            length_oracle=LengthFeasibilityOracle(),
            angle_oracle=AngleFeasibilityOracle(),
            symmetry_mode="incremental",
            enable_length_filter=True,
            enable_angle_filter=True,
            enable_exterior_arc_repetition_filter=True,
            track_exact_leaf_mass=False,
            required_equivariance_transform=assignments.required_transform(assignment),
            equivariance_piece_orbits=assignments.equivariance_piece_orbits,
            mapping_symmetry=assignments.mapping_symmetry,
        )
        baseline = {
            placement.blocks: placement
            for placement in WeakOrderEnumerator(**common).enumerate()
        }
        prefix_filter = PrefixRadiusArcTopologyFilter(
            planar_map, assignment, max_intervals=4096
        )
        pruned = {
            placement.blocks: placement
            for placement in WeakOrderEnumerator(
                **common, prefix_topology_filter=prefix_filter
            ).enumerate()
        }
        omitted = set(baseline) - set(pruned)
        self.assertGreater(len(omitted), 0)
        complete_filter = RadiusArcTopologyFilter(max_intervals=4096)
        for blocks in omitted:
            placement = baseline[blocks]
            result = complete_filter.analyze(
                planar_map,
                placement,
                compile_word_case(planar_map, placement),
            )
            self.assertFalse(result.feasible, blocks)


if __name__ == "__main__":
    unittest.main()
