from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

from formal_disk4.config import load_config
from formal_disk4.maps.registry import build_map
from formal_disk4.orchestration.catalog import CaseCatalog
from formal_disk4.pipeline.runner import SolverRunner

from .benchmark import (
    PlacementDataset,
    load_exact_placement_dataset,
    run_learning_benchmark,
    write_benchmark_report,
)


def _deep_merge(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = deepcopy(value)


def load_positive_control_config(root: Path, path: Path | str) -> dict[str, Any]:
    source = Path(path)
    if not source.is_absolute():
        source = root / source
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("The positive-control configuration must be a JSON object")
    return value


def build_collection_config(
    root: Path,
    lab_config: Mapping[str, Any],
    *,
    restart: bool,
    max_placements: int | None,
) -> tuple[dict[str, Any], Path]:
    case_id = str(lab_config["case_id"])
    case = CaseCatalog.load(root).get(case_id)
    search_config = load_config(case.config_for("search"))
    _deep_merge(search_config, case.overrides_for("search"))
    _deep_merge(search_config, dict(lab_config.get("search_overrides", {})))
    search_config["maps"] = [case.map_name]

    output = Path(str(lab_config["output"]["directory"]))
    if not output.is_absolute():
        output = root / output
    collection = output / "collection"
    search_config["output"].update(
        {
            "directory": str(collection),
            "write_candidates": True,
            "write_families": False,
            "write_unsupported": False,
            "write_word_cases": True,
            "write_deferred_word_cases": False,
            "write_placements": True,
            "max_word_case_records": None,
            "max_placement_records": None,
        }
    )
    search_config["checkpoint"]["restart"] = bool(restart)
    search_config["checkpoint"]["resume"] = not bool(restart)
    if max_placements is not None:
        search_config["limits"]["max_placements"] = max(1, int(max_placements))
    return search_config, collection


def _cached_dataset(output: Path) -> PlacementDataset | None:
    path = output / "dataset.npz"
    return PlacementDataset.load(path) if path.exists() else None


def run_positive_control(
    root: Path,
    config_path: Path | str,
    *,
    restart: bool = False,
    retrain_only: bool = False,
    max_placements: int | None = None,
) -> dict[str, object]:
    lab_config = load_positive_control_config(root, config_path)
    output = Path(str(lab_config["output"]["directory"]))
    if not output.is_absolute():
        output = root / output
    benchmark_output = output / "benchmark"
    dataset = None if restart else _cached_dataset(benchmark_output)

    collection_summary: Mapping[str, Any] | None = None
    if dataset is None:
        search_config, collection = build_collection_config(
            root,
            lab_config,
            restart=restart,
            max_placements=max_placements,
        )
        if retrain_only:
            raise FileNotFoundError(
                f"No cached dataset at {benchmark_output / 'dataset.npz'}; "
                "run the positive control once without --retrain-only"
            )
        collection_summary = SolverRunner(search_config).run()
        planar_map = build_map(str(lab_config["case_id"]))
        dataset, trace_summary = load_exact_placement_dataset(
            planar_map, collection
        )
        dataset.save(benchmark_output / "dataset.npz")
    else:
        trace_summary = {
            "cached": True,
            "placements": dataset.size,
            "stage_histogram": dataset.stage_histogram(),
            "passage_rates": dataset.passage_summary(),
        }

    report = run_learning_benchmark(dataset, lab_config, benchmark_output)
    report["case_id"] = str(lab_config["case_id"])
    report["trace_collection"] = dict(trace_summary)
    if collection_summary is not None:
        statistics = dict(collection_summary.get("statistics", {}))
        report["production_search"] = {
            "stop_reason": statistics.get("stop_reason"),
            "elapsed_seconds": statistics.get("elapsed_seconds"),
            "tainted": bool(collection_summary.get("tainted", False)),
        }
    write_benchmark_report(benchmark_output, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Collect exact production labels on a known-solvable case, then test "
            "offline learnability and online acquisition against uniform sampling."
        )
    )
    parser.add_argument(
        "--config",
        default="config/mapping_lab/double-cycle-offset-6-positive-control.json",
    )
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--restart",
        action="store_true",
        help="rerun the exact production collection and replace the cached benchmark",
    )
    parser.add_argument(
        "--retrain-only",
        action="store_true",
        help="reuse dataset.npz and rerun only learning/reporting",
    )
    parser.add_argument(
        "--max-placements",
        type=int,
        help="diagnostic-only cap for a short smoke run; omit for the real control",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.restart and args.retrain_only:
        raise SystemExit("--restart and --retrain-only are mutually exclusive")
    root = Path(args.root).resolve()
    report = run_positive_control(
        root,
        args.config,
        restart=bool(args.restart),
        retrain_only=bool(args.retrain_only),
        max_placements=args.max_placements,
    )
    compact = {
        "verdict": report["verdict"],
        "stage_histogram": report["dataset"]["stage_histogram"],
        "offline_ranking": {
            name: {
                "auc": values["auc"],
                "top_10_percent": values["top_fractions"].get("0.1"),
            }
            for name, values in report["offline"]["unconditional_ranking"].items()
        },
        "online_replay": report["online_replay"]["summary"],
    }
    lab_config = load_positive_control_config(root, args.config)
    output = Path(str(lab_config["output"]["directory"]))
    if not output.is_absolute():
        output = root / output
    print(json.dumps(compact, indent=2, sort_keys=True))
    print(f"Full report: {output / 'benchmark' / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
