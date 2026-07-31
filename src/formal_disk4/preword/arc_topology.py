from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

from formal_disk4.constraints.strict_length_lp import (
    ExactStrictLengthFeasibilityOracle,
    StrictLengthFeasibilityOracle,
)
from formal_disk4.enumeration.weak_orders import Placement
from formal_disk4.maps.base import PlanarMap
from formal_disk4.words.algebra import Word, inverse_word
from formal_disk4.words.compile import CompiledWordCase


IntRow = Tuple[int, ...]


@dataclass(frozen=True, order=True)
class CircularInterval:
    """A smooth same-radius circular subarc on the prototype contour.

    The interval is always stored in the positive prototype direction from
    ``start_boundary`` to ``end_boundary``.  ``sign`` is +1 for convex and -1
    for concave relative to the prototype piece interior.  Boundaries are the
    atomic contour boundaries, not word-solver subdivisions.
    """

    start_boundary: int
    end_boundary: int
    sign: int


@dataclass(frozen=True)
class RadiusArcTopologyResult:
    feasible: bool
    reason: str
    propagated_intervals: int
    circular_atomic_intervals: int
    unresolved_images: int
    endpoint_crossing_checks: int
    forced_overlap_checks: int
    propagation_truncated: bool
    forced_atomic_signs: Tuple[int, ...]

    def to_dict(self) -> Dict[str, object]:
        return {
            "feasible": self.feasible,
            "reason": self.reason,
            "propagated_intervals": self.propagated_intervals,
            "circular_atomic_intervals": self.circular_atomic_intervals,
            "unresolved_images": self.unresolved_images,
            "endpoint_crossing_checks": self.endpoint_crossing_checks,
            "forced_overlap_checks": self.forced_overlap_checks,
            "propagation_truncated": self.propagation_truncated,
            "forced_atomic_signs": list(self.forced_atomic_signs),
        }


@dataclass(frozen=True)
class _PathLayout:
    word: Word
    boundaries: Tuple[int, ...]
    prefixes: Tuple[IntRow, ...]


class _EqualitySpace:
    """Exact row-space reducer for homogeneous integral length equations."""

    def __init__(self, width: int, rows: Iterable[Sequence[int]]) -> None:
        matrix = [
            [Fraction(int(value)) for value in row]
            for row in rows
            if any(int(value) for value in row)
        ]
        current = 0
        pivots: list[tuple[int, list[Fraction]]] = []
        for column in range(width):
            pivot = next(
                (index for index in range(current, len(matrix)) if matrix[index][column]),
                None,
            )
            if pivot is None:
                continue
            matrix[current], matrix[pivot] = matrix[pivot], matrix[current]
            scale = matrix[current][column]
            matrix[current] = [value / scale for value in matrix[current]]
            for index in range(len(matrix)):
                if index == current:
                    continue
                factor = matrix[index][column]
                if factor:
                    matrix[index] = [
                        value - factor * pivot_value
                        for value, pivot_value in zip(matrix[index], matrix[current])
                    ]
            pivots.append((column, matrix[current]))
            current += 1
            if current == len(matrix):
                break
        self.width = width
        self.pivots = tuple(pivots)

    def reduce(self, row: Sequence[int | Fraction]) -> Tuple[Fraction, ...]:
        values = [Fraction(value) for value in row]
        for column, pivot in self.pivots:
            factor = values[column]
            if factor:
                values = [
                    value - factor * pivot_value
                    for value, pivot_value in zip(values, pivot)
                ]
        return tuple(values)

    def equal(self, left: Sequence[int | Fraction], right: Sequence[int | Fraction]) -> bool:
        return not any(
            self.reduce(tuple(Fraction(a) - Fraction(b) for a, b in zip(left, right)))
        )


class RadiusArcTopologyFilter:
    """Structural same-radius arc propagation before word solving.

    The filter uses only the compiled interface words and the current positive
    length system.  It never guesses a Nielsen--Levi subdivision.  It propagates
    a smooth circular interval only when both image endpoints are already forced
    to coincide with atomic boundaries.  Symbolic non-aligned images are still
    checked for forced traversal of a hard outer endpoint and for forced overlap
    with an oppositely signed known circular interval.

    This stage performs only topological interval reasoning. Metric balances and
    global curvature identities are handled by a separate exact linear system.
    """

    def __init__(
        self,
        *,
        tolerance: float = 1e-9,
        enable_endpoint_crossing: bool = True,
        max_intervals: int = 1024,
    ) -> None:
        self.strict_oracle = StrictLengthFeasibilityOracle(tolerance=tolerance)
        self.exact_strict_oracle = ExactStrictLengthFeasibilityOracle()
        self.enable_endpoint_crossing = bool(enable_endpoint_crossing)
        self.max_intervals = max(1, int(max_intervals))

    def seed_only(self, compiled: CompiledWordCase) -> RadiusArcTopologyResult:
        """Return only the radius-R facts stated directly by exterior arcs."""

        size = len(compiled.atomic_variables)
        variable_index = {name: index for index, name in enumerate(compiled.atomic_variables)}
        signs: Dict[int, int] = {}
        seeds = self._outer_seed_intervals(compiled, variable_index, size)
        for seed in seeds:
            for index in self._cyclic_indices(
                seed.start_boundary, seed.end_boundary, size
            ):
                signs[index] = +1
        return RadiusArcTopologyResult(
            True,
            "topology disabled; exterior seeds only",
            len(seeds),
            len(signs),
            0,
            0,
            0,
            False,
            tuple(signs.get(index, 0) for index in range(size)),
        )

    def analyze(
        self,
        planar_map: PlanarMap,
        placement: Placement,
        compiled: CompiledWordCase,
    ) -> RadiusArcTopologyResult:
        return self.analyze_compiled(
            planar_map,
            placement.length_rows,
            compiled,
        )

    def analyze_compiled(
        self,
        planar_map: PlanarMap,
        length_rows: Sequence[Sequence[int]],
        compiled: CompiledWordCase,
        *,
        additional_hard_outer_boundaries: Iterable[int] = (),
    ) -> RadiusArcTopologyResult:
        """Analyze an already compiled, possibly conservative partial case.

        ``additional_hard_outer_boundaries`` is used by the weak-order prefix
        filter for hard boundary points whose adjacent outer arc is not yet
        closed in the current prefix.  Adding such fixed boundaries can only
        expose contradictions; unresolved arcs and interfaces are omitted.
        """

        size = len(compiled.atomic_variables)
        variable_index = {name: index for index, name in enumerate(compiled.atomic_variables)}
        equality_rows = tuple(tuple(int(value) for value in row) for row in length_rows)
        equality_space = _EqualitySpace(size, equality_rows)
        hard_outer_boundaries = frozenset(
            set(self._hard_outer_boundaries(planar_map, compiled, variable_index, size))
            | {int(value) for value in additional_hard_outer_boundaries}
        )
        seeds = self._outer_seed_intervals(compiled, variable_index, size)

        endpoint_checks = 0
        overlap_checks = 0
        unresolved_images = 0
        known: set[CircularInterval] = set()
        signs: Dict[int, int] = {}
        queue: List[CircularInterval] = []
        propagation_truncated = False

        def reject(reason: str) -> RadiusArcTopologyResult:
            return RadiusArcTopologyResult(
                False,
                reason,
                len(known),
                len(signs),
                unresolved_images,
                endpoint_checks,
                overlap_checks,
                propagation_truncated,
                tuple(signs.get(index, 0) for index in range(size)),
            )

        def add_interval(interval: CircularInterval) -> str | None:
            nonlocal propagation_truncated
            if interval.sign not in (-1, 1):
                raise ValueError("Circular interval sign must be +/-1")
            if interval.start_boundary == interval.end_boundary:
                return "same-radius circular interval covers the whole prototype"
            if self.enable_endpoint_crossing:
                for boundary in hard_outer_boundaries:
                    if self._boundary_strictly_inside(
                        boundary,
                        interval.start_boundary,
                        interval.end_boundary,
                        size,
                    ):
                        return "same-radius circular arc crosses a hard outer endpoint"
            for index in self._cyclic_indices(
                interval.start_boundary, interval.end_boundary, size
            ):
                previous = signs.get(index)
                if previous is not None and previous != interval.sign:
                    return "same atomic interval forced both convex and concave"
            if interval in known:
                return None
            if len(known) >= self.max_intervals:
                propagation_truncated = True
                return None
            known.add(interval)
            queue.append(interval)
            for index in self._cyclic_indices(
                interval.start_boundary, interval.end_boundary, size
            ):
                signs[index] = interval.sign
            return None

        for seed in seeds:
            reason = add_interval(seed)
            if reason:
                return reject(reason)

        interface_layouts = []
        for interface in compiled.interfaces:
            left = self._layout(interface.left_positive_word, variable_index, size)
            right = self._layout(
                inverse_word(interface.right_positive_word), variable_index, size
            )
            interface_layouts.append((left, right))

        processed: set[tuple[CircularInterval, int, int]] = set()
        while queue:
            interval = queue.pop(0)
            for interface_index, (left, right) in enumerate(interface_layouts):
                for direction, (source, target) in enumerate(((left, right), (right, left))):
                    process_key = (interval, interface_index, direction)
                    if process_key in processed:
                        continue
                    processed.add(process_key)
                    for start_literal, end_literal in self._covered_runs(source, interval, variable_index, size):
                        source_start = source.prefixes[start_literal]
                        source_end = source.prefixes[end_literal]

                        if self.enable_endpoint_crossing:
                            for position, boundary in enumerate(target.boundaries[1:-1], start=1):
                                if boundary not in hard_outer_boundaries:
                                    continue
                                endpoint_checks += 1
                                point = target.prefixes[position]
                                if self._forced_strict_between(
                                    source_start,
                                    point,
                                    source_end,
                                    equality_rows,
                                ):
                                    return reject(
                                        "mapped same-radius circular arc crosses a hard outer endpoint"
                                    )

                        image_sign = -interval.sign
                        for other in tuple(known):
                            if other.sign == image_sign:
                                continue
                            for other_start_index, other_end_index in self._covered_runs(
                                target, other, variable_index, size
                            ):
                                overlap_checks += 1
                                if self._forced_positive_overlap(
                                    source_start,
                                    source_end,
                                    target.prefixes[other_start_index],
                                    target.prefixes[other_end_index],
                                    equality_rows,
                                ):
                                    return reject(
                                        "mapped circular arc is forced to overlap opposite circular sign"
                                    )

                        target_start_index = self._matching_prefix_index(
                            target.prefixes, source_start, equality_space
                        )
                        target_end_index = self._matching_prefix_index(
                            target.prefixes, source_end, equality_space
                        )
                        if (
                            target_start_index is None
                            or target_end_index is None
                            or target_start_index >= target_end_index
                        ):
                            unresolved_images += 1
                            continue
                        target_word = target.word[target_start_index:target_end_index]
                        propagated = self._interval_from_word(
                            target_word, variable_index, size, image_sign
                        )
                        reason = add_interval(propagated)
                        if reason:
                            return reject(reason)

        return RadiusArcTopologyResult(
            True,
            "feasible",
            len(known),
            len(signs),
            unresolved_images,
            endpoint_checks,
            overlap_checks,
            propagation_truncated,
            tuple(signs.get(index, 0) for index in range(size)),
        )

    @staticmethod
    def _zero(size: int) -> IntRow:
        return tuple(0 for _ in range(size))

    def _layout(
        self,
        word: Word,
        variable_index: Mapping[str, int],
        size: int,
    ) -> _PathLayout:
        if not word:
            raise ValueError("Compiled interface path cannot be empty")
        boundaries: List[int] = []
        prefixes: List[IntRow] = [self._zero(size)]
        previous_end: int | None = None
        accumulated = [0] * size
        for literal in word:
            index = variable_index[literal.variable]
            start = (index + 1) % size if literal.inverse else index
            end = index if literal.inverse else (index + 1) % size
            if previous_end is not None and previous_end != start:
                raise ValueError("Compiled word is not a contiguous prototype path")
            if not boundaries:
                boundaries.append(start)
            boundaries.append(end)
            previous_end = end
            accumulated[index] += 1
            prefixes.append(tuple(accumulated))
        return _PathLayout(tuple(word), tuple(boundaries), tuple(prefixes))

    def _interval_from_word(
        self,
        word: Word,
        variable_index: Mapping[str, int],
        size: int,
        sign: int,
    ) -> CircularInterval:
        layout = self._layout(word, variable_index, size)
        first = word[0]
        if all(literal.inverse == first.inverse for literal in word):
            if first.inverse:
                return CircularInterval(layout.boundaries[-1], layout.boundaries[0], sign)
            return CircularInterval(layout.boundaries[0], layout.boundaries[-1], sign)
        raise ValueError("A compiled piece edge changed prototype direction internally")

    def _outer_seed_intervals(
        self,
        compiled: CompiledWordCase,
        variable_index: Mapping[str, int],
        size: int,
    ) -> Tuple[CircularInterval, ...]:
        return tuple(
            self._interval_from_word(outer.positive_word, variable_index, size, +1)
            for outer in compiled.outer_arcs
        )

    def _hard_outer_boundaries(
        self,
        planar_map: PlanarMap,
        compiled: CompiledWordCase,
        variable_index: Mapping[str, int],
        size: int,
    ) -> frozenset[int]:
        hard_vertex_names = {
            vertex.name
            for vertex in planar_map.vertices
            if vertex.kind == "outer" and len(vertex.incident_pieces) >= 2
        }
        by_name = {interface.name: interface for interface in planar_map.outer_interfaces()}
        boundaries: set[int] = set()
        for outer in compiled.outer_arcs:
            interface = by_name[outer.name]
            view = interface.views[0]
            layout = self._layout(outer.positive_word, variable_index, size)
            if view.start_vertex in hard_vertex_names:
                boundaries.add(layout.boundaries[0])
            if view.end_vertex in hard_vertex_names:
                boundaries.add(layout.boundaries[-1])
        return frozenset(boundaries)

    @staticmethod
    def _cyclic_indices(start: int, end: int, size: int) -> Tuple[int, ...]:
        output: List[int] = []
        current = start
        while current != end:
            output.append(current)
            current = (current + 1) % size
            if len(output) > size:
                raise RuntimeError("Invalid cyclic interval")
        return tuple(output)

    def _covered_runs(
        self,
        layout: _PathLayout,
        interval: CircularInterval,
        variable_index: Mapping[str, int],
        size: int,
    ) -> Tuple[Tuple[int, int], ...]:
        covered = set(self._cyclic_indices(interval.start_boundary, interval.end_boundary, size))
        flags = [variable_index[literal.variable] in covered for literal in layout.word]
        runs: List[Tuple[int, int]] = []
        start: int | None = None
        for index, flag in enumerate(flags + [False]):
            if flag and start is None:
                start = index
            elif not flag and start is not None:
                runs.append((start, index))
                start = None
        return tuple(runs)

    @staticmethod
    def _boundary_strictly_inside(boundary: int, start: int, end: int, size: int) -> bool:
        if boundary in (start, end):
            return False
        current = (start + 1) % size
        while current != end:
            if current == boundary:
                return True
            current = (current + 1) % size
        return False

    @staticmethod
    def _subtract(left: Sequence[int], right: Sequence[int]) -> IntRow:
        return tuple(int(a) - int(b) for a, b in zip(left, right))

    def _positive_feasible(
        self,
        equality_rows: Sequence[Sequence[int]],
        inequality_rows: Sequence[Sequence[int]],
        *,
        exact: bool = False,
    ) -> bool:
        if not equality_rows:
            width = len(inequality_rows[0]) if inequality_rows else 0
        else:
            width = len(equality_rows[0])
        if width <= 0:
            raise ValueError("Cannot infer length-system width")
        oracle = self.exact_strict_oracle if exact else self.strict_oracle
        return oracle.analyze(width, equality_rows, inequality_rows).feasible

    def _forced_strict_between(
        self,
        start: Sequence[int],
        point: Sequence[int],
        end: Sequence[int],
        equality_rows: Sequence[Sequence[int]],
    ) -> bool:
        # point <= start  <=>  point-start <= 0
        before_row = self._subtract(point, start)
        after_row = self._subtract(end, point)
        can_be_before_or_at = self._positive_feasible(
            equality_rows,
            (before_row,),
        )
        if can_be_before_or_at:
            return False
        can_be_after_or_at = self._positive_feasible(
            equality_rows,
            (after_row,),
        )
        if can_be_after_or_at:
            return False
        # Certify both failed alternatives in exact rational arithmetic.
        return not self._positive_feasible(
            equality_rows, (before_row,), exact=True
        ) and not self._positive_feasible(
            equality_rows, (after_row,), exact=True
        )

    def _forced_positive_overlap(
        self,
        first_start: Sequence[int],
        first_end: Sequence[int],
        second_start: Sequence[int],
        second_end: Sequence[int],
        equality_rows: Sequence[Sequence[int]],
    ) -> bool:
        # Disjoint or touching with first before second: first_end <= second_start.
        first_row = self._subtract(first_end, second_start)
        second_row = self._subtract(second_end, first_start)
        first_before = self._positive_feasible(equality_rows, (first_row,))
        if first_before:
            return False
        second_before = self._positive_feasible(equality_rows, (second_row,))
        if second_before:
            return False
        return not self._positive_feasible(
            equality_rows, (first_row,), exact=True
        ) and not self._positive_feasible(
            equality_rows, (second_row,), exact=True
        )

    @staticmethod
    def _matching_prefix_index(
        prefixes: Sequence[Sequence[int]],
        form: Sequence[int],
        equality_space: _EqualitySpace,
    ) -> int | None:
        matches = [
            index for index, prefix in enumerate(prefixes) if equality_space.equal(prefix, form)
        ]
        return matches[0] if len(matches) == 1 else None
