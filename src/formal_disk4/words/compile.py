from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from fractions import Fraction
from math import gcd, lcm
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

from formal_disk4.constraints.rational_lp import RationalSimplex
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
class CompiledFreeArc:
    """One unconstrained boundary factor of the retained partial domain."""

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
    free_arcs: Tuple[CompiledFreeArc, ...] = ()
    mirror_variables: Tuple[Tuple[str, str], ...] = ()
    solver_equations: Tuple[Equation, ...] = ()
    prototype_rotation_order: int = 1
    prototype_sector_variable: str | None = None

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
            "prototype_rotational_symmetry": {
                "order": self.prototype_rotation_order,
                "sector_variable": self.prototype_sector_variable,
                "constraint": (
                    None
                    if self.prototype_sector_variable is None
                    else (
                        f"contour = {self.prototype_sector_variable}^"
                        f"{self.prototype_rotation_order}"
                    )
                ),
            },
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
            "free_arcs": [
                {
                    "name": arc.name,
                    "piece": arc.piece,
                    "positive_word": word_to_text(arc.positive_word),
                }
                for arc in self.free_arcs
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

    free_arcs = []
    for interface in planar_map.free_interfaces():
        view = interface.views[0]
        free_arcs.append(
            CompiledFreeArc(
                interface.name,
                view.piece,
                positive_piece_word(view.piece, view.start_vertex, view.end_vertex),
            )
        )

    # STRUCTURAL CONSTRAINT: an intrinsically k-fold rotationally symmetric
    # prototype has an oriented contour of the form S^k.  S is a genuine word
    # variable rather than a boundary marker, so its endpoints may fall inside
    # any atomic interval introduced by the contact map.  This is what makes
    # the constraint independent of the graph and valid for partial domains.
    rotation_order = int(planar_map.prototype_rotation_order)
    sector_variable = None
    if rotation_order > 1:
        sector_variable = "ROTATION_SECTOR"
        mirrored_sector_variable = "M_ROTATION_SECTOR"
        if sector_variable in atomic_variables or mirrored_sector_variable in atomic_variables:
            raise ValueError("Prototype rotation helper variable collides with contour variables")
        mirror_variables = mirror_variables + (
            (sector_variable, mirrored_sector_variable),
        )
        direct_sector = (Literal(sector_variable),) * rotation_order
        mirrored_contour = tuple(
            Literal(mirror_map[literal.variable], literal.inverse)
            for literal in contour_word
        )
        mirrored_sector = (Literal(mirrored_sector_variable),) * rotation_order
        solver_equations.append(Equation(contour_word, direct_sector))
        solver_equations.append(Equation(mirrored_contour, mirrored_sector))

    return CompiledWordCase(
        atomic_variables=atomic_variables,
        contour_word=contour_word,
        equations=tuple(equations),
        interfaces=tuple(compiled_interfaces),
        outer_arcs=tuple(outer_arcs),
        free_arcs=tuple(free_arcs),
        mirror_variables=mirror_variables,
        solver_equations=tuple(solver_equations),
        prototype_rotation_order=rotation_order,
        prototype_sector_variable=sector_variable,
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
class TerminalSmoothBoundary:
    """A terminal subdivision point forced to have zero point turn.

    Endpoint-swapping involutions cannot remain opaque constraints on one
    terminal curve atom. The formal specialization splits the atom into two
    half-atoms; their common endpoint is this smooth boundary.
    """

    boundary_index: int
    source_variable: str
    transform: str


@dataclass(frozen=True)
class TerminalContactSystem:
    environment: Tuple[Tuple[str, Word], ...]
    terminal_contour: Word
    mappings: Tuple[ContactMapping, ...]
    template_relations: Tuple[TerminalTemplateRelation, ...]
    forced_smooth_boundaries: Tuple[TerminalSmoothBoundary, ...] = ()
    prototype_rotation_order: int = 1
    prototype_sector_word: Word = ()

    def environment_map(self) -> Dict[str, Word]:
        return dict(self.environment)


class TerminalMappingInfeasible(ValueError):
    pass


def refine_mirror_compatible_terminal_environment(
    environment: Mapping[str, Word],
    mirror_variables: Sequence[Tuple[str, str]],
) -> Dict[str, Word]:
    """Refine terminal atoms so the mirror involution is length preserving.

    The exact word solver deliberately represents the direct and reflected
    alphabets with independent variables.  A physical mirror involution does
    not require their terminal words to be textually equal, but it does require
    every paired variable to refine into the same number of terminal segments.

    For a concrete word-family specialization this is a homogeneous exact
    linear system in the positive lengths of its terminal atoms.  Any positive
    rational witness can be scaled to positive integers.  Replacing each atom
    by a word of that integer length preserves every solved word equation and
    constructs the common refinement instead of hoping that two independently
    produced terminal alphabets happened to use unit atoms compatibly.
    """

    output = dict(environment)
    active_pairs = tuple(
        (direct, mirrored)
        for direct, mirrored in mirror_variables
        if direct in output and mirrored in output
    )
    if not active_pairs:
        return output

    terminal_names = tuple(
        sorted(
            {
                literal.variable
                for word in output.values()
                for literal in word
            }
        )
    )
    if not terminal_names:
        raise TerminalMappingInfeasible(
            "Mirror-compatible terminal refinement has no terminal atoms"
        )
    terminal_index = {name: index for index, name in enumerate(terminal_names)}

    equality_rows: List[List[int]] = []
    for direct, mirrored in active_pairs:
        row = [0 for _ in terminal_names]
        for literal in output[direct]:
            row[terminal_index[literal.variable]] += 1
        for literal in output[mirrored]:
            row[terminal_index[literal.variable]] -= 1
        if any(row):
            equality_rows.append(row)

    # Unit terminal atoms already give a common refinement in the usual case.
    if not equality_rows or all(sum(row) == 0 for row in equality_rows):
        return output

    # Write every positive weight as w=1+y with y>=0, which is the native
    # domain of RationalSimplex.  An equality a.w=0 becomes the pair of exact
    # inequalities a.y<=-a.1 and -a.y<=a.1.
    inequalities: List[List[int]] = []
    bounds: List[int] = []
    for row in equality_rows:
        rhs = -sum(row)
        inequalities.append(list(row))
        bounds.append(rhs)
        inequalities.append([-value for value in row])
        bounds.append(-rhs)
    result = RationalSimplex(
        inequalities,
        bounds,
        [0 for _ in terminal_names],
    ).solve()
    if result.status != "optimal":
        raise TerminalMappingInfeasible(
            "Mirror images admit no positive common terminal refinement"
        )

    rational_weights = tuple(Fraction(1) + value for value in result.solution)
    denominator = 1
    for value in rational_weights:
        denominator = lcm(denominator, value.denominator)
    integer_weights = [
        int(value * denominator) for value in rational_weights
    ]
    common_divisor = 0
    for value in integer_weights:
        common_divisor = gcd(common_divisor, value)
    if common_divisor > 1:
        integer_weights = [value // common_divisor for value in integer_weights]
    if any(value <= 0 for value in integer_weights):
        raise RuntimeError("Exact positive mirror refinement produced a nonpositive weight")

    used_names = set(terminal_names)
    substitution: Dict[str, Word] = {}
    for terminal_name, weight in zip(terminal_names, integer_weights, strict=True):
        if weight == 1:
            substitution[terminal_name] = (Literal(terminal_name),)
            continue
        refined: List[Literal] = []
        for index in range(weight):
            candidate = f"__MR_{terminal_name}_{index}"
            suffix = 0
            while candidate in used_names:
                suffix += 1
                candidate = f"__MR_{terminal_name}_{index}_{suffix}"
            used_names.add(candidate)
            refined.append(Literal(candidate))
        substitution[terminal_name] = tuple(refined)

    refined_environment = {
        variable: substitute_word(word, substitution)
        for variable, word in output.items()
    }
    for direct, mirrored in active_pairs:
        if len(refined_environment[direct]) != len(refined_environment[mirrored]):
            raise RuntimeError("Mirror refinement witness did not satisfy its equations")
    return refined_environment


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


_TerminalTransform = Tuple[bool, bool]
_TERMINAL_IDENTITY: _TerminalTransform = (False, False)
_TERMINAL_REVERSE: _TerminalTransform = (True, False)
_TERMINAL_MIRROR: _TerminalTransform = (False, True)
_TERMINAL_MIRROR_REVERSE: _TerminalTransform = (True, True)


def _compose_terminal_transforms(
    left: _TerminalTransform, right: _TerminalTransform
) -> _TerminalTransform:
    return (left[0] ^ right[0], left[1] ^ right[1])


def _terminal_transform_label(transform: _TerminalTransform) -> str:
    reverse, mirror = transform
    if reverse and mirror:
        return "mirror_reverse"
    if reverse:
        return "reverse"
    if mirror:
        return "mirror"
    return "identity"


def _terminal_relation_edges(
    system: TerminalContactSystem,
) -> Tuple[Tuple[str, str, _TerminalTransform], ...]:
    """Return the exact factor isometries already certified by the word case."""

    edges: List[Tuple[str, str, _TerminalTransform]] = [
        (
            relation.left_variable,
            relation.right_variable,
            (relation.reverse, relation.mirror),
        )
        for relation in system.template_relations
    ]
    for mapping in system.mappings:
        for left_ref, right_ref in mapping.pairs:
            left = system.terminal_contour[left_ref.segment_index]
            right = system.terminal_contour[right_ref.segment_index]
            left_orientation = (-1 if left.inverse else 1) * (
                1 if left_ref.forward else -1
            )
            right_orientation = (-1 if right.inverse else 1) * (
                1 if right_ref.forward else -1
            )
            edges.append(
                (
                    left.variable,
                    right.variable,
                    (
                        left_orientation != right_orientation,
                        mapping.relative_parity == -1,
                    ),
                )
            )
    return tuple(edges)


def _endpoint_swapping_fixed_atoms(
    system: TerminalContactSystem,
) -> Dict[str, str]:
    """Find terminal components fixed by a transform swapping their endpoints.

    A pure mirror self-identification fixes both endpoints and therefore forces
    a straight factor. Reverse and mirror+reverse self-identifications swap
    endpoints: they must instead be represented by two formal half-factors.
    """

    contour_variables = {literal.variable for literal in system.terminal_contour}
    adjacency: Dict[str, List[Tuple[str, _TerminalTransform]]] = defaultdict(list)
    for left, right, transform in _terminal_relation_edges(system):
        adjacency[left].append((right, transform))
        adjacency[right].append((left, transform))

    output: Dict[str, str] = {}
    visited: set[str] = set()
    for representative in sorted(contour_variables):
        if representative in visited:
            continue
        transforms: Dict[str, _TerminalTransform] = {
            representative: _TERMINAL_IDENTITY
        }
        symmetries = {_TERMINAL_IDENTITY}
        queue = deque((representative,))
        while queue:
            current = queue.popleft()
            visited.add(current)
            for target, relation in adjacency[current]:
                candidate = _compose_terminal_transforms(
                    relation, transforms[current]
                )
                previous = transforms.get(target)
                if previous is None:
                    transforms[target] = candidate
                    queue.append(target)
                else:
                    symmetries.add(
                        _compose_terminal_transforms(previous, candidate)
                    )

        # MIRROR fixes each point of the factor and is represented exactly by
        # a straight component. Endpoint-swapping stabilizers require an
        # explicit two-half word refinement instead.
        if _TERMINAL_MIRROR in symmetries:
            continue
        fixed_transform = None
        for candidate in (
            _TERMINAL_MIRROR_REVERSE,
            _TERMINAL_REVERSE,
        ):
            if candidate in symmetries:
                fixed_transform = candidate
                break
        if fixed_transform is None:
            continue
        label = _terminal_transform_label(fixed_transform)
        for variable in transforms:
            output[variable] = label
    return output


def _split_endpoint_swapping_atoms(
    environment: Mapping[str, Word],
    terminal_contour: Word,
    fixed_atoms: Mapping[str, str],
) -> Tuple[Dict[str, Word], Tuple[TerminalSmoothBoundary, ...]]:
    """Replace each fixed atom A by A_left A_right in every formal word."""

    used_names = {
        literal.variable for word in environment.values() for literal in word
    }
    substitution: Dict[str, Word] = {}
    for variable in sorted(fixed_atoms):
        halves = []
        for side in ("left", "right"):
            candidate = f"__INV_{variable}_{side}"
            suffix = 0
            while candidate in used_names:
                suffix += 1
                candidate = f"__INV_{variable}_{side}_{suffix}"
            used_names.add(candidate)
            halves.append(Literal(candidate))
        substitution[variable] = tuple(halves)

    refined_environment = {
        variable: substitute_word(word, substitution)
        for variable, word in environment.items()
    }

    boundaries = []
    refined_offset = 0
    for literal in terminal_contour:
        replacement = substitution.get(literal.variable)
        if replacement is None:
            refined_offset += 1
            continue
        if literal.inverse:
            replacement = inverse_word(replacement)
        boundaries.append(
            TerminalSmoothBoundary(
                boundary_index=refined_offset + 1,
                source_variable=literal.variable,
                transform=fixed_atoms[literal.variable],
            )
        )
        refined_offset += len(replacement)
    return refined_environment, tuple(boundaries)


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
    complete_environment = refine_mirror_compatible_terminal_environment(
        complete_environment,
        compiled.mirror_variables,
    )
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
    mirror_map = compiled.mirror_map()
    mirror_pairs = () if legacy_mirror_environment else compiled.mirror_variables

    def assemble(
        current_environment: Mapping[str, Word],
        forced_smooth_boundaries: Sequence[TerminalSmoothBoundary] = (),
    ) -> TerminalContactSystem:
        prototype_environment = {
            variable: current_environment[variable]
            for variable in compiled.atomic_variables
        }
        expanded_contour, refs = _expanded_contour_refs(
            compiled.atomic_variables, prototype_environment
        )
        prototype_sector_word: Word = ()
        if compiled.prototype_rotation_order > 1:
            sector_variable = compiled.prototype_sector_variable
            if sector_variable is None or sector_variable not in current_environment:
                raise TerminalMappingInfeasible(
                    "Intrinsic prototype rotation has no terminal sector word"
                )
            prototype_sector_word = current_environment[sector_variable]
            if not prototype_sector_word:
                raise TerminalMappingInfeasible(
                    "Intrinsic prototype rotation acquired an empty sector"
                )
            if (
                expanded_contour
                != prototype_sector_word * compiled.prototype_rotation_order
            ):
                raise TerminalMappingInfeasible(
                    "Terminal contour does not satisfy the intrinsic rotational period"
                )

        mappings: List[ContactMapping] = []
        for interface in compiled.interfaces:
            left_refs = _path_refs(interface.left_positive_word, refs)
            right_same_direction_word = inverse_word(
                interface.right_positive_word
            )
            right_refs = _path_refs(right_same_direction_word, refs)
            transformed_right_word = right_same_direction_word
            if interface.relative_parity == -1:
                if not mirror_map:
                    raise TerminalMappingInfeasible(
                        f"Reflected interface {interface.name} has no mirror variables"
                    )
                transformed_right_word = mirror_word(
                    transformed_right_word, mirror_map
                )

            left_expanded = substitute_word(
                interface.left_positive_word, current_environment
            )
            right_expanded = substitute_word(
                transformed_right_word, current_environment
            )
            if left_expanded != right_expanded:
                raise TerminalMappingInfeasible(
                    f"Terminal environment does not satisfy {interface.name}"
                )
            if (
                len(left_refs) != len(right_refs)
                or len(left_refs) != len(left_expanded)
            ):
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
        for direct, mirrored in mirror_pairs:
            direct_word = current_environment[direct]
            mirrored_word = current_environment[mirrored]
            if len(direct_word) != len(mirrored_word):
                raise TerminalMappingInfeasible(
                    f"Mirror images of {direct} have different refinement lengths"
                )
            for pair_index, (left, right) in enumerate(
                zip(direct_word, mirrored_word)
            ):
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
            forced_smooth_boundaries=tuple(forced_smooth_boundaries),
            prototype_rotation_order=compiled.prototype_rotation_order,
            prototype_sector_word=prototype_sector_word,
        )

    terminal_system = assemble(normalized_environment)
    fixed_atoms = _endpoint_swapping_fixed_atoms(terminal_system)
    if not fixed_atoms:
        return terminal_system

    refined_environment, forced_smooth_boundaries = (
        _split_endpoint_swapping_atoms(
            normalized_environment,
            terminal_system.terminal_contour,
            fixed_atoms,
        )
    )
    terminal_system = assemble(
        refined_environment,
        forced_smooth_boundaries,
    )
    remaining = _endpoint_swapping_fixed_atoms(terminal_system)
    if remaining:
        raise TerminalMappingInfeasible(
            "Endpoint-swapping terminal involution survived exact half-factor refinement: "
            + ", ".join(sorted(remaining))
        )
    return terminal_system


def build_contact_mappings(
    compiled: CompiledWordCase, environment: Mapping[str, Word]
) -> Tuple[Word, Tuple[ContactMapping, ...]]:
    system = build_terminal_contact_system(compiled, environment)
    return system.terminal_contour, system.mappings
