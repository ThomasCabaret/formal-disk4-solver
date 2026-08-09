from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import random
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .backend import ObservationBatch
from .core import (
    LAB_SEMANTICS_VERSION,
    CompleteMappingEvaluator,
    LabEvaluation,
    MappingSpace,
)
from .deep_report import write_deep_report
from .deep_support import (
    DEEP_STAGES,
    WORD_SOLVER_DEPTH,
    DeepArchive,
    DeepProposalContext,
    DeepSampler,
    DeepScoringBackend,
    PersistentSeen,
    deep_failure_name,
    deep_learning_depth,
    recover_deep_candidates,
    recover_prior_observations,
)
from .neural import NeuralLearningBackend
from .runner import EvaluationWorker


DEEP_EXPERIMENT_VERSION = "mapping-lab-deep-curriculum-v2"
KNOWN_RESTART_TARGETS = (
    "arms",
    "progress.jsonl",
    "report.json",
    "report.md",
    "experiment.json",
)


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _append_jsonl(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, sort_keys=True) + "\n")
        stream.flush()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                result.append(payload)
    return result


def _fresh_stats() -> dict[str, object]:
    return {
        "schema_version": "mapping-lab-deep-arm-stats-v1",
        "evaluations": 0,
        "timeouts": 0,
        "errors": 0,
        "depth_sum": 0.0,
        "max_depth": 0,
        "depth_reached_counts": {name: 0 for name in DEEP_STAGES},
        "curriculum_failure_histogram": {},
        "terminal_reason_histogram": {},
        "strategy_histogram": {},
        "sampling": {},
        "repair": {
            "attempted": 0,
            "improved": 0,
            "same": 0,
            "regressed": 0,
            "failure_changed": 0,
            "depth_delta_sum": 0,
            "probe_topology_retained": 0,
            "probe_positive_lengths": 0,
            "score_compared": 0,
            "score_improved": 0,
            "score_delta_sum": 0.0,
            "operator_attempts": {},
            "operator_nonregressions": {},
            "operator_score_compared": {},
            "operator_score_improvements": {},
            "operator_positive_lengths": {},
        },
        "timing_seconds": {
            "proposal": 0.0,
            "evaluation": 0.0,
            "learning": 0.0,
            "reporting": 0.0,
            "total": 0.0,
        },
        "trend": {"initial": [], "recent": []},
    }


def _merge_counter(
    stats: dict[str, object], key: str, additions: Mapping[str, int]
) -> None:
    current = Counter(
        {str(name): int(value) for name, value in dict(stats.get(key, {})).items()}
    )
    current.update({str(name): int(value) for name, value in additions.items()})
    stats[key] = dict(current.most_common(512))


def _update_stats(
    stats: dict[str, object],
    evaluations: Sequence[LabEvaluation],
    contexts: Mapping[str, DeepProposalContext],
    sampling: Mapping[str, int],
    timing: Mapping[str, float],
    *,
    generation: int,
    window_size: int = 50,
) -> None:
    reached = Counter(
        {
            str(name): int(value)
            for name, value in dict(stats["depth_reached_counts"]).items()
        }
    )
    failures: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    strategies: Counter[str] = Counter()
    repair = dict(stats["repair"])
    operator_attempts = Counter(
        {
            str(name): int(value)
            for name, value in dict(repair.get("operator_attempts", {})).items()
        }
    )
    operator_nonregressions = Counter(
        {
            str(name): int(value)
            for name, value in dict(
                repair.get("operator_nonregressions", {})
            ).items()
        }
    )
    operator_score_compared = Counter(
        {
            str(name): int(value)
            for name, value in dict(
                repair.get("operator_score_compared", {})
            ).items()
        }
    )
    operator_score_improvements = Counter(
        {
            str(name): int(value)
            for name, value in dict(
                repair.get("operator_score_improvements", {})
            ).items()
        }
    )
    operator_positive_lengths = Counter(
        {
            str(name): int(value)
            for name, value in dict(
                repair.get("operator_positive_lengths", {})
            ).items()
        }
    )
    usable = []
    for evaluation in evaluations:
        stats["evaluations"] = int(stats["evaluations"]) + 1
        reasons[f"{evaluation.terminal_stage}:{evaluation.reason}"] += 1
        strategies[evaluation.proposal_strategy] += 1
        if evaluation.status == "timeout":
            stats["timeouts"] = int(stats["timeouts"]) + 1
            continue
        if evaluation.status == "evaluation_error":
            stats["errors"] = int(stats["errors"]) + 1
            continue
        usable.append(evaluation)
        depth = deep_learning_depth(evaluation)
        failure = deep_failure_name(evaluation)
        failures[failure] += 1
        stats["depth_sum"] = float(stats["depth_sum"]) + depth
        stats["max_depth"] = max(int(stats["max_depth"]), depth)
        for index, name in enumerate(DEEP_STAGES):
            if depth >= index:
                reached[name] += 1
        context = contexts.get(evaluation.candidate_id, DeepProposalContext())
        if context.parent_depth is None:
            continue
        operator = context.operator or evaluation.proposal_strategy
        operator_attempts[operator] += 1
        repair["attempted"] = int(repair["attempted"]) + 1
        delta = depth - context.parent_depth
        repair["depth_delta_sum"] = int(repair["depth_delta_sum"]) + delta
        if delta > 0:
            repair["improved"] = int(repair["improved"]) + 1
        elif delta == 0:
            repair["same"] = int(repair["same"]) + 1
            operator_nonregressions[operator] += 1
        else:
            repair["regressed"] = int(repair["regressed"]) + 1
        if delta > 0:
            operator_nonregressions[operator] += 1
        if failure != context.parent_failure:
            repair["failure_changed"] = int(repair["failure_changed"]) + 1
        if context.proposal_preword_topology:
            repair["probe_topology_retained"] = int(
                repair.get("probe_topology_retained", 0)
            ) + 1
        if context.proposal_positive_lengths:
            repair["probe_positive_lengths"] = int(
                repair.get("probe_positive_lengths", 0)
            ) + 1
            operator_positive_lengths[operator] += 1
        if (
            context.parent_repair_score is not None
            and context.proposal_repair_score is not None
        ):
            score_delta = (
                context.proposal_repair_score - context.parent_repair_score
            )
            repair["score_compared"] = int(repair.get("score_compared", 0)) + 1
            operator_score_compared[operator] += 1
            repair["score_delta_sum"] = float(
                repair.get("score_delta_sum", 0.0)
            ) + score_delta
            if score_delta > 0:
                repair["score_improved"] = int(
                    repair.get("score_improved", 0)
                ) + 1
                operator_score_improvements[operator] += 1

    stats["depth_reached_counts"] = dict(reached)
    _merge_counter(stats, "curriculum_failure_histogram", failures)
    _merge_counter(stats, "terminal_reason_histogram", reasons)
    _merge_counter(stats, "strategy_histogram", strategies)
    _merge_counter(stats, "sampling", sampling)
    repair["operator_attempts"] = dict(operator_attempts)
    repair["operator_nonregressions"] = dict(operator_nonregressions)
    repair["operator_score_compared"] = dict(operator_score_compared)
    repair["operator_score_improvements"] = dict(operator_score_improvements)
    repair["operator_positive_lengths"] = dict(operator_positive_lengths)
    stats["repair"] = repair
    cumulative_timing = dict(stats["timing_seconds"])
    for name, seconds in timing.items():
        cumulative_timing[name] = float(cumulative_timing.get(name, 0.0)) + float(
            seconds
        )
    stats["timing_seconds"] = cumulative_timing

    depth_values = [deep_learning_depth(item) for item in usable]
    point = {
        "generation": generation,
        "evaluations": len(usable),
        "depth_sum": sum(depth_values),
        "reached_first_metric_step": sum(value >= 9 for value in depth_values),
        "reached_word_solver": sum(
            value >= WORD_SOLVER_DEPTH for value in depth_values
        ),
        "max_depth": max(depth_values, default=0),
    }
    trend = dict(stats.get("trend", {}))
    initial = list(trend.get("initial", []))
    recent = list(trend.get("recent", []))
    if len(initial) < window_size:
        initial.append(point)
    recent.append(point)
    stats["trend"] = {
        "initial": initial[:window_size],
        "recent": recent[-window_size:],
    }


class DeepExperimentRunner:
    def __init__(self, root: Path, config: Mapping[str, Any]) -> None:
        self.root = root.resolve()
        self.config = dict(config)
        self.case_id = str(self.config["case_id"])
        self.space = MappingSpace(self.root, self.case_id)
        self.fingerprint = hashlib.sha256(
            json.dumps(self.config, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        raw_output = Path(str(dict(self.config["output"])["directory"]))
        self.output = (
            raw_output if raw_output.is_absolute() else self.root / raw_output
        ).resolve()
        try:
            self.output.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("deep experiment output must stay inside the project") from exc
        if self.output == self.root:
            raise ValueError("deep experiment output cannot be the project root")
        sampling = dict(self.config.get("sampling", {}))
        self.seed = int(sampling.get("seed", 20260804))
        self.generations = max(1, int(sampling.get("generations", 1000)))
        self.batch_size = max(1, int(sampling.get("batch_size", 64)))
        self.sampling = sampling
        raw_arms = self.config.get("arms", list(DeepSampler.MODES))
        if not isinstance(raw_arms, Sequence) or isinstance(raw_arms, str):
            raise ValueError("deep experiment arms must be an array")
        self.arms = tuple(str(value) for value in raw_arms)
        unknown = set(self.arms) - set(DeepSampler.MODES)
        if unknown:
            raise ValueError(f"unknown deep experiment arms: {sorted(unknown)}")
        self.backend_config = dict(self.config.get("backend", {}))
        self.evaluation = dict(self.config.get("evaluation", {}))
        # The deep campaign needs only the exact nested pre-word stages.  The
        # broader learning diagnostics are intentionally disabled because they
        # solve complete pre-word systems even for candidates rejected earlier.
        self.evaluation["enable_learning_diagnostics"] = False
        self.evaluation["enable_deep_curriculum_diagnostics"] = True
        self.hard_timeout = max(
            0.001, float(self.evaluation.get("hard_timeout_seconds", 20.0))
        )
        self.startup_timeout = max(
            1.0, float(self.evaluation.get("startup_timeout_seconds", 60.0))
        )
        archive = dict(self.config.get("archive", {}))
        self.archive_capacity = max(1, int(archive.get("capacity", 5000)))
        self.archive_per_failure = max(1, int(archive.get("per_failure", 2000)))
        bootstrap = dict(self.config.get("bootstrap", {}))
        raw_sources = bootstrap.get("source_arm_directories", [])
        self.bootstrap_sources = tuple(
            self._project_path(str(value)) for value in raw_sources
        )
        self.bootstrap_minimum_stage = max(
            0, int(bootstrap.get("minimum_stage_index", 8))
        )
        self.prior_examples_per_stage = max(
            1, int(bootstrap.get("prior_training_max_examples_per_stage", 5000))
        )
        self.prior_observations = recover_prior_observations(
            self.space,
            self.bootstrap_sources,
            maximum_stage_exclusive=self.bootstrap_minimum_stage,
            maximum_examples_per_stage=self.prior_examples_per_stage,
        )

    @classmethod
    def from_file(cls, root: Path, path: Path | str) -> "DeepExperimentRunner":
        config_path = Path(path)
        if not config_path.is_absolute():
            config_path = root / config_path
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("deep experiment config must be an object")
        return cls(root, payload)

    def _project_path(self, value: str) -> Path:
        path = Path(value)
        resolved = (path if path.is_absolute() else self.root / path).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("deep experiment data paths must stay inside the project") from exc
        return resolved

    def _restart(self, *, rebuild_bootstrap: bool) -> None:
        self.output.mkdir(parents=True, exist_ok=True)
        for name in KNOWN_RESTART_TARGETS:
            path = self.output / name
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        if rebuild_bootstrap:
            for name in ("bootstrap.jsonl", "bootstrap_meta.json"):
                path = self.output / name
                if path.exists():
                    path.unlink()

    def _ensure_bootstrap(
        self, worker: EvaluationWorker, *, limit: int | None = None
    ) -> list[dict[str, Any]]:
        path = self.output / "bootstrap.jsonl"
        meta_path = self.output / "bootstrap_meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if (
                meta.get("version") != DEEP_EXPERIMENT_VERSION
                or meta.get("space_fingerprint") != self.space.fingerprint
            ):
                raise ValueError(
                    "the cached deep bootstrap is incompatible; use "
                    "--restart --rebuild-bootstrap"
                )
        records = _load_jsonl(path)
        completed = {
            str(item.get("candidate_id"))
            for item in records
            if not (
                isinstance(item.get("diagnostics"), Mapping)
                and "diagnostic_error" in item["diagnostics"]
            )
        }
        all_candidates = recover_deep_candidates(
            self.space,
            self.bootstrap_sources,
            minimum_stage=self.bootstrap_minimum_stage,
        )
        # A clean checkout has no ignored historical output. In that case the
        # study starts with empty models/archives and every arm falls back to
        # fresh uniform proposals until it discovers its own deep frontier.
        # Historical sources remain an optional acceleration, not a hidden
        # prerequisite for running the experiment.
        candidates = (
            all_candidates[: max(1, int(limit))]
            if limit is not None
            else all_candidates
        )
        missing = [item for item in candidates if item.candidate_id not in completed]
        print(
            f"deep bootstrap recovered={len(all_candidates)} selected={len(candidates)} "
            f"cached={len(records)} "
            f"to_evaluate={len(missing)}",
            flush=True,
        )
        for index, candidate in enumerate(missing, start=1):
            evaluation = worker.evaluate(candidate, self.hard_timeout)
            record = evaluation.to_dict(self.space.assignments.occurrence_names)
            record.update(
                {
                    "deep_depth": deep_learning_depth(evaluation),
                    "deep_failure": deep_failure_name(evaluation),
                    "bootstrap_index": len(records),
                }
            )
            _append_jsonl(path, record)
            records.append(record)
            if index == 1 or index % 25 == 0 or index == len(missing):
                print(
                    f"  bootstrap {index}/{len(missing)} "
                    f"depth={record['deep_depth']} failure={record['deep_failure']}",
                    flush=True,
                )
        _atomic_json(
            meta_path,
            {
                "schema_version": "mapping-lab-deep-bootstrap-meta-v1",
                "version": DEEP_EXPERIMENT_VERSION,
                "space_fingerprint": self.space.fingerprint,
                "records": len(records),
                "source_directories": [str(path) for path in self.bootstrap_sources],
            },
        )
        return records

    def _arm_components(
        self, arm: str, bootstrap: Sequence[Mapping[str, object]]
    ) -> tuple[
        Path,
        DeepScoringBackend,
        DeepArchive,
        PersistentSeen,
        dict[str, object],
        int,
    ]:
        directory = self.output / "arms" / arm
        directory.mkdir(parents=True, exist_ok=True)
        policy = "expected" if arm == "expected_ranker" else "deepest"
        raw_backend, _ = NeuralLearningBackend.load_or_create(
            directory,
            input_dimension=self.space.mapping_feature_dimension,
            transition_stages=tuple(range(4, len(DEEP_STAGES))),
            config=self.backend_config,
            seed=self.seed,
            feature_builder=self.space.mapping_feature_vector,
        )
        backend = DeepScoringBackend(raw_backend, policy)
        archive_path = directory / "archive.json"
        archive = (
            DeepArchive.from_dict(json.loads(archive_path.read_text(encoding="utf-8")))
            if archive_path.exists()
            else DeepArchive(self.archive_capacity, self.archive_per_failure)
        )
        seen = PersistentSeen(directory / "seen.sqlite3")
        stats_path = directory / "stats.json"
        stats = (
            json.loads(stats_path.read_text(encoding="utf-8"))
            if stats_path.exists()
            else _fresh_stats()
        )
        state_path = directory / "state.json"
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if state.get("fingerprint") != self.fingerprint:
                raise ValueError(f"stored {arm} state is incompatible; use --restart")
            next_generation = int(state["next_generation"])
        else:
            usable = [
                item
                for item in bootstrap
                if str(item.get("status")) not in {"timeout", "evaluation_error"}
            ]
            for item in usable:
                archive.add(item)
            bootstrap_observation = ObservationBatch(
                candidate_ids=tuple(str(item["candidate_id"]) for item in usable),
                features=np.asarray(
                    [
                        self.space.mapping_feature_vector(item["masks"])  # type: ignore[arg-type]
                        for item in usable
                    ],
                    dtype=np.float32,
                ).reshape((-1, self.space.mapping_feature_dimension)),
                terminal_stages=np.asarray(
                    [int(item["deep_depth"]) for item in usable], dtype=np.int16
                ),
            )
            observation = ObservationBatch(
                candidate_ids=(
                    *self.prior_observations.candidate_ids,
                    *bootstrap_observation.candidate_ids,
                ),
                features=np.concatenate(
                    (
                        self.prior_observations.features,
                        bootstrap_observation.features,
                    ),
                    axis=0,
                ),
                terminal_stages=np.concatenate(
                    (
                        self.prior_observations.terminal_stages,
                        bootstrap_observation.terminal_stages,
                    )
                ),
            )
            seen.add_many(observation.candidate_ids)
            backend.observe(observation, generation=-1)
            next_generation = 0
        _atomic_json(directory / "archive.json", archive.to_dict())
        _atomic_json(directory / "stats.json", stats)
        _atomic_json(directory / "metrics.json", backend.metrics())
        _atomic_json(
            state_path,
            {
                "schema_version": "mapping-lab-deep-arm-state-v1",
                "fingerprint": self.fingerprint,
                "arm": arm,
                "next_generation": next_generation,
            },
        )
        return directory, backend, archive, seen, stats, next_generation

    def run(
        self,
        *,
        restart: bool,
        rebuild_bootstrap: bool,
        generations: int | None,
        batch_size: int | None,
        bootstrap_limit: int | None = None,
    ) -> None:
        if rebuild_bootstrap and not restart:
            raise ValueError("--rebuild-bootstrap requires --restart")
        if restart:
            self._restart(rebuild_bootstrap=rebuild_bootstrap)
        self.output.mkdir(parents=True, exist_ok=True)
        target_generations = self.generations if generations is None else max(1, generations)
        target_batch = self.batch_size if batch_size is None else max(1, batch_size)
        _atomic_json(
            self.output / "experiment.json",
            {
                "schema_version": DEEP_EXPERIMENT_VERSION,
                "lab_semantics_version": LAB_SEMANTICS_VERSION,
                "fingerprint": self.fingerprint,
                "case_id": self.case_id,
                "arms": list(self.arms),
                "stage_names": list(DEEP_STAGES),
                "target_generations": target_generations,
                "batch_size_per_arm": target_batch,
                "prior_training_examples": len(
                    self.prior_observations.candidate_ids
                ),
            },
        )
        components: dict[str, tuple[Any, ...]] = {}
        try:
            with EvaluationWorker(
                self.root,
                self.case_id,
                self.evaluation,
                startup_timeout_seconds=self.startup_timeout,
            ) as worker:
                bootstrap = self._ensure_bootstrap(
                    worker, limit=bootstrap_limit
                )
                for arm in self.arms:
                    components[arm] = self._arm_components(arm, bootstrap)
                repair_evaluator = CompleteMappingEvaluator(
                    self.space,
                    {
                        **self.evaluation,
                        "enable_word_solver": False,
                    },
                )
                start = min(int(components[arm][5]) for arm in self.arms)
                print(
                    f"deep experiment case={self.case_id} "
                    f"generations={start}..{target_generations - 1} "
                    f"batch/arm={target_batch} bootstrap={len(bootstrap)} "
                    f"prior-training={len(self.prior_observations.candidate_ids)}",
                    flush=True,
                )
                for generation in range(start, target_generations):
                    ran = False
                    for arm in self.arms:
                        directory, backend, archive, seen, stats, next_generation = components[arm]
                        if generation < next_generation:
                            continue
                        ran = True
                        generation_started = time.perf_counter()
                        rng = random.Random(self.seed + generation * 1_000_003)
                        sampler = DeepSampler(
                            self.space,
                            arm,
                            pool_multiplier=int(self.sampling.get("pool_multiplier", 4)),
                            exploration_fraction=float(
                                self.sampling.get("exploration_fraction", 0.15)
                            ),
                            mutation_fraction=float(
                                self.sampling.get("mutation_fraction", 0.8)
                            ),
                            max_attempts=int(
                                self.sampling.get("max_attempts_per_candidate", 3000)
                            ),
                            local_neighbors_per_parent=int(
                                self.sampling.get(
                                    "local_neighbors_per_parent", 128
                                )
                            ),
                        )
                        proposal_started = time.perf_counter()
                        proposals = sampler.sample_batch(
                            backend,
                            archive,
                            rng,
                            target_batch,
                            seen,
                            repair_probe=(
                                repair_evaluator.repair_probe
                                if arm in {"local_topology", "length_repair"}
                                else None
                            ),
                        )
                        proposal_seconds = time.perf_counter() - proposal_started
                        contexts = {
                            item.candidate.candidate_id: item.context for item in proposals
                        }
                        evaluations: list[LabEvaluation] = []
                        old_max = int(stats["max_depth"])
                        evaluation_started = time.perf_counter()
                        for proposal in proposals:
                            evaluation = worker.evaluate(
                                proposal.candidate, self.hard_timeout
                            )
                            evaluations.append(evaluation)
                            archive.add(evaluation)
                            depth = deep_learning_depth(evaluation)
                            if depth > old_max:
                                old_max = depth
                                record = evaluation.to_dict(
                                    self.space.assignments.occurrence_names
                                )
                                record.update(
                                    {
                                        "generation": generation,
                                        "arm": arm,
                                        "deep_depth": depth,
                                        "deep_stage": DEEP_STAGES[depth],
                                        "deep_failure": deep_failure_name(evaluation),
                                    }
                                )
                                _append_jsonl(directory / "champions.jsonl", record)
                            if depth >= WORD_SOLVER_DEPTH:
                                record = evaluation.to_dict(
                                    self.space.assignments.occurrence_names
                                )
                                record.update(
                                    {
                                        "generation": generation,
                                        "arm": arm,
                                        "deep_depth": depth,
                                        "deep_stage": DEEP_STAGES[depth],
                                    }
                                )
                                _append_jsonl(directory / "word_candidates.jsonl", record)
                        # One durable transaction per batch.  At worst an abrupt
                        # crash repeats the unfinished batch, never an entire run.
                        seen.add_many(
                            [evaluation.candidate_id for evaluation in evaluations]
                        )
                        evaluation_seconds = time.perf_counter() - evaluation_started
                        usable = [
                            item
                            for item in evaluations
                            if item.status not in {"timeout", "evaluation_error"}
                        ]
                        observation = ObservationBatch(
                            candidate_ids=tuple(item.candidate_id for item in usable),
                            features=np.asarray(
                                [
                                    self.space.mapping_feature_vector(item.masks)
                                    for item in usable
                                ],
                                dtype=np.float32,
                            ).reshape((-1, self.space.mapping_feature_dimension)),
                            terminal_stages=np.asarray(
                                [deep_learning_depth(item) for item in usable],
                                dtype=np.int16,
                            ),
                        )
                        learning_started = time.perf_counter()
                        if arm == "uniform":
                            # The control arm never consults its model. Avoid
                            # spending roughly one third of its runtime training
                            # an unused network.
                            learning = {
                                "skipped": "uniform_control",
                                "training_examples": len(
                                    observation.candidate_ids
                                ),
                            }
                        else:
                            learning = backend.observe(
                                observation, generation=generation
                            )
                        learning_seconds = time.perf_counter() - learning_started
                        total_seconds = time.perf_counter() - generation_started
                        timing = {
                            "proposal": proposal_seconds,
                            "evaluation": evaluation_seconds,
                            "learning": learning_seconds,
                            "reporting": 0.0,
                            "total": total_seconds,
                        }
                        _update_stats(
                            stats,
                            evaluations,
                            contexts,
                            sampler.last_diagnostics,
                            timing,
                            generation=generation,
                        )
                        metrics = backend.metrics()
                        _atomic_json(directory / "stats.json", stats)
                        _atomic_json(directory / "metrics.json", metrics)
                        _atomic_json(directory / "archive.json", archive.to_dict())
                        _atomic_json(
                            directory / "state.json",
                            {
                                "schema_version": "mapping-lab-deep-arm-state-v1",
                                "fingerprint": self.fingerprint,
                                "arm": arm,
                                "next_generation": generation + 1,
                            },
                        )
                        depths = [deep_learning_depth(item) for item in usable]
                        progress = {
                            "schema_version": "mapping-lab-deep-progress-v1",
                            "generation": generation,
                            "arm": arm,
                            "evaluations": len(evaluations),
                            "mean_depth": sum(depths) / len(depths) if depths else 0.0,
                            "max_depth": max(depths, default=0),
                            "max_stage": DEEP_STAGES[max(depths, default=0)],
                            "failure_histogram": dict(
                                Counter(deep_failure_name(item) for item in usable)
                            ),
                            "sampling": sampler.last_diagnostics,
                            "learning": learning,
                            "model": metrics,
                            "archive_size": len(archive),
                            "timing_seconds": timing,
                        }
                        _append_jsonl(self.output / "progress.jsonl", progress)
                        components[arm] = (
                            directory,
                            backend,
                            archive,
                            seen,
                            stats,
                            generation + 1,
                        )
                        print(
                            f"g{generation} {arm}: mean={progress['mean_depth']:.3f} "
                            f"max={progress['max_stage']} archive={len(archive)} "
                            f"seen={len(seen)} wall={total_seconds:.1f}s",
                            flush=True,
                        )
                    if ran:
                        report_started = time.perf_counter()
                        write_deep_report(self.output, self.arms)
                        report_seconds = time.perf_counter() - report_started
                        # Reporting is shared by the generation and is kept in
                        # progress output; method comparisons use the measured
                        # per-arm proposal/evaluation/learning totals.
                        if report_seconds > 1.0:
                            print(
                                f"  report generation {generation}: {report_seconds:.1f}s",
                                flush=True,
                            )
                report = write_deep_report(self.output, self.arms)
                print(
                    "deep experiment complete: "
                    f"{self.output / 'report.md'}\n"
                    + json.dumps(report["comparisons"], indent=2, sort_keys=True),
                    flush=True,
                )
        finally:
            for component in components.values():
                seen = component[3]
                if isinstance(seen, PersistentSeen):
                    seen.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the exact pre-word curriculum experiment"
    )
    parser.add_argument(
        "--config",
        default="config/mapping_lab/wheel-6-repair.json",
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--generations", type=int)
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--rebuild-bootstrap", action="store_true")
    parser.add_argument(
        "--bootstrap-limit",
        type=int,
        help="diagnostic-only cap; a later run automatically fills the rest",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runner = DeepExperimentRunner.from_file(Path(args.root).resolve(), args.config)
    runner.run(
        restart=args.restart,
        rebuild_bootstrap=args.rebuild_bootstrap,
        generations=args.generations,
        batch_size=args.batch_size,
        bootstrap_limit=args.bootstrap_limit,
    )
    return 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
