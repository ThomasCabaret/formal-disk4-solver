from __future__ import annotations

import random
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np

from .evaluator import GraphEvaluation
from .feedback import LearningFeedback
from .model import GraphLearningModel
from .space import DualGraphCandidate


SelectionRecord = tuple[DualGraphCandidate, Mapping[str, object]]
NoveltyFunction = Callable[[DualGraphCandidate], float]


class GraphSelectionPolicy(ABC):
    """Strategy boundary for graph ordering.

    Proposal generation is intentionally outside this contract.  A future
    incremental graph backtracker can feed the same policy, while callers and
    the formal evaluation service remain unchanged.
    """

    mode: str

    @abstractmethod
    def select(
        self,
        pool: Sequence[DualGraphCandidate],
        *,
        novelty: NoveltyFunction,
        rng: random.Random,
        amount: int,
    ) -> list[SelectionRecord]:
        raise NotImplementedError

    @abstractmethod
    def train(
        self,
        observations: Sequence[GraphEvaluation],
        *,
        generation: int,
        feedback: LearningFeedback,
    ) -> Mapping[str, object]:
        raise NotImplementedError

    @abstractmethod
    def metrics(
        self,
        observations: Sequence[GraphEvaluation],
        *,
        feedback: LearningFeedback,
    ) -> Mapping[str, object]:
        raise NotImplementedError

    @abstractmethod
    def save(self) -> None:
        raise NotImplementedError


class PriorOnlyGraphPolicy(GraphSelectionPolicy):
    mode = "prior"

    def select(
        self,
        pool: Sequence[DualGraphCandidate],
        *,
        novelty: NoveltyFunction,
        rng: random.Random,
        amount: int,
    ) -> list[SelectionRecord]:
        chosen = rng.sample(list(pool), min(max(1, amount), len(pool)))
        return [
            (
                candidate,
                {
                    "selection_mode": "exploration",
                    "policy_mode": "prior",
                    "selection_score": novelty(candidate),
                    "novelty": novelty(candidate),
                    "predicted_stage": None,
                    "predicted_geometry_probability": None,
                    "predicted_value_probabilities": [],
                    "predicted_transition_probabilities": [],
                    "predicted_seconds": None,
                },
            )
            for candidate in chosen
        ]

    @staticmethod
    def _metrics(observations: Sequence[GraphEvaluation]) -> Mapping[str, object]:
        return {
            "schema_version": "graph-lab-prior-policy-metrics-v1",
            "mode": "prior",
            "status": "learning_disabled",
            "examples": len(observations),
            "training_examples": 0,
            "validation_examples": 0,
            "transitions": {},
            "values": {},
            "pairwise_ranking": {},
            "curriculum": {
                "status": "disabled",
                "frontier_stage": None,
                "probability_semantics": "No learned probabilities in prior-only mode.",
            },
        }

    def train(
        self,
        observations: Sequence[GraphEvaluation],
        *,
        generation: int,
        feedback: LearningFeedback,
    ) -> Mapping[str, object]:
        del generation, feedback
        return self._metrics(observations)

    def metrics(
        self,
        observations: Sequence[GraphEvaluation],
        *,
        feedback: LearningFeedback,
    ) -> Mapping[str, object]:
        del feedback
        return self._metrics(observations)

    def save(self) -> None:
        return


class LearnedGraphPolicy(GraphSelectionPolicy):
    mode = "learned"

    def __init__(
        self,
        checkpoint: Path,
        learning: Mapping[str, object],
        sampling: Mapping[str, object],
    ) -> None:
        self.checkpoint = checkpoint
        self.learning = dict(learning)
        self.sampling = dict(sampling)
        self.model = GraphLearningModel.load_or_create(checkpoint, self.learning)

    def select(
        self,
        pool: Sequence[DualGraphCandidate],
        *,
        novelty: NoveltyFunction,
        rng: random.Random,
        amount: int,
    ) -> list[SelectionRecord]:
        amount = min(max(1, amount), len(pool))
        exploration = min(
            amount,
            max(
                1,
                int(
                    round(
                        amount
                        * float(self.sampling.get("exploration_fraction", 0.25))
                    )
                ),
            ),
        )
        scored = []
        for candidate in pool:
            candidate_novelty = novelty(candidate)
            score, prediction = self.model.utility(
                candidate,
                novelty=candidate_novelty,
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
            scored.append((score, candidate, prediction, candidate_novelty))
        if not self.model.has_policy_signal:
            selected = [
                (item, "exploration") for item in rng.sample(scored, amount)
            ]
        else:
            random_control = rng.sample(scored, exploration) if exploration else []
            control_ids = {item[1].graph_id for item in random_control}
            remaining = [
                item for item in scored if item[1].graph_id not in control_ids
            ]
            learned = []
            temperature = max(
                1e-3, float(self.sampling.get("temperature", 0.7))
            )
            epsilon = min(
                1.0, max(0.0, float(self.sampling.get("epsilon", 0.15)))
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
                candidate,
                {
                    "selection_mode": selection_mode,
                    "selection_score": score,
                    "novelty": candidate_novelty,
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
            for (
                score,
                candidate,
                prediction,
                candidate_novelty,
            ), selection_mode in selected
        ]

    def train(
        self,
        observations: Sequence[GraphEvaluation],
        *,
        generation: int,
        feedback: LearningFeedback,
    ) -> Mapping[str, object]:
        metrics = dict(
            self.model.train(
                observations,
                steps=int(self.learning.get("steps_per_generation", 8)),
                batch_size=int(self.learning.get("batch_size", 16)),
                generation=generation,
                feedback=feedback,
            )
        )
        metrics["mode"] = "learned"
        self.save()
        return metrics

    def bootstrap(
        self,
        observations: Sequence[GraphEvaluation],
        *,
        feedback: LearningFeedback,
    ) -> None:
        if observations and not self.checkpoint.exists():
            self.model.train(
                observations,
                steps=int(self.learning.get("bootstrap_steps", 100)),
                batch_size=int(self.learning.get("batch_size", 16)),
                generation=-1,
                feedback=feedback,
            )

    def metrics(
        self,
        observations: Sequence[GraphEvaluation],
        *,
        feedback: LearningFeedback,
    ) -> Mapping[str, object]:
        metrics = dict(
            self.model.metrics(
                observations,
                feedback=feedback,
                maximum_examples=int(self.learning.get("metric_examples", 512)),
            )
        )
        metrics["mode"] = "learned"
        return metrics

    def save(self) -> None:
        self.model.save(self.checkpoint)


def build_graph_policy(
    mode: str,
    *,
    output: Path,
    learning: Mapping[str, object],
    sampling: Mapping[str, object],
) -> GraphSelectionPolicy:
    if mode == "prior":
        return PriorOnlyGraphPolicy()
    if mode == "learned":
        return LearnedGraphPolicy(output / "model.pt", learning, sampling)
    raise ValueError(f"Unknown graph policy mode {mode!r}")
