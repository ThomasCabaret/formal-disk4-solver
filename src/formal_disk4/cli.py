from __future__ import annotations

import argparse
import json
from itertools import islice
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

from formal_disk4.config import load_config, load_geometry_config, load_visualization_config
from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.enumeration.exterior_arc_repetition import (
    build_exterior_arc_repetition_constraint,
)
from formal_disk4.enumeration.weak_orders import (
    count_distinct_orders_all_peripheral_phases,
    count_weak_orders_all_peripheral_phases,
    count_weak_orders_fixed_phases,
    count_weak_orders_for_lengths,
)
from formal_disk4.geometry.runner import GeometryRunner
from formal_disk4.visualization.runner import VisualizationRunner
from formal_disk4.maps.registry import available_maps, build_map
from formal_disk4.pipeline.runner import SolverRunner


def _apply_overrides(config: Dict[str, Any], args: argparse.Namespace) -> None:
    if getattr(args, "map", None) is not None:
        config["maps"] = [str(args.map)]
    if getattr(args, "output", None) is not None:
        config["output"]["directory"] = str(args.output)
    if getattr(args, "max_seconds", None) is not None:
        config["limits"]["time_limit_seconds"] = args.max_seconds
    if getattr(args, "max_nodes", None) is not None:
        config["limits"]["max_nodes"] = args.max_nodes
    if getattr(args, "max_placements", None) is not None:
        config["limits"]["max_placements"] = args.max_placements
    if getattr(args, "max_profiles", None) is not None:
        config["limits"]["max_profiles"] = args.max_profiles
    if getattr(args, "symmetry", None) is not None:
        config["enumeration"]["symmetry_mode"] = args.symmetry
    if getattr(args, "no_lengths", False):
        config["enumeration"]["enable_length_filter"] = False
    if getattr(args, "no_angles", False):
        config["enumeration"]["enable_angle_filter"] = False
    if getattr(args, "no_exterior_arc_repetition", False):
        config["enumeration"]["exterior_arc_repetition"]["enabled"] = False
    if getattr(args, "no_solver", False):
        config["solver"]["enabled"] = False
    if getattr(args, "no_preword_pruning", False) or getattr(
        args, "no_preword_circular", False
    ):
        config["filters"]["preword_pruning"]["enabled"] = False
    if getattr(args, "restart", False):
        config["checkpoint"]["restart"] = True
        config["checkpoint"]["resume"] = False
    if getattr(args, "no_resume", False):
        config["checkpoint"]["resume"] = False


def command_run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    _apply_overrides(config, args)
    summary = SolverRunner(config).run()
    print(json.dumps(summary["statistics"], indent=2, ensure_ascii=False))
    print(f"Output directory: {Path(config['output']['directory']).resolve()}")
    return 0



def _apply_geometry_overrides(config: Dict[str, Any], args: argparse.Namespace) -> None:
    if getattr(args, "input", None) is not None:
        config["input"]["candidates_file"] = str(args.input)
    if getattr(args, "output", None) is not None:
        config["output"]["directory"] = str(args.output)
    if getattr(args, "intermediate_points", None) is not None:
        config["geometry"]["intermediate_points_per_generic_curve"] = int(
            args.intermediate_points
        )
    if getattr(args, "max_restarts", None) is not None:
        config["geometry"]["max_restarts"] = int(args.max_restarts)
    if getattr(args, "max_candidates", None) is not None:
        config["limits"]["max_candidates"] = int(args.max_candidates)
    if getattr(args, "max_solutions", None) is not None:
        config.setdefault("limits", {})["max_solutions"] = int(args.max_solutions)
    if getattr(args, "seed", None) is not None:
        config["geometry"]["random_seed"] = int(args.seed)
    if getattr(args, "restart", False):
        config["checkpoint"]["restart"] = True
        config["checkpoint"]["resume"] = False
    if getattr(args, "no_resume", False):
        config["checkpoint"]["resume"] = False


def command_geometry(args: argparse.Namespace) -> int:
    config = load_geometry_config(args.config)
    _apply_geometry_overrides(config, args)
    summary = GeometryRunner(config).run()
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"Geometry output directory: {Path(config['output']['directory']).resolve()}")
    return 0


def _apply_visualization_overrides(config: Dict[str, Any], args: argparse.Namespace) -> None:
    if getattr(args, "input", None) is not None:
        config["input"]["solutions_file"] = str(args.input)
    if getattr(args, "max_solutions", None) is not None:
        config.setdefault("limits", {})["max_solutions"] = int(args.max_solutions)
    if getattr(args, "start_index", None) is not None:
        config["viewer"]["start_index"] = max(0, int(args.start_index) - 1)


def command_visualize(args: argparse.Namespace) -> int:
    config = load_visualization_config(args.config)
    _apply_visualization_overrides(config, args)
    summary = VisualizationRunner(config).run(validate_only=bool(args.validate_only))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def command_counts(args: argparse.Namespace) -> int:
    planar_map = build_map(args.map)
    enumerator = AssignmentEnumerator(
        planar_map,
        allow_reflections=not args.direct_only,
        symmetry_mode=args.symmetry,
    )
    raw_count = enumerator.raw_assignment_count()
    if args.symmetry == "off":
        assignment_count = raw_count
        first_assignment = enumerator.assignment_at(0) if assignment_count else None
        assignments = None
    else:
        if raw_count > 1_000_000:
            raise ValueError(
                "Exact canonical counting would enumerate more than one million raw "
                "assignments. Use --symmetry off for the raw domain size."
            )
        materialized = tuple(enumerator.enumerate())
        assignments = materialized
        assignment_count = len(materialized)
        first_assignment = materialized[0] if materialized else None

    if first_assignment is not None and len(planar_map.pieces) <= 8:
        lengths = tuple(len(sequence) for sequence in first_assignment.sequences)
        reference_index = first_assignment.piece_names.index(planar_map.reference_piece)
        weak_per_assignment = count_weak_orders_for_lengths(lengths, reference_index)
    elif first_assignment is not None:
        lengths = tuple(len(sequence) for sequence in first_assignment.sequences)
        weak_per_assignment = None
    else:
        lengths = ()
        weak_per_assignment = 0

    repetition_summary: Dict[str, object]
    if assignments is None or assignment_count > 100_000:
        sample_constraint = (
            build_exterior_arc_repetition_constraint(
                planar_map,
                first_assignment.piece_names,
                first_assignment.sequences,
                enumerator.occurrence_index,
                enabled=True,
            )
            if first_assignment is not None
            else None
        )
        repetition_summary = {
            "fully_enumerated": False,
            "sample_assignment_applicable": bool(
                sample_constraint is not None and sample_constraint.applicable
            ),
        }
    else:
        repetition_constraints = tuple(
            build_exterior_arc_repetition_constraint(
                planar_map,
                assignment.piece_names,
                assignment.sequences,
                enumerator.occurrence_index,
                enabled=True,
            )
            for assignment in assignments
        )
        repetition_applicable = sum(
            1 for constraint in repetition_constraints if constraint.applicable
        )
        repetition_impossible = sum(
            1
            for constraint in repetition_constraints
            if constraint.applicable and not constraint.candidate_pairs
        )
        histogram: Dict[str, int] = {}
        for constraint in repetition_constraints:
            if not constraint.applicable:
                continue
            key = str(len(constraint.candidate_pairs))
            histogram[key] = histogram.get(key, 0) + 1
        repetition_summary = {
            "fully_enumerated": True,
            "applicable_assignments": repetition_applicable,
            "assignments_rejected_before_weak_orders": repetition_impossible,
            "assignments_after_assignment_level_check": assignment_count
            - repetition_impossible,
            "candidate_pair_count_histogram": histogram,
        }

    result = {
        "map": planar_map.name,
        "contour_occurrence_lengths": list(lengths),
        "raw_copy_assignments": raw_count,
        "canonical_copy_assignments": (
            assignment_count if args.symmetry != "off" else None
        ),
        "enumerated_assignment_domain": assignment_count,
        "symmetry_mode": args.symmetry,
        "exterior_arc_repetition": repetition_summary,
        "raw_weak_orders_per_assignment": weak_per_assignment,
        "estimated_raw_weak_orders_over_assignment_domain": (
            assignment_count * weak_per_assignment
            if isinstance(weak_per_assignment, int)
            else None
        ),
    }
    if planar_map.name == "k4":
        result.update(
            {
                "legacy_distinct_cyclic_orders_all_peripheral_offsets": count_distinct_orders_all_peripheral_phases(),
                "legacy_weak_orders_fixed_offsets": count_weak_orders_fixed_phases(),
                "legacy_weak_orders_all_peripheral_offsets": count_weak_orders_all_peripheral_phases(),
            }
        )
    print(json.dumps(result, indent=2))
    return 0


def command_map_info(args: argparse.Namespace) -> int:
    planar_map = build_map(args.map)
    print(json.dumps(planar_map.to_dict(), indent=2, ensure_ascii=False))
    return 0


def command_assignments(args: argparse.Namespace) -> int:
    planar_map = build_map(args.map)
    enumerator = AssignmentEnumerator(
        planar_map,
        allow_reflections=not args.direct_only,
        symmetry_mode=args.symmetry,
    )
    if args.symmetry == "off":
        sample = [
            enumerator.assignment_at(index)
            for index in range(min(args.limit, enumerator.raw_assignment_count()))
        ]
        emitted_count = enumerator.raw_assignment_count()
    else:
        sample = list(islice(enumerator.enumerate(), args.limit))
        emitted_count = None
    payload = {
        "raw_count": enumerator.raw_assignment_count(),
        "emitted_count": emitted_count,
        "sampled_count": len(sample),
        "assignments": [
            assignment.to_dict(enumerator.occurrence_names)
            for assignment in sample
        ],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def command_self_test(_args: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(root / "tests"), "-v"],
        check=False,
    )
    return completed.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="formal-disk4",
        description="Formal contour solver prototype for congruent pieces tiling a disk.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the streaming pipeline")
    run_parser.add_argument("--config", type=Path)
    run_parser.add_argument(
        "--map",
        metavar="MAP",
        help=(
            "Override config.maps. Registered cases: "
            + ", ".join(available_maps())
            + "; dynamic family: double-cycle-N."
        ),
    )
    run_parser.add_argument("--output", type=Path)
    run_parser.add_argument("--max-seconds", type=float)
    run_parser.add_argument("--max-nodes", type=int)
    run_parser.add_argument("--max-placements", type=int)
    run_parser.add_argument("--max-profiles", type=int)
    run_parser.add_argument("--symmetry", choices=("off", "assignment", "incremental"))
    run_parser.add_argument("--no-lengths", action="store_true")
    run_parser.add_argument("--no-angles", action="store_true")
    run_parser.add_argument(
        "--no-exterior-arc-repetition",
        action="store_true",
        help="Disable the early K4 Stein transported-exterior-arc repetition theorem.",
    )
    run_parser.add_argument("--no-solver", action="store_true")
    run_parser.add_argument(
        "--no-preword-pruning",
        action="store_true",
        help="Disable all pre-Nielsen--Levi pruning for differential debugging.",
    )
    run_parser.add_argument(
        "--no-preword-circular",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    run_parser.add_argument(
        "--restart",
        action="store_true",
        help="Discard the checkpoint and survivor database for this output directory.",
    )
    run_parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore an existing checkpoint without deleting it.",
    )
    run_parser.set_defaults(function=command_run)


    geometry_parser = subparsers.add_parser(
        "geometry",
        help="Numerically realize decorated formal candidate contours",
    )
    geometry_parser.add_argument("--config", type=Path)
    geometry_parser.add_argument("--input", type=Path)
    geometry_parser.add_argument("--output", type=Path)
    geometry_parser.add_argument("--intermediate-points", type=int)
    geometry_parser.add_argument("--max-restarts", type=int)
    geometry_parser.add_argument("--max-candidates", type=int)
    geometry_parser.add_argument("--max-solutions", type=int)
    geometry_parser.add_argument("--seed", type=int)
    geometry_parser.add_argument(
        "--restart",
        action="store_true",
        help="Discard geometry solutions and the geometry line checkpoint.",
    )
    geometry_parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore the existing geometry checkpoint without deleting it.",
    )
    geometry_parser.set_defaults(function=command_geometry)

    visualization_parser = subparsers.add_parser(
        "visualize",
        help="Reconstruct mapped copies and display complete assemblies",
    )
    visualization_parser.add_argument("--config", type=Path)
    visualization_parser.add_argument("--input", type=Path)
    visualization_parser.add_argument("--max-solutions", type=int)
    visualization_parser.add_argument(
        "--start-index",
        type=int,
        help="One-based geometric solution index initially displayed.",
    )
    visualization_parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Reconstruct and validate assemblies without opening a window.",
    )
    visualization_parser.set_defaults(function=command_visualize)

    counts_parser = subparsers.add_parser("counts", help="Print exact combinatorial counts")
    counts_parser.add_argument("--map", default="k4", metavar="MAP")
    counts_parser.add_argument("--direct-only", action="store_true")
    counts_parser.add_argument(
        "--symmetry", choices=("off", "assignment", "incremental"), default="incremental"
    )
    counts_parser.set_defaults(function=command_counts)

    map_parser = subparsers.add_parser("map-info", help="Inspect a registered planar map")
    map_parser.add_argument("--map", default="k4", metavar="MAP")
    map_parser.set_defaults(function=command_map_info)

    assignment_parser = subparsers.add_parser(
        "assignments", help="Inspect phase/orientation assignment representatives"
    )
    assignment_parser.add_argument("--map", default="k4", metavar="MAP")
    assignment_parser.add_argument("--direct-only", action="store_true")
    assignment_parser.add_argument(
        "--symmetry", choices=("off", "assignment", "incremental"), default="incremental"
    )
    assignment_parser.add_argument("--limit", type=int, default=10)
    assignment_parser.set_defaults(function=command_assignments)

    test_parser = subparsers.add_parser("self-test", help="Run the bundled unit tests")
    test_parser.set_defaults(function=command_self_test)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.function(args)
