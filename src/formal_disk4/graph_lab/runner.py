from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from formal_disk4.pipeline.filter_report import LEARNING_FILTER_IDS

from .evaluator import GRAPH_STAGES, GraphEvaluation, GraphFormalEvaluator
from .isomorphism import IsomorphismIndex
from .mapping import MappingEvaluation, MappingProposal
from .mapping_model import MappingLearningModel
from .model import GraphLearningModel
from .rollout_audit import build_generation_coverage, weak_trajectory_id
from .space import DualGraphCandidate, GraphSpace, graph_feature_payload
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
    "state.json",
    "report.json",
    "report.md",
    "effective_config.json",
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
    records = []
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                records.append(value)
    return records


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

    def choose_parent(self, rng: random.Random) -> GraphEvaluation | None:
        nonempty = [values for values in self.cells.values() if values]
        if not nonempty:
            return None
        if rng.random() < 0.75:
            values = rng.choice(nonempty)
            weights = [max(0.1, self.reward(item) + 1.0) for item in values]
            return rng.choices(values, weights=weights, k=1)[0]
        all_values = [item for values in nonempty for item in values]
        weights = [max(0.1, self.reward(item) + 1.0) for item in all_values]
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
        self.evaluator = GraphFormalEvaluator(
            self.root, dict(config.get("evaluation", {}))
        )
        self.fingerprint = hashlib.sha256(
            json.dumps(self.config, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @classmethod
    def from_file(cls, root: Path, path: Path | str) -> "GraphLabRunner":
        source = Path(path)
        if not source.is_absolute():
            source = root / source
        config = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError("Graph Lab config must be a JSON object")
        return cls(root, config)

    def _restart(self) -> None:
        self.output.mkdir(parents=True, exist_ok=True)
        for name in RESTART_FILES:
            path = self.output / name
            if path.exists():
                path.unlink()

    def _load_observations(self) -> list[GraphEvaluation]:
        return [
            GraphEvaluation.from_dict(value)
            for value in _load_jsonl(self.output / "observations.jsonl")
        ]

    def _load_mapping_observations(self) -> list[MappingEvaluation]:
        return [
            MappingEvaluation.from_dict(value)
            for value in _load_jsonl(self.output / "mapping_observations.jsonl")
        ]

    def _load_weak_order_rollouts(self) -> list[WeakOrderRolloutObservation]:
        return [
            WeakOrderRolloutObservation.from_dict(value)
            for value in _load_jsonl(self.output / "weak_order_rollouts.jsonl")
        ]

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
        active_heads = [
            index for index, active in enumerate(model.active_heads) if active
        ]
        for proposal in pool:
            prediction = model.predict(proposal)
            utility = (
                math.log(
                    max(
                        1e-12,
                        prediction.reach_probabilities[active_heads[-1]],
                    )
                )
                if active_heads
                else 0.0
            ) - float(
                self.mapping_sampling.get("cost_weight", 0.02)
            ) * math.log1p(prediction.expected_seconds)
            scored.append((utility, proposal, prediction))
        scored.sort(key=lambda item: (-item[0], item[1].mapping_id))
        if not active_heads:
            selected = [
                (item, "exploration") for item in rng.sample(scored, amount)
            ]
        else:
            random_control = (
                rng.sample(scored, exploration) if exploration else []
            )
            control_ids = {item[1].mapping_id for item in random_control}
            learned = [
                item for item in scored if item[1].mapping_id not in control_ids
            ][: amount - exploration]
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
                    "predicted_seconds": prediction.expected_seconds,
                    "frontier_filter": (
                        LEARNING_FILTER_IDS[active_heads[-1]]
                        if active_heads
                        else None
                    ),
                },
            )
            for (score, proposal, prediction), mode in selected
        ]

    def _evaluate_with_mapping_ranker(
        self,
        candidate: DualGraphCandidate,
        model: MappingLearningModel,
        weak_model: WeakOrderLearningModel,
        rng: random.Random,
        generation: int,
    ) -> tuple[
        GraphEvaluation,
        list[tuple[MappingEvaluation, Mapping[str, object]]],
        list[WeakOrderRolloutObservation],
        tuple[MappingProposal, ...],
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

        def preserve_rollout(observation: WeakOrderRolloutObservation) -> None:
            payload = observation.to_dict()
            payload["generation"] = generation
            _append_jsonl(self.output / "weak_order_rollouts.jsonl", payload)
            if observation.deepest_filter_index >= int(
                self.weak_order_sampling.get("preserve_from_filter_index", 21)
            ):
                _append_jsonl(
                    self.output / "deep_weak_order_candidates.jsonl", payload
                )
            weak_records.append(observation)

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
            )
            payload = evaluation.to_dict()
            payload["generation"] = generation
            payload["selection"] = dict(metadata)
            _append_jsonl(self.output / "mapping_observations.jsonl", payload)
            if evaluation.deepest_filter_index >= int(
                self.mapping_sampling.get("preserve_from_filter_index", 21)
            ):
                _append_jsonl(self.output / "deep_mapping_candidates.jsonl", payload)
            records.append((evaluation, metadata))
        evaluations = [evaluation for evaluation, _metadata in records]
        return (
            self.evaluator.aggregate_mappings(candidate, evaluations),
            records,
            weak_records,
            pool,
        )

    def _mapping_generation_metrics(
        self,
        generation: int,
        records: Sequence[
            tuple[MappingEvaluation, Mapping[str, object]]
        ],
        model_metrics: Mapping[str, object],
    ) -> dict[str, object]:
        modes: dict[str, dict[str, object]] = {}
        for evaluation, selection in records:
            mode = str(selection.get("selection_mode", "unknown"))
            bucket = modes.setdefault(
                mode,
                {
                    "count": 0,
                    "filters": {
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
            assert isinstance(filters, dict)
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
        return {
            "schema_version": "graph-lab-mapping-generation-metrics-v1",
            "generation": generation,
            "evaluated": len(records),
            "geometry_ready": sum(
                bool(evaluation.profiles) for evaluation, _selection in records
            ),
            "filter_order": list(LEARNING_FILTER_IDS),
            "selection_modes": modes,
            "model": dict(model_metrics),
        }

    def _weak_order_generation_metrics(
        self,
        generation: int,
        records: Sequence[WeakOrderRolloutObservation],
        model_metrics: Mapping[str, object],
    ) -> dict[str, object]:
        modes: dict[str, dict[str, object]] = {}
        for rollout in records:
            bucket = modes.setdefault(
                rollout.selection_mode,
                {
                    "count": 0,
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
                },
            )
            bucket["count"] = int(bucket["count"]) + 1
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
            assert isinstance(filters, dict)
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
        return {
            "schema_version": "graph-lab-weak-order-generation-metrics-v1",
            "generation": generation,
            "evaluated": len(records),
            "geometry_ready": sum(item.profile_count > 0 for item in records),
            "filter_order": list(LEARNING_FILTER_IDS),
            "selection_modes": modes,
            "model": dict(model_metrics),
        }

    def _training_output_bytes(self) -> int:
        if not self.output.exists():
            return 0
        return sum(
            path.stat().st_size
            for path in self.output.iterdir()
            if path.is_file() and not path.name.endswith(".tmp")
        )

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
            parent = archive.choose_parent(rng) if rng.random() < mutation_fraction else None
            candidate = (
                self.space.mutate(parent.candidate, rng)
                if parent is not None
                else self.space.sample_prior(rng)
            )
            if candidate is None:
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
                novelty_weight=float(self.sampling.get("novelty_weight", 1.5)),
                cost_weight=float(self.sampling.get("cost_weight", 0.08)),
            )
            scored.append((score, candidate, prediction, novelty))
        scored.sort(key=lambda item: (-item[0], item[1].graph_id))
        if not any(bool(value) for value in model.active_heads):
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
        learned = [
            item for item in scored if item[1].graph_id not in control_ids
        ][:exploit]
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
            mode = str(
                selection.get(
                    "selection_mode",
                    "known_control"
                    if selection.get("selection") == "known_control"
                    else "unknown",
                )
            )
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
    ) -> dict[str, object]:
        stage_histogram = Counter(item.stage_name for item in observations)
        reached = {
            name: sum(item.stage_index >= index for item in observations)
            for index, name in enumerate(GRAPH_STAGES)
        }
        sizes = Counter(item.candidate.tile_count for item in observations)
        symmetries = Counter(item.candidate.symmetry_order for item in observations)
        origins = Counter(item.candidate.origin for item in observations)
        known = {
            item.candidate.source_map_name: {
                "graph_id": item.candidate.graph_id,
                "stage": item.stage_name,
                "profiles": int(item.counters.get("profiles_emitted", 0)),
                "stop_reason": item.stop_reason,
            }
            for item in observations
            if item.candidate.source_map_name is not None
        }
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
            "tile_count_histogram": dict(sorted(sizes.items())),
            "symmetry_order_histogram": dict(sorted(symmetries.items())),
            "origin_histogram": dict(origins),
            "diversity_cells": len(diversity_archive.cells),
            "diversity_cell_sizes": {
                name: len(values)
                for name, values in sorted(diversity_archive.cells.items())
            },
            "known_seed_results": known,
            "geometry_ready": geometry,
            "geometry_ready_evaluations": len(geometry),
            "geometry_ready_unique_graphs": unique_geometry_count,
            "model": model.metrics(observations),
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
            "## Pipeline depth",
            "",
            "| Stage reached | Count |",
            "|---|---:|",
        ]
        for name in GRAPH_STAGES:
            lines.append(f"| {name} | {reached[name]} |")
        lines.extend(
            [
                "",
                "## Known controls",
                "",
                "| Map | Deepest stage | Profiles | Stop reason |",
                "|---|---|---:|---|",
            ]
        )
        for name, value in sorted(known.items()):
            lines.append(
                f"| {name} | {value['stage']} | {value['profiles']} | {value['stop_reason']} |"
            )
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
            self._restart()
        self.output.mkdir(parents=True, exist_ok=True)
        _atomic_json(self.output / "effective_config.json", self.config)
        observations = self._load_observations()
        mapping_observations = self._load_mapping_observations()
        weak_order_rollouts = self._load_weak_order_rollouts()
        seen_graph_ids = {
            observation.candidate.graph_id for observation in observations
        }
        seen_mapping_ids = {
            observation.proposal.mapping_id for observation in mapping_observations
        }
        seen_trajectory_ids = {
            weak_trajectory_id(observation) for observation in weak_order_rollouts
        }
        # This index is consulted only once below to avoid re-running pending
        # explicit control seeds after resume. It is not passed to the proposal
        # generator and therefore never closes a sampled graph neighbourhood.
        evaluated_graph_index = IsomorphismIndex()
        for observation in observations:
            evaluated_graph_index.add(observation.candidate)
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
        if observations and not (self.output / "model.pt").exists():
            model.train(
                observations,
                steps=int(self.learning.get("bootstrap_steps", 100)),
                batch_size=int(self.learning.get("batch_size", 16)),
                generation=-1,
            )
        if mapping_observations and not (self.output / "mapping_model.pt").exists():
            mapping_model.train(
                mapping_observations,
                steps=int(self.mapping_learning.get("bootstrap_steps", 100)),
                batch_size=int(self.mapping_learning.get("batch_size", 16)),
                generation=-1,
            )
        if weak_order_rollouts and not (
            self.output / "weak_order_model.pt"
        ).exists():
            weak_order_model.train(
                weak_order_rollouts,
                steps=int(self.weak_order_learning.get("bootstrap_steps", 100)),
                batch_size=int(self.weak_order_learning.get("batch_size", 16)),
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
        pending_known = [
            candidate
            for candidate in self.space.known_seeds
            if evaluated_graph_index.equivalent(candidate) is None
        ]
        if self.max_training_bytes is None:
            disk_limit = "off"
        elif self.max_training_bytes >= 1024**3:
            disk_limit = f"{self.max_training_bytes / 1024**3:.2f}GiB"
        else:
            disk_limit = f"{self.max_training_bytes / 1024**2:.0f}MiB"
        print(
            f"graph-lab generations={start}..{total_generations - 1} "
            f"batch={target_batch} known-pending={len(pending_known)} "
            f"tiles<= {self.space.maximum_tiles} "
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
                known_quota = min(
                    len(pending_known),
                    target_batch,
                    max(0, int(self.sampling.get("known_seeds_per_generation", 2))),
                )
                selected: list[tuple[DualGraphCandidate, Mapping[str, object]]] = [
                    (
                        pending_known.pop(0),
                        {
                            "selection": "known_control",
                            "selection_mode": "known_control",
                        },
                    )
                    for _ in range(known_quota)
                ]
                generation_graph_pool: list[DualGraphCandidate] = []
                remaining = target_batch - len(selected)
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
                        ) = (
                            self._evaluate_with_mapping_ranker(
                                candidate,
                                mapping_model,
                                weak_order_model,
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
                    else:
                        evaluation = self.evaluator.evaluate(candidate)
                        new_mapping_observations = []
                        new_weak_order_records = []
                    mapping_observations.extend(new_mapping_observations)
                    weak_order_rollouts.extend(new_weak_order_records)
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

                metrics = model.train(
                    observations,
                    steps=int(self.learning.get("steps_per_generation", 8)),
                    batch_size=int(self.learning.get("batch_size", 16)),
                    generation=generation,
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
                    mapping_metrics = mapping_model.metrics(mapping_observations)
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
                        weak_order_rollouts
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
                        "next_generation": generation + 1,
                        "observations": len(observations),
                        "mapping_observations": len(mapping_observations),
                        "weak_order_rollouts": len(weak_order_rollouts),
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
