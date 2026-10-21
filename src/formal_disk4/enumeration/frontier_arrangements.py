from __future__ import annotations

"""Tile-frontier backtracking for contour arrangements.

Unlike the historical ``assignment -> weak order`` Cartesian traversal, this
search adds one graph tile at a time.  Adding a tile chooses its direct or
reflected cyclic contour mapping and merges all of its marked occurrences into
the weak cyclic order already built by the neighbouring tiles.  Exact partial
length and angle contradictions are checked after every tile insertion.

The validation hook is deliberately independent from the traversal.  A later
word-prefix or partial-geometry oracle can therefore reject a partial state
without changing how the search tree is constructed.
"""

from dataclasses import dataclass
from typing import Callable, Iterator, Protocol, Sequence

from .cyclic_arrangements import (
    ArrangementSearchStatistics,
    CyclicArrangementEnumerator,
)
from .weak_orders import Placement


@dataclass(frozen=True)
class PartialArrangementState:
    """Immutable public view of one tile-frontier search node."""

    blocks: tuple[tuple[int, ...], ...]
    positions: tuple[int, ...]
    selected_sequences: tuple[tuple[int, ...] | None, ...]
    placed_piece_indices: tuple[int, ...]
    remaining_piece_indices: tuple[int, ...]
    last_piece_index: int

    @property
    def complete(self) -> bool:
        return not self.remaining_piece_indices


@dataclass(frozen=True)
class PartialValidationResult:
    feasible: bool
    reason: str = ""
    certified: bool = True


class PartialArrangementValidator(Protocol):
    """Optional, conservative extension test for a partial arrangement.

    Returning ``feasible=False`` removes the whole descendant subtree.  Set
    ``certified=True`` only for a proof of non-extendability.  A bounded
    numerical or heuristic rejection may use ``certified=False``; the search
    then records that its exhaustion is tainted and cannot certify absence.
    """

    def __call__(
        self, state: PartialArrangementState
    ) -> PartialValidationResult | bool: ...


PieceSelector = Callable[
    [tuple[int, ...], tuple[int, ...], tuple[tuple[int, ...], ...]], int
]


class FrontierArrangementEnumerator(CyclicArrangementEnumerator):
    """Complete tile-by-tile arrangement search for an unconstrained graph.

    Completeness here is relative to the same formal model as
    :class:`CyclicArrangementEnumerator`: every direct/reflected cyclic mapping
    and every weak cyclic merge remains reachable unless a supplied exact
    validator rejects it or a caller budget stops the traversal.

    Imposed graph automorphisms are intentionally not accepted yet.  Searching
    tile orbits rather than individual tiles requires a separate, exact merge
    operation; silently falling back to the old traversal would make the
    selected strategy misleading.
    """

    def __init__(
        self,
        *args: object,
        partial_validators: Sequence[PartialArrangementValidator] = (),
        piece_selector: PieceSelector | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)
        if self.active_transform is not None or self.required_reflections:
            raise ValueError(
                "Tile-frontier arrangement search does not yet support an "
                "imposed graph automorphism; use the symmetry-aware joint "
                "contour search for that domain"
            )
        self.partial_validators = tuple(partial_validators)
        self.piece_selector = piece_selector
        self._piece_neighbors = self._build_piece_neighbors()
        self._frontier_nodes = 0
        self._frontier_candidates = 0
        self._partial_validator_rejections = 0
        self._heuristic_partial_rejections = 0

    def _build_piece_neighbors(self) -> tuple[tuple[int, ...], ...]:
        piece_index = self.assignment_enumerator.piece_index
        neighbors = [set() for _piece in self.piece_names]
        for interface in self.planar_map.internal_interfaces():
            if interface.right_piece is None:
                continue
            left = piece_index[interface.left_piece]
            right = piece_index[interface.right_piece]
            neighbors[left].add(right)
            neighbors[right].add(left)
        return tuple(tuple(sorted(items)) for items in neighbors)

    def _select_next_piece(
        self,
        placed: tuple[int, ...],
        remaining: tuple[int, ...],
    ) -> int:
        if self.piece_selector is not None:
            selected = int(
                self.piece_selector(placed, remaining, self._piece_neighbors)
            )
            if selected not in remaining:
                raise ValueError("Piece selector returned a tile outside the frontier")
            return selected
        placed_set = set(placed)
        # First close as many already exposed interfaces as possible.  Degree
        # and contour-occurrence count only break ties; they do not prune.
        return max(
            remaining,
            key=lambda piece: (
                sum(neighbor in placed_set for neighbor in self._piece_neighbors[piece]),
                len(self._piece_neighbors[piece]),
                len(self.base_sequences[piece]),
                -piece,
            ),
        )

    def _merge_piece_sequence(
        self,
        blocks: tuple[tuple[int, ...], ...],
        sequence: tuple[int, ...],
    ) -> Iterator[tuple[tuple[int, ...], ...]]:
        """Enumerate weak cyclic merges while retaining the reference cut.

        Existing blocks and the new tile sequence each retain their order.  A
        diagonal step puts one new occurrence in an existing block (a weak
        equality); horizontal/vertical steps retain or create a strict gap.
        No new-only step is allowed before block zero because that block owns
        the fixed global contour cut.  The same cyclic placement is represented
        after the final existing block instead.
        """

        existing_count = len(blocks)
        occurrence_count = len(sequence)

        def visit(
            existing_index: int,
            occurrence_index: int,
            output: tuple[tuple[int, ...], ...],
        ) -> Iterator[tuple[tuple[int, ...], ...]]:
            if self._should_stop():
                return
            if (
                existing_index == existing_count
                and occurrence_index == occurrence_count
            ):
                yield output
                return

            # Prefer a coincidence because it tends to resolve graph
            # interfaces sooner.  This is branch ordering only.
            if (
                existing_index < existing_count
                and occurrence_index < occurrence_count
            ):
                merged = tuple(
                    sorted(blocks[existing_index] + (sequence[occurrence_index],))
                )
                yield from visit(
                    existing_index + 1,
                    occurrence_index + 1,
                    output + (merged,),
                )
            if existing_index < existing_count:
                yield from visit(
                    existing_index + 1,
                    occurrence_index,
                    output + (blocks[existing_index],),
                )
            if occurrence_index < occurrence_count and existing_index > 0:
                yield from visit(
                    existing_index,
                    occurrence_index + 1,
                    output + ((sequence[occurrence_index],),),
                )

        yield from visit(0, 0, ())

    def _state(
        self,
        blocks: tuple[tuple[int, ...], ...],
        selected_sequences: tuple[tuple[int, ...] | None, ...],
        placed: tuple[int, ...],
        remaining: tuple[int, ...],
        last_piece: int,
    ) -> PartialArrangementState:
        return PartialArrangementState(
            blocks=blocks,
            positions=self._positions(blocks),
            selected_sequences=selected_sequences,
            placed_piece_indices=placed,
            remaining_piece_indices=remaining,
            last_piece_index=last_piece,
        )

    def _external_validators_allow(self, state: PartialArrangementState) -> bool:
        for validator in self.partial_validators:
            result = validator(state)
            feasible = result if isinstance(result, bool) else result.feasible
            if not feasible:
                self._partial_validator_rejections += 1
                self.event_sink("frontier_partial_validator_rejections", 1)
                if not isinstance(result, bool) and not result.certified:
                    self._heuristic_partial_rejections += 1
                    self.event_sink("frontier_heuristic_partial_rejections", 1)
                return False
        return True

    def _search_frontier(
        self,
        blocks: tuple[tuple[int, ...], ...],
        selected_sequences: tuple[tuple[int, ...] | None, ...],
        placed: tuple[int, ...],
        remaining: tuple[int, ...],
    ) -> Iterator[Placement]:
        if self._should_stop():
            return
        self._nodes += 1
        self._frontier_nodes += 1
        self.event_sink("arrangement_nodes", 1)
        self.event_sink("frontier_tile_nodes", 1)

        if not remaining:
            domains = tuple((sequence,) for sequence in selected_sequences if sequence)
            if len(domains) != len(self.piece_names):
                raise RuntimeError("Complete frontier state has an unassigned tile")
            placement = self._complete_placement(blocks, domains)
            if placement is not None:
                yield placement
            return

        piece = self._select_next_piece(placed, remaining)
        next_remaining = tuple(item for item in remaining if item != piece)
        for sequence in self.sequence_domains[piece]:
            for next_blocks in self._merge_piece_sequence(blocks, sequence):
                if self._should_stop():
                    return
                self._candidate_blocks += 1
                self._frontier_candidates += 1
                self.event_sink("arrangement_candidate_blocks", 1)
                self.event_sink("frontier_tile_candidates", 1)
                next_selected_list = list(selected_sequences)
                next_selected_list[piece] = tuple(sequence)
                next_selected = tuple(next_selected_list)
                domains = tuple(
                    (selected,) if selected is not None else self.sequence_domains[index]
                    for index, selected in enumerate(next_selected)
                )
                if not self._constraints_allow(next_blocks, domains):
                    continue
                next_placed = placed + (piece,)
                state = self._state(
                    next_blocks,
                    next_selected,
                    next_placed,
                    next_remaining,
                    piece,
                )
                if not self._external_validators_allow(state):
                    continue
                yield from self._search_frontier(
                    next_blocks,
                    next_selected,
                    next_placed,
                    next_remaining,
                )

    def enumerate(self) -> Iterator[Placement]:
        reference = self.reference_index
        reference_sequence = self.sequence_domains[reference][0]
        blocks = tuple((occurrence_id,) for occurrence_id in reference_sequence)
        selected: list[tuple[int, ...] | None] = [None] * len(self.piece_names)
        selected[reference] = reference_sequence
        remaining = tuple(
            piece for piece in range(len(self.piece_names)) if piece != reference
        )
        domains = tuple(
            (reference_sequence,)
            if piece == reference
            else self.sequence_domains[piece]
            for piece in range(len(self.piece_names))
        )
        if not self._constraints_allow(blocks, domains):
            return
        initial = self._state(
            blocks,
            tuple(selected),
            (reference,),
            remaining,
            reference,
        )
        if not self._external_validators_allow(initial):
            return
        yield from self._search_frontier(
            blocks,
            tuple(selected),
            (reference,),
            remaining,
        )

    @property
    def statistics(self) -> ArrangementSearchStatistics:
        return super().statistics

    @property
    def heuristic_pruning_used(self) -> bool:
        """Whether an uncertified validator removed at least one subtree."""

        return self._heuristic_partial_rejections > 0
