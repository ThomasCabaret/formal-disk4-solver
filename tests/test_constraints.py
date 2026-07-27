import unittest

from formal_disk4.constraints.angle_lp import AngleEquation, AngleFeasibilityOracle
from formal_disk4.constraints.length_lp import LengthFeasibilityOracle


class ConstraintTests(unittest.TestCase):
    def test_length_feasible(self) -> None:
        oracle = LengthFeasibilityOracle()
        result = oracle.analyze(3, ((1, -1, 0),), need_witness=True)
        self.assertTrue(result.feasible)
        self.assertGreater(result.margin, 0.0)
        self.assertAlmostEqual(sum(result.lengths), 1.0)

    def test_length_containment_contradiction(self) -> None:
        oracle = LengthFeasibilityOracle()
        result = oracle.analyze(3, ((1, 1, 0),))
        self.assertFalse(result.feasible)

    def test_angle_coincidence_contradiction(self) -> None:
        oracle = AngleFeasibilityOracle()
        equations = (
            AngleEquation((3,), 2.0),
            AngleEquation((2,), 1.0),
        )
        result = oracle.analyze(1, equations)
        self.assertFalse(result.feasible)

    def test_complementary_copy_angles_can_be_detected_early(self) -> None:
        oracle = AngleFeasibilityOracle()
        # Two occurrences with opposite contour orientations at the same prototype
        # point cancel in the signed-turn equation. They cannot form a boundary
        # vertex whose total interior angle is pi, because alpha+(2-alpha)=2pi.
        result = oracle.analyze(1, (AngleEquation((0,), 1.0),))
        self.assertFalse(result.feasible)


if __name__ == "__main__":
    unittest.main()
