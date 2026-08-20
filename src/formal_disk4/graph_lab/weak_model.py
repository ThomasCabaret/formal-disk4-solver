from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from formal_disk4.enumeration.weak_policy import (
    WeakOrderActionView,
    WeakOrderBranchPolicy,
    WeakOrderStateView,
)
from formal_disk4.pipeline.filter_report import (
    FILTER_SPECS,
    LEARNING_FILTER_IDS,
    FilterObservation,
    FilterReport,
)
from formal_disk4.pipeline.output import atomic_replace

from .mapping import MappingProposal
from .mapping_model import EDGE_FEATURES, mapping_tensors
from .curriculum import build_curriculum, curriculum_utility, normalized_cost
from .feedback import LearningFeedback, VALUE_TARGET_IDS, balanced_binary_weights
from .model import GLOBAL_FEATURES, NODE_FEATURES

try:
    import torch
    from torch import nn
except ImportError as error:  # pragma: no cover
    raise RuntimeError(
        "Graph Lab weak-order learning requires PyTorch. Install the project "
        "with `pip install -e .[graph-lab]`."
    ) from error


MODEL_VERSION = "graph-lab-weak-order-ranker-v3-reach-curriculum"
WEAK_NODE_FEATURES = 13
WEAK_GLOBAL_FEATURES = 10


@dataclass(frozen=True)
class WeakOrderDecisionObservation:
    state: WeakOrderStateView
    action: WeakOrderActionView
    candidate_count: int
    selection_mode: str
    selection_probability: float
    policy_entropy: float
    predicted_conditional_probabilities: tuple[float, ...]
    predicted_reach_probabilities: tuple[float, ...]
    selection_score: float
    legal_mask_count: int = 0
    pooled_mask_count: int = 0

    def to_dict(self) -> dict[str, object]:
        state = self.state.to_dict()
        # The ordered decisions already are the path. Repeating the growing
        # path prefix in every state would make a rollout quadratic on disk.
        state.pop("path", None)
        return {
            "state": state,
            "action": self.action.to_dict(),
            "candidate_count": self.candidate_count,
            "legal_mask_count": self.legal_mask_count,
            "pooled_mask_count": self.pooled_mask_count,
            "selection_mode": self.selection_mode,
            "selection_probability": self.selection_probability,
            "policy_entropy": self.policy_entropy,
            "selection_score": self.selection_score,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, object]
    ) -> "WeakOrderDecisionObservation":
        return cls(
            state=WeakOrderStateView.from_dict(dict(payload["state"])),  # type: ignore[arg-type]
            action=WeakOrderActionView.from_dict(dict(payload["action"])),  # type: ignore[arg-type]
            candidate_count=int(payload.get("candidate_count", 1)),
            selection_mode=str(payload.get("selection_mode", "restored")),
            selection_probability=float(payload.get("selection_probability", 1.0)),
            policy_entropy=float(payload.get("policy_entropy", 0.0)),
            predicted_conditional_probabilities=tuple(
                float(value)
                for value in payload.get("predicted_conditional_probabilities", ())  # type: ignore[union-attr]
            ),
            predicted_reach_probabilities=tuple(
                float(value)
                for value in payload.get("predicted_reach_probabilities", ())  # type: ignore[union-attr]
            ),
            selection_score=float(payload.get("selection_score", 0.0)),
            legal_mask_count=int(
                payload.get("legal_mask_count", payload.get("candidate_count", 1))
            ),
            pooled_mask_count=int(
                payload.get("pooled_mask_count", payload.get("candidate_count", 1))
            ),
        )


@dataclass(frozen=True)
class WeakOrderRolloutObservation:
    proposal: MappingProposal
    decisions: tuple[WeakOrderDecisionObservation, ...]
    filters: FilterReport
    elapsed_seconds: float
    profile_count: int
    profile_ids: tuple[str, ...]
    selection_mode: str
    random_seed: int
    tainted: bool
    error: str | None = None

    @property
    def target_vector(self) -> tuple[float | None, ...]:
        return self.filters.target_vector()

    @property
    def reach_vector(self) -> tuple[float | None, ...]:
        """Whether this rollout actually invoked each instrumented filter."""

        if self.tainted:
            return tuple(None for _ in self.filters.observations)
        return tuple(
            1.0 if observation.entered else 0.0
            for observation in self.filters.observations
        )

    @property
    def deepest_filter_index(self) -> int:
        deepest = -1
        for index, observation in enumerate(self.filters.observations):
            if observation.entered or observation.passed:
                deepest = index
        return deepest

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "graph-lab-weak-order-rollout-v1",
            "proposal": self.proposal.to_dict(),
            "decisions": [decision.to_dict() for decision in self.decisions],
            "target_vector": list(self.target_vector),
            "reach_vector": list(self.reach_vector),
            "filter_counts": [
                [
                    item.entered,
                    item.passed,
                    item.rejected,
                    item.deferred,
                    item.errors,
                    item.unaccounted,
                ]
                for item in self.filters.observations
            ],
            "deepest_filter_index": self.deepest_filter_index,
            "elapsed_seconds": self.elapsed_seconds,
            "profile_count": self.profile_count,
            "profile_ids": list(self.profile_ids),
            "selection_mode": self.selection_mode,
            "random_seed": self.random_seed,
            "tainted": self.tainted,
            "error": self.error,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, object]
    ) -> "WeakOrderRolloutObservation":
        report = payload.get("filter_report")
        if isinstance(report, Mapping):
            filters = FilterReport.from_dict(report)
        else:
            raw_counts = payload.get("filter_counts", ())
            if not isinstance(raw_counts, Sequence) or isinstance(
                raw_counts, (str, bytes)
            ):
                raise ValueError("Weak-order rollout has no filter outcomes")
            rows = list(raw_counts)
            observations = []
            for index, spec in enumerate(FILTER_SPECS):
                row = rows[index] if index < len(rows) else ()
                values = (
                    list(row)
                    if isinstance(row, Sequence)
                    and not isinstance(row, (str, bytes))
                    else []
                )
                values.extend([0] * (6 - len(values)))
                observations.append(
                    FilterObservation(
                        spec.filter_id,
                        spec.block,
                        spec.label,
                        *(int(value) for value in values[:6]),
                    )
                )
            filters = FilterReport(tuple(observations))
        restored_decisions = []
        restored_path: list[int] = []
        for value in payload.get("decisions", ()):  # type: ignore[union-attr]
            raw_decision = dict(value)
            raw_state = dict(raw_decision["state"])
            # The writer omits the redundant growing prefix. Reconstruct it
            # from the preceding selected masks so resumed training sees the
            # same Markov state as live training.
            raw_state["path"] = list(restored_path)
            raw_decision["state"] = raw_state
            decision = WeakOrderDecisionObservation.from_dict(raw_decision)
            restored_decisions.append(decision)
            restored_path.append(decision.action.mask)
        return cls(
            proposal=MappingProposal.from_dict(payload["proposal"]),  # type: ignore[arg-type]
            decisions=tuple(restored_decisions),
            filters=filters,
            elapsed_seconds=float(payload.get("elapsed_seconds", 0.0)),
            profile_count=int(payload.get("profile_count", 0)),
            profile_ids=tuple(
                str(value) for value in payload.get("profile_ids", ())  # type: ignore[union-attr]
            ),
            selection_mode=str(payload.get("selection_mode", "restored")),
            random_seed=int(payload.get("random_seed", 0)),
            tainted=bool(payload.get("tainted", False)),
            error=str(payload["error"]) if payload.get("error") else None,
        )


def weak_action_tensors(
    proposal: MappingProposal,
    state: WeakOrderStateView,
    action: WeakOrderActionView,
    *,
    tile_scale: float,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Encode one state/action pair without graph-size-specific parameters."""

    tile_count = proposal.candidate.tile_count
    if not (
        len(state.counters)
        == len(state.targets)
        == len(action.next_counters)
        == tile_count
    ):
        raise ValueError("Weak-order counters do not align with graph tile nodes")
    rows = [tuple(0.0 for _ in range(WEAK_NODE_FEATURES))]
    for index, (counter, target, next_counter) in enumerate(
        zip(state.counters, state.targets, action.next_counters)
    ):
        denominator = max(1, int(target))
        current_fraction = float(counter) / denominator
        next_fraction = float(next_counter) / denominator
        current_angle = 2.0 * math.pi * current_fraction
        next_angle = 2.0 * math.pi * next_fraction
        rows.append(
            (
                current_fraction,
                float(max(0, target - counter)) / denominator,
                float(target) / max(1.0, float(tile_scale)),
                1.0 if state.available_mask & (1 << index) else 0.0,
                1.0 if action.mask >= 0 and action.mask & (1 << index) else 0.0,
                next_fraction,
                float(next_counter - counter) / denominator,
                1.0 if next_counter >= target else 0.0,
                math.sin(current_angle),
                math.cos(current_angle),
                math.sin(next_angle),
                math.cos(next_angle),
                1.0 if index == state.reference_index else 0.0,
            )
        )
    total = max(1, state.total_occurrences)
    tile_denominator = max(1, tile_count)
    equation_denominator = max(1, total * total)
    selected_tiles = (
        action.mask.bit_count() if action.mask >= 0 else action.selected_count
    )
    global_features = (
        float(state.placed_occurrences) / total,
        float(state.block_count) / total,
        float(state.resolved_length_equations) / equation_denominator,
        float(state.resolved_angle_equations) / equation_denominator,
        float(selected_tiles) / tile_denominator,
        float(action.new_length_equations) / equation_denominator,
        float(action.new_angle_equations) / equation_denominator,
        1.0 if state.cyclic_shift_half else 0.0,
        1.0 if action.mask < 0 else 0.0,
        float(state.available_mask.bit_count()) / tile_denominator,
    )
    return (
        torch.tensor(rows, dtype=torch.float32),
        torch.tensor(global_features, dtype=torch.float32),
    )


class WeakOrderActionNetwork(nn.Module):
    """Shared graph/mapping encoder plus a cheap state/action scoring head."""

    def __init__(self, hidden_size: int, message_layers: int) -> None:
        super().__init__()
        mapping_features = 8
        self.node_input = nn.Linear(
            NODE_FEATURES + mapping_features, hidden_size
        )
        self.message_layers = nn.ModuleList(
            nn.Linear(hidden_size + EDGE_FEATURES, hidden_size)
            for _ in range(max(1, int(message_layers)))
        )
        self.update_layers = nn.ModuleList(
            nn.Linear(2 * hidden_size, hidden_size)
            for _ in range(max(1, int(message_layers)))
        )
        self.global_input = nn.Linear(GLOBAL_FEATURES, hidden_size)
        self.mapping_trunk = nn.Sequential(
            nn.Linear(4 * hidden_size, 2 * hidden_size),
            nn.ReLU(),
            nn.Linear(2 * hidden_size, hidden_size),
            nn.ReLU(),
        )
        self.action_node = nn.Sequential(
            nn.Linear(hidden_size + WEAK_NODE_FEATURES, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, hidden_size),
            nn.ReLU(),
        )
        self.history_gru = nn.GRU(
            hidden_size + 1, hidden_size, batch_first=True
        )
        self.action_trunk = nn.Sequential(
            nn.Linear(5 * hidden_size + WEAK_GLOBAL_FEATURES, 2 * hidden_size),
            nn.ReLU(),
            nn.Linear(2 * hidden_size, hidden_size),
            nn.ReLU(),
        )
        self.filter_heads = nn.Linear(hidden_size, len(LEARNING_FILTER_IDS))
        self.reach_heads = nn.Linear(hidden_size, len(LEARNING_FILTER_IDS))
        self.value_heads = nn.Linear(hidden_size, len(VALUE_TARGET_IDS))
        self.cost_head = nn.Linear(hidden_size, 1)

    def encode_mapping(
        self,
        node_features: torch.Tensor,
        adjacency: torch.Tensor,
        global_features: torch.Tensor,
        outside_index: int,
        edge_features: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        hidden = torch.relu(self.node_input(node_features))
        node_count = len(hidden)
        for message_layer, update_layer in zip(
            self.message_layers, self.update_layers
        ):
            sources = hidden.unsqueeze(0).expand(node_count, node_count, -1)
            messages = torch.relu(
                message_layer(torch.cat((sources, edge_features), dim=2))
            )
            messages = (messages * adjacency.unsqueeze(2)).sum(dim=1)
            hidden = torch.relu(
                update_layer(torch.cat((hidden, messages), dim=1))
            ) + hidden
        tile_mask = torch.ones(len(hidden), dtype=torch.bool, device=hidden.device)
        tile_mask[outside_index] = False
        tiles = hidden[tile_mask]
        pooled = torch.cat(
            (
                tiles.mean(dim=0),
                tiles.max(dim=0).values,
                hidden[outside_index],
                torch.relu(self.global_input(global_features)),
            )
        )
        return hidden, tile_mask, self.mapping_trunk(pooled)

    def score_actions(
        self,
        encoded: tuple[torch.Tensor, torch.Tensor, torch.Tensor],
        weak_nodes: torch.Tensor,
        weak_globals: torch.Tensor,
        history_masks: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        hidden, tile_mask, mapping_representation = encoded
        tile_hidden = hidden[tile_mask]
        if len(history_masks):
            counts = history_masks.sum(dim=1, keepdim=True).clamp_min(1.0)
            block_embeddings = history_masks @ tile_hidden / counts
            history_inputs = torch.cat(
                (block_embeddings, counts / max(1, len(tile_hidden))), dim=1
            ).unsqueeze(0)
            _sequence, history_state = self.history_gru(history_inputs)
            history_representation = history_state[-1, 0]
        else:
            history_representation = torch.zeros_like(mapping_representation)
        action_hidden = self.action_node(
            torch.cat(
                (
                    hidden.unsqueeze(0).expand(len(weak_nodes), -1, -1),
                    weak_nodes,
                ),
                dim=2,
            )
        )
        tiles = action_hidden[:, tile_mask, :]
        selected = weak_nodes[:, tile_mask, 4].unsqueeze(2)
        selected_pool = (tiles * selected).sum(dim=1) / selected.sum(
            dim=1
        ).clamp_min(1.0)
        pooled = torch.cat(
            (
                tiles.mean(dim=1),
                tiles.max(dim=1).values,
                selected_pool,
                mapping_representation.unsqueeze(0).expand(len(weak_nodes), -1),
                history_representation.unsqueeze(0).expand(len(weak_nodes), -1),
                weak_globals,
            ),
            dim=1,
        )
        representation = self.action_trunk(pooled)
        return (
            self.filter_heads(representation),
            self.reach_heads(representation),
            self.value_heads(representation),
            self.cost_head(representation).squeeze(1),
        )


@dataclass(frozen=True)
class WeakOrderPrediction:
    conditional_probabilities: tuple[float, ...]
    reach_probabilities: tuple[float, ...]
    value_probabilities: tuple[float, ...]
    auxiliary_progress: float
    expected_seconds: float

    @property
    def terminal_probability(self) -> float:
        return self.value_probabilities[0]


class WeakOrderLearningModel:
    def __init__(self, config: Mapping[str, object]) -> None:
        self.config = dict(config)
        self.seed = int(config.get("seed", 20260811))
        self.tile_scale = max(1.0, float(config.get("tile_feature_scale", 13.0)))
        torch.manual_seed(self.seed)
        torch.set_num_threads(max(1, int(config.get("torch_threads", 1))))
        self.network = WeakOrderActionNetwork(
            hidden_size=max(8, int(config.get("hidden_size", 64))),
            message_layers=max(1, int(config.get("message_layers", 3))),
        )
        self.optimizer = torch.optim.AdamW(
            self.network.parameters(),
            lr=float(config.get("learning_rate", 0.001)),
            weight_decay=float(config.get("weight_decay", 1e-4)),
        )
        self.active_heads = np.zeros(len(LEARNING_FILTER_IDS), dtype=bool)
        self.pass_supports = np.zeros(len(LEARNING_FILTER_IDS), dtype=np.int64)
        self.empirical_rates = np.full(
            len(LEARNING_FILTER_IDS), 0.5, dtype=np.float32
        )
        self.active_reach_heads = np.zeros(len(LEARNING_FILTER_IDS), dtype=bool)
        self.reach_supports = np.zeros(len(LEARNING_FILTER_IDS), dtype=np.int64)
        self.empirical_reach_rates = np.full(
            len(LEARNING_FILTER_IDS), 0.5, dtype=np.float32
        )
        self.best_filter_auc = np.full(len(LEARNING_FILTER_IDS), np.nan)
        self.best_reach_auc = np.full(len(LEARNING_FILTER_IDS), np.nan)
        self.active_value_heads = np.zeros(len(VALUE_TARGET_IDS), dtype=bool)
        self.empirical_value_rates = np.full(
            len(VALUE_TARGET_IDS), 0.5, dtype=np.float32
        )

    @staticmethod
    def _is_validation(observation: WeakOrderRolloutObservation) -> bool:
        # Split by complete graph, not decision or mapping. Validation therefore
        # measures whether local ordering knowledge transfers to unseen graphs.
        digest = hashlib.sha256(
            observation.proposal.candidate.graph_id.encode("utf-8")
        ).digest()
        return digest[0] < 51

    def _partitions(
        self, observations: Sequence[WeakOrderRolloutObservation]
    ) -> tuple[list[WeakOrderRolloutObservation], list[WeakOrderRolloutObservation]]:
        training = [item for item in observations if not self._is_validation(item)]
        validation = [item for item in observations if self._is_validation(item)]
        if not training:
            return list(observations), []
        return training, validation

    def _refresh_statistics(
        self, observations: Sequence[WeakOrderRolloutObservation]
    ) -> None:
        for head in range(len(LEARNING_FILTER_IDS)):
            labels = [
                item.target_vector[head]
                for item in observations
                if item.decisions and item.target_vector[head] is not None
            ]
            positive = sum(float(value) for value in labels)
            negative = len(labels) - positive
            self.pass_supports[head] = len(labels)
            self.active_heads[head] = positive > 0.0 and negative > 0.0
            self.empirical_rates[head] = float(
                (positive + 0.5) / (len(labels) + 1.0)
            )
            reach_labels = [
                item.reach_vector[head]
                for item in observations
                if item.decisions and item.reach_vector[head] is not None
            ]
            reach_positive = sum(reach_labels)
            reach_negative = len(reach_labels) - reach_positive
            self.reach_supports[head] = len(reach_labels)
            self.active_reach_heads[head] = (
                reach_positive > 0.0 and reach_negative > 0.0
            )
            self.empirical_reach_rates[head] = float(
                (reach_positive + 0.5) / (len(reach_labels) + 1.0)
            )

    def _value_targets(
        self,
        rollout: WeakOrderRolloutObservation,
        feedback: LearningFeedback,
    ) -> tuple[float | None, ...]:
        return feedback.targets(
            candidate=rollout.proposal.candidate,
            profile_count=rollout.profile_count,
            profile_ids=rollout.profile_ids,
        )

    def _refresh_value_statistics(
        self,
        observations: Sequence[WeakOrderRolloutObservation],
        feedback: LearningFeedback,
    ) -> None:
        targets = [self._value_targets(item, feedback) for item in observations]
        for head in range(len(VALUE_TARGET_IDS)):
            labels = [row[head] for row in targets if row[head] is not None]
            positive = sum(float(value) for value in labels)
            negative = len(labels) - positive
            self.active_value_heads[head] = positive > 0.0 and negative > 0.0
            self.empirical_value_rates[head] = float(
                (positive + 0.5) / (len(labels) + 1.0)
            )

    def curriculum_state(self):
        return build_curriculum(
            empirical_reach_rates=self.empirical_reach_rates,
            reach_supports=self.reach_supports,
            active_reach_heads=self.active_reach_heads,
            active_pass_heads=self.active_heads,
            config=self.config,
        )

    @property
    def has_policy_signal(self) -> bool:
        return bool(
            np.any(self.active_reach_heads)
            or np.any(self.active_heads)
            or np.any(self.active_value_heads)
        )

    def policy_score(self, prediction: WeakOrderPrediction) -> float:
        score = curriculum_utility(
            self.curriculum_state(),
            prediction.reach_probabilities,
            prediction.conditional_probabilities,
        )
        if self.active_value_heads[0]:
            score += float(self.config.get("terminal_profile_weight", 0.20)) * (
                prediction.value_probabilities[0]
            )
        if len(prediction.value_probabilities) > 1 and self.active_value_heads[1]:
            score += float(self.config.get("geometry_solution_weight", 0.20)) * (
                prediction.value_probabilities[1]
            )
        if len(prediction.value_probabilities) > 2 and self.active_value_heads[2]:
            score += float(self.config.get("nontrivial_solution_weight", 0.40)) * (
                prediction.value_probabilities[2]
            )
        score -= float(self.config.get("cost_weight", 0.01)) * normalized_cost(
            prediction.expected_seconds, self.config
        )
        return score

    @staticmethod
    def _history_masks(
        state: WeakOrderStateView, tile_count: int
    ) -> torch.Tensor:
        if not state.path:
            return torch.zeros((0, tile_count), dtype=torch.float32)
        return torch.tensor(
            [
                [1.0 if int(mask) & (1 << tile) else 0.0 for tile in range(tile_count)]
                for mask in state.path
            ],
            dtype=torch.float32,
        )

    def prepare_mapping(
        self, proposal: MappingProposal
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Cache the expensive graph/mapping message pass for one rollout."""

        self.network.eval()
        with torch.no_grad():
            return self.network.encode_mapping(
                *mapping_tensors(proposal, tile_scale=self.tile_scale)
            )

    def predict_many(
        self,
        proposal: MappingProposal,
        state: WeakOrderStateView,
        actions: Sequence[WeakOrderActionView],
        *,
        prepared_mapping: tuple[
            torch.Tensor, torch.Tensor, torch.Tensor
        ] | None = None,
    ) -> tuple[WeakOrderPrediction, ...]:
        if not actions:
            return ()
        self.network.eval()
        action_tensors = [
            weak_action_tensors(
                proposal, state, action, tile_scale=self.tile_scale
            )
            for action in actions
        ]
        with torch.no_grad():
            encoded = (
                prepared_mapping
                if prepared_mapping is not None
                else self.network.encode_mapping(
                    *mapping_tensors(proposal, tile_scale=self.tile_scale)
                )
            )
            logits, reach_logits, value_logits, log_costs = self.network.score_actions(
                encoded,
                torch.stack([item[0] for item in action_tensors]),
                torch.stack([item[1] for item in action_tensors]),
                self._history_masks(state, proposal.candidate.tile_count),
            )
            probabilities = torch.sigmoid(logits).cpu().numpy()
            reach_probabilities = torch.sigmoid(reach_logits).cpu().numpy()
            value_probabilities = torch.sigmoid(value_logits).cpu().numpy()
        probabilities[:, ~self.active_heads] = self.empirical_rates[
            ~self.active_heads
        ]
        reach_probabilities[:, ~self.active_reach_heads] = (
            self.empirical_reach_rates[~self.active_reach_heads]
        )
        value_probabilities[:, ~self.active_value_heads] = self.empirical_value_rates[
            ~self.active_value_heads
        ]
        results = []
        for row, reaches, values, log_cost in zip(
            probabilities, reach_probabilities, value_probabilities, log_costs
        ):
            active = reaches[self.active_reach_heads]
            results.append(
                WeakOrderPrediction(
                    conditional_probabilities=tuple(float(value) for value in row),
                    reach_probabilities=tuple(float(value) for value in reaches),
                    value_probabilities=tuple(float(value) for value in values),
                    auxiliary_progress=(
                        float(np.mean(active)) if len(active) else 0.5
                    ),
                    expected_seconds=max(
                        0.0,
                        math.expm1(
                            min(20.0, max(-20.0, float(log_cost.item())))
                        ),
                    ),
                )
            )
        return tuple(results)

    def train(
        self,
        observations: Sequence[WeakOrderRolloutObservation],
        *,
        steps: int,
        batch_size: int,
        generation: int,
        feedback: LearningFeedback | None = None,
    ) -> dict[str, object]:
        feedback = feedback or LearningFeedback.empty()
        replay_limit = max(1, int(self.config.get("replay_rollouts", 50000)))
        usable = [
            item for item in observations[-replay_limit:] if item.decisions
        ]
        if not usable:
            return self.metrics(observations, feedback=feedback)
        training, _validation = self._partitions(usable)
        self._refresh_statistics(training)
        self._refresh_value_statistics(training, feedback)
        value_targets = {
            id(item): self._value_targets(item, feedback) for item in training
        }
        filter_weights = balanced_binary_weights(
            tuple(item.target_vector for item in training),
            len(LEARNING_FILTER_IDS),
            maximum=float(self.config.get("maximum_class_weight", 50.0)),
        )
        reach_weights = balanced_binary_weights(
            tuple(item.reach_vector for item in training),
            len(LEARNING_FILTER_IDS),
            maximum=float(self.config.get("maximum_class_weight", 50.0)),
        )
        value_weights = balanced_binary_weights(
            tuple(value_targets.values()),
            len(VALUE_TARGET_IDS),
            maximum=float(self.config.get("maximum_class_weight", 50.0)),
        )
        state_groups: dict[
            tuple[str, WeakOrderStateView],
            list[tuple[WeakOrderRolloutObservation, WeakOrderDecisionObservation]],
        ] = defaultdict(list)
        ranking_window = training[-max(
            1, int(self.config.get("ranking_replay_rollouts", 10000))
        ):]
        for rollout in ranking_window:
            for decision in rollout.decisions:
                state_groups[(rollout.proposal.mapping_id, decision.state)].append(
                    (rollout, decision)
                )
        rankable: list[
            tuple[
                int,
                list[tuple[WeakOrderRolloutObservation, WeakOrderDecisionObservation]],
                list[tuple[WeakOrderRolloutObservation, WeakOrderDecisionObservation]],
            ]
        ] = []
        for values in state_groups.values():
            for head in range(len(VALUE_TARGET_IDS)):
                labelled = [
                    (item, value_targets[id(item[0])][head])
                    for item in values
                ]
                positive = [item for item, target in labelled if target == 1.0]
                negative = [item for item, target in labelled if target == 0.0]
                if positive and negative and any(
                    left[1].action.mask != right[1].action.mask
                    for left in positive
                    for right in negative
                ):
                    rankable.append((head, positive, negative))
        curriculum = self.curriculum_state()
        reach_rankable: list[
            tuple[
                tuple[WeakOrderRolloutObservation, WeakOrderDecisionObservation],
                tuple[WeakOrderRolloutObservation, WeakOrderDecisionObservation],
            ]
        ] = []
        if curriculum.frontier_index is not None:
            head = curriculum.frontier_index
            for values in state_groups.values():
                positives = [
                    item
                    for item in values
                    if item[0].reach_vector[head] is not None
                    and float(item[0].reach_vector[head]) > 0.5
                ]
                negatives = [
                    item
                    for item in values
                    if item[0].reach_vector[head] is not None
                    and float(item[0].reach_vector[head]) <= 0.5
                ]
                compatible = [
                    (positive, negative)
                    for positive in positives
                    for negative in negatives
                    if positive[1].action.mask != negative[1].action.mask
                ]
                if compatible:
                    reach_rankable.append(compatible[0])
        rng = random.Random(self.seed + int(generation) * 130363)
        losses: list[float] = []
        self.network.train()
        for _step in range(max(0, int(steps))):
            selected = [
                training[rng.randrange(len(training))]
                for _ in range(max(1, int(batch_size)))
            ]
            self.optimizer.zero_grad()
            loss = torch.tensor(0.0)
            terms = 0
            for rollout in selected:
                decision = rollout.decisions[rng.randrange(len(rollout.decisions))]
                weak_nodes, weak_globals = weak_action_tensors(
                    rollout.proposal,
                    decision.state,
                    decision.action,
                    tile_scale=self.tile_scale,
                )
                encoded = self.network.encode_mapping(
                    *mapping_tensors(
                        rollout.proposal, tile_scale=self.tile_scale
                    )
                )
                logits, reach_logits, value_logits, log_cost = self.network.score_actions(
                    encoded,
                    weak_nodes.unsqueeze(0),
                    weak_globals.unsqueeze(0),
                    self._history_masks(
                        decision.state, rollout.proposal.candidate.tile_count
                    ),
                )
                for head, target in enumerate(rollout.target_vector):
                    if target is None or not self.active_heads[head]:
                        continue
                    weight = (
                        filter_weights[head][0] * float(target)
                        + filter_weights[head][1] * (1.0 - float(target))
                    )
                    loss = loss + float(weight) * torch.nn.functional.binary_cross_entropy_with_logits(
                        logits[0, head],
                        torch.tensor(float(target), dtype=torch.float32),
                    )
                    terms += 1
                for head, target in enumerate(rollout.reach_vector):
                    if target is None or not self.active_reach_heads[head]:
                        continue
                    weight = (
                        reach_weights[head][0] * float(target)
                        + reach_weights[head][1] * (1.0 - float(target))
                    )
                    loss = loss + float(weight) * torch.nn.functional.binary_cross_entropy_with_logits(
                        reach_logits[0, head],
                        torch.tensor(float(target), dtype=torch.float32),
                    )
                    terms += 1
                for head, target in enumerate(
                    value_targets[id(rollout)]
                ):
                    if target is None or not self.active_value_heads[head]:
                        continue
                    weight = (
                        value_weights[head][0] * float(target)
                        + value_weights[head][1] * (1.0 - float(target))
                    )
                    loss = loss + float(weight) * torch.nn.functional.binary_cross_entropy_with_logits(
                        value_logits[0, head],
                        torch.tensor(float(target), dtype=torch.float32),
                    )
                    terms += 1
                loss = loss + float(self.config.get("cost_loss_weight", 0.02)) * (
                    torch.nn.functional.smooth_l1_loss(
                        log_cost[0],
                        torch.tensor(math.log1p(rollout.elapsed_seconds)),
                    )
                )
                terms += 1
            pair_amount = min(
                len(rankable),
                max(0, int(self.config.get("ranking_pairs_per_step", 4))),
            )
            if pair_amount:
                for head, positive, negative in rng.sample(rankable, pair_amount):
                    better_rollout, better_decision = positive[
                        rng.randrange(len(positive))
                    ]
                    worse_options = [
                        item
                        for item in negative
                        if item[1].action.mask != better_decision.action.mask
                    ]
                    if not worse_options:
                        continue
                    worse_rollout, worse_decision = worse_options[
                        rng.randrange(len(worse_options))
                    ]
                    pair_logits = []
                    for pair_rollout, pair_decision in (
                        (better_rollout, better_decision),
                        (worse_rollout, worse_decision),
                    ):
                        weak_nodes, weak_globals = weak_action_tensors(
                            pair_rollout.proposal,
                            pair_decision.state,
                            pair_decision.action,
                            tile_scale=self.tile_scale,
                        )
                        encoded = self.network.encode_mapping(
                            *mapping_tensors(
                                pair_rollout.proposal,
                                tile_scale=self.tile_scale,
                            )
                        )
                        _filters, _reaches, values, _cost = self.network.score_actions(
                            encoded,
                            weak_nodes.unsqueeze(0),
                            weak_globals.unsqueeze(0),
                            self._history_masks(
                                pair_decision.state,
                                pair_rollout.proposal.candidate.tile_count,
                            ),
                        )
                        pair_logits.append(values[0, head])
                    loss = loss + float(
                        self.config.get("ranking_loss_weight", 0.5)
                    ) * torch.nn.functional.softplus(
                        -(pair_logits[0] - pair_logits[1])
                    )
                    terms += 1
            reach_pair_amount = min(
                len(reach_rankable),
                max(0, int(self.config.get("curriculum_ranking_pairs_per_step", 4))),
            )
            if reach_pair_amount and curriculum.frontier_index is not None:
                head = curriculum.frontier_index
                for positive, negative in rng.sample(
                    reach_rankable, reach_pair_amount
                ):
                    pair_logits = []
                    for pair_rollout, pair_decision in (positive, negative):
                        weak_nodes, weak_globals = weak_action_tensors(
                            pair_rollout.proposal,
                            pair_decision.state,
                            pair_decision.action,
                            tile_scale=self.tile_scale,
                        )
                        encoded = self.network.encode_mapping(
                            *mapping_tensors(
                                pair_rollout.proposal,
                                tile_scale=self.tile_scale,
                            )
                        )
                        _passes, reaches, _values, _cost = self.network.score_actions(
                            encoded,
                            weak_nodes.unsqueeze(0),
                            weak_globals.unsqueeze(0),
                            self._history_masks(
                                pair_decision.state,
                                pair_rollout.proposal.candidate.tile_count,
                            ),
                        )
                        pair_logits.append(reaches[0, head])
                    loss = loss + float(
                        self.config.get("curriculum_ranking_loss_weight", 0.5)
                    ) * torch.nn.functional.softplus(
                        -(pair_logits[0] - pair_logits[1])
                    )
                    terms += 1
            loss = loss / max(1, terms)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.network.parameters(), 5.0)
            self.optimizer.step()
            losses.append(float(loss.detach().item()))
        metrics = self.metrics(observations, feedback=feedback)
        metrics["training_loss"] = float(np.mean(losses)) if losses else None
        metrics["training_replay_rollouts"] = len(training)
        return metrics

    @staticmethod
    def _auc(labels: np.ndarray, scores: np.ndarray) -> float | None:
        labels = np.asarray(labels, dtype=bool)
        positives = int(np.count_nonzero(labels))
        negatives = len(labels) - positives
        if not positives or not negatives:
            return None
        order = np.argsort(scores, kind="mergesort")
        ranks = np.empty(len(scores), dtype=np.float64)
        start = 0
        while start < len(order):
            end = start + 1
            while end < len(order) and scores[order[end]] == scores[order[start]]:
                end += 1
            ranks[order[start:end]] = 0.5 * (start + 1 + end)
            start = end
        return float(
            (ranks[labels].sum() - positives * (positives + 1) / 2)
            / (positives * negatives)
        )

    def metrics(
        self,
        observations: Sequence[WeakOrderRolloutObservation],
        *,
        feedback: LearningFeedback | None = None,
    ) -> dict[str, object]:
        feedback = feedback or LearningFeedback.empty()
        metric_rollouts = max(
            1, int(self.config.get("metric_rollouts", 5000))
        )
        usable = [
            item for item in observations[-metric_rollouts:] if item.decisions
        ]
        if not usable:
            return {
                "schema_version": "graph-lab-weak-order-metrics-v1",
                "rollouts": len(observations),
                "decisions": 0,
                "filters": {},
            }
        training, validation = self._partitions(usable)
        self._refresh_statistics(training)
        self._refresh_value_statistics(training, feedback)
        measured = validation if validation else training
        metric_limit = max(1, int(self.config.get("metric_decisions", 2048)))
        examples = list(
            deque(
                (
                    (rollout, decision)
                    for rollout in measured
                    for decision in rollout.decisions
                ),
                maxlen=metric_limit,
            )
        )
        prepared_by_rollout: dict[int, tuple[torch.Tensor, torch.Tensor, torch.Tensor]] = {}
        predictions = []
        for rollout, decision in examples:
            key = id(rollout)
            prepared = prepared_by_rollout.get(key)
            if prepared is None:
                prepared = self.prepare_mapping(rollout.proposal)
                prepared_by_rollout[key] = prepared
            predictions.append(
                self.predict_many(
                    rollout.proposal,
                    decision.state,
                    (decision.action,),
                    prepared_mapping=prepared,
                )[0]
            )
        filters: dict[str, object] = {}
        reach: dict[str, object] = {}
        for head, filter_id in enumerate(LEARNING_FILTER_IDS):
            eligible = [
                index
                for index, (rollout, _decision) in enumerate(examples)
                if rollout.target_vector[head] is not None
            ]
            labels = np.asarray(
                [float(examples[index][0].target_vector[head]) for index in eligible]
            )
            scores = np.asarray(
                [
                    predictions[index].conditional_probabilities[head]
                    for index in eligible
                ]
            )
            filter_auc = self._auc(labels >= 0.5, scores)
            filter_best = self.best_filter_auc[head]
            filters[filter_id] = {
                "eligible": len(eligible),
                "mean_conditional_pass_rate": (
                    float(np.mean(labels)) if len(labels) else None
                ),
                "mean_prediction": float(np.mean(scores)) if len(scores) else None,
                "binary_auc": filter_auc,
                "best_binary_auc": (
                    None if np.isnan(filter_best) else float(filter_best)
                ),
                "auc_regression": bool(
                    filter_auc is not None
                    and not np.isnan(filter_best)
                    and filter_auc + 0.05 < filter_best
                ),
                "brier_score": (
                    float(np.mean((scores - labels) ** 2)) if len(labels) else None
                ),
                "active": bool(self.active_heads[head]),
            }
            reach_eligible = [
                index
                for index, (rollout, _decision) in enumerate(examples)
                if rollout.reach_vector[head] is not None
            ]
            reach_labels = np.asarray(
                [float(examples[index][0].reach_vector[head]) for index in reach_eligible]
            )
            reach_scores = np.asarray(
                [predictions[index].reach_probabilities[head] for index in reach_eligible]
            )
            reach_auc = self._auc(reach_labels >= 0.5, reach_scores)
            reach_best = self.best_reach_auc[head]
            reach[filter_id] = {
                "eligible": len(reach_labels),
                "mean_reach_rate": (
                    float(np.mean(reach_labels)) if len(reach_labels) else None
                ),
                "mean_prediction": (
                    float(np.mean(reach_scores)) if len(reach_scores) else None
                ),
                "binary_auc": reach_auc,
                "best_binary_auc": (
                    None if np.isnan(reach_best) else float(reach_best)
                ),
                "auc_regression": bool(
                    reach_auc is not None
                    and not np.isnan(reach_best)
                    and reach_auc + 0.05 < reach_best
                ),
                "brier_score": (
                    float(np.mean((reach_scores - reach_labels) ** 2))
                    if len(reach_labels)
                    else None
                ),
                "active": bool(self.active_reach_heads[head]),
                "training_support": int(self.reach_supports[head]),
            }
            if filter_auc is not None:
                self.best_filter_auc[head] = (
                    filter_auc
                    if np.isnan(filter_best)
                    else max(float(filter_best), filter_auc)
                )
            if reach_auc is not None:
                self.best_reach_auc[head] = (
                    reach_auc
                    if np.isnan(reach_best)
                    else max(float(reach_best), reach_auc)
                )
        values: dict[str, object] = {}
        for head, value_id in enumerate(VALUE_TARGET_IDS):
            labels_and_scores = [
                (targets[head], prediction.value_probabilities[head])
                for (rollout, _decision), prediction in zip(examples, predictions)
                for targets in (self._value_targets(rollout, feedback),)
                if targets[head] is not None
            ]
            labels = np.asarray([float(item[0]) for item in labels_and_scores])
            scores = np.asarray([float(item[1]) for item in labels_and_scores])
            values[value_id] = {
                "eligible": len(labels),
                "mean_rate": float(np.mean(labels)) if len(labels) else None,
                "mean_prediction": float(np.mean(scores)) if len(scores) else None,
                "binary_auc": self._auc(labels >= 0.5, scores),
                "active": bool(self.active_value_heads[head]),
            }
        paired: dict[
            tuple[str, WeakOrderStateView],
            list[tuple[WeakOrderRolloutObservation, WeakOrderDecisionObservation, WeakOrderPrediction]],
        ] = defaultdict(list)
        for (rollout, decision), prediction in zip(examples, predictions):
            paired[(rollout.proposal.mapping_id, decision.state)].append(
                (rollout, decision, prediction)
            )
        pairwise: dict[str, object] = {}
        for head, value_id in enumerate(VALUE_TARGET_IDS):
            pair_total = 0
            pair_correct = 0
            for items in paired.values():
                labelled = [
                    (rollout, decision, prediction, self._value_targets(rollout, feedback)[head])
                    for rollout, decision, prediction in items
                ]
                positives = [item for item in labelled if item[3] == 1.0]
                negatives = [item for item in labelled if item[3] == 0.0]
                for positive in positives:
                    for negative in negatives:
                        if positive[1].action.mask == negative[1].action.mask:
                            continue
                        pair_total += 1
                        pair_correct += int(
                            positive[2].value_probabilities[head]
                            > negative[2].value_probabilities[head]
                        )
            pairwise[value_id] = {
                "pairs": pair_total,
                "accuracy": pair_correct / pair_total if pair_total else None,
                "scope": "same_mapping_and_state",
            }
        curriculum = self.curriculum_state()
        frontier_pairs = 0
        frontier_correct = 0
        if curriculum.frontier_index is not None:
            head = curriculum.frontier_index
            for items in paired.values():
                for left_index, left in enumerate(items):
                    for right in items[left_index + 1 :]:
                        left_target = left[0].reach_vector[head]
                        right_target = right[0].reach_vector[head]
                        if left_target is None or right_target is None:
                            continue
                        if abs(left_target - right_target) < 1e-9:
                            continue
                        if left[1].action.mask == right[1].action.mask:
                            continue
                        frontier_pairs += 1
                        left_score = left[2].reach_probabilities[head]
                        right_score = right[2].reach_probabilities[head]
                        frontier_correct += int(
                            (left_score - right_score) * (left_target - right_target) > 0
                        )
        return {
            "schema_version": "graph-lab-weak-order-metrics-v1",
            "rollouts": len(observations),
            "usable_rollouts": len(usable),
            "decisions": sum(len(item.decisions) for item in observations),
            "training_rollouts": len(training),
            "validation_rollouts": len(validation),
            "metric_partition": "validation" if validation else "training_fallback",
            "metric_decisions": len(examples),
            "filters": filters,
            "reach": reach,
            "values": values,
            "curriculum": {
                **curriculum.to_dict(),
                "within_state_pairs": frontier_pairs,
                "within_state_pair_accuracy": (
                    frontier_correct / frontier_pairs if frontier_pairs else None
                ),
                "learnable_reach_heads": int(np.count_nonzero(self.active_reach_heads)),
                "learnable_conditional_heads": int(np.count_nonzero(self.active_heads)),
            },
            "pairwise_ranking": pairwise,
            "within_state_pair_accuracy": pairwise["profile_emitted"]["accuracy"],
            "within_state_pairs": pairwise["profile_emitted"]["pairs"],
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        torch.save(
            {
                "version": MODEL_VERSION,
                "config": self.config,
                "network": self.network.state_dict(),
                "optimizer": self.optimizer.state_dict(),
                "active_heads": self.active_heads,
                "pass_supports": self.pass_supports,
                "empirical_rates": self.empirical_rates,
                "active_reach_heads": self.active_reach_heads,
                "reach_supports": self.reach_supports,
                "empirical_reach_rates": self.empirical_reach_rates,
                "best_filter_auc": self.best_filter_auc,
                "best_reach_auc": self.best_reach_auc,
                "active_value_heads": self.active_value_heads,
                "empirical_value_rates": self.empirical_value_rates,
            },
            temporary,
        )
        atomic_replace(temporary, path)

    @classmethod
    def load_or_create(
        cls, path: Path, config: Mapping[str, object]
    ) -> "WeakOrderLearningModel":
        result = cls(config)
        if not path.exists():
            return result
        payload = torch.load(path, map_location="cpu", weights_only=False)
        version = payload.get("version")
        if version != MODEL_VERSION:
            raise ValueError("Stored weak-order model is incompatible; use --restart")
        result.network.load_state_dict(payload["network"])
        result.optimizer.load_state_dict(payload["optimizer"])
        result.active_heads = np.asarray(payload["active_heads"], dtype=bool)
        result.pass_supports = np.asarray(payload["pass_supports"], dtype=np.int64)
        result.empirical_rates = np.asarray(
            payload["empirical_rates"], dtype=np.float32
        )
        result.active_reach_heads = np.asarray(
            payload["active_reach_heads"], dtype=bool
        )
        result.reach_supports = np.asarray(payload["reach_supports"], dtype=np.int64)
        result.empirical_reach_rates = np.asarray(
            payload["empirical_reach_rates"], dtype=np.float32
        )
        result.best_filter_auc = np.asarray(payload["best_filter_auc"], dtype=float)
        result.best_reach_auc = np.asarray(payload["best_reach_auc"], dtype=float)
        result.active_value_heads = np.asarray(
            payload["active_value_heads"], dtype=bool
        )
        result.empirical_value_rates = np.asarray(
            payload["empirical_value_rates"], dtype=np.float32
        )
        return result


class WeakOrderRankedPolicy(WeakOrderBranchPolicy):
    """One stochastic rollout: pool legal actions, rank them, sample one."""

    def __init__(
        self,
        proposal: MappingProposal,
        model: WeakOrderLearningModel,
        config: Mapping[str, object],
        *,
        random_seed: int,
        selection_mode: str,
    ) -> None:
        self.proposal = proposal
        self.model = model
        self.config = dict(config)
        self.random_seed = int(random_seed)
        self.selection_mode = str(selection_mode)
        self.rng = random.Random(self.random_seed)
        self.decisions: list[WeakOrderDecisionObservation] = []
        self.prepared_mapping = self.model.prepare_mapping(self.proposal)
        self._pool_sizes: dict[WeakOrderStateView, tuple[int, int]] = {}

    def propose_masks(
        self, state: WeakOrderStateView, masks: Sequence[int]
    ) -> Sequence[int]:
        limit = max(1, int(self.config.get("action_pool_size", 64)))
        legal_count = len(masks)
        if legal_count <= limit:
            values = tuple(int(mask) for mask in masks)
            self._pool_sizes[state] = (legal_count, len(values))
            return values
        # The control policy must genuinely be uniform over legal actions.
        # Hard-wiring the full mask and singleton masks into every bounded pool
        # gave those shapes orders of magnitude more mass on large graphs and
        # made the learned/control comparison misleading. The learned policy
        # now ranks a uniformly sampled candidate pool; every legal action has
        # the same positive probability of entering it.
        pooled = tuple(int(mask) for mask in self.rng.sample(masks, limit))
        self._pool_sizes[state] = (legal_count, len(pooled))
        return pooled

    @staticmethod
    def _distribution(scores: Sequence[float], temperature: float) -> np.ndarray:
        values = np.asarray(scores, dtype=np.float64)
        values = values / max(1e-3, float(temperature))
        values -= np.max(values)
        weights = np.exp(np.clip(values, -60.0, 0.0))
        return weights / max(1e-12, float(np.sum(weights)))

    def _score(self, prediction: WeakOrderPrediction) -> float:
        return self.model.policy_score(prediction)

    def select_actions(
        self,
        state: WeakOrderStateView,
        actions: Sequence[WeakOrderActionView],
    ) -> Sequence[int]:
        if not actions:
            return ()
        learned = self.selection_mode == "learned" and bool(
            self.model.has_policy_signal
        )
        if learned:
            predictions = self.model.predict_many(
                self.proposal,
                state,
                actions,
                prepared_mapping=self.prepared_mapping,
            )
            scores = [self._score(prediction) for prediction in predictions]
            learned_distribution = self._distribution(
                scores, float(self.config.get("temperature", 0.7))
            )
            epsilon = min(
                1.0, max(0.0, float(self.config.get("epsilon", 0.15)))
            )
            probabilities = (
                (1.0 - epsilon) * learned_distribution
                + epsilon / len(actions)
            )
            mode = "learned"
            chosen_index = self.rng.choices(
                range(len(actions)), weights=probabilities, k=1
            )[0]
            prediction = predictions[chosen_index]
            selection_score = scores[chosen_index]
        else:
            probabilities = np.full(len(actions), 1.0 / len(actions))
            mode = "exploration"
            chosen_index = self.rng.randrange(len(actions))
            # The control rollout is genuinely uniform.  Only score its chosen
            # action for diagnostics; scoring the whole pool cannot affect the
            # decision and used to waste most weak-policy inference time.
            prediction = self.model.predict_many(
                self.proposal,
                state,
                (actions[chosen_index],),
                prepared_mapping=self.prepared_mapping,
            )[0]
            selection_score = self._score(prediction)
        chosen = actions[chosen_index]
        legal_mask_count, pooled_mask_count = self._pool_sizes.pop(
            state, (len(actions), len(actions))
        )
        entropy = -float(
            np.sum(probabilities * np.log(np.maximum(probabilities, 1e-12)))
        )
        self.decisions.append(
            WeakOrderDecisionObservation(
                state=state,
                action=chosen,
                candidate_count=len(actions),
                selection_mode=mode,
                selection_probability=float(probabilities[chosen_index]),
                policy_entropy=entropy,
                predicted_conditional_probabilities=(
                    prediction.conditional_probabilities
                ),
                predicted_reach_probabilities=prediction.reach_probabilities,
                selection_score=float(selection_score),
                legal_mask_count=legal_mask_count,
                pooled_mask_count=pooled_mask_count,
            )
        )
        return (chosen.mask,)
