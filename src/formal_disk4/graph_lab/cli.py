from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .runner import GraphLabRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="formal-disk4-graph-lab",
        description=(
            "Explore valid planar dual graphs and complete contour mappings "
            "with shared graph, mapping, and weak-order rankers driving "
            "bounded production-solver rollouts."
        ),
    )
    parser.add_argument(
        "--config", default="config/graph_lab/up-to-13.json"
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--generations", type=int)
    parser.add_argument("--batch-size", type=int)
    parser.add_argument(
        "--restart",
        action="store_true",
        help="replace only the known generated files in this Graph Lab output",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runner = GraphLabRunner.from_file(Path(args.root).resolve(), args.config)
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
