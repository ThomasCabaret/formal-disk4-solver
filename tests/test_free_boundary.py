from fractions import Fraction
from pathlib import Path
import unittest

from formal_disk4.constraints.angle_lp import AngleFeasibilityOracle
from formal_disk4.constraints.length_lp import LengthFeasibilityOracle
from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.enumeration.weak_orders import WeakOrderEnumerator
from formal_disk4.geometry.model import parse_formal_geometry_problem
from formal_disk4.maps.base import (
    InterfaceSpec,
    InterfaceView,
    PieceSpec,
    PlanarMap,
    ProblemHypotheses,
    VertexSpec,
)
from formal_disk4.preword.arc_topology import RadiusArcTopologyFilter
from formal_disk4.preword.linear_invariants import PrewordLinearInvariantFilter
from formal_disk4.profiles.build import build_formal_profile
from formal_disk4.profiles.filters import ProfileFilterPipeline
from formal_disk4.words.compile import compile_word_case
from formal_disk4.words.exact_partial import ExactPartialWordSolver, SolverLimits
from formal_disk4.words.families import FamilyExpansionPolicy, expand_family


def build_three_tile_crown() -> PlanarMap:
    """Three congruent annular sectors with an unconstrained inner boundary."""

    pieces = tuple(
        PieceSpec(
            name=f"P{i}",
            contour_vertices=(f"O{i}", f"O{(i + 1) % 3}", f"I{(i + 1) % 3}", f"I{i}"),
            touches_outer_boundary=True,
            outer_boundary_contact="arc",
        )
        for i in range(3)
    )
    vertices = tuple(
        VertexSpec(
            name=f"O{i}",
            kind="outer",
            incident_pieces=(f"P{(i - 1) % 3}", f"P{i}"),
            angle_sum_pi=1.0,
        )
        for i in range(3)
    ) + tuple(
        VertexSpec(
            name=f"I{i}",
            kind="free",
            incident_pieces=(f"P{(i - 1) % 3}", f"P{i}"),
            angle_sum_pi=2.0,
        )
        for i in range(3)
    )
    interfaces = []
    for i in range(3):
        previous = (i - 1) % 3
        next_index = (i + 1) % 3
        interfaces.extend(
            (
                InterfaceSpec(
                    name=f"outer-{i}",
                    left_piece=f"P{i}",
                    right_piece=None,
                    views=(InterfaceView(f"P{i}", f"O{i}", f"O{next_index}"),),
                    is_outer=True,
                ),
                InterfaceSpec(
                    name=f"radial-{i}",
                    left_piece=f"P{i}",
                    right_piece=f"P{previous}",
                    views=(
                        InterfaceView(f"P{i}", f"I{i}", f"O{i}"),
                        InterfaceView(f"P{previous}", f"O{i}", f"I{i}"),
                    ),
                ),
                InterfaceSpec(
                    name=f"free-{i}",
                    left_piece=f"P{i}",
                    right_piece=None,
                    views=(InterfaceView(f"P{i}", f"I{next_index}", f"I{i}"),),
                    is_free=True,
                ),
            )
        )
    result = PlanarMap(
        name="three-tile-free-crown",
        pieces=pieces,
        vertices=vertices,
        interfaces=tuple(interfaces),
        automorphisms=(),
        reference_piece="P0",
        hypotheses=ProblemHypotheses(piecewise_c2_boundary=True),
    )
    result.validate()
    return result


class FreeBoundaryTests(unittest.TestCase):
    def _first_placement(self, planar_map: PlanarMap):
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
        return assignments, placement

    def test_free_boundary_is_a_distinct_one_sided_interface(self) -> None:
        planar_map = build_three_tile_crown()
        self.assertEqual(len(planar_map.internal_interfaces()), 3)
        self.assertEqual(len(planar_map.outer_interfaces()), 3)
        self.assertEqual(len(planar_map.free_interfaces()), 3)
        self.assertTrue(planar_map.has_free_boundary)
        self.assertEqual(
            {item.boundary_kind for item in planar_map.free_interfaces()},
            {"free"},
        )
        self.assertTrue(
            all(vertex.solid_angle_relation == "strict_upper" for vertex in planar_map.vertices[3:])
        )

    def test_free_edges_create_no_word_equation_and_angles_are_strict_bounds(self) -> None:
        planar_map = build_three_tile_crown()
        _assignments, placement = self._first_placement(planar_map)
        compiled = compile_word_case(planar_map, placement)

        self.assertEqual(len(compiled.interfaces), 3)
        self.assertEqual(len(compiled.equations), 3)
        self.assertEqual(len(compiled.outer_arcs), 3)
        self.assertEqual(len(compiled.free_arcs), 3)
        self.assertEqual(len(placement.angle_equations), 3)
        self.assertEqual(len(placement.angle_inequalities), 3)

        topology = RadiusArcTopologyFilter().seed_only(compiled)
        curriculum = PrewordLinearInvariantFilter().metric_curriculum(
            planar_map, placement, compiled, topology
        )
        by_name = {item.name: item for item in curriculum.steps}
        for name in (
            "radius_global",
            "smooth_turn_global",
            "radius_concavity",
            "isoperimetric",
        ):
            self.assertEqual(by_name[name].status, "not_applicable")
        self.assertFalse(curriculum.point_turn_balance_derived)

    def test_formal_profile_preserves_the_free_boundary_contract(self) -> None:
        planar_map = build_three_tile_crown()
        assignments, placement = self._first_placement(planar_map)
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

        self.assertEqual(profile.expected_internal_mapping_count, 3)
        self.assertEqual(profile.expected_outer_arc_count, 3)
        self.assertEqual(profile.expected_free_boundary_count, 3)
        self.assertEqual(len(profile.free_boundaries), 3)
        free_angle_constraints = tuple(
            item
            for item in profile.angle_equations
            if item.kind == "free_boundary_vertex_angle_bound"
        )
        self.assertEqual(len(free_angle_constraints), 3)
        self.assertTrue(
            all(item.comparison == "strict_less" for item in free_angle_constraints)
        )
        self.assertTrue(
            all(item.rhs_pi == Fraction(2) for item in free_angle_constraints)
        )
        joint_kinds = {
            (item.kind, item.comparison)
            for item in profile.joint_angular_feasibility.equations
        }
        self.assertIn(
            ("free_boundary_vertex_angle_bound", "strict_less"),
            joint_kinds,
        )
        self.assertIn(("prototype_total_turn", "equal"), joint_kinds)
        self.assertNotIn(("prototype_smooth_turn_balance", "equal"), joint_kinds)
        self.assertNotIn(("prototype_point_turn_balance", "equal"), joint_kinds)
        filtered, statuses = ProfileFilterPipeline().apply(profile)
        self.assertIsNotNone(filtered, statuses)
        geometry_problem = parse_formal_geometry_problem(
            {
                "formal_profile_id": "fp-free-boundary-test",
                "map": planar_map.to_dict(),
                "profile": profile.to_dict(),
            },
            source_path=Path("free-boundary-test.jsonl"),
            source_line=1,
        )
        self.assertEqual(len(geometry_problem.strict_angle_constraints), 3)
        witness_angles = tuple(
            point.prototype_angle_pi for point in profile.point_decorations
        )
        self.assertTrue(all(value is not None for value in witness_angles))
        self.assertTrue(
            all(
                constraint.evaluate(witness_angles) < constraint.upper_pi  # type: ignore[arg-type]
                for constraint in geometry_problem.strict_angle_constraints
            )
        )


if __name__ == "__main__":
    unittest.main()
