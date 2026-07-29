from __future__ import annotations

import unittest
from fractions import Fraction
from pathlib import Path

from formal_disk4.config import load_config
from formal_disk4.constraints.angle_lp import AngleFeasibilityOracle
from formal_disk4.constraints.length_lp import LengthFeasibilityOracle
from formal_disk4.enumeration.assignments import (
    AssignmentEnumerator,
    ContourAssignment,
    rotate,
)
from formal_disk4.enumeration.weak_orders import Placement, WeakOrderEnumerator
from formal_disk4.maps.base import Occurrence
from formal_disk4.maps.registry import build_map
from formal_disk4.preword import (
    PrewordLinearInvariantFilter,
    PrewordPruningPipeline,
    RadiusArcTopologyFilter,
)
from formal_disk4.profiles.build import build_formal_profile
from formal_disk4.profiles.decorations import DecorationInfeasible
from formal_disk4.profiles.filters import ProfileFilterPipeline
from formal_disk4.words.compile import compile_word_case
from formal_disk4.words.exact_partial import ExactPartialWordSolver, SolverLimits
from formal_disk4.words.families import FamilyExpansionPolicy, expand_family


FIGURE2B_POINT_TURNS_PI = (
    Fraction(2, 3),
    Fraction(1, 2),
    Fraction(0),
    Fraction(1, 2),
    Fraction(2, 3),
    Fraction(-1, 2),
)


def _figure2b_assignment(planar_map, enumerator) -> ContourAssignment:
    sequences = []
    signs = []
    phases = []
    for piece, base in zip(planar_map.pieces, enumerator.base_sequences):
        if piece.name.startswith("E"):
            sequences.append(rotate(base, 3))
            signs.append(+1)
            phases.append(3)
        else:
            sequences.append(tuple(reversed(base)))
            signs.append(-1)
            phases.append(0)
    sequence_tuple = tuple(sequences)
    return ContourAssignment(
        assignment_id=-1,
        piece_names=enumerator.piece_names,
        sequences=sequence_tuple,
        orientation_signs=tuple(signs),
        cyclic_offsets=tuple(phases),
        stabilizer=(),
        canonical_key=sequence_tuple,
        required_equivariance="rotation_1",
    )


def _figure2b_placement():
    planar_map = build_map("double-cycle-6")
    enumerator = AssignmentEnumerator(
        planar_map,
        allow_reflections=True,
        symmetry_mode="off",
    )
    assignment = _figure2b_assignment(planar_map, enumerator)
    occurrence_index = enumerator.occurrence_index

    def previous(index: int) -> int:
        return (index - 2) % 6 + 1

    blocks = (
        tuple(
            sorted(
                [
                    *(
                        occurrence_index[Occurrence(f"E{index}", f"V{previous(index)}")]
                        for index in range(1, 7)
                    ),
                    *(
                        occurrence_index[Occurrence(f"I{index}", "Z")]
                        for index in range(1, 7)
                    ),
                ]
            )
        ),
        tuple(
            sorted(
                occurrence_index[Occurrence(f"E{index}", f"A{index}")]
                for index in range(1, 7)
            )
        ),
        tuple(
            sorted(
                occurrence_index[Occurrence(f"I{index}", f"V{index}")]
                for index in range(1, 7)
            )
        ),
        tuple(
            sorted(
                occurrence_index[Occurrence(f"E{index}", f"A{index % 6 + 1}")]
                for index in range(1, 7)
            )
        ),
        tuple(
            sorted(
                [
                    *(
                        occurrence_index[Occurrence(f"E{index}", f"V{index}")]
                        for index in range(1, 7)
                    ),
                    *(
                        occurrence_index[Occurrence(f"I{index}", f"V{previous(index)}")]
                        for index in range(1, 7)
                    ),
                ]
            )
        ),
    )
    positions = [-1] * len(enumerator.occurrences)
    for block_index, block in enumerate(blocks):
        for occurrence_id in block:
            positions[occurrence_id] = block_index
    if any(position < 0 for position in positions):
        raise AssertionError("Incomplete Figure 2b placement")

    weak_orders = WeakOrderEnumerator(
        planar_map,
        assignment,
        enumerator.occurrence_names,
        LengthFeasibilityOracle(),
        AngleFeasibilityOracle(),
        symmetry_mode="off",
        enable_exterior_arc_repetition_filter=False,
    )
    length_rows = weak_orders._resolved_length_rows(positions, len(blocks))
    angle_equations = weak_orders._resolved_angle_equations(positions, len(blocks))
    placement = Placement(
        placement_id=-1,
        assignment=assignment,
        blocks=blocks,
        positions=tuple(positions),
        length_rows=length_rows,
        length_margin=Fraction(1, 6),
        length_witness=tuple(1.0 / len(blocks) for _ in blocks),
        angle_equations=angle_equations,
        angle_margin=Fraction(1, 3),
        angle_witness=tuple(0.0 for _ in blocks),
    )
    return planar_map, enumerator, placement


def _preword_pipeline(config) -> PrewordPruningPipeline:
    pruning = config["filters"]["preword_pruning"]
    topology = pruning["topology"]
    linear = pruning["linear_invariants"]
    tolerance = float(config["enumeration"]["lp_tolerance"])
    return PrewordPruningPipeline(
        topology_filter=RadiusArcTopologyFilter(
            tolerance=tolerance,
            enable_endpoint_crossing=bool(topology["enable_endpoint_crossing"]),
            max_intervals=int(topology["max_intervals"]),
        ),
        linear_filter=PrewordLinearInvariantFilter(
            tolerance=tolerance,
            enable_radius_measures=bool(linear["enable_radius_measures"]),
            enable_smooth_turns=bool(linear["enable_smooth_turns"]),
            enable_point_turns=bool(linear["enable_point_turns"]),
            enforce_global_point_turn_balance=bool(
                linear.get("enforce_global_point_turn_balance", True)
            ),
            enable_isoperimetric=bool(linear["enable_isoperimetric"]),
            sqrt_upper_bound_denominator=int(linear["sqrt_upper_bound_denominator"]),
        ),
        enable_topology=bool(topology["enabled"]),
        enable_linear_invariants=bool(linear["enabled"]),
    )


class Figure2BFormalPipelineTests(unittest.TestCase):
    def test_exact_user_mapping_survives_every_formal_stage(self) -> None:
        root = Path(__file__).resolve().parents[1]
        config = load_config(root / "config/cases/double-cycle-6/search.json")
        for config_name in ("search.json", "profile.json"):
            case_config = load_config(
                root / "config/cases/double-cycle-6" / config_name
            )
            linear = case_config["filters"]["preword_pruning"][
                "linear_invariants"
            ]
            self.assertTrue(linear["enable_point_turns"])
            self.assertFalse(linear["enforce_global_point_turn_balance"])

        planar_map, enumerator, placement = _figure2b_placement()
        compiled = compile_word_case(planar_map, placement)

        preword = _preword_pipeline(config).analyze(
            planar_map, placement, compiled
        )
        self.assertTrue(preword.feasible, preword.reason)

        self.assertTrue(compiled.mirror_variables)
        self.assertTrue(
            any("M_X" in equation.to_text() for equation in compiled.effective_solver_equations)
        )
        solver = ExactPartialWordSolver(
            compiled.effective_solver_equations,
            compiled.solver_variables,
        )
        families = list(
            solver.solve(
                SolverLimits(
                    max_graph_nodes=100_000,
                    max_graph_edges=400_000,
                    max_families=50,
                    max_expression_nodes=10_000,
                    validation_exponent=3,
                )
            )
        )
        self.assertTrue(families)

        profile_filter = ProfileFilterPipeline(
            enable_subsumption_hook=False,
            enable_geometry_hook=False,
        )
        matching_profile = None
        for family in families:
            for specialization in expand_family(
                family, FamilyExpansionPolicy(kind="none")
            ):
                try:
                    profile = build_formal_profile(
                        planar_map,
                        enumerator.occurrence_names,
                        placement,
                        compiled,
                        family,
                        specialization,
                    )
                except DecorationInfeasible:
                    continue
                filtered, statuses = profile_filter.apply(profile)
                if filtered is None:
                    continue
                turns = tuple(
                    point.prototype_turn_expression.constant
                    if not point.prototype_turn_expression.terms
                    else None
                    for point in filtered.point_decorations
                )
                if turns == FIGURE2B_POINT_TURNS_PI:
                    matching_profile = filtered
                    break
            if matching_profile is not None:
                break

        self.assertIsNotNone(matching_profile)
        profile = matching_profile
        assert profile is not None
        self.assertEqual(len(profile.terminal_contour), 6)

        component_by_variable = {
            variable: component
            for component in profile.curve_components
            for variable in component.variables
        }
        curve_types = tuple(
            component_by_variable[literal.variable].curve_type
            for literal in profile.terminal_contour
        )
        self.assertEqual(
            curve_types,
            (
                "straight_segment",
                "circular_arc",
                "circular_arc",
                "straight_segment",
                "circular_arc",
                "straight_segment",
            ),
        )

        transform_sign = {
            "identity": +1,
            "reverse": -1,
            "mirror": -1,
            "mirror_reverse": +1,
        }
        circular_turn_signs = []
        for index in (1, 2, 4):
            literal = profile.terminal_contour[index]
            component = component_by_variable[literal.variable]
            transforms = dict(component.variable_transforms)
            sign = transform_sign[transforms[literal.variable]]
            if literal.inverse:
                sign *= -1
            circular_turn_signs.append(sign)
        self.assertEqual(circular_turn_signs, [+1, +1, -1])

        mappings = {
            mapping.interface_name: tuple(
                (
                    left.segment_index,
                    left.forward,
                    right.segment_index,
                    right.forward,
                )
                for left, right in mapping.pairs
            )
            for mapping in profile.contact_mappings
        }
        # Equivalent to 0-1 / 4-3 after reversing both sides.
        self.assertEqual(mappings["E1-E2"], ((3, True, 0, False),))
        # Exactly 4-5-0 / 2-3-4.
        self.assertEqual(
            mappings["E1-I1"],
            ((4, True, 2, True), (5, True, 3, True)),
        )
        # Equivalent to 0-5-4 / 0-1-2 after swapping and reversing both paths.
        self.assertEqual(
            mappings["I1-I2"],
            ((1, False, 4, True), (0, False, 5, True)),
        )

        self.assertTrue(all(status for _name, status in profile.filter_status))


if __name__ == "__main__":
    unittest.main()
