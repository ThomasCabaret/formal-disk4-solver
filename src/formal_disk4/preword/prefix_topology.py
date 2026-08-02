from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Sequence, Tuple

from formal_disk4.enumeration.assignments import ContourAssignment
from formal_disk4.maps.base import InterfaceSpec, Occurrence, PlanarMap
from formal_disk4.words.algebra import Equation, Literal, Word, inverse_word
from formal_disk4.words.compile import (
    CompiledInterface,
    CompiledOuterArc,
    CompiledWordCase,
    cyclic_factor,
)

from .arc_topology import RadiusArcTopologyFilter, RadiusArcTopologyResult


@dataclass(frozen=True)
class PrefixTopologyResult:
    applicable: bool
    feasible: bool
    reason: str
    stable_interfaces: int
    stable_outer_arcs: int
    topology: RadiusArcTopologyResult | None = None
    cache_hit: bool = False


class PrefixRadiusArcTopologyFilter:
    """Conservative same-radius topology checks on weak-order prefixes.

    A weak-order prefix fixes a linear part of the cyclic prototype contour;
    later DFS blocks are inserted only across the still-open frontier between
    the last current block and block zero.  This filter compiles only piece
    paths that do not cross that frontier.  Therefore every path, equality and
    hard boundary used here is unchanged by all descendants of the prefix.

    Unresolved paths are omitted.  Consequently this can lose pruning
    opportunities but cannot reject a descendant that the complete topology
    filter would accept.
    """

    def __init__(
        self,
        planar_map: PlanarMap,
        assignment: ContourAssignment,
        *,
        tolerance: float = 1e-9,
        enable_endpoint_crossing: bool = True,
        max_intervals: int = 1024,
    ) -> None:
        self.planar_map = planar_map
        self.assignment = assignment
        self.occurrences = planar_map.occurrences()
        self.occurrence_index = {
            occurrence: index for index, occurrence in enumerate(self.occurrences)
        }
        self.piece_index = {
            piece: index for index, piece in enumerate(assignment.piece_names)
        }
        self.topology_filter = RadiusArcTopologyFilter(
            tolerance=tolerance,
            enable_endpoint_crossing=enable_endpoint_crossing,
            max_intervals=max_intervals,
        )
        self.internal_interfaces = planar_map.internal_interfaces()
        self.outer_interfaces = planar_map.outer_interfaces()
        hard_vertices = {
            vertex.name
            for vertex in planar_map.vertices
            if vertex.kind == "outer" and len(vertex.incident_pieces) >= 2
        }
        self._cache: Dict[tuple[object, ...], PrefixTopologyResult] = {}
        self.hard_outer_occurrences = tuple(
            self.occurrence_index[occurrence]
            for interface in self.outer_interfaces
            for view in interface.views
            for occurrence in (view.start_occurrence, view.end_occurrence)
            if occurrence.vertex in hard_vertices
        )

    def _stable_positive_word(
        self,
        interface: InterfaceSpec,
        view_index: int,
        positions: Sequence[int],
        contour: Word,
        *,
        complete: bool = False,
    ) -> Word | None:
        view = interface.views[view_index]
        start_id = self.occurrence_index[view.start_occurrence]
        end_id = self.occurrence_index[view.end_occurrence]
        start = positions[start_id]
        end = positions[end_id]
        if start < 0 or end < 0 or start == end:
            return None
        direction = self.assignment.orientation_signs[self.piece_index[view.piece]]
        # Future blocks are inserted only across the open last->zero frontier.
        # A path that crosses it is not stable yet and is conservatively omitted.
        crosses_open_frontier = (
            (direction == 1 and start >= end)
            or (direction == -1 and start <= end)
        )
        if crosses_open_frontier and not complete:
            return None
        word = cyclic_factor(contour, start, end, direction)
        return word or None

    @staticmethod
    def _length_row(left: Word, right: Word, width: int) -> Tuple[int, ...]:
        row = [0] * width
        for literal in left:
            row[int(literal.variable[1:])] += 1
        for literal in right:
            row[int(literal.variable[1:])] -= 1
        return tuple(row)

    @staticmethod
    def _word_key(word: Word) -> Tuple[int, ...]:
        return tuple(
            -(int(literal.variable[1:]) + 1)
            if literal.inverse
            else int(literal.variable[1:]) + 1
            for literal in word
        )

    def analyze(
        self,
        positions: Sequence[int],
        block_count: int,
        *,
        complete: bool = False,
    ) -> PrefixTopologyResult:
        if block_count <= 1:
            return PrefixTopologyResult(False, True, "insufficient prefix", 0, 0)
        atomic_variables = tuple(f"X{index}" for index in range(block_count))
        contour = tuple(Literal(name) for name in atomic_variables)
        compiled_interfaces = []
        length_rows = []
        interface_key = []
        for interface in self.internal_interfaces:
            left = self._stable_positive_word(
                interface, 0, positions, contour, complete=complete
            )
            right = self._stable_positive_word(
                interface, 1, positions, contour, complete=complete
            )
            if left is None or right is None:
                continue
            left_view, right_view = interface.views
            left_sign = self.assignment.orientation_signs[
                self.piece_index[left_view.piece]
            ]
            right_sign = self.assignment.orientation_signs[
                self.piece_index[right_view.piece]
            ]
            compiled_interfaces.append(
                CompiledInterface(
                    name=interface.name,
                    left_piece=left_view.piece,
                    right_piece=right_view.piece,
                    left_positive_word=left,
                    right_positive_word=right,
                    equation=Equation(left, inverse_word(right)),
                    relative_parity=left_sign * right_sign,
                )
            )
            length_rows.append(self._length_row(left, right, block_count))
            interface_key.append(
                (interface.name, self._word_key(left), self._word_key(right))
            )

        compiled_outer_arcs = []
        outer_key = []
        for interface in self.outer_interfaces:
            word = self._stable_positive_word(
                interface, 0, positions, contour, complete=complete
            )
            if word is None:
                continue
            view = interface.views[0]
            compiled_outer_arcs.append(
                CompiledOuterArc(interface.name, view.piece, word)
            )
            outer_key.append((interface.name, self._word_key(word)))

        hard_boundaries = tuple(
            sorted(
                {
                    positions[occurrence_id]
                    for occurrence_id in self.hard_outer_occurrences
                    if positions[occurrence_id] >= 0
                }
            )
        )
        key = (tuple(interface_key), tuple(outer_key), hard_boundaries)
        cached = self._cache.get(key)
        if cached is not None:
            return PrefixTopologyResult(
                cached.applicable,
                cached.feasible,
                cached.reason,
                cached.stable_interfaces,
                cached.stable_outer_arcs,
                cached.topology,
                True,
            )

        if not compiled_outer_arcs or not compiled_interfaces:
            result = PrefixTopologyResult(
                False,
                True,
                "no stable propagation system",
                len(compiled_interfaces),
                len(compiled_outer_arcs),
            )
            self._cache[key] = result
            return result

        compiled = CompiledWordCase(
            atomic_variables=atomic_variables,
            contour_word=contour,
            equations=tuple(item.equation for item in compiled_interfaces),
            interfaces=tuple(compiled_interfaces),
            outer_arcs=tuple(compiled_outer_arcs),
        )
        topology = self.topology_filter.analyze_compiled(
            self.planar_map,
            tuple(length_rows),
            compiled,
            additional_hard_outer_boundaries=hard_boundaries,
        )
        result = PrefixTopologyResult(
            True,
            topology.feasible,
            topology.reason,
            len(compiled_interfaces),
            len(compiled_outer_arcs),
            topology,
        )
        self._cache[key] = result
        return result

