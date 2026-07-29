from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations
from typing import Callable, Dict, Iterable, Iterator, List, Mapping, Sequence, Tuple

from formal_disk4.constraints.angle_lp import AngleEquation, AngleFeasibilityOracle
from formal_disk4.constraints.length_lp import LengthFeasibilityOracle
from formal_disk4.maps.base import InterfaceSpec, Occurrence, PlanarMap

from .assignments import AssignmentTransform, ContourAssignment
from .exterior_arc_repetition import build_exterior_arc_repetition_constraint


EventSink = Callable[[str, int], None]
StopPredicate = Callable[[], bool]
CheckpointSink = Callable[[Mapping[str, object]], None]


@dataclass(frozen=True)
class Placement:
    placement_id: int
    assignment: ContourAssignment
    blocks: Tuple[Tuple[int, ...], ...]
    positions: Tuple[int, ...]
    length_rows: Tuple[Tuple[int, ...], ...]
    length_margin: float
    length_witness: Tuple[float, ...]
    angle_equations: Tuple[AngleEquation, ...]
    angle_margin: float
    angle_witness: Tuple[float, ...]

    @property
    def interval_count(self) -> int:
        return len(self.blocks)

    def to_dict(self, occurrence_names: Sequence[str]) -> Dict[str, object]:
        return {
            "placement_id": self.placement_id,
            "assignment_id": self.assignment.assignment_id,
            "blocks": [
                [occurrence_names[occurrence_id] for occurrence_id in block]
                for block in self.blocks
            ],
            "length_margin": self.length_margin,
            "length_witness": list(self.length_witness),
            "length_rows": [list(row) for row in self.length_rows],
            "angle_margin": self.angle_margin,
            "signed_turn_witness_pi": list(self.angle_witness),
            "prototype_angle_witness_pi": [1.0 - value for value in self.angle_witness],
            "angle_equations": [
                {"coefficients": list(equation.coefficients), "rhs": equation.rhs}
                for equation in self.angle_equations
            ],
        }


class WeakOrderEnumerator:
    """Depth-first weak cyclic interleaving with incremental pruning."""

    def __init__(
        self,
        planar_map: PlanarMap,
        assignment: ContourAssignment,
        occurrence_names: Sequence[str],
        length_oracle: LengthFeasibilityOracle,
        angle_oracle: AngleFeasibilityOracle,
        symmetry_mode: str = "incremental",
        enable_length_filter: bool = True,
        enable_angle_filter: bool = True,
        enable_exterior_arc_repetition_filter: bool = True,
        event_sink: EventSink | None = None,
        stop_predicate: StopPredicate | None = None,
        resume_state: Mapping[str, object] | None = None,
        checkpoint_sink: CheckpointSink | None = None,
        track_exact_leaf_mass: bool = True,
    ) -> None:
        self.planar_map = planar_map
        self.assignment = assignment
        self.occurrence_names = tuple(occurrence_names)
        self.length_oracle = length_oracle
        self.angle_oracle = angle_oracle
        self.symmetry_mode = symmetry_mode
        self.enable_length_filter = enable_length_filter
        self.enable_angle_filter = enable_angle_filter
        self.enable_exterior_arc_repetition_filter = enable_exterior_arc_repetition_filter
        self.event_sink = event_sink or (lambda _name, _amount=1: None)
        self.stop_predicate = stop_predicate or (lambda: False)
        self.checkpoint_sink = checkpoint_sink or (lambda _state: None)
        self.track_exact_leaf_mass = track_exact_leaf_mass
        self.piece_names = assignment.piece_names
        self.piece_index = {name: index for index, name in enumerate(self.piece_names)}
        self.reference_index = self.piece_index[planar_map.reference_piece]
        self.occurrences = planar_map.occurrences()
        self.occurrence_index = {occurrence: index for index, occurrence in enumerate(self.occurrences)}
        self.exterior_arc_repetition = build_exterior_arc_repetition_constraint(
            planar_map,
            assignment.piece_names,
            assignment.sequences,
            self.occurrence_index,
            enabled=enable_exterior_arc_repetition_filter,
        )
        self.interface_occurrences = self._build_interface_occurrences()
        self.vertex_occurrences = self._build_vertex_occurrences()
        self._positive_arc_endpoints = self._build_positive_arc_endpoints()
        self.incremental_stabilizer = tuple(
            transform for transform in assignment.stabilizer if not transform.reverse_cycle
        )
        self._placement_id = 0
        self.target_counters = tuple(len(sequence) for sequence in assignment.sequences)
        state = dict(resume_state or {})
        if state and int(state.get("assignment_id", -1)) != assignment.assignment_id:
            raise ValueError("Weak-order resume state belongs to another assignment")
        self._resume_path = tuple(int(item) for item in state.get("last_completed_path", ()))
        self._resuming = bool(self._resume_path)
        self._processed_leaf_mass = int(state.get("processed_leaf_mass", 0))
        self._placement_id = int(state.get("placement_id", 0))
        self._last_completed_path = self._resume_path

    @property
    def processed_leaf_mass(self) -> int:
        return self._processed_leaf_mass

    @property
    def total_leaf_mass(self) -> int:
        if not self.track_exact_leaf_mass:
            return 0
        return count_weak_orders_for_lengths(self.target_counters, self.reference_index)

    def _subtree_leaf_mass(self, counters: Tuple[int, ...]) -> int:
        if not self.track_exact_leaf_mass:
            return 0
        return _weak_path_count(counters, self.target_counters)

    def checkpoint_state(self) -> Dict[str, object]:
        return {
            "version": 1,
            "assignment_id": self.assignment.assignment_id,
            "last_completed_path": list(self._last_completed_path),
            "processed_leaf_mass": self._processed_leaf_mass,
            "placement_id": self._placement_id,
        }

    def _mark_subtree_complete(
        self, path: Tuple[int, ...], leaf_mass: int = 0
    ) -> None:
        self._last_completed_path = path
        self._processed_leaf_mass += int(leaf_mass)
        self.checkpoint_sink(self.checkpoint_state())

    def _resume_child_allowed(
        self, path: Tuple[int, ...], child_mask: int
    ) -> bool:
        if not self._resuming:
            return True
        depth = len(path)
        if depth >= len(self._resume_path):
            return False
        return child_mask == self._resume_path[depth]

    def _build_interface_occurrences(
        self,
    ) -> Tuple[Tuple[str, Tuple[Tuple[int, int], Tuple[int, int]]], ...]:
        output = []
        for interface in self.planar_map.internal_interfaces():
            views = []
            for view in interface.views:
                views.append(
                    (
                        self.occurrence_index[view.start_occurrence],
                        self.occurrence_index[view.end_occurrence],
                    )
                )
            output.append((interface.name, (views[0], views[1])))
        return tuple(output)

    def _build_vertex_occurrences(self) -> Tuple[Tuple[str, float, Tuple[int, ...]], ...]:
        output = []
        for vertex in self.planar_map.vertices:
            occurrences = tuple(
                self.occurrence_index[Occurrence(piece, vertex.name)]
                for piece in vertex.incident_pieces
            )
            output.append(
                (
                    vertex.name,
                    float(vertex.required_solid_angle_sum_pi),
                    occurrences,
                )
            )
        return tuple(output)

    def _build_positive_arc_endpoints(self) -> Dict[Tuple[int, int], Tuple[int, int]]:
        result: Dict[Tuple[int, int], Tuple[int, int]] = {}
        for piece_index, sequence in enumerate(self.assignment.sequences):
            position = {occurrence_id: index for index, occurrence_id in enumerate(sequence)}
            for interface_index, (_name, views) in enumerate(self.interface_occurrences):
                for view_index, endpoints in enumerate(views):
                    if endpoints[0] not in position:
                        continue
                    start, end = endpoints
                    start_index = position[start]
                    end_index = position[end]
                    if (start_index + 1) % len(sequence) == end_index:
                        result[(interface_index, view_index)] = (start, end)
                    elif (end_index + 1) % len(sequence) == start_index:
                        result[(interface_index, view_index)] = (end, start)
                    else:
                        raise ValueError("Interface endpoints are not adjacent in assignment sequence")
        if len(result) != 2 * len(self.interface_occurrences):
            raise RuntimeError("Could not orient every internal interface view")
        return result

    @staticmethod
    def _arc_vector(start_block: int, end_block: int, block_count: int) -> Tuple[int, ...]:
        if start_block == end_block:
            raise ValueError("A positive piece edge cannot have coincident endpoints")
        row = [0] * block_count
        current = start_block
        while current != end_block:
            row[current] = 1
            current = (current + 1) % block_count
        return tuple(row)

    def _resolved_length_rows(
        self, positions: Sequence[int], block_count: int
    ) -> Tuple[Tuple[int, ...], ...]:
        rows: List[Tuple[int, ...]] = []
        for interface_index, (_name, _views) in enumerate(self.interface_occurrences):
            endpoints0 = self._positive_arc_endpoints[(interface_index, 0)]
            endpoints1 = self._positive_arc_endpoints[(interface_index, 1)]
            all_endpoints = endpoints0 + endpoints1
            if any(positions[occurrence_id] < 0 for occurrence_id in all_endpoints):
                continue
            left = self._arc_vector(
                positions[endpoints0[0]], positions[endpoints0[1]], block_count
            )
            right = self._arc_vector(
                positions[endpoints1[0]], positions[endpoints1[1]], block_count
            )
            rows.append(tuple(a - b for a, b in zip(left, right)))
        return tuple(rows)

    def _resolved_angle_equations(
        self, positions: Sequence[int], block_count: int
    ) -> Tuple[AngleEquation, ...]:
        equations: List[AngleEquation] = []
        for vertex_name, angle_sum_pi, occurrences in self.vertex_occurrences:
            if any(positions[occurrence_id] < 0 for occurrence_id in occurrences):
                continue
            coefficients = [0] * block_count
            for occurrence_id in occurrences:
                # A direct or reflected congruent copy has the same positive
                # polygonal interior angle.  Copy parity affects how signed
                # turns are transported along an interface, but not the
                # physical angle sum at a map vertex.
                coefficients[positions[occurrence_id]] += 1
            # With prototype signed point turn tau = 1 - alpha,
            # Sum(alpha) = angle_sum_pi is equivalent to
            # Sum(tau) = degree - angle_sum_pi.
            rhs = float(len(occurrences) - angle_sum_pi)
            equations.append(AngleEquation(tuple(coefficients), rhs))
        return tuple(equations)

    @staticmethod
    def _transform_blocks(
        blocks: Sequence[Tuple[int, ...]], transform: AssignmentTransform
    ) -> Tuple[Tuple[int, ...], ...]:
        mapped = tuple(
            tuple(sorted(transform.map_occurrence_id(item) for item in block))
            for block in blocks
        )
        if transform.reverse_cycle and len(mapped) > 1:
            return (mapped[0],) + tuple(reversed(mapped[1:]))
        return mapped

    def _prefix_is_canonical(self, blocks: Tuple[Tuple[int, ...], ...]) -> bool:
        if self.symmetry_mode != "incremental" or len(self.incremental_stabilizer) <= 1:
            return True
        best = min(self._transform_blocks(blocks, transform) for transform in self.incremental_stabilizer)
        return blocks == best

    def _leaf_is_canonical(self, blocks: Tuple[Tuple[int, ...], ...]) -> bool:
        if self.symmetry_mode != "incremental" or len(self.assignment.stabilizer) <= 1:
            return True
        best = min(self._transform_blocks(blocks, transform) for transform in self.assignment.stabilizer)
        return blocks == best

    def enumerate(self) -> Iterator[Placement]:
        if (
            self.exterior_arc_repetition.applicable
            and not self.exterior_arc_repetition.candidate_pairs
        ):
            self.event_sink("exterior_arc_repetition_pruned_assignments", 1)
            self._mark_subtree_complete((), self.total_leaf_mass)
            return

        counters = tuple(0 for _ in self.piece_names)
        positions = tuple(-1 for _ in self.occurrences)
        available_mask = (1 << len(self.piece_names)) - 1
        first_masks = tuple(
            sorted(
                (
                    mask
                    for mask in range(1, available_mask + 1)
                    if mask & (1 << self.reference_index)
                ),
                key=lambda item: (-item.bit_count(), item),
            )
        )
        for mask in first_masks:
            if self.stop_predicate():
                return
            if self._resuming and mask != self._resume_path[0]:
                continue
            result = self._append_block((), counters, positions, mask)
            if result is None:
                continue
            blocks, new_counters, new_positions = result
            yield from self._search(
                blocks,
                new_counters,
                new_positions,
                previous_length_equation_count=0,
                previous_angle_equation_count=0,
                path=(mask,),
            )

    def _append_block(
        self,
        blocks: Tuple[Tuple[int, ...], ...],
        counters: Tuple[int, ...],
        positions: Tuple[int, ...],
        mask: int,
    ) -> Tuple[Tuple[Tuple[int, ...], ...], Tuple[int, ...], Tuple[int, ...]] | None:
        next_counters = list(counters)
        next_positions = list(positions)
        block: List[int] = []
        for piece_index, sequence in enumerate(self.assignment.sequences):
            if not mask & (1 << piece_index):
                continue
            counter = counters[piece_index]
            if counter >= len(sequence):
                return None
            occurrence_id = sequence[counter]
            if next_positions[occurrence_id] >= 0:
                raise RuntimeError("Occurrence placed twice")
            block.append(occurrence_id)
            next_positions[occurrence_id] = len(blocks)
            next_counters[piece_index] += 1
        if not block:
            return None
        return blocks + (tuple(sorted(block)),), tuple(next_counters), tuple(next_positions)

    def _search(
        self,
        blocks: Tuple[Tuple[int, ...], ...],
        counters: Tuple[int, ...],
        positions: Tuple[int, ...],
        previous_length_equation_count: int,
        previous_angle_equation_count: int,
        path: Tuple[int, ...],
    ) -> Iterator[Placement]:
        if self.stop_predicate():
            return
        if self._resuming:
            if path == self._resume_path:
                self._resuming = False
                return
            if self._resume_path[: len(path)] != path:
                return
        self.event_sink("placement_nodes", 1)

        if not self.exterior_arc_repetition.prefix_is_feasible(positions):
            # Once every possible repeated exterior-arc pair has separated an
            # endpoint, no descendant can restore equality in a past block.
            self.event_sink("exterior_arc_repetition_pruned_nodes", 1)
            self._mark_subtree_complete(
                path, self._subtree_leaf_mass(counters)
            )
            return

        if not self._prefix_is_canonical(blocks):
            self.event_sink("symmetry_pruned_nodes", 1)
            self._mark_subtree_complete(path, self._subtree_leaf_mass(counters))
            return

        block_count = len(blocks)
        length_rows = self._resolved_length_rows(positions, block_count)
        if self.enable_length_filter and len(length_rows) > previous_length_equation_count:
            self.event_sink("length_checks", 1)
            length_result = self.length_oracle.analyze(block_count, length_rows)
            if not length_result.feasible:
                self.event_sink("length_pruned_nodes", 1)
                self._mark_subtree_complete(path, self._subtree_leaf_mass(counters))
                return

        angle_equations = self._resolved_angle_equations(positions, block_count)
        if self.enable_angle_filter and len(angle_equations) > previous_angle_equation_count:
            self.event_sink("angle_checks", 1)
            angle_result = self.angle_oracle.analyze(block_count, angle_equations)
            if not angle_result.feasible:
                self.event_sink("angle_pruned_nodes", 1)
                self._mark_subtree_complete(path, self._subtree_leaf_mass(counters))
                return

        complete = all(
            counter == len(sequence)
            for counter, sequence in zip(counters, self.assignment.sequences)
        )
        if complete:
            if not self._leaf_is_canonical(blocks):
                self.event_sink("symmetry_pruned_leaves", 1)
                self._mark_subtree_complete(path, 1)
                return
            length_result = self.length_oracle.analyze(
                block_count, length_rows, need_witness=True
            ) if self.enable_length_filter else None
            angle_result = self.angle_oracle.analyze(
                block_count, angle_equations, need_witness=True
            ) if self.enable_angle_filter else None
            if length_result is not None and not length_result.feasible:
                self._mark_subtree_complete(path, 1)
                return
            if angle_result is not None and not angle_result.feasible:
                self._mark_subtree_complete(path, 1)
                return
            self.event_sink("surviving_placements", 1)
            placement = Placement(
                placement_id=self._placement_id,
                assignment=self.assignment,
                blocks=blocks,
                positions=positions,
                length_rows=length_rows,
                length_margin=length_result.margin if length_result else 0.0,
                length_witness=length_result.lengths if length_result else (),
                angle_equations=angle_equations,
                angle_margin=angle_result.margin if angle_result else 0.0,
                angle_witness=angle_result.turns_pi if angle_result else (),
            )
            yield placement
            self._placement_id += 1
            self._mark_subtree_complete(path, 1)
            return

        available_mask = 0
        for piece_index, (counter, sequence) in enumerate(zip(counters, self.assignment.sequences)):
            if counter < len(sequence):
                available_mask |= 1 << piece_index

        candidates = []
        for mask in range(1, available_mask + 1):
            if mask & ~available_mask:
                continue
            appended = self._append_block(blocks, counters, positions, mask)
            if appended is None:
                continue
            next_blocks, next_counters, next_positions = appended
            next_length_count = len(
                self._resolved_length_rows(next_positions, len(next_blocks))
            )
            next_angle_count = len(
                self._resolved_angle_equations(next_positions, len(next_blocks))
            )
            score = (
                next_length_count - len(length_rows),
                next_angle_count - len(angle_equations),
                mask.bit_count(),
                -mask,
            )
            candidates.append((score, mask, next_blocks, next_counters, next_positions))

        candidates.sort(key=lambda item: item[0], reverse=True)
        for _score, mask, next_blocks, next_counters, next_positions in candidates:
            if self.stop_predicate():
                return
            if not self._resume_child_allowed(path, mask):
                continue
            yield from self._search(
                next_blocks,
                next_counters,
                next_positions,
                previous_length_equation_count=len(length_rows),
                previous_angle_equation_count=len(angle_equations),
                path=path + (mask,),
            )
        if not self.stop_predicate():
            self._mark_subtree_complete(path, 0)


@lru_cache(maxsize=None)
def _weak_path_count(state: Tuple[int, ...], target: Tuple[int, ...]) -> int:
    if state == target:
        return 1
    total = 0
    dimension = len(target)
    for mask in range(1, 1 << dimension):
        next_state = list(state)
        valid = True
        for index in range(dimension):
            if mask & (1 << index):
                if next_state[index] >= target[index]:
                    valid = False
                    break
                next_state[index] += 1
        if valid:
            total += _weak_path_count(tuple(next_state), target)
    return total



def count_weak_orders_for_lengths(
    lengths: Tuple[int, ...], reference_index: int = 0
) -> int:
    """Count anchored weak cyclic orders for arbitrary contour lengths."""
    total = 0
    for first_mask in range(1, 1 << len(lengths)):
        if not first_mask & (1 << reference_index):
            continue
        state = tuple(1 if first_mask & (1 << index) else 0 for index in range(len(lengths)))
        total += _weak_path_count(state, lengths)
    return total


def count_weak_orders_fixed_phases(lengths: Tuple[int, ...] = (3, 4, 4, 4)) -> int:
    """Count weak cyclic orders after fixing the first occurrence of cycle zero."""
    return count_weak_orders_for_lengths(lengths, 0)


def count_distinct_orders_all_peripheral_phases() -> int:
    # 14! / (2! 3!^3), as in the problem statement.
    import math

    return math.factorial(14) // (
        math.factorial(2) * math.factorial(3) ** 3
    )


def count_weak_orders_all_peripheral_phases() -> int:
    return count_weak_orders_fixed_phases() * (4 ** 3)
