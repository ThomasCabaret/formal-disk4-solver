from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from formal_disk4.pipeline.filter_report import LEARNING_FILTER_IDS

from .mapping import MappingEvaluation, MappingProposal
from .model import GLOBAL_FEATURES, NODE_FEATURES, graph_tensors

try:
    import torch
    from torch import nn
except ImportError as error:  # pragma: no cover
    raise RuntimeError(
        "Graph Lab mapping learning requires PyTorch. Install the project with "
        "`pip install -e .[graph-lab]`."
    ) from error


MODEL_VERSION = "graph-lab-mapping-gnn-v1"
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
        self.cost_head = nn.Linear(hidden_size, 1)

    def forward(
        self,
        node_features: torch.Tensor,
        adjacency: torch.Tensor,
        global_features: torch.Tensor,
        outside_index: int,
        edge_features: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
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
        return self.filter_heads(representation), self.cost_head(representation).squeeze(0)


@dataclass(frozen=True)
class MappingPrediction:
    conditional_probabilities: tuple[float, ...]
    reach_probabilities: tuple[float, ...]
    utility: float
    expected_seconds: float


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
        self.empirical_rates = np.full(len(LEARNING_FILTER_IDS), 0.5, dtype=np.float32)

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
            self.active_heads[head] = positive > 0.0 and negative > 0.0
            self.empirical_rates[head] = float((positive + 0.5) / (len(labels) + 1.0))

    def predict(self, proposal: MappingProposal) -> MappingPrediction:
        self.network.eval()
        with torch.no_grad():
            logits, log_cost = self.network(
                *mapping_tensors(proposal, tile_scale=self.tile_scale)
            )
            probabilities = torch.sigmoid(logits).cpu().numpy()
        probabilities[~self.active_heads] = self.empirical_rates[~self.active_heads]
        reach = np.cumprod(probabilities)
        weights = np.asarray(
            [float(value) for value in self.config.get(
                "filter_weights", [1.0] * len(LEARNING_FILTER_IDS)
            )],
            dtype=np.float32,
        )
        if len(weights) != len(LEARNING_FILTER_IDS):
            weights = np.ones(len(LEARNING_FILTER_IDS), dtype=np.float32)
        utility = float(np.sum(weights * reach))
        return MappingPrediction(
            conditional_probabilities=tuple(float(value) for value in probabilities),
            reach_probabilities=tuple(float(value) for value in reach),
            utility=utility,
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
    ) -> dict[str, object]:
        if not observations:
            return self.metrics(observations)
        training, _ = self._partitions(observations)
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
            for observation in selected:
                logits, log_cost = self.network(
                    *mapping_tensors(observation.proposal, tile_scale=self.tile_scale)
                )
                for head, target in enumerate(observation.target_vector):
                    if target is None or not self.active_heads[head]:
                        continue
                    loss = loss + torch.nn.functional.binary_cross_entropy_with_logits(
                        logits[head], torch.tensor(float(target), dtype=torch.float32)
                    )
                    terms += 1
                loss = loss + float(self.config.get("cost_loss_weight", 0.05)) * (
                    torch.nn.functional.smooth_l1_loss(
                        log_cost,
                        torch.tensor(math.log1p(observation.elapsed_seconds)),
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

    def metrics(self, observations: Sequence[MappingEvaluation]) -> dict[str, object]:
        if not observations:
            return {
                "schema_version": "graph-lab-mapping-metrics-v1",
                "examples": 0,
                "filters": {},
            }
        training, validation = self._partitions(observations)
        self._refresh_statistics(training)
        measured = validation if validation else training
        predictions = [self.predict(item.proposal) for item in measured]
        filters: dict[str, object] = {}
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
            filters[filter_id] = {
                "eligible": len(eligible),
                "mean_conditional_pass_rate": float(np.mean(labels)) if len(labels) else None,
                "mean_prediction": float(np.mean(scores)) if len(scores) else None,
                "binary_auc": self._auc(labels >= 0.5, scores),
                "active": bool(self.active_heads[head]),
            }
        return {
            "schema_version": "graph-lab-mapping-metrics-v1",
            "examples": len(observations),
            "training_examples": len(training),
            "validation_examples": len(validation),
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
    ) -> "MappingLearningModel":
        result = cls(config)
        if not path.exists():
            return result
        payload = torch.load(path, map_location="cpu", weights_only=False)
        if payload.get("version") != MODEL_VERSION:
            raise ValueError("Stored mapping model is incompatible; use --restart")
        result.network.load_state_dict(payload["network"])
        result.optimizer.load_state_dict(payload["optimizer"])
        result.active_heads = np.asarray(payload["active_heads"], dtype=bool)
        result.empirical_rates = np.asarray(payload["empirical_rates"], dtype=np.float32)
        return result
