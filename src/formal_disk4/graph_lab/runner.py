from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import AbstractSet, Any, Callable, Iterator, Mapping, Sequence, TypeVar

import numpy as np

from formal_disk4.pipeline.filter_report import LEARNING_FILTER_IDS
from formal_disk4.pipeline.output import atomic_replace

from .evaluator import GRAPH_STAGES, GraphEvaluation, GraphFormalEvaluator
from .feedback import read_learning_feedback
from .isomorphism import IsomorphismIndex
from .mapping import MappingEvaluation, MappingProposal
from .mapping_model import MappingLearningModel
from .model import GraphLearningModel
from .rollout_audit import build_generation_coverage, weak_trajectory_id
from .space import (
    DualGraphCandidate,
    GraphSpace,
    format_tile_count_spec,
    graph_feature_payload,
)
from .specialization_model import (
    SpecializationLearningModel,
    SpecializationPoolObservation,
)
from .weak_model import WeakOrderLearningModel, WeakOrderRolloutObservation


RESTART_FILES = (
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

# The model checkpoints retain the knowledge learned over the complete run.
# Replay records are only the recent examples used to continue training.  The
# JSON representation of one mapping/weak-order record expands substantially
# when restored as Python objects, so retaining tens of thousands of them can
# consume several gigabytes and make resume spend tens of minutes in GC.
MAX_MAPPING_REPLAY_IN_MEMORY = 8192
MAX_WEAK_ORDER_REPLAY_IN_MEMORY = 8192
MAX_SPECIALIZATION_REPLAY_IN_MEMORY = 4096


def _checkpoint_fingerprint(config: Mapping[str, object]) -> str:
    """Hash only checkpoint-shape/semantics settings.

    Ring exclusion changes the future proposal distribution, not model shapes,
    solver targets, or stored record schemas.  It is intentionally omitted so
    a run can use rings as pre-training and later transfer those weights to the
    non-ring domain (or temporarily enable rings again).
    """

    compatible = json.loads(json.dumps(config))
    space = compatible.get("space")
    if isinstance(space, dict):
        space.pop("exclude_rings", None)
        space.pop("tile_counts", None)
    return hashlib.sha256(
        json.dumps(compatible, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    atomic_replace(temporary, path)


def _append_jsonl(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, sort_keys=True) + "\n")
        stream.flush()


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                yield value


_MAPPING_ID_PATTERN = re.compile(rb'"mapping_id"\s*:\s*"([^"]+)"')
_ACTION_MASK_PATTERN = re.compile(rb'"mask"\s*:\s*(-?\d+)')


def _mapping_id_from_journal_line(line: bytes) -> str | None:
    match = _MAPPING_ID_PATTERN.search(line)
    return match.group(1).decode("ascii") if match is not None else None


def _weak_trajectory_id_from_journal_line(line: bytes) -> str | None:
    mapping_id = _mapping_id_from_journal_line(line)
    if mapping_id is None:
        return None
    masks = ",".join(
        match.group(1).decode("ascii") for match in _ACTION_MASK_PATTERN.finditer(line)
    )
    payload = f"{mapping_id}|{masks}".encode("ascii")
    return "wr-" + hashlib.sha256(payload).hexdigest()[:24]


def _tail_jsonl(
    path: Path,
    limit: int,
    *,
    identity: Callable[[bytes], str | None] | None = None,
) -> tuple[list[dict[str, Any]], int, set[str]]:
    """Return the last ``limit`` records while counting the complete journal.

    Old records are read only as raw bytes.  This keeps resume linear in disk
    I/O but bounds JSON decoding and Python-object construction to the replay
    window that can actually influence subsequent training.
    """

    if not path.exists():
        return [], 0, set()
    raw_tail: deque[bytes] = deque(maxlen=max(1, int(limit)))
    identities: set[str] = set()
    total = 0
    with path.open("rb") as stream:
        for line in stream:
            if not line.strip():
                continue
            raw_tail.append(line)
            if identity is not None:
                identifier = identity(line)
                if identifier is not None:
                    identities.add(identifier)
            total += 1
    records: list[dict[str, Any]] = []
    for line in raw_tail:
        value = json.loads(line)
        if isinstance(value, dict):
            records.append(value)
    return records, total, identities


ReplayItem = TypeVar("ReplayItem")


def _extend_bounded_replay(
    replay: list[ReplayItem],
    additions: Sequence[ReplayItem],
    *,
    limit: int,
) -> None:
    """Append records while retaining exactly the model's replay window."""

    replay.extend(additions)
    excess = len(replay) - max(1, int(limit))
    if excess > 0:
        del replay[:excess]


def _diversity_cell(candidate: DualGraphCandidate, stage: int) -> str:
    maximum_edges = max(1, 3 * (candidate.tile_count + 1) - 6)
    density_bin = min(4, int(5 * candidate.edge_count / maximum_edges))
    symmetry = candidate.symmetry_order
    symmetry_bin = "none" if symmetry <= 1 else ("high" if symmetry >= 4 else "low")
    return f"n{candidate.tile_count}:sym-{symmetry_bin}:density-{density_bin}:stage-{stage}"


class DiversityArchive:
    def __init__(self, observations: Sequence[GraphEvaluation]) -> None:
        self.cells: dict[str, list[GraphEvaluation]] = defaultdict(list)
        for observation in observations:
            self.add(observation)

    @staticmethod
    def reward(observation: GraphEvaluation) -> float:
        return (
            float(observation.stage_index)
            + 4.0 * len(observation.profiles)
            - 0.08 * math.log1p(observation.elapsed_seconds)
            - (1.0 if observation.tainted else 0.0)
        )

    def add(self, observation: GraphEvaluation) -> None:
        cell = _diversity_cell(observation.candidate, observation.stage_index)
        values = self.cells[cell]
        # Repeated visits to one graph are useful because they sample new
        # mappings and weak-order trajectories, but they must not evict all
        # structurally different parents from the diversity archive.
        values[:] = [
            item
            for item in values
            if item.candidate.graph_id != observation.candidate.graph_id
        ]
        values.append(observation)
        values.sort(key=lambda item: (-self.reward(item), item.candidate.graph_id))
        del values[8:]

    def novelty(self, candidate: DualGraphCandidate) -> float:
        prefix = _diversity_cell(candidate, 0).rsplit(":stage-", 1)[0]
        amount = sum(
            len(values) for cell, values in self.cells.items() if cell.startswith(prefix)
        )
        return 1.0 / math.sqrt(1.0 + amount)

    def choose_parent(
        self,
        rng: random.Random,
        *,
        size_weight: Callable[[int], float] | None = None,
        allowed_tile_counts: AbstractSet[int] | None = None,
    ) -> GraphEvaluation | None:
        nonempty = []
        for values in self.cells.values():
            eligible = [
                item
                for item in values
                if allowed_tile_counts is None
                or item.candidate.tile_count in allowed_tile_counts
            ]
            if eligible:
                nonempty.append(eligible)
        if not nonempty:
            return None
        weight_for = size_weight or (lambda _tile_count: 1.0)
        if rng.random() < 0.75:
            values = rng.choices(
                nonempty,
                weights=[
                    max(1e-12, float(weight_for(items[0].candidate.tile_count)))
                    for items in nonempty
                ],
                k=1,
            )[0]
            weights = [max(0.1, self.reward(item) + 1.0) for item in values]
            return rng.choices(values, weights=weights, k=1)[0]
        all_values = [item for values in nonempty for item in values]
        weights = [
            max(0.1, self.reward(item) + 1.0)
            * max(1e-12, float(weight_for(item.candidate.tile_count)))
            for item in all_values
        ]
        return rng.choices(all_values, weights=weights, k=1)[0]


@dataclass(frozen=True)
class GraphLabResult:
    output_directory: Path
    generations_completed: int
    observations: int
    geometry_ready_graphs: int
    stop_reason: str


class GraphLabRunner:
    def __init__(self, root: Path, config: Mapping[str, object]) -> None:
        self.root = root.resolve()
        self.config = dict(config)
        output = Path(str(dict(config["output"])["directory"]))
        self.output = (output if output.is_absolute() else self.root / output).resolve()
        try:
            self.output.relative_to(self.root)
        except ValueError as error:
            raise ValueError("Graph Lab output must stay inside the project") from error
        if self.output == self.root:
            raise ValueError("Graph Lab output cannot be the project root")
        raw_budget = dict(config["output"]).get("max_training_megabytes")
        self.max_training_bytes = (
            max(1, int(float(raw_budget) * 1024 * 1024))
            if raw_budget is not None and float(raw_budget) > 0
            else None
        )
        self.space = GraphSpace.from_config(dict(config.get("space", {})))
        self.exclude_rings = self.space.exclude_rings
        self.stein_symmetric = self.space.stein_symmetric
        self.sampling = dict(config.get("sampling", {}))
        self.learning = dict(config.get("learning", {}))
        self.mapping_sampling = dict(config.get("mapping_sampling", {}))
        self.mapping_learning = dict(config.get("mapping_learning", {}))
        self.mapping_learning_enabled = bool(
            self.mapping_sampling.get("enabled", False)
        )
        self.weak_order_sampling = dict(config.get("weak_order_sampling", {}))
        self.weak_order_learning = dict(config.get("weak_order_learning", {}))
        self.weak_order_learning_enabled = bool(
            self.mapping_learning_enabled
            and self.weak_order_sampling.get("enabled", False)
        )
        self.specialization_sampling = dict(
            config.get("specialization_sampling", {})
        )
        self.specialization_learning = dict(
            config.get("specialization_learning", {})
        )
        self.specialization_learning_enabled = bool(
            self.weak_order_learning_enabled
            and self.specialization_sampling.get("enabled", False)
        )
        self.evaluator = GraphFormalEvaluator(
            self.root, dict(config.get("evaluation", {}))
        )
        self.fingerprint = _checkpoint_fingerprint(self.config)

    @classmethod
    def from_file(
        cls,
        root: Path,
        path: Path | str,
        *,
        exclude_rings: bool | None = None,
        tile_counts: str | Sequence[int] | None = None,
        stein_symmetric: bool | None = None,
        symmetry_orders: str | Sequence[int] | None = None,
        output_directory: Path | str | None = None,
    ) -> "GraphLabRunner":
        source = Path(path)
        if not source.is_absolute():
            source = root / source
        config = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError("Graph Lab config must be a JSON object")
        if exclude_rings is not None:
            space = dict(config.get("space", {}))
            space["exclude_rings"] = bool(exclude_rings)
            config["space"] = space
        if tile_counts is not None:
            space = dict(config.get("space", {}))
            space["tile_counts"] = tile_counts
            config["space"] = space
        if stein_symmetric is not None:
            space = dict(config.get("space", {}))
            space["stein_symmetric"] = bool(stein_symmetric)
            config["space"] = space
        if symmetry_orders is not None:
            space = dict(config.get("space", {}))
            space["symmetry_orders"] = symmetry_orders
            config["space"] = space
        if output_directory is not None:
            output = dict(config.get("output", {}))
            output["directory"] = str(output_directory)
            config["output"] = output
        return cls(root, config)

    def restart_outputs(self) -> None:
        self.output.mkdir(parents=True, exist_ok=True)
        for name in RESTART_FILES:
            path = self.output / name
            temporary = path.with_suffix(path.suffix + ".tmp")
            for stale in (path, temporary):
                if stale.exists():
                    stale.unlink()

    def _load_observations(self) -> list[GraphEvaluation]:
        return [
            GraphEvaluation.from_dict(value)
            for value in _iter_jsonl(self.output / "observations.jsonl")
        ]

    def _load_mapping_observations(
        self,
    ) -> tuple[list[MappingEvaluation], set[str], int]:
        configured = max(
            1, int(self.mapping_learning.get("replay_examples", 50000))
        )
        limit = min(configured, MAX_MAPPING_REPLAY_IN_MEMORY)
        values, total, seen_ids = _tail_jsonl(
            self.output / "mapping_observations.jsonl",
            limit,
            identity=_mapping_id_from_journal_line,
        )
        replay = [MappingEvaluation.from_dict(value) for value in values]
        return replay, seen_ids, total

    def _load_weak_order_rollouts(
        self,
    ) -> tuple[list[WeakOrderRolloutObservation], set[str], int]:
        configured = max(
            1, int(self.weak_order_learning.get("replay_rollouts", 50000))
        )
        limit = min(configured, MAX_WEAK_ORDER_REPLAY_IN_MEMORY)
        values, total, seen_ids = _tail_jsonl(
            self.output / "weak_order_rollouts.jsonl",
            limit,
            identity=_weak_trajectory_id_from_journal_line,
        )
        replay = [WeakOrderRolloutObservation.from_dict(value) for value in values]
        return replay, seen_ids, total

    def _load_specialization_pools(
        self,
    ) -> tuple[list[SpecializationPoolObservation], int]:
        configured = max(
            1, int(self.specialization_learning.get("replay_pools", 20000))
        )
        limit = min(configured, MAX_SPECIALIZATION_REPLAY_IN_MEMORY)
        proposals: dict[str, MappingProposal] = {}
        pools: deque[SpecializationPoolObservation] = deque(maxlen=limit)
        total = 0
        for value in _iter_jsonl(self.output / "specialization_pools.jsonl"):
            raw_proposal = value.get("proposal")
            proposal = (
                MappingProposal.from_dict(raw_proposal)
                if isinstance(raw_proposal, Mapping)
                else proposals.get(str(value.get("mapping_id", "")))
            )
            if proposal is None:
                raise ValueError(
                    "Specialization journal references a mapping before its full record"
                )
            proposals[proposal.mapping_id] = proposal
            pools.append(
                SpecializationPoolObservation.from_dict(value, proposal=proposal)
            )
            total += 1
        return list(pools), total

    def _select_mappings(
        self,
        pool: Sequence[MappingProposal],
        model: MappingLearningModel,
        rng: random.Random,
        amount: int,
    ) -> list[tuple[MappingProposal, Mapping[str, object]]]:
        amount = min(max(1, int(amount)), len(pool))
        exploration = min(
            amount,
            max(
                1,
                int(
                    round(
                        amount
                        * float(
                            self.mapping_sampling.get("exploration_fraction", 0.25)
                        )
                    )
                ),
            ),
        )
        scored = []
        curriculum = model.curriculum_state()
        for proposal in pool:
            prediction = model.predict(proposal)
            utility = model.policy_score(prediction)
            scored.append((utility, proposal, prediction))
        if not model.has_policy_signal:
            selected = [
                (item, "exploration") for item in rng.sample(scored, amount)
            ]
        else:
            random_control = (
                rng.sample(scored, exploration) if exploration else []
            )
            control_ids = {item[1].mapping_id for item in random_control}
            remaining = [
                item for item in scored if item[1].mapping_id not in control_ids
            ]
            learned = []
            temperature = max(
                1e-3, float(self.mapping_sampling.get("temperature", 0.7))
            )
            epsilon = min(
                1.0, max(0.0, float(self.mapping_sampling.get("epsilon", 0.15)))
            )
            while remaining and len(learned) < amount - exploration:
                values = np.asarray(
                    [item[0] for item in remaining], dtype=np.float64
                ) / temperature
                values -= np.max(values)
                weights = np.exp(np.clip(values, -60.0, 0.0))
                weights = (1.0 - epsilon) * weights / max(
                    1e-12, float(np.sum(weights))
                ) + epsilon / len(remaining)
                chosen = rng.choices(
                    range(len(remaining)), weights=weights, k=1
                )[0]
                learned.append(remaining.pop(chosen))
            selected = [(item, "learned") for item in learned]
            selected.extend((item, "exploration") for item in random_control)
        return [
            (
                proposal,
                {
                    "selection_mode": mode,
                    "selection_score": score,
                    "predicted_conditional_probabilities": list(
                        prediction.conditional_probabilities
                    ),
                    "predicted_reach_probabilities": list(
                        prediction.reach_probabilities
                    ),
                    "predicted_value_probabilities": list(
                        prediction.value_probabilities
                    ),
                    "predicted_seconds": prediction.expected_seconds,
                    "ranking_target": (
                        curriculum.frontier_id or "waiting_for_filter_contrast"
                    ),
                    "curriculum": curriculum.to_dict(),
                },
            )
            for (score, proposal, prediction), mode in selected
        ]

    def _evaluate_with_mapping_ranker(
        self,
        candidate: DualGraphCandidate,
        model: MappingLearningModel,
        weak_model: WeakOrderLearningModel,
        specialization_model: SpecializationLearningModel,
        rng: random.Random,
        generation: int,
    ) -> tuple[
        GraphEvaluation,
        list[tuple[MappingEvaluation, Mapping[str, object]]],
        list[WeakOrderRolloutObservation],
        tuple[MappingProposal, ...],
        list[SpecializationPoolObservation],
    ]:
        amount = max(1, int(self.mapping_sampling.get("mappings_per_graph", 4)))
        pool_size = max(
            amount,
            amount * max(1, int(self.mapping_sampling.get("pool_multiplier", 8))),
        )
        pool = self.evaluator.mapping_pool(candidate, rng, pool_size)
        selected = self._select_mappings(pool, model, rng, amount)
        rollouts = max(
            1,
            int(
                self.weak_order_sampling.get(
                    "rollouts_per_mapping",
                    self.mapping_sampling.get("rollouts_per_mapping", 2),
                )
            ),
        )
        seed = int(self.mapping_sampling.get("rollout_seed", 20260810))
        records: list[tuple[MappingEvaluation, Mapping[str, object]]] = []
        weak_records: list[WeakOrderRolloutObservation] = []
        specialization_records: list[SpecializationPoolObservation] = []
        specialization_proposals_written: set[str] = set()

        def preserve_rollout(observation: WeakOrderRolloutObservation) -> None:
            payload = observation.to_dict()
            payload["generation"] = generation
            _append_jsonl(self.output / "weak_order_rollouts.jsonl", payload)
            if observation.deepest_filter_index >= int(
                self.weak_order_sampling.get("preserve_from_filter_index", 21)
            ):
                _append_jsonl(
                    self.output / "deep_weak_order_candidates.jsonl",
                    {
                        "schema_version": "graph-lab-deep-weak-index-v2",
                        "generation": generation,
                        "trajectory_id": weak_trajectory_id(observation),
                        "graph_id": observation.proposal.candidate.graph_id,
                        "mapping_id": observation.proposal.mapping_id,
                        "deepest_filter_index": observation.deepest_filter_index,
                        "profile_count": observation.profile_count,
                        "source": "weak_order_rollouts.jsonl",
                    },
                )
            weak_records.append(observation)

        def preserve_specialization(
            observation: SpecializationPoolObservation,
        ) -> None:
            mapping_id = observation.proposal.mapping_id
            payload = observation.to_dict(
                include_proposal=mapping_id not in specialization_proposals_written
            )
            specialization_proposals_written.add(mapping_id)
            payload["generation"] = generation
            _append_jsonl(self.output / "specialization_pools.jsonl", payload)
            specialization_records.append(observation)

        for selection_index, (proposal, metadata) in enumerate(selected):
            evaluation = self.evaluator.evaluate_mapping(
                proposal,
                rollouts=rollouts,
                random_seed=(
                    seed
                    + generation * 10000019
                    + selection_index * 100003
                    + rng.randrange(100003)
                ),
                weak_model=(
                    weak_model if self.weak_order_learning_enabled else None
                ),
                weak_sampling=self.weak_order_sampling,
                rollout_sink=(
                    preserve_rollout if self.weak_order_learning_enabled else None
                ),
                specialization_model=(
                    specialization_model
                    if self.specialization_learning_enabled
                    else None
                ),
                specialization_sampling=self.specialization_sampling,
                specialization_sink=(
                    preserve_specialization
                    if self.specialization_learning_enabled
                    else None
                ),
            )
            payload = evaluation.to_dict()
            payload["generation"] = generation
            payload["selection"] = dict(metadata)
            _append_jsonl(self.output / "mapping_observations.jsonl", payload)
            if evaluation.deepest_filter_index >= int(
                self.mapping_sampling.get("preserve_from_filter_index", 21)
            ):
                _append_jsonl(
                    self.output / "deep_mapping_candidates.jsonl",
                    {
                        "schema_version": "graph-lab-deep-mapping-index-v2",
                        "generation": generation,
                        "graph_id": evaluation.proposal.candidate.graph_id,
                        "mapping_id": evaluation.proposal.mapping_id,
                        "deepest_filter_index": evaluation.deepest_filter_index,
                        "profile_count": len(evaluation.profiles),
                        "source": "mapping_observations.jsonl",
                    },
                )
            records.append((evaluation, metadata))
        evaluations = [evaluation for evaluation, _metadata in records]
        return (
            self.evaluator.aggregate_mappings(candidate, evaluations),
            records,
            weak_records,
            pool,
            specialization_records,
        )

    def _mapping_generation_metrics(
        self,
        generation: int,
        records: Sequence[
            tuple[MappingEvaluation, Mapping[str, object]]
        ],
        model_metrics: Mapping[str, object],
    ) -> dict[str, object]:
        def aggregate(
            selected: Sequence[
                tuple[MappingEvaluation, Mapping[str, object]]
            ],
        ) -> dict[str, dict[str, object]]:
            modes: dict[str, dict[str, object]] = {}
            for evaluation, selection in selected:
                mode = str(selection.get("selection_mode", "unknown"))
                bucket = modes.setdefault(
                    mode,
                    {
                        "count": 0,
                        "profile_emitting_count": 0,
                        "profile_count": 0,
                        "filters": {
                            filter_id: {
                                "eligible": 0,
                                "passed": 0,
                                "prediction_sum": 0.0,
                                "prediction_count": 0,
                            }
                            for filter_id in LEARNING_FILTER_IDS
                        },
                        "reach": {
                            filter_id: {
                                "eligible": 0,
                                "passed": 0.0,
                                "prediction_sum": 0.0,
                                "prediction_count": 0,
                            }
                            for filter_id in LEARNING_FILTER_IDS
                        },
                    },
                )
                bucket["count"] = int(bucket["count"]) + 1
                bucket["profile_emitting_count"] = int(
                    bucket["profile_emitting_count"]
                ) + bool(evaluation.profiles)
                bucket["profile_count"] = int(bucket["profile_count"]) + len(
                    evaluation.profiles
                )
                raw_predictions = selection.get(
                    "predicted_conditional_probabilities", ()
                )
                predictions = (
                    raw_predictions
                    if isinstance(raw_predictions, Sequence)
                    and not isinstance(raw_predictions, (str, bytes))
                    else ()
                )
                filters = bucket["filters"]
                reaches = bucket["reach"]
                assert isinstance(filters, dict)
                assert isinstance(reaches, dict)
                raw_reach_predictions = selection.get(
                    "predicted_reach_probabilities", ()
                )
                reach_predictions = (
                    raw_reach_predictions
                    if isinstance(raw_reach_predictions, Sequence)
                    and not isinstance(raw_reach_predictions, (str, bytes))
                    else ()
                )
                for head, observation in enumerate(evaluation.filters.observations):
                    target = filters[observation.filter_id]
                    assert isinstance(target, dict)
                    target["eligible"] = int(target["eligible"]) + observation.decided
                    target["passed"] = int(target["passed"]) + observation.passed
                    if head < len(predictions) and observation.decided:
                        target["prediction_sum"] = float(
                            target["prediction_sum"]
                        ) + float(predictions[head])
                        target["prediction_count"] = int(
                            target["prediction_count"]
                        ) + 1
                    reach_target = reaches[observation.filter_id]
                    assert isinstance(reach_target, dict)
                    reach_value = evaluation.reach_vector[head]
                    if reach_value is None:
                        continue
                    reach_target["eligible"] = int(reach_target["eligible"]) + 1
                    reach_target["passed"] = float(reach_target["passed"]) + float(
                        reach_value
                    )
                    if head < len(reach_predictions):
                        reach_target["prediction_sum"] = float(
                            reach_target["prediction_sum"]
                        ) + float(reach_predictions[head])
                        reach_target["prediction_count"] = int(
                            reach_target["prediction_count"]
                        ) + 1
            return modes

        parent_modes: dict[str, set[str]] = defaultdict(set)
        for evaluation, selection in records:
            parent_modes[evaluation.proposal.candidate.graph_id].add(
                str(selection.get("selection_mode", "unknown"))
            )
        comparable_parents = {
            parent
            for parent, modes in parent_modes.items()
            if {"exploration", "learned"}.issubset(modes)
        }
        comparable_records = [
            record
            for record in records
            if record[0].proposal.candidate.graph_id in comparable_parents
        ]
        return {
            "schema_version": "graph-lab-mapping-generation-metrics-v1",
            "generation": generation,
            "evaluated": len(records),
            "geometry_ready": sum(
                bool(evaluation.profiles) for evaluation, _selection in records
            ),
            "filter_order": list(LEARNING_FILTER_IDS),
            "selection_modes": aggregate(records),
            "comparable_selection_modes": aggregate(comparable_records),
            "comparison": {
                "scope": "same_generation_and_graph",
                "comparable_parent_count": len(comparable_parents),
                "excluded_parent_count": len(parent_modes) - len(comparable_parents),
            },
            "model": dict(model_metrics),
        }

    def _weak_order_generation_metrics(
        self,
        generation: int,
        records: Sequence[WeakOrderRolloutObservation],
        model_metrics: Mapping[str, object],
    ) -> dict[str, object]:
        def aggregate(
            selected: Sequence[WeakOrderRolloutObservation],
        ) -> dict[str, dict[str, object]]:
            modes: dict[str, dict[str, object]] = {}
            for rollout in selected:
                bucket = modes.setdefault(
                    rollout.selection_mode,
                    {
                        "count": 0,
                        "profile_emitting_count": 0,
                        "profile_count": 0,
                        "decision_count": 0,
                        "candidate_count_sum": 0,
                        "entropy_sum": 0.0,
                        "filters": {
                            filter_id: {
                                "eligible": 0,
                                "passed": 0,
                                "prediction_sum": 0.0,
                                "prediction_count": 0,
                            }
                            for filter_id in LEARNING_FILTER_IDS
                        },
                        "reach": {
                            filter_id: {
                                "eligible": 0,
                                "passed": 0,
                                "prediction_sum": 0.0,
                                "prediction_count": 0,
                            }
                            for filter_id in LEARNING_FILTER_IDS
                        },
                    },
                )
                bucket["count"] = int(bucket["count"]) + 1
                bucket["profile_emitting_count"] = int(
                    bucket["profile_emitting_count"]
                ) + (rollout.profile_count > 0)
                bucket["profile_count"] = int(bucket["profile_count"]) + int(
                    rollout.profile_count
                )
                bucket["decision_count"] = int(bucket["decision_count"]) + len(
                    rollout.decisions
                )
                bucket["candidate_count_sum"] = int(
                    bucket["candidate_count_sum"]
                ) + sum(decision.candidate_count for decision in rollout.decisions)
                bucket["entropy_sum"] = float(bucket["entropy_sum"]) + sum(
                    decision.policy_entropy for decision in rollout.decisions
                )
                filters = bucket["filters"]
                reaches = bucket["reach"]
                assert isinstance(filters, dict)
                assert isinstance(reaches, dict)
                for head, observation in enumerate(rollout.filters.observations):
                    target = filters[observation.filter_id]
                    assert isinstance(target, dict)
                    target["eligible"] = int(target["eligible"]) + observation.decided
                    target["passed"] = int(target["passed"]) + observation.passed
                    for decision in rollout.decisions:
                        if (
                            observation.decided
                            and head
                            < len(decision.predicted_conditional_probabilities)
                        ):
                            target["prediction_sum"] = float(
                                target["prediction_sum"]
                            ) + decision.predicted_conditional_probabilities[head]
                            target["prediction_count"] = int(
                                target["prediction_count"]
                            ) + 1
                    reach_target = reaches[observation.filter_id]
                    assert isinstance(reach_target, dict)
                    reach_value = rollout.reach_vector[head]
                    if reach_value is None:
                        continue
                    reach_target["eligible"] = int(reach_target["eligible"]) + 1
                    reach_target["passed"] = int(reach_target["passed"]) + int(
                        reach_value
                    )
                    for decision in rollout.decisions:
                        if head < len(decision.predicted_reach_probabilities):
                            reach_target["prediction_sum"] = float(
                                reach_target["prediction_sum"]
                            ) + decision.predicted_reach_probabilities[head]
                            reach_target["prediction_count"] = int(
                                reach_target["prediction_count"]
                            ) + 1
            return modes

        parent_modes: dict[str, set[str]] = defaultdict(set)
        for rollout in records:
            parent_modes[rollout.proposal.mapping_id].add(rollout.selection_mode)
        comparable_parents = {
            parent
            for parent, modes in parent_modes.items()
            if {"exploration", "learned"}.issubset(modes)
        }
        comparable_records = [
            rollout
            for rollout in records
            if rollout.proposal.mapping_id in comparable_parents
        ]
        return {
            "schema_version": "graph-lab-weak-order-generation-metrics-v1",
            "generation": generation,
            "evaluated": len(records),
            "geometry_ready": sum(item.profile_count > 0 for item in records),
            "filter_order": list(LEARNING_FILTER_IDS),
            "selection_modes": aggregate(records),
            "comparable_selection_modes": aggregate(comparable_records),
            "comparison": {
                "scope": "same_generation_and_mapping",
                "comparable_parent_count": len(comparable_parents),
                "excluded_parent_count": len(parent_modes) - len(comparable_parents),
            },
            "model": dict(model_metrics),
        }

    def _specialization_generation_metrics(
        self,
        generation: int,
        records: Sequence[SpecializationPoolObservation],
        model_metrics: Mapping[str, object],
    ) -> dict[str, object]:
        filter_ids = (
            "specialization.profile_valid",
            "specialization.profile_emitted",
        )

        def aggregate(
            selected: Sequence[SpecializationPoolObservation],
        ) -> dict[str, dict[str, object]]:
            modes: dict[str, dict[str, object]] = {}
            for pool in selected:
                for decision in pool.decisions:
                    bucket = modes.setdefault(
                        decision.selection_mode,
                        {
                            "count": 0,
                            "profile_emitting_count": 0,
                            "profile_count": 0,
                            "decision_count": 0,
                            "candidate_count_sum": 0,
                            "entropy_sum": 0.0,
                            "filters": {
                                name: {
                                    "eligible": 0,
                                    "passed": 0,
                                    "prediction_sum": 0.0,
                                    "prediction_count": 0,
                                }
                                for name in filter_ids
                            },
                            "reach": {
                                name: {
                                    "eligible": 0,
                                    "passed": 0,
                                    "prediction_sum": 0.0,
                                    "prediction_count": 0,
                                }
                                for name in filter_ids
                            },
                        },
                    )
                    bucket["count"] = int(bucket["count"]) + 1
                    bucket["profile_emitting_count"] = int(
                        bucket["profile_emitting_count"]
                    ) + int(decision.outcome.emitted)
                    bucket["profile_count"] = int(bucket["profile_count"]) + int(
                        decision.outcome.emitted
                    )
                    bucket["decision_count"] = int(bucket["decision_count"]) + 1
                    bucket["candidate_count_sum"] = int(
                        bucket["candidate_count_sum"]
                    ) + pool.state.candidate_count
                    bucket["entropy_sum"] = float(bucket["entropy_sum"]) + float(
                        decision.policy_entropy
                    )
                    values = (
                        (
                            "specialization.profile_valid",
                            decision.valid_target,
                            decision.predicted_valid_probability,
                        ),
                        (
                            "specialization.profile_emitted",
                            decision.emission_target,
                            decision.predicted_emission_probability,
                        ),
                    )
                    for name, actual, prediction in values:
                        if actual is None:
                            continue
                        for collection in (bucket["filters"], bucket["reach"]):
                            assert isinstance(collection, dict)
                            target = collection[name]
                            assert isinstance(target, dict)
                            target["eligible"] = int(target["eligible"]) + 1
                            target["passed"] = int(target["passed"]) + int(actual)
                            target["prediction_sum"] = float(
                                target["prediction_sum"]
                            ) + float(prediction)
                            target["prediction_count"] = int(
                                target["prediction_count"]
                            ) + 1
            return modes

        comparable_ids = {
            pool.pool_id
            for pool in records
            if {item.selection_mode for item in pool.decisions}
            >= {"exploration", "learned"}
        }
        comparable = [pool for pool in records if pool.pool_id in comparable_ids]
        legal_candidates = sum(pool.state.candidate_count for pool in records)
        visited_candidates = sum(len(pool.decisions) for pool in records)
        return {
            "schema_version": "graph-lab-specialization-generation-metrics-v1",
            "generation": generation,
            "evaluated": sum(len(pool.decisions) for pool in records),
            "geometry_ready": sum(
                decision.outcome.emitted
                for pool in records
                for decision in pool.decisions
            ),
            "filter_order": list(filter_ids),
            "selection_modes": aggregate(records),
            "comparable_selection_modes": aggregate(comparable),
            "comparison": {
                "scope": "same_word_case_specialization_pool",
                "comparable_parent_count": len(comparable_ids),
                "excluded_parent_count": len(records) - len(comparable_ids),
            },
            "pool_coverage": {
                "pools": len(records),
                "legal_candidates": legal_candidates,
                "visited_candidates": visited_candidates,
                "locally_not_selected": max(
                    0, legal_candidates - visited_candidates
                ),
                "permanently_closed": 0,
                "semantics": (
                    "Unselected siblings remain eligible on every repeated rollout"
                ),
            },
            "model": dict(model_metrics),
        }

    def _training_output_bytes(self) -> int:
        if not self.output.exists():
            return 0
        total = 0
        for path in self.output.rglob("*"):
            if not path.is_file() or path.name.endswith(".tmp"):
                continue
            try:
                total += path.stat().st_size
            except OSError:
                # A concurrent geometry worker may atomically replace a file
                # while the Lab samples disk usage. The next check sees it.
                continue
        return total

    def _output_budget_reached(self) -> bool:
        return (
            self.max_training_bytes is not None
            and self._training_output_bytes() >= self.max_training_bytes
        )

    def _state_generation(self) -> int:
        path = self.output / "state.json"
        if not path.exists():
            return 0
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("fingerprint") != self.fingerprint:
            raise ValueError("Stored Graph Lab state is incompatible; use --restart")
        return int(state.get("next_generation", 0))

    def _candidate_pool(
        self,
        rng: random.Random,
        archive: DiversityArchive,
        target: int,
    ) -> list[DualGraphCandidate]:
        pool: list[DualGraphCandidate] = []
        local = IsomorphismIndex()
        mutation_fraction = min(
            1.0, max(0.0, float(self.sampling.get("mutation_fraction", 0.65)))
        )
        attempts = 0
        while len(pool) < target and attempts < target * 200:
            attempts += 1
            parent = (
                archive.choose_parent(
                    rng,
                    size_weight=self.space.size_sampling_weight,
                    allowed_tile_counts=self.space.allowed_tile_counts,
                )
                if rng.random() < mutation_fraction
                else None
            )
            if parent is not None and not self.space.allows_candidate(
                parent.candidate
            ):
                parent = None
            candidate = (
                self.space.mutate(parent.candidate, rng)
                if parent is not None
                else self.space.sample_prior(rng)
            )
            if candidate is None:
                continue
            if self.exclude_rings and candidate.is_simple_ring:
                continue
            if local.add(candidate):
                pool.append(candidate)
        if len(pool) < target:
            raise RuntimeError(
                f"Graph generator produced only {len(pool)} novel candidates for a pool of {target}"
            )
        return pool

    def _select(
        self,
        pool: Sequence[DualGraphCandidate],
        model: GraphLearningModel,
        archive: DiversityArchive,
        rng: random.Random,
        amount: int,
    ) -> list[tuple[DualGraphCandidate, Mapping[str, object]]]:
        if self.exclude_rings and any(item.is_simple_ring for item in pool):
            raise ValueError(
                "A simple ring reached the graph ranker while exclude_rings is enabled"
            )
        exploration = min(
            amount,
            max(1, int(round(amount * float(self.sampling.get("exploration_fraction", 0.25))))),
        )
        scored = []
        for candidate in pool:
            novelty = archive.novelty(candidate)
            score, prediction = model.utility(
                candidate,
                novelty=novelty,
                geometry_weight=float(self.sampling.get("geometry_weight", 8.0)),
                solution_weight=float(
                    self.sampling.get("geometry_solution_weight", 4.0)
                ),
                nontrivial_solution_weight=float(
                    self.sampling.get("nontrivial_solution_weight", 8.0)
                ),
                novelty_weight=float(self.sampling.get("novelty_weight", 1.5)),
                cost_weight=float(self.sampling.get("cost_weight", 0.08)),
            )
            scored.append((score, candidate, prediction, novelty))
        if not model.has_policy_signal:
            return [
                (
                    candidate,
                    {
                        "selection_mode": "exploration",
                        "selection_score": score,
                        "novelty": novelty,
                        "predicted_stage": prediction.expected_stage,
                        "predicted_geometry_probability": (
                            prediction.geometry_probability
                        ),
                        "predicted_value_probabilities": list(
                            prediction.value_probabilities
                        ),
                        "predicted_transition_probabilities": list(
                            prediction.conditional_probabilities
                        ),
                        "predicted_seconds": prediction.expected_seconds,
                    },
                )
                for score, candidate, prediction, novelty in rng.sample(
                    scored, amount
                )
            ]
        exploit = amount - exploration
        # Draw the control uniformly from the complete pool first. Sampling it
        # only from the tail left by the ranker would make the control
        # artificially weak and overstate learned enrichment.
        random_control = rng.sample(scored, exploration) if exploration else []
        control_ids = {item[1].graph_id for item in random_control}
        remaining = [
            item for item in scored if item[1].graph_id not in control_ids
        ]
        learned = []
        temperature = max(1e-3, float(self.sampling.get("temperature", 0.7)))
        epsilon = min(1.0, max(0.0, float(self.sampling.get("epsilon", 0.15))))
        while remaining and len(learned) < exploit:
            values = np.asarray([item[0] for item in remaining], dtype=np.float64)
            values = values / temperature
            values -= np.max(values)
            weights = np.exp(np.clip(values, -60.0, 0.0))
            weights = (1.0 - epsilon) * weights / max(
                1e-12, float(np.sum(weights))
            ) + epsilon / len(remaining)
            chosen = rng.choices(range(len(remaining)), weights=weights, k=1)[0]
            learned.append(remaining.pop(chosen))
        selected = [(item, "learned") for item in learned]
        selected.extend((item, "exploration") for item in random_control)
        return [
            (
                candidate,
                {
                    "selection_mode": selection_mode,
                    "selection_score": score,
                    "novelty": novelty,
                    "predicted_stage": prediction.expected_stage,
                    "predicted_geometry_probability": prediction.geometry_probability,
                    "predicted_value_probabilities": list(
                        prediction.value_probabilities
                    ),
                    "predicted_transition_probabilities": list(
                        prediction.conditional_probabilities
                    ),
                    "predicted_seconds": prediction.expected_seconds,
                },
            )
            for (score, candidate, prediction, novelty), selection_mode in selected
        ]

    def _generation_metrics(
        self,
        generation: int,
        records: Sequence[tuple[GraphEvaluation, Mapping[str, object]]],
        model_metrics: Mapping[str, object],
    ) -> dict[str, object]:
        """Build tiny per-generation aggregates for the live dashboard."""

        modes: dict[str, dict[str, object]] = {}
        for evaluation, selection in records:
            mode = str(selection.get("selection_mode", "unknown"))
            bucket = modes.setdefault(
                mode,
                {
                    "count": 0,
                    "stage_reached_counts": {
                        stage: 0 for stage in GRAPH_STAGES
                    },
                    "transitions": {
                        stage: {
                            "eligible": 0,
                            "passed": 0,
                            "prediction_sum": 0.0,
                            "prediction_count": 0,
                        }
                        for stage in GRAPH_STAGES[1:]
                    },
                },
            )
            bucket["count"] = int(bucket["count"]) + 1
            reached = bucket["stage_reached_counts"]
            assert isinstance(reached, dict)
            for stage_index, stage in enumerate(GRAPH_STAGES):
                if evaluation.stage_index >= stage_index:
                    reached[stage] = int(reached[stage]) + 1

            raw_predictions = selection.get(
                "predicted_transition_probabilities", ()
            )
            predictions = (
                raw_predictions
                if isinstance(raw_predictions, Sequence)
                and not isinstance(raw_predictions, (str, bytes))
                else ()
            )
            transitions = bucket["transitions"]
            assert isinstance(transitions, dict)
            for head, stage in enumerate(GRAPH_STAGES[1:]):
                target = head + 1
                if evaluation.stage_index < target - 1:
                    continue
                transition = transitions[stage]
                assert isinstance(transition, dict)
                transition["eligible"] = int(transition["eligible"]) + 1
                if evaluation.stage_index >= target:
                    transition["passed"] = int(transition["passed"]) + 1
                if head < len(predictions):
                    transition["prediction_sum"] = float(
                        transition["prediction_sum"]
                    ) + float(predictions[head])
                    transition["prediction_count"] = int(
                        transition["prediction_count"]
                    ) + 1

        comparable = (
            modes if {"exploration", "learned"}.issubset(modes) else {}
        )
        return {
            "schema_version": "graph-lab-generation-metrics-v1",
            "generation": generation,
            "evaluated": len(records),
            "geometry_ready": sum(
                evaluation.geometry_ready for evaluation, _selection in records
            ),
            "training_output_bytes": self._training_output_bytes(),
            "max_training_bytes": self.max_training_bytes,
            "selection_modes": modes,
            "comparable_selection_modes": comparable,
            "comparison": {
                "scope": "same_generation_proposal_pool",
                "comparable_parent_count": 1 if comparable else 0,
                "excluded_parent_count": 0 if comparable else 1,
            },
            "model": dict(model_metrics),
        }

    def _save_geometry(
        self, evaluation: GraphEvaluation, generation: int
    ) -> None:
        graph_payload = {
            "schema_version": "graph-lab-geometry-graph-v1",
            "generation": generation,
            "candidate": evaluation.candidate.to_dict(),
            "evaluation": evaluation.to_dict(),
        }
        _append_jsonl(self.output / "geometry_graphs.jsonl", graph_payload)
        for profile in evaluation.profiles:
            enriched = dict(profile)
            enriched["graph_lab"] = {
                "generation": generation,
                "graph_id": evaluation.candidate.graph_id,
                "structural_candidate": evaluation.candidate.to_dict(),
                "formal_evaluation": evaluation.to_dict(),
            }
            _append_jsonl(self.output / "geometry_candidates.jsonl", enriched)

    def _report(
        self,
        observations: Sequence[GraphEvaluation],
        model: GraphLearningModel,
        generation: int,
        *,
        stop_reason: str,
        model_metrics: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        stage_histogram = Counter(item.stage_name for item in observations)
        reached = {
            name: sum(item.stage_index >= index for item in observations)
            for index, name in enumerate(GRAPH_STAGES)
        }
        sizes = Counter(item.candidate.tile_count for item in observations)
        symmetries = Counter(item.candidate.symmetry_order for item in observations)
        origins = Counter(item.candidate.origin for item in observations)
        geometry = [
            {
                "graph_id": item.candidate.graph_id,
                "tiles": item.candidate.tile_count,
                "edges": item.candidate.edge_count,
                "symmetry_order": item.candidate.symmetry_order,
                "profiles": len(item.profiles)
                or int(item.counters.get("profiles_emitted", 0)),
                "source_map": item.candidate.source_map_name,
            }
            for item in observations
            if item.stage_index >= len(GRAPH_STAGES) - 1
        ]
        unique_graph_count = len(
            {item.candidate.graph_id for item in observations}
        )
        unique_geometry_count = len(
            {item["graph_id"] for item in geometry}
        )
        diversity_archive = DiversityArchive(observations)
        report = {
            "schema_version": "graph-lab-report-v1",
            "generation": generation,
            "stop_reason": stop_reason,
            "observations": len(observations),
            "unique_graphs_evaluated": unique_graph_count,
            "training_output_bytes": self._training_output_bytes(),
            "max_training_bytes": self.max_training_bytes,
            "stage_histogram": dict(stage_histogram),
            "reached_counts": reached,
            "tile_count_prior": {
                str(size): probability
                for size, probability in self.space.size_sampling_distribution()
            },
            "tile_count_domain": list(self.space.tile_counts),
            "requested_tile_count_domain": list(
                self.space.requested_tile_counts
            ),
            "stein_symmetric": self.stein_symmetric,
            "symmetry_order_domain": (
                list(self.space.symmetry_orders)
                if self.space.symmetry_orders is not None
                else None
            ),
            "tile_count_histogram": dict(sorted(sizes.items())),
            "symmetry_order_histogram": dict(sorted(symmetries.items())),
            "origin_histogram": dict(origins),
            "diversity_cells": len(diversity_archive.cells),
            "diversity_cell_sizes": {
                name: len(values)
                for name, values in sorted(diversity_archive.cells.items())
            },
            "geometry_ready": geometry,
            "geometry_ready_evaluations": len(geometry),
            "geometry_ready_unique_graphs": unique_geometry_count,
            "model": (
                dict(model_metrics)
                if model_metrics is not None
                else model.metrics(
                    observations,
                    feedback=read_learning_feedback(self.output),
                    maximum_examples=int(
                        self.learning.get("metric_examples", 512)
                    ),
                )
            ),
        }
        _atomic_json(self.output / "report.json", report)
        lines = [
            "# Variable-graph learning report",
            "",
            f"Generation: {generation}",
            f"Stop reason: {stop_reason}",
            f"Evaluated graph structures: {len(observations)}",
            f"Distinct evaluated graph structures: {unique_graph_count}",
            f"Geometry-ready evaluations: {len(geometry)}",
            f"Distinct geometry-ready graph structures: {unique_geometry_count}",
            f"Training output: {self._training_output_bytes() / (1024 * 1024):.2f} MiB",
            (
                f"Training output limit: {self.max_training_bytes / (1024 * 1024):.2f} MiB"
                if self.max_training_bytes is not None
                else "Training output limit: disabled"
            ),
            "",
            "## Tile-count sampling",
            "",
            "| Tiles | Configured prior probability | Evaluated |",
            "|---:|---:|---:|",
        ]
        for size, probability in self.space.size_sampling_distribution():
            lines.append(
                f"| {size} | {100.0 * probability:.3f}% | {sizes.get(size, 0)} |"
            )
        lines.extend(
            [
                "",
                "## Pipeline depth",
                "",
                "| Stage reached | Count |",
                "|---|---:|",
            ]
        )
        for name in GRAPH_STAGES:
            lines.append(f"| {name} | {reached[name]} |")
        lines.extend(
            [
                "",
                "## Geometry-ready structures",
                "",
                "Every formal candidate is preserved in `geometry_candidates.jsonl`.",
                "The corresponding graph and imposed symmetry are preserved in",
                "`geometry_graphs.jsonl`.",
                "",
                "| Graph | Tiles | Edges | Symmetry order | Profiles | Source |",
                "|---|---:|---:|---:|---:|---|",
            ]
        )
        for value in geometry:
            lines.append(
                f"| {value['graph_id']} | {value['tiles']} | {value['edges']} | "
                f"{value['symmetry_order']} | {value['profiles']} | "
                f"{value['source_map'] or 'generated'} |"
            )
        (self.output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return report

    def run(
        self,
        *,
        restart: bool = False,
        generations: int | None = None,
        batch_size: int | None = None,
    ) -> GraphLabResult:
        if restart:
            self.restart_outputs()
        self.output.mkdir(parents=True, exist_ok=True)
        _atomic_json(self.output / "effective_config.json", self.config)
        observations = self._load_observations()
        (
            mapping_observations,
            seen_mapping_ids,
            mapping_observation_count,
        ) = self._load_mapping_observations()
        (
            weak_order_rollouts,
            seen_trajectory_ids,
            weak_order_rollout_count,
        ) = self._load_weak_order_rollouts()
        (
            specialization_pools,
            specialization_pool_count,
        ) = self._load_specialization_pools()
        seen_graph_ids = {
            observation.candidate.graph_id for observation in observations
        }
        archive = DiversityArchive(observations)
        model = GraphLearningModel.load_or_create(
            self.output / "model.pt", self.learning
        )
        mapping_model = MappingLearningModel.load_or_create(
            self.output / "mapping_model.pt", self.mapping_learning
        )
        weak_order_model = WeakOrderLearningModel.load_or_create(
            self.output / "weak_order_model.pt", self.weak_order_learning
        )
        specialization_model = SpecializationLearningModel.load_or_create(
            self.output / "specialization_model.pt", self.specialization_learning
        )
        feedback = read_learning_feedback(self.output)
        if observations and not (self.output / "model.pt").exists():
            model.train(
                observations,
                steps=int(self.learning.get("bootstrap_steps", 100)),
                batch_size=int(self.learning.get("batch_size", 16)),
                generation=-1,
                feedback=feedback,
            )
        if mapping_observations and not (self.output / "mapping_model.pt").exists():
            mapping_model.train(
                mapping_observations,
                steps=int(self.mapping_learning.get("bootstrap_steps", 100)),
                batch_size=int(self.mapping_learning.get("batch_size", 16)),
                generation=-1,
                feedback=feedback,
            )
        if weak_order_rollouts and not (
            self.output / "weak_order_model.pt"
        ).exists():
            weak_order_model.train(
                weak_order_rollouts,
                steps=int(self.weak_order_learning.get("bootstrap_steps", 100)),
                batch_size=int(self.weak_order_learning.get("batch_size", 16)),
                generation=-1,
                feedback=feedback,
            )
        if specialization_pools and not (
            self.output / "specialization_model.pt"
        ).exists():
            specialization_model.train(
                specialization_pools,
                steps=int(
                    self.specialization_learning.get("bootstrap_steps", 100)
                ),
                batch_size=int(
                    self.specialization_learning.get("batch_size", 16)
                ),
                generation=-1,
            )

        start = self._state_generation()
        total_generations = max(
            1,
            int(
                generations
                if generations is not None
                else self.sampling.get("generations", 1000)
            ),
        )
        target_batch = max(
            1,
            int(
                batch_size
                if batch_size is not None
                else self.sampling.get("batch_size", 8)
            ),
        )
        if self.max_training_bytes is None:
            disk_limit = "off"
        elif self.max_training_bytes >= 1024**3:
            disk_limit = f"{self.max_training_bytes / 1024**3:.2f}GiB"
        else:
            disk_limit = f"{self.max_training_bytes / 1024**2:.0f}MiB"
        print(
            f"graph-lab generations={start}..{total_generations - 1} "
            f"batch={target_batch} "
            f"tiles={format_tile_count_spec(self.space.tile_counts)} "
            f"mode={'stein-symmetric' if self.stein_symmetric else 'general'} "
            f"exclude-rings={'on' if self.exclude_rings else 'off'} "
            f"disk-limit={disk_limit}",
            flush=True,
        )

        last_generation = start - 1
        stop_reason = "completed"
        try:
            for generation in range(start, total_generations):
                if self._output_budget_reached():
                    stop_reason = "max_training_output_bytes"
                    print(
                        "[OUTPUT BUDGET] Graph Lab stopped before evaluating another "
                        f"graph: {self._training_output_bytes() / (1024 * 1024):.2f} "
                        "MiB already stored.",
                        flush=True,
                    )
                    self._report(
                        observations,
                        model,
                        last_generation,
                        stop_reason=stop_reason,
                    )
                    break
                rng = random.Random(
                    int(self.sampling.get("seed", 20260809)) + generation * 1000003
                )
                selected: list[tuple[DualGraphCandidate, Mapping[str, object]]] = []
                generation_graph_pool: list[DualGraphCandidate] = []
                remaining = target_batch
                if remaining:
                    pool = self._candidate_pool(
                        rng,
                        archive,
                        max(
                            remaining,
                            remaining * max(1, int(self.sampling.get("pool_multiplier", 6))),
                        ),
                    )
                    generation_graph_pool.extend(pool)
                    selected.extend(self._select(pool, model, archive, rng, remaining))

                generation_evaluations = []
                generation_mapping_records: list[
                    tuple[MappingEvaluation, Mapping[str, object]]
                ] = []
                generation_mapping_pool: list[MappingProposal] = []
                generation_weak_order_records: list[
                    WeakOrderRolloutObservation
                ] = []
                generation_specialization_records: list[
                    SpecializationPoolObservation
                ] = []
                generation_records: list[
                    tuple[GraphEvaluation, Mapping[str, object]]
                ] = []
                for candidate, selection in selected:
                    if self._output_budget_reached():
                        stop_reason = "max_training_output_bytes"
                        break
                    if self.mapping_learning_enabled:
                        (
                            evaluation,
                            new_mapping_records,
                            new_weak_order_records,
                            new_mapping_pool,
                            new_specialization_records,
                        ) = (
                            self._evaluate_with_mapping_ranker(
                                candidate,
                                mapping_model,
                                weak_order_model,
                                specialization_model,
                                rng,
                                generation,
                            )
                        )
                        new_mapping_observations = [
                            item for item, _metadata in new_mapping_records
                        ]
                        generation_mapping_records.extend(new_mapping_records)
                        generation_mapping_pool.extend(new_mapping_pool)
                        generation_weak_order_records.extend(
                            new_weak_order_records
                        )
                        generation_specialization_records.extend(
                            new_specialization_records
                        )
                    else:
                        evaluation = self.evaluator.evaluate(candidate)
                        new_mapping_observations = []
                        new_weak_order_records = []
                        new_specialization_records = []
                    mapping_observation_count += len(new_mapping_observations)
                    weak_order_rollout_count += len(new_weak_order_records)
                    specialization_pool_count += len(new_specialization_records)
                    _extend_bounded_replay(
                        mapping_observations,
                        new_mapping_observations,
                        limit=min(
                            MAX_MAPPING_REPLAY_IN_MEMORY,
                            int(
                                self.mapping_learning.get(
                                    "replay_examples", 50000
                                )
                            ),
                        ),
                    )
                    _extend_bounded_replay(
                        weak_order_rollouts,
                        new_weak_order_records,
                        limit=min(
                            MAX_WEAK_ORDER_REPLAY_IN_MEMORY,
                            int(
                                self.weak_order_learning.get(
                                    "replay_rollouts", 50000
                                )
                            ),
                        ),
                    )
                    _extend_bounded_replay(
                        specialization_pools,
                        new_specialization_records,
                        limit=min(
                            MAX_SPECIALIZATION_REPLAY_IN_MEMORY,
                            int(
                                self.specialization_learning.get(
                                    "replay_pools", 20000
                                )
                            ),
                        ),
                    )
                    observation = evaluation.to_dict()
                    observation["generation"] = generation
                    observation["selection"] = dict(selection)
                    observation["graph_features"] = graph_feature_payload(candidate)
                    _append_jsonl(self.output / "observations.jsonl", observation)
                    archive.add(evaluation)
                    observations.append(evaluation)
                    generation_evaluations.append(evaluation)
                    generation_records.append((evaluation, selection))
                    if evaluation.geometry_ready:
                        self._save_geometry(evaluation, generation)
                        print(
                            "[GEOMETRY READY] "
                            f"g={generation} graph={candidate.graph_id} "
                            f"tiles={candidate.tile_count} edges={candidate.edge_count} "
                            f"sym={candidate.symmetry_order} profiles={len(evaluation.profiles)} "
                            f"source={candidate.source_map_name or 'generated'}",
                            flush=True,
                        )
                    print(
                        f"g{generation} {candidate.graph_id} "
                        f"n={candidate.tile_count} e={candidate.edge_count} "
                        f"sym={candidate.symmetry_order} stage={evaluation.stage_name} "
                        f"profiles={len(evaluation.profiles)} wall={evaluation.elapsed_seconds:.2f}s "
                        f"origin={candidate.origin}",
                        flush=True,
                    )
                    if evaluation.stop_reason == "keyboard_interrupt":
                        raise KeyboardInterrupt

                feedback = read_learning_feedback(self.output)
                metrics = model.train(
                    observations,
                    steps=int(self.learning.get("steps_per_generation", 8)),
                    batch_size=int(self.learning.get("batch_size", 16)),
                    generation=generation,
                    feedback=feedback,
                )
                model.save(self.output / "model.pt")
                if self.mapping_learning_enabled:
                    mapping_metrics = mapping_model.train(
                        mapping_observations,
                        steps=int(
                            self.mapping_learning.get("steps_per_generation", 8)
                        ),
                        batch_size=int(self.mapping_learning.get("batch_size", 16)),
                        generation=generation,
                        feedback=feedback,
                    )
                    mapping_model.save(self.output / "mapping_model.pt")
                    _append_jsonl(
                        self.output / "mapping_training_metrics.jsonl",
                        self._mapping_generation_metrics(
                            generation,
                            generation_mapping_records,
                            mapping_metrics,
                        ),
                    )
                else:
                    mapping_metrics = mapping_model.metrics(
                        mapping_observations, feedback=feedback
                    )
                if self.weak_order_learning_enabled:
                    weak_order_metrics = weak_order_model.train(
                        weak_order_rollouts,
                        steps=int(
                            self.weak_order_learning.get(
                                "steps_per_generation", 8
                            )
                        ),
                        batch_size=int(
                            self.weak_order_learning.get("batch_size", 16)
                        ),
                        generation=generation,
                        feedback=feedback,
                    )
                    weak_order_model.save(
                        self.output / "weak_order_model.pt"
                    )
                    _append_jsonl(
                        self.output / "weak_order_training_metrics.jsonl",
                        self._weak_order_generation_metrics(
                            generation,
                            generation_weak_order_records,
                            weak_order_metrics,
                        ),
                    )
                else:
                    weak_order_metrics = weak_order_model.metrics(
                        weak_order_rollouts, feedback=feedback
                    )
                if self.specialization_learning_enabled:
                    specialization_metrics = specialization_model.train(
                        specialization_pools,
                        steps=int(
                            self.specialization_learning.get(
                                "steps_per_generation", 8
                            )
                        ),
                        batch_size=int(
                            self.specialization_learning.get("batch_size", 16)
                        ),
                        generation=generation,
                    )
                    specialization_model.save(
                        self.output / "specialization_model.pt"
                    )
                    _append_jsonl(
                        self.output / "specialization_training_metrics.jsonl",
                        self._specialization_generation_metrics(
                            generation,
                            generation_specialization_records,
                            specialization_metrics,
                        ),
                    )
                else:
                    specialization_metrics = specialization_model.metrics(
                        specialization_pools
                    )
                _append_jsonl(
                    self.output / "training_metrics.jsonl",
                    self._generation_metrics(
                        generation, generation_records, metrics
                    ),
                )
                coverage = build_generation_coverage(
                    generation,
                    graph_pool=generation_graph_pool,
                    graph_records=generation_records,
                    mapping_pool=generation_mapping_pool,
                    mapping_records=generation_mapping_records,
                    weak_rollouts=generation_weak_order_records,
                    seen_graph_ids=seen_graph_ids,
                    seen_mapping_ids=seen_mapping_ids,
                    seen_trajectory_ids=seen_trajectory_ids,
                )
                _append_jsonl(
                    self.output / "rollout_coverage_metrics.jsonl", coverage
                )
                seen_graph_ids.update(
                    evaluation.candidate.graph_id
                    for evaluation, _selection in generation_records
                )
                seen_mapping_ids.update(
                    evaluation.proposal.mapping_id
                    for evaluation, _selection in generation_mapping_records
                )
                seen_trajectory_ids.update(
                    weak_trajectory_id(rollout)
                    for rollout in generation_weak_order_records
                )
                if self._output_budget_reached():
                    stop_reason = "max_training_output_bytes"
                _atomic_json(
                    self.output / "state.json",
                    {
                        "schema_version": "graph-lab-state-v1",
                        "fingerprint": self.fingerprint,
                        "exclude_rings": self.exclude_rings,
                        "tile_counts": list(self.space.tile_counts),
                        "stein_symmetric": self.stein_symmetric,
                        "symmetry_orders": (
                            list(self.space.symmetry_orders)
                            if self.space.symmetry_orders is not None
                            else None
                        ),
                        "next_generation": generation + 1,
                        "observations": len(observations),
                        "mapping_observations": mapping_observation_count,
                        "weak_order_rollouts": weak_order_rollout_count,
                        "specialization_pools": specialization_pool_count,
                    },
                )
                report = self._report(
                    observations,
                    model,
                    generation,
                    stop_reason=(
                        stop_reason
                        if stop_reason == "max_training_output_bytes"
                        else (
                            "completed"
                            if generation + 1 >= total_generations
                            else "running"
                        )
                    ),
                    model_metrics=metrics,
                )
                last_generation = generation
                print(
                    f"generation {generation} complete: evaluated={len(generation_evaluations)} "
                    f"total-visits={len(observations)} "
                    f"unique-graphs={report['unique_graphs_evaluated']} "
                    f"geometry-visits={report['geometry_ready_evaluations']} "
                    f"geometry-graphs={report['geometry_ready_unique_graphs']} "
                    f"graph_examples={metrics['examples']} "
                    f"mapping_examples={mapping_metrics['examples']}",
                    f" weak_rollouts={weak_order_metrics.get('rollouts', 0)}",
                    f" specialization_pools={specialization_metrics.get('pools', 0)}",
                    flush=True,
                )
                if stop_reason == "max_training_output_bytes":
                    print(
                        "[OUTPUT BUDGET] Graph Lab stopped cleanly at "
                        f"{self._training_output_bytes() / (1024 * 1024):.2f} MiB.",
                        flush=True,
                    )
                    break
        except KeyboardInterrupt:
            stop_reason = "keyboard_interrupt"
            print("Graph Lab interrupted; completed observations are already durable.", flush=True)
            model.save(self.output / "model.pt")
            if self.mapping_learning_enabled:
                mapping_model.save(self.output / "mapping_model.pt")
            if self.weak_order_learning_enabled:
                weak_order_model.save(self.output / "weak_order_model.pt")
            if self.specialization_learning_enabled:
                specialization_model.save(self.output / "specialization_model.pt")
            self._report(
                observations,
                model,
                last_generation,
                stop_reason=stop_reason,
            )

        geometry_graphs = len(
            {
                item.candidate.graph_id
                for item in observations
                if item.stage_index >= len(GRAPH_STAGES) - 1
            }
        )
        return GraphLabResult(
            output_directory=self.output,
            generations_completed=max(0, last_generation + 1),
            observations=len(observations),
            geometry_ready_graphs=geometry_graphs,
            stop_reason=stop_reason,
        )
