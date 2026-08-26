from __future__ import annotations

import unittest

from formal_disk4.words.algebra import Equation, Literal
from formal_disk4.words.compile import (
    CompiledInterface,
    CompiledWordCase,
    TerminalMappingInfeasible,
    build_terminal_contact_system,
)


class MirrorTerminalRefinementTests(unittest.TestCase):
    def test_endpoint_swapping_fixed_atom_becomes_two_formal_halves(self) -> None:
        compiled = CompiledWordCase(
            atomic_variables=("X",),
            contour_word=(Literal("X"),),
            equations=(),
            interfaces=(),
            outer_arcs=(),
            mirror_variables=(("X", "M_X"),),
        )

        terminal = build_terminal_contact_system(
            compiled,
            {
                "X": (Literal("A"),),
                "M_X": (Literal("A", True),),
            },
        )

        self.assertEqual(len(terminal.terminal_contour), 2)
        left, right = terminal.terminal_contour
        self.assertNotEqual(left.variable, right.variable)
        self.assertEqual(
            tuple(item.boundary_index for item in terminal.forced_smooth_boundaries),
            (1,),
        )
        self.assertEqual(
            terminal.forced_smooth_boundaries[0].transform,
            "mirror_reverse",
        )
        self.assertTrue(terminal.template_relations)
        self.assertTrue(
            all(
                relation.left_variable != relation.right_variable
                for relation in terminal.template_relations
            )
        )

    def test_constructs_positive_common_refinement_for_reflected_contact(self) -> None:
        x = (Literal("X"),)
        y_inverse = (Literal("Y", True),)
        compiled = CompiledWordCase(
            atomic_variables=("X", "Y"),
            contour_word=(Literal("X"), Literal("Y")),
            equations=(Equation(x, y_inverse),),
            interfaces=(
                CompiledInterface(
                    name="T0-T1",
                    left_piece="P0",
                    right_piece="P1",
                    left_positive_word=x,
                    right_positive_word=y_inverse,
                    equation=Equation(x, y_inverse),
                    relative_parity=-1,
                ),
            ),
            outer_arcs=(),
            mirror_variables=(("X", "M_X"), ("Y", "M_Y")),
        )
        # X=M_Y is already a solved reflected word equation.  The old code
        # nevertheless rejected it because Y and M_Y used 1 versus 2 unit
        # atoms.  A->A0 A1 supplies the exact common refinement.
        environment = {
            "X": (Literal("B"), Literal("B")),
            "M_X": (Literal("A"),),
            "Y": (Literal("A"),),
            "M_Y": (Literal("B"), Literal("B")),
        }

        terminal = build_terminal_contact_system(compiled, environment)

        refined = terminal.environment_map()
        self.assertEqual(len(refined["X"]), 2)
        self.assertEqual(len(refined["Y"]), 2)
        relation_counts = {
            source: sum(
                relation.source == source
                for relation in terminal.template_relations
            )
            for source in ("mirror-involution:X", "mirror-involution:Y")
        }
        self.assertEqual(relation_counts["mirror-involution:X"], 2)
        self.assertEqual(relation_counts["mirror-involution:Y"], 2)
        self.assertEqual(len(terminal.mappings), 1)
        self.assertEqual(len(terminal.mappings[0].pairs), 2)

    def test_rejects_only_when_no_positive_common_refinement_exists(self) -> None:
        compiled = CompiledWordCase(
            atomic_variables=("X", "Y"),
            contour_word=(Literal("X"), Literal("Y")),
            equations=(),
            interfaces=(),
            outer_arcs=(),
            mirror_variables=(("X", "M_X"), ("Y", "M_Y")),
        )
        # len(A)=2 len(B) and len(B)=2 len(A) have no strictly positive
        # solution, so this family really is incompatible with an involution.
        environment = {
            "X": (Literal("A"),),
            "M_X": (Literal("B"), Literal("B")),
            "Y": (Literal("B"),),
            "M_Y": (Literal("A"), Literal("A")),
        }

        with self.assertRaisesRegex(
            TerminalMappingInfeasible,
            "no positive common terminal refinement",
        ):
            build_terminal_contact_system(compiled, environment)


if __name__ == "__main__":
    unittest.main()
