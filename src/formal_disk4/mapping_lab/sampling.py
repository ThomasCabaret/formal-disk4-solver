from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from .backend import LearningBackend
from .core import MappingCandidate, MappingSpace
from .seeds import DeepSeedBuffer


@dataclass(frozen=True)
class SamplingSettings:
    uniform_fraction: float = 0.2
    pool_multiplier: int = 3
    pool_exploration_fraction: float = 0.15
    pool_local_fraction: float = 0.35
    pool_broad_fraction: float = 0.35
    broad_mutation_prefix_fraction: float = 0.6
    max_attempts_per_candidate: int = 2000


class ProposalSampler:
    """Generate complete mappings, then let a backend rank a bounded pool."""

    def __init__(self, space: MappingSpace, settings: SamplingSettings) -> None:
        self.space = space
        self.settings = settings
        self.last_diagnostics: dict[str, int] = {}

    def sample_batch(
        self,
        backend: LearningBackend,
        rng: random.Random,
        batch_size: int,
        seen: Mapping[str, set[str]],
        *,
        seeds: DeepSeedBuffer,
    ) -> list[MappingCandidate]:
        diagnostics: Counter[str] = Counter()
        uniform_count = int(round(batch_size * self.settings.uniform_fraction))
        if self.settings.uniform_fraction > 0 and batch_size > 1:
            uniform_count = max(1, min(batch_size - 1, uniform_count))
        learned_count = batch_size - uniform_count

        controls: list[MappingCandidate] = []
        for _ in range(uniform_count):
            controls.append(
                self._novel_candidate(
                    rng,
                    seen["uniform"],
                    diagnostics,
                    source="uniform",
                    strategy="uniform_control",
                )
            )

        deepest = ()
        if seeds.deepest_stage_index is not None:
            deepest = tuple(
                entry
                for entry in seeds.entries
                if entry.stage_index == seeds.deepest_stage_index
            )
        pool_target = max(learned_count, learned_count * self.settings.pool_multiplier)
        pool: list[MappingCandidate] = []
        pool_ids: set[str] = set()
        maximum_attempts = max(1, pool_target * self.settings.max_attempts_per_candidate)
        for _ in range(maximum_attempts):
            if len(pool) >= pool_target:
                break
            selector = rng.random()
            reference_masks: Sequence[int] | None = None
            if deepest and selector < self.settings.pool_local_fraction:
                strategy = "model_seed_local"
                reference_masks = rng.choice(deepest).masks
                prefix_fraction = 1.0
            elif deepest and selector < (
                self.settings.pool_local_fraction + self.settings.pool_broad_fraction
            ):
                strategy = "model_seed_broad"
                reference_masks = rng.choice(deepest).masks
                prefix_fraction = self.settings.broad_mutation_prefix_fraction
            else:
                strategy = "model_random_pool"
                prefix_fraction = 1.0
            diagnostics[f"pool_attempts.{strategy}"] += 1
            candidate = self.space.sample(
                rng,
                reference_masks=reference_masks,
                mutation_prefix_fraction=prefix_fraction,
                proposal_source="learned",
                proposal_strategy=strategy,
            )
            if candidate is None:
                diagnostics[f"pool_invalid.{strategy}"] += 1
                continue
            if candidate.candidate_id in seen["learned"] or candidate.candidate_id in pool_ids:
                diagnostics[f"pool_duplicate.{strategy}"] += 1
                continue
            pool.append(candidate)
            pool_ids.add(candidate.candidate_id)
            diagnostics[f"pool_generated.{strategy}"] += 1
        if len(pool) < learned_count:
            raise RuntimeError(
                f"proposal pool produced only {len(pool)} novel mappings; "
                f"required {learned_count}"
            )

        features = np.asarray(
            [self.space.mapping_feature_vector(candidate.masks) for candidate in pool],
            dtype=np.float32,
        )
        utilities = backend.score(features)
        ranked = list(np.argsort(-utilities, kind="stable"))
        explore_count = min(
            learned_count,
            int(round(learned_count * self.settings.pool_exploration_fraction)),
        )
        exploit_count = learned_count - explore_count
        selected_indexes = ranked[:exploit_count]
        remainder = ranked[exploit_count:]
        if explore_count:
            selected_indexes.extend(rng.sample(remainder, explore_count))
        selected = [pool[int(index)] for index in selected_indexes]
        for candidate in selected:
            seen["learned"].add(candidate.candidate_id)
            diagnostics[f"accepted.{candidate.proposal_strategy}"] += 1
        diagnostics["pool.size"] = len(pool)
        diagnostics["pool.selected_exploit"] = exploit_count
        diagnostics["pool.selected_explore"] = explore_count
        result = controls + selected
        rng.shuffle(result)
        self.last_diagnostics = dict(sorted(diagnostics.items()))
        return result

    def _novel_candidate(
        self,
        rng: random.Random,
        seen: set[str],
        diagnostics: Counter[str],
        *,
        source: str,
        strategy: str,
    ) -> MappingCandidate:
        for _ in range(self.settings.max_attempts_per_candidate):
            diagnostics[f"attempts.{strategy}"] += 1
            candidate = self.space.sample(
                rng,
                proposal_source=source,
                proposal_strategy=strategy,
            )
            if candidate is None:
                diagnostics[f"invalid.{strategy}"] += 1
                continue
            if candidate.candidate_id in seen:
                diagnostics[f"duplicate.{strategy}"] += 1
                continue
            seen.add(candidate.candidate_id)
            diagnostics[f"accepted.{strategy}"] += 1
            return candidate
        raise RuntimeError(
            f"could not sample a novel {source} mapping after "
            f"{self.settings.max_attempts_per_candidate} attempts"
        )
