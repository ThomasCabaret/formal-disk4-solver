from __future__ import annotations

from collections import defaultdict
from typing import Mapping

import networkx as nx

from .space import DualGraphCandidate, OUTSIDE


def _wl_bucket(candidate: DualGraphCandidate) -> str:
    graph = candidate.graph()
    nx.set_node_attributes(
        graph,
        {node: "outside" if node == OUTSIDE else "tile" for node in graph},
        "kind",
    )
    digest = nx.weisfeiler_lehman_graph_hash(graph, node_attr="kind")
    return f"{candidate.tile_count}:{candidate.symmetry_order}:{digest}"


def _conjugates_imposed_symmetry(
    left: DualGraphCandidate,
    right: DualGraphCandidate,
    mapping: Mapping[int, int],
) -> bool:
    if (left.imposed_permutation is None) != (right.imposed_permutation is None):
        return False
    if left.imposed_permutation is None:
        return True
    assert right.imposed_permutation is not None
    return all(
        mapping[left.imposed_permutation[node]]
        == right.imposed_permutation[mapping[node]]
        for node in range(left.tile_count)
    )


class IsomorphismIndex:
    """Exact graph/symmetry classes, with WL used only as a lookup bucket."""

    def __init__(self) -> None:
        self.buckets: dict[str, list[DualGraphCandidate]] = defaultdict(list)

    def equivalent(self, candidate: DualGraphCandidate) -> DualGraphCandidate | None:
        graph = candidate.graph()
        nx.set_node_attributes(
            graph, {node: node == OUTSIDE for node in graph}, "outside"
        )
        for existing in self.buckets.get(_wl_bucket(candidate), ()):
            matcher = nx.algorithms.isomorphism.GraphMatcher(
                graph,
                existing.graph(),
                node_match=lambda left, right: bool(left.get("outside"))
                == bool(right.get("outside")),
            )
            for mapping in matcher.isomorphisms_iter():
                if _conjugates_imposed_symmetry(candidate, existing, mapping):
                    return existing
        return None

    def add(self, candidate: DualGraphCandidate) -> bool:
        if self.equivalent(candidate) is not None:
            return False
        self.buckets[_wl_bucket(candidate)].append(candidate)
        return True

    def __len__(self) -> int:
        return sum(len(values) for values in self.buckets.values())
