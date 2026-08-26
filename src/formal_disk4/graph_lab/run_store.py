from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, Mapping

from formal_disk4.pipeline.output import atomic_replace


RUN_OWNED_FILES = (
    "observations.jsonl",
    "training_metrics.jsonl",
    "geometry_candidates.jsonl",
    "geometry_graphs.jsonl",
    "model.pt",
    "mapping_observations.jsonl",
    "mapping_training_metrics.jsonl",
    "mapping_model.pt",
    "deep_mapping_candidates.jsonl",
    "weak_order_rollouts.jsonl",
    "weak_order_training_metrics.jsonl",
    "rollout_coverage_metrics.jsonl",
    "weak_order_model.pt",
    "deep_weak_order_candidates.jsonl",
    "specialization_pools.jsonl",
    "specialization_training_metrics.jsonl",
    "specialization_model.pt",
    "state.json",
    "report.json",
    "report.md",
    "effective_config.json",
)


class GraphLabRunStore:
    """Durable run-state boundary shared by search strategies.

    Traversal code owns observations, not filesystem details.  Keeping this
    contract strategy-neutral allows future graph and weak-order backtrackers
    to reuse the same resume and dashboard data without becoming part of the
    web server or the learning subsystem.
    """

    def __init__(
        self,
        output: Path,
        *,
        maximum_bytes: int | None = None,
    ) -> None:
        self.output = output.resolve()
        self.maximum_bytes = maximum_bytes

    def path(self, name: str) -> Path:
        return self.output / name

    def restart(self) -> None:
        self.output.mkdir(parents=True, exist_ok=True)
        for name in RUN_OWNED_FILES:
            path = self.path(name)
            temporary = path.with_suffix(path.suffix + ".tmp")
            for stale in (path, temporary):
                try:
                    stale.unlink()
                except FileNotFoundError:
                    pass

    def write_json(self, name: str, payload: Mapping[str, object]) -> None:
        path = self.path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        atomic_replace(temporary, path)

    def append_jsonl(self, name: str, payload: Mapping[str, object]) -> None:
        path = self.path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, sort_keys=True) + "\n")
            stream.flush()

    def iter_jsonl(self, name: str) -> Iterator[dict[str, object]]:
        path = self.path(name)
        if not path.exists():
            return
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if not line.strip():
                    continue
                value = json.loads(line)
                if isinstance(value, dict):
                    yield value

    def total_bytes(self) -> int:
        if not self.output.exists():
            return 0
        total = 0
        for path in self.output.rglob("*"):
            if not path.is_file() or path.name.endswith(".tmp"):
                continue
            try:
                total += path.stat().st_size
            except OSError:
                # Geometry and dashboard workers may atomically replace files.
                continue
        return total

    def budget_reached(self) -> bool:
        return (
            self.maximum_bytes is not None
            and self.total_bytes() >= self.maximum_bytes
        )
