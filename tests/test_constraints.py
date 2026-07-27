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

    def test_copy_reflection_does_not_complement_solid_angle(self) -> None:
        oracle = AngleFeasibilityOracle()
        # Two congruent occurrences of the same prototype point can meet on the
        # disk boundary.  Reflection preserves the positive polygonal angle, so
        # 2*alpha = pi, equivalently 2*tau = 1 in pi units.
        result = oracle.analyze(1, (AngleEquation((2,), 1.0),), need_witness=True)
        self.assertTrue(result.feasible)
        self.assertAlmostEqual(result.angles_pi[0], 0.5)

    def test_three_piece_interior_junction_forces_two_thirds_angle(self) -> None:
        oracle = AngleFeasibilityOracle()
        # 3*alpha = 2*pi, hence 3*tau = 1.
        result = oracle.analyze(1, (AngleEquation((3,), 1.0),), need_witness=True)
        self.assertTrue(result.feasible)
        self.assertAlmostEqual(result.angles_pi[0], 2.0 / 3.0)

    def test_three_piece_outer_junction_forces_one_third_angle(self) -> None:
        oracle = AngleFeasibilityOracle()
        # 3*alpha = pi, hence 3*tau = 2.
        result = oracle.analyze(1, (AngleEquation((3,), 2.0),), need_witness=True)
        self.assertTrue(result.feasible)
        self.assertAlmostEqual(result.angles_pi[0], 1.0 / 3.0)


if __name__ == "__main__":
    unittest.main()
