from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from formal_disk4.geometry.status import (
    SOLUTION_FOUND,
    GeometryCandidateStatus,
    read_geometry_status_records,
)

from .space import DualGraphCandidate


VALUE_TARGET_IDS = (
    "profile_emitted",
    "geometry_solution",
    "nontrivial_geometry_solution",
)


def balanced_binary_weights(
    targets: Sequence[Sequence[float | None]],
    width: int,
    *,
    maximum: float = 50.0,
) -> tuple[tuple[float, float], ...]:
    """Return bounded positive/negative BCE weights for sparse Lab labels."""

    output = []
    for head in range(int(width)):
        labels = [row[head] for row in targets if row[head] is not None]
        positive = sum(float(value) for value in labels)
        negative = len(labels) - positive
        total = positive + negative
        positive_weight = total / (2.0 * positive) if positive else 1.0
        negative_weight = total / (2.0 * negative) if negative else 1.0
        output.append(
            (
                min(float(maximum), positive_weight),
                min(float(maximum), negative_weight),
            )
        )
    return tuple(output)


def formal_profile_ids(
    profiles: Sequence[Mapping[str, object]],
) -> tuple[str, ...]:
    return tuple(
        str(profile["formal_profile_id"])
        for profile in profiles
        if profile.get("formal_profile_id")
    )


def is_ring_candidate(candidate: DualGraphCandidate) -> bool:
    """Conservatively recognize an outside star plus one simple tile cycle."""

    tile_count = candidate.tile_count
    if tile_count < 3 or len(candidate.edges) != 2 * tile_count:
        return False
    edges = {tuple(sorted((int(left), int(right)))) for left, right in candidate.edges}
    if len(edges) != len(candidate.edges):
        return False
    tiles = set(range(tile_count))
    outside = {(-1, tile) for tile in tiles}
    if not outside.issubset(edges):
        return False
    internal = edges - outside
    if len(internal) != tile_count:
        return False
    adjacency = {tile: set() for tile in tiles}
    for left, right in internal:
        if left not in tiles or right not in tiles:
            return False
        adjacency[left].add(right)
        adjacency[right].add(left)
    if any(len(neighbours) != 2 for neighbours in adjacency.values()):
        return False
    seen = {0}
    pending = [0]
    while pending:
        current = pending.pop()
        for neighbour in adjacency[current]:
            if neighbour not in seen:
                seen.add(neighbour)
                pending.append(neighbour)
    return seen == tiles


@dataclass(frozen=True)
class LearningFeedback:
    """Asynchronous geometry labels joined back to formal Lab observations."""

    profile_statuses: Mapping[str, GeometryCandidateStatus]
    graph_profiles: Mapping[str, tuple[tuple[str, bool], ...]]

    @classmethod
    def empty(cls) -> "LearningFeedback":
        return cls({}, {})

    def targets(
        self,
        *,
        candidate: DualGraphCandidate,
        profile_count: int,
        profile_ids: Sequence[str] = (),
        allow_graph_fallback: bool = False,
    ) -> tuple[float | None, ...]:
        emitted = float(profile_count > 0)
        identifiers = tuple(str(value) for value in profile_ids if value)
        if not identifiers and allow_graph_fallback:
            graph_values = self.graph_profiles.get(candidate.graph_id, ())
            identifiers = tuple(profile_id for profile_id, _is_ring in graph_values)
        if not profile_count and not identifiers:
            solution: float | None = 0.0
        elif not identifiers:
            # Old observations retained only a count. They remain useful for the
            # immediate formal target but must not invent a geometry label.
            solution = None
        else:
            known = [
                self.profile_statuses[profile_id]
                for profile_id in identifiers
                if profile_id in self.profile_statuses
            ]
            if any(item.status == SOLUTION_FOUND for item in known):
                solution = 1.0
            elif len(known) == len(identifiers):
                solution = 0.0
            else:
                solution = None
        nontrivial = (
            0.0 if is_ring_candidate(candidate) else solution
        )
        return (emitted, solution, nontrivial)


def read_learning_feedback(output: Path) -> LearningFeedback:
    geometry = output / "geometry"
    statuses = read_geometry_status_records(geometry / "geometry_status.sqlite3")
    catalog_path = geometry / "geometry_candidate_catalog.sqlite3"
    graph_profiles: dict[str, list[tuple[str, bool]]] = {}
    if catalog_path.exists():
        try:
            connection = sqlite3.connect(str(catalog_path), timeout=1.0)
            try:
                rows = connection.execute(
                    "SELECT formal_profile_id, graph_id, is_pizza "
                    "FROM geometry_candidate_catalog WHERE graph_id IS NOT NULL"
                ).fetchall()
            finally:
                connection.close()
            for profile_id, graph_id, is_pizza in rows:
                graph_profiles.setdefault(str(graph_id), []).append(
                    (str(profile_id), bool(is_pizza))
                )
        except (sqlite3.Error, OSError, ValueError):
            pass
    return LearningFeedback(
        statuses,
        {name: tuple(values) for name, values in graph_profiles.items()},
    )
