from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from formal_disk4.pipeline.filter_report import LEARNING_FILTER_IDS
from formal_disk4.pipeline.output import atomic_replace

from .mapping import MappingEvaluation, MappingProposal
from .curriculum import build_curriculum, curriculum_utility, normalized_cost
from .model import GLOBAL_FEATURES, NODE_FEATURES, graph_tensors
from .feedback import (
    LearningFeedback,
    VALUE_TARGET_IDS,
    balanced_binary_weights,
    formal_profile_ids,
)

try:
    import torch
    from torch import nn
except ImportError as error:  # pragma: no cover
    raise RuntimeError(
        "Graph Lab mapping learning requires PyTorch. Install the project with "
        "`pip install -e .[graph-lab]`."
    ) from error


MODEL_VERSION = "graph-lab-mapping-gnn-v3-reach-curriculum"
MAPPING_FEATURES = 8
EDGE_FEATURES = 8


def mapping_tensors(
    proposal: MappingProposal,
    *,
    tile_scale: float = 13.0,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, int, torch.Tensor]:
    """Encode a mapping on graph nodes with no graph-specific parameter table.

    Phase is represented periodically.  The GNN can consequently reuse the
    same local rules on graphs with different numbers of tiles and contour
    lengths.
    """

    nodes, adjacency, globals_, outside_index = graph_tensors(
        proposal.candidate, tile_scale=tile_scale
    )
    rows = [tuple(0.0 for _ in range(MAPPING_FEATURES))]
    for sign, offset, length in zip(
        proposal.orientation_signs,
        proposal.cyclic_offsets,
        proposal.contour_lengths,
    ):
        normalized = float(offset) / max(1, int(length))
        angle = 2.0 * math.pi * normalized
        rows.append(
            (
                1.0 if sign > 0 else 0.0,
                1.0 if sign < 0 else 0.0,
                math.sin(angle),
                math.cos(angle),
                normalized,
                float(length) / max(3.0, float(tile_scale)),
                1.0 if offset == 0 else 0.0,
                1.0,
            )
        )
    mapping_features = torch.tensor(rows, dtype=torch.float32)
    if len(mapping_features) != len(nodes):
        raise ValueError(
            "Mapping pieces do not align with the candidate graph tile nodes"
        )
    edge_features = torch.zeros(
        (len(nodes), len(nodes), EDGE_FEATURES), dtype=torch.float32
    )
    if len(proposal.edge_ports) != len(proposal.candidate.edges):
        raise ValueError("Mapping edge-port features do not align with graph edges")
    for edge, raw_features in zip(
        proposal.candidate.edges, proposal.edge_ports
    ):
        if len(raw_features) != EDGE_FEATURES:
            raise ValueError("A mapping edge needs eight port features")
        left, right = edge
        left_index = 0 if left == -1 else left + 1
        right_index = 0 if right == -1 else right + 1
        direct = torch.tensor(raw_features, dtype=torch.float32)
        reverse = torch.cat((direct[4:], direct[:4]))
        edge_features[left_index, right_index] = direct
        edge_features[right_index, left_index] = reverse
    return (
        torch.cat((nodes, mapping_features), dim=1),
        adjacency,
        globals_,
        outside_index,
        edge_features,
    )


class MappingGraphNetwork(nn.Module):
    def __init__(self, hidden_size: int, message_layers: int) -> None:
        super().__init__()
        self.node_input = nn.Linear(NODE_FEATURES + MAPPING_FEATURES, hidden_size)
        self.message_layers = nn.ModuleList(
            nn.Linear(hidden_size + EDGE_FEATURES, hidden_size)
            for _ in range(max(1, int(message_layers)))
        )
        self.update_layers = nn.ModuleList(
            nn.Linear(2 * hidden_size, hidden_size)
            for _ in range(max(1, int(message_layers)))
        )
        self.global_input = nn.Linear(GLOBAL_FEATURES, hidden_size)
        self.trunk = nn.Sequential(
            nn.Linear(4 * hidden_size, 2 * hidden_size),
            nn.ReLU(),
            nn.Linear(2 * hidden_size, hidden_size),
            nn.ReLU(),
        )
        self.filter_heads = nn.Linear(hidden_size, len(LEARNING_FILTER_IDS))
        self.reach_heads = nn.Linear(hidden_size, len(LEARNING_FILTER_IDS))
        self.value_heads = nn.Linear(hidden_size, len(VALUE_TARGET_IDS))
        self.cost_head = nn.Linear(hidden_size, 1)

    def forward(
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
            # Row i receives a message from column j. Edge attributes encode
            # the cyclic port as seen from i followed by the port as seen from j.
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
        representation = self.trunk(pooled)
        return (
            self.filter_heads(representation),
            self.reach_heads(representation),
            self.value_heads(representation),
            self.cost_head(representation).squeeze(0),
        )


@dataclass(frozen=True)
class MappingPrediction:
    conditional_probabilities: tuple[float, ...]
    reach_probabilities: tuple[float, ...]
    value_probabilities: tuple[float, ...]
    auxiliary_progress: float
    expected_seconds: float

    @property
    def terminal_probability(self) -> float:
        return self.value_probabilities[0]


class MappingLearningModel:
    """Graph-conditioned ranker for complete orientation/phase mappings."""

    def __init__(self, config: Mapping[str, object]) -> None:
        self.config = dict(config)
        self.seed = int(config.get("seed", 20260810))
        self.tile_scale = max(1.0, float(config.get("tile_feature_scale", 13.0)))
        torch.manual_seed(self.seed)
        torch.set_num_threads(max(1, int(config.get("torch_threads", 1))))
        self.network = MappingGraphNetwork(
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
        self.empirical_rates = np.full(len(LEARNING_FILTER_IDS), 0.5, dtype=np.float32)
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
    def _is_validation(observation: MappingEvaluation) -> bool:
        # Keep every mapping of one graph in the same partition. A validation
        # score then measures transfer to another graph, not memorization of a
        # neighbouring phase/orientation assignment on a familiar graph.
        digest = hashlib.sha256(
            observation.proposal.candidate.graph_id.encode("utf-8")
        ).digest()
        return digest[0] < 51

    def _partitions(
        self, observations: Sequence[MappingEvaluation]
    ) -> tuple[list[MappingEvaluation], list[MappingEvaluation]]:
        training = [item for item in observations if not self._is_validation(item)]
        validation = [item for item in observations if self._is_validation(item)]
        if not training:
            return list(observations), []
        return training, validation

    def _refresh_statistics(self, observations: Sequence[MappingEvaluation]) -> None:
        for head in range(len(LEARNING_FILTER_IDS)):
            labels = [
                item.target_vector[head]
                for item in observations
                if item.target_vector[head] is not None
            ]
            positive = sum(float(value) for value in labels)
            negative = len(labels) - positive
            self.pass_supports[head] = len(labels)
            self.active_heads[head] = positive > 0.0 and negative > 0.0
            self.empirical_rates[head] = float((positive + 0.5) / (len(labels) + 1.0))
            reach_labels = [
                item.reach_vector[head]
                for item in observations
                if item.reach_vector[head] is not None
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
        observation: MappingEvaluation,
        feedback: LearningFeedback,
    ) -> tuple[float | None, ...]:
        return feedback.targets(
            candidate=observation.proposal.candidate,
            profile_count=len(observation.profiles),
            profile_ids=formal_profile_ids(observation.profiles),
        )

    def _refresh_value_statistics(
        self,
        observations: Sequence[MappingEvaluation],
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

    def policy_score(self, prediction: MappingPrediction) -> float:
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
        score -= float(self.config.get("cost_weight", 0.02)) * normalized_cost(
            prediction.expected_seconds, self.config
        )
        return score

    def predict(self, proposal: MappingProposal) -> MappingPrediction:
        self.network.eval()
        with torch.no_grad():
            logits, reach_logits, value_logits, log_cost = self.network(
                *mapping_tensors(proposal, tile_scale=self.tile_scale)
            )
            probabilities = torch.sigmoid(logits).cpu().numpy()
            reach_probabilities = torch.sigmoid(reach_logits).cpu().numpy()
            value_probabilities = torch.sigmoid(value_logits).cpu().numpy()
        probabilities[~self.active_heads] = self.empirical_rates[~self.active_heads]
        reach_probabilities[~self.active_reach_heads] = self.empirical_reach_rates[
            ~self.active_reach_heads
        ]
        value_probabilities[~self.active_value_heads] = self.empirical_value_rates[
            ~self.active_value_heads
        ]
        active = reach_probabilities[self.active_reach_heads]
        return MappingPrediction(
            conditional_probabilities=tuple(float(value) for value in probabilities),
            reach_probabilities=tuple(float(value) for value in reach_probabilities),
            value_probabilities=tuple(float(value) for value in value_probabilities),
            auxiliary_progress=float(np.mean(active)) if len(active) else 0.5,
            expected_seconds=max(
                0.0, math.expm1(min(20.0, max(-20.0, float(log_cost.item()))))
            ),
        )

    def train(
        self,
        observations: Sequence[MappingEvaluation],
        *,
        steps: int,
        batch_size: int,
        generation: int,
        feedback: LearningFeedback | None = None,
    ) -> dict[str, object]:
        feedback = feedback or LearningFeedback.empty()
        if not observations:
            return self.metrics(observations, feedback=feedback)
        replay_limit = max(1, int(self.config.get("replay_examples", 50000)))
        replay = observations[-replay_limit:]
        training, _ = self._partitions(replay)
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
        groups: dict[str, list[MappingEvaluation]] = defaultdict(list)
        ranking_window = training[
            -max(1, int(self.config.get("ranking_replay_examples", 10000))):
        ]
        for observation in ranking_window:
            groups[observation.proposal.candidate.graph_id].append(observation)
        rankable: list[
            tuple[int, list[MappingEvaluation], list[MappingEvaluation]]
        ] = []
        for values in groups.values():
            for head in range(len(VALUE_TARGET_IDS)):
                labelled = [
                    (item, value_targets[id(item)][head])
                    for item in values
                ]
                positive = [item for item, target in labelled if target == 1.0]
                negative = [item for item, target in labelled if target == 0.0]
                if positive and negative:
                    rankable.append((head, positive, negative))
        curriculum = self.curriculum_state()
        reach_rankable: list[tuple[MappingEvaluation, MappingEvaluation]] = []
        if curriculum.frontier_index is not None:
            head = curriculum.frontier_index
            for values in groups.values():
                ordered = sorted(
                    (item for item in values if item.reach_vector[head] is not None),
                    key=lambda item: float(item.reach_vector[head]),
                )
                if (
                    ordered
                    and float(ordered[0].reach_vector[head])
                    < float(ordered[-1].reach_vector[head])
                ):
                    reach_rankable.append((ordered[-1], ordered[0]))
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
            for observation in selected:
                logits, reach_logits, value_logits, log_cost = self.network(
                    *mapping_tensors(observation.proposal, tile_scale=self.tile_scale)
                )
                for head, target in enumerate(observation.target_vector):
                    if target is None or not self.active_heads[head]:
                        continue
                    weight = (
                        filter_weights[head][0] * float(target)
                        + filter_weights[head][1] * (1.0 - float(target))
                    )
                    loss = loss + float(weight) * torch.nn.functional.binary_cross_entropy_with_logits(
                        logits[head], torch.tensor(float(target), dtype=torch.float32)
                    )
                    terms += 1
                for head, target in enumerate(observation.reach_vector):
                    if target is None or not self.active_reach_heads[head]:
                        continue
                    weight = (
                        reach_weights[head][0] * float(target)
                        + reach_weights[head][1] * (1.0 - float(target))
                    )
                    loss = loss + float(weight) * torch.nn.functional.binary_cross_entropy_with_logits(
                        reach_logits[head],
                        torch.tensor(float(target), dtype=torch.float32),
                    )
                    terms += 1
                for head, target in enumerate(
                    value_targets[id(observation)]
                ):
                    if target is None or not self.active_value_heads[head]:
                        continue
                    weight = (
                        value_weights[head][0] * float(target)
                        + value_weights[head][1] * (1.0 - float(target))
                    )
                    loss = loss + float(weight) * torch.nn.functional.binary_cross_entropy_with_logits(
                        value_logits[head],
                        torch.tensor(float(target), dtype=torch.float32),
                    )
                    terms += 1
                loss = loss + float(self.config.get("cost_loss_weight", 0.05)) * (
                    torch.nn.functional.smooth_l1_loss(
                        log_cost,
                        torch.tensor(math.log1p(observation.elapsed_seconds)),
                    )
                )
                terms += 1
            pair_amount = min(
                len(rankable),
                max(0, int(self.config.get("ranking_pairs_per_step", 4))),
            )
            if pair_amount:
                for head, positive, negative in rng.sample(rankable, pair_amount):
                    better = positive[rng.randrange(len(positive))]
                    worse = negative[rng.randrange(len(negative))]
                    _filters, _reaches, better_values, _cost = self.network(
                        *mapping_tensors(better.proposal, tile_scale=self.tile_scale)
                    )
                    _filters, _reaches, worse_values, _cost = self.network(
                        *mapping_tensors(worse.proposal, tile_scale=self.tile_scale)
                    )
                    loss = loss + float(
                        self.config.get("ranking_loss_weight", 0.5)
                    ) * torch.nn.functional.softplus(
                        -(better_values[head] - worse_values[head])
                    )
                    terms += 1
            reach_pair_amount = min(
                len(reach_rankable),
                max(0, int(self.config.get("curriculum_ranking_pairs_per_step", 4))),
            )
            if reach_pair_amount and curriculum.frontier_index is not None:
                head = curriculum.frontier_index
                for better, worse in rng.sample(reach_rankable, reach_pair_amount):
                    _passes, better_reaches, _values, _cost = self.network(
                        *mapping_tensors(better.proposal, tile_scale=self.tile_scale)
                    )
                    _passes, worse_reaches, _values, _cost = self.network(
                        *mapping_tensors(worse.proposal, tile_scale=self.tile_scale)
                    )
                    loss = loss + float(
                        self.config.get("curriculum_ranking_loss_weight", 0.5)
                    ) * torch.nn.functional.softplus(
                        -(better_reaches[head] - worse_reaches[head])
                    )
                    terms += 1
            loss = loss / max(1, terms)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.network.parameters(), 5.0)
            self.optimizer.step()
            losses.append(float(loss.detach().item()))
        metric_limit = max(1, int(self.config.get("metric_examples", 512)))
        metrics = self.metrics(
            observations,
            feedback=feedback,
            maximum_examples=metric_limit,
        )
        metrics["training_loss"] = float(np.mean(losses)) if losses else None
        metrics["training_replay_examples"] = len(training)
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
        observations: Sequence[MappingEvaluation],
        *,
        feedback: LearningFeedback | None = None,
        maximum_examples: int | None = None,
    ) -> dict[str, object]:
        feedback = feedback or LearningFeedback.empty()
        if not observations:
            return {
                "schema_version": "graph-lab-mapping-metrics-v1",
                "examples": 0,
                "filters": {},
            }
        metric_source = observations
        if maximum_examples is not None:
            metric_source = observations[
                -max(1, int(maximum_examples) * 5):
            ]
        training, validation = self._partitions(metric_source)
        self._refresh_statistics(training)
        self._refresh_value_statistics(training, feedback)
        measured = validation if validation else training
        if maximum_examples is not None:
            measured = measured[-max(1, int(maximum_examples)):]
        predictions = [self.predict(item.proposal) for item in measured]
        filters: dict[str, object] = {}
        reach: dict[str, object] = {}
        for head, filter_id in enumerate(LEARNING_FILTER_IDS):
            eligible = [
                index
                for index, item in enumerate(measured)
                if item.target_vector[head] is not None
            ]
            labels = np.asarray(
                [float(measured[index].target_vector[head]) for index in eligible]
            )
            scores = np.asarray(
                [predictions[index].conditional_probabilities[head] for index in eligible]
            )
            filter_auc = self._auc(labels >= 0.5, scores)
            filter_best = self.best_filter_auc[head]
            filters[filter_id] = {
                "eligible": len(eligible),
                "mean_conditional_pass_rate": float(np.mean(labels)) if len(labels) else None,
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
                for index, item in enumerate(measured)
                if item.reach_vector[head] is not None
            ]
            reach_labels = np.asarray(
                [float(measured[index].reach_vector[head]) for index in reach_eligible]
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
                for item, prediction in zip(measured, predictions)
                for targets in (self._value_targets(item, feedback),)
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
        by_graph: dict[str, list[tuple[MappingEvaluation, MappingPrediction]]] = defaultdict(list)
        for item, prediction in zip(measured, predictions):
            by_graph[item.proposal.candidate.graph_id].append((item, prediction))
        pairwise: dict[str, object] = {}
        for head, value_id in enumerate(VALUE_TARGET_IDS):
            pair_total = 0
            pair_correct = 0
            for items in by_graph.values():
                labelled = [
                    (item, prediction, self._value_targets(item, feedback)[head])
                    for item, prediction in items
                ]
                positives = [pair for pair in labelled if pair[2] == 1.0]
                negatives = [pair for pair in labelled if pair[2] == 0.0]
                for positive in positives:
                    for negative in negatives:
                        pair_total += 1
                        pair_correct += int(
                            positive[1].value_probabilities[head]
                            > negative[1].value_probabilities[head]
                        )
            pairwise[value_id] = {
                "pairs": pair_total,
                "accuracy": pair_correct / pair_total if pair_total else None,
                "scope": "same_graph",
            }
        curriculum = self.curriculum_state()
        frontier_pairs = 0
        frontier_correct = 0
        if curriculum.frontier_index is not None:
            head = curriculum.frontier_index
            for items in by_graph.values():
                for left_index, left in enumerate(items):
                    for right in items[left_index + 1 :]:
                        left_target = left[0].reach_vector[head]
                        right_target = right[0].reach_vector[head]
                        if left_target is None or right_target is None:
                            continue
                        if abs(left_target - right_target) < 1e-9:
                            continue
                        frontier_pairs += 1
                        left_score = left[1].reach_probabilities[head]
                        right_score = right[1].reach_probabilities[head]
                        frontier_correct += int(
                            (left_score - right_score) * (left_target - right_target) > 0
                        )
        return {
            "schema_version": "graph-lab-mapping-metrics-v1",
            "examples": len(observations),
            "training_examples": len(training),
            "validation_examples": len(validation),
            "metric_partition": "validation" if validation else "training_fallback",
            "metric_examples": len(measured),
            "filters": filters,
            "reach": reach,
            "values": values,
            "curriculum": {
                **curriculum.to_dict(),
                "within_parent_pairs": frontier_pairs,
                "within_parent_pair_accuracy": (
                    frontier_correct / frontier_pairs if frontier_pairs else None
                ),
                "learnable_reach_heads": int(np.count_nonzero(self.active_reach_heads)),
                "learnable_conditional_heads": int(np.count_nonzero(self.active_heads)),
            },
            "pairwise_ranking": pairwise,
            "within_parent_pair_accuracy": pairwise["profile_emitted"]["accuracy"],
            "within_parent_pairs": pairwise["profile_emitted"]["pairs"],
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
    ) -> "MappingLearningModel":
        result = cls(config)
        if not path.exists():
            return result
        payload = torch.load(path, map_location="cpu", weights_only=False)
        version = payload.get("version")
        if version != MODEL_VERSION:
            raise ValueError("Stored mapping model is incompatible; use --restart")
        result.network.load_state_dict(payload["network"])
        result.optimizer.load_state_dict(payload["optimizer"])
        result.active_heads = np.asarray(payload["active_heads"], dtype=bool)
        result.pass_supports = np.asarray(payload["pass_supports"], dtype=np.int64)
        result.empirical_rates = np.asarray(payload["empirical_rates"], dtype=np.float32)
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
