from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .arguments import add_search_arguments
from .runner import GraphLabRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="formal-disk4-graph-lab",
        description=(
            "Compatibility wrapper for headless Graph Lab searches. New user "
            "workflows should normally use formal-disk4-lab."
        ),
    )
    parser.add_argument(
        "--config", default="config/graph_lab/up-to-13.json"
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--generations", type=int)
    parser.add_argument("--batch-size", type=int)
    add_search_arguments(parser)
    parser.add_argument(
        "--restart",
        action="store_true",
        help="replace only the known generated files in this Graph Lab output",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runner = GraphLabRunner.from_file(
        Path(args.root).resolve(),
        args.config,
        exclude_rings=True if args.exclude_rings else None,
        tile_counts=args.tile_counts,
        stein_symmetric=True if args.stein_symmetric else None,
        symmetry_orders=args.symmetry_orders,
        outer_crown_only=True if args.outer_crown_only else None,
        free_outer_boundary=True if args.free_outer_boundary else None,
        partial_crown_tile_counts=args.partial_crown_tiles,
        prototype_symmetry_mode=args.prototype_symmetry,
        joint_arrangement_search=(
            True if args.joint_arrangement_search else None
        ),
        policy_mode=args.policy,
        output_directory=args.output_directory,
    )
    result = runner.run(
        restart=bool(args.restart),
        generations=args.generations,
        batch_size=args.batch_size,
    )
    print(
        "graph-lab complete: "
        f"generations={result.generations_completed} "
        f"observations={result.observations} "
        f"geometry-ready={result.geometry_ready_graphs} "
        f"stop={result.stop_reason} "
        f"output={result.output_directory}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
