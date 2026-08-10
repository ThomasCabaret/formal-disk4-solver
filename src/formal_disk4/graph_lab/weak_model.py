from __future__ import annotations

import hashlib
import math
import random
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

from .mapping import MappingProposal
from .mapping_model import EDGE_FEATURES, mapping_tensors
from .model import GLOBAL_FEATURES, NODE_FEATURES

try:
    import torch
    from torch import nn
except ImportError as error:  # pragma: no cover
    raise RuntimeError(
        "Graph Lab weak-order learning requires PyTorch. Install the project "
        "with `pip install -e .[graph-lab]`."
    ) from error


MODEL_VERSION = "graph-lab-weak-order-ranker-v1"
WEAK_NODE_FEATURES = 12
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

    def to_dict(self) -> dict[str, object]:
        state = self.state.to_dict()
        # The ordered decisions already are the path. Repeating the growing
        # path prefix in every state would make a rollout quadratic on disk.
        state.pop("path", None)
        return {
            "state": state,
            "action": self.action.to_dict(),
            "candidate_count": self.candidate_count,
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
        )


@dataclass(frozen=True)
class WeakOrderRolloutObservation:
    proposal: MappingProposal
    decisions: tuple[WeakOrderDecisionObservation, ...]
    filters: FilterReport
    elapsed_seconds: float
    profile_count: int
    selection_mode: str
    random_seed: int
    tainted: bool
    error: str | None = None

    @property
    def target_vector(self) -> tuple[float | None, ...]:
        return self.filters.target_vector()

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
        return cls(
            proposal=MappingProposal.from_dict(payload["proposal"]),  # type: ignore[arg-type]
            decisions=tuple(
                WeakOrderDecisionObservation.from_dict(value)
                for value in payload.get("decisions", ())  # type: ignore[union-attr]
            ),
            filters=filters,
            elapsed_seconds=float(payload.get("elapsed_seconds", 0.0)),
            profile_count=int(payload.get("profile_count", 0)),
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
        self.action_trunk = nn.Sequential(
            nn.Linear(4 * hidden_size + WEAK_GLOBAL_FEATURES, 2 * hidden_size),
            nn.ReLU(),
            nn.Linear(2 * hidden_size, hidden_size),
            nn.ReLU(),
        )
        self.filter_heads = nn.Linear(hidden_size, len(LEARNING_FILTER_IDS))
        self.cost_head = nn.Linear(hidden_size, 1)

    def encode_mapping(
        self,
        node_features: torch.Tensor,
        adjacency: torch.Tensor,
        global_features: torch.Tensor,
        outside_index: int,
        edge_features: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
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
    ) -> tuple[torch.Tensor, torch.Tensor]:
        hidden, tile_mask, mapping_representation = encoded
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
                weak_globals,
            ),
            dim=1,
        )
        representation = self.action_trunk(pooled)
        return self.filter_heads(representation), self.cost_head(
            representation
        ).squeeze(1)


@dataclass(frozen=True)
class WeakOrderPrediction:
    conditional_probabilities: tuple[float, ...]
    reach_probabilities: tuple[float, ...]
    utility: float
    expected_seconds: float


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
        self.empirical_rates = np.full(
            len(LEARNING_FILTER_IDS), 0.5, dtype=np.float32
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
            self.active_heads[head] = positive > 0.0 and negative > 0.0
            self.empirical_rates[head] = float(
                (positive + 0.5) / (len(labels) + 1.0)
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
            logits, log_costs = self.network.score_actions(
                encoded,
                torch.stack([item[0] for item in action_tensors]),
                torch.stack([item[1] for item in action_tensors]),
            )
            probabilities = torch.sigmoid(logits).cpu().numpy()
        probabilities[:, ~self.active_heads] = self.empirical_rates[
            ~self.active_heads
        ]
        weights = np.asarray(
            self.config.get("filter_weights", [1.0] * len(LEARNING_FILTER_IDS)),
            dtype=np.float32,
        )
        if len(weights) != len(LEARNING_FILTER_IDS):
            weights = np.ones(len(LEARNING_FILTER_IDS), dtype=np.float32)
        results = []
        for row, log_cost in zip(probabilities, log_costs):
            reach = np.cumprod(row)
            results.append(
                WeakOrderPrediction(
                    conditional_probabilities=tuple(float(value) for value in row),
                    reach_probabilities=tuple(float(value) for value in reach),
                    utility=float(np.sum(weights * reach)),
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
    ) -> dict[str, object]:
        usable = [item for item in observations if item.decisions]
        if not usable:
            return self.metrics(observations)
        training, _validation = self._partitions(usable)
        replay_limit = max(1, int(self.config.get("replay_rollouts", 50000)))
        training = training[-replay_limit:]
        self._refresh_statistics(training)
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
                logits, log_cost = self.network.score_actions(
                    encoded, weak_nodes.unsqueeze(0), weak_globals.unsqueeze(0)
                )
                for head, target in enumerate(rollout.target_vector):
                    if target is None or not self.active_heads[head]:
                        continue
                    loss = loss + torch.nn.functional.binary_cross_entropy_with_logits(
                        logits[0, head],
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
            loss = loss / max(1, terms)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.network.parameters(), 5.0)
            self.optimizer.step()
            losses.append(float(loss.detach().item()))
        metrics = self.metrics(observations)
        metrics["training_loss"] = float(np.mean(losses)) if losses else None
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
        self, observations: Sequence[WeakOrderRolloutObservation]
    ) -> dict[str, object]:
        usable = [item for item in observations if item.decisions]
        if not usable:
            return {
                "schema_version": "graph-lab-weak-order-metrics-v1",
                "rollouts": len(observations),
                "decisions": 0,
                "filters": {},
            }
        training, validation = self._partitions(usable)
        self._refresh_statistics(training)
        measured = validation if validation else training
        metric_limit = max(1, int(self.config.get("metric_decisions", 2048)))
        examples = [
            (rollout, decision)
            for rollout in measured
            for decision in rollout.decisions
        ][-metric_limit:]
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
            filters[filter_id] = {
                "eligible": len(eligible),
                "mean_conditional_pass_rate": (
                    float(np.mean(labels)) if len(labels) else None
                ),
                "mean_prediction": float(np.mean(scores)) if len(scores) else None,
                "binary_auc": self._auc(labels >= 0.5, scores),
                "active": bool(self.active_heads[head]),
            }
        return {
            "schema_version": "graph-lab-weak-order-metrics-v1",
            "rollouts": len(observations),
            "usable_rollouts": len(usable),
            "decisions": sum(len(item.decisions) for item in observations),
            "training_rollouts": len(training),
            "validation_rollouts": len(validation),
            "metric_partition": "validation" if validation else "training_fallback",
            "filters": filters,
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
                "empirical_rates": self.empirical_rates,
            },
            temporary,
        )
        temporary.replace(path)

    @classmethod
    def load_or_create(
        cls, path: Path, config: Mapping[str, object]
    ) -> "WeakOrderLearningModel":
        result = cls(config)
        if not path.exists():
            return result
        payload = torch.load(path, map_location="cpu", weights_only=False)
        if payload.get("version") != MODEL_VERSION:
            raise ValueError("Stored weak-order model is incompatible; use --restart")
        result.network.load_state_dict(payload["network"])
        result.optimizer.load_state_dict(payload["optimizer"])
        result.active_heads = np.asarray(payload["active_heads"], dtype=bool)
        result.empirical_rates = np.asarray(
            payload["empirical_rates"], dtype=np.float32
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

    def propose_masks(
        self, state: WeakOrderStateView, masks: Sequence[int]
    ) -> Sequence[int]:
        values = tuple(int(mask) for mask in masks)
        limit = max(1, int(self.config.get("action_pool_size", 64)))
        if len(values) <= limit:
            return values
        # The control policy must genuinely be uniform over legal actions.
        # Hard-wiring the full mask and singleton masks into every bounded pool
        # gave those shapes orders of magnitude more mass on large graphs and
        # made the learned/control comparison misleading. The learned policy
        # now ranks a uniformly sampled candidate pool; every legal action has
        # the same positive probability of entering it.
        return tuple(self.rng.sample(values, limit))

    @staticmethod
    def _distribution(scores: Sequence[float], temperature: float) -> np.ndarray:
        values = np.asarray(scores, dtype=np.float64)
        values = values / max(1e-3, float(temperature))
        values -= np.max(values)
        weights = np.exp(np.clip(values, -60.0, 0.0))
        return weights / max(1e-12, float(np.sum(weights)))

    def _score(self, prediction: WeakOrderPrediction) -> float:
        active = np.flatnonzero(self.model.active_heads)
        if not len(active):
            return 0.0
        frontier = int(active[-1])
        # p(reach frontier) is the product of all conditional transition
        # probabilities up to it. Ordering by its logarithm prevents a strong
        # late head from hiding a weak prerequisite gate.
        score = math.log(
            max(1e-12, prediction.reach_probabilities[frontier])
        )
        score += float(self.config.get("deeper_utility_weight", 0.05)) * (
            prediction.utility
        )
        score -= float(self.config.get("cost_weight", 0.01)) * math.log1p(
            prediction.expected_seconds
        )
        return score

    def select_actions(
        self,
        state: WeakOrderStateView,
        actions: Sequence[WeakOrderActionView],
    ) -> Sequence[int]:
        if not actions:
            return ()
        predictions = self.model.predict_many(
            self.proposal,
            state,
            actions,
            prepared_mapping=self.prepared_mapping,
        )
        learned = self.selection_mode == "learned" and bool(
            np.any(self.model.active_heads)
        )
        scores = [self._score(prediction) for prediction in predictions]
        if learned:
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
        else:
            probabilities = np.full(len(actions), 1.0 / len(actions))
            mode = "exploration"
        chosen_index = self.rng.choices(
            range(len(actions)), weights=probabilities, k=1
        )[0]
        chosen = actions[chosen_index]
        prediction = predictions[chosen_index]
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
                selection_score=float(scores[chosen_index]),
            )
        )
        return (chosen.mask,)
