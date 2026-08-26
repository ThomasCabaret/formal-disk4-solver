from __future__ import annotations

"""Joint search for contour mappings and weak cyclic orders.

The historical solver first chooses one complete oriented cyclic sequence for
every tile copy and only then interleaves those sequences into a weak cyclic
order.  That factorisation repeats the same partial arrangements across an
astronomical Cartesian product of complete mappings.

This module searches the actual combined object instead: a cyclic sequence of
blocks of prototype-contour occurrences.  The orientation and cyclic offset of
each copy are consequences of the order in which its occurrences enter those
blocks.  A pointwise imposed rotation merges every occurrence orbit into one
block; a cyclic-shift rotation constructs one fundamental domain and obtains
the other domains as exact images.
"""

from dataclasses import dataclass
from itertools import combinations
from math import lcm
from typing import Callable, Iterator, Mapping, Sequence

from formal_disk4.constraints.angle_lp import (
    AngleEquation,
    AngleFeasibilityOracle,
    AngleInequality,
)
from formal_disk4.constraints.length_lp import LengthFeasibilityOracle
from formal_disk4.maps.base import Occurrence, PlanarMap

from .assignments import AssignmentEnumerator, AssignmentTransform, ContourAssignment
from .weak_orders import Placement


EventSink = Callable[[str, int], None]
StopPredicate = Callable[[], bool]


@dataclass(frozen=True)
class ArrangementSearchStatistics:
    nodes: int
    candidate_blocks: int
    contour_order_rejections: int
    collision_rejections: int
    length_rejections: int
    angle_rejections: int
    reflection_rejections: int
    complete_arrangements: int


class CyclicArrangementEnumerator:
    """Backtrack over mapping and weak order as one cyclic arrangement.

    Every yielded :class:`Placement` is compatible with the local contour
    orders, the imposed cyclic action, positive interface lengths, and the
    local point-angle equations.  The search is complete unless its caller
    stops it through ``stop_predicate`` or ``max_nodes``.

    The search deliberately performs no learned truncation.  Heuristics only
    order branches; every branch remains reachable until an explicit node or
    wall-clock budget stops the fixed-graph traversal.
    """

    def __init__(
        self,
        planar_map: PlanarMap,
        *,
        allow_reflections: bool = True,
        required_pointwise_transform: AssignmentTransform | None = None,
        required_cyclic_shift_transform: AssignmentTransform | None = None,
        required_reflection_transforms: Sequence[AssignmentTransform] = (),
        length_oracle: LengthFeasibilityOracle | None = None,
        angle_oracle: AngleFeasibilityOracle | None = None,
        event_sink: EventSink | None = None,
        stop_predicate: StopPredicate | None = None,
        max_nodes: int | None = None,
    ) -> None:
        self.planar_map = planar_map
        self.allow_reflections = bool(allow_reflections)
        if (
            required_pointwise_transform is not None
            and required_cyclic_shift_transform is not None
        ):
            raise ValueError(
                "Pointwise and cyclic-shift arrangement actions are mutually exclusive"
            )
        self.pointwise_transform = required_pointwise_transform
        self.required_transform = required_cyclic_shift_transform
        self.active_transform = self.required_transform or self.pointwise_transform
        self.required_reflections = tuple(required_reflection_transforms)
        self.length_oracle = length_oracle or LengthFeasibilityOracle()
        self.angle_oracle = angle_oracle or AngleFeasibilityOracle()
        self.event_sink = event_sink or (lambda _name, _amount=1: None)
        self.stop_predicate = stop_predicate or (lambda: False)
        self.max_nodes = None if max_nodes is None else max(1, int(max_nodes))

        if any(not transform.reverse_cycle for transform in self.required_reflections):
            raise ValueError("Required arrangement reflections must reverse the contour")
        if self.required_reflections and self.required_transform is None:
            raise ValueError("Dihedral arrangement search needs a cyclic rotation")
        if self.pointwise_transform is not None and self.pointwise_transform.reverse_cycle:
            raise ValueError("Pointwise arrangement equivariance must preserve orientation")

        self.assignment_enumerator = AssignmentEnumerator(
            planar_map,
            allow_reflections=self.allow_reflections,
            symmetry_mode="off",
        )
        self.piece_names = self.assignment_enumerator.piece_names
        self.reference_index = self.assignment_enumerator.reference_index
        self.occurrences = self.assignment_enumerator.occurrences
        self.occurrence_names = self.assignment_enumerator.occurrence_names
        self.occurrence_index = self.assignment_enumerator.occurrence_index
        self.occurrence_piece = tuple(
            self.assignment_enumerator.piece_index[item.piece]
            for item in self.occurrences
        )
        self.base_sequences = self.assignment_enumerator.base_sequences
        self.sequence_domains = self._initial_sequence_domains()
        self.symmetry_order = (
            self._permutation_order(self.active_transform.occurrence_map)
            if self.active_transform is not None
            else 1
        )
        self.occurrence_orbits = self._occurrence_orbits()
        self.orbit_index = {
            occurrence_id: orbit_index
            for orbit_index, orbit in enumerate(self.occurrence_orbits)
            for occurrence_id in orbit
        }
        self.anchor_occurrence = self.base_sequences[self.reference_index][0]
        self.anchor_orbit = self.orbit_index[self.anchor_occurrence]
        self.interface_occurrences = self._build_interface_occurrences()
        self.vertex_occurrences = self._build_vertex_occurrences()

        self._nodes = 0
        self._candidate_blocks = 0
        self._contour_order_rejections = 0
        self._collision_rejections = 0
        self._length_rejections = 0
        self._angle_rejections = 0
        self._reflection_rejections = 0
        self._complete_arrangements = 0
        self._placement_id = 0

    @staticmethod
    def _permutation_order(permutation: Sequence[int]) -> int:
        unseen = set(range(len(permutation)))
        order = 1
        while unseen:
            seed = min(unseen)
            current = seed
            length = 0
            while current in unseen:
                unseen.remove(current)
                current = int(permutation[current])
                length += 1
            if current != seed:
                raise ValueError("Occurrence action is not a permutation")
            order = lcm(order, max(1, length))
        return order

    @staticmethod
    def _rotations(values: Sequence[int]) -> tuple[tuple[int, ...], ...]:
        base = tuple(int(item) for item in values)
        return tuple(base[offset:] + base[:offset] for offset in range(len(base)))

    def _initial_sequence_domains(self) -> tuple[tuple[tuple[int, ...], ...], ...]:
        domains = []
        for piece_index, base in enumerate(self.base_sequences):
            if piece_index == self.reference_index:
                domains.append((tuple(base),))
                continue
            options = list(self._rotations(base))
            if self.allow_reflections:
                options.extend(self._rotations(tuple(reversed(base))))
            domains.append(tuple(dict.fromkeys(options)))
        return tuple(domains)

    def _occurrence_orbits(self) -> tuple[tuple[int, ...], ...]:
        if self.active_transform is None:
            return tuple((index,) for index in range(len(self.occurrences)))
        occurrence_map = self.active_transform.occurrence_map
        unseen = set(range(len(occurrence_map)))
        output = []
        while unseen:
            seed = min(unseen)
            orbit = []
            current = seed
            while current in unseen:
                unseen.remove(current)
                orbit.append(current)
                current = occurrence_map[current]
            if current != seed or (
                self.required_transform is not None
                and len(orbit) != self.symmetry_order
            ):
                raise ValueError(
                    "Cyclic-shift arrangement search requires a free occurrence action"
                )
            output.append(tuple(orbit))
        return tuple(output)

    def _build_interface_occurrences(
        self,
    ) -> tuple[tuple[tuple[int, int], tuple[int, int]], ...]:
        output = []
        for interface in self.planar_map.internal_interfaces():
            views = tuple(
                (
                    self.occurrence_index[view.start_occurrence],
                    self.occurrence_index[view.end_occurrence],
                )
                for view in interface.views
            )
            if len(views) != 2:
                raise ValueError("Every internal interface needs two views")
            output.append((views[0], views[1]))
        return tuple(output)

    def _build_vertex_occurrences(
        self,
    ) -> tuple[tuple[str, float, tuple[int, ...]], ...]:
        output = []
        for vertex in self.planar_map.vertices:
            output.append(
                (
                    vertex.solid_angle_relation,
                    float(vertex.solid_angle_limit_pi),
                    tuple(
                        self.occurrence_index[Occurrence(piece, vertex.name)]
                        for piece in vertex.incident_pieces
                    ),
                )
            )
        return tuple(output)

    def _mapped_block(
        self, block: Sequence[int], transform: AssignmentTransform
    ) -> tuple[int, ...]:
        return tuple(sorted(transform.map_occurrence_id(item) for item in block))

    def _full_blocks(
        self, fundamental_blocks: Sequence[Sequence[int]]
    ) -> tuple[tuple[int, ...], ...]:
        if self.pointwise_transform is not None:
            return tuple(
                tuple(
                    sorted(
                        occurrence_id
                        for representative in block
                        for occurrence_id in self.occurrence_orbits[
                            self.orbit_index[representative]
                        ]
                    )
                )
                for block in fundamental_blocks
            )
        current = tuple(tuple(sorted(block)) for block in fundamental_blocks)
        output = []
        for _sector in range(self.symmetry_order):
            output.extend(current)
            if self.required_transform is not None:
                current = tuple(
                    self._mapped_block(block, self.required_transform)
                    for block in current
                )
        return tuple(output)

    def _expanded_representative(self, occurrence_id: int) -> tuple[int, ...]:
        if self.required_transform is None:
            return (int(occurrence_id),)
        output = []
        current = int(occurrence_id)
        for _sector in range(self.symmetry_order):
            output.append(current)
            current = self.required_transform.map_occurrence_id(current)
        return tuple(output)

    @staticmethod
    def _is_subsequence(
        selected: Sequence[int], complete: Sequence[int]
    ) -> bool:
        iterator = iter(complete)
        return all(any(candidate == item for candidate in iterator) for item in selected)

    def _filter_sequence_domains(
        self,
        full_blocks: Sequence[Sequence[int]],
        domains: Sequence[Sequence[Sequence[int]]],
    ) -> tuple[tuple[tuple[int, ...], ...], ...] | None:
        seen_by_piece: list[list[int]] = [[] for _piece in self.piece_names]
        for block in full_blocks:
            seen_pieces: set[int] = set()
            for occurrence_id in block:
                piece_index = self.occurrence_piece[occurrence_id]
                if piece_index in seen_pieces:
                    self._collision_rejections += 1
                    self.event_sink("arrangement_piece_collision_rejections", 1)
                    return None
                seen_pieces.add(piece_index)
                seen_by_piece[piece_index].append(occurrence_id)

        filtered = []
        for seen, options in zip(seen_by_piece, domains):
            allowed = tuple(
                tuple(option)
                for option in options
                if self._is_subsequence(seen, option)
            )
            if not allowed:
                self._contour_order_rejections += 1
                self.event_sink("arrangement_contour_order_rejections", 1)
                return None
            filtered.append(allowed)
        return tuple(filtered)

    @staticmethod
    def _arc_vector(start: int, end: int, size: int) -> tuple[int, ...]:
        if start == end:
            raise ValueError("A positive interface side has coincident endpoints")
        row = [0] * size
        current = start
        while current != end:
            row[current] = 1
            current = (current + 1) % size
        return tuple(row)

    @staticmethod
    def _directed_endpoints(
        endpoints: tuple[int, int],
        domains: Sequence[Sequence[Sequence[int]]],
        occurrence_piece: Sequence[int],
    ) -> tuple[int, int] | None:
        piece_index = occurrence_piece[endpoints[0]]
        possibilities = set()
        for sequence in domains[piece_index]:
            positions = {value: index for index, value in enumerate(sequence)}
            left, right = endpoints
            if left not in positions or right not in positions:
                continue
            if (positions[left] + 1) % len(sequence) == positions[right]:
                possibilities.add((left, right))
            elif (positions[right] + 1) % len(sequence) == positions[left]:
                possibilities.add((right, left))
            else:
                raise ValueError("Interface endpoints are not adjacent on a tile")
        return next(iter(possibilities)) if len(possibilities) == 1 else None

    def _positions(
        self, blocks: Sequence[Sequence[int]]
    ) -> tuple[int, ...]:
        output = [-1] * len(self.occurrences)
        for block_index, block in enumerate(blocks):
            for occurrence_id in block:
                if output[occurrence_id] >= 0:
                    raise RuntimeError("An occurrence was placed twice")
                output[occurrence_id] = block_index
        return tuple(output)

    def _length_rows(
        self,
        blocks: Sequence[Sequence[int]],
        domains: Sequence[Sequence[Sequence[int]]],
    ) -> tuple[tuple[int, ...], ...]:
        positions = self._positions(blocks)
        size = len(blocks)
        rows = []
        for left_view, right_view in self.interface_occurrences:
            left = self._directed_endpoints(
                left_view, domains, self.occurrence_piece
            )
            right = self._directed_endpoints(
                right_view, domains, self.occurrence_piece
            )
            if left is None or right is None:
                continue
            if any(positions[item] < 0 for item in left + right):
                continue
            left_row = self._arc_vector(
                positions[left[0]], positions[left[1]], size
            )
            right_row = self._arc_vector(
                positions[right[0]], positions[right[1]], size
            )
            rows.append(tuple(a - b for a, b in zip(left_row, right_row)))
        return tuple(rows)

    def _angle_constraints(
        self, blocks: Sequence[Sequence[int]]
    ) -> tuple[tuple[AngleEquation, ...], tuple[AngleInequality, ...]]:
        positions = self._positions(blocks)
        size = len(blocks)
        equations = []
        inequalities = []
        for relation, limit, occurrences in self.vertex_occurrences:
            if any(positions[item] < 0 for item in occurrences):
                continue
            coefficients = [0] * size
            if relation == "equal":
                for occurrence_id in occurrences:
                    coefficients[positions[occurrence_id]] += 1
                equations.append(
                    AngleEquation(
                        tuple(coefficients), float(len(occurrences) - limit)
                    )
                )
            elif relation == "strict_upper":
                for occurrence_id in occurrences:
                    coefficients[positions[occurrence_id]] -= 1
                inequalities.append(
                    AngleInequality(
                        tuple(coefficients), float(limit - len(occurrences))
                    )
                )
        return tuple(equations), tuple(inequalities)

    def _constraints_allow(
        self,
        full_blocks: Sequence[Sequence[int]],
        domains: Sequence[Sequence[Sequence[int]]],
    ) -> bool:
        if not full_blocks:
            return True
        length_rows = self._length_rows(full_blocks, domains)
        length = self.length_oracle.analyze(len(full_blocks), length_rows)
        if not length.feasible:
            self._length_rejections += 1
            self.event_sink("arrangement_length_rejections", 1)
            return False
        equations, inequalities = self._angle_constraints(full_blocks)
        angle = self.angle_oracle.analyze(
            len(full_blocks), equations, inequalities=inequalities
        )
        if not angle.feasible:
            self._angle_rejections += 1
            self.event_sink("arrangement_angle_rejections", 1)
            return False
        return True

    def _representative_choices(
        self,
        orbit_indices: Sequence[int],
        *,
        forced: Mapping[int, int],
    ) -> Iterator[tuple[int, ...]]:
        ordered = tuple(
            sorted(
                orbit_indices,
                key=lambda orbit_index: (
                    0 if orbit_index in forced else 1,
                    len(self.occurrence_orbits[orbit_index]),
                    orbit_index,
                ),
            )
        )
        sector_pieces = [set() for _sector in range(self.symmetry_order)]
        selected: dict[int, int] = {}

        def visit(position: int) -> Iterator[tuple[int, ...]]:
            if self._should_stop():
                return
            if position == len(ordered):
                yield tuple(selected[index] for index in orbit_indices)
                return
            orbit_index = ordered[position]
            if self.pointwise_transform is not None:
                representative = forced.get(
                    orbit_index, self.occurrence_orbits[orbit_index][0]
                )
                pieces = tuple(
                    self.occurrence_piece[item]
                    for item in self.occurrence_orbits[orbit_index]
                )
                if len(set(pieces)) != len(pieces) or any(
                    piece in sector_pieces[0] for piece in pieces
                ):
                    return
                sector_pieces[0].update(pieces)
                selected[orbit_index] = representative
                yield from visit(position + 1)
                selected.pop(orbit_index, None)
                sector_pieces[0].difference_update(pieces)
                return
            choices = (
                (forced[orbit_index],)
                if orbit_index in forced
                else self.occurrence_orbits[orbit_index]
            )
            for occurrence_id in choices:
                if self._should_stop():
                    return
                expanded = self._expanded_representative(occurrence_id)
                pieces = tuple(
                    self.occurrence_piece[item] for item in expanded
                )
                if any(
                    piece in sector_pieces[sector]
                    for sector, piece in enumerate(pieces)
                ):
                    continue
                for sector, piece in enumerate(pieces):
                    sector_pieces[sector].add(piece)
                selected[orbit_index] = occurrence_id
                yield from visit(position + 1)
                selected.pop(orbit_index, None)
                for sector, piece in enumerate(pieces):
                    sector_pieces[sector].remove(piece)

        yield from visit(0)

    def _candidate_fundamental_blocks(
        self,
        remaining: Sequence[int],
        *,
        first: bool,
    ) -> Iterator[tuple[int, ...]]:
        remaining = tuple(int(item) for item in remaining)
        mandatory = (self.anchor_orbit,) if first else ()
        if first and self.anchor_orbit not in remaining:
            return
        optional = tuple(item for item in remaining if item not in mandatory)
        maximum_size = min(len(remaining), len(self.piece_names))
        minimum_optional = 0 if mandatory else 1
        for block_size in range(maximum_size, 0, -1):
            if self._should_stop():
                return
            optional_size = block_size - len(mandatory)
            if optional_size < minimum_optional or optional_size > len(optional):
                continue
            for selected_optional in combinations(optional, optional_size):
                if self._should_stop():
                    return
                selected_orbits = mandatory + tuple(selected_optional)
                forced = (
                    {self.anchor_orbit: self.anchor_occurrence}
                    if first
                    else {}
                )
                for representatives in self._representative_choices(
                    selected_orbits, forced=forced
                ):
                    self._candidate_blocks += 1
                    self.event_sink("arrangement_candidate_blocks", 1)
                    yield tuple(sorted(representatives))

    def _reflection_allows(
        self, blocks: Sequence[Sequence[int]]
    ) -> bool:
        if not self.required_reflections:
            return True
        normalized = tuple(tuple(sorted(block)) for block in blocks)
        for transform in self.required_reflections:
            mapped = tuple(self._mapped_block(block, transform) for block in normalized)
            if len(mapped) > 1:
                mapped = (mapped[0],) + tuple(reversed(mapped[1:]))
            for offset in range(len(mapped)):
                if normalized == mapped[offset:] + mapped[:offset]:
                    return True
        return False

    def _complete_placement(
        self,
        fundamental_blocks: Sequence[Sequence[int]],
        domains: Sequence[Sequence[Sequence[int]]],
    ) -> Placement | None:
        full_blocks = self._full_blocks(fundamental_blocks)
        flattened = tuple(item for block in full_blocks for item in block)
        if len(flattened) != len(self.occurrences) or len(set(flattened)) != len(flattened):
            raise RuntimeError("Complete arrangement does not cover occurrences once")
        if not self._reflection_allows(full_blocks):
            self._reflection_rejections += 1
            self.event_sink("arrangement_reflection_rejections", 1)
            return None

        sequences = []
        for piece_index in range(len(self.piece_names)):
            sequence = tuple(
                occurrence_id
                for block in full_blocks
                for occurrence_id in block
                if self.occurrence_piece[occurrence_id] == piece_index
            )
            if sequence not in domains[piece_index]:
                return None
            sequences.append(sequence)
        assignment_id = self.assignment_enumerator.assignment_id_for_sequences(
            sequences
        )
        if assignment_id is None:
            return None
        assignment = self.assignment_enumerator.assignment_at(assignment_id)
        if assignment.sequences != tuple(sequences):
            raise RuntimeError("Arrangement assignment reconstruction drifted")

        positions = self._positions(full_blocks)
        length_rows = self._length_rows(full_blocks, domains)
        length = self.length_oracle.analyze(
            len(full_blocks), length_rows, need_witness=True
        )
        if not length.feasible:
            return None
        equations, inequalities = self._angle_constraints(full_blocks)
        angle = self.angle_oracle.analyze(
            len(full_blocks), equations, need_witness=True, inequalities=inequalities
        )
        if not angle.feasible:
            return None
        placement = Placement(
            placement_id=self._placement_id,
            assignment=assignment,
            blocks=tuple(tuple(block) for block in full_blocks),
            positions=positions,
            length_rows=length_rows,
            length_margin=length.margin,
            length_witness=length.lengths,
            angle_equations=equations,
            angle_margin=angle.margin,
            angle_witness=angle.turns_pi,
            angle_inequalities=inequalities,
        )
        self._placement_id += 1
        self._complete_arrangements += 1
        self.event_sink("arrangement_complete", 1)
        return placement

    def _should_stop(self) -> bool:
        return self.stop_predicate() or (
            self.max_nodes is not None and self._nodes >= self.max_nodes
        )

    def _search(
        self,
        fundamental_blocks: tuple[tuple[int, ...], ...],
        remaining: tuple[int, ...],
        domains: tuple[tuple[tuple[int, ...], ...], ...],
    ) -> Iterator[Placement]:
        if self._should_stop():
            return
        self._nodes += 1
        self.event_sink("arrangement_nodes", 1)
        if not remaining:
            placement = self._complete_placement(fundamental_blocks, domains)
            if placement is not None:
                yield placement
            return

        first = not fundamental_blocks
        for block in self._candidate_fundamental_blocks(remaining, first=first):
            if self._should_stop():
                return
            selected_orbits = {self.orbit_index[item] for item in block}
            next_remaining = tuple(
                item for item in remaining if item not in selected_orbits
            )
            next_blocks = fundamental_blocks + (block,)
            full_blocks = self._full_blocks(next_blocks)
            next_domains = self._filter_sequence_domains(full_blocks, domains)
            if next_domains is None:
                continue
            if not self._constraints_allow(full_blocks, next_domains):
                continue
            yield from self._search(next_blocks, next_remaining, next_domains)

    def enumerate(self) -> Iterator[Placement]:
        remaining = tuple(range(len(self.occurrence_orbits)))
        yield from self._search((), remaining, self.sequence_domains)

    @property
    def statistics(self) -> ArrangementSearchStatistics:
        return ArrangementSearchStatistics(
            nodes=self._nodes,
            candidate_blocks=self._candidate_blocks,
            contour_order_rejections=self._contour_order_rejections,
            collision_rejections=self._collision_rejections,
            length_rejections=self._length_rejections,
            angle_rejections=self._angle_rejections,
            reflection_rejections=self._reflection_rejections,
            complete_arrangements=self._complete_arrangements,
        )
