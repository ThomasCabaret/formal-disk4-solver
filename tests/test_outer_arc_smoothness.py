from __future__ import annotations

import unittest

from formal_disk4.constraints.angle_lp import AngleEquation
from formal_disk4.enumeration.assignments import AssignmentEnumerator, ContourAssignment
from formal_disk4.enumeration.weak_orders import Placement
from formal_disk4.maps.registry import build_map
from formal_disk4.profiles.build import build_formal_profile
from formal_disk4.profiles.decorations import (
    DecorationInfeasible,
    _outer_arc_internal_boundaries,
)
from formal_disk4.words.algebra import Literal
from formal_disk4.words.compile import build_terminal_contact_system, compile_word_case
from formal_disk4.words.families import (
    ExactFormalFamily,
    FamilySpecialization,
    expr_from_word,
)


def _word(text: str):
    if text == "1":
        return ()
    return tuple(
        Literal(token[:-3], True) if token.endswith("^-1") else Literal(token)
        for token in text.split()
    )


def _d693_case():
    planar_map = build_map("double-cycle-6")
    enumerator = AssignmentEnumerator(
        planar_map,
        allow_reflections=True,
        symmetry_mode="off",
    )
    occurrence_id = {
        name: index for index, name in enumerate(enumerator.occurrence_names)
    }

    piece_sequences = {
        "E1": ("E1:V1", "E1:A2", "E1:A1", "E1:V6"),
        "E2": ("E2:V2", "E2:A3", "E2:A2", "E2:V1"),
        "E3": ("E3:V3", "E3:A4", "E3:A3", "E3:V2"),
        "E4": ("E4:V4", "E4:A5", "E4:A4", "E4:V3"),
        "E5": ("E5:V5", "E5:A6", "E5:A5", "E5:V4"),
        "E6": ("E6:V6", "E6:A1", "E6:A6", "E6:V5"),
        "I1": ("I1:V1", "I1:Z", "I1:V6"),
        "I2": ("I2:V2", "I2:Z", "I2:V1"),
        "I3": ("I3:V3", "I3:Z", "I3:V2"),
        "I4": ("I4:V4", "I4:Z", "I4:V3"),
        "I5": ("I5:V5", "I5:Z", "I5:V4"),
        "I6": ("I6:V6", "I6:Z", "I6:V5"),
    }
    sequences = tuple(
        tuple(occurrence_id[name] for name in piece_sequences[piece])
        for piece in enumerator.piece_names
    )
    assignment = ContourAssignment(
        assignment_id=16,
        piece_names=enumerator.piece_names,
        sequences=sequences,
        orientation_signs=(-1,) * 6 + (1,) * 6,
        cyclic_offsets=(1,) * 12,
        stabilizer=(),
        canonical_key=sequences,
        required_equivariance="rotation_1",
    )

    block_names = (
        ("I1:V1", "I2:V2", "I3:V3", "I4:V4", "I5:V5", "I6:V6"),
        ("E1:V1", "E2:V2", "E3:V3", "E4:V4", "E5:V5", "E6:V6"),
        (
            "E1:A2", "E2:A3", "E3:A4", "E4:A5", "E5:A6", "E6:A1",
            "I1:Z", "I2:Z", "I3:Z", "I4:Z", "I5:Z", "I6:Z",
        ),
        ("I1:V6", "I2:V1", "I3:V2", "I4:V3", "I5:V4", "I6:V5"),
        ("E1:A1", "E2:A2", "E3:A3", "E4:A4", "E5:A5", "E6:A6"),
        ("E1:V6", "E2:V1", "E3:V2", "E4:V3", "E5:V4", "E6:V5"),
    )
    blocks = tuple(
        tuple(sorted(occurrence_id[name] for name in block))
        for block in block_names
    )
    positions = [-1] * len(enumerator.occurrence_names)
    for block_index, block in enumerate(blocks):
        for item in block:
            positions[item] = block_index

    length_rows = (
        ((0, 1, 0, 0, -1, 0),) * 6
        + ((1, 0, 0, -1, -1, 0),) * 6
        + ((1, 1, -1, 0, 0, 0),) * 6
    )
    angle_equations = (
        (AngleEquation((0, 0, 1, 0, 1, 0), 1.0),) * 6
        + (AngleEquation((1, 1, 0, 1, 0, 1), 2.0),) * 6
        + (AngleEquation((0, 0, 6, 0, 0, 0), 4.0),)
    )
    placement = Placement(
        placement_id=8,
        assignment=assignment,
        blocks=blocks,
        positions=tuple(positions),
        length_rows=length_rows,
        length_margin=1.0 / 9.0,
        length_witness=(2 / 9, 1 / 9, 1 / 3, 1 / 9, 1 / 9, 1 / 9),
        angle_equations=angle_equations,
        angle_margin=1.0 / 3.0,
        angle_witness=(2 / 3, 0, 2 / 3, 2 / 3, 1 / 3, 2 / 3),
    )

    environment_text = {
        "M_X0": "T0 T1^-1",
        "M_X1": "T2",
        "M_X2": "T2^-1 T1 T0^-1",
        "M_X3": "T3",
        "M_X4": "T2^-1",
        "M_X5": "T0 T1^-1 T3 T2^-1",
        "X0": "T3 T2^-1",
        "X1": "T1",
        "X2": "T1^-1 T2 T3^-1",
        "X3": "T0",
        "X4": "T1^-1",
        "X5": "T3 T2^-1 T0 T1^-1",
    }
    environment = tuple(
        (variable, _word(text)) for variable, text in environment_text.items()
    )
    family = ExactFormalFamily(
        family_id=25,
        kind="finite",
        environment=tuple(
            (variable, expr_from_word(word)) for variable, word in environment
        ),
        exponent_minimums=(),
        trace=(),
        residual_graph_nodes=116,
        validation_assignments=((),),
    )
    specialization = FamilySpecialization(
        family_id=25,
        family_kind="finite",
        exponent_assignment=(),
        environment=environment,
        trace=(),
    )
    return planar_map, enumerator, placement, family, specialization


class OuterArcSmoothnessTests(unittest.TestCase):
    def test_locator_finds_only_strict_internal_outer_boundaries(self) -> None:
        planar_map = build_map("double-cycle-6")
        _planar_map, enumerator, placement, _family, _specialization = _d693_case()
        compiled = compile_word_case(planar_map, placement)
        environment = {variable: (Literal(f"T{index}"),) for index, variable in enumerate(compiled.atomic_variables)}
        environment["X3"] = (Literal("A"), Literal("B"), Literal("C"))
        boundaries = dict(_outer_arc_internal_boundaries(compiled, environment))
        self.assertEqual(len(boundaries["outer-E1"]), 3)
        self.assertEqual(len(set(boundaries["outer-E1"])), 3)
        self.assertEqual(enumerator.piece_names[0], "E1")

    def test_d693_cornered_outer_arc_is_rejected_formally(self) -> None:
        planar_map, enumerator, placement, family, specialization = _d693_case()
        compiled = compile_word_case(planar_map, placement)
        terminal_system = build_terminal_contact_system(
            compiled, specialization.environment_map()
        )
        boundaries = dict(
            _outer_arc_internal_boundaries(
                compiled, terminal_system.environment_map()
            )
        )
        self.assertEqual(boundaries["outer-E1"], (6, 5, 4))

        with self.assertRaises(DecorationInfeasible) as context:
            build_formal_profile(
                planar_map,
                enumerator.occurrence_names,
                placement,
                compiled,
                family,
                specialization,
            )
        self.assertEqual(context.exception.stage, "angle_classes")


if __name__ == "__main__":
    unittest.main()
