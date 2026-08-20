from __future__ import annotations

import json
import random
import tempfile
import time
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping

from formal_disk4.config import load_config
from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.pipeline.api import (
    AssignmentSelection,
    FormalSolverAPI,
    SolverAPIRequest,
)
from formal_disk4.pipeline.filter_report import LEARNING_FILTER_IDS, FilterReport
from formal_disk4.pipeline.runner import SolverRunner

from .mapping import MappingEvaluation, MappingProposal, sum_counters
from .feedback import formal_profile_ids
from .space import DynamicPlanarMap, DualGraphCandidate, build_dynamic_planar_map

if TYPE_CHECKING:
    from .specialization_model import (
        SpecializationLearningModel,
        SpecializationPoolObservation,
    )
    from .weak_model import WeakOrderLearningModel, WeakOrderRolloutObservation


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
            "profile_ids": list(formal_profile_ids(self.profiles)),
            "geometry_ready": self.geometry_ready,
            "tainted": self.tainted,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "GraphEvaluation":
        identifiers = tuple(
            str(value) for value in payload.get("profile_ids", ())  # type: ignore[union-attr]
        )
        profile_count = int(payload.get("profile_count", len(identifiers)))
        restored_profiles = [
            {"formal_profile_id": profile_id} for profile_id in identifiers
        ]
        restored_profiles.extend(
            {} for _ in range(max(0, profile_count - len(restored_profiles)))
        )
        return cls(
            candidate=DualGraphCandidate.from_dict(payload["candidate"]),  # type: ignore[arg-type]
            stage_index=int(payload["stage_index"]),
            elapsed_seconds=float(payload.get("elapsed_seconds", 0.0)),
            stop_reason=str(payload.get("stop_reason", "restored")),
            counters={
                str(name): int(value)
                for name, value in dict(payload.get("counters", {})).items()  # type: ignore[arg-type]
            },
            profiles=tuple(restored_profiles),
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
        self.mapping_overrides = dict(config.get("mapping_search_overrides", {}))

    def _configured_dynamic(
        self,
        candidate: DualGraphCandidate,
        directory: Path,
        *,
        mapping_rollout: bool = False,
    ) -> tuple[DynamicPlanarMap, dict[str, Any]]:
        dynamic = build_dynamic_planar_map(candidate)
        config = deepcopy(self.base_config)
        _deep_merge(config, self.overrides)
        if mapping_rollout:
            _deep_merge(config, self.mapping_overrides)
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
        return dynamic, config

    @staticmethod
    def _assignment_enumerator(
        dynamic: DynamicPlanarMap, config: Mapping[str, Any]
    ) -> AssignmentEnumerator:
        enumeration = config["enumeration"]
        pointwise = enumeration.get("cyclic_equivariance", {})
        return AssignmentEnumerator(
            dynamic.planar_map,
            allow_reflections=bool(enumeration["allow_reflections"]),
            symmetry_mode=str(enumeration["symmetry_mode"]),
            required_equivariance=(
                str(pointwise.get("automorphism", "rotation_1"))
                if pointwise.get("enabled", False)
                else None
            ),
            required_equivariance_on_weak_orders=bool(
                pointwise.get("enforce_weak_orders", True)
            ),
        )

    def mapping_pool(
        self,
        candidate: DualGraphCandidate,
        rng: random.Random,
        amount: int,
    ) -> tuple[MappingProposal, ...]:
        """Sample cheap complete mappings; quotient rejection remains a target.

        Cyclic-shift equivariance is an imposed search restriction, not a rare
        downstream event.  Sampling the unrestricted raw assignment space here
        would make almost every Stein mapping die before its first weak-order
        decision, leaving the ranker with no useful contrast.
        """

        with tempfile.TemporaryDirectory(prefix="formal-disk4-mapping-domain-") as raw:
            dynamic, config = self._configured_dynamic(candidate, Path(raw))
            enumerator = self._assignment_enumerator(dynamic, config)
            cyclic_automorphism = (
                dynamic.imposed_automorphism
                if dynamic.imposed_equivariance_mode == "cyclic_shift"
                else None
            )
            total = (
                enumerator.cyclic_shift_compatible_assignment_count(
                    cyclic_automorphism
                )
                if cyclic_automorphism is not None
                else enumerator.raw_assignment_count()
            )
            if total <= 0:
                return ()
            target = min(max(1, int(amount)), total)
            selected: set[int] = set()
            while len(selected) < target:
                selected.add(rng.randrange(total))
            return tuple(
                MappingProposal.from_assignment(
                    candidate,
                    (
                        enumerator.cyclic_shift_compatible_assignment_at(
                            cyclic_automorphism, assignment_id
                        )
                        if cyclic_automorphism is not None
                        else enumerator.assignment_at(assignment_id)
                    ),
                    dynamic.planar_map,
                )
                for assignment_id in sorted(selected)
            )

    def evaluate_mapping(
        self,
        proposal: MappingProposal,
        *,
        rollouts: int,
        random_seed: int,
        weak_model: WeakOrderLearningModel | None = None,
        weak_sampling: Mapping[str, object] | None = None,
        rollout_sink: Callable[[WeakOrderRolloutObservation], None] | None = None,
        specialization_model: SpecializationLearningModel | None = None,
        specialization_sampling: Mapping[str, object] | None = None,
        specialization_sink: Callable[[SpecializationPoolObservation], None]
        | None = None,
    ) -> MappingEvaluation:
        """Run bounded stochastic weak-order descendants of one fixed mapping."""

        started = time.perf_counter()
        counter_values: list[Mapping[str, int]] = []
        clean_rollout_reports: list[FilterReport] = []
        profiles: list[Mapping[str, object]] = []
        reasons: list[str] = []
        tainted = False
        weak_config = dict(weak_sampling or {})
        rollout_total = max(1, int(rollouts))
        exploration_rollouts = min(
            rollout_total,
            max(
                1,
                int(
                    round(
                        rollout_total
                        * float(weak_config.get("exploration_fraction", 0.25))
                    )
                ),
            ),
        )
        try:
            for rollout in range(rollout_total):
                rollout_started = time.perf_counter()
                rollout_seed = int(random_seed) + rollout * 104729
                selection_mode = (
                    "exploration" if rollout < exploration_rollouts else "learned"
                )
                if weak_model is not None:
                    from .weak_model import WeakOrderRankedPolicy

                branch_policy = (
                    WeakOrderRankedPolicy(
                        proposal,
                        weak_model,
                        weak_config,
                        random_seed=rollout_seed,
                        selection_mode=selection_mode,
                    )
                    if weak_model is not None
                    else None
                )
                specialization_policy = None
                if specialization_model is not None:
                    from .specialization_model import SpecializationRankedPolicy

                    specialization_policy = SpecializationRankedPolicy(
                        proposal,
                        specialization_model,
                        dict(specialization_sampling or {}),
                        random_seed=rollout_seed + 7919,
                    )
                with tempfile.TemporaryDirectory(
                    prefix="formal-disk4-mapping-rollout-"
                ) as raw:
                    directory = Path(raw)
                    dynamic, config = self._configured_dynamic(
                        proposal.candidate, directory, mapping_rollout=True
                    )
                    with (directory / "solver.log").open(
                        "w", encoding="utf-8"
                    ) as diagnostic_stream:
                        with redirect_stdout(diagnostic_stream), redirect_stderr(
                            diagnostic_stream
                        ):
                            result = FormalSolverAPI.evaluate(
                                SolverAPIRequest(
                                    config=config,
                                    planar_maps=(dynamic.planar_map,),
                                    assignments=(
                                        AssignmentSelection(
                                            dynamic.planar_map.name,
                                            (proposal.raw_assignment_id,),
                                        ),
                                    ),
                                    weak_order_random_seed=(
                                        rollout_seed if branch_policy is None else None
                                    ),
                                    weak_order_branch_policy=branch_policy,
                                    family_specialization_policy=specialization_policy,
                                    collect_learning_diagnostics=True,
                                    collect_profiles=True,
                                )
                            )
                    if not bool(result.summary.get("tainted", False)):
                        clean_rollout_reports.append(result.filters)
                    statistics = dict(result.summary.get("statistics", {}))
                    counters = {
                        str(name): int(value)
                        for name, value in dict(
                            statistics.get("counters", {})
                        ).items()
                    }
                    counter_values.append(counters)
                    reasons.append(str(statistics.get("stop_reason", "unknown")))
                    tainted |= bool(result.summary.get("tainted", False))
                    rollout_profiles = list(result.profiles)
                    profiles.extend(rollout_profiles)
                    if specialization_policy is not None and specialization_sink is not None:
                        for pool_observation in specialization_policy.observations:
                            specialization_sink(pool_observation)
                    if branch_policy is not None and rollout_sink is not None:
                        from .weak_model import WeakOrderRolloutObservation

                        actual_modes = {
                            decision.selection_mode
                            for decision in branch_policy.decisions
                        }
                        actual_mode = (
                            next(iter(actual_modes))
                            if len(actual_modes) == 1
                            else ("mixed" if actual_modes else "uncontrolled")
                        )
                        rollout_sink(
                            WeakOrderRolloutObservation(
                                proposal=proposal,
                                decisions=tuple(branch_policy.decisions),
                                filters=result.filters,
                                elapsed_seconds=time.perf_counter()
                                - rollout_started,
                                profile_count=len(rollout_profiles),
                                profile_ids=formal_profile_ids(rollout_profiles),
                                selection_mode=actual_mode,
                                random_seed=rollout_seed,
                                tainted=bool(result.summary.get("tainted", False)),
                            )
                        )
            counters = sum_counters(counter_values)
            reach_vector = tuple(
                sum(
                    1.0 if report.observations[index].entered else 0.0
                    for report in clean_rollout_reports
                )
                / len(clean_rollout_reports)
                for index in range(len(LEARNING_FILTER_IDS))
            ) if clean_rollout_reports else tuple(None for _ in LEARNING_FILTER_IDS)
            return MappingEvaluation(
                proposal=proposal,
                filters=FilterReport.from_counters(counters),
                counters=counters,
                rollout_count=rollout_total,
                elapsed_seconds=time.perf_counter() - started,
                profiles=tuple(profiles),
                tainted=tainted,
                stop_reasons=tuple(reasons),
                reach_vector=reach_vector,
            )
        except Exception as error:
            counters = sum_counters(counter_values)
            reach_vector = tuple(
                sum(
                    1.0 if report.observations[index].entered else 0.0
                    for report in clean_rollout_reports
                )
                / len(clean_rollout_reports)
                for index in range(len(LEARNING_FILTER_IDS))
            ) if clean_rollout_reports else tuple(None for _ in LEARNING_FILTER_IDS)
            return MappingEvaluation(
                proposal=proposal,
                filters=FilterReport.from_counters(counters),
                counters=counters,
                rollout_count=len(counter_values),
                elapsed_seconds=time.perf_counter() - started,
                profiles=tuple(profiles),
                tainted=True,
                stop_reasons=tuple(reasons),
                reach_vector=reach_vector,
                error=f"{type(error).__name__}: {error}",
            )

    def aggregate_mappings(
        self,
        candidate: DualGraphCandidate,
        mappings: list[MappingEvaluation],
    ) -> GraphEvaluation:
        counters = sum_counters([item.counters for item in mappings])
        profiles = tuple(
            profile for item in mappings for profile in item.profiles
        )
        return GraphEvaluation(
            candidate=candidate,
            stage_index=self._stage(counters),
            elapsed_seconds=sum(item.elapsed_seconds for item in mappings),
            stop_reason="mapping_rollouts",
            counters=counters,
            profiles=profiles,
            tainted=any(item.tainted for item in mappings),
            error="; ".join(item.error for item in mappings if item.error) or None,
        )

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
            with tempfile.TemporaryDirectory(prefix="formal-disk4-graph-lab-") as raw:
                directory = Path(raw)
                dynamic, config = self._configured_dynamic(candidate, directory)
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
