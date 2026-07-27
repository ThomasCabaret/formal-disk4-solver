from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Dict, Tuple

from formal_disk4.words.algebra import Literal, Word, word_to_text
from formal_disk4.words.compile import ContactMapping
from formal_disk4.words.families import ExactFormalFamily, FamilySpecialization

from .decorations import (
    AngleEquationRecord,
    CurveComponentRecord,
    JointAngularFeasibility,
    OuterArcRecord,
    PointClassRecord,
    PointRecord,
    TemplateRelationRecord,
)
from .exact_linear import ExactLinearSolution, LinearExpression, fraction_record, fraction_text


def _pi_expression_text(expression: LinearExpression) -> str:
    value = expression.exact_value
    if value is not None:
        if value == 0:
            return "0"
        if value == 1:
            return "pi"
        return f"{fraction_text(value)}*pi"
    return f"({expression.to_text()})*pi"


def _full_turn_expression_text(expression: LinearExpression) -> str:
    fraction = expression.scale(Fraction(1, 2))
    value = fraction.exact_value
    if value is not None:
        if value == 0:
            return "0 turns"
        if value == 1:
            return "1 turn"
        return f"{fraction_text(value)} turn"
    return f"({fraction.to_text()}) turn"


def _disk_length_text(expression: LinearExpression) -> str:
    value = expression.exact_value
    if value is not None:
        if value == 0:
            return "0"
        if value == 1:
            return "C_disk"
        return f"{fraction_text(value)}*C_disk"
    return f"({expression.to_text()})*C_disk"


def _angle_equation_text(item: AngleEquationRecord) -> str:
    terms = []
    for boundary, coefficient in item.terms:
        variable = f"alpha_B{boundary}"
        if coefficient == 1:
            terms.append(variable)
        elif coefficient == -1:
            terms.append(f"-{variable}")
        else:
            terms.append(f"{coefficient}*{variable}")
    left = " + ".join(terms).replace("+ -", "- ") or "0"
    return f"{left} = {fraction_text(item.rhs_pi)}"


def _joint_angular_dict(item: JointAngularFeasibility) -> Dict[str, object]:
    return {
        "feasible": item.feasible,
        "status": item.status,
        "strict_margin": fraction_record(item.strict_margin),
        "point_angle_variables": list(item.point_angle_variables),
        "curve_turn_variables": list(item.curve_turn_variables),
        "length_variables": list(item.length_variables),
        "point_turn_convention": "tau_Bi = 1 - alpha_Bi, with -1 < tau_Bi < 1",
        "curve_turn_convention": "K_Ci is signed total tangent turn in pi units and is unbounded",
        "equations": [
            {
                "kind": equation.kind,
                "relation": equation.relation,
                "sources": list(equation.sources),
                "terms": [
                    {"variable": name, "coefficient": fraction_record(coefficient)}
                    for name, coefficient in equation.terms
                ],
                "rhs_pi": fraction_record(equation.rhs_pi),
            }
            for equation in item.equations
        ],
        "exact_solution": item.exact_solution.to_dict(),
        "witness": {name: fraction_record(value) for name, value in item.witness},
    }


def _segment_record(
    index: int,
    literal: Literal,
    component: CurveComponentRecord,
) -> Dict[str, object]:
    return {
        "segment_index": index,
        "literal": literal.to_text(),
        "variable": literal.variable,
        "template_orientation": "inverse" if literal.inverse else "direct",
        "curve_component": component.component_id,
        "curve_type": component.curve_type,
        "circle_class": component.circle_class,
        "length_parameter": component.length_parameter,
        "disk_normalized_length": component.disk_normalized_length.to_dict(),
        "disk_normalized_length_text": _disk_length_text(component.disk_normalized_length),
        "curve_turn_parameter": component.turn_parameter,
        "curve_turn_pi": component.curve_turn_pi.to_dict(),
        "curve_turn_text": _pi_expression_text(component.curve_turn_pi),
        "curve_turn_pi_witness": fraction_record(component.curve_turn_pi_witness),
        "disk_normalized_turn_pi": component.curve_turn_pi.to_dict(),
        "disk_normalized_turn_text": _pi_expression_text(component.curve_turn_pi),
        "full_turn_fraction": component.curve_turn_pi.scale(Fraction(1, 2)).to_dict(),
        "full_turn_fraction_text": _full_turn_expression_text(component.curve_turn_pi),
        "forced_straight": component.forced_straight,
        "self_symmetries": list(component.self_symmetries),
    }


@dataclass(frozen=True)
class FormalProfile:
    schema_version: str
    map_name: str
    assignment_id: int
    placement_id: int
    expected_internal_mapping_count: int
    expected_outer_arc_count: int
    family: ExactFormalFamily
    specialization: FamilySpecialization
    atomic_contour: Word
    terminal_contour: Word
    point_decorations: Tuple[PointRecord, ...]
    point_classes: Tuple[PointClassRecord, ...]
    angle_equations: Tuple[AngleEquationRecord, ...]
    exact_angle_solution: ExactLinearSolution
    joint_angular_feasibility: JointAngularFeasibility
    curve_components: Tuple[CurveComponentRecord, ...]
    exact_length_solution: ExactLinearSolution
    template_relations: Tuple[TemplateRelationRecord, ...]
    contact_mappings: Tuple[ContactMapping, ...]
    outer_arcs: Tuple[OuterArcRecord, ...]
    formal_constraints: Tuple[Dict[str, object], ...]
    placement_length_margin: float
    placement_angle_margin: float
    decorated_angle_margin: float
    terminal_length_margin: float
    canonical_contour_signature: Tuple[Tuple[int, bool], ...]
    filter_status: Tuple[Tuple[str, str], ...]

    def environment_map(self) -> Dict[str, Word]:
        return self.specialization.environment_map()

    def decorated_terminal_contour(self) -> Dict[str, object]:
        component_by_variable = {
            variable: component
            for component in self.curve_components
            for variable in component.variables
        }
        cycle = []
        text_tokens = []
        segment_count = len(self.terminal_contour)
        for index, literal in enumerate(self.terminal_contour):
            point = self.point_decorations[index]
            component = component_by_variable[literal.variable]
            incoming = self.terminal_contour[(index - 1) % segment_count]
            angle_text = _pi_expression_text(point.prototype_angle_expression)
            angle_turn_text = _full_turn_expression_text(point.prototype_angle_expression)
            point_record = {
                "boundary_index": point.boundary_index,
                "between": {
                    "incoming_literal": incoming.to_text(),
                    "outgoing_literal": literal.to_text(),
                },
                "angle_class": point.class_id,
                "angle_class_sign": point.class_sign,
                "interior_angle_pi": point.prototype_angle_expression.to_dict(),
                "interior_angle_text": angle_text,
                "interior_angle_full_turn_fraction": point.prototype_angle_expression.scale(Fraction(1, 2)).to_dict(),
                "interior_angle_full_turn_text": _full_turn_expression_text(point.prototype_angle_expression),
                "signed_point_turn_pi": point.prototype_turn_expression.to_dict(),
                "signed_point_turn_text": _pi_expression_text(point.prototype_turn_expression),
                "signed_point_turn_domain": "(-pi, pi)",
                "occurrences": list(point.occurrences),
                "roles": list(point.roles),
            }
            segment_record = _segment_record(index, literal, component)
            cycle.append({"point": point_record, "segment_after_point": segment_record})
            if component.curve_type == "circular_arc":
                segment_text = (
                    f"{literal.to_text()}{{circular_arc:{component.circle_class},"
                    f"L={_disk_length_text(component.disk_normalized_length)},"
                    f"turn={_pi_expression_text(component.curve_turn_pi)}"
                    f"[{_full_turn_expression_text(component.curve_turn_pi)}]}}"
                )
            elif component.curve_type == "straight_segment":
                segment_text = (
                    f"{literal.to_text()}{{straight_segment,"
                    f"L={_disk_length_text(component.disk_normalized_length)},"
                    f"turn={_pi_expression_text(component.curve_turn_pi)}}}"
                )
            else:
                segment_text = (
                    f"{literal.to_text()}{{generic_curve,"
                    f"L={_disk_length_text(component.disk_normalized_length)},"
                    f"turn={_pi_expression_text(component.curve_turn_pi)}}}"
                )
            text_tokens.extend((f"({angle_text}[{angle_turn_text}])", segment_text))
        return {
            "normalizations": {
                "angle_unit": "pi",
                "full_turn": "2*pi",
                "disk_circumference": "C_disk = 1 for normalized expressions",
            },
            "variable_naming_note": (
                "T0, T1, ... are canonical terminal curve-template names. "
                "Their geometric types and parameters are carried by the segment decorations."
            ),
            "text": " ".join(text_tokens),
            "word": word_to_text(self.terminal_contour),
            "cycle": cycle,
            "angle_relations": [
                {
                    "kind": item.kind,
                    "sources": list(item.sources),
                    "relation": item.relation,
                    "equation": _angle_equation_text(item),
                    "terms": [
                        {"boundary_index": boundary, "coefficient": coefficient}
                        for boundary, coefficient in item.terms
                    ],
                    "rhs_pi": fraction_record(item.rhs_pi),
                }
                for item in self.angle_equations
            ],
            "exact_angle_solution": self.exact_angle_solution.to_dict(),
            "exact_joint_angular_feasibility": _joint_angular_dict(self.joint_angular_feasibility),
            "exact_disk_normalized_length_solution": self.exact_length_solution.to_dict(),
        }

    def to_dict(self) -> Dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "map": self.map_name,
            "assignment_id": self.assignment_id,
            "placement_id": self.placement_id,
            "expected_internal_mapping_count": self.expected_internal_mapping_count,
            "expected_outer_arc_count": self.expected_outer_arc_count,
            "word_family": self.family.to_dict(),
            "specialization": self.specialization.to_dict(),
            "atomic_contour": word_to_text(self.atomic_contour),
            "terminal_contour": word_to_text(self.terminal_contour),
            "decorated_terminal_contour": self.decorated_terminal_contour(),
            "points": [
                {
                    "boundary_index": point.boundary_index,
                    "source": point.source,
                    "source_block_index": point.source_block_index,
                    "occurrences": list(point.occurrences),
                    "angle_class": point.class_id,
                    "angle_class_sign": point.class_sign,
                    "fixed_zero_turn": point.fixed_zero_turn,
                    "prototype_turn_pi_witness": point.prototype_turn_pi,
                    "prototype_angle_pi_witness": point.prototype_angle_pi,
                    "prototype_angle_pi": point.prototype_angle_expression.to_dict(),
                    "prototype_angle_text": _pi_expression_text(point.prototype_angle_expression),
                    "prototype_turn_pi": point.prototype_turn_expression.to_dict(),
                    "prototype_turn_text": _pi_expression_text(point.prototype_turn_expression),
                    "prototype_turn_domain": "(-pi, pi)",
                    "prototype_angle_full_turn_fraction": point.prototype_angle_expression.scale(Fraction(1, 2)).to_dict(),
                    "prototype_angle_full_turn_text": _full_turn_expression_text(point.prototype_angle_expression),
                    "occurrence_angles_pi_witness": dict(point.occurrence_angles_pi),
                    "occurrence_angle_expressions": {
                        name: expression.to_dict()
                        for name, expression in point.occurrence_angle_expressions
                    },
                    "roles": list(point.roles),
                }
                for point in self.point_decorations
            ],
            "angle_classes": [
                {
                    "class_id": item.class_id,
                    "representative_boundary": item.representative_boundary,
                    "members": [
                        {"boundary_index": boundary, "sign": sign}
                        for boundary, sign in item.members
                    ],
                    "forced_zero_turn": item.forced_zero,
                    "turn_pi_witness": item.turn_pi,
                    "representative_angle_pi": item.representative_angle_expression.to_dict(),
                    "representative_angle_text": _pi_expression_text(
                        item.representative_angle_expression
                    ),
                    "representative_turn_pi": item.representative_turn_expression.to_dict(),
                    "representative_turn_text": _pi_expression_text(
                        item.representative_turn_expression
                    ),
                    "signed_class_relation": (
                        "sign +1: alpha_member = alpha_representative; "
                        "sign -1: alpha_member + alpha_representative = 2*pi"
                    ),
                }
                for item in self.point_classes
            ],
            "angle_equations": [
                {
                    "kind": item.kind,
                    "sources": list(item.sources),
                    "relation": item.relation,
                    "equation": _angle_equation_text(item),
                    "terms": [
                        {"boundary_index": boundary, "coefficient": coefficient}
                        for boundary, coefficient in item.terms
                    ],
                    "rhs_pi": fraction_record(item.rhs_pi),
                }
                for item in self.angle_equations
            ],
            "exact_angle_solution": self.exact_angle_solution.to_dict(),
            "joint_angular_feasibility": _joint_angular_dict(self.joint_angular_feasibility),
            "curve_components": [
                {
                    "component_id": item.component_id,
                    "representative": item.representative,
                    "variables": list(item.variables),
                    "variable_transforms": dict(item.variable_transforms),
                    "self_symmetries": list(item.self_symmetries),
                    "mode": item.mode,
                    "curve_type": item.curve_type,
                    "forced_straight": item.forced_straight,
                    "circular": item.circular,
                    "circle_class": item.circle_class,
                    "length_parameter": item.length_parameter,
                    "search_witness_normalized_length": item.search_witness_normalized_length,
                    "search_witness_note": (
                        "LP witness only; it is not a uniquely determined geometric length."
                    ),
                    "disk_normalized_length": item.disk_normalized_length.to_dict(),
                    "disk_normalized_length_text": _disk_length_text(
                        item.disk_normalized_length
                    ),
                    "curve_turn_parameter": item.turn_parameter,
                    "curve_turn_pi": item.curve_turn_pi.to_dict(),
                    "curve_turn_text": _pi_expression_text(item.curve_turn_pi),
                    "curve_turn_pi_witness": fraction_record(item.curve_turn_pi_witness),
                    "curve_turn_domain": "unbounded real",
                    "disk_normalized_turn_pi": item.curve_turn_pi.to_dict(),
                    "disk_normalized_turn_text": _pi_expression_text(item.curve_turn_pi),
                    "full_turn_fraction": item.curve_turn_pi.scale(Fraction(1, 2)).to_dict(),
                    "full_turn_fraction_text": _full_turn_expression_text(item.curve_turn_pi),
                }
                for item in self.curve_components
            ],
            "exact_disk_normalized_length_solution": self.exact_length_solution.to_dict(),
            "template_relations": [
                {
                    "left_variable": item.left_variable,
                    "right_variable": item.right_variable,
                    "transform": item.transform,
                    "interface": item.interface,
                    "pair_index": item.pair_index,
                }
                for item in self.template_relations
            ],
            "contact_mappings": [
                {
                    "interface": mapping.interface_name,
                    "left_piece": mapping.left_piece,
                    "right_piece": mapping.right_piece,
                    "relative_parity": mapping.relative_parity,
                    "isometry": "direct" if mapping.relative_parity == 1 else "reflected",
                    "pairs": [
                        {
                            "left": {
                                "segment": left.segment_index,
                                "forward": left.forward,
                            },
                            "right": {
                                "segment": right.segment_index,
                                "forward": right.forward,
                            },
                        }
                        for left, right in mapping.pairs
                    ],
                }
                for mapping in self.contact_mappings
            ],
            "outer_arcs": [
                {
                    "name": item.name,
                    "piece": item.piece,
                    "terminal_word": word_to_text(item.terminal_word),
                    "curve_type": "circular_arc",
                    "length_parameter": item.length_parameter,
                    "length_expression": [
                        {"parameter": parameter, "coefficient": coefficient}
                        for parameter, coefficient in item.length_expression
                    ],
                    "disk_normalized_length": item.disk_normalized_length.to_dict(),
                    "disk_normalized_length_text": _disk_length_text(
                        item.disk_normalized_length
                    ),
                    "turn_parameter": item.turn_parameter,
                    "turn_pi": item.turn_pi.to_dict(),
                    "turn_text": _pi_expression_text(item.turn_pi),
                    "full_turn_fraction": item.turn_pi.scale(Fraction(1, 2)).to_dict(),
                    "full_turn_fraction_text": _full_turn_expression_text(item.turn_pi),
                    "circle_class": "disk_boundary",
                }
                for item in self.outer_arcs
            ],
            "formal_constraints": list(self.formal_constraints),
            "margins": {
                "placement_length": self.placement_length_margin,
                "placement_angle": self.placement_angle_margin,
                "decorated_angle": self.decorated_angle_margin,
                "joint_angular_exact": float(self.joint_angular_feasibility.strict_margin),
                "terminal_curve_length": self.terminal_length_margin,
            },
            "canonical_contour_signature": [
                [index, inverse] for index, inverse in self.canonical_contour_signature
            ],
            "filter_status": dict(self.filter_status),
        }
