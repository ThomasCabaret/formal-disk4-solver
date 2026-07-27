from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple

import numpy as np
from scipy.optimize import least_squares

from .model import (
    FormalCurveComponent,
    FormalGeometryProblem,
    GeometrySolution,
    LinearFormula,
    LocalCurveGeometry,
    OccurrenceGeometry,
    TransformSpec,
    angle_wrap,
    point_record,
)
from .validation import nonadjacent_distances, sampled_polyline, signed_area, validate_geometry


@dataclass(frozen=True)
class GeometrySolverConfig:
    intermediate_points_per_generic_curve: int = 1
    arc_sample_count: int = 48
    max_restarts: int = 32
    max_function_evaluations: int = 5000
    random_seed: int = 0
    maximum_curve_length: float = 4.0
    minimum_curve_length: float = 1e-6
    maximum_generic_turn_per_joint_pi: float = 0.95
    optimization_clearance: float = 1e-5
    closure_tolerance: float = 1e-8
    tangent_tolerance: float = 1e-7
    angle_tolerance: float = 1e-7
    length_tolerance: float = 1e-8
    intersection_tolerance: float = 1e-7
    minimum_area: float = 1e-8
    minimum_sample_edge_length: float = 1e-9

    @staticmethod
    def from_mapping(config: Mapping[str, Any]) -> "GeometrySolverConfig":
        return GeometrySolverConfig(
            intermediate_points_per_generic_curve=max(
                0, int(config.get("intermediate_points_per_generic_curve", 1))
            ),
            arc_sample_count=max(8, int(config.get("arc_sample_count", 48))),
            max_restarts=max(1, int(config.get("max_restarts", 32))),
            max_function_evaluations=max(
                100, int(config.get("max_function_evaluations", 5000))
            ),
            random_seed=int(config.get("random_seed", 0)),
            maximum_curve_length=float(config.get("maximum_curve_length", 4.0)),
            minimum_curve_length=float(config.get("minimum_curve_length", 1e-6)),
            maximum_generic_turn_per_joint_pi=float(
                config.get("maximum_generic_turn_per_joint_pi", 0.95)
            ),
            optimization_clearance=float(config.get("optimization_clearance", 1e-5)),
            closure_tolerance=float(config.get("closure_tolerance", 1e-8)),
            tangent_tolerance=float(config.get("tangent_tolerance", 1e-7)),
            angle_tolerance=float(config.get("angle_tolerance", 1e-7)),
            length_tolerance=float(config.get("length_tolerance", 1e-8)),
            intersection_tolerance=float(config.get("intersection_tolerance", 1e-7)),
            minimum_area=float(config.get("minimum_area", 1e-8)),
            minimum_sample_edge_length=float(
                config.get("minimum_sample_edge_length", 1e-9)
            ),
        )


@dataclass(frozen=True)
class GeometryAttemptResult:
    solution: GeometrySolution | None
    reason: str
    attempts: int
    best_cost: float | None
    best_validation: Mapping[str, Any] | None


@dataclass(frozen=True)
class _ParameterLayout:
    formal_names: Tuple[str, ...]
    generic_components: Tuple[str, ...]
    slices: Mapping[str, slice]
    lower_bounds: np.ndarray
    upper_bounds: np.ndarray
    initial: np.ndarray


@dataclass(frozen=True)
class _BuiltGeometry:
    parameter_values: Mapping[str, float]
    template_parameters: Mapping[str, Mapping[str, Any]]
    local_templates: Mapping[str, LocalCurveGeometry]
    point_positions: Tuple[np.ndarray, ...]
    point_incoming_tangents: Tuple[float, ...]
    point_outgoing_tangents: Tuple[float, ...]
    target_angles: Tuple[float, ...]
    occurrences: Tuple[OccurrenceGeometry, ...]
    final_tangent_after_closure_vertex: float


def _rotation(angle: float) -> np.ndarray:
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return np.asarray(((cosine, -sine), (sine, cosine)), dtype=float)


def _softmax_with_fixed_last(values: np.ndarray) -> np.ndarray:
    augmented = np.concatenate((values, np.zeros(1, dtype=float)))
    shifted = augmented - np.max(augmented)
    exponentials = np.exp(shifted)
    return exponentials / np.sum(exponentials)


def _transform_local_geometry(
    geometry: LocalCurveGeometry,
    transform: TransformSpec,
) -> LocalCurveGeometry:
    control = np.asarray(geometry.control_points, dtype=float)
    samples = np.asarray(geometry.sample_points, dtype=float)
    center = None if geometry.arc_center is None else np.asarray(geometry.arc_center, dtype=float)
    turn = float(geometry.total_turn)
    sweep = geometry.arc_sweep

    if transform.reverse:
        endpoint = control[-1].copy()
        reverse_rotation = _rotation(-(turn + math.pi))
        control = np.asarray(
            [reverse_rotation @ (point - endpoint) for point in reversed(control)],
            dtype=float,
        )
        sample_endpoint = samples[-1].copy()
        samples = np.asarray(
            [reverse_rotation @ (point - sample_endpoint) for point in reversed(samples)],
            dtype=float,
        )
        if center is not None:
            center = reverse_rotation @ (center - endpoint)
        turn = -turn
        if sweep is not None:
            sweep = -float(sweep)

    if transform.mirror:
        control = control.copy()
        samples = samples.copy()
        control[:, 1] *= -1.0
        samples[:, 1] *= -1.0
        if center is not None:
            center = center.copy()
            center[1] *= -1.0
        turn = -turn
        if sweep is not None:
            sweep = -float(sweep)

    return LocalCurveGeometry(
        component_id=geometry.component_id,
        curve_type=geometry.curve_type,
        length=geometry.length,
        total_turn=turn,
        control_points=control,
        sample_points=samples,
        arc_center=center,
        arc_radius=geometry.arc_radius,
        arc_sweep=sweep,
    )


def _world_geometry(
    local: LocalCurveGeometry,
    *,
    start_point: np.ndarray,
    start_tangent: float,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    rotation = _rotation(start_tangent)
    control = np.asarray([start_point + rotation @ point for point in local.control_points])
    samples = np.asarray([start_point + rotation @ point for point in local.sample_points])
    center = (
        None
        if local.arc_center is None
        else start_point + rotation @ np.asarray(local.arc_center)
    )
    return control, samples, center


def _expression_parameter_roles(problem: FormalGeometryProblem) -> Tuple[set[str], set[str]]:
    angle_parameters: set[str] = set()
    length_parameters: set[str] = set()
    for point in problem.points:
        angle_parameters.update(point.angle_pi.parameters)
    for component in problem.components:
        length_parameters.update(component.length.parameters)
        if component.turn_pi is not None:
            angle_parameters.update(component.turn_pi.parameters)
    return angle_parameters, length_parameters


def _pure_parameter(formula: LinearFormula) -> str | None:
    if formula.constant != 0.0 or len(formula.terms) != 1:
        return None
    name, coefficient = formula.terms[0]
    if abs(coefficient - 1.0) <= 1e-12:
        return name
    return None


class NumericalContourSolver:
    """Numerically realize one decorated formal contour.

    This solver intentionally ignores the assembly of congruent copies. It builds
    only one closed piece contour. Generic curve templates are represented by a
    polyline with a configurable number of intermediate points. Circular arcs are
    represented analytically and sampled only for validation.
    """

    def __init__(self, config: GeometrySolverConfig) -> None:
        self.config = config

    def solve(self, problem: FormalGeometryProblem) -> GeometryAttemptResult:
        started = time.perf_counter()
        layout = self._build_layout(problem)
        rng_seed = self.config.random_seed ^ int(
            hashlib.sha256(problem.formal_profile_id.encode("utf-8")).hexdigest()[:8], 16
        )
        rng = np.random.default_rng(rng_seed)
        best_cost = math.inf
        best_validation = None
        best_reason = "no optimization attempt completed"

        for attempt_index in range(self.config.max_restarts):
            initial = self._restart_initial(layout, rng, attempt_index)
            result = least_squares(
                lambda vector: self._residual(problem, layout, vector),
                initial,
                bounds=(layout.lower_bounds, layout.upper_bounds),
                max_nfev=self.config.max_function_evaluations,
                xtol=1e-12,
                ftol=1e-12,
                gtol=1e-12,
                verbose=0,
            )
            cost = float(2.0 * result.cost)
            built = self._build_geometry(problem, layout, result.x)
            validation = validate_geometry(
                built.occurrences,
                built.target_angles,
                closure_tolerance=self.config.closure_tolerance,
                tangent_tolerance=self.config.tangent_tolerance,
                angle_tolerance=self.config.angle_tolerance,
                length_tolerance=self.config.length_tolerance,
                intersection_tolerance=self.config.intersection_tolerance,
                minimum_area=self.config.minimum_area,
                minimum_edge_length=self.config.minimum_sample_edge_length,
            )
            if cost < best_cost:
                best_cost = cost
                best_validation = validation.to_dict()
                failed = [name for name, passed, _detail in validation.checks if not passed]
                best_reason = (
                    "validation failed: " + ", ".join(failed)
                    if failed
                    else "optimizer did not report an acceptable result"
                )
            if validation.passed:
                elapsed = time.perf_counter() - started
                solution = self._solution_record(
                    problem,
                    built,
                    validation,
                    attempt_index=attempt_index,
                    optimizer_result=result,
                    elapsed_seconds=elapsed,
                )
                return GeometryAttemptResult(
                    solution=solution,
                    reason="solved",
                    attempts=attempt_index + 1,
                    best_cost=cost,
                    best_validation=validation.to_dict(),
                )

        return GeometryAttemptResult(
            solution=None,
            reason=best_reason,
            attempts=self.config.max_restarts,
            best_cost=None if math.isinf(best_cost) else best_cost,
            best_validation=best_validation,
        )

    def _build_layout(self, problem: FormalGeometryProblem) -> _ParameterLayout:
        angle_parameters, length_parameters = _expression_parameter_roles(problem)
        formal_names = problem.parameter_names
        lower = []
        upper = []
        initial = []
        initial_by_name: Dict[str, float] = {}

        for component in problem.components:
            parameter = _pure_parameter(component.length)
            if parameter and component.search_witness_length is not None:
                initial_by_name.setdefault(parameter, component.search_witness_length)
        for point in problem.points:
            parameter = _pure_parameter(point.angle_pi)
            if parameter and point.witness_angle_pi is not None:
                initial_by_name.setdefault(parameter, point.witness_angle_pi)

        for name in formal_names:
            if name in length_parameters:
                lower.append(self.config.minimum_curve_length)
                upper.append(self.config.maximum_curve_length)
                initial.append(
                    min(
                        self.config.maximum_curve_length * 0.9,
                        max(
                            self.config.minimum_curve_length * 10.0,
                            initial_by_name.get(name, 0.25),
                        ),
                    )
                )
            else:
                lower.append(-4.0)
                upper.append(4.0)
                initial.append(initial_by_name.get(name, 1.0))

        slices: Dict[str, slice] = {}
        generic_components = []
        offset = len(formal_names)
        intermediate_count = self.config.intermediate_points_per_generic_curve
        edge_count = intermediate_count + 1
        shape_parameter_count = max(0, edge_count - 1) + max(0, edge_count - 1)
        for component in problem.components:
            if component.curve_type != "generic_curve" or component.forced_straight:
                continue
            generic_components.append(component.component_id)
            slices[component.component_id] = slice(offset, offset + shape_parameter_count)
            offset += shape_parameter_count
            lower.extend([-6.0] * max(0, edge_count - 1))
            upper.extend([6.0] * max(0, edge_count - 1))
            maximum_turn = math.pi * self.config.maximum_generic_turn_per_joint_pi
            lower.extend([-maximum_turn] * max(0, edge_count - 1))
            upper.extend([maximum_turn] * max(0, edge_count - 1))
            initial.extend([0.0] * shape_parameter_count)

        return _ParameterLayout(
            formal_names=formal_names,
            generic_components=tuple(generic_components),
            slices=slices,
            lower_bounds=np.asarray(lower, dtype=float),
            upper_bounds=np.asarray(upper, dtype=float),
            initial=np.asarray(initial, dtype=float),
        )

    def _restart_initial(
        self,
        layout: _ParameterLayout,
        rng: np.random.Generator,
        attempt_index: int,
    ) -> np.ndarray:
        if attempt_index == 0:
            return layout.initial.copy()
        result = layout.initial.copy()
        span = layout.upper_bounds - layout.lower_bounds
        noise_scale = min(0.45, 0.08 + 0.03 * attempt_index)
        result += rng.normal(0.0, noise_scale, size=result.shape) * span
        result = np.minimum(layout.upper_bounds - 1e-10, np.maximum(layout.lower_bounds + 1e-10, result))
        return result

    def _formal_values(
        self, layout: _ParameterLayout, vector: np.ndarray
    ) -> Dict[str, float]:
        return {
            name: float(vector[index]) for index, name in enumerate(layout.formal_names)
        }

    def _component_template(
        self,
        component: FormalCurveComponent,
        formal_values: Mapping[str, float],
        shape_values: np.ndarray,
    ) -> Tuple[LocalCurveGeometry, Mapping[str, Any]]:
        length = float(component.length.evaluate(formal_values))
        if component.curve_type == "circular_arc":
            if component.turn_pi is None:
                turn = 2.0 * math.pi * length
            else:
                turn = math.pi * float(component.turn_pi.evaluate(formal_values))
            if abs(turn) <= 1e-12:
                radius = math.inf
                endpoint = np.asarray((length, 0.0), dtype=float)
                center = None
                samples = np.asarray(
                    [
                        (length * index / self.config.arc_sample_count, 0.0)
                        for index in range(self.config.arc_sample_count + 1)
                    ],
                    dtype=float,
                )
            else:
                signed_radius = length / turn
                radius = abs(signed_radius)
                center = np.asarray((0.0, signed_radius), dtype=float)
                endpoint = np.asarray(
                    (
                        signed_radius * math.sin(turn),
                        signed_radius * (1.0 - math.cos(turn)),
                    ),
                    dtype=float,
                )
                samples = np.asarray(
                    [
                        (
                            signed_radius * math.sin(turn * index / self.config.arc_sample_count),
                            signed_radius
                            * (1.0 - math.cos(turn * index / self.config.arc_sample_count)),
                        )
                        for index in range(self.config.arc_sample_count + 1)
                    ],
                    dtype=float,
                )
            geometry = LocalCurveGeometry(
                component_id=component.component_id,
                curve_type="circular_arc",
                length=length,
                total_turn=turn,
                control_points=np.asarray(((0.0, 0.0), endpoint), dtype=float),
                sample_points=samples,
                arc_center=center,
                arc_radius=radius,
                arc_sweep=turn,
            )
            return geometry, {
                "curve_type": "circular_arc",
                "length": length,
                "turn_radians": turn,
                "radius": radius,
                "circle_class": component.circle_class,
            }

        if component.curve_type == "straight_segment" or component.forced_straight:
            geometry = LocalCurveGeometry(
                component_id=component.component_id,
                curve_type="straight_segment",
                length=length,
                total_turn=0.0,
                control_points=np.asarray(((0.0, 0.0), (length, 0.0)), dtype=float),
                sample_points=np.asarray(((0.0, 0.0), (length, 0.0)), dtype=float),
            )
            return geometry, {
                "curve_type": "straight_segment",
                "length": length,
                "intermediate_point_count": 0,
            }

        intermediate_count = self.config.intermediate_points_per_generic_curve
        edge_count = intermediate_count + 1
        split = max(0, edge_count - 1)
        logits = shape_values[:split]
        turns = shape_values[split:]
        fractions = _softmax_with_fixed_last(logits) if edge_count > 1 else np.ones(1)
        headings = [0.0]
        for increment in turns:
            headings.append(headings[-1] + float(increment))
        points = [np.zeros(2, dtype=float)]
        for fraction, heading in zip(fractions, headings):
            displacement = length * float(fraction) * np.asarray(
                (math.cos(heading), math.sin(heading)), dtype=float
            )
            points.append(points[-1] + displacement)
        geometry = LocalCurveGeometry(
            component_id=component.component_id,
            curve_type="generic_curve",
            length=length,
            total_turn=headings[-1],
            control_points=np.asarray(points, dtype=float),
            sample_points=np.asarray(points, dtype=float),
        )
        return geometry, {
            "curve_type": "generic_curve",
            "length": length,
            "intermediate_point_count": intermediate_count,
            "edge_length_fractions": [float(value) for value in fractions],
            "turn_increments_radians": [float(value) for value in turns],
            "total_turn_radians": float(headings[-1]),
        }

    def _build_geometry(
        self,
        problem: FormalGeometryProblem,
        layout: _ParameterLayout,
        vector: np.ndarray,
    ) -> _BuiltGeometry:
        formal_values = self._formal_values(layout, vector)
        component_map = problem.component_map
        local_templates: Dict[str, LocalCurveGeometry] = {}
        template_parameters: Dict[str, Mapping[str, Any]] = {}
        for component in problem.components:
            shape_slice = layout.slices.get(component.component_id)
            shape_values = (
                np.zeros(0, dtype=float)
                if shape_slice is None
                else vector[shape_slice]
            )
            geometry, parameters = self._component_template(
                component, formal_values, shape_values
            )
            local_templates[component.component_id] = geometry
            template_parameters[component.component_id] = parameters

        target_angles = tuple(
            math.pi * point.angle_pi.evaluate(formal_values) for point in problem.points
        )
        point_positions = [np.zeros(2, dtype=float)]
        point_outgoing = [0.0]
        point_incoming = [math.nan] * len(problem.points)
        occurrences = []
        current_point = np.zeros(2, dtype=float)
        current_tangent = 0.0

        for index, segment in enumerate(problem.segments):
            component = component_map[segment.component_id]
            transform = component.transform_for_variable(segment.variable)
            if segment.literal_inverse:
                transform = transform.compose(TransformSpec(reverse=True))
            local = _transform_local_geometry(local_templates[segment.component_id], transform)
            control, samples, center = _world_geometry(
                local,
                start_point=current_point,
                start_tangent=current_tangent,
            )
            end_tangent = current_tangent + local.total_turn
            occurrence = OccurrenceGeometry(
                segment_index=segment.segment_index,
                literal=segment.literal,
                variable=segment.variable,
                component_id=segment.component_id,
                transform=transform,
                curve_type=local.curve_type,
                circle_class=component.circle_class,
                start_point=current_point.copy(),
                end_point=control[-1].copy(),
                start_tangent=current_tangent,
                end_tangent=end_tangent,
                control_points=control,
                sample_points=samples,
                length=local.length,
                total_turn=local.total_turn,
                arc_center=center,
                arc_radius=local.arc_radius,
                arc_sweep=local.arc_sweep,
            )
            occurrences.append(occurrence)
            next_boundary = (index + 1) % len(problem.points)
            point_incoming[next_boundary] = end_tangent
            next_tangent = end_tangent + math.pi - target_angles[next_boundary]
            current_point = control[-1].copy()
            current_tangent = next_tangent
            if next_boundary != 0:
                point_positions.append(current_point.copy())
                point_outgoing.append(current_tangent)

        return _BuiltGeometry(
            parameter_values=formal_values,
            template_parameters=template_parameters,
            local_templates=local_templates,
            point_positions=tuple(point_positions),
            point_incoming_tangents=tuple(float(value) for value in point_incoming),
            point_outgoing_tangents=tuple(float(value) for value in point_outgoing),
            target_angles=target_angles,
            occurrences=tuple(occurrences),
            final_tangent_after_closure_vertex=current_tangent,
        )

    def _residual(
        self,
        problem: FormalGeometryProblem,
        layout: _ParameterLayout,
        vector: np.ndarray,
    ) -> np.ndarray:
        built = self._build_geometry(problem, layout, vector)
        formal_values = built.parameter_values
        residuals = []
        closure = built.occurrences[-1].end_point - built.occurrences[0].start_point
        residuals.extend((float(closure[0]), float(closure[1])))
        angular_error = built.final_tangent_after_closure_vertex - built.occurrences[0].start_tangent
        residuals.extend((math.sin(angular_error), 1.0 - math.cos(angular_error)))

        positivity_weight = 10.0
        for point in problem.points:
            angle_pi = point.angle_pi.evaluate(formal_values)
            residuals.append(positivity_weight * max(0.0, 1e-5 - angle_pi))
            residuals.append(positivity_weight * max(0.0, angle_pi - (2.0 - 1e-5)))
        for component in problem.components:
            length = component.length.evaluate(formal_values)
            residuals.append(
                positivity_weight * max(0.0, self.config.minimum_curve_length - length)
            )
            if component.curve_type == "circular_arc" and component.turn_pi is not None:
                turn_pi = component.turn_pi.evaluate(formal_values)
                residuals.append(positivity_weight * max(0.0, 1e-6 - abs(turn_pi)))

        polyline = sampled_polyline(built.occurrences)
        minimum_distance, intersections = nonadjacent_distances(polyline)
        if minimum_distance is None:
            minimum_distance = self.config.optimization_clearance
        residuals.append(
            5.0 * max(0.0, self.config.optimization_clearance - minimum_distance)
        )
        residuals.append(5.0 * float(intersections))
        area = abs(signed_area(polyline))
        residuals.append(5.0 * max(0.0, self.config.minimum_area - area))

        regularization = 1e-5
        for component_id in layout.generic_components:
            shape_slice = layout.slices[component_id]
            residuals.extend(regularization * vector[shape_slice])
        return np.asarray(residuals, dtype=float)

    def _solution_record(
        self,
        problem: FormalGeometryProblem,
        built: _BuiltGeometry,
        validation,
        *,
        attempt_index: int,
        optimizer_result,
        elapsed_seconds: float,
    ) -> GeometrySolution:
        point_records = []
        for index, point_spec in enumerate(problem.points):
            incoming = built.point_incoming_tangents[index]
            outgoing = built.point_outgoing_tangents[index]
            measured_turn = angle_wrap(outgoing - incoming)
            reconstructed_angle = math.pi - measured_turn
            point_records.append(
                {
                    "boundary_index": index,
                    "position": point_record(built.point_positions[index]),
                    "angle_class": point_spec.angle_class,
                    "angle_class_sign": point_spec.angle_class_sign,
                    "occurrences": list(point_spec.occurrences),
                    "roles": list(point_spec.roles),
                    "target_interior_angle_radians": built.target_angles[index],
                    "target_interior_angle_pi": built.target_angles[index] / math.pi,
                    "reconstructed_interior_angle_radians": reconstructed_angle,
                    "incoming_tangent_radians": incoming,
                    "outgoing_tangent_radians": outgoing,
                }
            )

        occurrence_records = []
        for occurrence in built.occurrences:
            record: Dict[str, Any] = {
                "segment_index": occurrence.segment_index,
                "literal": occurrence.literal,
                "variable": occurrence.variable,
                "curve_component": occurrence.component_id,
                "template_transform": occurrence.transform.label,
                "curve_type": occurrence.curve_type,
                "length": occurrence.length,
                "total_turn_radians": occurrence.total_turn,
                "start_point": point_record(occurrence.start_point),
                "end_point": point_record(occurrence.end_point),
                "start_tangent_radians": occurrence.start_tangent,
                "end_tangent_radians": occurrence.end_tangent,
                "control_points": [point_record(point) for point in occurrence.control_points],
                "validation_sample_count": len(occurrence.sample_points),
            }
            if occurrence.curve_type == "circular_arc":
                record["circular_arc"] = {
                    "center": (
                        None if occurrence.arc_center is None else point_record(occurrence.arc_center)
                    ),
                    "radius": occurrence.arc_radius,
                    "signed_sweep_radians": occurrence.arc_sweep,
                }
            occurrence_records.append(record)

        template_records = []
        component_map = problem.component_map
        for component_id, local in built.local_templates.items():
            component = component_map[component_id]
            record: Dict[str, Any] = {
                "component_id": component_id,
                "representative": component.representative,
                "variables": list(component.variables),
                "variable_transforms": {
                    variable: transform.label
                    for variable, transform in component.variable_transforms
                },
                "curve_type": local.curve_type,
                "circle_class": component.circle_class,
                "length": local.length,
                "total_turn_radians": local.total_turn,
                "local_control_points": [point_record(point) for point in local.control_points],
                "validation_sample_count": len(local.sample_points),
            }
            if local.curve_type == "circular_arc":
                record["circular_arc"] = {
                    "center": None if local.arc_center is None else point_record(local.arc_center),
                    "radius": local.arc_radius,
                    "signed_sweep_radians": local.arc_sweep,
                }
            template_records.append(record)

        solution_payload_for_hash = {
            "formal_profile_id": problem.formal_profile_id,
            "parameters": sorted(built.parameter_values.items()),
            "points": [record["position"] for record in point_records],
            "occurrences": [
                {
                    "literal": record["literal"],
                    "control_points": record["control_points"],
                }
                for record in occurrence_records
            ],
        }
        encoded = json.dumps(
            solution_payload_for_hash,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        solution_id = "geo-" + hashlib.sha256(encoded).hexdigest()[:32]
        return GeometrySolution(
            formal_profile_id=problem.formal_profile_id,
            solution_id=solution_id,
            parameter_values=tuple(sorted(built.parameter_values.items())),
            template_parameters=tuple(sorted(built.template_parameters.items())),
            points=tuple(point_records),
            occurrences=tuple(occurrence_records),
            templates=tuple(template_records),
            validation=validation,
            optimization={
                "method": "scipy.optimize.least_squares",
                "attempt_index": attempt_index,
                "attempt_count": attempt_index + 1,
                "success_flag": bool(optimizer_result.success),
                "status": int(optimizer_result.status),
                "message": str(optimizer_result.message),
                "function_evaluations": int(optimizer_result.nfev),
                "residual_sum_of_squares": float(2.0 * optimizer_result.cost),
                "elapsed_seconds": elapsed_seconds,
                "generic_intermediate_points_per_template": self.config.intermediate_points_per_generic_curve,
                "arc_validation_sample_count": self.config.arc_sample_count,
            },
        )
