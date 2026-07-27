from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple

import numpy as np


Point2 = Tuple[float, float]


def _fraction_float(record: Mapping[str, Any] | None, default: float = 0.0) -> float:
    if not record:
        return default
    if "float" in record:
        return float(record["float"])
    numerator = float(record.get("numerator", 0.0))
    denominator = float(record.get("denominator", 1.0))
    return numerator / denominator


@dataclass(frozen=True)
class LinearFormula:
    constant: float
    terms: Tuple[Tuple[str, float], ...]
    text: str

    @staticmethod
    def from_record(record: Mapping[str, Any] | None) -> "LinearFormula":
        if not record:
            return LinearFormula(0.0, (), "0")
        constant = _fraction_float(record.get("constant"))
        terms = tuple(
            (
                str(item["parameter"]),
                _fraction_float(item.get("coefficient"), 0.0),
            )
            for item in record.get("terms", [])
        )
        return LinearFormula(constant, terms, str(record.get("text", "0")))

    @property
    def parameters(self) -> Tuple[str, ...]:
        return tuple(name for name, _coefficient in self.terms)

    @property
    def exact(self) -> bool:
        return not self.terms

    def evaluate(self, values: Mapping[str, float]) -> float:
        return self.constant + sum(
            coefficient * float(values[name]) for name, coefficient in self.terms
        )

    def to_dict(self) -> Dict[str, object]:
        return {
            "text": self.text,
            "constant": self.constant,
            "terms": [
                {"parameter": name, "coefficient": coefficient}
                for name, coefficient in self.terms
            ],
        }


@dataclass(frozen=True)
class TransformSpec:
    reverse: bool = False
    mirror: bool = False

    @staticmethod
    def from_label(label: str) -> "TransformSpec":
        normalized = label.strip().lower()
        if normalized == "identity":
            return TransformSpec()
        if normalized == "reverse":
            return TransformSpec(reverse=True)
        if normalized == "mirror":
            return TransformSpec(mirror=True)
        if normalized in {"mirror_reverse", "reverse_mirror"}:
            return TransformSpec(reverse=True, mirror=True)
        raise ValueError(f"Unknown template transform: {label}")

    def compose(self, other: "TransformSpec") -> "TransformSpec":
        return TransformSpec(self.reverse ^ other.reverse, self.mirror ^ other.mirror)

    @property
    def label(self) -> str:
        if self.reverse and self.mirror:
            return "mirror_reverse"
        if self.reverse:
            return "reverse"
        if self.mirror:
            return "mirror"
        return "identity"


@dataclass(frozen=True)
class FormalPointSpec:
    boundary_index: int
    angle_pi: LinearFormula
    angle_class: str
    angle_class_sign: int
    occurrences: Tuple[str, ...]
    roles: Tuple[str, ...]
    witness_angle_pi: float | None


@dataclass(frozen=True)
class FormalSegmentOccurrence:
    segment_index: int
    literal: str
    variable: str
    literal_inverse: bool
    component_id: str
    curve_type: str
    circle_class: str | None


@dataclass(frozen=True)
class FormalCurveComponent:
    component_id: str
    representative: str
    variables: Tuple[str, ...]
    variable_transforms: Tuple[Tuple[str, TransformSpec], ...]
    curve_type: str
    circle_class: str | None
    forced_straight: bool
    length: LinearFormula
    turn_pi: LinearFormula | None
    search_witness_length: float | None

    def transform_for_variable(self, variable: str) -> TransformSpec:
        mapping = dict(self.variable_transforms)
        return mapping.get(variable, TransformSpec())


@dataclass(frozen=True)
class FormalGeometryProblem:
    formal_profile_id: str
    source_candidate: Mapping[str, Any]
    source_path: str
    source_line: int
    map_name: str
    points: Tuple[FormalPointSpec, ...]
    segments: Tuple[FormalSegmentOccurrence, ...]
    components: Tuple[FormalCurveComponent, ...]

    @property
    def component_map(self) -> Dict[str, FormalCurveComponent]:
        return {component.component_id: component for component in self.components}

    @property
    def parameter_names(self) -> Tuple[str, ...]:
        names = set()
        for point in self.points:
            names.update(point.angle_pi.parameters)
        for component in self.components:
            names.update(component.length.parameters)
            if component.turn_pi is not None:
                names.update(component.turn_pi.parameters)
        return tuple(sorted(names))


@dataclass(frozen=True)
class LocalCurveGeometry:
    component_id: str
    curve_type: str
    length: float
    total_turn: float
    control_points: np.ndarray
    sample_points: np.ndarray
    arc_center: np.ndarray | None = None
    arc_radius: float | None = None
    arc_sweep: float | None = None


@dataclass(frozen=True)
class OccurrenceGeometry:
    segment_index: int
    literal: str
    variable: str
    component_id: str
    transform: TransformSpec
    curve_type: str
    circle_class: str | None
    start_point: np.ndarray
    end_point: np.ndarray
    start_tangent: float
    end_tangent: float
    control_points: np.ndarray
    sample_points: np.ndarray
    length: float
    total_turn: float
    arc_center: np.ndarray | None = None
    arc_radius: float | None = None
    arc_sweep: float | None = None


@dataclass(frozen=True)
class GeometryValidation:
    passed: bool
    closure_error: float
    tangent_closure_error: float
    maximum_angle_error: float
    maximum_length_error: float
    signed_area: float
    minimum_nonadjacent_distance: float | None
    self_intersection_count: int
    minimum_edge_length: float
    checks: Tuple[Tuple[str, bool, str], ...]

    def to_dict(self) -> Dict[str, object]:
        return {
            "passed": self.passed,
            "closure_error": self.closure_error,
            "tangent_closure_error": self.tangent_closure_error,
            "maximum_angle_error": self.maximum_angle_error,
            "maximum_length_error": self.maximum_length_error,
            "signed_area": self.signed_area,
            "minimum_nonadjacent_distance": self.minimum_nonadjacent_distance,
            "self_intersection_count": self.self_intersection_count,
            "minimum_edge_length": self.minimum_edge_length,
            "checks": [
                {"name": name, "passed": passed, "detail": detail}
                for name, passed, detail in self.checks
            ],
        }


@dataclass(frozen=True)
class GeometrySolution:
    formal_profile_id: str
    solution_id: str
    parameter_values: Tuple[Tuple[str, float], ...]
    template_parameters: Tuple[Tuple[str, Mapping[str, Any]], ...]
    points: Tuple[Mapping[str, Any], ...]
    occurrences: Tuple[Mapping[str, Any], ...]
    templates: Tuple[Mapping[str, Any], ...]
    validation: GeometryValidation
    optimization: Mapping[str, Any]

    def to_dict(self) -> Dict[str, object]:
        return {
            "schema_version": "geometric-contour-solution-v1",
            "geometric_solution_id": self.solution_id,
            "formal_profile_id": self.formal_profile_id,
            "scope": "single_piece_contour_only",
            "normalization": {
                "disk_circumference": 1.0,
                "coordinate_unit": "disk_circumference",
                "angle_unit": "radian",
            },
            "formal_parameter_values": dict(self.parameter_values),
            "template_parameter_values": {
                name: value for name, value in self.template_parameters
            },
            "points": list(self.points),
            "curve_templates": list(self.templates),
            "contour_occurrences": list(self.occurrences),
            "validation": self.validation.to_dict(),
            "optimization": dict(self.optimization),
        }


def canonical_candidate_id(candidate: Mapping[str, Any]) -> str:
    existing = candidate.get("formal_profile_id")
    if existing:
        return str(existing)
    payload = {
        "map": candidate.get("map", {}).get("name") if isinstance(candidate.get("map"), Mapping) else candidate.get("map"),
        "assignment": candidate.get("assignment"),
        "placement": candidate.get("placement"),
        "specialization": candidate.get("specialization"),
        "profile": candidate.get("profile"),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "fp-" + hashlib.sha256(encoded).hexdigest()[:32]


def parse_formal_geometry_problem(
    candidate: Mapping[str, Any],
    *,
    source_path: Path,
    source_line: int,
) -> FormalGeometryProblem:
    profile = candidate.get("profile")
    if not isinstance(profile, Mapping):
        raise ValueError("Candidate does not contain a profile object")
    decorated = profile.get("decorated_terminal_contour")
    if not isinstance(decorated, Mapping):
        raise ValueError("Profile does not contain decorated_terminal_contour")
    cycle = decorated.get("cycle")
    if not isinstance(cycle, Sequence) or not cycle:
        raise ValueError("Decorated contour cycle is empty")

    point_witnesses = {}
    raw_points = profile.get("points", [])
    if isinstance(raw_points, Sequence):
        for raw_point in raw_points:
            if isinstance(raw_point, Mapping) and raw_point.get("boundary_index") is not None:
                explicit_witness = raw_point.get("prototype_angle_pi_witness")
                if explicit_witness is not None:
                    witness = float(explicit_witness)
                else:
                    value = raw_point.get("prototype_angle_pi")
                    if isinstance(value, Mapping):
                        exact_value = value.get("exact_value")
                        witness = (
                            _fraction_float(exact_value)
                            if isinstance(exact_value, Mapping)
                            else None
                        )
                    else:
                        witness = None if value is None else float(value)
                point_witnesses[int(raw_point["boundary_index"])] = witness

    points = []
    segments = []
    for expected_index, item in enumerate(cycle):
        if not isinstance(item, Mapping):
            raise ValueError("Invalid decorated contour cycle entry")
        point = item.get("point")
        segment = item.get("segment_after_point")
        if not isinstance(point, Mapping) or not isinstance(segment, Mapping):
            raise ValueError("Decorated contour entry lacks point or segment")
        boundary_index = int(point.get("boundary_index", expected_index))
        points.append(
            FormalPointSpec(
                boundary_index=boundary_index,
                angle_pi=LinearFormula.from_record(point.get("interior_angle_pi")),
                angle_class=str(point.get("angle_class", f"A{boundary_index}")),
                angle_class_sign=int(point.get("angle_class_sign", 1)),
                occurrences=tuple(str(value) for value in point.get("occurrences", [])),
                roles=tuple(str(value) for value in point.get("roles", [])),
                witness_angle_pi=point_witnesses.get(boundary_index),
            )
        )
        segments.append(
            FormalSegmentOccurrence(
                segment_index=int(segment.get("segment_index", expected_index)),
                literal=str(segment["literal"]),
                variable=str(segment["variable"]),
                literal_inverse=str(segment.get("template_orientation", "direct")) == "inverse",
                component_id=str(segment["curve_component"]),
                curve_type=str(segment["curve_type"]),
                circle_class=(
                    None if segment.get("circle_class") is None else str(segment.get("circle_class"))
                ),
            )
        )

    component_records = profile.get("curve_components")
    if not isinstance(component_records, Sequence):
        raise ValueError("Profile does not contain curve_components")
    components = []
    for item in component_records:
        if not isinstance(item, Mapping):
            raise ValueError("Invalid curve component record")
        raw_transforms = item.get("variable_transforms", {})
        if isinstance(raw_transforms, Mapping):
            transforms = tuple(
                (str(name), TransformSpec.from_label(str(label)))
                for name, label in sorted(raw_transforms.items())
            )
        else:
            transforms = ()
        turn_record = item.get("curve_turn_pi")
        if turn_record is None:
            turn_record = item.get("disk_normalized_turn_pi")
        components.append(
            FormalCurveComponent(
                component_id=str(item["component_id"]),
                representative=str(item["representative"]),
                variables=tuple(str(value) for value in item.get("variables", [])),
                variable_transforms=transforms,
                curve_type=str(item.get("curve_type", "generic_curve")),
                circle_class=(
                    None if item.get("circle_class") is None else str(item.get("circle_class"))
                ),
                forced_straight=bool(item.get("forced_straight", False)),
                length=LinearFormula.from_record(item.get("disk_normalized_length")),
                turn_pi=(
                    None if turn_record is None else LinearFormula.from_record(turn_record)
                ),
                search_witness_length=(
                    None
                    if item.get("search_witness_normalized_length") is None
                    else float(item.get("search_witness_normalized_length"))
                ),
            )
        )

    component_ids = {component.component_id for component in components}
    missing = sorted({segment.component_id for segment in segments} - component_ids)
    if missing:
        raise ValueError(f"Missing curve component definitions: {missing}")

    map_record = candidate.get("map")
    map_name = (
        str(map_record.get("name"))
        if isinstance(map_record, Mapping)
        else str(profile.get("map", map_record))
    )
    return FormalGeometryProblem(
        formal_profile_id=canonical_candidate_id(candidate),
        source_candidate=candidate,
        source_path=str(source_path.resolve()),
        source_line=source_line,
        map_name=map_name,
        points=tuple(sorted(points, key=lambda item: item.boundary_index)),
        segments=tuple(sorted(segments, key=lambda item: item.segment_index)),
        components=tuple(components),
    )


def point_record(point: np.ndarray) -> Point2:
    return (float(point[0]), float(point[1]))


def angle_wrap(value: float) -> float:
    return math.atan2(math.sin(value), math.cos(value))
