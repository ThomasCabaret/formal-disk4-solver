from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Mapping, Sequence, Tuple

from formal_disk4.maps.base import Occurrence, PlanarMap


@dataclass(frozen=True)
class OrderedOuterArc:
    """One full outer map edge expressed in the prototype cyclic direction."""

    piece_index: int
    piece_name: str
    start_occurrence: int
    end_occurrence: int
    wraps_global_cut: bool


@dataclass(frozen=True)
class ExteriorArcRepetitionConstraint:
    """Incremental necessary condition for the supported K4 Stein map shape.

    The transported-exterior-arc theorem used by Kurusa--Langi--Vigh implies
    that at least two peripheral copies use exactly the same prototype boundary
    arc. For full map edges,
    equality is equivalent to equality of both endpoint blocks in the weak
    cyclic order.
    """

    applicable: bool
    reason: str
    arcs: Tuple[OrderedOuterArc, ...] = ()
    candidate_pairs: Tuple[Tuple[int, int], ...] = ()

    def surviving_pairs(self, positions: Sequence[int]) -> Tuple[Tuple[int, int], ...]:
        if not self.applicable:
            return ()
        return tuple(
            pair
            for pair in self.candidate_pairs
            if self._pair_is_still_possible(pair, positions)
        )

    def prefix_is_feasible(self, positions: Sequence[int]) -> bool:
        if not self.applicable:
            return True
        return any(
            self._pair_is_still_possible(pair, positions)
            for pair in self.candidate_pairs
        )

    def _pair_is_still_possible(
        self, pair: Tuple[int, int], positions: Sequence[int]
    ) -> bool:
        left = self.arcs[pair[0]]
        right = self.arcs[pair[1]]
        return self._endpoints_can_coincide(
            left.start_occurrence,
            right.start_occurrence,
            positions,
        ) and self._endpoints_can_coincide(
            left.end_occurrence,
            right.end_occurrence,
            positions,
        )

    @staticmethod
    def _endpoints_can_coincide(
        left_occurrence: int,
        right_occurrence: int,
        positions: Sequence[int],
    ) -> bool:
        left_position = positions[left_occurrence]
        right_position = positions[right_occurrence]
        if left_position < 0 and right_position < 0:
            return True
        # A completed weak-order block cannot receive another occurrence later.
        return left_position >= 0 and left_position == right_position


def build_exterior_arc_repetition_constraint(
    planar_map: PlanarMap,
    piece_names: Sequence[str],
    sequences: Sequence[Sequence[int]],
    occurrence_index: Mapping[Occurrence, int],
    *,
    enabled: bool,
) -> ExteriorArcRepetitionConstraint:
    """Activate only when every theorem assumption is visible in the map data.

    This deliberately conservative implementation accepts only four-piece Stein
    maps whose three peripheral pieces each own one full nondegenerate outer
    edge.  The central piece may have no outer contact, a point contact, or its
    own outer arc; only peripheral arcs participate in the repetition theorem.
    """

    if not enabled:
        return ExteriorArcRepetitionConstraint(False, "disabled")
    if len(planar_map.pieces) != 4:
        return ExteriorArcRepetitionConstraint(False, "requires_exactly_four_pieces")
    if not planar_map.hypotheses.center_strictly_inside_one_tile:
        return ExteriorArcRepetitionConstraint(
            False, "requires_stein_center_hypothesis"
        )

    reference_piece = planar_map.reference_piece
    expected_peripheral = {
        piece.name for piece in planar_map.pieces if piece.name != reference_piece
    }
    peripheral_outer_interfaces = tuple(
        interface
        for interface in planar_map.outer_interfaces()
        if interface.views[0].piece in expected_peripheral
    )
    outer_pieces = tuple(
        interface.views[0].piece for interface in peripheral_outer_interfaces
    )
    if len(peripheral_outer_interfaces) != 3 or set(outer_pieces) != expected_peripheral:
        return ExteriorArcRepetitionConstraint(
            False, "requires_one_outer_edge_per_peripheral_piece"
        )

    piece_index = {name: index for index, name in enumerate(piece_names)}
    arcs = []
    for interface in peripheral_outer_interfaces:
        view = interface.views[0]
        index = piece_index[view.piece]
        sequence = tuple(sequences[index])
        positions = {
            occurrence_id: offset
            for offset, occurrence_id in enumerate(sequence)
        }
        raw_start = occurrence_index[view.start_occurrence]
        raw_end = occurrence_index[view.end_occurrence]
        start_offset = positions[raw_start]
        end_offset = positions[raw_end]
        if (start_offset + 1) % len(sequence) == end_offset:
            start_occurrence, end_occurrence = raw_start, raw_end
        elif (end_offset + 1) % len(sequence) == start_offset:
            start_occurrence, end_occurrence = raw_end, raw_start
        else:
            return ExteriorArcRepetitionConstraint(
                False, "outer_interface_is_not_one_full_edge"
            )
        ordered_start = positions[start_occurrence]
        ordered_end = positions[end_occurrence]
        arcs.append(
            OrderedOuterArc(
                piece_index=index,
                piece_name=view.piece,
                start_occurrence=start_occurrence,
                end_occurrence=end_occurrence,
                wraps_global_cut=(
                    ordered_start == len(sequence) - 1 and ordered_end == 0
                ),
            )
        )

    # Identical prototype intervals must either both cross the chosen cut or
    # both avoid it. Endpoint-block equality is then enforced by the DFS.
    candidate_pairs = tuple(
        (left, right)
        for left, right in combinations(range(len(arcs)), 2)
        if arcs[left].wraps_global_cut == arcs[right].wraps_global_cut
    )
    return ExteriorArcRepetitionConstraint(
        applicable=True,
        reason="four_tile_stein_peripheral_arc_repetition",
        arcs=tuple(arcs),
        candidate_pairs=candidate_pairs,
    )
