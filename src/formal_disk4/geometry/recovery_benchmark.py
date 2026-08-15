"""Known-positive stress benchmark for the numerical contour solver.

The generator first constructs a simple, strongly non-convex contour from a
mixture of straight segments, circular arcs and broken generic curves.  It then
keeps only the formal constraints that the production solver normally sees:
point angles, curve turns and unknown component lengths.  The exact lengths and
generic control points are retained privately as an oracle witness, never used
as the optimizer's initial point.

This is deliberately a white-box *certification* followed by a black-box
*recovery*: private construction helpers certify the oracle vector, while the
measurement itself calls ``NumericalContourSolver.solve`` unchanged.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .model import (
    FormalCurveComponent,
    FormalGeometryProblem,
    FormalPointSpec,
    FormalSegmentOccurrence,
    LinearFormula,
    TransformSpec,
    angle_wrap,
)
from .solver import GeometrySolverConfig, NumericalContourSolver


_DIFFICULTIES: Mapping[str, Mapping[str, float]] = {
    "moderate": {"inner_radius": 0.58, "arc_sweep_pi": 0.10, "jitter": 0.035},
    "strong": {"inner_radius": 0.36, "arc_sweep_pi": 0.18, "jitter": 0.055},
    "extreme": {"inner_radius": 0.23, "arc_sweep_pi": 0.25, "jitter": 0.075},
}


@dataclass(frozen=True)
class BenchmarkSettings:
    case_count: int = 6
    solver_repeats: int = 3
    generator_seed: int = 20260814
    vertex_counts: tuple[int, ...] = (8, 10, 12)
    difficulties: tuple[str, ...] = ("moderate", "strong", "extreme")
    output_directory: str = "output/geometry_recovery_benchmark"
    write_solutions: bool = True


@dataclass(frozen=True)
class _ComponentWitness:
    component_id: str
    curve_type: str
    edge_start: int
    edge_count: int
    length: float
    start_tangent: float
    end_tangent: float
    total_turn_radians: float
    generic_parameters: tuple[float, ...] = ()
    sweep_radians: float | None = None


@dataclass(frozen=True)
class GeneratedRecoveryCase:
    problem: FormalGeometryProblem
    oracle_vector: np.ndarray
    metadata: Mapping[str, Any]
    witness_record: Mapping[str, Any]


def _unit_formula(value: float) -> LinearFormula:
    return LinearFormula(float(value), (), f"{value:.17g}")


def _length_parameter(name: str) -> LinearFormula:
    return LinearFormula(0.0, ((name, 1.0),), name)


def _heading(vector: np.ndarray) -> float:
    return math.atan2(float(vector[1]), float(vector[0]))


def _polygon_area(points: Sequence[np.ndarray]) -> float:
    return 0.5 * sum(
        float(left[0] * right[1] - left[1] * right[0])
        for left, right in zip(points, (*points[1:], points[0]))
    )


def _convex_hull(points: Sequence[np.ndarray]) -> list[np.ndarray]:
    ordered = sorted((float(point[0]), float(point[1])) for point in points)
    if len(ordered) <= 1:
        return [np.asarray(point, dtype=float) for point in ordered]

    def cross(origin, left, right) -> float:
        return (left[0] - origin[0]) * (right[1] - origin[1]) - (
            left[1] - origin[1]
        ) * (right[0] - origin[0])

    lower: list[tuple[float, float]] = []
    for point in ordered:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0.0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(ordered):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0.0:
            upper.pop()
        upper.append(point)
    return [np.asarray(point, dtype=float) for point in lower[:-1] + upper[:-1]]


def _reflex_vertex_count(points: Sequence[np.ndarray]) -> int:
    result = 0
    for index, point in enumerate(points):
        before = points[index - 1]
        after = points[(index + 1) % len(points)]
        incoming = point - before
        outgoing = after - point
        cross = float(incoming[0] * outgoing[1] - incoming[1] * outgoing[0])
        if cross < -1e-10:
            result += 1
    return result


def _star_vertices(
    vertex_count: int, difficulty: str, rng: np.random.Generator
) -> list[np.ndarray]:
    preset = _DIFFICULTIES[difficulty]
    angular_step = 2.0 * math.pi / vertex_count
    phase = float(rng.uniform(-math.pi, math.pi))
    points = []
    for index in range(vertex_count):
        angle = phase + index * angular_step
        angle += float(rng.uniform(-1.0, 1.0)) * preset["jitter"] * angular_step
        base_radius = 0.82 if index % 2 == 0 else preset["inner_radius"]
        radius = base_radius * float(rng.uniform(0.94, 1.06))
        points.append(
            np.asarray((radius * math.cos(angle), radius * math.sin(angle)), dtype=float)
        )
    if _polygon_area(points) < 0.0:
        points.reverse()
    return points


def _component_partition(
    edge_count: int, generic_edge_capacity: int, rng: np.random.Generator
) -> list[tuple[str, int]]:
    if edge_count < 5 or generic_edge_capacity < 2:
        raise ValueError("Recovery cases require at least five edges and two generic edges")
    first_generic = min(generic_edge_capacity, max(2, edge_count - 2))
    result: list[tuple[str, int]] = [
        ("generic_curve", first_generic),
        ("circular_arc", 1),
        ("straight_segment", 1),
    ]
    remaining = edge_count - first_generic - 2
    while remaining:
        if remaining >= 2 and rng.random() < 0.45:
            size = int(rng.integers(2, min(generic_edge_capacity, remaining) + 1))
            result.append(("generic_curve", size))
            remaining -= size
        else:
            kind = "circular_arc" if rng.random() < 0.35 else "straight_segment"
            result.append((kind, 1))
            remaining -= 1
    return result


def _subdivide_polyline(
    points: Sequence[np.ndarray], target_edge_count: int
) -> list[np.ndarray]:
    source_edges = len(points) - 1
    if source_edges <= 0 or source_edges > target_edge_count:
        raise ValueError("Generic witness cannot be represented by this point budget")
    allocations = [1] * source_edges
    for extra in range(target_edge_count - source_edges):
        allocations[extra % source_edges] += 1
    result = [np.asarray(points[0], dtype=float)]
    for start, end, count in zip(points, points[1:], allocations):
        for step in range(1, count + 1):
            result.append(start + (end - start) * (step / count))
    return result


def _generic_witness(
    component_id: str,
    edge_start: int,
    edge_count: int,
    vertices: Sequence[np.ndarray],
    generic_edge_capacity: int,
) -> _ComponentWitness:
    polyline = [vertices[(edge_start + offset) % len(vertices)] for offset in range(edge_count + 1)]
    control = _subdivide_polyline(polyline, generic_edge_capacity)
    displacements = [right - left for left, right in zip(control, control[1:])]
    lengths = np.asarray([np.linalg.norm(value) for value in displacements], dtype=float)
    total_length = float(np.sum(lengths))
    fractions = lengths / total_length
    headings = [_heading(value) for value in displacements]
    logits = [math.log(float(value / fractions[-1])) for value in fractions[:-1]]
    turns = [angle_wrap(right - left) for left, right in zip(headings, headings[1:])]
    if any(abs(value) >= 0.95 * math.pi for value in turns):
        raise ValueError("Generated generic corner exceeds the solver turn bound")
    return _ComponentWitness(
        component_id=component_id,
        curve_type="generic_curve",
        edge_start=edge_start,
        edge_count=edge_count,
        length=total_length,
        start_tangent=headings[0],
        end_tangent=headings[-1],
        total_turn_radians=sum(turns),
        generic_parameters=tuple(logits + turns),
    )


def _straight_witness(
    component_id: str,
    edge_start: int,
    vertices: Sequence[np.ndarray],
) -> _ComponentWitness:
    chord = vertices[(edge_start + 1) % len(vertices)] - vertices[edge_start]
    heading = _heading(chord)
    return _ComponentWitness(
        component_id=component_id,
        curve_type="straight_segment",
        edge_start=edge_start,
        edge_count=1,
        length=float(np.linalg.norm(chord)),
        start_tangent=heading,
        end_tangent=heading,
        total_turn_radians=0.0,
    )


def _arc_witness(
    component_id: str,
    edge_start: int,
    vertices: Sequence[np.ndarray],
    sweep: float,
) -> _ComponentWitness:
    chord = vertices[(edge_start + 1) % len(vertices)] - vertices[edge_start]
    chord_length = float(np.linalg.norm(chord))
    denominator = 2.0 * abs(math.sin(sweep / 2.0))
    length = chord_length * abs(sweep) / denominator
    chord_heading = _heading(chord)
    return _ComponentWitness(
        component_id=component_id,
        curve_type="circular_arc",
        edge_start=edge_start,
        edge_count=1,
        length=length,
        start_tangent=chord_heading - sweep / 2.0,
        end_tangent=chord_heading + sweep / 2.0,
        total_turn_radians=sweep,
        sweep_radians=sweep,
    )


def _build_problem(
    *,
    case_id: str,
    case_seed: int,
    difficulty: str,
    vertex_count: int,
    intermediate_points: int,
    arc_scale: float,
) -> tuple[FormalGeometryProblem, list[_ComponentWitness], list[np.ndarray]]:
    rng = np.random.default_rng(case_seed)
    vertices = _star_vertices(vertex_count, difficulty, rng)
    generic_edge_capacity = intermediate_points + 1
    partition = _component_partition(vertex_count, generic_edge_capacity, rng)
    component_witnesses: list[_ComponentWitness] = []
    edge_start = 0
    arc_index = 0
    for component_index, (curve_type, edge_count) in enumerate(partition):
        component_id = f"C{component_index}"
        if curve_type == "generic_curve":
            witness = _generic_witness(
                component_id,
                edge_start,
                edge_count,
                vertices,
                generic_edge_capacity,
            )
        elif curve_type == "circular_arc":
            preset = _DIFFICULTIES[difficulty]
            sign = -1.0 if (arc_index + case_seed) % 2 else 1.0
            random_factor = float(rng.uniform(0.8, 1.2))
            sweep = sign * math.pi * preset["arc_sweep_pi"] * random_factor * arc_scale
            witness = _arc_witness(component_id, edge_start, vertices, sweep)
            arc_index += 1
        else:
            witness = _straight_witness(component_id, edge_start, vertices)
        component_witnesses.append(witness)
        edge_start += edge_count

    points = []
    segments = []
    components = []
    for index, witness in enumerate(component_witnesses):
        previous = component_witnesses[index - 1]
        vertex_turn = angle_wrap(witness.start_tangent - previous.end_tangent)
        interior_angle_pi = (math.pi - vertex_turn) / math.pi
        if not 1e-8 < interior_angle_pi < 2.0 - 1e-8:
            raise ValueError("Generated formal point angle is degenerate")
        points.append(
            FormalPointSpec(
                boundary_index=index,
                angle_pi=_unit_formula(interior_angle_pi),
                angle_class=f"A{index}",
                angle_class_sign=1,
                occurrences=(),
                roles=("synthetic_recovery_benchmark",),
                witness_angle_pi=None,
            )
        )
        segments.append(
            FormalSegmentOccurrence(
                segment_index=index,
                literal=f"B{index}",
                variable=f"B{index}",
                literal_inverse=False,
                component_id=witness.component_id,
                curve_type=witness.curve_type,
                circle_class=(
                    f"synthetic-circle-{index}"
                    if witness.curve_type == "circular_arc"
                    else None
                ),
            )
        )
        components.append(
            FormalCurveComponent(
                component_id=witness.component_id,
                representative=f"B{index}",
                variables=(f"B{index}",),
                variable_transforms=((f"B{index}", TransformSpec()),),
                curve_type=witness.curve_type,
                circle_class=(
                    f"synthetic-circle-{index}"
                    if witness.curve_type == "circular_arc"
                    else None
                ),
                forced_straight=witness.curve_type == "straight_segment",
                length=_length_parameter(f"L_{witness.component_id}"),
                turn_pi=(
                    _unit_formula(
                        witness.total_turn_radians / math.pi
                    )
                    if witness.curve_type != "straight_segment"
                    else None
                ),
                # Deliberately do not leak the oracle length into solver initialization.
                search_witness_length=None,
            )
        )
    problem = FormalGeometryProblem(
        formal_profile_id=case_id,
        source_candidate={
            "kind": "synthetic_known_positive_geometry",
            "generator_seed": case_seed,
            "difficulty": difficulty,
        },
        source_path="synthetic:geometry-recovery-benchmark",
        source_line=1,
        map_name="synthetic-recovery",
        points=tuple(points),
        segments=tuple(segments),
        components=tuple(components),
    )
    return problem, component_witnesses, vertices


def generate_recovery_case(
    *,
    case_index: int,
    case_seed: int,
    difficulty: str,
    vertex_count: int,
    solver_config: GeometrySolverConfig,
) -> GeneratedRecoveryCase:
    """Generate and independently certify one satisfiable solver problem."""
    if difficulty not in _DIFFICULTIES:
        raise ValueError(f"Unknown difficulty {difficulty!r}")
    if vertex_count < 6 or vertex_count % 2:
        raise ValueError("vertex_count must be even and at least six")
    if solver_config.intermediate_points_per_generic_curve < 1:
        raise ValueError("The recovery benchmark needs at least one generic point")

    case_id = f"geometry-recovery-{case_index:04d}"
    last_failure = "not generated"
    for generation_attempt in range(16):
        effective_seed = case_seed + generation_attempt * 104729
        for arc_scale in (1.0, 0.7, 0.45, 0.25):
            try:
                problem, witnesses, vertices = _build_problem(
                    case_id=case_id,
                    case_seed=effective_seed,
                    difficulty=difficulty,
                    vertex_count=vertex_count,
                    intermediate_points=solver_config.intermediate_points_per_generic_curve,
                    arc_scale=arc_scale,
                )
            except ValueError as error:
                last_failure = str(error)
                continue
            certifier = NumericalContourSolver(solver_config)
            layout = certifier._build_layout(problem)
            oracle = layout.initial.copy()
            length_by_name = {
                f"L_{witness.component_id}": witness.length for witness in witnesses
            }
            for index, name in enumerate(layout.formal_names):
                oracle[index] = length_by_name[name]
            for witness in witnesses:
                shape_slice = layout.slices.get(witness.component_id)
                if shape_slice is not None:
                    oracle[shape_slice] = np.asarray(
                        witness.generic_parameters, dtype=float
                    )
            if np.any(oracle < layout.lower_bounds) or np.any(
                oracle > layout.upper_bounds
            ):
                last_failure = "oracle_outside_solver_bounds"
                continue
            built = certifier._build_geometry(problem, layout, oracle)
            validation = certifier._validate_built(built)
            oracle_residual = certifier._closure_residual(problem, layout, oracle)
            oracle_residual_norm = float(np.linalg.norm(oracle_residual))
            if oracle_residual_norm > 1e-7:
                last_failure = f"oracle_formal_residual={oracle_residual_norm:.3e}"
                continue
            if not validation.passed:
                failed = [name for name, passed, _ in validation.checks if not passed]
                last_failure = ",".join(failed)
                continue

            hull = _convex_hull(vertices)
            polygon_area = abs(_polygon_area(vertices))
            hull_area = abs(_polygon_area(hull))
            curve_counts = {
                kind: sum(w.curve_type == kind for w in witnesses)
                for kind in ("straight_segment", "circular_arc", "generic_curve")
            }
            metadata = {
                "case_id": case_id,
                "requested_seed": case_seed,
                "effective_seed": effective_seed,
                "generation_attempt": generation_attempt,
                "difficulty": difficulty,
                "vertex_count": vertex_count,
                "formal_point_count": len(problem.points),
                "component_count": len(problem.components),
                "curve_counts": curve_counts,
                "degrees_of_freedom": int(layout.initial.size),
                "oracle_distance_from_solver_initial": float(
                    np.linalg.norm(oracle - layout.initial)
                ),
                "reflex_vertex_count": _reflex_vertex_count(vertices),
                "formal_reflex_point_count": sum(
                    point.angle_pi.constant > 1.0 for point in problem.points
                ),
                "polygon_to_hull_area_ratio": polygon_area / hull_area,
                "arc_scale": arc_scale,
                "oracle_validation": validation.to_dict(),
                "oracle_formal_residual_norm": oracle_residual_norm,
            }
            witness_record = {
                **metadata,
                "base_polygon": [
                    [float(point[0]), float(point[1])] for point in vertices
                ],
                "components": [
                    {
                        "component_id": witness.component_id,
                        "curve_type": witness.curve_type,
                        "edge_start": witness.edge_start,
                        "edge_count": witness.edge_count,
                        "length": witness.length,
                        "start_tangent": witness.start_tangent,
                        "end_tangent": witness.end_tangent,
                        "total_turn_radians": witness.total_turn_radians,
                        "sweep_radians": witness.sweep_radians,
                    }
                    for witness in witnesses
                ],
            }
            return GeneratedRecoveryCase(problem, oracle, metadata, witness_record)
    raise RuntimeError(
        f"Could not generate a certified witness for {case_id}: {last_failure}"
    )


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return float(ordered[index])


def _aggregate(records: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    successes = [record for record in records if record["recovered"]]
    durations = [float(record["elapsed_seconds"]) for record in records]
    evaluations = [
        int(record["function_evaluations"])
        for record in successes
        if record.get("function_evaluations") is not None
    ]
    per_case: dict[str, list[bool]] = {}
    for record in records:
        per_case.setdefault(str(record["case_id"]), []).append(bool(record["recovered"]))
    return {
        "trial_count": len(records),
        "successful_trials": len(successes),
        "trial_recovery_rate": len(successes) / len(records) if records else 0.0,
        "case_count": len(per_case),
        "cases_recovered_at_least_once": sum(any(values) for values in per_case.values()),
        "cases_recovered_every_time": sum(all(values) for values in per_case.values()),
        "median_elapsed_seconds": statistics.median(durations) if durations else None,
        "p95_elapsed_seconds": _percentile(durations, 0.95),
        "median_success_evaluations": (
            statistics.median(evaluations) if evaluations else None
        ),
    }


def _markdown_report(
    settings: BenchmarkSettings,
    solver_config: GeometrySolverConfig,
    aggregate: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
) -> str:
    lines = [
        "# Geometry recovery benchmark",
        "",
        "Every generated instance has first been certified with a hidden exact witness. "
        "The production `NumericalContourSolver.solve()` then received the formal problem "
        "without oracle lengths or generic control points.",
        "",
        "## Result",
        "",
        f"- Trial recovery: **{aggregate['successful_trials']}/{aggregate['trial_count']} "
        f"({100.0 * float(aggregate['trial_recovery_rate']):.1f}%)**",
        f"- Cases recovered at least once: **{aggregate['cases_recovered_at_least_once']}/"
        f"{aggregate['case_count']}**",
        f"- Cases recovered on every seed: **{aggregate['cases_recovered_every_time']}/"
        f"{aggregate['case_count']}**",
        f"- Median trial time: **{float(aggregate['median_elapsed_seconds'] or 0.0):.3f}s**",
        f"- 95th-percentile trial time: **{float(aggregate['p95_elapsed_seconds'] or 0.0):.3f}s**",
        "",
        "A miss is a false negative under this finite parameterization and budget: the "
        "hidden witness proves that the formal instance is realizable. It is not evidence "
        "that the instance is impossible.",
        "The `attempts` column also matters: if attempt 1 consumes the whole candidate "
        "timeout, the solver never reaches a seed-dependent randomized restart, so repeated "
        "seeds are expected to agree.",
        "",
        "## Recovery by difficulty",
        "",
        "The machine-readable `report.json` also contains the complete breakdown by "
        "difficulty and every failed validation check.",
        "",
        "## Trials",
        "",
        "| case | difficulty | vertices | curves (S/A/G) | concavity ratio | seed | result | attempts | time | reason |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for record in records:
        counts = record["curve_counts"]
        curve_mix = (
            f"{counts['straight_segment']}/{counts['circular_arc']}/"
            f"{counts['generic_curve']}"
        )
        lines.append(
            f"| {record['case_id']} | {record['difficulty']} | {record['vertex_count']} | "
            f"{curve_mix} | {float(record['polygon_to_hull_area_ratio']):.3f} | "
            f"{record['solver_seed']} | {'yes' if record['recovered'] else 'NO'} | "
            f"{record['attempts']} | {float(record['elapsed_seconds']):.3f}s | "
            f"{record['reason']} |"
        )
    lines.extend(
        [
            "",
            "## Configuration",
            "",
            "```json",
            json.dumps(
                {"benchmark": asdict(settings), "solver": asdict(solver_config)},
                indent=2,
                sort_keys=True,
            ),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def run_benchmark(
    settings: BenchmarkSettings,
    solver_config: GeometrySolverConfig,
) -> Mapping[str, Any]:
    output = Path(settings.output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    records: list[Mapping[str, Any]] = []
    witnesses: list[Mapping[str, Any]] = []
    solution_records: list[Mapping[str, Any]] = []
    for case_index in range(settings.case_count):
        difficulty = settings.difficulties[case_index % len(settings.difficulties)]
        vertex_count = settings.vertex_counts[case_index % len(settings.vertex_counts)]
        case_seed = settings.generator_seed + case_index * 1009
        generated = generate_recovery_case(
            case_index=case_index,
            case_seed=case_seed,
            difficulty=difficulty,
            vertex_count=vertex_count,
            solver_config=solver_config,
        )
        witnesses.append(generated.witness_record)
        for repeat in range(settings.solver_repeats):
            solver_seed = settings.generator_seed + case_index * 1009 + repeat * 65537
            trial_config = replace(solver_config, random_seed=solver_seed)
            started = time.perf_counter()
            result = NumericalContourSolver(trial_config).solve(generated.problem)
            elapsed = time.perf_counter() - started
            optimization = (
                {} if result.solution is None else dict(result.solution.optimization)
            )
            record = {
                **generated.metadata,
                "repeat": repeat,
                "solver_seed": solver_seed,
                "recovered": result.solution is not None,
                "reason": result.reason,
                "attempts": result.attempts,
                "elapsed_seconds": elapsed,
                "best_cost": result.best_cost,
                "best_validation": result.best_validation,
                "function_evaluations": optimization.get("function_evaluations"),
            }
            records.append(record)
            print(
                f"[{len(records):03d}] {generated.problem.formal_profile_id} "
                f"{difficulty} n={vertex_count} seed={solver_seed} "
                f"{'RECOVERED' if result.solution is not None else 'MISSED'} "
                f"attempts={result.attempts} wall={elapsed:.3f}s reason={result.reason}",
                flush=True,
            )
            if settings.write_solutions and result.solution is not None:
                solution_records.append(
                    {
                        "benchmark_case": generated.metadata,
                        "repeat": repeat,
                        "solver_seed": solver_seed,
                        "geometric_solution": result.solution.to_dict(),
                    }
                )

    aggregate = _aggregate(records)
    by_difficulty = {
        difficulty: _aggregate(
            [record for record in records if record["difficulty"] == difficulty]
        )
        for difficulty in settings.difficulties
    }
    report = {
        "schema_version": "geometry-recovery-benchmark-v1",
        "benchmark": asdict(settings),
        "solver": asdict(solver_config),
        "aggregate": aggregate,
        "by_difficulty": by_difficulty,
        "trials": records,
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    (output / "trials.jsonl").write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    (output / "witnesses.jsonl").write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in witnesses),
        encoding="utf-8",
    )
    if settings.write_solutions:
        (output / "recovered_solutions.jsonl").write_text(
            "".join(
                json.dumps(record, sort_keys=True) + "\n"
                for record in solution_records
            ),
            encoding="utf-8",
        )
    (output / "report.md").write_text(
        _markdown_report(settings, solver_config, aggregate, records),
        encoding="utf-8",
    )
    print(json.dumps(aggregate, indent=2, sort_keys=True), flush=True)
    print(f"report: {output / 'report.md'}", flush=True)
    return report


def _load_configuration(path: Path) -> tuple[BenchmarkSettings, GeometrySolverConfig]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_benchmark = dict(payload.get("benchmark", {}))
    settings = BenchmarkSettings(
        case_count=max(1, int(raw_benchmark.get("case_count", 6))),
        solver_repeats=max(1, int(raw_benchmark.get("solver_repeats", 3))),
        generator_seed=int(raw_benchmark.get("generator_seed", 20260814)),
        vertex_counts=tuple(
            int(value) for value in raw_benchmark.get("vertex_counts", [8, 10, 12])
        ),
        difficulties=tuple(
            str(value)
            for value in raw_benchmark.get(
                "difficulties", ["moderate", "strong", "extreme"]
            )
        ),
        output_directory=str(
            raw_benchmark.get(
                "output_directory", "output/geometry_recovery_benchmark"
            )
        ),
        write_solutions=bool(raw_benchmark.get("write_solutions", True)),
    )
    if not settings.vertex_counts or not settings.difficulties:
        raise ValueError("vertex_counts and difficulties cannot be empty")
    unknown = sorted(set(settings.difficulties) - set(_DIFFICULTIES))
    if unknown:
        raise ValueError(f"Unknown benchmark difficulties: {unknown}")
    return settings, GeometrySolverConfig.from_mapping(payload.get("solver", {}))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Recover hidden known-valid non-convex contour witnesses."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/benchmarks/geometry-recovery.json"),
    )
    parser.add_argument("--cases", type=int)
    parser.add_argument("--repeats", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--output", type=str)
    parser.add_argument("--quick", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings, solver_config = _load_configuration(args.config)
    if args.cases is not None:
        settings = replace(settings, case_count=max(1, args.cases))
    if args.repeats is not None:
        settings = replace(settings, solver_repeats=max(1, args.repeats))
    if args.seed is not None:
        settings = replace(settings, generator_seed=args.seed)
    if args.output is not None:
        settings = replace(settings, output_directory=args.output)
    if args.quick:
        settings = replace(settings, case_count=min(3, settings.case_count), solver_repeats=1)
        solver_config = replace(
            solver_config,
            max_restarts=min(8, solver_config.max_restarts),
            max_function_evaluations=min(500, solver_config.max_function_evaluations),
            candidate_timeout_seconds=min(4.0, solver_config.candidate_timeout_seconds),
        )
    run_benchmark(settings, solver_config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
