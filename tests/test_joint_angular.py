from fractions import Fraction
import unittest

from formal_disk4.profiles.decorations import (
    DecorationInfeasible,
    MIRROR,
    TemplateTransform,
    _build_joint_angular_feasibility,
)
from formal_disk4.profiles.exact_linear import solve_exact_linear_system
from formal_disk4.words.algebra import Literal


class JointAngularFeasibilityTests(unittest.TestCase):
    def test_straight_one_segment_contour_is_rejected_by_total_turn(self) -> None:
        angle_solution = solve_exact_linear_system(
            ("alpha_B0",),
            [({"alpha_B0": 1}, Fraction(1))],
        )
        length_solution = solve_exact_linear_system(
            ("L_C0",),
            [({"L_C0": 1}, Fraction(1))],
        )
        components = (
            (
                "T0",
                ("T0",),
                {"T0": TemplateTransform()},
                (TemplateTransform(), MIRROR),
                "straight",
            ),
        )
        with self.assertRaises(DecorationInfeasible) as context:
            _build_joint_angular_feasibility(
                terminal_contour=(Literal("T0"),),
                components=components,
                component_by_variable={"T0": 0},
                exact_angle_solution=angle_solution,
                exact_length_solution=length_solution,
                expanded_outer=(),
                piece_orientation_signs={},
            )
        self.assertEqual(context.exception.stage, "joint_angular_feasibility")

    def test_curve_turns_are_unbounded_except_for_exact_relations(self) -> None:
        angle_solution = solve_exact_linear_system(
            ("alpha_B0", "alpha_B1", "alpha_B2"),
            [({"alpha_B0": 1, "alpha_B1": 1, "alpha_B2": 1}, Fraction(3))],
        )
        length_solution = solve_exact_linear_system(
            ("L_C0", "L_C1"),
            [({"L_C0": 1, "L_C1": 1}, Fraction(1))],
        )
        components = (
            (
                "T0",
                ("T0",),
                {"T0": TemplateTransform()},
                (TemplateTransform(),),
                "free",
            ),
            (
                "T1",
                ("T1",),
                {"T1": TemplateTransform()},
                (TemplateTransform(),),
                "free",
            ),
        )
        result = _build_joint_angular_feasibility(
            terminal_contour=(
                Literal("T0"),
                Literal("T0", inverse=True),
                Literal("T1"),
            ),
            components=components,
            component_by_variable={"T0": 0, "T1": 1},
            exact_angle_solution=angle_solution,
            exact_length_solution=length_solution,
            expanded_outer=(),
            piece_orientation_signs={},
        )
        self.assertTrue(result.feasible)
        self.assertGreater(result.strict_margin, 0)
        self.assertIn("K_C0", result.exact_solution.free_parameters)
        self.assertNotIn("K_C1", result.exact_solution.free_parameters)
        total_turn = [
            equation for equation in result.equations
            if equation.kind == "prototype_total_turn"
        ]
        self.assertEqual(len(total_turn), 1)



if __name__ == "__main__":
    unittest.main()
