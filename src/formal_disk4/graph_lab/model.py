from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import networkx as nx
import numpy as np

from .evaluator import GRAPH_STAGES, GraphEvaluation
from .space import DualGraphCandidate, OUTSIDE

try:
    import torch
    from torch import nn
except ImportError as error:  # pragma: no cover - exercised only without the extra
    raise RuntimeError(
        "Graph Lab learning requires PyTorch. Install the project with "
        "`pip install -e .[graph-lab]`."
    ) from error


MODEL_VERSION = "graph-lab-gnn-v2"
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
        self.cost_head = nn.Linear(hidden_size, 1)

    def forward(
        self,
        node_features: torch.Tensor,
        adjacency: torch.Tensor,
        global_features: torch.Tensor,
        outside_index: int,
    ) -> tuple[torch.Tensor, torch.Tensor]:
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
        return self.stage_heads(representation), self.cost_head(representation).squeeze(0)


@dataclass(frozen=True)
class GraphPrediction:
    conditional_probabilities: tuple[float, ...]
    reach_probabilities: tuple[float, ...]
    expected_stage: float
    geometry_probability: float
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
            logits, log_cost = self.network(
                *graph_tensors(candidate, tile_scale=self.tile_scale)
            )
            probabilities = torch.sigmoid(logits).cpu().numpy()
        probabilities[~self.active_heads] = self.empirical_rates[~self.active_heads]
        reach = np.cumprod(probabilities)
        expected_stage = float(np.sum(reach))
        return GraphPrediction(
            conditional_probabilities=tuple(float(value) for value in probabilities),
            reach_probabilities=tuple(float(value) for value in reach),
            expected_stage=expected_stage,
            geometry_probability=float(reach[-1]),
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
        novelty_weight: float,
        cost_weight: float,
    ) -> tuple[float, GraphPrediction]:
        prediction = self.predict(candidate)
        score = (
            prediction.expected_stage
            + geometry_weight * prediction.geometry_probability
            + novelty_weight * float(novelty)
            - cost_weight * math.log1p(prediction.expected_seconds)
        )
        return score, prediction

    def train(
        self,
        observations: Sequence[GraphEvaluation],
        *,
        steps: int,
        batch_size: int,
        generation: int,
    ) -> dict[str, object]:
        if not observations:
            return self.metrics(observations)
        training, _validation = self._partitions(observations)
        self._refresh_statistics(training)
        stages = np.asarray([item.stage_index for item in training], dtype=np.int16)
        positive_weights = []
        negative_weights = []
        for target in TRANSITIONS:
            eligible = stages >= target - 1
            positive = int(np.count_nonzero(stages >= target))
            negative = int(np.count_nonzero(eligible)) - positive
            total = positive + negative
            positive_weights.append(total / (2 * positive) if positive else 1.0)
            negative_weights.append(total / (2 * negative) if negative else 1.0)

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
                logits, log_cost = self.network(
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
                cost_target = torch.tensor(math.log1p(observation.elapsed_seconds))
                batch_loss = batch_loss + float(
                    self.config.get("cost_loss_weight", 0.1)
                ) * torch.nn.functional.smooth_l1_loss(log_cost, cost_target)
                terms += 1
            batch_loss = batch_loss / max(1, terms)
            batch_loss.backward()
            torch.nn.utils.clip_grad_norm_(self.network.parameters(), 5.0)
            self.optimizer.step()
            losses.append(float(batch_loss.detach().item()))
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

    def metrics(self, observations: Sequence[GraphEvaluation]) -> dict[str, object]:
        if not observations:
            return {
                "examples": 0,
                "training_examples": 0,
                "validation_examples": 0,
                "metric_partition": "none",
                "transitions": {},
            }
        training, validation = self._partitions(observations)
        self._refresh_statistics(training)
        measured = validation if validation else training
        stages = np.asarray([item.stage_index for item in measured], dtype=np.int16)
        predictions = [self.predict(item.candidate) for item in measured]
        transitions = {}
        for head, target in enumerate(TRANSITIONS):
            eligible = stages >= target - 1
            labels = stages[eligible] >= target
            scores = np.asarray(
                [item.conditional_probabilities[head] for item in predictions]
            )[eligible]
            transitions[GRAPH_STAGES[target]] = {
                "eligible": int(np.count_nonzero(eligible)),
                "positives": int(np.count_nonzero(labels)),
                "conditional_rate": (
                    float(np.mean(labels)) if len(labels) else None
                ),
                "auc": self._auc(labels, scores),
                "active": bool(self.active_heads[head]),
            }
        cost_errors = [
            abs(item.expected_seconds - observation.elapsed_seconds)
            for item, observation in zip(predictions, measured)
        ]
        return {
            "schema_version": "graph-lab-gnn-metrics-v1",
            "examples": len(observations),
            "training_examples": len(training),
            "validation_examples": len(validation),
            "metric_partition": "validation" if validation else "training_fallback",
            "transitions": transitions,
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
            },
            temporary,
        )
        temporary.replace(path)

    @classmethod
    def load_or_create(
        cls, path: Path, config: Mapping[str, object]
    ) -> "GraphLearningModel":
        result = cls(config)
        if not path.exists():
            return result
        payload = torch.load(path, map_location="cpu", weights_only=False)
        if payload.get("version") != MODEL_VERSION:
            raise ValueError("Stored Graph Lab model is incompatible; use --restart")
        result.network.load_state_dict(payload["network"])
        result.optimizer.load_state_dict(payload["optimizer"])
        result.active_heads = np.asarray(payload["active_heads"], dtype=bool)
        result.empirical_rates = np.asarray(
            payload["empirical_rates"], dtype=np.float32
        )
        return result
