from __future__ import annotations

import json
import tempfile
import time
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from formal_disk4.config import load_config
from formal_disk4.pipeline.runner import SolverRunner

from .space import DualGraphCandidate, build_dynamic_planar_map


GRAPH_STAGES = (
    "generated_graph",
    "assignment",
    "placement",
    "preword_pass",
    "word_family",
    "geometry_ready",
)


def _deep_merge(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = deepcopy(value)


@dataclass(frozen=True)
class GraphEvaluation:
    candidate: DualGraphCandidate
    stage_index: int
    elapsed_seconds: float
    stop_reason: str
    counters: Mapping[str, int]
    profiles: tuple[Mapping[str, object], ...]
    tainted: bool
    error: str | None = None

    @property
    def stage_name(self) -> str:
        return GRAPH_STAGES[self.stage_index]

    @property
    def geometry_ready(self) -> bool:
        return bool(self.profiles)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "graph-lab-observation-v1",
            "candidate": self.candidate.to_dict(),
            "stage_index": self.stage_index,
            "stage_name": self.stage_name,
            "elapsed_seconds": self.elapsed_seconds,
            "stop_reason": self.stop_reason,
            "counters": dict(self.counters),
            "profile_count": len(self.profiles),
            "geometry_ready": self.geometry_ready,
            "tainted": self.tainted,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "GraphEvaluation":
        return cls(
            candidate=DualGraphCandidate.from_dict(payload["candidate"]),  # type: ignore[arg-type]
            stage_index=int(payload["stage_index"]),
            elapsed_seconds=float(payload.get("elapsed_seconds", 0.0)),
            stop_reason=str(payload.get("stop_reason", "restored")),
            counters={
                str(name): int(value)
                for name, value in dict(payload.get("counters", {})).items()  # type: ignore[arg-type]
            },
            profiles=(),
            tainted=bool(payload.get("tainted", False)),
            error=str(payload["error"]) if payload.get("error") else None,
        )


class GraphFormalEvaluator:
    """Run one dynamic structural map through a bounded production search."""

    def __init__(
        self,
        root: Path,
        config: Mapping[str, object],
    ) -> None:
        self.root = root.resolve()
        base_path = Path(str(config.get("base_search_config", "config/cycle_campaign/search.json")))
        if not base_path.is_absolute():
            base_path = self.root / base_path
        self.base_config = load_config(base_path)
        self.overrides = dict(config.get("search_overrides", {}))

    @staticmethod
    def _stage(counters: Mapping[str, int]) -> int:
        stage = 0
        if int(counters.get("assignments_processed", 0)) > 0:
            stage = 1
        if int(counters.get("surviving_placements", 0)) > 0:
            stage = 2
        if int(counters.get("solver_cases", 0)) > 0:
            stage = 3
        if int(counters.get("word_families", 0)) > 0:
            stage = 4
        if int(counters.get("profiles_emitted", 0)) > 0:
            stage = 5
        return stage

    def evaluate(self, candidate: DualGraphCandidate) -> GraphEvaluation:
        started = time.perf_counter()
        try:
            dynamic = build_dynamic_planar_map(candidate)
            with tempfile.TemporaryDirectory(prefix="formal-disk4-graph-lab-") as raw:
                directory = Path(raw)
                config = deepcopy(self.base_config)
                _deep_merge(config, self.overrides)
                config["maps"] = [dynamic.planar_map.name]
                config["output"].update(
                    {
                        "directory": str(directory),
                        "write_candidates": True,
                        "write_families": False,
                        "write_unsupported": False,
                        "write_word_cases": False,
                        "write_deferred_word_cases": False,
                        "write_placements": False,
                        "write_errors": True,
                        "max_error_records": 100,
                    }
                )
                config["checkpoint"].update(
                    {"enabled": False, "resume": False, "restart": False}
                )
                config["progress"]["enabled"] = False
                config["enumeration"]["track_exact_domain_size"] = False
                pointwise_config = config["enumeration"].setdefault(
                    "cyclic_equivariance", {}
                )
                cyclic_shift_config = config["enumeration"].setdefault(
                    "cyclic_shift_equivariance", {}
                )
                pointwise_config["enabled"] = False
                cyclic_shift_config["enabled"] = False
                if dynamic.imposed_automorphism is None:
                    pass
                elif dynamic.imposed_equivariance_mode == "pointwise":
                    pointwise_config.update(
                        {
                            "enabled": True,
                            "automorphism": dynamic.imposed_automorphism,
                            "enforce_weak_orders": True,
                        }
                    )
                elif dynamic.imposed_equivariance_mode == "cyclic_shift":
                    cyclic_shift_config.update(
                        {
                            "enabled": True,
                            "automorphism": dynamic.imposed_automorphism,
                        }
                    )
                else:
                    raise ValueError("Unknown imposed Graph Lab equivariance mode")
                # Production diagnostics can contain thousands of deferred word
                # cases. Keep the long-running Graph Lab console focused on one
                # compact line per graph and explicit GEOMETRY READY events.
                with (directory / "solver.log").open(
                    "w", encoding="utf-8"
                ) as diagnostic_stream:
                    with redirect_stdout(diagnostic_stream), redirect_stderr(
                        diagnostic_stream
                    ):
                        summary = SolverRunner(
                            config, planar_maps=(dynamic.planar_map,)
                        ).run()
                statistics = dict(summary.get("statistics", {}))
                counters = {
                    str(name): int(value)
                    for name, value in dict(statistics.get("counters", {})).items()
                }
                profiles = []
                candidate_path = directory / str(config["output"]["candidates_file"])
                if candidate_path.exists():
                    with candidate_path.open("r", encoding="utf-8") as stream:
                        for line in stream:
                            if line.strip():
                                value = json.loads(line)
                                if isinstance(value, dict):
                                    profiles.append(value)
                return GraphEvaluation(
                    candidate=candidate,
                    stage_index=self._stage(counters),
                    elapsed_seconds=time.perf_counter() - started,
                    stop_reason=str(statistics.get("stop_reason", "unknown")),
                    counters=counters,
                    profiles=tuple(profiles),
                    tainted=bool(summary.get("tainted", False)),
                )
        except Exception as error:
            return GraphEvaluation(
                candidate=candidate,
                stage_index=0,
                elapsed_seconds=time.perf_counter() - started,
                stop_reason="evaluation_error",
                counters={},
                profiles=(),
                tainted=True,
                error=f"{type(error).__name__}: {error}",
            )
