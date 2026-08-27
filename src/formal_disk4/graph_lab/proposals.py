from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import AbstractSet, Callable, Protocol, Sequence

from .evaluator import GraphEvaluation
from .isomorphism import IsomorphismIndex
from .space import DualGraphCandidate, GraphSpace


def _diversity_cell(candidate: DualGraphCandidate, stage: int) -> str:
    maximum_edges = max(1, 3 * (candidate.tile_count + 1) - 6)
    density_bin = min(4, int(5 * candidate.edge_count / maximum_edges))
    symmetry = candidate.symmetry_order
    symmetry_bin = "none" if symmetry <= 1 else ("high" if symmetry >= 4 else "low")
    return f"n{candidate.tile_count}:sym-{symmetry_bin}:density-{density_bin}:stage-{stage}"


class DiversityArchive:
    """Bounded archive used for novelty estimates and mutation parents."""

    def __init__(self, observations: Sequence[GraphEvaluation]) -> None:
        self.cells: dict[str, list[GraphEvaluation]] = defaultdict(list)
        for observation in observations:
            self.add(observation)

    @staticmethod
    def reward(observation: GraphEvaluation) -> float:
        return (
            float(observation.stage_index)
            + 4.0 * len(observation.profiles)
            - 0.08 * math.log1p(observation.elapsed_seconds)
            - (1.0 if observation.tainted else 0.0)
        )

    def add(self, observation: GraphEvaluation) -> None:
        cell = _diversity_cell(observation.candidate, observation.stage_index)
        values = self.cells[cell]
        values[:] = [
            item
            for item in values
            if item.candidate.graph_id != observation.candidate.graph_id
        ]
        values.append(observation)
        values.sort(key=lambda item: (-self.reward(item), item.candidate.graph_id))
        del values[8:]

    def novelty(self, candidate: DualGraphCandidate) -> float:
        prefix = _diversity_cell(candidate, 0).rsplit(":stage-", 1)[0]
        amount = sum(
            len(values) for cell, values in self.cells.items() if cell.startswith(prefix)
        )
        return 1.0 / math.sqrt(1.0 + amount)

    def choose_parent(
        self,
        rng: random.Random,
        *,
        size_weight: Callable[[int], float] | None = None,
        allowed_tile_counts: AbstractSet[int] | None = None,
    ) -> GraphEvaluation | None:
        nonempty = []
        for values in self.cells.values():
            eligible = [
                item
                for item in values
                if allowed_tile_counts is None
                or item.candidate.tile_count in allowed_tile_counts
            ]
            if eligible:
                nonempty.append(eligible)
        if not nonempty:
            return None
        weight_for = size_weight or (lambda _tile_count: 1.0)
        if rng.random() < 0.75:
            values = rng.choices(
                nonempty,
                weights=[
                    max(1e-12, float(weight_for(items[0].candidate.tile_count)))
                    for items in nonempty
                ],
                k=1,
            )[0]
            weights = [max(0.1, self.reward(item) + 1.0) for item in values]
            return rng.choices(values, weights=weights, k=1)[0]
        all_values = [item for values in nonempty for item in values]
        weights = [
            max(0.1, self.reward(item) + 1.0)
            * max(1e-12, float(weight_for(item.candidate.tile_count)))
            for item in all_values
        ]
        return rng.choices(all_values, weights=weights, k=1)[0]


class GraphProposalSource(Protocol):
    """Strategy boundary for producing candidate graph pools."""

    def pool(
        self,
        rng: random.Random,
        archive: DiversityArchive,
        target: int,
    ) -> list[DualGraphCandidate]: ...


class StochasticGraphProposalSource:
    """Current prior/mutation graph proposal strategy."""

    def __init__(
        self,
        space: GraphSpace,
        *,
        mutation_fraction: float,
        exclude_rings: bool,
    ) -> None:
        self.space = space
        self.mutation_fraction = min(1.0, max(0.0, float(mutation_fraction)))
        self.exclude_rings = bool(exclude_rings)

    def pool(
        self,
        rng: random.Random,
        archive: DiversityArchive,
        target: int,
    ) -> list[DualGraphCandidate]:
        candidates: list[DualGraphCandidate] = []
        local = IsomorphismIndex()
        attempts = 0
        while len(candidates) < target and attempts < target * 200:
            attempts += 1
            parent = (
                archive.choose_parent(
                    rng,
                    size_weight=self.space.size_sampling_weight,
                    allowed_tile_counts=self.space.allowed_tile_counts,
                )
                if rng.random() < self.mutation_fraction
                else None
            )
            if parent is not None and not self.space.allows_candidate(parent.candidate):
                parent = None
            candidate = (
                self.space.mutate(parent.candidate, rng)
                if parent is not None
                else self.space.sample_prior(rng)
            )
            if candidate is None or (self.exclude_rings and candidate.is_simple_ring):
                continue
            if local.add(candidate):
                candidates.append(candidate)
        if len(candidates) < target:
            raise RuntimeError(
                "Graph generator produced only "
                f"{len(candidates)} novel candidates for a pool of {target}"
            )
        return candidates
