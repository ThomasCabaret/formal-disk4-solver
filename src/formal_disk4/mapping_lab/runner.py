from __future__ import annotations

import json
import multiprocessing as mp
import queue
import random
import traceback
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .core import (
    LAB_SEMANTICS_VERSION,
    STAGES,
    CompleteMappingEvaluator,
    LabEvaluation,
    MappingCandidate,
    MappingSpace,
)
from .backend import LearningBackend, ObservationBatch
from .neural import NeuralLearningBackend
from .sampling import ProposalSampler, SamplingSettings
from .seeds import DeepSeedBuffer, DeepSeedEntry


OUTPUT_FILES = (
    "evaluations.jsonl",
    "generations.jsonl",
    "state.json",
    "deep_seeds.json",
    "summary.json",
    "champions.jsonl",
    "promising_mappings.jsonl",
    "timeout_mappings.jsonl",
    "model.npz",
    "dataset.npz",
)


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _append_jsonl(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, sort_keys=True) + "\n")
        stream.flush()


def _worker_main(
    root: str,
    case_id: str,
    evaluation_config: Mapping[str, Any],
    requests: Any,
    responses: Any,
) -> None:
    try:
        space = MappingSpace(Path(root), case_id)
        evaluator = CompleteMappingEvaluator(space, evaluation_config)
        responses.put(("ready", space.fingerprint))
    except BaseException:
        responses.put(("startup_error", traceback.format_exc()))
        return
    while True:
        candidate = requests.get()
        if candidate is None:
            return
        try:
            responses.put(("result", evaluator.evaluate(candidate)))
        except BaseException:
            responses.put(
                ("evaluation_error", candidate.candidate_id, traceback.format_exc())
            )


class EvaluationWorker:
    """Persistent evaluator with a killable per-candidate hard timeout."""

    def __init__(
        self,
        root: Path,
        case_id: str,
        evaluation_config: Mapping[str, Any],
        *,
        startup_timeout_seconds: float,
    ) -> None:
        self.root = root
        self.case_id = case_id
        self.evaluation_config = dict(evaluation_config)
        self.startup_timeout_seconds = max(1.0, float(startup_timeout_seconds))
        self._context = mp.get_context("spawn")
        self._process: mp.Process | None = None
        self._requests: Any = None
        self._responses: Any = None
        self._start()

    def _start(self) -> None:
        self._requests = self._context.Queue()
        self._responses = self._context.Queue()
        self._process = self._context.Process(
            target=_worker_main,
            args=(
                str(self.root),
                self.case_id,
                self.evaluation_config,
                self._requests,
                self._responses,
            ),
            daemon=True,
        )
        self._process.start()
        try:
            message = self._responses.get(timeout=self.startup_timeout_seconds)
        except queue.Empty as exc:
            self._terminate()
            raise RuntimeError("mapping evaluator worker startup timed out") from exc
        if message[0] != "ready":
            self._terminate()
            raise RuntimeError(f"mapping evaluator failed to start:\n{message[1]}")

    def evaluate(
        self, candidate: MappingCandidate, timeout_seconds: float
    ) -> LabEvaluation:
        seconds = max(0.001, float(timeout_seconds))
        if self._process is None or not self._process.is_alive():
            self._terminate()
            self._start()
        self._requests.put(candidate)
        try:
            message = self._responses.get(timeout=seconds)
        except queue.Empty:
            self._terminate()
            self._start()
            return LabEvaluation.timeout(candidate, seconds)
        if message[0] == "result":
            return message[1]
        self._terminate()
        self._start()
        detail = message[-1] if message else "unknown worker failure"
        return LabEvaluation.error(candidate, str(detail))

    def _terminate(self) -> None:
        process = self._process
        if process is not None and process.is_alive():
            process.terminate()
            process.join(timeout=5.0)
            if process.is_alive():
                process.kill()
                process.join(timeout=5.0)
        for channel in (self._requests, self._responses):
            if channel is not None:
                channel.close()
                channel.join_thread()
        self._process = None
        self._requests = None
        self._responses = None

    def close(self) -> None:
        if self._process is not None and self._process.is_alive():
            self._requests.put(None)
            self._process.join(timeout=5.0)
        self._terminate()

    def __enter__(self) -> "EvaluationWorker":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


@dataclass(frozen=True)
class CampaignResult:
    output_directory: Path
    generations_completed: int
    evaluations: int
    first_mean_stage: float
    last_mean_stage: float
    first_max_stage: int
    last_max_stage: int
    learned_mean_stage: float | None
    uniform_mean_stage: float | None
    learned_advantage: float | None


class MappingLabRunner:
    def __init__(self, root: Path | str, config: Mapping[str, Any]) -> None:
        self.root = Path(root).resolve()
        self.config = dict(config)
        self.case_id = str(self.config["case_id"])
        self.space = MappingSpace(self.root, self.case_id)
        output_config = dict(self.config.get("output", {}))
        output_value = str(
            output_config.get(
                "directory", f"output/mapping_lab/{self.case_id}"
            )
        )
        candidate_output = Path(output_value)
        if not candidate_output.is_absolute():
            candidate_output = self.root / candidate_output
        self.output = candidate_output.resolve()
        try:
            self.output.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("mapping lab output must be inside the project root") from exc
        if self.output == self.root:
            raise ValueError("mapping lab output cannot be the project root")

        sampling = dict(self.config.get("sampling", {}))
        learning = dict(self.config.get("learning", {}))
        backend = dict(self.config.get("backend", {}))
        evaluation = dict(self.config.get("evaluation", {}))
        self.backend_type = str(backend.get("type", "neural_stage_curriculum"))
        if self.backend_type != "neural_stage_curriculum":
            raise ValueError(
                f"unsupported mapping-lab backend {self.backend_type!r}; "
                "only 'neural_stage_curriculum' is retained"
            )
        self.backend_config = backend
        self.seed = int(sampling.get("seed", 20260802))
        self.generations = max(1, int(sampling.get("generations", 8)))
        self.batch_size = max(1, int(sampling.get("batch_size", 32)))
        sampling_settings = SamplingSettings(
            uniform_fraction=min(
                1.0, max(0.0, float(sampling.get("uniform_fraction", 0.2)))
            ),
            pool_multiplier=max(1, int(sampling.get("pool_multiplier", 3))),
            pool_exploration_fraction=min(
                1.0,
                max(0.0, float(sampling.get("pool_exploration_fraction", 0.15))),
            ),
            pool_local_fraction=min(
                1.0, max(0.0, float(sampling.get("pool_local_fraction", 0.35)))
            ),
            pool_broad_fraction=min(
                1.0, max(0.0, float(sampling.get("pool_broad_fraction", 0.35)))
            ),
            broad_mutation_prefix_fraction=min(
                1.0,
                max(0.0, float(sampling.get("broad_mutation_prefix_fraction", 0.6))),
            ),
            max_attempts_per_candidate=max(
                1, int(sampling.get("max_attempts_per_candidate", 2000))
            ),
        )
        self.sampler = ProposalSampler(self.space, sampling_settings)
        raw_exclusions = sampling.get("exclude_evaluations", [])
        exclusion_values = (
            raw_exclusions
            if isinstance(raw_exclusions, list)
            else [raw_exclusions]
            if raw_exclusions
            else []
        )
        self.excluded_evaluations = tuple(
            self._project_path(str(value)) for value in exclusion_values
        )
        self.seed_capacity = max(1, int(learning.get("seed_capacity", 1024)))
        self.seed_minimum_stage_index = max(
            0, int(learning.get("seed_minimum_stage_index", 8))
        )
        self.archive_minimum_stage_index = max(
            0, int(learning.get("archive_minimum_stage_index", 8))
        )
        raw_seed_archives = learning.get("seed_archives", [])
        seed_archive_values = (
            raw_seed_archives
            if isinstance(raw_seed_archives, list)
            else [raw_seed_archives]
            if raw_seed_archives
            else []
        )
        self.seed_archives = tuple(
            self._project_path(str(value)) for value in seed_archive_values
        )
        raw_bootstrap = backend.get("bootstrap_evaluations", [])
        bootstrap_values = (
            raw_bootstrap
            if isinstance(raw_bootstrap, list)
            else [raw_bootstrap]
            if raw_bootstrap
            else []
        )
        self.backend_bootstrap_evaluations = tuple(
            self._project_path(str(value)) for value in bootstrap_values
        )
        self.evaluation_config = evaluation
        self.hard_timeout_seconds = max(
            0.001, float(evaluation.get("hard_timeout_seconds", 10.0))
        )
        self.startup_timeout_seconds = max(
            1.0, float(evaluation.get("startup_timeout_seconds", 60.0))
        )

    @classmethod
    def from_file(cls, root: Path | str, path: Path | str) -> "MappingLabRunner":
        config_path = Path(path)
        if not config_path.is_absolute():
            config_path = Path(root) / config_path
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("mapping lab configuration must be a JSON object")
        return cls(root, payload)

    def run(
        self,
        *,
        restart: bool = False,
        generations: int | None = None,
        batch_size: int | None = None,
    ) -> CampaignResult:
        target_generations = self.generations if generations is None else max(1, generations)
        target_batch_size = self.batch_size if batch_size is None else max(1, batch_size)
        self.output.mkdir(parents=True, exist_ok=True)
        if restart:
            for name in OUTPUT_FILES:
                path = self.output / name
                if path.exists():
                    path.unlink()

        start_generation = self._load_state()
        seeds = self._load_seeds()
        if start_generation == 0 and not seeds and self.seed_archives:
            bootstrap = Counter[str]()
            for archive_path in self.seed_archives:
                bootstrap.update(seeds.load_archive(archive_path, space=self.space))
            print(
                "mapping-lab seed bootstrap: "
                f"scanned={bootstrap['scanned']} eligible={bootstrap['eligible']} "
                f"retained={len(seeds)} invalid={bootstrap['invalid']}",
                flush=True,
            )
            self._save_seeds(seeds)
        seen = self._load_seen_candidates()
        seed_candidate_ids = {entry.candidate_id for entry in seeds.entries}
        seen["learned"].update(seed_candidate_ids)
        seen["uniform"].update(seed_candidate_ids)
        best_stage_index = self._load_best_stage_index()
        generation_summaries = self._load_generation_summaries()
        evaluations_written = 0
        backend, dataset_summary = self._load_backend()
        print(
            f"mapping-lab backend={backend.name}: "
            f"scanned={dataset_summary['scanned']} "
            f"retained={dataset_summary['retained']} "
            f"train={dataset_summary['training']} "
            f"validation={dataset_summary['validation']}",
            flush=True,
        )

        if start_generation >= target_generations:
            campaign = self._campaign_result(generation_summaries, 0)
            self._write_campaign_summary(campaign, evaluations_this_run=0)
            print(
                f"mapping-lab already complete at generation {start_generation}; "
                f"target={target_generations}",
                flush=True,
            )
            return campaign

        print(
            f"mapping-lab case={self.case_id} generations={start_generation}.."
            f"{target_generations - 1} batch={target_batch_size} "
            f"timeout={self.hard_timeout_seconds:g}s",
            flush=True,
        )
        with EvaluationWorker(
            self.root,
            self.case_id,
            self.evaluation_config,
            startup_timeout_seconds=self.startup_timeout_seconds,
        ) as worker:
            for generation in range(start_generation, target_generations):
                rng = random.Random(self.seed + generation * 1_000_003)
                candidates = self.sampler.sample_batch(
                    backend,
                    rng,
                    target_batch_size,
                    seen,
                    seeds=seeds,
                )
                evaluations: list[LabEvaluation] = []
                for index, candidate in enumerate(candidates, start=1):
                    evaluation = worker.evaluate(
                        candidate, self.hard_timeout_seconds
                    )
                    evaluations.append(evaluation)
                    evaluations_written += 1
                    record = evaluation.to_dict(
                        self.space.assignments.occurrence_names
                    )
                    record.update(
                        {
                            "lab_semantics_version": LAB_SEMANTICS_VERSION,
                            "case_id": self.case_id,
                            "fingerprint": self.space.fingerprint,
                            "generation": generation,
                            "sample_index": index - 1,
                        }
                    )
                    _append_jsonl(self.output / "evaluations.jsonl", record)
                    if evaluation.stage_index >= self.archive_minimum_stage_index:
                        promising_record = dict(record)
                        promising_record["archive_kind"] = "promising_mapping"
                        _append_jsonl(
                            self.output / "promising_mappings.jsonl",
                            promising_record,
                        )
                    if evaluation.status == "timeout":
                        timeout_record = dict(record)
                        timeout_record["archive_kind"] = "evaluation_timeout"
                        _append_jsonl(
                            self.output / "timeout_mappings.jsonl",
                            timeout_record,
                        )
                    if evaluation.stage_index > best_stage_index:
                        best_stage_index = evaluation.stage_index
                        champion_record = dict(record)
                        champion_record["archive_kind"] = "new_depth_record"
                        _append_jsonl(
                            self.output / "champions.jsonl", champion_record
                        )
                    seeds.add_evaluation(evaluation)
                    print(
                        f"  g{generation} {index}/{len(candidates)} "
                        f"{evaluation.terminal_stage}: {evaluation.reason}",
                        flush=True,
                    )

                summary = self._summarize_generation(generation, evaluations)
                seeds.finalize()
                usable = [
                    item
                    for item in evaluations
                    if item.status not in {"timeout", "evaluation_error"}
                ]
                observation = ObservationBatch(
                    candidate_ids=tuple(item.candidate_id for item in usable),
                    features=np.asarray(
                        [self.space.mapping_feature_vector(item.masks) for item in usable],
                        dtype=np.float32,
                    ).reshape((-1, self.space.mapping_feature_dimension)),
                    terminal_stages=np.asarray(
                        [item.stage_index for item in usable], dtype=np.int16
                    ),
                )
                learning_metrics = backend.observe(observation, generation=generation)
                summary["learning_metrics"] = learning_metrics
                update_reason = (
                    f"{backend.name}:steps="
                    f"{int(self.backend_config.get('steps_per_generation', 4))},"
                    f"dataset={learning_metrics.get('training_examples', 0)}"
                )
                summary["learning_update"] = update_reason
                summary["seed_buffer_size"] = len(seeds)
                summary["seed_deepest_stage_index"] = seeds.deepest_stage_index
                _append_jsonl(self.output / "generations.jsonl", summary)
                generation_summaries.append(summary)
                self._save_state(generation + 1)
                self._save_seeds(seeds)
                print(
                    f"generation {generation}: mean-stage="
                    f"{summary['mean_stage_index']:.3f} max="
                    f"{summary['max_stage_name']} timeouts={summary['timeouts']} "
                    f"learning={update_reason}",
                    flush=True,
                )

        campaign = self._campaign_result(
            generation_summaries, evaluations_written
        )
        self._write_campaign_summary(
            campaign, evaluations_this_run=evaluations_written
        )
        return campaign

    def _write_campaign_summary(
        self,
        campaign: CampaignResult,
        *,
        evaluations_this_run: int,
    ) -> None:
        _atomic_write_json(
            self.output / "summary.json",
            {
                "schema_version": "mapping-lab-summary-v1",
                "case_id": self.case_id,
                "fingerprint": self.space.fingerprint,
                "generations_completed": campaign.generations_completed,
                "evaluations_this_run": evaluations_this_run,
                "first_mean_stage": campaign.first_mean_stage,
                "last_mean_stage": campaign.last_mean_stage,
                "first_max_stage": campaign.first_max_stage,
                "last_max_stage": campaign.last_max_stage,
                "post_warmup_learned_mean_stage": campaign.learned_mean_stage,
                "post_warmup_uniform_mean_stage": campaign.uniform_mean_stage,
                "post_warmup_learned_advantage": campaign.learned_advantage,
                "output_directory": str(self.output),
            },
        )

    def _load_backend(self) -> tuple[LearningBackend, dict[str, int]]:
        return NeuralLearningBackend.load_or_create(
            self.output,
            input_dimension=self.space.mapping_feature_dimension,
            transition_stages=tuple(range(4, len(STAGES))),
            config=self.backend_config,
            seed=self.seed,
            feature_builder=self.space.mapping_feature_vector,
            bootstrap_paths=self.backend_bootstrap_evaluations,
        )

    def _summarize_generation(
        self,
        generation: int,
        evaluations: Sequence[LabEvaluation],
    ) -> dict[str, object]:
        stages = Counter(item.terminal_stage for item in evaluations)
        statuses = Counter(item.status for item in evaluations)
        strategies = Counter(item.proposal_strategy for item in evaluations)
        usable = [
            item
            for item in evaluations
            if item.status not in {"timeout", "evaluation_error"}
        ]
        indexes = [item.stage_index for item in usable]
        max_index = max(indexes, default=0)
        reached = {
            stage: sum(item.stage_index >= index for item in usable)
            for index, stage in enumerate(STAGES)
        }
        source_comparison: dict[str, dict[str, object]] = {}
        for source in ("learned", "uniform"):
            source_items = [
                item for item in usable if item.proposal_source == source
            ]
            source_indexes = [item.stage_index for item in source_items]
            source_comparison[source] = {
                "count": len(source_items),
                "mean_stage_index": (
                    sum(source_indexes) / len(source_indexes)
                    if source_indexes
                    else None
                ),
                "max_stage_index": max(source_indexes, default=None),
                "stage_reached_counts": {
                    stage: sum(item.stage_index >= index for item in source_items)
                    for index, stage in enumerate(STAGES)
                },
            }
        strategy_comparison: dict[str, dict[str, object]] = {}
        strategy_names = sorted(
            {
                "model_random_pool",
                "model_seed_local",
                "model_seed_broad",
                "uniform_control",
            }
            | {item.proposal_strategy for item in usable}
        )
        for strategy in strategy_names:
            strategy_items = [
                item for item in usable if item.proposal_strategy == strategy
            ]
            strategy_indexes = [item.stage_index for item in strategy_items]
            strategy_comparison[strategy] = {
                "count": len(strategy_items),
                "mean_stage_index": (
                    sum(strategy_indexes) / len(strategy_indexes)
                    if strategy_indexes
                    else None
                ),
                "max_stage_index": max(strategy_indexes, default=None),
                "terminal_stage_histogram": dict(
                    sorted(
                        Counter(
                            item.terminal_stage for item in strategy_items
                        ).items()
                    )
                ),
                "stage_reached_counts": {
                    stage: sum(
                        item.stage_index >= index for item in strategy_items
                    )
                    for index, stage in enumerate(STAGES)
                },
            }
        mean_stage = sum(indexes) / len(indexes) if indexes else 0.0
        return {
            "schema_version": "mapping-lab-generation-v1",
            "generation": generation,
            "evaluations": len(evaluations),
            "usable_evaluations": len(usable),
            "timeouts": statuses.get("timeout", 0),
            "errors": statuses.get("evaluation_error", 0),
            "mean_stage_index": mean_stage,
            "max_stage_index": max_index,
            "max_stage_name": STAGES[max_index],
            "terminal_stage_histogram": dict(sorted(stages.items())),
            "status_histogram": dict(sorted(statuses.items())),
            "proposal_strategy_histogram": dict(sorted(strategies.items())),
            "sampling_diagnostics": dict(self.sampler.last_diagnostics),
            "stage_reached_counts": reached,
            "proposal_source_comparison": source_comparison,
            "proposal_strategy_comparison": strategy_comparison,
        }

    def _load_state(self) -> int:
        path = self.output / "state.json"
        if not path.exists():
            return 0
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("fingerprint") != self.space.fingerprint:
            raise ValueError(
                "existing mapping-lab state belongs to a different case/config; "
                "use --restart or another output directory"
            )
        if payload.get("backend") != self.backend_type:
            raise ValueError("stored mapping-lab state uses another learning backend")
        return int(payload["next_generation"])

    def _save_state(self, next_generation: int) -> None:
        _atomic_write_json(
            self.output / "state.json",
            {
                "schema_version": "mapping-lab-state-v1",
                "lab_semantics_version": LAB_SEMANTICS_VERSION,
                "case_id": self.case_id,
                "fingerprint": self.space.fingerprint,
                "backend": self.backend_type,
                "next_generation": int(next_generation),
            },
        )

    def _load_seeds(self) -> DeepSeedBuffer:
        path = self.output / "deep_seeds.json"
        if not path.exists():
            seeds = DeepSeedBuffer(
                capacity=self.seed_capacity,
                minimum_stage_index=self.seed_minimum_stage_index,
            )
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("fingerprint") != self.space.fingerprint:
                raise ValueError(
                    "existing mapping-lab seeds belong to a different case/config; "
                    "use --restart or another output directory"
                )
            seeds = DeepSeedBuffer.from_dict(payload["buffer"])
            if (
                seeds.capacity != self.seed_capacity
                or seeds.minimum_stage_index != self.seed_minimum_stage_index
            ):
                raise ValueError(
                    "stored seed settings differ from the current configuration; "
                    "use --restart or another output directory"
                )
        promising = self.output / "promising_mappings.jsonl"
        if promising.exists():
            with promising.open("r", encoding="utf-8") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    try:
                        seeds.add(DeepSeedEntry.from_dict(json.loads(line)))
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                        continue
            seeds.finalize()
        return seeds

    def _save_seeds(self, seeds: DeepSeedBuffer) -> None:
        _atomic_write_json(
            self.output / "deep_seeds.json",
            {
                "schema_version": "mapping-lab-deep-seeds-v1",
                "lab_semantics_version": LAB_SEMANTICS_VERSION,
                "case_id": self.case_id,
                "fingerprint": self.space.fingerprint,
                "buffer": seeds.to_dict(),
            },
        )

    def _load_seen_candidates(self) -> dict[str, set[str]]:
        path = self.output / "evaluations.jsonl"
        seen = {"learned": set(), "uniform": set()}
        if path.exists():
            self._merge_seen_evaluations(path, seen, preserve_source=True)
        for exclusion in self.excluded_evaluations:
            self._merge_seen_evaluations(exclusion, seen, preserve_source=False)
        return seen

    @staticmethod
    def _merge_seen_evaluations(
        path: Path,
        seen: dict[str, set[str]],
        *,
        preserve_source: bool,
    ) -> None:
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    try:
                        payload = json.loads(line)
                        candidate_id = str(payload["candidate_id"])
                    except (json.JSONDecodeError, KeyError, TypeError):
                        continue
                    if preserve_source:
                        source = str(payload.get("proposal_source", "learned"))
                        if source in seen:
                            seen[source].add(candidate_id)
                    else:
                        seen["learned"].add(candidate_id)
                        seen["uniform"].add(candidate_id)

    def _load_best_stage_index(self) -> int:
        path = self.output / "champions.jsonl"
        if not path.exists():
            return -1
        best = -1
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    best = max(best, int(json.loads(line).get("stage_index", -1)))
        return best

    def _project_path(self, value: str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = self.root / path
        resolved = path.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("mapping lab data paths must be inside the project root") from exc
        return resolved

    def _load_generation_summaries(self) -> list[dict[str, object]]:
        path = self.output / "generations.jsonl"
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as stream:
            return [json.loads(line) for line in stream if line.strip()]

    def _campaign_result(
        self,
        summaries: Sequence[Mapping[str, object]],
        evaluations: int,
    ) -> CampaignResult:
        if not summaries:
            return CampaignResult(
                self.output, 0, evaluations, 0.0, 0.0, 0, 0, None, None, None
            )
        first = summaries[0]
        last = summaries[-1]
        learned, uniform = self._aggregate_source_comparison(summaries[1:])
        advantage = (
            learned - uniform
            if learned is not None and uniform is not None
            else None
        )
        return CampaignResult(
            output_directory=self.output,
            generations_completed=len(summaries),
            evaluations=evaluations,
            first_mean_stage=float(first["mean_stage_index"]),
            last_mean_stage=float(last["mean_stage_index"]),
            first_max_stage=int(first["max_stage_index"]),
            last_max_stage=int(last["max_stage_index"]),
            learned_mean_stage=learned,
            uniform_mean_stage=uniform,
            learned_advantage=advantage,
        )

    @staticmethod
    def _aggregate_source_comparison(
        summaries: Sequence[Mapping[str, object]],
    ) -> tuple[float | None, float | None]:
        means: dict[str, float | None] = {}
        for source in ("learned", "uniform"):
            weighted_sum = 0.0
            count = 0
            for summary in summaries:
                comparison = summary["proposal_source_comparison"]
                assert isinstance(comparison, Mapping)
                item = comparison[source]
                assert isinstance(item, Mapping)
                item_count = int(item["count"])
                item_mean = item["mean_stage_index"]
                if item_count and item_mean is not None:
                    weighted_sum += item_count * float(item_mean)
                    count += item_count
            means[source] = weighted_sum / count if count else None
        return means["learned"], means["uniform"]
