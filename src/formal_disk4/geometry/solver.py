from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Sequence, Tuple

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
from .validation import (
    pairwise_clearance_penalties,
    sampled_polyline,
    signed_area,
    validate_geometry,
)


@dataclass(frozen=True)
class GeometrySolverConfig:
    intermediate_points_per_generic_curve: int = 1
    arc_sample_count: int = 48
    max_restarts: int = 32
    max_function_evaluations: int = 1000
    candidate_timeout_seconds: float = 20.0
    enable_clearance_refinement: bool = True
    coarse_collision_sample_count: int = 8
    max_refinement_evaluations: int = 160
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
        timeout = config.get("candidate_timeout_seconds", 20.0)
        return GeometrySolverConfig(
            intermediate_points_per_generic_curve=max(
                0, int(config.get("intermediate_points_per_generic_curve", 1))
            ),
            arc_sample_count=max(8, int(config.get("arc_sample_count", 48))),
            # Keep the historical keys as public aliases. Their new meaning is
            # closure starts/evaluations, not full collision validations.
            max_restarts=max(1, int(config.get("max_restarts", 32))),
            max_function_evaluations=max(
                1, int(config.get("max_function_evaluations", 1000))
            ),
            candidate_timeout_seconds=max(0.0, float(timeout)),
            enable_clearance_refinement=bool(
                config.get("enable_clearance_refinement", True)
            ),
            coarse_collision_sample_count=max(
                4, int(config.get("coarse_collision_sample_count", 8))
            ),
            max_refinement_evaluations=max(
                1, int(config.get("max_refinement_evaluations", 160))
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


class _CandidateTimeout(RuntimeError):
    pass


class _AcceptedSolution(RuntimeError):
    def __init__(self, vector: np.ndarray) -> None:
        super().__init__("valid geometry found")
        self.vector = np.asarray(vector, dtype=float).copy()


@dataclass
class _SolveMonitor:
    deadline: float | None
    best_cost: float = math.inf
    evaluations: int = 0

    def check(self) -> None:
        if self.deadline is not None and time.perf_counter() >= self.deadline:
            raise _CandidateTimeout

    def observe(self, residual: np.ndarray) -> None:
        self.evaluations += 1
        cost = float(np.dot(residual, residual))
        if cost < self.best_cost:
            self.best_cost = cost
        self.check()


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
        deadline = (
            None
            if self.config.candidate_timeout_seconds <= 0.0
            else started + self.config.candidate_timeout_seconds
        )

        if layout.initial.size == 0:
            return self._solve_fixed(problem, layout, started)

        rng_seed = self.config.random_seed ^ int(
            hashlib.sha256(problem.formal_profile_id.encode("utf-8")).hexdigest()[:8], 16
        )
        rng = np.random.default_rng(rng_seed)
        monitor = _SolveMonitor(deadline=deadline)
        best_validation: Mapping[str, Any] | None = None
        best_reason = "closure_not_found"
        unique_closed_vectors: list[np.ndarray] = []
        attempts_completed = 0

        for attempt_index in range(self.config.max_restarts):
            try:
                monitor.check()
                attempts_completed = attempt_index + 1
                initial = self._restart_initial(layout, rng, attempt_index)
                accepted_vector: np.ndarray | None = None
                accepted_validation = None
                accepted_built: _BuiltGeometry | None = None
                last_checked: np.ndarray | None = None

                def closure_residual(vector: np.ndarray) -> np.ndarray:
                    residual = self._closure_residual(problem, layout, vector)
                    monitor.observe(residual)
                    return residual

                def stop_when_valid(intermediate_result) -> None:
                    nonlocal accepted_vector, accepted_validation, accepted_built
                    nonlocal last_checked, best_validation, best_reason
                    monitor.check()
                    vector = np.asarray(intermediate_result.x, dtype=float)
                    metrics = self._closure_metrics(problem, layout, vector)
                    if not self._closure_is_close(metrics):
                        return
                    if last_checked is not None and np.linalg.norm(vector - last_checked) <= 1e-10:
                        return
                    last_checked = vector.copy()
                    validation, built_candidate = self._full_validation(
                        problem, layout, vector
                    )
                    if validation.passed:
                        accepted_vector = vector.copy()
                        accepted_validation = validation
                        accepted_built = built_candidate
                        raise _AcceptedSolution(vector)
                    best_validation = validation.to_dict()
                    best_reason = self._validation_reason(validation)

                result = None
                try:
                    result = least_squares(
                        closure_residual,
                        initial,
                        bounds=(layout.lower_bounds, layout.upper_bounds),
                        max_nfev=self.config.max_function_evaluations,
                        xtol=1e-11,
                        ftol=1e-11,
                        gtol=1e-11,
                        verbose=0,
                        callback=stop_when_valid,
                    )
                    solution_vector = np.asarray(result.x, dtype=float)
                except _AcceptedSolution as accepted:
                    solution_vector = accepted.vector

                if accepted_vector is None:
                    metrics = self._closure_metrics(problem, layout, solution_vector)
                    if not self._closure_is_close(metrics):
                        best_validation = self._closure_precheck_record(metrics)
                        best_reason = "closure_not_found"
                        continue
                    validation, built = self._full_validation(
                        problem, layout, solution_vector
                    )
                else:
                    assert accepted_validation is not None and accepted_built is not None
                    validation, built = accepted_validation, accepted_built
                    solution_vector = accepted_vector

                if validation.passed:
                    return self._successful_result(
                        problem=problem,
                        built=built,
                        validation=validation,
                        vector=solution_vector,
                        layout=layout,
                        started=started,
                        attempts=attempts_completed,
                        attempt_index=attempt_index,
                        optimizer_result=result,
                        monitor=monitor,
                        method="staged_closure_least_squares",
                    )

                best_validation = validation.to_dict()
                best_reason = self._validation_reason(validation)
                if not any(
                    np.linalg.norm(solution_vector - previous) <= 1e-8
                    for previous in unique_closed_vectors
                ):
                    unique_closed_vectors.append(solution_vector.copy())

                if (
                    self.config.enable_clearance_refinement
                    and self._needs_clearance_refinement(validation)
                ):
                    refined = self._refine_closed_geometry(
                        problem, layout, solution_vector, monitor
                    )
                    if refined is not None:
                        refined_validation, refined_built = self._full_validation(
                            problem, layout, refined
                        )
                        if refined_validation.passed:
                            return self._successful_result(
                                problem=problem,
                                built=refined_built,
                                validation=refined_validation,
                                vector=refined,
                                layout=layout,
                                started=started,
                                attempts=attempts_completed,
                                attempt_index=attempt_index,
                                optimizer_result=None,
                                monitor=monitor,
                                method="staged_closure_with_clearance_refinement",
                            )
                        best_validation = refined_validation.to_dict()
                        best_reason = self._validation_reason(refined_validation)
            except _CandidateTimeout:
                elapsed = time.perf_counter() - started
                return GeometryAttemptResult(
                    solution=None,
                    reason=(
                        f"candidate_timeout after {elapsed:.3f}s; "
                        f"best_stage={best_reason}"
                    ),
                    attempts=attempts_completed,
                    best_cost=None if math.isinf(monitor.best_cost) else monitor.best_cost,
                    best_validation=best_validation,
                )

        return GeometryAttemptResult(
            solution=None,
            reason=best_reason,
            attempts=attempts_completed,
            best_cost=None if math.isinf(monitor.best_cost) else monitor.best_cost,
            best_validation=best_validation,
        )

    def _solve_fixed(
        self,
        problem: FormalGeometryProblem,
        layout: _ParameterLayout,
        started: float,
    ) -> GeometryAttemptResult:
        vector = layout.initial.copy()
        metrics = self._closure_metrics(problem, layout, vector)
        if not self._closure_is_close(metrics):
            return GeometryAttemptResult(
                solution=None,
                reason="fixed geometry failed closure precheck: "
                + ", ".join(metrics["failed_checks"]),
                attempts=0,
                best_cost=float(metrics["cost"]),
                best_validation=self._closure_precheck_record(metrics),
            )
        validation, built = self._full_validation(problem, layout, vector)
        residual = self._closure_residual(problem, layout, vector)
        cost = float(np.dot(residual, residual))
        if not validation.passed:
            return GeometryAttemptResult(
                solution=None,
                reason="fixed geometry failed validation: "
                + self._validation_reason(validation),
                attempts=0,
                best_cost=cost,
                best_validation=validation.to_dict(),
            )
        elapsed = time.perf_counter() - started
        solution = self._solution_record(
            problem,
            built,
            validation,
            optimization={
                "method": "deterministic_fixed_geometry",
                "degrees_of_freedom": 0,
                "attempt_index": None,
                "attempt_count": 0,
                "success_flag": True,
                "status": 0,
                "message": "No free geometry parameters; evaluated the unique contour once.",
                "function_evaluations": 0,
                "residual_sum_of_squares": cost,
                "elapsed_seconds": elapsed,
                "candidate_timeout_seconds": self.config.candidate_timeout_seconds,
                "generic_intermediate_points_per_template": self.config.intermediate_points_per_generic_curve,
                "arc_validation_sample_count": self.config.arc_sample_count,
            },
        )
        return GeometryAttemptResult(
            solution=solution,
            reason="solved fixed geometry",
            attempts=0,
            best_cost=cost,
            best_validation=validation.to_dict(),
        )

    def _successful_result(
        self,
        *,
        problem: FormalGeometryProblem,
        built: _BuiltGeometry,
        validation,
        vector: np.ndarray,
        layout: _ParameterLayout,
        started: float,
        attempts: int,
        attempt_index: int,
        optimizer_result,
        monitor: _SolveMonitor,
        method: str,
    ) -> GeometryAttemptResult:
        elapsed = time.perf_counter() - started
        residual = self._closure_residual(problem, layout, vector)
        cost = float(np.dot(residual, residual))
        solution = self._solution_record(
            problem,
            built,
            validation,
            optimization={
                "method": method,
                "degrees_of_freedom": int(layout.initial.size),
                "attempt_index": attempt_index,
                "attempt_count": attempts,
                "success_flag": bool(
                    True if optimizer_result is None else optimizer_result.success
                ),
                "status": int(0 if optimizer_result is None else optimizer_result.status),
                "message": str(
                    "Valid closed contour found during staged search."
                    if optimizer_result is None
                    else optimizer_result.message
                ),
                "function_evaluations": monitor.evaluations,
                "residual_sum_of_squares": cost,
                "elapsed_seconds": elapsed,
                "candidate_timeout_seconds": self.config.candidate_timeout_seconds,
                "generic_intermediate_points_per_template": self.config.intermediate_points_per_generic_curve,
                "arc_validation_sample_count": self.config.arc_sample_count,
            },
        )
        return GeometryAttemptResult(
            solution=solution,
            reason="solved",
            attempts=attempts,
            best_cost=cost,
            best_validation=validation.to_dict(),
        )

    @staticmethod
    def _validation_reason(validation) -> str:
        failed = [name for name, passed, _detail in validation.checks if not passed]
        return "validation_failed:" + (",".join(failed) if failed else "unknown")

    @staticmethod
    def _needs_clearance_refinement(validation) -> bool:
        failed = {name for name, passed, _detail in validation.checks if not passed}
        return bool(
            failed.intersection(
                {"no_sampled_self_intersection", "nonzero_enclosed_area"}
            )
        )

    def _validate_built(self, built: _BuiltGeometry):
        return validate_geometry(
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
        *,
        arc_sample_count: int,
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
                        (length * index / arc_sample_count, 0.0)
                        for index in range(arc_sample_count + 1)
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
                            signed_radius * math.sin(turn * index / arc_sample_count),
                            signed_radius
                            * (1.0 - math.cos(turn * index / arc_sample_count)),
                        )
                        for index in range(arc_sample_count + 1)
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
        *,
        arc_sample_count: int | None = None,
    ) -> _BuiltGeometry:
        if arc_sample_count is None:
            arc_sample_count = self.config.arc_sample_count
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
                component,
                formal_values,
                shape_values,
                arc_sample_count=arc_sample_count,
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

    def _closure_residual(
        self,
        problem: FormalGeometryProblem,
        layout: _ParameterLayout,
        vector: np.ndarray,
    ) -> np.ndarray:
        # Two samples per arc are enough to propagate exact analytic endpoints.
        built = self._build_geometry(problem, layout, vector, arc_sample_count=1)
        formal_values = built.parameter_values
        closure = built.occurrences[-1].end_point - built.occurrences[0].start_point
        angular_error = angle_wrap(
            built.final_tangent_after_closure_vertex
            - built.occurrences[0].start_tangent
        )
        residuals = [
            10.0 * float(closure[0]),
            10.0 * float(closure[1]),
            math.sin(angular_error),
            1.0 - math.cos(angular_error),
        ]

        # These are cheap guards for linear formulas whose feasible region is
        # narrower than the box bounds of their free parameters.
        positivity_weight = 10.0
        for point in problem.points:
            angle_pi = point.angle_pi.evaluate(formal_values)
            residuals.append(positivity_weight * max(0.0, 1e-7 - angle_pi))
            residuals.append(positivity_weight * max(0.0, angle_pi - (2.0 - 1e-7)))
        for component in problem.components:
            length = component.length.evaluate(formal_values)
            residuals.append(
                positivity_weight
                * max(0.0, self.config.minimum_curve_length - length)
            )
            if component.turn_pi is not None:
                target_turn = math.pi * component.turn_pi.evaluate(formal_values)
                actual_turn = built.local_templates[component.component_id].total_turn
                residuals.append(actual_turn - target_turn)

        regularization = 1e-8
        for component_id in layout.generic_components:
            residuals.extend(regularization * vector[layout.slices[component_id]])
        return np.asarray(residuals, dtype=float)

    def _closure_metrics(
        self,
        problem: FormalGeometryProblem,
        layout: _ParameterLayout,
        vector: np.ndarray,
    ) -> Dict[str, Any]:
        built = self._build_geometry(problem, layout, vector, arc_sample_count=1)
        closure = built.occurrences[-1].end_point - built.occurrences[0].start_point
        closure_error = float(np.linalg.norm(closure))
        tangent_error = abs(
            angle_wrap(
                built.final_tangent_after_closure_vertex
                - built.occurrences[0].start_tangent
            )
        )
        failed = []
        if closure_error > self.config.closure_tolerance:
            failed.append("closed_contour")
        if tangent_error > self.config.tangent_tolerance:
            failed.append("closed_tangent_cycle")
        return {
            "closure_error": closure_error,
            "tangent_closure_error": tangent_error,
            "cost": closure_error * closure_error + tangent_error * tangent_error,
            "failed_checks": failed,
        }

    def _closure_is_close(
        self, metrics: Mapping[str, Any], *, multiplier: float = 1.0
    ) -> bool:
        return (
            float(metrics["closure_error"])
            <= multiplier * self.config.closure_tolerance
            and float(metrics["tangent_closure_error"])
            <= multiplier * self.config.tangent_tolerance
        )

    def _closure_precheck_record(self, metrics: Mapping[str, Any]) -> Dict[str, Any]:
        closure_error = float(metrics["closure_error"])
        tangent_error = float(metrics["tangent_closure_error"])
        return {
            "passed": False,
            "precheck_only": True,
            "closure_error": closure_error,
            "tangent_closure_error": tangent_error,
            "checks": [
                {
                    "name": "closed_contour",
                    "passed": closure_error <= self.config.closure_tolerance,
                    "detail": (
                        f"closure_error={closure_error:.3e}, "
                        f"tolerance={self.config.closure_tolerance:.3e}"
                    ),
                },
                {
                    "name": "closed_tangent_cycle",
                    "passed": tangent_error <= self.config.tangent_tolerance,
                    "detail": (
                        f"tangent_error={tangent_error:.3e}, "
                        f"tolerance={self.config.tangent_tolerance:.3e}"
                    ),
                },
            ],
        }

    def _full_validation(
        self,
        problem: FormalGeometryProblem,
        layout: _ParameterLayout,
        vector: np.ndarray,
    ):
        built = self._build_geometry(
            problem,
            layout,
            vector,
            arc_sample_count=self.config.arc_sample_count,
        )
        return self._validate_built(built), built

    def _refine_closed_geometry(
        self,
        problem: FormalGeometryProblem,
        layout: _ParameterLayout,
        initial: np.ndarray,
        monitor: _SolveMonitor,
    ) -> np.ndarray | None:
        if layout.initial.size <= 2:
            return None

        accepted: np.ndarray | None = None

        def residual(vector: np.ndarray) -> np.ndarray:
            monitor.check()
            built = self._build_geometry(
                problem,
                layout,
                vector,
                arc_sample_count=self.config.coarse_collision_sample_count,
            )
            closure_residual = self._closure_residual(problem, layout, vector)
            polyline = sampled_polyline(built.occurrences)
            clearance = pairwise_clearance_penalties(
                polyline, self.config.optimization_clearance
            )
            area = abs(signed_area(polyline))
            area_penalty = max(0.0, self.config.minimum_area - area)
            combined = np.concatenate(
                (
                    5.0 * closure_residual,
                    2.0 * clearance,
                    np.asarray((2.0 * area_penalty,), dtype=float),
                )
            )
            monitor.observe(combined)
            return combined

        def stop_when_valid(intermediate_result) -> None:
            nonlocal accepted
            monitor.check()
            vector = np.asarray(intermediate_result.x, dtype=float)
            metrics = self._closure_metrics(problem, layout, vector)
            if not self._closure_is_close(metrics, multiplier=4.0):
                return
            validation, _built = self._full_validation(problem, layout, vector)
            if validation.passed:
                accepted = vector.copy()
                raise _AcceptedSolution(vector)

        try:
            result = least_squares(
                residual,
                initial,
                bounds=(layout.lower_bounds, layout.upper_bounds),
                max_nfev=self.config.max_refinement_evaluations,
                xtol=1e-10,
                ftol=1e-10,
                gtol=1e-10,
                verbose=0,
                callback=stop_when_valid,
            )
            candidate = np.asarray(result.x, dtype=float)
        except _AcceptedSolution as found:
            candidate = found.vector
        return accepted if accepted is not None else candidate

    def _solution_record(
        self,
        problem: FormalGeometryProblem,
        built: _BuiltGeometry,
        validation,
        *,
        optimization: Mapping[str, Any],
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
            optimization=dict(optimization),
        )
