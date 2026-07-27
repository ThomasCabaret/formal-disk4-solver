from fractions import Fraction
import unittest

from formal_disk4.profiles.exact_linear import (
    ExactLinearInfeasible,
    solve_exact_linear_system,
)


class ExactLinearTests(unittest.TestCase):
    def test_unique_and_free_expressions(self) -> None:
        solution = solve_exact_linear_system(
            ("x", "y", "z"),
            (
                ({"x": 3}, 2),
                ({"y": 1, "z": 1}, 1),
                ({"y": 1, "z": -1}, 0),
            ),
        )
        expressions = solution.expression_map()
        self.assertEqual(expressions["x"].exact_value, Fraction(2, 3))
        self.assertEqual(expressions["y"].exact_value, Fraction(1, 2))
        self.assertEqual(expressions["z"].exact_value, Fraction(1, 2))
        self.assertEqual(solution.free_parameters, ())

    def test_free_parameter_is_preserved(self) -> None:
        solution = solve_exact_linear_system(
            ("radius", "arc"),
            (({"arc": 3}, 1),),
        )
        expressions = solution.expression_map()
        self.assertIsNone(expressions["radius"].exact_value)
        self.assertEqual(expressions["arc"].exact_value, Fraction(1, 3))
        self.assertEqual(solution.free_parameters, ("radius",))

    def test_inconsistent_system_is_rejected(self) -> None:
        with self.assertRaises(ExactLinearInfeasible):
            solve_exact_linear_system(("x",), (({"x": 1}, 0), ({"x": 1}, 1)))


if __name__ == "__main__":
    unittest.main()
