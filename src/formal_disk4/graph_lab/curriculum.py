from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Sequence

from formal_disk4.pipeline.filter_report import LEARNING_FILTER_IDS


@dataclass(frozen=True)
class CurriculumState:
    """The currently learnable local objective of one Graph Lab policy.

    ``reach`` and ``conditional pass`` deliberately remain separate.  Filters
    in ``LEARNING_FILTER_IDS`` are instrumentation points, not a single chain:
    multiplying their probabilities would therefore have no probabilistic
    meaning.  The policy instead optimises one directly supervised reach
    probability and uses the other heads only as bounded auxiliary signals.
    """

    frontier_index: int | None
    status: str
    reach_weights: tuple[float, ...]
    pass_weights: tuple[float, ...]

    @property
    def frontier_id(self) -> str | None:
        return (
            LEARNING_FILTER_IDS[self.frontier_index]
            if self.frontier_index is not None
            else None
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "frontier_index": self.frontier_index,
            "frontier_filter": self.frontier_id,
            "status": self.status,
            "reach_weights": {
                filter_id: self.reach_weights[index]
                for index, filter_id in enumerate(LEARNING_FILTER_IDS)
                if self.reach_weights[index]
            },
            "conditional_pass_weights": {
                filter_id: self.pass_weights[index]
                for index, filter_id in enumerate(LEARNING_FILTER_IDS)
                if self.pass_weights[index]
            },
            "probability_semantics": (
                "Direct P(filter entered) objectives; conditional pass heads "
                "are auxiliary and probabilities of different filters are "
                "never multiplied."
            ),
        }


def build_curriculum(
    *,
    empirical_reach_rates: Sequence[float],
    reach_supports: Sequence[int],
    active_reach_heads: Sequence[bool],
    active_pass_heads: Sequence[bool],
    config: Mapping[str, object],
) -> CurriculumState:
    count = len(LEARNING_FILTER_IDS)
    minimum_support = max(1, int(config.get("curriculum_minimum_support", 64)))
    mastery = min(
        0.999, max(0.5, float(config.get("curriculum_mastery_rate", 0.85)))
    )
    learnable = [
        index
        for index in range(count)
        if int(reach_supports[index]) >= minimum_support
        and bool(active_reach_heads[index])
    ]
    frontier = next(
        (
            index
            for index in learnable
            if float(empirical_reach_rates[index]) < mastery
        ),
        (learnable[-1] if learnable else None),
    )
    reach_weights = [0.0] * count
    pass_weights = [0.0] * count
    if frontier is None:
        supported = [
            index
            for index in range(count)
            if int(reach_supports[index]) >= minimum_support
        ]
        status = "waiting_for_contrast" if supported else "waiting_for_support"
        return CurriculumState(None, status, tuple(reach_weights), tuple(pass_weights))

    reach_weights[frontier] = float(config.get("curriculum_frontier_weight", 1.0))
    shallow_weight = max(0.0, float(config.get("curriculum_shallow_weight", 0.15)))
    deep_weight = max(0.0, float(config.get("curriculum_deep_weight", 0.10)))
    decay = min(1.0, max(0.0, float(config.get("curriculum_depth_decay", 0.70))))
    for index in learnable:
        if index < frontier:
            reach_weights[index] = shallow_weight * decay ** (frontier - index - 1)
        elif index > frontier:
            reach_weights[index] = deep_weight * decay ** (index - frontier - 1)
    if bool(active_pass_heads[frontier]):
        pass_weights[frontier] = max(
            0.0, float(config.get("curriculum_local_pass_weight", 0.20))
        )
    return CurriculumState(frontier, "active", tuple(reach_weights), tuple(pass_weights))


def curriculum_utility(
    state: CurriculumState,
    reach_probabilities: Sequence[float],
    conditional_probabilities: Sequence[float],
) -> float:
    """A bounded additive policy score with explicit probability semantics."""

    return sum(
        weight * float(reach_probabilities[index])
        for index, weight in enumerate(state.reach_weights)
    ) + sum(
        weight * float(conditional_probabilities[index])
        for index, weight in enumerate(state.pass_weights)
    )


def normalized_cost(seconds: float, config: Mapping[str, object]) -> float:
    """Map a predicted wall time to [0, 1] before mixing it with probabilities."""

    reference = max(1e-6, float(config.get("cost_reference_seconds", 30.0)))
    return min(1.0, max(0.0, math.log1p(seconds) / math.log1p(reference)))
