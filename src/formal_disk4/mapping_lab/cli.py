from __future__ import annotations

import argparse
import multiprocessing as mp
from pathlib import Path

from .runner import MappingLabRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="formal-disk4-mapping-lab",
        description=(
            "Learn a fast sampling policy over complete mappings using bounded "
            "evaluations by the production formal filters."
        ),
    )
    parser.add_argument(
        "--config",
        default="config/mapping_lab/wheel-6.json",
        help="mapping-lab JSON configuration, relative to the project root",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="project root containing config/case_families.json",
    )
    parser.add_argument(
        "--generations",
        type=int,
        help="override the total number of generations",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        help="override the number of new complete mappings per generation",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="restart this campaign by removing only its known generated files",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    runner = MappingLabRunner.from_file(root, args.config)
    result = runner.run(
        restart=args.restart,
        generations=args.generations,
        batch_size=args.batch_size,
    )
    advantage = (
        "n/a"
        if result.learned_advantage is None
        else f"{result.learned_advantage:+.3f}"
    )
    print(
        "mapping-lab complete: "
        f"generations={result.generations_completed} "
        f"evaluations_this_run={result.evaluations} "
        f"mean-stage={result.first_mean_stage:.3f}->{result.last_mean_stage:.3f} "
        f"max-stage={result.first_max_stage}->{result.last_max_stage} "
        f"post-warmup-learned-advantage={advantage} "
        f"output={result.output_directory}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
