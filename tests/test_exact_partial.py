import unittest

from formal_disk4.words.algebra import Equation, Literal, simplify_system, substitute_equations
from formal_disk4.words.exact_partial import (
    ExactPartialWordSolver,
    SolverLimits,
    _classify_fixed_context_loop,
)
from formal_disk4.words.families import (
    FamilyExpansionPolicy,
    expand_family,
)


def word(*variables: str):
    return tuple(Literal(variable) for variable in variables)


class ExactPartialSolverTests(unittest.TestCase):
    def test_finite_family(self) -> None:
        equations = (Equation(word("X"), word("Y")),)
        solver = ExactPartialWordSolver(equations, ("X", "Y"))
        families = list(solver.solve(SolverLimits(max_graph_nodes=50, max_graph_edges=100)))
        self.assertEqual([family.kind for family in families], ["finite"])
        specializations = list(
            expand_family(families[0], FamilyExpansionPolicy("range", 2, 10))
        )
        self.assertEqual(len(specializations), 1)
        concrete = specializations[0].environment_map()
        self.assertEqual(simplify_system(substitute_equations(equations, concrete)), ())

    def test_power_and_nested_power_families(self) -> None:
        equations = (Equation(word("X", "Y"), word("Y", "X")),)
        solver = ExactPartialWordSolver(equations, ("X", "Y"))
        families = list(
            solver.solve(
                SolverLimits(
                    max_graph_nodes=200,
                    max_graph_edges=1000,
                    max_families=10,
                )
            )
        )
        kinds = {family.kind for family in families}
        self.assertIn("finite", kinds)
        self.assertIn("power", kinds)
        self.assertIn("nested_power", kinds)
        for family in families:
            for specialization in expand_family(
                family, FamilyExpansionPolicy("range", 2, 20)
            ):
                self.assertEqual(
                    simplify_system(
                        substitute_equations(equations, specialization.environment_map())
                    ),
                    (),
                )

    def test_mutually_evolving_cycle_is_rejected(self) -> None:
        transition = {
            "V0": (Literal("V0"), Literal("V1")),
            "V1": (Literal("V1"), Literal("V0")),
        }
        plan, reason = _classify_fixed_context_loop(("V0", "V1"), transition)
        self.assertIsNone(plan)
        self.assertIn("evolving", reason)


if __name__ == "__main__":
    unittest.main()
