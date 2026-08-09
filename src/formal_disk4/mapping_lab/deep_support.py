from __future__ import annotations

import json
import math
import random
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from formal_disk4.preword import PREWORD_LINEAR_CURRICULUM_STAGES

from .backend import LearningBackend, ObservationBatch
from .core import (
    STAGES,
    LabEvaluation,
    LengthRepairProbe,
    MappingCandidate,
    MappingSpace,
)
from .neural import NeuralLearningBackend, NeuralTrainingDataset


DEEP_STAGES = (
    *STAGES[:9],
    *(f"preword_{name}" for name in PREWORD_LINEAR_CURRICULUM_STAGES),
    "word_solver",
    "word_family",
)
CURRICULUM_OFFSET = 9
WORD_SOLVER_DEPTH = CURRICULUM_OFFSET + len(PREWORD_LINEAR_CURRICULUM_STAGES)


def deep_learning_depth(evaluation: LabEvaluation | Mapping[str, object]) -> int:
    if isinstance(evaluation, LabEvaluation):
        stage_index = evaluation.stage_index
        diagnostics = evaluation.diagnostics
    else:
        stage_index = int(evaluation["stage_index"])
        raw = evaluation.get("diagnostics", {})
        diagnostics = raw if isinstance(raw, Mapping) else {}
    if stage_index < 8:
        return stage_index
    if stage_index >= 9:
        return WORD_SOLVER_DEPTH + (stage_index - 9)
    curriculum = diagnostics.get("preword_linear_curriculum")
    passed = 0
    if isinstance(curriculum, Mapping):
        passed = int(curriculum.get("passed_steps", 0))
    return min(WORD_SOLVER_DEPTH, 8 + max(0, passed))


def deep_failure_name(evaluation: LabEvaluation | Mapping[str, object]) -> str:
    depth = deep_learning_depth(evaluation)
    if depth + 1 < len(DEEP_STAGES):
        return DEEP_STAGES[depth + 1]
    return "complete"


class PersistentSeen:
    """Exact candidate de-duplication that survives process restarts."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS seen "
            "(candidate_id TEXT PRIMARY KEY) WITHOUT ROWID"
        )
        self.connection.commit()
        self._identifiers = {
            str(row[0])
            for row in self.connection.execute("SELECT candidate_id FROM seen")
        }

    def __contains__(self, candidate_id: object) -> bool:
        return str(candidate_id) in self._identifiers

    def add(self, candidate_id: str) -> None:
        identifier = str(candidate_id)
        self.connection.execute(
            "INSERT OR IGNORE INTO seen(candidate_id) VALUES (?)",
            (identifier,),
        )
        self.connection.commit()
        self._identifiers.add(identifier)

    def add_many(self, candidate_ids: Sequence[str]) -> None:
        identifiers = tuple(str(value) for value in candidate_ids)
        self.connection.executemany(
            "INSERT OR IGNORE INTO seen(candidate_id) VALUES (?)",
            ((value,) for value in identifiers),
        )
        self.connection.commit()
        self._identifiers.update(identifiers)

    def __len__(self) -> int:
        return len(self._identifiers)

    def close(self) -> None:
        self.connection.close()


class DeepScoringBackend:
    """Neural backend with a selectable rare-event ranking objective."""

    name = "deep_neural_curriculum"

    def __init__(self, backend: NeuralLearningBackend, policy: str) -> None:
        if policy not in {"expected", "deepest"}:
            raise ValueError(f"unsupported deep scoring policy {policy!r}")
        self.backend = backend
        self.policy = policy

    def score(self, features: np.ndarray) -> np.ndarray:
        if self.policy == "expected":
            return self.backend.score(features)
        probabilities = self.backend.model.predict_probabilities(features)
        active = np.flatnonzero(self.backend.model.active_heads)
        target_head = int(active[-1]) if len(active) else 0
        # The search objective is one rare event, not average filter depth:
        # maximize P(reach the deepest transition for which both classes exist).
        log_reach = np.log(
            np.clip(probabilities[:, : target_head + 1], 1e-9, 1.0)
        ).sum(axis=1)
        expected_tiebreak = np.asarray(self.backend.score(features), dtype=np.float64)
        return log_reach + 1e-6 * expected_tiebreak

    def observe(
        self, batch: ObservationBatch, *, generation: int
    ) -> dict[str, Any]:
        return self.backend.observe(batch, generation=generation)

    def metrics(self) -> dict[str, Any]:
        result = dict(self.backend.metrics())
        active = np.flatnonzero(self.backend.model.active_heads)
        head = int(active[-1]) if len(active) else 0
        result["scoring_policy"] = self.policy
        result["scoring_target_depth"] = int(
            self.backend.model.transition_stages[head]
        )
        result["scoring_target_name"] = DEEP_STAGES[
            int(self.backend.model.transition_stages[head])
        ]
        return result

    def save(self) -> None:
        self.backend.save()


@dataclass(frozen=True)
class DeepEntry:
    candidate_id: str
    masks: tuple[int, ...]
    depth: int
    failure: str
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "masks": list(self.masks),
            "depth": self.depth,
            "failure": self.failure,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "DeepEntry":
        return cls(
            str(payload["candidate_id"]),
            tuple(int(value) for value in payload["masks"]),  # type: ignore[arg-type]
            int(payload["depth"]),
            str(payload["failure"]),
            str(payload["reason"]),
        )


class DeepArchive:
    def __init__(self, capacity: int = 5000, per_failure: int = 2000) -> None:
        self.capacity = max(1, int(capacity))
        self.per_failure = max(1, int(per_failure))
        self._entries: dict[str, DeepEntry] = {}

    @property
    def entries(self) -> tuple[DeepEntry, ...]:
        return tuple(
            sorted(
                self._entries.values(),
                key=lambda item: (-item.depth, item.failure, item.candidate_id),
            )
        )

    def __len__(self) -> int:
        return len(self._entries)

    def add(self, evaluation: LabEvaluation | Mapping[str, object]) -> bool:
        if isinstance(evaluation, LabEvaluation):
            candidate_id = evaluation.candidate_id
            masks = evaluation.masks
            reason = evaluation.reason
        else:
            candidate_id = str(evaluation["candidate_id"])
            masks = tuple(int(value) for value in evaluation["masks"])  # type: ignore[arg-type]
            reason = str(evaluation.get("reason", ""))
        depth = deep_learning_depth(evaluation)
        if depth < 8:
            return False
        entry = DeepEntry(
            candidate_id,
            tuple(masks),
            depth,
            deep_failure_name(evaluation),
            reason,
        )
        self._entries[candidate_id] = entry
        self._trim()
        return candidate_id in self._entries

    def choose(self, rng: random.Random) -> DeepEntry | None:
        entries = self.entries
        if not entries:
            return None
        if rng.random() < 0.75:
            deepest = entries[0].depth
            choices = tuple(item for item in entries if item.depth == deepest)
        else:
            failures: dict[str, list[DeepEntry]] = {}
            for entry in entries:
                failures.setdefault(entry.failure, []).append(entry)
            choices = tuple(rng.choice(tuple(failures.values())))
        return rng.choice(choices)

    def _trim(self) -> None:
        grouped: dict[str, list[DeepEntry]] = {}
        for entry in self._entries.values():
            grouped.setdefault(entry.failure, []).append(entry)
        retained: list[DeepEntry] = []
        for entries in grouped.values():
            retained.extend(
                sorted(entries, key=lambda item: (-item.depth, item.candidate_id))[
                    : self.per_failure
                ]
            )
        retained = sorted(
            retained, key=lambda item: (-item.depth, item.failure, item.candidate_id)
        )[: self.capacity]
        self._entries = {entry.candidate_id: entry for entry in retained}

    def to_dict(self) -> dict[str, object]:
        return {
            "capacity": self.capacity,
            "per_failure": self.per_failure,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "DeepArchive":
        result = cls(int(payload["capacity"]), int(payload["per_failure"]))
        raw = payload.get("entries", ())
        if isinstance(raw, Sequence):
            for item in raw:
                if isinstance(item, Mapping):
                    entry = DeepEntry.from_dict(item)
                    result._entries[entry.candidate_id] = entry
        result._trim()
        return result


@dataclass(frozen=True)
class DeepProposalContext:
    parent_id: str | None = None
    parent_depth: int | None = None
    parent_failure: str | None = None
    operator: str | None = None
    parent_repair_score: float | None = None
    proposal_repair_score: float | None = None
    proposal_preword_topology: bool | None = None
    proposal_positive_lengths: bool | None = None


@dataclass(frozen=True)
class DeepProposal:
    candidate: MappingCandidate
    context: DeepProposalContext


class DeepSampler:
    MODES = (
        "uniform",
        "expected_ranker",
        "deep_ranker",
        "deep_mutation",
        "local_topology",
        "length_repair",
    )

    def __init__(
        self,
        space: MappingSpace,
        mode: str,
        *,
        pool_multiplier: int,
        exploration_fraction: float,
        mutation_fraction: float,
        max_attempts: int,
        local_neighbors_per_parent: int = 128,
    ) -> None:
        if mode not in self.MODES:
            raise ValueError(f"unknown deep sampler mode {mode!r}")
        self.space = space
        self.mode = mode
        self.pool_multiplier = max(1, int(pool_multiplier))
        self.exploration_fraction = min(1.0, max(0.0, exploration_fraction))
        self.mutation_fraction = min(1.0, max(0.0, mutation_fraction))
        self.max_attempts = max(1, int(max_attempts))
        self.local_neighbors_per_parent = max(1, int(local_neighbors_per_parent))
        self.last_diagnostics: dict[str, int] = {}

    def sample_batch(
        self,
        backend: LearningBackend,
        archive: DeepArchive,
        rng: random.Random,
        batch_size: int,
        seen: PersistentSeen,
        repair_probe: Callable[[MappingCandidate], LengthRepairProbe] | None = None,
    ) -> list[DeepProposal]:
        diagnostics: Counter[str] = Counter()
        target = batch_size if self.mode == "uniform" else batch_size * self.pool_multiplier
        pool: list[DeepProposal] = []
        pool_ids: set[str] = set()
        probe_cache: dict[str, LengthRepairProbe] = {}

        def probe(candidate: MappingCandidate) -> LengthRepairProbe | None:
            if repair_probe is None:
                return None
            cached = probe_cache.get(candidate.candidate_id)
            if cached is not None:
                return cached
            try:
                result = repair_probe(candidate)
            except Exception:
                diagnostics["probe.errors"] += 1
                return None
            probe_cache[candidate.candidate_id] = result
            diagnostics["probe.calls"] += 1
            diagnostics[
                "probe.complete_topology_feasible"
                if result.complete_topology_feasible
                else "probe.complete_topology_rejected"
            ] += 1
            diagnostics[
                "probe.preword_topology_feasible"
                if result.preword_topology_feasible
                else "probe.preword_topology_rejected"
            ] += 1
            if result.positive_lengths_feasible:
                diagnostics["probe.positive_lengths_feasible"] += 1
            return result

        def retain(
            candidate: MappingCandidate,
            *,
            parent: DeepEntry | None = None,
            operator: str | None = None,
        ) -> None:
            strategy = candidate.proposal_strategy
            if candidate.candidate_id in seen or candidate.candidate_id in pool_ids:
                diagnostics[f"duplicate.{strategy}"] += 1
                return
            candidate_probe = probe(candidate)
            parent_probe = None
            if parent is not None and repair_probe is not None:
                try:
                    parent_candidate = self.space.candidate_from_masks(
                        parent.masks,
                        proposal_source="repair_parent",
                        proposal_strategy="repair_parent",
                    )
                except (TypeError, ValueError):
                    diagnostics["probe.invalid_parent"] += 1
                else:
                    parent_probe = probe(parent_candidate)
            pool_ids.add(candidate.candidate_id)
            pool.append(
                DeepProposal(
                    candidate,
                    DeepProposalContext(
                        parent.candidate_id if parent else None,
                        parent.depth if parent else None,
                        parent.failure if parent else None,
                        operator,
                        self._repair_scalar(parent_probe),
                        self._repair_scalar(candidate_probe),
                        (
                            candidate_probe.preword_topology_feasible
                            if candidate_probe is not None
                            else None
                        ),
                        (
                            candidate_probe.positive_lengths_feasible
                            if candidate_probe is not None
                            else None
                        ),
                    ),
                )
            )
            diagnostics[f"generated.{strategy}"] += 1

        local_mode = self.mode in {"local_topology", "length_repair"}
        if local_mode and archive:
            parent_attempts = 0
            parent_budget = min(
                target * self.max_attempts,
                max(target * 8, len(archive) * 4),
            )
            while len(pool) < target and parent_attempts < parent_budget:
                parent_attempts += 1
                parent = archive.choose(rng)
                if parent is None:
                    break
                diagnostics["attempts.local_parent"] += 1
                neighbors = self.space.local_neighbors(
                    parent.masks,
                    rng,
                    limit=min(
                        self.local_neighbors_per_parent,
                        max(1, target - len(pool)),
                    ),
                    proposal_source=self.mode,
                )
                if not neighbors:
                    diagnostics["invalid.local_parent"] += 1
                    continue
                for candidate, operator in neighbors:
                    diagnostics[f"attempts.{operator}"] += 1
                    retain(candidate, parent=parent, operator=operator)
                    if len(pool) >= target:
                        break

        # Keep a well-defined fallback for an exhausted local neighborhood and
        # for the legacy/global arms. It also preserves a small path to wholly
        # new fertile regions.
        for _ in range(target * self.max_attempts):
            if len(pool) >= target:
                break
            parent = None
            if (
                self.mode == "deep_mutation"
                and len(archive)
                and rng.random() < self.mutation_fraction
            ):
                parent = archive.choose(rng)
            strategy = "deep_mutation" if parent is not None else "random_pool"
            if self.mode == "uniform":
                strategy = "uniform"
            elif local_mode:
                strategy = "fallback_random"
            diagnostics[f"attempts.{strategy}"] += 1
            candidate = self.space.sample(
                rng,
                reference_masks=parent.masks if parent is not None else None,
                mutation_prefix_fraction=(
                    0.55 if parent is not None and rng.random() < 0.35 else 1.0
                ),
                proposal_source=self.mode,
                proposal_strategy=strategy,
            )
            if candidate is None:
                diagnostics[f"invalid.{strategy}"] += 1
                continue
            retain(candidate, parent=parent, operator=strategy)
        if len(pool) < batch_size:
            raise RuntimeError(
                f"{self.mode} produced {len(pool)} novel mappings; required {batch_size}"
            )
        if self.mode == "uniform":
            selected = pool[:batch_size]
            diagnostics["selected.uniform"] = batch_size
        else:
            features = np.asarray(
                [self.space.mapping_feature_vector(item.candidate.masks) for item in pool],
                dtype=np.float32,
            )
            model_scores = np.asarray(backend.score(features), dtype=np.float64)
            if local_mode:
                order = np.argsort(np.argsort(model_scores, kind="stable"), kind="stable")
                model_tiebreak = order.astype(np.float64) / max(1, len(order) - 1)
                repair_scores = np.asarray(
                    [
                        self._local_ranking_score(
                            probe_cache.get(item.candidate.candidate_id),
                            length_guided=self.mode == "length_repair",
                        )
                        for item in pool
                    ],
                    dtype=np.float64,
                )
                scores = repair_scores + 1e-3 * model_tiebreak
            else:
                scores = model_scores
            ranked = list(np.argsort(-scores, kind="stable"))
            explore = min(
                batch_size,
                int(round(batch_size * self.exploration_fraction)),
            )
            exploit = batch_size - explore
            indexes = ranked[:exploit]
            if explore:
                indexes.extend(rng.sample(ranked[exploit:], explore))
            selected = [pool[int(index)] for index in indexes]
            diagnostics["selected.exploit"] = exploit
            diagnostics["selected.explore"] = explore
        for item in selected:
            diagnostics[f"accepted.{item.candidate.proposal_strategy}"] += 1
        diagnostics["pool_size"] = len(pool)
        diagnostics["persistent_seen"] = len(seen)
        self.last_diagnostics = dict(sorted(diagnostics.items()))
        return selected

    @staticmethod
    def _repair_scalar(probe: LengthRepairProbe | None) -> float | None:
        if probe is None:
            return None
        slack = probe.normalized_length_slack
        slack_quality = (
            -math.log10(max(1e-12, float(slack)))
            if slack is not None
            else -12.0
        )
        return (
            100.0 * probe.topology_level
            + (50.0 if probe.positive_lengths_feasible else 0.0)
            + slack_quality
        )

    @classmethod
    def _local_ranking_score(
        cls,
        probe: LengthRepairProbe | None,
        *,
        length_guided: bool,
    ) -> float:
        if probe is None:
            return -1e12
        topology = float(probe.topology_level)
        if not length_guided:
            return topology * 1e6
        scalar = cls._repair_scalar(probe)
        return topology * 1e9 + (scalar if scalar is not None else -1e6) * 1e3


def recover_deep_candidates(
    space: MappingSpace,
    source_arm_directories: Sequence[Path],
    *,
    minimum_stage: int = 8,
) -> tuple[MappingCandidate, ...]:
    recovered: dict[str, MappingCandidate] = {}
    for directory in source_arm_directories:
        dataset_path = directory / "dataset.npz"
        if dataset_path.exists():
            dataset = NeuralTrainingDataset.load(dataset_path)
            features = np.concatenate(
                (dataset.train_features, dataset.validation_features), axis=0
            )
            stages = np.concatenate(
                (dataset.train_stages, dataset.validation_stages), axis=0
            )
            for vector in features[stages >= minimum_stage]:
                try:
                    masks = space.mapping_masks_from_feature_vector(vector)
                    candidate = space.candidate_from_masks(
                        masks,
                        proposal_source="bootstrap",
                        proposal_strategy="recovered_dataset",
                    )
                except (TypeError, ValueError):
                    continue
                recovered[candidate.candidate_id] = candidate
        archive_path = directory / "archive.json"
        if archive_path.exists():
            payload = json.loads(archive_path.read_text(encoding="utf-8"))
            for raw in payload.get("entries", []):
                # Both the original experiment archive (stage_index) and the
                # deep curriculum archive (depth) are accepted as bootstrap
                # sources. This preserves the 92 exact depth-8 mappings found by
                # the previous run instead of falling back to only its 71 seeds.
                recovered_depth = int(
                    raw.get("depth", raw.get("stage_index", 0))
                )
                if recovered_depth < minimum_stage:
                    continue
                try:
                    candidate = space.candidate_from_masks(
                        raw["masks"],
                        proposal_source="bootstrap",
                        proposal_strategy="recovered_archive",
                    )
                except (TypeError, ValueError):
                    continue
                recovered[candidate.candidate_id] = candidate
    return tuple(recovered[key] for key in sorted(recovered))


def recover_prior_observations(
    space: MappingSpace,
    source_arm_directories: Sequence[Path],
    *,
    maximum_stage_exclusive: int = 8,
    maximum_examples_per_stage: int = 5000,
) -> ObservationBatch:
    """Recover old coarse labels whose meaning did not change.

    Mapping feature vectors are lossless, so they also recover stable candidate
    identifiers.  Stage 8 is deliberately excluded: only a fresh exact
    curriculum evaluation can refine that old coarse label.
    """

    capacity = max(1, int(maximum_examples_per_stage))
    recovered: dict[str, tuple[int, np.ndarray]] = {}
    for directory in source_arm_directories:
        path = directory / "dataset.npz"
        if not path.exists():
            continue
        dataset = NeuralTrainingDataset.load(path)
        features = np.concatenate(
            (dataset.train_features, dataset.validation_features), axis=0
        )
        stages = np.concatenate(
            (dataset.train_stages, dataset.validation_stages), axis=0
        )
        for vector, raw_stage in zip(features, stages):
            stage = int(raw_stage)
            if stage >= maximum_stage_exclusive:
                continue
            try:
                masks = space.mapping_masks_from_feature_vector(vector)
                candidate = space.candidate_from_masks(masks)
            except (TypeError, ValueError):
                continue
            previous = recovered.get(candidate.candidate_id)
            if previous is None or stage > previous[0]:
                recovered[candidate.candidate_id] = (
                    stage,
                    np.asarray(vector, dtype=np.float32),
                )

    by_stage: dict[int, dict[str, np.ndarray]] = {}
    for candidate_id, (stage, vector) in recovered.items():
        by_stage.setdefault(stage, {})[candidate_id] = vector

    candidate_ids: list[str] = []
    retained_features: list[np.ndarray] = []
    retained_stages: list[int] = []
    for stage, candidates in sorted(by_stage.items()):
        for candidate_id in sorted(candidates)[:capacity]:
            candidate_ids.append(candidate_id)
            retained_features.append(candidates[candidate_id])
            retained_stages.append(stage)
    features = (
        np.stack(retained_features).astype(np.float32, copy=False)
        if retained_features
        else np.empty((0, space.mapping_feature_dimension), dtype=np.float32)
    )
    return ObservationBatch(
        candidate_ids=tuple(candidate_ids),
        features=features,
        terminal_stages=np.asarray(retained_stages, dtype=np.int16),
    )
