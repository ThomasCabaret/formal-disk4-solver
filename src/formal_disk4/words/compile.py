from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

from formal_disk4.enumeration.weak_orders import Placement
from formal_disk4.maps.base import InterfaceSpec, Occurrence, PlanarMap

from .algebra import Equation, Literal, Word, inverse_word, substitute_word, word_to_text


@dataclass(frozen=True)
class CompiledInterface:
    name: str
    left_piece: str
    right_piece: str
    left_positive_word: Word
    right_positive_word: Word
    equation: Equation
    relative_parity: int

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "left_piece": self.left_piece,
            "right_piece": self.right_piece,
            "left_positive_word": word_to_text(self.left_positive_word),
            "right_positive_word": word_to_text(self.right_positive_word),
            "equation": self.equation.to_text(),
            "relative_parity": self.relative_parity,
            "isometry": "direct" if self.relative_parity == 1 else "reflected",
        }


@dataclass(frozen=True)
class CompiledOuterArc:
    name: str
    piece: str
    positive_word: Word


@dataclass(frozen=True)
class CompiledWordCase:
    atomic_variables: Tuple[str, ...]
    contour_word: Word
    equations: Tuple[Equation, ...]
    interfaces: Tuple[CompiledInterface, ...]
    outer_arcs: Tuple[CompiledOuterArc, ...]

    def to_dict(self) -> Dict[str, object]:
        return {
            "atomic_variables": list(self.atomic_variables),
            "contour_word": word_to_text(self.contour_word),
            "equations": [equation.to_text() for equation in self.equations],
            "interfaces": [interface.to_dict() for interface in self.interfaces],
            "outer_arcs": [
                {
                    "name": arc.name,
                    "piece": arc.piece,
                    "positive_word": word_to_text(arc.positive_word),
                }
                for arc in self.outer_arcs
            ],
        }


def cyclic_factor(
    contour: Word, start_boundary: int, end_boundary: int, direction: int
) -> Word:
    if start_boundary == end_boundary:
        return ()
    size = len(contour)
    output: List[Literal] = []
    current = start_boundary
    if direction == 1:
        while current != end_boundary:
            output.append(contour[current])
            current = (current + 1) % size
    elif direction == -1:
        while current != end_boundary:
            segment_index = (current - 1) % size
            output.append(contour[segment_index].flipped())
            current = segment_index
    else:
        raise ValueError("direction must be +1 or -1")
    return tuple(output)


def compile_word_case(planar_map: PlanarMap, placement: Placement) -> CompiledWordCase:
    atomic_variables = tuple(f"X{index}" for index in range(placement.interval_count))
    contour_word = tuple(Literal(name) for name in atomic_variables)
    piece_index = {name: index for index, name in enumerate(placement.assignment.piece_names)}
    occurrence_index = {
        occurrence: index for index, occurrence in enumerate(planar_map.occurrences())
    }

    def positive_piece_word(piece: str, start_vertex: str, end_vertex: str) -> Word:
        start_id = occurrence_index[Occurrence(piece, start_vertex)]
        end_id = occurrence_index[Occurrence(piece, end_vertex)]
        start_boundary = placement.positions[start_id]
        end_boundary = placement.positions[end_id]
        direction = placement.assignment.orientation_signs[piece_index[piece]]
        word = cyclic_factor(contour_word, start_boundary, end_boundary, direction)
        if not word:
            raise ValueError("A piece edge acquired zero contour length")
        return word

    compiled_interfaces: List[CompiledInterface] = []
    equations: List[Equation] = []
    for interface in planar_map.internal_interfaces():
        left_view, right_view = interface.views
        left_word = positive_piece_word(
            left_view.piece, left_view.start_vertex, left_view.end_vertex
        )
        right_word = positive_piece_word(
            right_view.piece, right_view.start_vertex, right_view.end_vertex
        )
        equation = Equation(left_word, inverse_word(right_word))
        equations.append(equation)
        left_sign = placement.assignment.orientation_signs[piece_index[left_view.piece]]
        right_sign = placement.assignment.orientation_signs[piece_index[right_view.piece]]
        compiled_interfaces.append(
            CompiledInterface(
                name=interface.name,
                left_piece=left_view.piece,
                right_piece=right_view.piece,
                left_positive_word=left_word,
                right_positive_word=right_word,
                equation=equation,
                relative_parity=left_sign * right_sign,
            )
        )

    outer_arcs = []
    for interface in planar_map.outer_interfaces():
        view = interface.views[0]
        outer_arcs.append(
            CompiledOuterArc(
                interface.name,
                view.piece,
                positive_piece_word(view.piece, view.start_vertex, view.end_vertex),
            )
        )

    return CompiledWordCase(
        atomic_variables=atomic_variables,
        contour_word=contour_word,
        equations=tuple(equations),
        interfaces=tuple(compiled_interfaces),
        outer_arcs=tuple(outer_arcs),
    )


@dataclass(frozen=True)
class DirectedSegmentRef:
    segment_index: int
    forward: bool


@dataclass(frozen=True)
class ContactMapping:
    interface_name: str
    left_piece: str
    right_piece: str
    relative_parity: int
    pairs: Tuple[Tuple[DirectedSegmentRef, DirectedSegmentRef], ...]


def _expanded_contour_refs(
    atomic_variables: Sequence[str], environment: Mapping[str, Word]
) -> Tuple[Word, Dict[str, Tuple[DirectedSegmentRef, ...]]]:
    expanded: List[Literal] = []
    refs: Dict[str, Tuple[DirectedSegmentRef, ...]] = {}
    for variable in atomic_variables:
        variable_refs: List[DirectedSegmentRef] = []
        for literal in environment[variable]:
            segment_index = len(expanded)
            expanded.append(literal)
            # A positive occurrence of an atomic variable traverses its expanded
            # image in contour order, independently of whether an individual
            # terminal literal uses its curve template directly or inversely.
            # ``forward`` records traversal of the expanded contour segment; the
            # literal itself records orientation relative to the curve template.
            variable_refs.append(DirectedSegmentRef(segment_index, True))
        refs[variable] = tuple(variable_refs)
    return tuple(expanded), refs


def _path_refs(word: Word, refs: Mapping[str, Tuple[DirectedSegmentRef, ...]]) -> Tuple[DirectedSegmentRef, ...]:
    output: List[DirectedSegmentRef] = []
    for literal in word:
        variable_refs = refs[literal.variable]
        if literal.inverse:
            output.extend(
                DirectedSegmentRef(item.segment_index, not item.forward)
                for item in reversed(variable_refs)
            )
        else:
            output.extend(variable_refs)
    return tuple(output)


def build_contact_mappings(
    compiled: CompiledWordCase, environment: Mapping[str, Word]
) -> Tuple[Word, Tuple[ContactMapping, ...]]:
    expanded_contour, refs = _expanded_contour_refs(compiled.atomic_variables, environment)
    mappings: List[ContactMapping] = []
    for interface in compiled.interfaces:
        left_refs = _path_refs(interface.left_positive_word, refs)
        right_same_direction_refs = _path_refs(inverse_word(interface.right_positive_word), refs)
        left_expanded = substitute_word(interface.left_positive_word, environment)
        right_expanded = substitute_word(inverse_word(interface.right_positive_word), environment)
        if left_expanded != right_expanded:
            raise ValueError(f"Terminal environment does not satisfy {interface.name}")
        if len(left_refs) != len(right_same_direction_refs):
            raise RuntimeError("Equal terminal words yielded different mapping lengths")
        mappings.append(
            ContactMapping(
                interface.name,
                interface.left_piece,
                interface.right_piece,
                interface.relative_parity,
                tuple(zip(left_refs, right_same_direction_refs)),
            )
        )
    return expanded_contour, tuple(mappings)
