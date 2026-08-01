import unittest

from formal_disk4.words.algebra import Equation, Literal, simplify_system, substitute_equations
from formal_disk4.words.exact_partial import (
    ExactPartialWordSolver,
    SolverLimits,
    _classify_fixed_context_loop,
    _simplify_system_fast,
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

    def test_external_stop_interrupts_residual_graph(self) -> None:
        solver = ExactPartialWordSolver(
            (Equation(word("A", "B"), word("B", "A")),),
            ("A", "B"),
        )
        self.assertEqual(
            list(
                solver.solve(
                    SolverLimits(
                        max_graph_nodes=1000,
                        max_graph_edges=4000,
                        max_families=8,
                        max_expression_nodes=1000,
                        validation_exponent=2,
                    ),
                    stop_predicate=lambda: True,
                )
            ),
            [],
        )
        self.assertEqual(solver.last_summary.status, "interrupted_external_stop")
        self.assertTrue(solver.last_summary.external_stop_reached)

    def test_residual_literal_budget_defers_growth_before_canonicalization(self) -> None:
        solver = ExactPartialWordSolver(
            (Equation(word("A", "B"), word("B", "A")),),
            ("A", "B"),
        )
        self.assertEqual(
            list(
                solver.solve(
                    SolverLimits(
                        max_graph_nodes=100,
                        max_graph_edges=400,
                        max_residual_literals=0,
                    )
                )
            ),
            [],
        )
        self.assertEqual(
            solver.last_summary.status,
            "unresolved_residual_literal_limit",
        )
        self.assertTrue(solver.last_summary.residual_literal_limit_reached)
        self.assertEqual(
            solver.progress_snapshot()["phase"],
            "done",
        )

    def test_fast_simplifier_matches_reference_on_long_cancellation(self) -> None:
        prefix = tuple(Literal("P") for _ in range(200))
        suffix = tuple(Literal("S") for _ in range(200))
        equations = (
            Equation(prefix + word("X") + suffix, prefix + word("Y") + suffix),
            Equation(word("A", "B"), word("A", "B")),
        )
        self.assertEqual(_simplify_system_fast(equations), simplify_system(equations))

    def test_growth_regression_preserves_graph_semantics(self) -> None:
        equations = (
            Equation(
                (Literal("X0"), Literal("X0"), Literal("X0", True)),
                (Literal("X1", True), Literal("X0", True), Literal("X0")),
            ),
        )
        solver = ExactPartialWordSolver(equations, ("X0", "X1"))
        families = list(
            solver.solve(
                SolverLimits(
                    max_graph_nodes=120,
                    max_graph_edges=480,
                    max_families=16,
                    max_expression_nodes=2000,
                )
            )
        )
        self.assertEqual([family.kind for family in families], ["finite"])
        self.assertEqual(solver.last_summary.visited_states, 120)
        self.assertEqual(solver.last_summary.graph_edges, 352)
        self.assertEqual(solver.last_summary.status, "unresolved_graph_limit")
        progress = solver.progress_snapshot()
        self.assertEqual(progress["phase"], "done")
        self.assertEqual(progress["visited_states"], 120)
        self.assertEqual(progress["graph_edges"], 352)


    def test_terminal_contour_cutoff_tracks_only_physical_variables(self) -> None:
        equations = (Equation(word("X"), word("M_X")),)

        allowed = ExactPartialWordSolver(
            equations,
            ("X", "M_X"),
            contour_variables=("X",),
        )
        families = list(
            allowed.solve(
                SolverLimits(
                    max_graph_nodes=50,
                    max_graph_edges=100,
                    max_terminal_contour_segments=1,
                )
            )
        )
        self.assertEqual([family.kind for family in families], ["finite"])
        self.assertEqual(allowed.last_summary.terminal_contour_pruned, 0)

        blocked = ExactPartialWordSolver(
            equations,
            ("X", "M_X"),
            contour_variables=("X",),
        )
        self.assertEqual(
            list(
                blocked.solve(
                    SolverLimits(
                        max_graph_nodes=50,
                        max_graph_edges=100,
                        max_terminal_contour_segments=0,
                    )
                )
            ),
            [],
        )
        self.assertEqual(blocked.last_summary.terminal_contour_pruned, 1)
        self.assertEqual(
            blocked.last_summary.status,
            "restricted_terminal_contour_limit",
        )
        progress = blocked.progress_snapshot()
        self.assertEqual(progress["terminal_limit"], 0)
        self.assertEqual(progress["terminal_pruned"], 1)





if __name__ == "__main__":
    unittest.main()
