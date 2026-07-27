import unittest

from formal_disk4.words.algebra import Equation, Literal, substitute_equations, simplify_system
from formal_disk4.words.solver import NielsenLeviSolver, SolverLimits


class WordSolverTests(unittest.TestCase):
    def test_simple_equality(self) -> None:
        equations = (Equation((Literal("X"),), (Literal("Y"),)),)
        solver = NielsenLeviSolver(equations, ("X", "Y"))
        terminals = list(
            solver.solve(
                SolverLimits(
                    max_depth=2,
                    max_states=20,
                    max_terminals=4,
                    max_environment_word_length=10,
                )
            )
        )
        self.assertTrue(terminals)
        for terminal in terminals:
            self.assertEqual(
                simplify_system(substitute_equations(equations, terminal.environment_map())),
                (),
            )

    def test_involutive_equation_generates_palindrome(self) -> None:
        equations = (
            Equation((Literal("X"),), (Literal("X", True),)),
        )
        solver = NielsenLeviSolver(equations, ("X",))
        terminals = list(
            solver.solve(
                SolverLimits(
                    max_depth=2,
                    max_states=20,
                    max_terminals=2,
                    max_environment_word_length=10,
                )
            )
        )
        self.assertTrue(terminals)
        word = terminals[0].environment_map()["X"]
        self.assertEqual(len(word), 2)
        self.assertEqual(word[0].variable, word[1].variable)
        self.assertNotEqual(word[0].inverse, word[1].inverse)


if __name__ == "__main__":
    unittest.main()
