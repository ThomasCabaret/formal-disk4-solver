from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from formal_disk4.pipeline.output import atomic_replace
from formal_disk4.words.specialization_policy import (
    FamilySpecializationPolicy,
    SpecializationActionView,
    SpecializationOutcomeView,
    SpecializationPoolStateView,
)

from .mapping import MappingProposal
from .mapping_model import EDGE_FEATURES, MAPPING_FEATURES, mapping_tensors
from .model import GLOBAL_FEATURES, NODE_FEATURES

try:
    import torch
    from torch import nn
except ImportError as error:  # pragma: no cover
    raise RuntimeError(
        "Graph Lab specialization learning requires PyTorch. Install the "
        "project with `pip install -e .[graph-lab]`."
    ) from error


MODEL_VERSION = "graph-lab-family-specialization-ranker-v2-symbolic"
STATE_FEATURES = 8
ACTION_FEATURES = 17
STRUCTURAL_FEATURES = 128


def _hashed_feature(vector: np.ndarray, name: str, value: float = 1.0) -> None:
    """Add one deterministic signed feature without a graph-sized vocabulary."""

    digest = hashlib.blake2b(name.encode("utf-8"), digest_size=8).digest()
    raw = int.from_bytes(digest, "little")
    vector[raw % len(vector)] += value if (raw >> 63) == 0 else -value


def _structural_features(
    state: SpecializationPoolStateView,
    action: SpecializationActionView,
) -> torch.Tensor:
    """Encode the actual weak placement and symbolic family, not only counts.

    Canonical occurrence/literal integers make the motifs reusable across graph
    sizes.  Signed feature hashing keeps the model bounded while retaining
    singleton, adjacency and short word-order motifs.
    """

    vector = np.zeros(STRUCTURAL_FEATURES, dtype=np.float32)
    block_count = max(1, len(state.placement_blocks))
    for block_index, block in enumerate(state.placement_blocks):
        phase = min(7, (8 * block_index) // block_count)
        _hashed_feature(vector, f"block-size:{min(8, len(block))}")
        for occurrence in block:
            _hashed_feature(vector, f"block-occ:{phase}:{occurrence}")
        for left in block:
            for right in block:
                if left < right:
                    _hashed_feature(vector, f"simultaneous:{left}:{right}")
        following = state.placement_blocks[(block_index + 1) % block_count]
        for left in block:
            for right in following:
                _hashed_feature(vector, f"block-next:{left}:{right}")

    word_count = max(1, len(action.environment_words))
    for word_index, word in enumerate(action.environment_words):
        word_phase = min(7, (8 * word_index) // word_count)
        _hashed_feature(vector, f"word-length:{word_phase}:{min(16, len(word))}")
        if not word:
            _hashed_feature(vector, f"word-empty:{word_phase}")
            continue
        for position, token in enumerate(word):
            token_phase = min(7, (8 * position) // len(word))
            _hashed_feature(
                vector,
                f"literal:{word_phase}:{token_phase}:{token}",
            )
        for left, right in zip(word, word[1:]):
            _hashed_feature(vector, f"literal-bigram:{left}:{right}")
        _hashed_feature(vector, f"word-ends:{word[0]}:{word[-1]}")

    norm = float(np.linalg.norm(vector))
    if norm > 0.0:
        vector /= norm
    return torch.from_numpy(vector)


def _context_features(
    state: SpecializationPoolStateView,
    action: SpecializationActionView,
) -> torch.Tensor:
    literals = max(1, action.total_word_literals)
    words = max(1, action.environment_variable_count)
    state_values = (
        state.placement_block_count / 32.0,
        state.solver_variable_count / 32.0,
        state.equation_count / 64.0,
        state.interface_count / 64.0,
        state.outer_arc_count / 16.0,
        state.contour_literal_count / 64.0,
        state.family_count / 32.0,
        state.candidate_count / 32.0,
    )
    action_values = (
        1.0 if action.family_kind == "finite" else 0.0,
        1.0 if action.family_kind == "power" else 0.0,
        action.residual_graph_nodes / 256.0,
        action.family_power_depth / 8.0,
        action.family_trace_length / 32.0,
        action.exponent_variable_count / 8.0,
        action.exponent_sum / 32.0,
        action.exponent_minimum / 16.0,
        action.exponent_maximum / 16.0,
        action.environment_variable_count / 32.0,
        action.total_word_literals / 256.0,
        action.maximum_word_literals / 64.0,
        action.distinct_word_count / words,
        action.distinct_literal_variable_count / 32.0,
        action.inverse_literal_count / literals,
        action.empty_word_count / words,
        (action.total_word_literals - action.distinct_literal_variable_count)
        / literals,
    )
    return torch.tensor((*state_values, *action_values), dtype=torch.float32)


class SpecializationGraphNetwork(nn.Module):
    def __init__(self, hidden_size: int, message_layers: int) -> None:
        super().__init__()
        self.node_input = nn.Linear(
            NODE_FEATURES + MAPPING_FEATURES, hidden_size
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
        self.context_input = nn.Linear(STATE_FEATURES + ACTION_FEATURES, hidden_size)
        self.structural_input = nn.Linear(STRUCTURAL_FEATURES, hidden_size)
        self.trunk = nn.Sequential(
            nn.Linear(6 * hidden_size, 2 * hidden_size),
            nn.ReLU(),
            nn.Linear(2 * hidden_size, hidden_size),
            nn.ReLU(),
        )
        self.heads = nn.Linear(hidden_size, 2)

    def encode_mapping(
        self,
        nodes: torch.Tensor,
        adjacency: torch.Tensor,
        globals_: torch.Tensor,
        outside_index: int,
        edge_features: torch.Tensor,
    ) -> torch.Tensor:
        hidden = torch.relu(self.node_input(nodes))
        count = len(hidden)
        for message_layer, update_layer in zip(
            self.message_layers, self.update_layers
        ):
            sources = hidden.unsqueeze(0).expand(count, count, -1)
            messages = torch.relu(
                message_layer(torch.cat((sources, edge_features), dim=2))
            )
            messages = (messages * adjacency.unsqueeze(2)).sum(dim=1)
            hidden = torch.relu(
                update_layer(torch.cat((hidden, messages), dim=1))
            ) + hidden
        mask = torch.ones(len(hidden), dtype=torch.bool, device=hidden.device)
        mask[outside_index] = False
        tiles = hidden[mask]
        return torch.cat(
            (
                tiles.mean(dim=0),
                tiles.max(dim=0).values,
                hidden[outside_index],
                torch.relu(self.global_input(globals_)),
            )
        )

    def score_actions(
        self,
        mapping_encoding: torch.Tensor,
        contexts: torch.Tensor,
        structures: torch.Tensor,
    ) -> torch.Tensor:
        if contexts.ndim == 1:
            contexts = contexts.unsqueeze(0)
        if structures.ndim == 1:
            structures = structures.unsqueeze(0)
        repeated = mapping_encoding.unsqueeze(0).expand(len(contexts), -1)
        combined = torch.cat(
            (
                repeated,
                torch.relu(self.context_input(contexts)),
                torch.relu(self.structural_input(structures)),
            ),
            dim=1,
        )
        return self.heads(self.trunk(combined))

    def forward(
        self,
        nodes: torch.Tensor,
        adjacency: torch.Tensor,
        globals_: torch.Tensor,
        outside_index: int,
        edge_features: torch.Tensor,
        contexts: torch.Tensor,
        structures: torch.Tensor,
    ) -> torch.Tensor:
        return self.score_actions(
            self.encode_mapping(
                nodes, adjacency, globals_, outside_index, edge_features
            ),
            contexts,
            structures,
        )


@dataclass(frozen=True)
class SpecializationDecisionObservation:
    action: SpecializationActionView
    outcome: SpecializationOutcomeView
    selection_mode: str
    selection_probability: float
    policy_entropy: float
    predicted_valid_probability: float
    predicted_emission_probability: float
    selection_score: float

    @property
    def valid_target(self) -> float | None:
        if self.outcome.stage == "profile_build_error":
            return None
        return float(self.outcome.valid_profile)

    @property
    def emission_target(self) -> float | None:
        if self.outcome.stage == "profile_build_error":
            return None
        return float(self.outcome.emitted)

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action.to_dict(),
            "outcome": {
                "valid_profile": self.outcome.valid_profile,
                "emitted": self.outcome.emitted,
                "duplicate": self.outcome.duplicate,
                "stage": self.outcome.stage,
                "reason": self.outcome.reason,
                "elapsed_seconds": self.outcome.elapsed_seconds,
                "formal_profile_id": self.outcome.formal_profile_id,
            },
            "selection_mode": self.selection_mode,
            "selection_probability": self.selection_probability,
            "policy_entropy": self.policy_entropy,
            "predicted_valid_probability": self.predicted_valid_probability,
            "predicted_emission_probability": self.predicted_emission_probability,
            "selection_score": self.selection_score,
        }

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, object]
    ) -> "SpecializationDecisionObservation":
        raw = dict(payload["outcome"])  # type: ignore[arg-type]
        return cls(
            action=SpecializationActionView.from_dict(
                dict(payload["action"])  # type: ignore[arg-type]
            ),
            outcome=SpecializationOutcomeView(
                valid_profile=bool(raw.get("valid_profile", False)),
                emitted=bool(raw.get("emitted", False)),
                duplicate=bool(raw.get("duplicate", False)),
                stage=str(raw.get("stage", "unknown")),
                reason=str(raw["reason"]) if raw.get("reason") else None,
                elapsed_seconds=float(raw.get("elapsed_seconds", 0.0)),
                formal_profile_id=(
                    str(raw["formal_profile_id"])
                    if raw.get("formal_profile_id")
                    else None
                ),
            ),
            selection_mode=str(payload.get("selection_mode", "restored")),
            selection_probability=float(payload.get("selection_probability", 1.0)),
            policy_entropy=float(payload.get("policy_entropy", 0.0)),
            predicted_valid_probability=float(
                payload.get("predicted_valid_probability", 0.5)
            ),
            predicted_emission_probability=float(
                payload.get("predicted_emission_probability", 0.5)
            ),
            selection_score=float(payload.get("selection_score", 0.0)),
        )


@dataclass(frozen=True)
class SpecializationPoolObservation:
    proposal: MappingProposal
    state: SpecializationPoolStateView
    decisions: tuple[SpecializationDecisionObservation, ...]
    pool_sequence: int
    random_seed: int

    @property
    def pool_id(self) -> str:
        raw = (
            f"{self.proposal.mapping_id}|{self.random_seed}|{self.pool_sequence}|"
            f"{self.state.assignment_id}|{self.state.placement_id}"
        )
        return "sp-" + hashlib.sha256(raw.encode()).hexdigest()[:32]

    def to_dict(self, *, include_proposal: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "graph-lab-specialization-pool-v1",
            "pool_id": self.pool_id,
            "mapping_id": self.proposal.mapping_id,
            "state": self.state.to_dict(),
            "decisions": [item.to_dict() for item in self.decisions],
            "pool_sequence": self.pool_sequence,
            "random_seed": self.random_seed,
        }
        if include_proposal:
            payload["proposal"] = self.proposal.to_dict()
        return payload

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, object],
        *,
        proposal: MappingProposal | None = None,
    ) -> "SpecializationPoolObservation":
        if proposal is None:
            raw_proposal = payload.get("proposal")
            if not isinstance(raw_proposal, Mapping):
                raise ValueError(
                    "Compact specialization pool has no preceding mapping proposal"
                )
            proposal = MappingProposal.from_dict(raw_proposal)
        return cls(
            proposal=proposal,
            state=SpecializationPoolStateView.from_dict(
                dict(payload["state"])  # type: ignore[arg-type]
            ),
            decisions=tuple(
                SpecializationDecisionObservation.from_dict(value)
                for value in payload.get("decisions", ())  # type: ignore[union-attr]
            ),
            pool_sequence=int(payload.get("pool_sequence", 0)),
            random_seed=int(payload.get("random_seed", 0)),
        )


@dataclass(frozen=True)
class SpecializationPrediction:
    valid_probability: float
    emission_probability: float


class SpecializationLearningModel:
    """Graph-conditioned ranker for word-family specialization pools."""

    def __init__(self, config: Mapping[str, object]) -> None:
        self.config = dict(config)
        self.seed = int(config.get("seed", 20260815))
        self.tile_scale = max(1.0, float(config.get("tile_feature_scale", 13.0)))
        torch.manual_seed(self.seed)
        torch.set_num_threads(max(1, int(config.get("torch_threads", 1))))
        self.network = SpecializationGraphNetwork(
            max(8, int(config.get("hidden_size", 64))),
            max(1, int(config.get("message_layers", 3))),
        )
        self.optimizer = torch.optim.AdamW(
            self.network.parameters(),
            lr=float(config.get("learning_rate", 0.001)),
            weight_decay=float(config.get("weight_decay", 1e-4)),
        )
        self.positive_support = 0
        self.negative_support = 0

    @property
    def has_policy_signal(self) -> bool:
        minimum = max(1, int(self.config.get("minimum_class_support", 8)))
        return self.positive_support >= minimum and self.negative_support >= minimum

    def _logits_many(
        self,
        proposal: MappingProposal,
        state: SpecializationPoolStateView,
        actions: Sequence[SpecializationActionView],
    ) -> torch.Tensor:
        if not actions:
            return torch.empty((0, 2), dtype=torch.float32)
        nodes, adjacency, globals_, outside, edges = mapping_tensors(
            proposal, tile_scale=self.tile_scale
        )
        return self.network(
            nodes,
            adjacency,
            globals_,
            outside,
            edges,
            torch.stack(tuple(_context_features(state, action) for action in actions)),
            torch.stack(tuple(_structural_features(state, action) for action in actions)),
        )

    def _logits(
        self,
        proposal: MappingProposal,
        state: SpecializationPoolStateView,
        action: SpecializationActionView,
    ) -> torch.Tensor:
        return self._logits_many(proposal, state, (action,))[0]

    def predict(
        self,
        proposal: MappingProposal,
        state: SpecializationPoolStateView,
        action: SpecializationActionView,
    ) -> SpecializationPrediction:
        return self.predict_many(proposal, state, (action,))[0]

    def predict_many(
        self,
        proposal: MappingProposal,
        state: SpecializationPoolStateView,
        actions: Sequence[SpecializationActionView],
    ) -> tuple[SpecializationPrediction, ...]:
        self.network.eval()
        with torch.no_grad():
            probabilities = torch.sigmoid(
                self._logits_many(proposal, state, actions)
            ).tolist()
        return tuple(
            SpecializationPrediction(float(valid), float(emitted))
            for valid, emitted in probabilities
        )

    @staticmethod
    def _is_validation(observation: SpecializationPoolObservation) -> bool:
        digest = hashlib.sha256(
            observation.proposal.candidate.graph_id.encode()
        ).digest()
        return digest[0] < 51

    @staticmethod
    def _auc(labels: np.ndarray, scores: np.ndarray) -> float | None:
        positives = scores[labels]
        negatives = scores[~labels]
        if not len(positives) or not len(negatives):
            return None
        return float(
            np.mean(
                (positives[:, None] > negatives[None, :])
                + 0.5 * (positives[:, None] == negatives[None, :])
            )
        )

    @staticmethod
    def _flatten(
        observations: Sequence[SpecializationPoolObservation],
    ) -> list[tuple[SpecializationPoolObservation, SpecializationDecisionObservation]]:
        return [
            (pool, decision)
            for pool in observations
            for decision in pool.decisions
            if decision.valid_target is not None
        ]

    def _refresh_support(
        self, observations: Sequence[SpecializationPoolObservation]
    ) -> None:
        targets = [
            decision.valid_target
            for _pool, decision in self._flatten(observations)
        ]
        self.positive_support = sum(value == 1.0 for value in targets)
        self.negative_support = sum(value == 0.0 for value in targets)

    def train(
        self,
        observations: Sequence[SpecializationPoolObservation],
        *,
        steps: int,
        batch_size: int,
        generation: int,
    ) -> dict[str, object]:
        maximum = max(1, int(self.config.get("replay_pools", 20000)))
        replay = list(observations[-maximum:])
        training_pools = [item for item in replay if not self._is_validation(item)]
        if not training_pools:
            training_pools = replay
        self._refresh_support(training_pools)
        examples = self._flatten(training_pools)
        if not examples:
            return self.metrics(observations)
        positives = max(1, self.positive_support)
        negatives = max(1, self.negative_support)
        total = positives + negatives
        positive_weight = min(50.0, total / (2.0 * positives))
        negative_weight = min(50.0, total / (2.0 * negatives))
        rng = random.Random(self.seed + int(generation) * 1009)
        losses = []
        ranking_losses = []
        ranking_weight = max(
            0.0, float(self.config.get("ranking_loss_weight", 0.5))
        )
        ranking_pairs_per_step = max(
            0, int(self.config.get("ranking_pairs_per_step", 4))
        )
        pair_pools = []
        for pool in training_pools:
            positives_in_pool = [
                item for item in pool.decisions if item.valid_target == 1.0
            ]
            negatives_in_pool = [
                item for item in pool.decisions if item.valid_target == 0.0
            ]
            if positives_in_pool and negatives_in_pool:
                pair_pools.append((pool, positives_in_pool, negatives_in_pool))
        self.network.train()
        for _step in range(max(0, int(steps))):
            batch = [
                examples[rng.randrange(len(examples))]
                for _ in range(max(1, int(batch_size)))
            ]
            loss = torch.tensor(0.0)
            for pool, decision in batch:
                logits = self._logits(pool.proposal, pool.state, decision.action)
                valid = torch.tensor(float(decision.valid_target))
                emitted = torch.tensor(float(decision.emission_target or 0.0))
                valid_loss = torch.nn.functional.binary_cross_entropy_with_logits(
                    logits[0], valid, reduction="none"
                ) * (positive_weight if valid.item() else negative_weight)
                emission_loss = torch.nn.functional.binary_cross_entropy_with_logits(
                    logits[1], emitted
                )
                loss = loss + valid_loss + 0.25 * emission_loss
            loss = loss / len(batch)

            # Classification calibrates absolute probabilities.  This direct
            # within-pool loss teaches the actual decision we need: put a
            # profile-valid family ahead of an invalid sibling from the same
            # word case.
            pair_loss = torch.tensor(0.0)
            pair_batch = (
                rng.sample(pair_pools, min(ranking_pairs_per_step, len(pair_pools)))
                if pair_pools and ranking_pairs_per_step
                else []
            )
            for pool, positives_in_pool, negatives_in_pool in pair_batch:
                positive = rng.choice(positives_in_pool)
                negative = rng.choice(negatives_in_pool)
                logits = self._logits_many(
                    pool.proposal,
                    pool.state,
                    (positive.action, negative.action),
                )[:, 0]
                pair_loss = pair_loss + torch.nn.functional.softplus(
                    -(logits[0] - logits[1])
                )
            if pair_batch:
                pair_loss = pair_loss / len(pair_batch)
                loss = loss + ranking_weight * pair_loss
                ranking_losses.append(float(pair_loss.detach()))
            self.optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.network.parameters(), 5.0)
            self.optimizer.step()
            losses.append(float(loss.detach()))
        result = self.metrics(observations)
        result["training_loss"] = float(np.mean(losses)) if losses else None
        result["training_pairwise_loss"] = (
            float(np.mean(ranking_losses)) if ranking_losses else None
        )
        result["training_pairwise_pools"] = len(pair_pools)
        result["training_replay_pools"] = len(training_pools)
        return result

    def metrics(
        self, observations: Sequence[SpecializationPoolObservation]
    ) -> dict[str, object]:
        replay = list(observations[-max(1, int(self.config.get("metric_pools", 4000))):])
        training = [item for item in replay if not self._is_validation(item)]
        validation = [item for item in replay if self._is_validation(item)]
        self._refresh_support(training or replay)
        measured = validation or training or replay
        examples = self._flatten(measured)
        labels = []
        emissions = []
        scores = []
        emission_scores = []
        pair_correct = 0
        pair_count = 0
        by_pool: dict[str, list[tuple[float, float]]] = {}
        for pool in measured:
            decisions = tuple(
                decision
                for decision in pool.decisions
                if decision.valid_target is not None
            )
            predictions = self.predict_many(
                pool.proposal,
                pool.state,
                tuple(decision.action for decision in decisions),
            )
            for decision, prediction in zip(decisions, predictions):
                label = float(decision.valid_target)
                labels.append(label)
                emissions.append(float(decision.emission_target or 0.0))
                scores.append(prediction.valid_probability)
                emission_scores.append(prediction.emission_probability)
                by_pool.setdefault(pool.pool_id, []).append(
                    (label, prediction.valid_probability)
                )
        for values in by_pool.values():
            positives = [score for label, score in values if label == 1.0]
            negatives = [score for label, score in values if label == 0.0]
            for positive in positives:
                for negative in negatives:
                    pair_count += 1
                    pair_correct += int(positive > negative)
        label_array = np.asarray(labels, dtype=float)
        score_array = np.asarray(scores, dtype=float)
        emission_array = np.asarray(emissions, dtype=float)
        emission_score_array = np.asarray(emission_scores, dtype=float)

        def head(name: str, raw_labels: np.ndarray, raw_scores: np.ndarray) -> dict[str, object]:
            auc = self._auc(raw_labels >= 0.5, raw_scores) if len(raw_labels) else None
            return {
                "id": name,
                "active": bool(len(raw_labels)),
                "eligible": int(len(raw_labels)),
                "positives": int(np.sum(raw_labels >= 0.5)) if len(raw_labels) else 0,
                "mean_rate": float(np.mean(raw_labels)) if len(raw_labels) else None,
                "mean_prediction": float(np.mean(raw_scores)) if len(raw_scores) else None,
                "binary_auc": auc,
                "brier_score": float(np.mean((raw_scores - raw_labels) ** 2)) if len(raw_labels) else None,
            }

        valid = head("specialization.profile_valid", label_array, score_array)
        emitted = head(
            "specialization.profile_emitted", emission_array, emission_score_array
        )
        return {
            "schema_version": "graph-lab-specialization-metrics-v1",
            "pools": len(observations),
            "training_pools": len(training),
            "validation_pools": len(validation),
            "metric_partition": "validation" if validation else "training_fallback",
            "examples": len(examples),
            "has_policy_signal": self.has_policy_signal,
            "positive_support": self.positive_support,
            "negative_support": self.negative_support,
            "filters": {
                "specialization.profile_valid": valid,
                "specialization.profile_emitted": emitted,
            },
            "reach": {
                "specialization.profile_valid": valid,
                "specialization.profile_emitted": emitted,
            },
            "values": {
                "profile_valid": valid,
                "profile_emitted": emitted,
            },
            "pairwise_ranking": {
                "profile_valid": {
                    "accuracy": pair_correct / pair_count if pair_count else None,
                    "pairs": pair_count,
                    "scope": "same_word_case_specialization_pool",
                }
            },
            "curriculum": {
                "status": "active" if self.has_policy_signal else "collecting_both_classes",
                "frontier_filter": "specialization.profile_valid",
                "within_parent_pair_accuracy": pair_correct / pair_count if pair_count else None,
                "within_parent_pairs": pair_count,
            },
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
                "positive_support": self.positive_support,
                "negative_support": self.negative_support,
            },
            temporary,
        )
        atomic_replace(temporary, path)

    @classmethod
    def load_or_create(
        cls, path: Path, config: Mapping[str, object]
    ) -> "SpecializationLearningModel":
        result = cls(config)
        if not path.exists():
            return result
        payload = torch.load(path, map_location="cpu", weights_only=False)
        if payload.get("version") != MODEL_VERSION:
            raise ValueError("Stored specialization model is incompatible; use --restart")
        result.network.load_state_dict(payload["network"])
        result.optimizer.load_state_dict(payload["optimizer"])
        result.positive_support = int(payload.get("positive_support", 0))
        result.negative_support = int(payload.get("negative_support", 0))
        return result


class SpecializationRankedPolicy(FamilySpecializationPolicy):
    """Stochastic pool ranker that always preserves every legal candidate."""

    def __init__(
        self,
        proposal: MappingProposal,
        model: SpecializationLearningModel,
        config: Mapping[str, object],
        *,
        random_seed: int,
    ) -> None:
        self.proposal = proposal
        self.model = model
        self.config = dict(config)
        self.random_seed = int(random_seed)
        self.rng = random.Random(self.random_seed)
        self._sequence = 0
        self._plans: dict[int, dict[int, tuple[str, float, float, float, float, float]]] = {}
        self._builders: dict[int, tuple[SpecializationPoolStateView, int, list[SpecializationDecisionObservation]]] = {}

    @property
    def observations(self) -> tuple[SpecializationPoolObservation, ...]:
        return tuple(
            SpecializationPoolObservation(
                self.proposal, state, tuple(decisions), sequence, self.random_seed
            )
            for state, sequence, decisions in self._builders.values()
            if decisions
        )

    def select_specializations(
        self,
        state: SpecializationPoolStateView,
        actions: Sequence[SpecializationActionView],
    ) -> Sequence[int]:
        sequence = self._sequence
        self._sequence += 1
        predictions = list(self.model.predict_many(self.proposal, state, actions))
        visit_budget = min(
            len(actions),
            max(1, int(self.config.get("visits_per_pool", 4))),
        )
        if not self.model.has_policy_signal or len(actions) < 2:
            order = self.rng.sample(range(len(actions)), visit_budget)
            modes = {index: "exploration" for index in order}
            probabilities = {index: 1.0 / max(1, len(actions)) for index in order}
            entropy = math.log(max(1, len(actions)))
        else:
            exploration_count = max(
                1,
                min(
                    visit_budget,
                    int(
                        round(
                            visit_budget
                            * float(
                                self.config.get("exploration_fraction", 0.25)
                            )
                        )
                    ),
                ),
            )
            controls = set(self.rng.sample(range(len(actions)), exploration_count))
            learned = [index for index in range(len(actions)) if index not in controls]
            learned_count = visit_budget - exploration_count
            temperature = max(1e-3, float(self.config.get("temperature", 0.7)))
            epsilon = min(1.0, max(0.0, float(self.config.get("epsilon", 0.15))))
            learned_order = []
            probabilities = {}
            entropies = []
            remaining = list(learned)
            while remaining and len(learned_order) < learned_count:
                logits = np.asarray(
                    [
                        math.log(max(1e-6, predictions[index].valid_probability))
                        for index in remaining
                    ],
                    dtype=float,
                ) / temperature
                logits -= np.max(logits)
                weights = np.exp(np.clip(logits, -60.0, 0.0))
                weights = (1.0 - epsilon) * weights / max(1e-12, float(np.sum(weights))) + epsilon / len(remaining)
                choice = self.rng.choices(range(len(remaining)), weights=weights, k=1)[0]
                index = remaining.pop(choice)
                probabilities[index] = float(weights[choice])
                entropies.append(float(-np.sum(weights * np.log(np.maximum(weights, 1e-12)))))
                learned_order.append(index)
            control_order = list(controls)
            self.rng.shuffle(control_order)
            for index in control_order:
                probabilities[index] = 1.0 / max(1, len(actions))
            order = []
            while learned_order or control_order:
                if learned_order:
                    order.append(learned_order.pop(0))
                if control_order:
                    order.append(control_order.pop(0))
            modes = {index: ("exploration" if index in controls else "learned") for index in order}
            entropy = float(np.mean(entropies)) if entropies else 0.0
        self._plans[id(state)] = {
            index: (
                modes[index],
                probabilities[index],
                entropy,
                predictions[index].valid_probability,
                predictions[index].emission_probability,
                predictions[index].valid_probability,
            )
            for index in order
        }
        self._builders[id(state)] = (state, sequence, [])
        return order

    def observe_specialization(
        self,
        state: SpecializationPoolStateView,
        action: SpecializationActionView,
        outcome: SpecializationOutcomeView,
    ) -> None:
        mode, probability, entropy, valid, emitted, score = self._plans[id(state)][action.index]
        self._builders[id(state)][2].append(
            SpecializationDecisionObservation(
                action,
                outcome,
                mode,
                probability,
                entropy,
                valid,
                emitted,
                score,
            )
        )
