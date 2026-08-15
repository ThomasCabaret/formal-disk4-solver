from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any, Sequence

from formal_disk4.config import load_geometry_config
from formal_disk4.geometry.status import remove_sqlite_files

from .dashboard import GraphLabDashboardServer
from .geometry_catalog import GeometryCandidateCatalog
from .geometry_queue import GeometryQueueWorker
from .runner import GraphLabRunner


def _resolved_geometry_config(
    root: Path, runner: GraphLabRunner, source: Path
) -> dict[str, Any]:
    path = source if source.is_absolute() else root / source
    config = load_geometry_config(path)
    config["input"]["candidates_file"] = str(
        runner.output / "geometry_candidates.jsonl"
    )
    config["output"]["directory"] = str(runner.output / "geometry")
    return config


def _reset_geometry_outputs(config: dict[str, Any]) -> None:
    output = Path(str(config["output"]["directory"])).resolve()
    output.mkdir(parents=True, exist_ok=True)
    names = (
        str(config["output"].get("solutions_file", "geometric_solutions.jsonl")),
        str(config["output"].get("summary_file", "geometry_summary.json")),
        str(config["output"].get("checkpoint_file", "geometry_checkpoint.json")),
        str(config["output"].get("failures_file", "geometry_failures.jsonl")),
        "geometry_queue_summary.json",
        "geometry_queue_checkpoint.json",
        "geometry_queue_batch.jsonl",
        "geometry_worker_state.json",
    )
    for name in names:
        path = output / name
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    remove_sqlite_files(
        output / str(config["output"].get("status_file", "geometry_status.sqlite3"))
    )
    remove_sqlite_files(output / "geometry_candidate_catalog.sqlite3")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="formal-disk4-lab",
        description=(
            "Run the learned Graph Lab, unified web dashboard, and background "
            "geometry queue from one console command."
        ),
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--config", default="config/graph_lab/up-to-13.json")
    parser.add_argument(
        "--geometry-config", default="config/graph_lab/geometry.json"
    )
    parser.add_argument("--generations", type=int)
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--restart", action="store_true")
    parser.add_argument(
        "--exclude-rings",
        action="store_true",
        help=(
            "exclude outside-star plus simple tile-cycle graphs before graph ranking"
        ),
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--window-generations", type=int, default=50)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-dashboard", action="store_true")
    parser.add_argument("--no-geometry", action="store_true")
    parser.add_argument(
        "--exit-when-complete",
        action="store_true",
        help="exit instead of keeping the completed dashboard open",
    )
    parser.add_argument("--geometry-batch-size", type=int, default=16)
    parser.add_argument("--geometry-poll-seconds", type=float, default=1.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    runner = GraphLabRunner.from_file(
        root,
        args.config,
        exclude_rings=True if args.exclude_rings else None,
    )
    geometry_config = _resolved_geometry_config(
        root, runner, Path(args.geometry_config)
    )
    if args.restart:
        runner.restart_outputs()
        _reset_geometry_outputs(geometry_config)

    dashboard: GraphLabDashboardServer | None = None
    owned_catalog: GeometryCandidateCatalog | None = None
    if not args.no_dashboard:
        dashboard = GraphLabDashboardServer(
            runner.output,
            host=args.host,
            port=args.port,
            window_generations=max(1, int(args.window_generations)),
        )
        dashboard.start(open_browser=not args.no_browser)
        catalog = dashboard.catalog
        print(f"dashboard: {dashboard.url}", flush=True)
    else:
        owned_catalog = GeometryCandidateCatalog(
            runner.output / "geometry" / "geometry_candidate_catalog.sqlite3",
            runner.output / "geometry_candidates.jsonl",
        )
        catalog = owned_catalog

    geometry_worker: GeometryQueueWorker | None = None
    if not args.no_geometry:
        geometry_worker = GeometryQueueWorker(
            geometry_config,
            catalog,
            poll_seconds=args.geometry_poll_seconds,
            batch_size=args.geometry_batch_size,
        )
        geometry_worker.start()
        print("geometry worker: background queue enabled", flush=True)

    result = None
    try:
        result = runner.run(
            restart=False,
            generations=args.generations,
            batch_size=args.batch_size,
        )
        if geometry_worker is not None:
            geometry_worker.mark_producer_done()
        print(
            "graph-lab complete: "
            f"generations={result.generations_completed} "
            f"observations={result.observations} "
            f"geometry-ready={result.geometry_ready_graphs} "
            f"stop={result.stop_reason} output={result.output_directory}",
            flush=True,
        )
        keep_open = (
            dashboard is not None
            and not args.exit_when_complete
            and result.stop_reason == "completed"
        )
        if keep_open:
            print(
                "Lab terminé; le dashboard et la file géométrique restent ouverts. "
                "Ctrl+C pour fermer.",
                flush=True,
            )
            while True:
                time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nGraph Lab application stopped.", flush=True)
    finally:
        if geometry_worker is not None:
            geometry_worker.stop()
            geometry_worker.join(timeout=30.0)
        if dashboard is not None:
            dashboard.close()
        if owned_catalog is not None:
            owned_catalog.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
