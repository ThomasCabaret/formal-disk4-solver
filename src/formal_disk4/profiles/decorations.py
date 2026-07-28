from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Dict, Iterable, Mapping, Sequence, Tuple

import numpy as np
from scipy.optimize import linprog

from formal_disk4.constraints.rational_lp import maximize_free_variables
from formal_disk4.enumeration.weak_orders import Placement
from formal_disk4.maps.base import Occurrence, PlanarMap
from formal_disk4.words.algebra import Literal, Word, substitute_word
from formal_disk4.words.compile import CompiledWordCase, ContactMapping, DirectedSegmentRef

from .exact_linear import (
    ExactLinearInfeasible,
    ExactLinearSolution,
    LinearExpression,
    solve_exact_linear_system,
)


class DecorationInfeasible(ValueError):
    def __init__(self, stage: str, reason: str) -> None:
        super().__init__(f"{stage}: {reason}")
        self.stage = stage
        self.reason = reason


@dataclass(frozen=True, order=True)
class TemplateTransform:
    reverse: bool = False
    mirror: bool = False

    def compose(self, other: "TemplateTransform") -> "TemplateTransform":
        return TemplateTransform(self.reverse ^ other.reverse, self.mirror ^ other.mirror)

    @property
    def turn_sign(self) -> int:
        return -1 if self.reverse ^ self.mirror else 1

    @property
    def label(self) -> str:
        if self.reverse and self.mirror:
            return "mirror_reverse"
        if self.reverse:
            return "reverse"
        if self.mirror:
            return "mirror"
        return "identity"


IDENTITY = TemplateTransform()
REVERSE = TemplateTransform(reverse=True)
MIRROR = TemplateTransform(mirror=True)
MIRROR_REVERSE = TemplateTransform(reverse=True, mirror=True)


class _SignedUnionFind:
    def __init__(self, names: Iterable[int]) -> None:
        self.parent: Dict[int, int] = {}
        self.sign: Dict[int, int] = {}
        self.zero_roots: set[int] = set()
        for name in names:
            self.parent[name] = name
            self.sign[name] = 1

    def find(self, name: int) -> Tuple[int, int]:
        parent = self.parent[name]
        if parent == name:
            return name, 1
        root, parent_sign = self.find(parent)
        value_sign = self.sign[name] * parent_sign
        self.parent[name] = root
        self.sign[name] = value_sign
        return root, value_sign

    def union(self, left: int, right: int, relation_sign: int) -> None:
        left_root, left_sign = self.find(left)
        right_root, right_sign = self.find(right)
        if left_root == right_root:
            if left_sign != relation_sign * right_sign:
                self.zero_roots.add(left_root)
            return
        root_sign = left_sign * relation_sign * right_sign
        left_zero = left_root in self.zero_roots
        right_zero = right_root in self.zero_roots
        self.parent[left_root] = right_root
        self.sign[left_root] = root_sign
        self.zero_roots.discard(left_root)
        if left_zero or right_zero:
            self.zero_roots.add(right_root)

    def mark_zero(self, name: int) -> None:
        root, _ = self.find(name)
        self.zero_roots.add(root)

    def normalize(self) -> None:
        self.zero_roots = {self.find(root)[0] for root in self.zero_roots}


@dataclass(frozen=True)
class AngleEquationRecord:
    kind: str
    terms: Tuple[Tuple[int, int], ...]
    rhs_pi: Fraction
    sources: Tuple[str, ...]
    relation: str


@dataclass(frozen=True)
class AngularEquationRecord:
    kind: str
    terms: Tuple[Tuple[str, Fraction], ...]
    rhs_pi: Fraction
    sources: Tuple[str, ...]
    relation: str


@dataclass(frozen=True)
class JointAngularFeasibility:
    feasible: bool
    status: str
    strict_margin: Fraction
    point_angle_variables: Tuple[str, ...]
    curve_turn_variables: Tuple[str, ...]
    length_variables: Tuple[str, ...]
    equations: Tuple[AngularEquationRecord, ...]
    exact_solution: ExactLinearSolution
    witness: Tuple[Tuple[str, Fraction], ...]

    def witness_map(self) -> Dict[str, Fraction]:
        return dict(self.witness)


@dataclass(frozen=True)
class PointClassRecord:
    class_id: str
    representative_boundary: int
    members: Tuple[Tuple[int, int], ...]
    forced_zero: bool
    turn_pi: float | None
    representative_angle_expression: LinearExpression
    representative_turn_expression: LinearExpression


@dataclass(frozen=True)
class PointRecord:
    boundary_index: int
    source: str
    source_block_index: int | None
    occurrences: Tuple[str, ...]
    class_id: str
    class_sign: int
    fixed_zero_turn: bool
    prototype_turn_pi: float | None
    prototype_angle_pi: float | None
    prototype_angle_expression: LinearExpression
    prototype_turn_expression: LinearExpression
    occurrence_angles_pi: Tuple[Tuple[str, float], ...]
    occurrence_angle_expressions: Tuple[Tuple[str, LinearExpression], ...]
    roles: Tuple[str, ...]


@dataclass(frozen=True)
class TemplateRelationRecord:
    left_variable: str
    right_variable: str
    transform: str
    interface: str
    pair_index: int


@dataclass(frozen=True)
class CurveComponentRecord:
    component_id: str
    representative: str
    variables: Tuple[str, ...]
    variable_transforms: Tuple[Tuple[str, str], ...]
    self_symmetries: Tuple[str, ...]
    mode: str
    curve_type: str
    forced_straight: bool
    circular: bool
    circle_class: str | None
    length_parameter: str
    search_witness_normalized_length: float | None
    disk_normalized_length: LinearExpression
    turn_parameter: str
    curve_turn_pi: LinearExpression
    curve_turn_pi_witness: Fraction
    disk_normalized_turn_pi: LinearExpression | None


@dataclass(frozen=True)
class OuterArcRecord:
    name: str
    piece: str
    terminal_word: Word
    length_parameter: str
    length_expression: Tuple[Tuple[str, int], ...]
    turn_parameter: str
    disk_normalized_length: LinearExpression
    turn_pi: LinearExpression


@dataclass(frozen=True)
class DecorationBundle:
    points: Tuple[PointRecord, ...]
    point_classes: Tuple[PointClassRecord, ...]
    angle_equations: Tuple[AngleEquationRecord, ...]
    exact_angle_solution: ExactLinearSolution
    joint_angular_feasibility: JointAngularFeasibility
    curve_components: Tuple[CurveComponentRecord, ...]
    exact_length_solution: ExactLinearSolution
    template_relations: Tuple[TemplateRelationRecord, ...]
    outer_arcs: Tuple[OuterArcRecord, ...]
    angle_margin: float
    terminal_length_margin: float
    formal_constraints: Tuple[Dict[str, object], ...]


def _effective_orientation(literal: Literal, directed: DirectedSegmentRef) -> int:
    literal_sign = -1 if literal.inverse else 1
    directed_sign = 1 if directed.forward else -1
    return literal_sign * directed_sign


def _directed_boundaries(ref: DirectedSegmentRef, segment_count: int) -> Tuple[int, int]:
    if ref.forward:
        return ref.segment_index, (ref.segment_index + 1) % segment_count
    return (ref.segment_index + 1) % segment_count, ref.segment_index


def _terminal_boundary_sources(
    planar_map: PlanarMap,
    placement: Placement,
    compiled: CompiledWordCase,
    environment: Mapping[str, Word],
    occurrence_names: Sequence[str],
) -> Tuple[Tuple[str, int | None, Tuple[str, ...], Tuple[str, ...]], ...]:
    sources: list[Tuple[str, int | None, Tuple[str, ...], Tuple[str, ...]]] = []
    vertex_kinds = {vertex.name: vertex.kind for vertex in planar_map.vertices}
    for atomic_index, variable in enumerate(compiled.atomic_variables):
        expansion = environment[variable]
        if not expansion:
            raise DecorationInfeasible("point_decorations", f"{variable} has an empty image")
        names = tuple(occurrence_names[item] for item in placement.blocks[atomic_index])
        vertices = {name.split(":", 1)[1] for name in names}
        roles = []
        if any(vertex_kinds.get(vertex) == "outer" for vertex in vertices):
            roles.append("outer-map-vertex-occurrence")
        if any(vertex_kinds.get(vertex) == "interior" for vertex in vertices):
            roles.append("interior-map-vertex-occurrence")
        sources.append(("map_vertex", atomic_index, names, tuple(roles)))
        for _ in expansion[1:]:
            sources.append(("solver_split", None, (), ("solver-introduced-boundary",)))
    return tuple(sources)


def _build_angle_decorations(
    planar_map: PlanarMap,
    occurrence_names: Sequence[str],
    placement: Placement,
    terminal_contour: Word,
    mappings: Sequence[ContactMapping],
    boundary_sources: Sequence[Tuple[str, int | None, Tuple[str, ...], Tuple[str, ...]]],
    tolerance: float,
) -> Tuple[
    Tuple[PointRecord, ...],
    Tuple[PointClassRecord, ...],
    float,
    Tuple[AngleEquationRecord, ...],
    ExactLinearSolution,
]:
    segment_count = len(terminal_contour)
    if len(boundary_sources) != segment_count:
        raise DecorationInfeasible("point_decorations", "terminal boundary/source count mismatch")

    union = _SignedUnionFind(range(segment_count))
    equation_records: list[AngleEquationRecord] = []
    equation_record_index: Dict[Tuple[object, ...], int] = {}
    exact_equations: list[Tuple[Dict[str, Fraction], Fraction]] = []
    angle_names = tuple(f"alpha_B{index}" for index in range(segment_count))

    def add_equation(
        kind: str,
        terms: Mapping[int, int],
        rhs: Fraction,
        source: str,
        relation: str,
    ) -> None:
        compact = tuple(sorted((index, coefficient) for index, coefficient in terms.items() if coefficient))
        if not compact and rhs == 0:
            return
        key = (kind, compact, rhs, relation)
        if key in equation_record_index:
            record_index = equation_record_index[key]
            previous = equation_records[record_index]
            equation_records[record_index] = AngleEquationRecord(
                previous.kind,
                previous.terms,
                previous.rhs_pi,
                previous.sources + (source,),
                previous.relation,
            )
            return
        equation_record_index[key] = len(equation_records)
        equation_records.append(
            AngleEquationRecord(kind, compact, rhs, (source,), relation)
        )
        exact_equations.append(
            ({angle_names[index]: Fraction(coefficient) for index, coefficient in compact}, rhs)
        )

    for mapping in mappings:
        # A contact mapping constrains only points strictly inside the mapped
        # interval.  At either endpoint, the mapping contains only the tangent
        # of the shared interface and says nothing about the other incident
        # contour side, so it cannot determine the complete corner angle.
        #
        # This distinction is essential at map vertices.  For example, in the
        # three-sector disk, the two outer angles of one prototype need only be
        # complementary; the radial-interface mappings do not make them equal.
        for internal_index in range(1, len(mapping.pairs)):
            previous_left, previous_right = mapping.pairs[internal_index - 1]
            next_left, next_right = mapping.pairs[internal_index]

            _left_start, left_boundary = _directed_boundaries(
                previous_left, segment_count
            )
            next_left_boundary, _left_end = _directed_boundaries(
                next_left, segment_count
            )
            _right_start, right_boundary = _directed_boundaries(
                previous_right, segment_count
            )
            next_right_boundary, _right_end = _directed_boundaries(
                next_right, segment_count
            )
            if left_boundary != next_left_boundary:
                raise DecorationInfeasible(
                    "angle_classes",
                    f"non-contiguous left mapping at {mapping.interface_name}:"
                    f"boundary{internal_index}",
                )
            if right_boundary != next_right_boundary:
                raise DecorationInfeasible(
                    "angle_classes",
                    f"non-contiguous right mapping at {mapping.interface_name}:"
                    f"boundary{internal_index}",
                )

            left_orientation = 1 if previous_left.forward else -1
            right_orientation = 1 if previous_right.forward else -1
            relation_sign = (
                mapping.relative_parity * left_orientation * right_orientation
            )
            union.union(left_boundary, right_boundary, relation_sign)
            relation_terms: Dict[int, int] = defaultdict(int)
            relation_terms[left_boundary] += 1
            relation_terms[right_boundary] += -1 if relation_sign == 1 else 1
            source = f"{mapping.interface_name}:internal-boundary{internal_index}"
            if relation_sign == 1:
                add_equation(
                    "mapping_internal_turn_equality",
                    relation_terms,
                    Fraction(0),
                    source,
                    "equal_signed_turns_at_internal_mapped_point",
                )
            else:
                add_equation(
                    "mapping_internal_turn_opposition",
                    relation_terms,
                    Fraction(2),
                    source,
                    "opposite_signed_turns_at_internal_mapped_point",
                )
    union.normalize()

    occurrence_index = {
        occurrence: index for index, occurrence in enumerate(planar_map.occurrences())
    }
    block_boundary = {
        int(source[1]): boundary_index
        for boundary_index, source in enumerate(boundary_sources)
        if source[0] == "map_vertex" and source[1] is not None
    }

    for vertex in planar_map.vertices:
        terms: Dict[int, int] = defaultdict(int)
        for piece in vertex.incident_pieces:
            occurrence_id = occurrence_index[Occurrence(piece, vertex.name)]
            block_index = placement.positions[occurrence_id]
            boundary_index = block_boundary[block_index]
            # These are positive polygonal interior angles.  Reflection of a
            # congruent copy preserves them; no orientation sign belongs in
            # the physical vertex-sum equation.
            terms[boundary_index] += 1
        rhs = vertex.required_solid_angle_sum_pi
        nonzero_terms = {index: coefficient for index, coefficient in terms.items() if coefficient}
        if vertex.kind == "outer":
            relation = "incident_piece_angles_sum_to_pi"
        elif vertex.kind == "interior":
            relation = "incident_piece_angles_sum_to_full_turn"
        else:
            relation = "physical_vertex_angle_sum"
        add_equation(
            "physical_vertex_angle_sum",
            nonzero_terms,
            rhs,
            vertex.name,
            relation,
        )

    try:
        exact_solution = solve_exact_linear_system(angle_names, exact_equations)
    except ExactLinearInfeasible as error:
        raise DecorationInfeasible("angle_classes", str(error)) from error

    variable_count = segment_count + 1
    epsilon_index = segment_count
    objective = np.zeros(variable_count)
    objective[epsilon_index] = -1.0
    a_eq = []
    b_eq = []
    for coefficients, rhs in exact_equations:
        row = [0.0] * variable_count
        for name, coefficient in coefficients.items():
            row[angle_names.index(name)] = float(coefficient)
        a_eq.append(row)
        b_eq.append(float(rhs))
    a_ub = []
    b_ub = []
    for index in range(segment_count):
        upper = [0.0] * variable_count
        upper[index] = 1.0
        upper[epsilon_index] = 1.0
        a_ub.append(upper)
        b_ub.append(2.0)
        lower = [0.0] * variable_count
        lower[index] = -1.0
        lower[epsilon_index] = 1.0
        a_ub.append(lower)
        b_ub.append(0.0)
    result = linprog(
        objective,
        A_ub=np.asarray(a_ub),
        b_ub=np.asarray(b_ub),
        A_eq=np.asarray(a_eq) if a_eq else None,
        b_eq=np.asarray(b_eq) if b_eq else None,
        bounds=[(None, None)] * segment_count + [(0.0, None)],
        method="highs",
    )
    if not result.success or result.x is None:
        raise DecorationInfeasible("angle_classes", f"infeasible terminal angle system ({result.status})")
    margin = float(result.x[epsilon_index])
    if margin <= tolerance:
        raise DecorationInfeasible("angle_classes", "terminal angle system has zero strict margin")

    exact_map = exact_solution.expression_map()
    alpha_values = tuple(float(result.x[index]) for index in range(segment_count))
    roots = sorted({union.find(index)[0] for index in range(segment_count)})
    class_ids = {root: f"A{index}" for index, root in enumerate(roots)}
    members: Dict[int, list[Tuple[int, int]]] = defaultdict(list)
    points: list[PointRecord] = []
    for boundary_index, source in enumerate(boundary_sources):
        root, class_sign = union.find(boundary_index)
        members[root].append((boundary_index, class_sign))
        forced_zero = root in union.zero_roots
        prototype_angle = alpha_values[boundary_index]
        prototype_turn = 1.0 - prototype_angle
        prototype_expression = exact_map[angle_names[boundary_index]]
        occurrence_angles = []
        occurrence_expressions = []
        for occurrence_name in source[2]:
            # Isometries preserve the positive solid interior angle, including
            # reflected isometries.
            occurrence_angles.append((occurrence_name, prototype_angle))
            occurrence_expressions.append((occurrence_name, prototype_expression))
        points.append(
            PointRecord(
                boundary_index=boundary_index,
                source=source[0],
                source_block_index=source[1],
                occurrences=source[2],
                class_id="0" if forced_zero else class_ids[root],
                class_sign=0 if forced_zero else class_sign,
                fixed_zero_turn=forced_zero,
                prototype_turn_pi=prototype_turn,
                prototype_angle_pi=prototype_angle,
                prototype_angle_expression=prototype_expression,
                prototype_turn_expression=(LinearExpression.value(1) - prototype_expression).normalized(),
                occurrence_angles_pi=tuple(occurrence_angles),
                occurrence_angle_expressions=tuple(occurrence_expressions),
                roles=source[3],
            )
        )

    classes = tuple(
        PointClassRecord(
            class_id="0" if root in union.zero_roots else class_ids[root],
            representative_boundary=root,
            members=tuple(sorted(members[root])),
            forced_zero=root in union.zero_roots,
            turn_pi=1.0 - alpha_values[root],
            representative_angle_expression=exact_map[angle_names[root]],
            representative_turn_expression=(
                LinearExpression.value(1) - exact_map[angle_names[root]]
            ).normalized(),
        )
        for root in roots
    )
    return tuple(points), classes, margin, tuple(equation_records), exact_solution


def _template_relations(
    terminal_contour: Word, mappings: Sequence[ContactMapping]
) -> Tuple[Tuple[str, str, TemplateTransform, str, int], ...]:
    output = []
    for mapping in mappings:
        for pair_index, (left_ref, right_ref) in enumerate(mapping.pairs):
            left = terminal_contour[left_ref.segment_index]
            right = terminal_contour[right_ref.segment_index]
            reverse = _effective_orientation(left, left_ref) != _effective_orientation(right, right_ref)
            transform = TemplateTransform(reverse=reverse, mirror=mapping.relative_parity == -1)
            output.append((left.variable, right.variable, transform, mapping.interface_name, pair_index))
    return tuple(output)


def _curve_components(
    terminal_contour: Word,
    relations: Sequence[Tuple[str, str, TemplateTransform, str, int]],
) -> Tuple[
    Tuple[Tuple[str, Tuple[str, ...], Dict[str, TemplateTransform], Tuple[TemplateTransform, ...], str], ...],
    Dict[str, int],
]:
    variables = sorted({item.variable for item in terminal_contour})
    adjacency: Dict[str, list[Tuple[str, TemplateTransform]]] = defaultdict(list)
    for left, right, transform, _interface, _pair in relations:
        adjacency[left].append((right, transform))
        adjacency[right].append((left, transform))

    components = []
    component_by_variable: Dict[str, int] = {}
    visited: set[str] = set()
    for representative in variables:
        if representative in visited:
            continue
        transforms: Dict[str, TemplateTransform] = {representative: IDENTITY}
        symmetries = {IDENTITY}
        queue = deque([representative])
        while queue:
            current = queue.popleft()
            visited.add(current)
            for target, relation_transform in adjacency[current]:
                candidate = relation_transform.compose(transforms[current])
                if target not in transforms:
                    transforms[target] = candidate
                    queue.append(target)
                else:
                    symmetries.add(transforms[target].compose(candidate))
        members = tuple(sorted(transforms))
        if MIRROR in symmetries:
            mode = "straight"
        elif REVERSE in symmetries:
            mode = "half_turn"
        elif MIRROR_REVERSE in symmetries:
            mode = "endpoint_swapping_reflection"
        else:
            mode = "free"
        component_index = len(components)
        for variable in members:
            component_by_variable[variable] = component_index
        components.append((representative, members, transforms, tuple(sorted(symmetries)), mode))
    return tuple(components), component_by_variable


def _terminal_lengths(
    compiled: CompiledWordCase,
    environment: Mapping[str, Word],
    placement: Placement,
    components: Sequence[Tuple[str, Tuple[str, ...], Dict[str, TemplateTransform], Tuple[TemplateTransform, ...], str]],
    component_by_variable: Mapping[str, int],
    tolerance: float,
) -> Tuple[Tuple[float, ...], float, ExactLinearSolution]:
    count = len(components)
    if count == 0:
        raise DecorationInfeasible("terminal_lengths", "terminal contour has no curve component")

    parameter_names = tuple(f"L_C{index}" for index in range(count))
    atomic_counts: list[Counter[int]] = []
    for variable in compiled.atomic_variables:
        atomic_counts.append(
            Counter(component_by_variable[literal.variable] for literal in environment[variable])
        )

    exact_equations: list[Tuple[Dict[str, Fraction], Fraction]] = []
    for row in placement.length_rows:
        coefficients: Dict[str, Fraction] = defaultdict(Fraction)
        for atomic_index, atomic_coefficient in enumerate(row):
            if not atomic_coefficient:
                continue
            for component_index, multiplicity in atomic_counts[atomic_index].items():
                coefficients[parameter_names[component_index]] += Fraction(
                    int(atomic_coefficient) * int(multiplicity)
                )
        compact = {name: value for name, value in coefficients.items() if value}
        if compact:
            exact_equations.append((compact, Fraction(0)))

    expanded_outer = tuple(
        substitute_word(arc.positive_word, environment) for arc in compiled.outer_arcs
    )
    normalization: Dict[str, Fraction] = defaultdict(Fraction)
    if expanded_outer:
        for word in expanded_outer:
            for literal in word:
                normalization[parameter_names[component_by_variable[literal.variable]]] += 1
    else:
        for counts in atomic_counts:
            for component_index, multiplicity in counts.items():
                normalization[parameter_names[component_index]] += multiplicity
    if not normalization:
        raise DecorationInfeasible("terminal_lengths", "no length normalization can be constructed")
    exact_equations.append((dict(normalization), Fraction(1)))

    try:
        exact_solution = solve_exact_linear_system(parameter_names, exact_equations)
    except ExactLinearInfeasible as error:
        raise DecorationInfeasible("terminal_lengths", str(error)) from error

    variable_count = count + 1
    epsilon_index = count
    objective = np.zeros(variable_count)
    objective[epsilon_index] = -1.0
    a_eq = []
    b_eq = []
    for coefficients, rhs in exact_equations:
        row = [0.0] * variable_count
        for name, coefficient in coefficients.items():
            row[parameter_names.index(name)] = float(coefficient)
        a_eq.append(row)
        b_eq.append(float(rhs))
    a_ub = []
    b_ub = []
    for index in range(count):
        row = [0.0] * variable_count
        row[index] = -1.0
        row[epsilon_index] = 1.0
        a_ub.append(row)
        b_ub.append(0.0)
    result = linprog(
        objective,
        A_ub=np.asarray(a_ub),
        b_ub=np.asarray(b_ub),
        A_eq=np.asarray(a_eq),
        b_eq=np.asarray(b_eq),
        bounds=[(0.0, None)] * count + [(0.0, None)],
        method="highs",
    )
    if not result.success or result.x is None:
        raise DecorationInfeasible(
            "terminal_lengths", f"infeasible disk-normalized terminal length system ({result.status})"
        )
    margin = float(result.x[epsilon_index])
    if margin <= tolerance:
        raise DecorationInfeasible(
            "terminal_lengths", "disk-normalized terminal curve lengths have zero strict margin"
        )
    return tuple(float(item) for item in result.x[:count]), margin, exact_solution



def _solution_equalities(
    solution: ExactLinearSolution,
) -> Tuple[Tuple[Dict[str, Fraction], Fraction], ...]:
    """Reconstruct an equality basis from an exact affine solution."""

    equations: list[Tuple[Dict[str, Fraction], Fraction]] = []
    for name, expression in solution.expressions:
        normalized = expression.normalized()
        if (
            normalized.constant == 0
            and normalized.terms == ((name, Fraction(1)),)
        ):
            continue
        coefficients: Dict[str, Fraction] = defaultdict(Fraction)
        coefficients[name] += 1
        for parameter, coefficient in normalized.terms:
            coefficients[parameter] -= coefficient
        equations.append(
            (
                {key: value for key, value in coefficients.items() if value},
                normalized.constant,
            )
        )
    return tuple(equations)


def _build_joint_angular_feasibility(
    terminal_contour: Word,
    components: Sequence[
        Tuple[
            str,
            Tuple[str, ...],
            Dict[str, TemplateTransform],
            Tuple[TemplateTransform, ...],
            str,
        ]
    ],
    component_by_variable: Mapping[str, int],
    exact_angle_solution: ExactLinearSolution,
    exact_length_solution: ExactLinearSolution,
    expanded_outer: Sequence[Tuple[str, str, Word]],
    piece_orientation_signs: Mapping[str, int],
    tile_count: int = 1,
    piecewise_c2_boundary: bool = False,
) -> JointAngularFeasibility:
    """Solve all inexpensive point/curve turning constraints simultaneously.

    Point variables are prototype interior angles ``alpha_Bi`` in units of pi,
    with strict bounds 0 < alpha < 2.  Their signed corner turn is
    ``tau_Bi = 1 - alpha_Bi`` and therefore lies in (-1, 1).

    Every curve-template component has an unbounded signed total turn ``K_Ci``.
    Reversing a curve or reflecting it changes the sign.  Straight templates
    and self-identifications that reverse signed turn force K_Ci = 0.  Under
    the disk-circumference normalization, an occurrence on the positively
    oriented outer circle satisfies signed_turn = 2 * length.
    """

    alpha_names = tuple(exact_angle_solution.variable_order)
    kappa_names = tuple(f"K_C{index}" for index in range(len(components)))
    length_names = tuple(exact_length_solution.variable_order)
    variable_names = alpha_names + kappa_names + length_names

    equations: list[Tuple[Dict[str, Fraction], Fraction]] = []
    records: list[AngularEquationRecord] = []
    seen: set[Tuple[Tuple[Tuple[str, Fraction], ...], Fraction]] = set()

    def add_equation(
        kind: str,
        coefficients: Mapping[str, int | Fraction],
        rhs: int | Fraction,
        source: str,
        relation: str,
    ) -> None:
        compact = tuple(
            sorted(
                (name, Fraction(value))
                for name, value in coefficients.items()
                if Fraction(value)
            )
        )
        rhs_fraction = Fraction(rhs)
        key = (compact, rhs_fraction)
        if not compact:
            if rhs_fraction:
                raise DecorationInfeasible(
                    "joint_angular_feasibility",
                    f"inconsistent angular equation from {source}",
                )
            return
        if key in seen:
            return
        seen.add(key)
        mapping = dict(compact)
        equations.append((mapping, rhs_fraction))
        records.append(
            AngularEquationRecord(
                kind=kind,
                terms=compact,
                rhs_pi=rhs_fraction,
                sources=(source,),
                relation=relation,
            )
        )

    for index, (coefficients, rhs) in enumerate(
        _solution_equalities(exact_angle_solution)
    ):
        add_equation(
            "point_angle_class_equation",
            coefficients,
            rhs,
            f"point-angle-basis:{index}",
            "existing point-angle equalities",
        )

    for index, (coefficients, rhs) in enumerate(
        _solution_equalities(exact_length_solution)
    ):
        add_equation(
            "curve_length_equation",
            coefficients,
            rhs,
            f"curve-length-basis:{index}",
            "existing normalized curve-length equalities",
        )

    def occurrence_turn_sign(literal: Literal) -> int:
        component_index = component_by_variable[literal.variable]
        transforms = components[component_index][2]
        template_sign = transforms[literal.variable].turn_sign
        traversal_sign = -1 if literal.inverse else 1
        return traversal_sign * template_sign

    for component_index, component in enumerate(components):
        _representative, _members, _transforms, symmetries, mode = component
        if mode == "straight" or any(symmetry.turn_sign == -1 for symmetry in symmetries):
            add_equation(
                "curve_turn_forced_zero",
                {kappa_names[component_index]: 1},
                0,
                f"curve-component:C{component_index}",
                "self-identification reverses signed curve turn",
            )

    for outer_name, piece, word in expanded_outer:
        copy_parity = int(piece_orientation_signs[piece])
        for occurrence_index, literal in enumerate(word):
            component_index = component_by_variable[literal.variable]
            physical_turn_sign = copy_parity * occurrence_turn_sign(literal)
            add_equation(
                "outer_circle_curve_turn",
                {
                    kappa_names[component_index]: physical_turn_sign,
                    length_names[component_index]: -2,
                },
                0,
                f"{outer_name}:segment{occurrence_index}",
                "positive disk-boundary traversal has turn_pi = 2 * normalized_length",
            )

    if piecewise_c2_boundary:
        smooth_turn_coefficients: Dict[str, Fraction] = defaultdict(Fraction)
        for literal in terminal_contour:
            component_index = component_by_variable[literal.variable]
            smooth_turn_coefficients[kappa_names[component_index]] += occurrence_turn_sign(literal)
        add_equation(
            "prototype_smooth_turn_balance",
            smooth_turn_coefficients,
            Fraction(2, tile_count),
            "terminal-contour",
            "internal smooth-curvature integrals cancel across copies, leaving the disk turn",
        )

        point_turn_coefficients: Dict[str, Fraction] = defaultdict(Fraction)
        for alpha_name in alpha_names:
            point_turn_coefficients[alpha_name] -= 1
        add_equation(
            "prototype_point_turn_balance",
            point_turn_coefficients,
            Fraction(2) - Fraction(2, tile_count) - len(alpha_names),
            "terminal-contour",
            "corner turns provide the remainder of the full contour winding",
        )
    else:
        total_turn_coefficients: Dict[str, Fraction] = defaultdict(Fraction)
        for literal in terminal_contour:
            component_index = component_by_variable[literal.variable]
            total_turn_coefficients[kappa_names[component_index]] += occurrence_turn_sign(literal)
        for alpha_name in alpha_names:
            total_turn_coefficients[alpha_name] -= 1
        add_equation(
            "prototype_total_turn",
            total_turn_coefficients,
            Fraction(2 - len(terminal_contour)),
            "terminal-contour",
            "sum(curve_turns) + sum(1 - interior_angle_pi) = 2",
        )

    try:
        exact_solution = solve_exact_linear_system(variable_names, equations)
    except ExactLinearInfeasible as error:
        raise DecorationInfeasible("joint_angular_feasibility", str(error)) from error

    # Eliminate all equalities first.  The exact simplex then sees only the
    # remaining free parameters plus the strict margin, which is substantially
    # smaller than the original alpha/kappa/length system.
    exact_map = exact_solution.expression_map()
    free_names = tuple(exact_solution.free_parameters)
    delta_name = "angular_strict_margin"
    lp_names = free_names + (delta_name,)
    index = {name: position for position, name in enumerate(lp_names)}
    inequalities: list[Tuple[list[Fraction], Fraction]] = []

    def expression_row(
        expression: LinearExpression,
        *,
        scale: int | Fraction = 1,
        delta: int | Fraction = 0,
    ) -> Tuple[list[Fraction], Fraction]:
        scaled = expression.scale(scale).normalized()
        row = [Fraction(0) for _ in lp_names]
        for name, coefficient in scaled.terms:
            row[index[name]] += coefficient
        row[index[delta_name]] += Fraction(delta)
        return row, scaled.constant

    # alpha + delta <= 2 and -alpha + delta <= 0.
    for name in alpha_names:
        row_values, constant = expression_row(exact_map[name], delta=1)
        inequalities.append((row_values, Fraction(2) - constant))
        row_values, constant = expression_row(exact_map[name], scale=-1, delta=1)
        inequalities.append((row_values, -constant))

    # -length + delta <= 0.
    for name in length_names:
        row_values, constant = expression_row(exact_map[name], scale=-1, delta=1)
        inequalities.append((row_values, -constant))

    delta_lower = [Fraction(0) for _ in lp_names]
    delta_lower[index[delta_name]] = Fraction(-1)
    inequalities.append((delta_lower, Fraction(0)))
    delta_upper = [Fraction(0) for _ in lp_names]
    delta_upper[index[delta_name]] = Fraction(1)
    inequalities.append((delta_upper, Fraction(1)))
    objective = [Fraction(0) for _ in lp_names]
    objective[index[delta_name]] = Fraction(1)
    result = maximize_free_variables(inequalities, objective)
    if result.status == "infeasible":
        raise DecorationInfeasible(
            "joint_angular_feasibility",
            "point turns, curve turns, circular arcs, lengths, and total winding are inconsistent",
        )
    if result.status != "optimal" or result.optimum is None:
        raise DecorationInfeasible(
            "joint_angular_feasibility",
            f"unexpected exact angular LP status {result.status}",
        )
    if result.optimum <= 0:
        raise DecorationInfeasible(
            "joint_angular_feasibility",
            "the angular system is feasible only at a forbidden point-angle or zero-length boundary",
        )

    free_witness = {
        name: result.solution[index[name]] for name in free_names
    }

    def evaluate(expression: LinearExpression) -> Fraction:
        normalized = expression.normalized()
        return normalized.constant + sum(
            coefficient * free_witness[name]
            for name, coefficient in normalized.terms
        )

    witness = tuple(
        (name, evaluate(exact_map[name])) for name in variable_names
    )
    return JointAngularFeasibility(
        feasible=True,
        status="feasible_with_strict_exact_margin",
        strict_margin=result.optimum,
        point_angle_variables=alpha_names,
        curve_turn_variables=kappa_names,
        length_variables=length_names,
        equations=tuple(records),
        exact_solution=exact_solution,
        witness=witness,
    )


def build_decorations(
    planar_map: PlanarMap,
    occurrence_names: Sequence[str],
    placement: Placement,
    compiled: CompiledWordCase,
    environment: Mapping[str, Word],
    terminal_contour: Word,
    mappings: Sequence[ContactMapping],
    tolerance: float = 1e-9,
) -> DecorationBundle:
    boundary_sources = _terminal_boundary_sources(
        planar_map, placement, compiled, environment, occurrence_names
    )
    points, point_classes, angle_margin, angle_equations, exact_angle_solution = _build_angle_decorations(
        planar_map,
        occurrence_names,
        placement,
        terminal_contour,
        mappings,
        boundary_sources,
        tolerance,
    )

    raw_relations = _template_relations(terminal_contour, mappings)
    components, component_by_variable = _curve_components(terminal_contour, raw_relations)
    component_lengths, terminal_length_margin, exact_length_solution = _terminal_lengths(
        compiled,
        environment,
        placement,
        components,
        component_by_variable,
        tolerance,
    )

    expanded_outer = tuple(
        (arc.name, arc.piece, substitute_word(arc.positive_word, environment))
        for arc in compiled.outer_arcs
    )
    circular_variables = {
        literal.variable
        for _name, _piece, word in expanded_outer
        for literal in word
    }
    circular_components = {
        component_by_variable[variable] for variable in circular_variables
    }

    joint_angular = _build_joint_angular_feasibility(
        terminal_contour=terminal_contour,
        components=components,
        component_by_variable=component_by_variable,
        exact_angle_solution=exact_angle_solution,
        exact_length_solution=exact_length_solution,
        expanded_outer=expanded_outer,
        piece_orientation_signs={
            name: placement.assignment.orientation_signs[index]
            for index, name in enumerate(placement.assignment.piece_names)
        },
        tile_count=len(planar_map.pieces),
        piecewise_c2_boundary=planar_map.hypotheses.piecewise_c2_boundary,
    )
    joint_expression_map = joint_angular.exact_solution.expression_map()
    joint_witness_map = joint_angular.witness_map()

    # The joint system can resolve point angles further than the point-only
    # subsystem.  Publish the refined exact expressions and witnesses.
    refined_points = []
    for point in points:
        alpha_name = f"alpha_B{point.boundary_index}"
        angle_expression = joint_expression_map[alpha_name]
        turn_expression = (LinearExpression.value(1) - angle_expression).normalized()
        angle_witness = joint_witness_map[alpha_name]
        occurrence_values = []
        occurrence_expressions = []
        for occurrence_name in point.occurrences:
            occurrence_values.append((occurrence_name, float(angle_witness)))
            occurrence_expressions.append((occurrence_name, angle_expression))
        refined_points.append(
            replace(
                point,
                prototype_turn_pi=float(Fraction(1) - angle_witness),
                prototype_angle_pi=float(angle_witness),
                prototype_angle_expression=angle_expression,
                prototype_turn_expression=turn_expression,
                occurrence_angles_pi=tuple(occurrence_values),
                occurrence_angle_expressions=tuple(occurrence_expressions),
            )
        )
    points = tuple(refined_points)

    refined_classes = []
    for point_class in point_classes:
        alpha_name = f"alpha_B{point_class.representative_boundary}"
        angle_expression = joint_expression_map[alpha_name]
        angle_witness = joint_witness_map[alpha_name]
        refined_classes.append(
            replace(
                point_class,
                turn_pi=float(Fraction(1) - angle_witness),
                representative_angle_expression=angle_expression,
                representative_turn_expression=(
                    LinearExpression.value(1) - angle_expression
                ).normalized(),
            )
        )
    point_classes = tuple(refined_classes)

    component_records = []
    for index, (representative, variables, transforms, symmetries, mode) in enumerate(components):
        circular = index in circular_components
        forced_straight = mode == "straight"
        if circular and forced_straight:
            raise DecorationInfeasible(
                "curve_templates",
                f"component {representative} is both a nonzero circle arc and forced straight",
            )
        length_parameter = f"L_C{index}"
        length_expression = exact_length_solution.expression_map()[length_parameter]
        curve_type = (
            "circular_arc" if circular else "straight_segment" if forced_straight else "generic_curve"
        )
        turn_parameter = f"K_C{index}"
        turn_expression = joint_expression_map[turn_parameter]
        component_records.append(
            CurveComponentRecord(
                component_id=f"C{index}",
                representative=representative,
                variables=variables,
                variable_transforms=tuple(
                    (variable, transforms[variable].label) for variable in variables
                ),
                self_symmetries=tuple(item.label for item in symmetries),
                mode=mode,
                curve_type=curve_type,
                forced_straight=forced_straight,
                circular=circular,
                circle_class="disk_boundary" if circular else None,
                length_parameter=length_parameter,
                search_witness_normalized_length=component_lengths[index],
                disk_normalized_length=length_expression,
                turn_parameter=turn_parameter,
                curve_turn_pi=turn_expression,
                curve_turn_pi_witness=joint_witness_map[turn_parameter],
                # Backward-compatible alias used by geometry readers before v0.6.
                disk_normalized_turn_pi=turn_expression,
            )
        )

    relation_records = tuple(
        TemplateRelationRecord(left, right, transform.label, interface, pair_index)
        for left, right, transform, interface, pair_index in raw_relations
    )

    outer_records = []
    length_expression_map = exact_length_solution.expression_map()
    for arc_index, (name, piece, word) in enumerate(expanded_outer):
        counts = Counter(component_by_variable[item.variable] for item in word)
        normalized_length = LinearExpression.value(0)
        for component_index, multiplicity in sorted(counts.items()):
            normalized_length = normalized_length + length_expression_map[
                f"L_C{component_index}"
            ].scale(multiplicity)
        normalized_length = normalized_length.normalized()
        outer_records.append(
            OuterArcRecord(
                name=name,
                piece=piece,
                terminal_word=word,
                length_parameter=f"O{arc_index}",
                length_expression=tuple(
                    (f"L_C{component_index}", multiplicity)
                    for component_index, multiplicity in sorted(counts.items())
                ),
                turn_parameter=f"theta{arc_index}",
                disk_normalized_length=normalized_length,
                turn_pi=normalized_length.scale(2),
            )
        )

    formal_constraints: list[Dict[str, object]] = []
    formal_constraints.append(
        {
            "kind": "terminal_point_angle_bounds",
            "unit": "pi",
            "strict_bounds": [
                {"parameter": f"alpha_B{index}", "lower": 0, "upper": 2}
                for index in range(len(terminal_contour))
            ],
        }
    )
    formal_constraints.append(
        {
            "kind": "terminal_curve_length_positivity",
            "normalization": "disk_circumference = 1",
            "strictly_positive_parameters": [
                item.length_parameter for item in component_records
            ],
        }
    )
    formal_constraints.append(
        {
            "kind": "outer_circle_positivity",
            "strictly_positive_parameters": [
                "C_disk",
                *[item.length_parameter for item in outer_records],
                *[item.turn_parameter for item in outer_records],
            ],
        }
    )
    formal_constraints.append(
        {
            "kind": "outer_circle_total_turn",
            "unit": "pi",
            "equation": " + ".join(item.turn_parameter for item in outer_records) + " = 2",
            "terms": [[item.turn_parameter, 1] for item in outer_records],
            "rhs": 2,
            "solved_last_parameter": (
                f"{outer_records[-1].turn_parameter} = 2 - "
                + " - ".join(item.turn_parameter for item in outer_records[:-1])
                if outer_records else None
            ),
        }
    )
    formal_constraints.append(
        {
            "kind": "outer_circle_total_length",
            "equation": " + ".join(item.length_parameter for item in outer_records) + " = C_disk",
            "terms": [[item.length_parameter, 1] for item in outer_records],
            "rhs_parameter": "C_disk",
        }
    )
    for item in outer_records:
        expression = " + ".join(
            f"{coefficient}*{parameter}" if coefficient != 1 else parameter
            for parameter, coefficient in item.length_expression
        ) or "0"
        formal_constraints.append(
            {
                "kind": "outer_arc_length_definition",
                "outer_arc": item.name,
                "equation": f"{item.length_parameter} = {expression}",
                "terms": [[parameter, coefficient] for parameter, coefficient in item.length_expression],
            }
        )
        formal_constraints.append(
            {
                "kind": "common_circle_length_turn_relation",
                "outer_arc": item.name,
                "equation": f"{item.turn_parameter} * C_disk = 2 * {item.length_parameter}",
                "unit": "pi",
                "note": "All outer arcs use the same disk circle; this relation is polynomial before disk normalization.",
                "disk_normalized_length": item.disk_normalized_length.to_dict(),
                "resolved_turn_pi": item.turn_pi.to_dict(),
            }
        )

    formal_constraints.append(
        {
            "kind": "exact_joint_point_curve_turn_feasibility",
            "unit": "pi",
            "point_turn_convention": "tau_Bi = 1 - alpha_Bi, with -1 < tau_Bi < 1",
            "curve_turn_convention": "K_Ci is unbounded signed total tangent turn of the representative curve template",
            "strict_margin": {
                "numerator": joint_angular.strict_margin.numerator,
                "denominator": joint_angular.strict_margin.denominator,
                "float": float(joint_angular.strict_margin),
            },
            "equations": [
                {
                    "kind": equation.kind,
                    "relation": equation.relation,
                    "sources": list(equation.sources),
                    "terms": [
                        [name, {
                            "numerator": coefficient.numerator,
                            "denominator": coefficient.denominator,
                            "float": float(coefficient),
                        }]
                        for name, coefficient in equation.terms
                    ],
                    "rhs_pi": {
                        "numerator": equation.rhs_pi.numerator,
                        "denominator": equation.rhs_pi.denominator,
                        "float": float(equation.rhs_pi),
                    },
                }
                for equation in joint_angular.equations
            ],
            "exact_solution": joint_angular.exact_solution.to_dict(),
            "witness": {
                name: {
                    "numerator": value.numerator,
                    "denominator": value.denominator,
                    "float": float(value),
                }
                for name, value in joint_angular.witness
            },
        }
    )
    formal_constraints.append(
        {
            "kind": "exact_terminal_angle_resolution",
            "unit": "pi",
            "solution": exact_angle_solution.to_dict(),
        }
    )
    formal_constraints.append(
        {
            "kind": "exact_disk_normalized_curve_lengths",
            "normalization": "disk_circumference = 1",
            "solution": exact_length_solution.to_dict(),
        }
    )

    return DecorationBundle(
        points=points,
        point_classes=point_classes,
        angle_equations=angle_equations,
        exact_angle_solution=exact_angle_solution,
        joint_angular_feasibility=joint_angular,
        curve_components=tuple(component_records),
        exact_length_solution=exact_length_solution,
        template_relations=relation_records,
        outer_arcs=tuple(outer_records),
        angle_margin=angle_margin,
        terminal_length_margin=terminal_length_margin,
        formal_constraints=tuple(formal_constraints),
    )
