from fractions import Fraction
import unittest

from formal_disk4.constraints.rational_lp import maximize_free_variables


class RationalLinearProgramTests(unittest.TestCase):
    def test_maximizes_exact_strict_margin_with_free_parameter(self) -> None:
        # max delta subject to delta <= x <= 1-delta and delta <= 1.
        result = maximize_free_variables(
            (
                ((-1, 1), 0),
                ((1, 1), 1),
                ((0, -1), 0),
                ((0, 1), 1),
            ),
            (0, 1),
        )
        self.assertEqual(result.status, "optimal")
        self.assertEqual(result.optimum, Fraction(1, 2))
        self.assertEqual(result.solution[1], Fraction(1, 2))

    def test_detects_infeasibility_exactly(self) -> None:
        # x <= 0 and x >= 1.
        result = maximize_free_variables(
            (
                ((1,), 0),
                ((-1,), -1),
            ),
            (0,),
        )
        self.assertEqual(result.status, "infeasible")

    def test_handles_rational_coefficients(self) -> None:
        result = maximize_free_variables(
            (
                ((Fraction(1, 2),), Fraction(1, 3)),
                ((-1,), 0),
            ),
            (1,),
        )
        self.assertEqual(result.status, "optimal")
        self.assertEqual(result.optimum, Fraction(2, 3))
        self.assertEqual(result.solution, (Fraction(2, 3),))


if __name__ == "__main__":
    unittest.main()
