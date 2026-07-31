import unittest

from formal_disk4.constraints.angle_lp import AngleFeasibilityOracle
from formal_disk4.constraints.length_lp import LengthFeasibilityOracle
from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.enumeration.weak_orders import WeakOrderEnumerator
from formal_disk4.maps import build_k4_central_map


class WeakOrderTests(unittest.TestCase):
    def test_first_survivor_has_all_constraints(self) -> None:
        planar_map = build_k4_central_map()
        assignments = AssignmentEnumerator(
            planar_map,
            allow_reflections=True,
            symmetry_mode="incremental",
        )
        assignment = next(assignments.enumerate())
        nodes = 0

        def event(name: str, amount: int) -> None:
            nonlocal nodes
            if name == "placement_nodes":
                nodes += amount

        enumerator = WeakOrderEnumerator(
            planar_map,
            assignment,
            assignments.occurrence_names,
            LengthFeasibilityOracle(),
            AngleFeasibilityOracle(),
            event_sink=event,
            stop_predicate=lambda: nodes >= 20_000,
        )
        placement = next(enumerator.enumerate())
        self.assertEqual(len(placement.length_rows), 6)
        self.assertEqual(len(placement.angle_equations), 6)
        # Float LPs are pruning oracles only. An inconclusive result is kept
        # conservatively and is represented by a zero margin with no witness.
        self.assertGreaterEqual(placement.length_margin, 0.0)
        self.assertGreaterEqual(placement.angle_margin, 0.0)
        if placement.length_margin > 0.0:
            self.assertTrue(placement.length_witness)
        if placement.angle_margin > 0.0:
            self.assertTrue(placement.angle_witness)


if __name__ == "__main__":
    unittest.main()
