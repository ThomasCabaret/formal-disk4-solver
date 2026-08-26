from __future__ import annotations

from pathlib import Path
import unittest

from formal_disk4.constraints.angle_lp import AngleFeasibilityOracle
from formal_disk4.constraints.length_lp import LengthFeasibilityOracle
from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.enumeration.weak_orders import WeakOrderEnumerator
from formal_disk4.geometry.model import parse_formal_geometry_problem
from formal_disk4.geometry.solver import GeometrySolverConfig, NumericalContourSolver
from formal_disk4.maps.base import (
    InterfaceSpec,
    InterfaceView,
    PieceSpec,
    PlanarMap,
    VertexSpec,
)
from formal_disk4.profiles.build import build_formal_profile
from formal_disk4.profiles.filters import ProfileFilterPipeline
from formal_disk4.words.compile import compile_word_case
from formal_disk4.words.exact_partial import ExactPartialWordSolver, SolverLimits
from formal_disk4.words.families import FamilyExpansionPolicy, expand_family


def build_free_symmetric_prototype(order: int = 3) -> PlanarMap:
    names = tuple(f"V{index}" for index in range(order))
    piece = PieceSpec("P0", names, False, outer_boundary_contact="none")
    vertices = tuple(
        VertexSpec(name, "free", ("P0",), 2.0) for name in names
    )
    interfaces = tuple(
        InterfaceSpec(
            name=f"free-{index}",
            left_piece="P0",
            right_piece=None,
            views=(
                InterfaceView("P0", names[index], names[(index + 1) % order]),
            ),
            is_free=True,
        )
        for index in range(order)
    )
    result = PlanarMap(
        name=f"free-prototype-c{order}",
        pieces=(piece,),
        vertices=vertices,
        interfaces=interfaces,
        automorphisms=(),
        reference_piece="P0",
        prototype_rotation_order=order,
    )
    result.validate()
    return result


class PrototypeRotationTests(unittest.TestCase):
    def _formal_profile(self):
        planar_map = build_free_symmetric_prototype()
        assignments = AssignmentEnumerator(
            planar_map,
            allow_reflections=False,
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
        compiled = compile_word_case(planar_map, placement)
        family = next(
            ExactPartialWordSolver(
                compiled.effective_solver_equations,
                compiled.solver_variables,
                contour_variables=compiled.atomic_variables,
            ).solve(
                SolverLimits(
                    max_graph_nodes=500,
                    max_graph_edges=2_000,
                    max_families=8,
                    max_expression_nodes=1_000,
                    validation_exponent=2,
                )
            )
        )
        specialization = next(
            expand_family(family, FamilyExpansionPolicy(kind="none"))
        )
        profile = build_formal_profile(
            planar_map,
            assignments.occurrence_names,
            placement,
            compiled,
            family,
            specialization,
        )
        return planar_map, placement, compiled, profile

    def test_invalid_prototype_rotation_order_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one"):
            build_free_symmetric_prototype(0)

    def test_compile_adds_exact_contour_power_equations(self) -> None:
        _planar_map, placement, compiled, _profile = self._formal_profile()

        self.assertEqual(compiled.prototype_rotation_order, 3)
        self.assertEqual(compiled.prototype_sector_variable, "ROTATION_SECTOR")
        self.assertIn("ROTATION_SECTOR", compiled.solver_variables)
        self.assertIn("M_ROTATION_SECTOR", compiled.solver_variables)
        equation_text = {item.to_text() for item in compiled.effective_solver_equations}
        contour_text = " ".join(f"X{index}" for index in range(placement.interval_count))
        self.assertIn(
            f"{contour_text} = ROTATION_SECTOR ROTATION_SECTOR ROTATION_SECTOR",
            equation_text,
        )

    def test_terminal_profile_repeats_curves_and_point_angles(self) -> None:
        planar_map, _placement, _compiled, profile = self._formal_profile()

        self.assertEqual(profile.prototype_rotation_order, 3)
        self.assertEqual(len(profile.terminal_contour) % 3, 0)
        sector_size = len(profile.terminal_contour) // 3
        self.assertEqual(
            profile.terminal_contour,
            profile.terminal_contour[:sector_size] * 3,
        )
        for offset in range(sector_size):
            expressions = {
                profile.point_decorations[offset + copy * sector_size]
                .prototype_angle_expression.to_text()
                for copy in range(3)
            }
            self.assertEqual(len(expressions), 1)
        self.assertTrue(
            any(
                item.kind == "prototype_rotation_point_angle_equality"
                for item in profile.angle_equations
            )
        )
        symmetry_constraints = [
            item
            for item in profile.formal_constraints
            if item["kind"] == "prototype_rotational_symmetry"
        ]
        self.assertEqual(len(symmetry_constraints), 1)
        self.assertEqual(symmetry_constraints[0]["order"], 3)
        filtered, statuses = ProfileFilterPipeline().apply(profile)
        self.assertIsNotNone(filtered, statuses)

        geometry_problem = parse_formal_geometry_problem(
            {
                "formal_profile_id": "fp-prototype-rotation-test",
                "map": planar_map.to_dict(),
                "profile": profile.to_dict(),
            },
            source_path=Path("prototype-rotation-test.jsonl"),
            source_line=1,
        )
        self.assertEqual(geometry_problem.prototype_rotation_order, 3)

    def test_geometry_realization_preserves_the_imposed_rotation(self) -> None:
        planar_map, _placement, _compiled, profile = self._formal_profile()
        problem = parse_formal_geometry_problem(
            {
                "formal_profile_id": "fp-prototype-rotation-geometry-test",
                "map": planar_map.to_dict(),
                "profile": profile.to_dict(),
            },
            source_path=Path("prototype-rotation-geometry-test.jsonl"),
            source_line=1,
        )
        result = NumericalContourSolver(
            GeometrySolverConfig(
                intermediate_points_per_generic_curve=0,
                max_restarts=8,
                max_function_evaluations=500,
                candidate_timeout_seconds=5.0,
            )
        ).solve(problem)

        self.assertIsNotNone(result.solution, result.reason)
        assert result.solution is not None
        checks = {
            name: passed
            for name, passed, _detail in result.solution.validation.checks
        }
        self.assertTrue(checks["prototype_rotational_symmetry"])


if __name__ == "__main__":
    unittest.main()
