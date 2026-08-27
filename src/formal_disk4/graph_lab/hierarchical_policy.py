from __future__ import annotations

import random
from collections import defaultdict
from typing import Mapping, Sequence

import numpy as np

from formal_disk4.pipeline.filter_report import LEARNING_FILTER_IDS

from .evaluator import GraphEvaluation, GraphFormalEvaluator
from .mapping import MappingEvaluation, MappingProposal
from .mapping_model import MappingLearningModel
from .rollout_audit import weak_trajectory_id
from .run_store import GraphLabRunStore
from .space import DualGraphCandidate
from .specialization_model import (
    SpecializationLearningModel,
    SpecializationPoolObservation,
)
from .weak_model import WeakOrderLearningModel, WeakOrderRolloutObservation


class HierarchicalPolicyRuntime:
    """Optional mapping, weak-order, and specialization policy execution."""

    def __init__(
        self,
        evaluator: GraphFormalEvaluator,
        store: GraphLabRunStore,
        *,
        mapping_sampling: Mapping[str, object],
        weak_order_sampling: Mapping[str, object],
        specialization_sampling: Mapping[str, object],
        mapping_learning_enabled: bool,
        weak_order_learning_enabled: bool,
        specialization_learning_enabled: bool,
    ) -> None:
        self.evaluator = evaluator
        self.store = store
        self.mapping_sampling = mapping_sampling
        self.weak_order_sampling = weak_order_sampling
        self.specialization_sampling = specialization_sampling
        self.mapping_learning_enabled = mapping_learning_enabled
        self.weak_order_learning_enabled = weak_order_learning_enabled
        self.specialization_learning_enabled = specialization_learning_enabled

    def select_mappings(
        self,
        pool: Sequence[MappingProposal],
        model: MappingLearningModel | None,
        rng: random.Random,
        amount: int,
    ) -> list[tuple[MappingProposal, Mapping[str, object]]]:
        amount = min(max(1, int(amount)), len(pool))
        if model is None:
            return [
                (
                    proposal,
                    {
                        "selection_mode": "exploration",
                        "policy_mode": "prior",
                        "selection_score": None,
                        "predicted_conditional_probabilities": [],
                        "predicted_reach_probabilities": [],
                        "predicted_value_probabilities": [],
                        "predicted_seconds": None,
                        "ranking_target": "prior_only",
                        "curriculum": {"status": "disabled"},
                    },
                )
                for proposal in rng.sample(list(pool), amount)
            ]
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

    def evaluate(
        self,
        candidate: DualGraphCandidate,
        model: MappingLearningModel | None,
        weak_model: WeakOrderLearningModel | None,
        specialization_model: SpecializationLearningModel | None,
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
        selected = self.select_mappings(pool, model, rng, amount)
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
            self.store.append_jsonl("weak_order_rollouts.jsonl", payload)
            if observation.deepest_filter_index >= int(
                self.weak_order_sampling.get("preserve_from_filter_index", 21)
            ):
                self.store.append_jsonl(
                    "deep_weak_order_candidates.jsonl",
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
            self.store.append_jsonl("specialization_pools.jsonl", payload)
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
            if self.mapping_learning_enabled:
                self.store.append_jsonl("mapping_observations.jsonl", payload)
            if self.mapping_learning_enabled and evaluation.deepest_filter_index >= int(
                self.mapping_sampling.get("preserve_from_filter_index", 21)
            ):
                self.store.append_jsonl(
                    "deep_mapping_candidates.jsonl",
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

    def mapping_generation_metrics(
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

    def weak_order_generation_metrics(
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

    def specialization_generation_metrics(
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
