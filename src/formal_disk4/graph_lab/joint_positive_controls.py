from __future__ import annotations

"""Targeted end-to-end controls for the joint arrangement search.

These examples are deliberately not catalogue seeds for Graph Lab.  They are a
standalone validation harness: each run fixes a contact graph whose elementary
polygonal realization is known, removes the circular outer-boundary condition,
and asks the joint arrangement/formal/geometry pipeline to rediscover *some*
congruent-tile realization.
"""

import argparse
import json
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from formal_disk4.config import load_config, load_geometry_config
from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.enumeration.cyclic_arrangements import CyclicArrangementEnumerator
from formal_disk4.geometry.runner import GeometryRunner
from formal_disk4.maps.base import (
    InterfaceSpec,
    InterfaceView,
    MapAutomorphism,
    PieceSpec,
    PlanarMap,
    ProblemHypotheses,
    VertexSpec,
)
from formal_disk4.pipeline import FormalSolverAPI, PlacementSelection, SolverAPIRequest
from formal_disk4.pipeline.output import JsonlWriter, atomic_write_json
from formal_disk4.visualization.assembly import AssemblyError
from formal_disk4.visualization.svg import geometric_solution_svg

from .free_outer_boundary import relax_outer_boundary
from .space import OUTSIDE, DualGraphCandidate, DynamicPlanarMap, build_dynamic_planar_map


@dataclass(frozen=True)
class PositiveControl:
    name: str
    dynamic: DynamicPlanarMap
    description: str


def _candidate(
    name: str,
    tile_count: int,
    internal_edges: Iterable[tuple[int, int]],
    outer_tiles: Iterable[int],
    permutation: Sequence[int],
    *,
    center: int | None = None,
) -> PositiveControl:
    edges = [tuple(sorted(edge)) for edge in internal_edges]
    edges.extend((OUTSIDE, int(tile)) for tile in outer_tiles)
    graph = DualGraphCandidate(
        tile_count=tile_count,
        edges=tuple(sorted(set(edges))),
        imposed_permutation=tuple(int(item) for item in permutation),
        origin="joint_positive_control",
        mutation=name,
        stein_center_tile=center,
    )
    return PositiveControl(
        name=name,
        dynamic=relax_outer_boundary(build_dynamic_planar_map(graph)),
        description=name.replace("-", " "),
    )


def _square_2x2() -> PositiveControl:
    return _candidate(
        "square-2x2",
        4,
        ((0, 1), (0, 2), (1, 3), (2, 3)),
        range(4),
        (1, 3, 0, 2),
    )


def _square_3x3() -> PositiveControl:
    edges = []
    edges.extend(
        (row * 3 + column, row * 3 + column + 1)
        for row in range(3)
        for column in range(2)
    )
    edges.extend(
        (row * 3 + column, (row + 1) * 3 + column)
        for row in range(2)
        for column in range(3)
    )
    return _candidate(
        "square-3x3",
        9,
        edges,
        (0, 1, 2, 3, 5, 6, 7, 8),
        (2, 5, 8, 1, 4, 7, 0, 3, 6),
        center=4,
    )


def _hexagonal_flower() -> PositiveControl:
    outer = tuple(range(1, 7))
    edges = [(0, tile) for tile in outer]
    edges.extend((outer[index], outer[(index + 1) % 6]) for index in range(6))
    return _candidate(
        "hexagonal-flower-7",
        7,
        edges,
        outer,
        (0, 2, 3, 4, 5, 6, 1),
        center=0,
    )


def _triangle_cluster_map() -> DynamicPlanarMap:
    pieces = (
        PieceSpec("T0", ("U", "W", "V"), False, "none"),
        PieceSpec("T1", ("A", "U", "V"), False, "none"),
        PieceSpec("T2", ("B", "W", "U"), False, "none"),
        PieceSpec("T3", ("C", "V", "W"), False, "none"),
    )
    vertices = (
        VertexSpec("A", "free", ("T1",), 2.0),
        VertexSpec("B", "free", ("T2",), 2.0),
        VertexSpec("C", "free", ("T3",), 2.0),
        VertexSpec("U", "free", ("T0", "T1", "T2"), 2.0),
        VertexSpec("V", "free", ("T0", "T1", "T3"), 2.0),
        VertexSpec("W", "free", ("T0", "T2", "T3"), 2.0),
    )
    interfaces = (
        InterfaceSpec(
            "T0-T1",
            "T0",
            "T1",
            (InterfaceView("T0", "V", "U"), InterfaceView("T1", "U", "V")),
        ),
        InterfaceSpec(
            "T0-T2",
            "T0",
            "T2",
            (InterfaceView("T0", "U", "W"), InterfaceView("T2", "W", "U")),
        ),
        InterfaceSpec(
            "T0-T3",
            "T0",
            "T3",
            (InterfaceView("T0", "W", "V"), InterfaceView("T3", "V", "W")),
        ),
        InterfaceSpec("free-T1-AU", "T1", None, (InterfaceView("T1", "A", "U"),), is_free=True),
        InterfaceSpec("free-T1-VA", "T1", None, (InterfaceView("T1", "V", "A"),), is_free=True),
        InterfaceSpec("free-T2-BW", "T2", None, (InterfaceView("T2", "B", "W"),), is_free=True),
        InterfaceSpec("free-T2-UB", "T2", None, (InterfaceView("T2", "U", "B"),), is_free=True),
        InterfaceSpec("free-T3-CV", "T3", None, (InterfaceView("T3", "C", "V"),), is_free=True),
        InterfaceSpec("free-T3-WC", "T3", None, (InterfaceView("T3", "W", "C"),), is_free=True),
    )
    rotation = MapAutomorphism(
        "rotation_1",
        (("T0", "T0"), ("T1", "T2"), ("T2", "T3"), ("T3", "T1")),
        (("A", "B"), ("B", "C"), ("C", "A"), ("U", "W"), ("W", "V"), ("V", "U")),
    )
    planar_map = PlanarMap(
        name="triangle-cluster-4-free-boundary",
        pieces=pieces,
        vertices=vertices,
        interfaces=interfaces,
        automorphisms=(rotation,),
        reference_piece="T0",
        hypotheses=ProblemHypotheses(center_strictly_inside_one_tile=False),
        outer_boundary_is_complete=False,
    )
    planar_map.validate()
    return DynamicPlanarMap(
        planar_map=planar_map,
        imposed_automorphism="rotation_1",
        imposed_equivariance_mode="cyclic_shift",
        imposed_reflections=(),
        automorphism_orders=(3,),
    )


def positive_controls() -> tuple[PositiveControl, ...]:
    return (
        PositiveControl(
            "triangle-cluster-4",
            _triangle_cluster_map(),
            "four-triangle contact pattern",
        ),
        _square_2x2(),
        _square_3x3(),
        _hexagonal_flower(),
    )


def _arrangement_transforms(dynamic: DynamicPlanarMap):
    assignments = AssignmentEnumerator(dynamic.planar_map, symmetry_mode="off")
    pointwise = cyclic = None
    reflections = ()
    if dynamic.imposed_automorphism is not None:
        transform = assignments.transform_for_automorphism(
            dynamic.imposed_automorphism
        )
        if dynamic.imposed_equivariance_mode == "pointwise":
            pointwise = transform
        elif dynamic.imposed_equivariance_mode == "cyclic_shift":
            cyclic = transform
            reflections = tuple(
                assignments.transform_for_automorphism(name)
                for name in dynamic.imposed_reflections
            )
        else:
            raise ValueError("Unknown positive-control equivariance mode")
    return pointwise, cyclic, reflections


def _formal_profiles(
    control: PositiveControl,
    *,
    root: Path,
    maximum_placements: int,
    time_limit_seconds: float,
) -> tuple[tuple[Mapping[str, object], ...], Mapping[str, object]]:
    pointwise, cyclic, reflections = _arrangement_transforms(control.dynamic)
    deadline = time.perf_counter() + time_limit_seconds
    search = CyclicArrangementEnumerator(
        control.dynamic.planar_map,
        required_pointwise_transform=pointwise,
        required_cyclic_shift_transform=cyclic,
        required_reflection_transforms=reflections,
        max_nodes=1_000_000,
        stop_predicate=lambda: time.perf_counter() >= deadline,
    )
    placements = []
    for placement in search.enumerate():
        placements.append(placement)
        if len(placements) >= maximum_placements:
            break
    if not placements:
        return (), {"arrangement": search.statistics.__dict__, "kernel": None}

    with tempfile.TemporaryDirectory(prefix=f"formal-disk4-{control.name}-") as raw:
        config = load_config(root / "config" / "cycle_campaign" / "search.json")
        config["maps"] = [control.dynamic.planar_map.name]
        config["checkpoint"].update({"enabled": False, "resume": False})
        config["progress"]["enabled"] = False
        config["output"].update(
            {
                "directory": raw,
                "write_candidates": True,
                "write_families": False,
                "write_word_cases": False,
                "write_errors": True,
            }
        )
        config["enumeration"]["symmetry_mode"] = "off"
        config["enumeration"]["track_exact_domain_size"] = False
        for name in (
            "cyclic_equivariance",
            "cyclic_shift_equivariance",
            "dihedral_equivariance",
        ):
            config["enumeration"].setdefault(name, {})["enabled"] = False
        config["limits"].update(
            {
                "max_assignments": len(
                    {item.assignment.assignment_id for item in placements}
                ),
                "max_placements": len(placements),
                "max_profiles": 16,
                "time_limit_seconds": time_limit_seconds,
                "stop_on_first_profile": False,
            }
        )
        config["solver"].update(
            {
                "max_graph_nodes_per_placement": 10_000,
                "max_graph_edges_per_placement": 40_000,
                "max_families_per_placement": 32,
                "max_seconds_per_word_case": 2,
            }
        )
        result = FormalSolverAPI.evaluate(
            SolverAPIRequest(
                config=config,
                planar_maps=(control.dynamic.planar_map,),
                placements=(
                    PlacementSelection(
                        control.dynamic.planar_map.name, tuple(placements)
                    ),
                ),
                collect_profiles=True,
            )
        )
    return tuple(result.profiles), {
        "arrangement": search.statistics.__dict__,
        "kernel": result.summary.get("statistics"),
    }


def _write_jsonl(path: Path, records: Sequence[Mapping[str, object]]) -> None:
    writer = JsonlWriter(path, flush_every=1, append=False)
    try:
        for record in records:
            writer.write(record)
    finally:
        writer.close()


def _geometry(
    control: PositiveControl,
    profiles: Sequence[Mapping[str, object]],
    *,
    root: Path,
    output: Path,
    candidate_seconds: float,
) -> tuple[Path | None, Mapping[str, object]]:
    candidates = output / "geometry_candidates.jsonl"
    _write_jsonl(candidates, profiles)
    geometry_output = output / "geometry"
    config = load_geometry_config(root / "config" / "graph_lab" / "geometry.json")
    config["input"]["candidates_file"] = str(candidates)
    config["output"]["directory"] = str(geometry_output)
    config["geometry"].update(
        {
            "candidate_timeout_seconds": candidate_seconds,
            "intermediate_points_per_generic_curve": 5,
            "max_restarts": 64,
            "max_function_evaluations": 2500,
        }
    )
    config["limits"].update(
        {
            "max_candidates": None,
            "max_solutions": None,
            "stop_on_first_solution": False,
        }
    )
    config["checkpoint"].update({"enabled": False, "resume": False, "restart": False})
    summary = GeometryRunner(config).run()
    solutions = geometry_output / "geometric_solutions.jsonl"
    if not solutions.exists():
        return None, summary
    assembly_failures = []
    with solutions.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            try:
                svg = geometric_solution_svg(
                    record, width=900, height=680, margin=28
                )
            except AssemblyError as error:
                assembly_failures.append(str(error))
                continue
            svg_path = output / f"{control.name}.svg"
            svg_path.write_text(svg, encoding="utf-8")
            enriched = dict(summary)
            enriched["assembly_failures_before_valid_solution"] = assembly_failures
            return svg_path, enriched
    enriched = dict(summary)
    enriched["assembly_failures"] = assembly_failures
    return None, enriched


def run(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    output_root = Path(args.output_directory).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    requested = {item.strip() for item in args.controls.split(",") if item.strip()}
    controls = tuple(item for item in positive_controls() if item.name in requested)
    missing = requested - {item.name for item in controls}
    if missing:
        raise ValueError("Unknown controls: " + ", ".join(sorted(missing)))

    report = []
    for control in controls:
        print(f"[CONTROL] {control.name}: joint formal search", flush=True)
        control_output = output_root / control.name
        control_output.mkdir(parents=True, exist_ok=True)
        profiles, formal = _formal_profiles(
            control,
            root=root,
            maximum_placements=args.max_placements,
            time_limit_seconds=args.formal_seconds,
        )
        print(f"[CONTROL] {control.name}: {len(profiles)} formal profiles", flush=True)
        svg_path = None
        geometry_summary: Mapping[str, object] | None = None
        if profiles:
            svg_path, geometry_summary = _geometry(
                control,
                profiles,
                root=root,
                output=control_output,
                candidate_seconds=args.geometry_seconds,
            )
        status = "geometric_solution" if svg_path is not None else (
            "formal_only" if profiles else "no_formal_profile"
        )
        print(f"[CONTROL] {control.name}: {status}", flush=True)
        report.append(
            {
                "name": control.name,
                "description": control.description,
                "status": status,
                "formal_profile_count": len(profiles),
                "svg": str(svg_path) if svg_path is not None else None,
                "formal": formal,
                "geometry": geometry_summary,
            }
        )
        atomic_write_json(
            output_root / "report.json",
            {"schema_version": "joint-positive-controls-v1", "controls": report},
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--output-directory",
        default="output/joint_positive_controls/v1",
    )
    parser.add_argument(
        "--controls",
        default="triangle-cluster-4,square-2x2,square-3x3,hexagonal-flower-7",
    )
    parser.add_argument("--max-placements", type=int, default=128)
    parser.add_argument("--formal-seconds", type=float, default=45.0)
    parser.add_argument("--geometry-seconds", type=float, default=12.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
