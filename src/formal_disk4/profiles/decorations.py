from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from fractions import Fraction
from typing import Dict, Iterable, Mapping, Sequence, Tuple

import numpy as np
from scipy.optimize import linprog

from formal_disk4.enumeration.weak_orders import Placement
from formal_disk4.maps.base import Occurrence, PlanarMap
from formal_disk4.words.algebra import Literal, Word, substitute_word
from formal_disk4.words.compile import CompiledWordCase, ContactMapping, DirectedSegmentRef

from .exact_linear import (
    ExactLinearInfeasible,
    ExactLinearSolution,
    LinearExpression,
    as_fraction,
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
class PointClassRecord:
    class_id: str
    representative_boundary: int
    members: Tuple[Tuple[int, int], ...]
    forced_zero: bool
    turn_pi: float | None
    representative_angle_expression: LinearExpression


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
        mirror = mapping.relative_parity == -1
        for pair_index, (left_ref, right_ref) in enumerate(mapping.pairs):
            left_literal = terminal_contour[left_ref.segment_index]
            right_literal = terminal_contour[right_ref.segment_index]
            reverse = _effective_orientation(left_literal, left_ref) != _effective_orientation(
                right_literal, right_ref
            )
            transform = TemplateTransform(reverse=reverse, mirror=mirror)
            left_start, left_end = _directed_boundaries(left_ref, segment_count)
            right_start, right_end = _directed_boundaries(right_ref, segment_count)
            for endpoint, left_boundary, right_boundary in (
                ("start", left_start, right_start),
                ("end", left_end, right_end),
            ):
                union.union(left_boundary, right_boundary, transform.turn_sign)
                relation_terms: Dict[int, int] = defaultdict(int)
                relation_terms[left_boundary] += 1
                relation_terms[right_boundary] += -1 if transform.turn_sign == 1 else 1
                if transform.turn_sign == 1:
                    add_equation(
                        "mapping_angle_equality",
                        relation_terms,
                        Fraction(0),
                        f"{mapping.interface_name}:pair{pair_index}:{endpoint}",
                        "equal_interior_angles",
                    )
                else:
                    add_equation(
                        "mapping_angle_full_turn_complement",
                        relation_terms,
                        Fraction(2),
                        f"{mapping.interface_name}:pair{pair_index}:{endpoint}",
                        "alpha_left + alpha_right = 2*pi",
                    )
    union.normalize()

    occurrence_index = {
        occurrence: index for index, occurrence in enumerate(planar_map.occurrences())
    }
    piece_index = {name: index for index, name in enumerate(placement.assignment.piece_names)}
    block_boundary = {
        int(source[1]): boundary_index
        for boundary_index, source in enumerate(boundary_sources)
        if source[0] == "map_vertex" and source[1] is not None
    }

    for vertex in planar_map.vertices:
        terms: Dict[int, int] = defaultdict(int)
        negative_orientation_count = 0
        for piece in vertex.incident_pieces:
            occurrence_id = occurrence_index[Occurrence(piece, vertex.name)]
            block_index = placement.positions[occurrence_id]
            boundary_index = block_boundary[block_index]
            orientation = placement.assignment.orientation_signs[piece_index[piece]]
            if orientation == 1:
                terms[boundary_index] += 1
            else:
                terms[boundary_index] -= 1
                negative_orientation_count += 1
        rhs = as_fraction(vertex.angle_sum_pi) - Fraction(2 * negative_orientation_count)
        nonzero_terms = {index: coefficient for index, coefficient in terms.items() if coefficient}
        if vertex.kind == "outer" and all(coefficient == 1 for coefficient in nonzero_terms.values()) and rhs == 1:
            relation = "incident_piece_angles_sum_to_pi"
        elif vertex.kind == "interior" and rhs == 2:
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
            piece = occurrence_name.split(":", 1)[0]
            orientation = placement.assignment.orientation_signs[piece_index[piece]]
            if orientation == 1:
                occurrence_value = prototype_angle
                occurrence_expression = prototype_expression
            else:
                occurrence_value = 2.0 - prototype_angle
                occurrence_expression = LinearExpression.value(2) - prototype_expression
            occurrence_angles.append((occurrence_name, occurrence_value))
            occurrence_expressions.append((occurrence_name, occurrence_expression.normalized()))
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
                disk_normalized_turn_pi=(length_expression.scale(2) if circular else None),
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
        curve_components=tuple(component_records),
        exact_length_solution=exact_length_solution,
        template_relations=relation_records,
        outer_arcs=tuple(outer_records),
        angle_margin=angle_margin,
        terminal_length_margin=terminal_length_margin,
        formal_constraints=tuple(formal_constraints),
    )
