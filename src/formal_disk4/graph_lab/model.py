from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import networkx as nx
import numpy as np

from formal_disk4.pipeline.output import atomic_replace

from .evaluator import GRAPH_STAGES, GraphEvaluation
from .feedback import (
    LearningFeedback,
    VALUE_TARGET_IDS,
    balanced_binary_weights,
    formal_profile_ids,
)
from .curriculum import normalized_cost
from .space import DualGraphCandidate, OUTSIDE

try:
    import torch
    from torch import nn
except ImportError as error:  # pragma: no cover - exercised only without the extra
    raise RuntimeError(
        "Graph Lab learning requires PyTorch. Install the project with "
        "`pip install -e .[graph-lab]`."
    ) from error


MODEL_VERSION = "graph-lab-gnn-v4-curriculum"
TRANSITIONS = tuple(range(1, len(GRAPH_STAGES)))
NODE_FEATURES = 8
GLOBAL_FEATURES = 6


def _orbit_lengths(candidate: DualGraphCandidate) -> tuple[int, ...]:
    if candidate.imposed_permutation is None:
        return tuple(1 for _ in range(candidate.tile_count))
    permutation = candidate.imposed_permutation
    output = [1] * len(permutation)
    unseen = set(range(len(permutation)))
    while unseen:
        seed = min(unseen)
        orbit = []
        current = seed
        while current not in orbit:
            orbit.append(current)
            unseen.discard(current)
            current = permutation[current]
        for node in orbit:
            output[node] = len(orbit)
    return tuple(output)


def graph_tensors(
    candidate: DualGraphCandidate,
    *,
    tile_scale: float = 13.0,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, int]:
    tile_scale = max(1.0, float(tile_scale))
    graph = candidate.graph()
    nodes = (OUTSIDE, *range(candidate.tile_count))
    index = {node: offset for offset, node in enumerate(nodes)}
    adjacency = torch.zeros((len(nodes), len(nodes)), dtype=torch.float32)
    for left, right in graph.edges():
        adjacency[index[left], index[right]] = 1.0
        adjacency[index[right], index[left]] = 1.0
    degree = adjacency.sum(dim=1, keepdim=True)
    normalized_adjacency = adjacency / torch.clamp(degree, min=1.0)
    clustering = nx.clustering(graph)
    orbit_lengths = _orbit_lengths(candidate)
    node_rows = []
    for node in nodes:
        outside = node == OUTSIDE
        boundary = not outside and graph.has_edge(node, OUTSIDE)
        orbit = 1 if outside else orbit_lengths[node]
        node_rows.append(
            (
                1.0 if outside else 0.0,
                0.0 if outside else 1.0,
                graph.degree(node) / max(1, candidate.tile_count),
                1.0 if boundary else 0.0,
                float(clustering[node]),
                candidate.tile_count / tile_scale,
                orbit / max(1, candidate.tile_count),
                1.0 if orbit == 1 else 0.0,
            )
        )
    maximum_edges = max(1, 3 * (candidate.tile_count + 1) - 6)
    boundary_count = graph.degree(OUTSIDE)
    globals_ = torch.tensor(
        (
            candidate.tile_count / tile_scale,
            candidate.edge_count / maximum_edges,
            candidate.symmetry_order / tile_scale,
            boundary_count / max(1, candidate.tile_count),
            1.0 if candidate.imposed_permutation is not None else 0.0,
            float(np.mean([graph.degree(node) for node in range(candidate.tile_count)]))
            / max(1, candidate.tile_count),
        ),
        dtype=torch.float32,
    )
    return (
        torch.tensor(node_rows, dtype=torch.float32),
        normalized_adjacency,
        globals_,
        0,
    )


class SharedGraphNetwork(nn.Module):
    def __init__(self, hidden_size: int, message_layers: int) -> None:
        super().__init__()
        self.node_input = nn.Linear(NODE_FEATURES, hidden_size)
        self.message_layers = nn.ModuleList(
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
        self.stage_heads = nn.Linear(hidden_size, len(TRANSITIONS))
        self.value_heads = nn.Linear(hidden_size, len(VALUE_TARGET_IDS))
        self.cost_head = nn.Linear(hidden_size, 1)

    def forward(
        self,
        node_features: torch.Tensor,
        adjacency: torch.Tensor,
        global_features: torch.Tensor,
        outside_index: int,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        hidden = torch.relu(self.node_input(node_features))
        for layer in self.message_layers:
            message = adjacency @ hidden
            hidden = torch.relu(layer(torch.cat((hidden, message), dim=1))) + hidden
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
            self.stage_heads(representation),
            self.value_heads(representation),
            self.cost_head(representation).squeeze(0),
        )


@dataclass(frozen=True)
class GraphPrediction:
    conditional_probabilities: tuple[float, ...]
    reach_probabilities: tuple[float, ...]
    expected_stage: float
    geometry_probability: float
    value_probabilities: tuple[float, ...]
    expected_seconds: float


class GraphLearningModel:
    def __init__(self, config: Mapping[str, object]) -> None:
        self.config = dict(config)
        self.seed = int(config.get("seed", 20260809))
        self.tile_scale = max(1.0, float(config.get("tile_feature_scale", 13.0)))
        torch.manual_seed(self.seed)
        torch.set_num_threads(max(1, int(config.get("torch_threads", 1))))
        self.network = SharedGraphNetwork(
            hidden_size=max(8, int(config.get("hidden_size", 64))),
            message_layers=max(1, int(config.get("message_layers", 3))),
        )
        self.optimizer = torch.optim.AdamW(
            self.network.parameters(),
            lr=float(config.get("learning_rate", 0.001)),
            weight_decay=float(config.get("weight_decay", 1e-4)),
        )
        self.active_heads = np.zeros(len(TRANSITIONS), dtype=bool)
        self.empirical_rates = np.full(len(TRANSITIONS), 0.5, dtype=np.float32)
        self.best_transition_auc = np.full(len(TRANSITIONS), np.nan)
        self.active_value_heads = np.zeros(len(VALUE_TARGET_IDS), dtype=bool)
        self.empirical_value_rates = np.full(
            len(VALUE_TARGET_IDS), 0.5, dtype=np.float32
        )

    def _refresh_statistics(self, observations: Sequence[GraphEvaluation]) -> None:
        stages = np.asarray([item.stage_index for item in observations], dtype=np.int16)
        for head, target in enumerate(TRANSITIONS):
            eligible = stages >= target - 1
            positives = int(np.count_nonzero(stages >= target))
            negatives = int(np.count_nonzero(eligible)) - positives
            self.active_heads[head] = positives > 0 and negatives > 0
            self.empirical_rates[head] = (positives + 0.5) / (
                int(np.count_nonzero(eligible)) + 1.0
            )

    def _value_targets(
        self, observation: GraphEvaluation, feedback: LearningFeedback
    ) -> tuple[float | None, ...]:
        return feedback.targets(
            candidate=observation.candidate,
            profile_count=len(observation.profiles),
            profile_ids=formal_profile_ids(observation.profiles),
            allow_graph_fallback=True,
        )

    def _refresh_value_statistics(
        self,
        observations: Sequence[GraphEvaluation],
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

    @property
    def has_policy_signal(self) -> bool:
        return bool(np.any(self.active_heads) or np.any(self.active_value_heads))

    def curriculum_frontier(self) -> int | None:
        active = np.flatnonzero(self.active_heads)
        if not len(active):
            return None
        mastery = min(
            0.999,
            max(0.5, float(self.config.get("curriculum_mastery_rate", 0.85))),
        )
        return next(
            (
                int(index)
                for index in active
                if float(self.empirical_rates[index]) < mastery
            ),
            int(active[-1]),
        )

    @staticmethod
    def _is_validation(observation: GraphEvaluation) -> bool:
        digest = hashlib.sha256(
            observation.candidate.graph_id.encode("utf-8")
        ).digest()
        return digest[0] < 51

    def _partitions(
        self, observations: Sequence[GraphEvaluation]
    ) -> tuple[list[GraphEvaluation], list[GraphEvaluation]]:
        training = [item for item in observations if not self._is_validation(item)]
        validation = [item for item in observations if self._is_validation(item)]
        if not training:
            training = list(observations)
            validation = []
        return training, validation

    def predict(self, candidate: DualGraphCandidate) -> GraphPrediction:
        self.network.eval()
        with torch.no_grad():
            logits, value_logits, log_cost = self.network(
                *graph_tensors(candidate, tile_scale=self.tile_scale)
            )
            probabilities = torch.sigmoid(logits).cpu().numpy()
            value_probabilities = torch.sigmoid(value_logits).cpu().numpy()
        probabilities[~self.active_heads] = self.empirical_rates[~self.active_heads]
        value_probabilities[~self.active_value_heads] = self.empirical_value_rates[
            ~self.active_value_heads
        ]
        reach = np.cumprod(probabilities)
        expected_stage = float(np.sum(reach))
        return GraphPrediction(
            conditional_probabilities=tuple(float(value) for value in probabilities),
            reach_probabilities=tuple(float(value) for value in reach),
            expected_stage=expected_stage,
            geometry_probability=float(reach[-1]),
            value_probabilities=tuple(float(value) for value in value_probabilities),
            expected_seconds=max(
                0.0, math.expm1(min(20.0, max(-20.0, float(log_cost.item()))))
            ),
        )

    def utility(
        self,
        candidate: DualGraphCandidate,
        *,
        novelty: float,
        geometry_weight: float,
        solution_weight: float,
        nontrivial_solution_weight: float,
        novelty_weight: float,
        cost_weight: float,
    ) -> tuple[float, GraphPrediction]:
        prediction = self.predict(candidate)
        frontier = self.curriculum_frontier()
        if frontier is None:
            curriculum_score = 0.10 * prediction.expected_stage
        else:
            curriculum_score = prediction.conditional_probabilities[frontier]
            curriculum_score += 0.15 * sum(
                prediction.conditional_probabilities[:frontier]
            ) / max(1, frontier)
            curriculum_score += 0.10 * sum(
                prediction.reach_probabilities[frontier + 1 :]
            ) / max(1, len(prediction.reach_probabilities) - frontier - 1)
        score = (
            curriculum_score
            + geometry_weight * prediction.value_probabilities[0]
            + solution_weight * prediction.value_probabilities[1]
            + nontrivial_solution_weight * prediction.value_probabilities[2]
            + novelty_weight * float(novelty)
            - cost_weight * normalized_cost(prediction.expected_seconds, self.config)
        )
        return score, prediction

    def train(
        self,
        observations: Sequence[GraphEvaluation],
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
        training, _validation = self._partitions(replay)
        self._refresh_statistics(training)
        self._refresh_value_statistics(training, feedback)
        value_targets = {
            id(item): self._value_targets(item, feedback) for item in training
        }
        value_weights = balanced_binary_weights(
            tuple(value_targets.values()),
            len(VALUE_TARGET_IDS),
            maximum=float(self.config.get("maximum_class_weight", 50.0)),
        )
        cohorts: dict[int, list[GraphEvaluation]] = defaultdict(list)
        ranking_window = training[
            -max(1, int(self.config.get("ranking_replay_examples", 10000))):
        ]
        for observation in ranking_window:
            cohorts[observation.candidate.tile_count].append(observation)
        rankable: list[
            tuple[int, list[GraphEvaluation], list[GraphEvaluation]]
        ] = []
        for values in cohorts.values():
            for head in range(len(VALUE_TARGET_IDS)):
                labelled = [
                    (item, value_targets[id(item)][head])
                    for item in values
                ]
                positive = [item for item, target in labelled if target == 1.0]
                negative = [item for item, target in labelled if target == 0.0]
                if positive and negative:
                    rankable.append((head, positive, negative))
        stages = np.asarray([item.stage_index for item in training], dtype=np.int16)
        positive_weights = []
        negative_weights = []
        maximum_class_weight = float(
            self.config.get("maximum_class_weight", 50.0)
        )
        for target in TRANSITIONS:
            eligible = stages >= target - 1
            positive = int(np.count_nonzero(stages >= target))
            negative = int(np.count_nonzero(eligible)) - positive
            total = positive + negative
            positive_weights.append(
                min(maximum_class_weight, total / (2 * positive))
                if positive
                else 1.0
            )
            negative_weights.append(
                min(maximum_class_weight, total / (2 * negative))
                if negative
                else 1.0
            )

        rng = random.Random(self.seed + int(generation) * 104729)
        losses = []
        self.network.train()
        for _ in range(max(0, int(steps))):
            selected = [
                training[rng.randrange(len(training))]
                for _ in range(max(1, int(batch_size)))
            ]
            self.optimizer.zero_grad()
            batch_loss = torch.tensor(0.0)
            terms = 0
            for observation in selected:
                logits, value_logits, log_cost = self.network(
                    *graph_tensors(
                        observation.candidate, tile_scale=self.tile_scale
                    )
                )
                for head, target in enumerate(TRANSITIONS):
                    if not self.active_heads[head] or observation.stage_index < target - 1:
                        continue
                    label = 1.0 if observation.stage_index >= target else 0.0
                    weight = (
                        positive_weights[head] if label else negative_weights[head]
                    )
                    batch_loss = batch_loss + float(weight) * torch.nn.functional.binary_cross_entropy_with_logits(
                        logits[head], torch.tensor(label)
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
                    batch_loss = batch_loss + float(weight) * torch.nn.functional.binary_cross_entropy_with_logits(
                        value_logits[head], torch.tensor(float(target))
                    )
                    terms += 1
                cost_target = torch.tensor(math.log1p(observation.elapsed_seconds))
                batch_loss = batch_loss + float(
                    self.config.get("cost_loss_weight", 0.1)
                ) * torch.nn.functional.smooth_l1_loss(log_cost, cost_target)
                terms += 1
            pair_amount = min(
                len(rankable),
                max(0, int(self.config.get("ranking_pairs_per_step", 4))),
            )
            if pair_amount:
                for head, positive, negative in rng.sample(rankable, pair_amount):
                    better = positive[rng.randrange(len(positive))]
                    worse = negative[rng.randrange(len(negative))]
                    _stages, better_values, _cost = self.network(
                        *graph_tensors(better.candidate, tile_scale=self.tile_scale)
                    )
                    _stages, worse_values, _cost = self.network(
                        *graph_tensors(worse.candidate, tile_scale=self.tile_scale)
                    )
                    batch_loss = batch_loss + float(
                        self.config.get("ranking_loss_weight", 0.5)
                    ) * torch.nn.functional.softplus(
                        -(better_values[head] - worse_values[head])
                    )
                    terms += 1
            batch_loss = batch_loss / max(1, terms)
            batch_loss.backward()
            torch.nn.utils.clip_grad_norm_(self.network.parameters(), 5.0)
            self.optimizer.step()
            losses.append(float(batch_loss.detach().item()))
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
        observations: Sequence[GraphEvaluation],
        *,
        feedback: LearningFeedback | None = None,
        maximum_examples: int | None = None,
    ) -> dict[str, object]:
        feedback = feedback or LearningFeedback.empty()
        if not observations:
            return {
                "examples": 0,
                "training_examples": 0,
                "validation_examples": 0,
                "metric_partition": "none",
                "transitions": {},
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
        stages = np.asarray([item.stage_index for item in measured], dtype=np.int16)
        predictions = [self.predict(item.candidate) for item in measured]
        transitions = {}
        for head, target in enumerate(TRANSITIONS):
            eligible = stages >= target - 1
            labels = stages[eligible] >= target
            scores = np.asarray(
                [item.conditional_probabilities[head] for item in predictions]
            )[eligible]
            transition_auc = self._auc(labels, scores)
            previous_best = self.best_transition_auc[head]
            transitions[GRAPH_STAGES[target]] = {
                "eligible": int(np.count_nonzero(eligible)),
                "positives": int(np.count_nonzero(labels)),
                "conditional_rate": (
                    float(np.mean(labels)) if len(labels) else None
                ),
                "auc": transition_auc,
                "best_auc": (
                    None if np.isnan(previous_best) else float(previous_best)
                ),
                "auc_regression": bool(
                    transition_auc is not None
                    and not np.isnan(previous_best)
                    and transition_auc + 0.05 < previous_best
                ),
                "brier_score": (
                    float(np.mean((scores - labels.astype(np.float64)) ** 2))
                    if len(labels)
                    else None
                ),
                "active": bool(self.active_heads[head]),
            }
            if transition_auc is not None:
                self.best_transition_auc[head] = (
                    transition_auc
                    if np.isnan(previous_best)
                    else max(float(previous_best), transition_auc)
                )
        cost_errors = [
            abs(item.expected_seconds - observation.elapsed_seconds)
            for item, observation in zip(predictions, measured)
        ]
        values: dict[str, object] = {}
        for head, value_id in enumerate(VALUE_TARGET_IDS):
            labels_and_scores = [
                (targets[head], prediction.value_probabilities[head])
                for observation, prediction in zip(measured, predictions)
                for targets in (self._value_targets(observation, feedback),)
                if targets[head] is not None
            ]
            labels = np.asarray([float(item[0]) for item in labels_and_scores])
            scores = np.asarray([float(item[1]) for item in labels_and_scores])
            values[value_id] = {
                "eligible": len(labels),
                "mean_rate": float(np.mean(labels)) if len(labels) else None,
                "mean_prediction": float(np.mean(scores)) if len(scores) else None,
                "auc": self._auc(labels >= 0.5, scores),
                "active": bool(self.active_value_heads[head]),
            }
        pairwise: dict[str, object] = {}
        cohorts: dict[int, list[tuple[GraphEvaluation, GraphPrediction]]] = defaultdict(list)
        for observation, prediction in zip(measured, predictions):
            cohorts[observation.candidate.tile_count].append(
                (observation, prediction)
            )
        for head, value_id in enumerate(VALUE_TARGET_IDS):
            correct = 0
            total = 0
            for items in cohorts.values():
                labelled = [
                    (item, prediction, self._value_targets(item, feedback)[head])
                    for item, prediction in items
                ]
                positive = [item for item in labelled if item[2] == 1.0]
                negative = [item for item in labelled if item[2] == 0.0]
                for better in positive:
                    for worse in negative:
                        total += 1
                        correct += int(
                            better[1].value_probabilities[head]
                            > worse[1].value_probabilities[head]
                        )
            pairwise[value_id] = {
                "pairs": total,
                "accuracy": correct / total if total else None,
                "scope": "same_tile_count",
            }
        frontier = self.curriculum_frontier()
        return {
            "schema_version": "graph-lab-gnn-metrics-v1",
            "examples": len(observations),
            "training_examples": len(training),
            "validation_examples": len(validation),
            "metric_partition": "validation" if validation else "training_fallback",
            "metric_examples": len(measured),
            "transitions": transitions,
            "values": values,
            "pairwise_ranking": pairwise,
            "curriculum": {
                "frontier_index": frontier,
                "frontier_stage": (
                    GRAPH_STAGES[TRANSITIONS[frontier]]
                    if frontier is not None
                    else None
                ),
                "status": "active" if frontier is not None else "waiting_for_contrast",
                "probability_semantics": (
                    "True sequential conditional transitions; cumulative reach "
                    "is their product only at this graph level."
                ),
                "learnable_transition_heads": int(np.count_nonzero(self.active_heads)),
            },
            "cost_mean_absolute_error_seconds": float(np.mean(cost_errors)),
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
                "best_transition_auc": self.best_transition_auc,
                "active_value_heads": self.active_value_heads,
                "empirical_value_rates": self.empirical_value_rates,
            },
            temporary,
        )
        atomic_replace(temporary, path)

    @classmethod
    def load_or_create(
        cls, path: Path, config: Mapping[str, object]
    ) -> "GraphLearningModel":
        result = cls(config)
        if not path.exists():
            return result
        payload = torch.load(path, map_location="cpu", weights_only=False)
        version = payload.get("version")
        if version != MODEL_VERSION:
            raise ValueError("Stored Graph Lab model is incompatible; use --restart")
        result.network.load_state_dict(payload["network"])
        result.optimizer.load_state_dict(payload["optimizer"])
        result.active_heads = np.asarray(payload["active_heads"], dtype=bool)
        result.empirical_rates = np.asarray(
            payload["empirical_rates"], dtype=np.float32
        )
        result.best_transition_auc = np.asarray(
            payload["best_transition_auc"], dtype=float
        )
        result.active_value_heads = np.asarray(
            payload["active_value_heads"], dtype=bool
        )
        result.empirical_value_rates = np.asarray(
            payload["empirical_value_rates"], dtype=np.float32
        )
        return result
