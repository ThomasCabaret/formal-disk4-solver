from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

from formal_disk4.enumeration.weak_orders import Placement
from formal_disk4.maps.base import Occurrence, PlanarMap

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
    mirror_variables: Tuple[Tuple[str, str], ...] = ()
    solver_equations: Tuple[Equation, ...] = ()

    @property
    def effective_solver_equations(self) -> Tuple[Equation, ...]:
        return self.solver_equations or self.equations

    @property
    def solver_variables(self) -> Tuple[str, ...]:
        output = list(self.atomic_variables)
        seen = set(output)
        for direct, mirrored in self.mirror_variables:
            for variable in (direct, mirrored):
                if variable not in seen:
                    output.append(variable)
                    seen.add(variable)
        for equation in self.effective_solver_equations:
            for literal in (*equation.left, *equation.right):
                if literal.variable not in seen:
                    output.append(literal.variable)
                    seen.add(literal.variable)
        return tuple(output)

    def mirror_map(self) -> Dict[str, str]:
        output: Dict[str, str] = {}
        for direct, mirrored in self.mirror_variables:
            output[direct] = mirrored
            output[mirrored] = direct
        return output

    def to_dict(self) -> Dict[str, object]:
        return {
            "atomic_variables": list(self.atomic_variables),
            "solver_variables": list(self.solver_variables),
            "mirror_variables": dict(self.mirror_variables),
            "contour_word": word_to_text(self.contour_word),
            "equations": [equation.to_text() for equation in self.equations],
            "solver_equations": [
                equation.to_text() for equation in self.effective_solver_equations
            ],
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


def mirror_word(word: Sequence[Literal], mirror_map: Mapping[str, str]) -> Word:
    """Apply the geometric mirror involution without reversing traversal."""

    output = []
    for literal in word:
        try:
            variable = mirror_map[literal.variable]
        except KeyError as error:
            raise ValueError(f"No mirror variable for {literal.variable}") from error
        output.append(Literal(variable, literal.inverse))
    return tuple(output)


def compile_word_case(planar_map: PlanarMap, placement: Placement) -> CompiledWordCase:
    atomic_variables = tuple(f"X{index}" for index in range(placement.interval_count))
    contour_word = tuple(Literal(name) for name in atomic_variables)
    mirror_variables = tuple((name, f"M_{name}") for name in atomic_variables)
    mirror_map = {left: right for left, right in mirror_variables}
    mirror_map.update({right: left for left, right in mirror_variables})
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
    solver_equations: List[Equation] = []
    for interface in planar_map.internal_interfaces():
        left_view, right_view = interface.views
        left_word = positive_piece_word(
            left_view.piece, left_view.start_vertex, left_view.end_vertex
        )
        right_word = positive_piece_word(
            right_view.piece, right_view.start_vertex, right_view.end_vertex
        )
        left_sign = placement.assignment.orientation_signs[piece_index[left_view.piece]]
        right_sign = placement.assignment.orientation_signs[piece_index[right_view.piece]]
        relative_parity = left_sign * right_sign
        plain_equation = Equation(left_word, inverse_word(right_word))
        equations.append(plain_equation)

        right_same_direction = inverse_word(right_word)
        if relative_parity == -1:
            right_same_direction = mirror_word(right_same_direction, mirror_map)
        solver_equation = Equation(left_word, right_same_direction)
        solver_equations.append(solver_equation)
        # The mirror image of every physical equality is equally mandatory.
        solver_equations.append(
            Equation(
                mirror_word(solver_equation.left, mirror_map),
                mirror_word(solver_equation.right, mirror_map),
            )
        )
        compiled_interfaces.append(
            CompiledInterface(
                name=interface.name,
                left_piece=left_view.piece,
                right_piece=right_view.piece,
                left_positive_word=left_word,
                right_positive_word=right_word,
                equation=plain_equation,
                relative_parity=relative_parity,
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
        mirror_variables=mirror_variables,
        solver_equations=tuple(solver_equations),
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


@dataclass(frozen=True)
class TerminalTemplateRelation:
    left_variable: str
    right_variable: str
    reverse: bool
    mirror: bool
    source: str
    pair_index: int


@dataclass(frozen=True)
class TerminalContactSystem:
    environment: Tuple[Tuple[str, Word], ...]
    terminal_contour: Word
    mappings: Tuple[ContactMapping, ...]
    template_relations: Tuple[TerminalTemplateRelation, ...]

    def environment_map(self) -> Dict[str, Word]:
        return dict(self.environment)


class TerminalMappingInfeasible(ValueError):
    pass


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
            variable_refs.append(DirectedSegmentRef(segment_index, True))
        refs[variable] = tuple(variable_refs)
    return tuple(expanded), refs


def _path_refs(
    word: Word, refs: Mapping[str, Tuple[DirectedSegmentRef, ...]]
) -> Tuple[DirectedSegmentRef, ...]:
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


def build_terminal_contact_system(
    compiled: CompiledWordCase, environment: Mapping[str, Word]
) -> TerminalContactSystem:
    # Direct callers from the pre-mirror API may still provide only the
    # prototype variables. In that compatibility mode, mirror images inherit
    # the same terminal words; production searches provide both sheets.
    complete_environment = dict(environment)
    legacy_mirror_environment = any(
        mirrored not in complete_environment
        for _direct, mirrored in compiled.mirror_variables
    )
    for direct, mirrored in compiled.mirror_variables:
        if mirrored not in complete_environment and direct in complete_environment:
            complete_environment[mirrored] = complete_environment[direct]
    environment = complete_environment

    # Canonical terminal names are assigned from the actual prototype contour
    # first. Mirror-only letters are named afterwards and do not perturb the
    # stable T0,T1,... presentation of existing direct cases.
    terminal_renaming: Dict[str, str] = {}
    for variable in compiled.atomic_variables:
        for literal in environment[variable]:
            if literal.variable not in terminal_renaming:
                terminal_renaming[literal.variable] = f"T{len(terminal_renaming)}"
    for variable in compiled.solver_variables:
        for literal in environment[variable]:
            if literal.variable not in terminal_renaming:
                terminal_renaming[literal.variable] = f"T{len(terminal_renaming)}"
    normalized_environment = {
        variable: tuple(
            Literal(terminal_renaming[literal.variable], literal.inverse)
            for literal in environment[variable]
        )
        for variable in compiled.solver_variables
    }
    environment = normalized_environment
    prototype_environment = {
        variable: environment[variable] for variable in compiled.atomic_variables
    }
    expanded_contour, refs = _expanded_contour_refs(
        compiled.atomic_variables, prototype_environment
    )
    mirror_map = compiled.mirror_map()
    mappings: List[ContactMapping] = []

    for interface in compiled.interfaces:
        left_refs = _path_refs(interface.left_positive_word, refs)
        right_same_direction_word = inverse_word(interface.right_positive_word)
        right_refs = _path_refs(right_same_direction_word, refs)
        transformed_right_word = right_same_direction_word
        if interface.relative_parity == -1:
            if not mirror_map:
                raise TerminalMappingInfeasible(
                    f"Reflected interface {interface.name} has no mirror variables"
                )
            transformed_right_word = mirror_word(transformed_right_word, mirror_map)

        left_expanded = substitute_word(interface.left_positive_word, environment)
        right_expanded = substitute_word(transformed_right_word, environment)
        if left_expanded != right_expanded:
            raise TerminalMappingInfeasible(
                f"Terminal environment does not satisfy {interface.name}"
            )
        if len(left_refs) != len(right_refs) or len(left_refs) != len(left_expanded):
            raise TerminalMappingInfeasible(
                f"Terminal refinement length mismatch on {interface.name}"
            )
        mappings.append(
            ContactMapping(
                interface.name,
                interface.left_piece,
                interface.right_piece,
                interface.relative_parity,
                tuple(zip(left_refs, right_refs)),
            )
        )

    template_relations: List[TerminalTemplateRelation] = []
    mirror_pairs = () if legacy_mirror_environment else compiled.mirror_variables
    for direct, mirrored in mirror_pairs:
        direct_word = environment[direct]
        mirrored_word = environment[mirrored]
        if len(direct_word) != len(mirrored_word):
            raise TerminalMappingInfeasible(
                f"Mirror images of {direct} have different refinement lengths"
            )
        for pair_index, (left, right) in enumerate(zip(direct_word, mirrored_word)):
            template_relations.append(
                TerminalTemplateRelation(
                    left_variable=left.variable,
                    right_variable=right.variable,
                    reverse=left.inverse != right.inverse,
                    mirror=True,
                    source=f"mirror-involution:{direct}",
                    pair_index=pair_index,
                )
            )

    return TerminalContactSystem(
        environment=tuple(
            (variable, prototype_environment[variable])
            for variable in compiled.atomic_variables
        ),
        terminal_contour=expanded_contour,
        mappings=tuple(mappings),
        template_relations=tuple(template_relations),
    )


def build_contact_mappings(
    compiled: CompiledWordCase, environment: Mapping[str, Word]
) -> Tuple[Word, Tuple[ContactMapping, ...]]:
    system = build_terminal_contact_system(compiled, environment)
    return system.terminal_contour, system.mappings
