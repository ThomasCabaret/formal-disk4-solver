import unittest

from formal_disk4.constraints.angle_lp import AngleFeasibilityOracle
from formal_disk4.constraints.length_lp import LengthFeasibilityOracle
from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.enumeration.weak_orders import Placement, WeakOrderEnumerator
from formal_disk4.maps import build_c3_map, build_c4_map
from formal_disk4.preword import (
    PrewordLinearInvariantFilter,
    PrewordPruningPipeline,
    RadiusArcTopologyFilter,
)
from formal_disk4.words.algebra import Equation, Literal, inverse_word
from formal_disk4.words.compile import (
    CompiledInterface,
    CompiledOuterArc,
    CompiledWordCase,
    compile_word_case,
)


class PrewordCircularArcTests(unittest.TestCase):
    @staticmethod
    def _placement(interval_count: int, rows: tuple[tuple[int, ...], ...]) -> Placement:
        planar_map = build_c3_map()
        assignment = next(
            AssignmentEnumerator(
                planar_map,
                allow_reflections=True,
                symmetry_mode="incremental",
            ).enumerate()
        )
        return Placement(
            placement_id=0,
            assignment=assignment,
            blocks=tuple((index,) for index in range(interval_count)),
            positions=tuple(0 for _ in planar_map.occurrences()),
            length_rows=rows,
            length_margin=0.1,
            length_witness=tuple(1.0 / interval_count for _ in range(interval_count)),
            angle_equations=(),
            angle_margin=0.1,
            angle_witness=(),
        )

    @staticmethod
    def _interface(left, target_same_direction) -> CompiledInterface:
        right_positive = inverse_word(target_same_direction)
        return CompiledInterface(
            name="test-interface",
            left_piece="P0",
            right_piece="P1",
            left_positive_word=tuple(left),
            right_positive_word=right_positive,
            equation=Equation(tuple(left), tuple(target_same_direction)),
            relative_parity=1,
        )

    @staticmethod
    def _pipeline() -> PrewordPruningPipeline:
        return PrewordPruningPipeline(
            topology_filter=RadiusArcTopologyFilter(),
            linear_filter=PrewordLinearInvariantFilter(),
        )

    def test_pizza_three_and_four_pass(self) -> None:
        for planar_map in (build_c3_map(), build_c4_map()):
            assignments = AssignmentEnumerator(
                planar_map,
                allow_reflections=True,
                symmetry_mode="incremental",
            )
            assignment = next(assignments.enumerate())
            placement = next(
                WeakOrderEnumerator(
                    planar_map,
                    assignment,
                    assignments.occurrence_names,
                    LengthFeasibilityOracle(),
                    AngleFeasibilityOracle(),
                ).enumerate()
            )
            result = self._pipeline().analyze(
                planar_map,
                placement,
                compile_word_case(planar_map, placement),
            )
            self.assertTrue(result.feasible, (planar_map.name, result))
            self.assertIsNotNone(result.linear_invariants)
            self.assertTrue(result.linear_invariants.signed_radius_balance_derived)
            self.assertTrue(result.linear_invariants.smooth_turn_balance_derived)
            self.assertTrue(result.linear_invariants.point_turn_balance_derived)

    def test_mapped_circular_arc_cannot_cross_hard_outer_endpoint(self) -> None:
        planar_map = build_c3_map()
        variables = ("X0", "X1", "X2")
        interface = self._interface(
            (Literal("X0"),),
            (Literal("X1"), Literal("X2")),
        )
        compiled = CompiledWordCase(
            atomic_variables=variables,
            contour_word=tuple(Literal(name) for name in variables),
            equations=(interface.equation,),
            interfaces=(interface,),
            outer_arcs=(
                CompiledOuterArc("outer-P0", "P0", (Literal("X0"),)),
                CompiledOuterArc("outer-P1", "P1", (Literal("X1"),)),
                CompiledOuterArc("outer-P2", "P2", (Literal("X2"),)),
            ),
        )
        placement = self._placement(3, ((1, -1, -1),))
        result = RadiusArcTopologyFilter().analyze(planar_map, placement, compiled)
        self.assertFalse(result.feasible)
        self.assertIn("crosses a hard outer endpoint", result.reason)

    def test_convex_concave_sign_conflict_rejects(self) -> None:
        planar_map = build_c3_map()
        variables = ("X0", "X1", "X2")
        interface = self._interface((Literal("X0"),), (Literal("X1"),))
        compiled = CompiledWordCase(
            atomic_variables=variables,
            contour_word=tuple(Literal(name) for name in variables),
            equations=(interface.equation,),
            interfaces=(interface,),
            outer_arcs=(
                CompiledOuterArc("outer-P0", "P0", (Literal("X0"),)),
                CompiledOuterArc("outer-P1", "P1", (Literal("X1"),)),
                CompiledOuterArc("outer-P2", "P2", (Literal("X2"),)),
            ),
        )
        placement = self._placement(3, ((1, -1, 0),))
        result = RadiusArcTopologyFilter().analyze(planar_map, placement, compiled)
        self.assertFalse(result.feasible)
        self.assertIn("opposite circular sign", result.reason)

    def test_general_radius_measure_system_replaces_closed_sign_balance(self) -> None:
        planar_map = build_c3_map()
        variables = ("X0", "X1", "X2")
        interface = self._interface((Literal("X0"),), (Literal("X1"),))
        compiled = CompiledWordCase(
            atomic_variables=variables,
            contour_word=tuple(Literal(name) for name in variables),
            equations=(interface.equation,),
            interfaces=(interface,),
            outer_arcs=(
                CompiledOuterArc("outer-P0", "P0", (Literal("X0"),)),
                CompiledOuterArc("outer-P1", "P1", (Literal("X0"),)),
                CompiledOuterArc("outer-P2", "P2", (Literal("X0"),)),
            ),
        )
        placement = self._placement(3, ((1, -1, 0),))
        result = self._pipeline().analyze(planar_map, placement, compiled)
        self.assertFalse(result.feasible)
        self.assertIsNotNone(result.linear_invariants)
        self.assertIn("metric/radius/turn", result.reason)


if __name__ == "__main__":
    unittest.main()
