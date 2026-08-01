from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterator, List, Mapping, Sequence, Tuple

from .algebra import (
    Equation,
    Literal,
    Word,
    inverse_word,
    simplify_system,
    substitute_equations,
    substitute_word,
)
from . import compact as cw
from .families import (
    AtomExpr,
    ExactFormalFamily,
    PowerExpr,
    WordExpr,
    canonicalize_environment,
    concat,
    expand_expression,
    expression_exponents,
    expression_node_count,
    expression_power_depth,
    expr_from_word,
    substitute_expr,
)


@dataclass(frozen=True)
class SolverLimits:
    max_graph_nodes: int | None = 3_000
    max_graph_edges: int | None = 12_000
    max_families: int | None = 16
    max_expression_nodes: int | None = 2_000
    max_terminal_contour_segments: int | None = None
    validation_exponent: int = 2


@dataclass(frozen=True)
class UnsupportedComponent:
    reason: str
    trace: Tuple[str, ...]
    cycle_length: int
    residual_equations: Tuple[str, ...]
    transformation: Tuple[Tuple[str, str], ...]

    def to_dict(self) -> Dict[str, object]:
        return {
            "reason": self.reason,
            "trace": list(self.trace),
            "cycle_length": self.cycle_length,
            "residual_equations": list(self.residual_equations),
            "transformation": dict(self.transformation),
        }


@dataclass(frozen=True)
class SolverRunSummary:
    visited_states: int
    graph_edges: int
    emitted_families: int
    finite_families: int
    power_families: int
    nested_power_families: int
    unsupported_complex_components: int
    graph_limit_reached: bool
    expression_limit_reached: bool
    terminal_contour_pruned: int
    family_limit_reached: bool
    external_stop_reached: bool
    exact_unsat: bool
    status: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "visited_states": self.visited_states,
            "graph_edges": self.graph_edges,
            "emitted_families": self.emitted_families,
            "finite_families": self.finite_families,
            "power_families": self.power_families,
            "nested_power_families": self.nested_power_families,
            "unsupported_complex_components": self.unsupported_complex_components,
            "graph_limit_reached": self.graph_limit_reached,
            "expression_limit_reached": self.expression_limit_reached,
            "terminal_contour_pruned": self.terminal_contour_pruned,
            "family_limit_reached": self.family_limit_reached,
            "external_stop_reached": self.external_stop_reached,
            "exact_unsat": self.exact_unsat,
            "status": self.status,
        }


@dataclass(frozen=True)
class _CanonicalResidual:
    equations: Tuple[Equation, ...]
    variables: Tuple[str, ...]
    rename: Tuple[Tuple[str, str], ...]
    signature: Tuple[object, ...]

    @property
    def key(self) -> Tuple[Equation, ...]:
        return self.equations

    def rename_map(self) -> Dict[str, str]:
        return dict(self.rename)


@dataclass(frozen=True)
class _LoopPlan:
    fixed_variables: Tuple[str, ...]
    pivots: Tuple[Tuple[str, Word, Word], ...]


@dataclass
class _MutableCounters:
    visited_states: int = 0
    graph_edges: int = 0
    finite_families: int = 0
    power_families: int = 0
    nested_power_families: int = 0
    unsupported_complex_components: int = 0
    graph_limit_reached: bool = False
    expression_limit_reached: bool = False
    terminal_contour_pruned: int = 0
    family_limit_reached: bool = False
    external_stop_reached: bool = False


def _simplify_equation_fast(equation: Equation) -> Equation | bool | None:
    """Equivalent to algebra.simplify_equation without quadratic pop(0) calls."""

    left = equation.left
    right = equation.right
    prefix = 0
    common = min(len(left), len(right))
    while prefix < common and left[prefix] == right[prefix]:
        prefix += 1

    left_end = len(left)
    right_end = len(right)
    while (
        left_end > prefix
        and right_end > prefix
        and left[left_end - 1] == right[right_end - 1]
    ):
        left_end -= 1
        right_end -= 1

    if prefix == left_end and prefix == right_end:
        return None
    if prefix == left_end or prefix == right_end:
        return False
    return Equation(left[prefix:left_end], right[prefix:right_end])


def _simplify_system_fast(equations: Sequence[Equation]) -> Tuple[Equation, ...] | None:
    """Local hot-path equivalent of simplify_system."""

    output: list[Equation] = []
    seen: set[Tuple[Word, Word]] = set()
    for equation in equations:
        simplified = _simplify_equation_fast(equation)
        if simplified is False:
            return None
        if simplified is None:
            continue
        direct = (simplified.left, simplified.right)
        reverse = (simplified.right, simplified.left)
        key = min(direct, reverse)
        if key not in seen:
            seen.add(key)
            output.append(simplified)
    return tuple(output)


def _substitute_equations_fast(
    equations: Sequence[Equation], substitution: Mapping[str, Word]
) -> Tuple[Equation, ...]:
    """Substitute a small Nielsen map without rebuilding untouched literals."""

    inverse_substitution = {
        variable: inverse_word(word) for variable, word in substitution.items()
    }

    def substitute(word: Word) -> Word:
        output: list[Literal] = []
        extend = output.extend
        append = output.append
        for literal in word:
            replacement = substitution.get(literal.variable)
            if replacement is None:
                append(literal)
            elif literal.inverse:
                extend(inverse_substitution[literal.variable])
            else:
                extend(replacement)
        return tuple(output)

    return tuple(
        Equation(substitute(equation.left), substitute(equation.right))
        for equation in equations
    )


def _local_pattern(word: Word, known: Mapping[str, int]) -> Tuple[Tuple[int, bool], ...]:
    local: Dict[str, int] = {}
    output = []
    for literal in word:
        token = known.get(literal.variable)
        if token is None:
            if literal.variable not in local:
                local[literal.variable] = len(local)
            token = 1_000_000 + local[literal.variable]
        output.append((token, literal.inverse))
    return tuple(output)


def _canonicalize_candidate(
    equations: Tuple[Equation, ...],
    all_variables: Sequence[str],
    seed_index: int,
    seed_flip: bool,
) -> Tuple[Tuple[object, ...], _CanonicalResidual]:
    remaining = set(range(len(equations)))
    order: List[Tuple[int, bool]] = [(seed_index, seed_flip)]
    remaining.remove(seed_index)
    renaming: Dict[str, int] = {}
    canonical_equations: List[Equation] = []
    order_index = 0

    def rename_word(word: Word) -> Word:
        output = []
        for literal in word:
            variable_index = renaming.get(literal.variable)
            if variable_index is None:
                variable_index = len(renaming)
                renaming[literal.variable] = variable_index
            output.append(Literal(f"V{variable_index}", literal.inverse))
        return tuple(output)

    while order_index < len(order):
        equation_index, flip = order[order_index]
        order_index += 1
        equation = equations[equation_index]
        left, right = (equation.right, equation.left) if flip else (equation.left, equation.right)
        canonical_equations.append(Equation(rename_word(left), rename_word(right)))
        if not remaining:
            continue

        selected_pattern: object | None = None
        selected_index = -1
        selected_flip = False
        for candidate_index in remaining:
            candidate = equations[candidate_index]
            for candidate_flip in (False, True):
                candidate_left, candidate_right = (
                    (candidate.right, candidate.left)
                    if candidate_flip
                    else (candidate.left, candidate.right)
                )
                choice = (
                    (
                        _local_pattern(candidate_left, renaming),
                        _local_pattern(candidate_right, renaming),
                    ),
                    candidate_index,
                    candidate_flip,
                )
                if selected_pattern is None or choice < selected_pattern:
                    selected_pattern = choice
                    selected_index = candidate_index
                    selected_flip = candidate_flip
        remaining.remove(selected_index)
        order.append((selected_index, selected_flip))

    for variable in sorted(set(all_variables)):
        if variable not in renaming:
            renaming[variable] = len(renaming)

    canonical_variables = tuple(f"V{index}" for index in range(len(renaming)))
    serialization = (
        tuple(
            (
                tuple((int(item.variable[1:]), item.inverse) for item in equation.left),
                tuple((int(item.variable[1:]), item.inverse) for item in equation.right),
            )
            for equation in canonical_equations
        ),
        len(canonical_variables),
    )
    return serialization, _CanonicalResidual(
        equations=tuple(canonical_equations),
        variables=canonical_variables,
        rename=tuple(sorted((name, f"V{index}") for name, index in renaming.items())),
        signature=serialization,
    )


def canonicalize_residual(
    equations: Sequence[Equation], all_variables: Sequence[str]
) -> _CanonicalResidual | None:
    simplified = _simplify_system_fast(equations)
    if simplified is None:
        return None
    if not simplified:
        renaming = {
            variable: f"V{index}" for index, variable in enumerate(sorted(set(all_variables)))
        }
        signature: Tuple[object, ...] = ((), len(renaming))
        return _CanonicalResidual(
            equations=(),
            variables=tuple(renaming.values()),
            rename=tuple(sorted(renaming.items())),
            signature=signature,
        )

    equations_tuple = tuple(simplified)
    best: Tuple[Tuple[object, ...], _CanonicalResidual] | None = None
    for seed_index in range(len(equations_tuple)):
        for seed_flip in (False, True):
            candidate = _canonicalize_candidate(
                equations_tuple, all_variables, seed_index, seed_flip
            )
            if best is None or candidate[0] < best[0]:
                best = candidate
    assert best is not None
    return best[1]

def _variables_in_words(words: Sequence[Word]) -> Tuple[str, ...]:
    return tuple(sorted({item.variable for word in words for item in word}))


def _fresh_variable(variables: Sequence[str]) -> str:
    used = set(variables)
    index = 0
    while f"R{index}" in used or f"V{index}" in used:
        index += 1
    return f"R{index}"


def branch_substitutions(
    equations: Tuple[Equation, ...], variables: Sequence[str]
) -> Iterator[Tuple[str, Dict[str, Word]]]:
    equation = equations[0]
    left_literal = equation.left[0]
    right_literal = equation.right[0]
    residual = Literal(_fresh_variable(variables))

    if left_literal.variable == right_literal.variable:
        if left_literal.inverse == right_literal.inverse:
            raise RuntimeError("Identical literals should have been cancelled")
        yield "involutive_palindrome", {
            left_literal.variable: (residual, residual.flipped())
        }
        return

    equal_orientation = left_literal.inverse ^ right_literal.inverse
    yield "equal_length", {
        left_literal.variable: (Literal(right_literal.variable, equal_orientation),)
    }

    oriented_right = (left_literal, residual)
    right_positive = inverse_word(oriented_right) if right_literal.inverse else oriented_right
    yield "left_strictly_shorter", {right_literal.variable: right_positive}

    oriented_left = (right_literal, residual)
    left_positive = inverse_word(oriented_left) if left_literal.inverse else oriented_left
    yield "right_strictly_shorter", {left_literal.variable: left_positive}


def _rename_word(word: Word, renaming: Mapping[str, str]) -> Word:
    return tuple(Literal(renaming[item.variable], item.inverse) for item in word)


def _edge_transition(
    parent_variables: Sequence[str],
    substitution: Mapping[str, Word],
    child_renaming: Mapping[str, str],
) -> Dict[str, Word]:
    output = {}
    for variable in parent_variables:
        raw = substitution.get(variable, (Literal(variable),))
        output[variable] = _rename_word(raw, child_renaming)
    return output


def _compose_transitions(
    domain_variables: Sequence[str], transitions: Sequence[Mapping[str, Word]]
) -> Dict[str, Word]:
    current: Dict[str, Word] = {variable: (Literal(variable),) for variable in domain_variables}
    for transition in transitions:
        current = {
            variable: substitute_word(word, transition)
            for variable, word in current.items()
        }
    return current


def _transition_text(transition: Mapping[str, Word]) -> Tuple[Tuple[str, str], ...]:
    def text(word: Word) -> str:
        return "1" if not word else " ".join(item.to_text() for item in word)

    return tuple((name, text(word)) for name, word in sorted(transition.items()))


def _classify_fixed_context_loop(
    variables: Sequence[str], transition: Mapping[str, Word]
) -> Tuple[_LoopPlan | None, str]:
    variable_set = set(variables)
    codomain = {item.variable for word in transition.values() for item in word}
    if not codomain <= variable_set:
        return None, "cycle introduces a fresh residual parameter on every iteration"

    fixed = {
        variable
        for variable in variables
        if transition.get(variable, (Literal(variable),)) == (Literal(variable),)
    }
    pivots: list[Tuple[str, Word, Word]] = []
    for variable in variables:
        word = transition.get(variable, (Literal(variable),))
        if variable in fixed:
            continue
        core_positions = [
            index
            for index, literal in enumerate(word)
            if literal.variable == variable and not literal.inverse
        ]
        if len(core_positions) != 1:
            return None, f"{variable} is not preserved exactly once by the cycle"
        if any(literal.variable == variable and literal.inverse for literal in word):
            return None, f"{variable} is inverted inside its cycle image"
        core = core_positions[0]
        prefix = word[:core]
        suffix = word[core + 1 :]
        context_variables = {item.variable for item in prefix + suffix}
        if not context_variables <= fixed:
            return None, f"{variable} depends on another evolving variable"
        if not prefix and not suffix:
            return None, f"{variable} changes only by an unsupported renaming"
        pivots.append((variable, prefix, suffix))

    if not pivots:
        return None, "cycle has no expanding fixed-context variable"
    return _LoopPlan(tuple(sorted(fixed)), tuple(pivots)), "supported_fixed_context_power"


def _loop_replacements(
    variables: Sequence[str], plan: _LoopPlan, exponent: str
) -> Dict[str, WordExpr]:
    replacements: Dict[str, WordExpr] = {
        variable: AtomExpr(variable) for variable in variables
    }
    for variable, prefix, suffix in plan.pivots:
        parts: list[WordExpr] = []
        if prefix:
            parts.append(PowerExpr(expr_from_word(prefix), exponent))
        parts.append(AtomExpr(variable))
        if suffix:
            parts.append(PowerExpr(expr_from_word(suffix), exponent))
        replacements[variable] = concat(*parts)
    return replacements


def _next_exponent_name(environment: Mapping[str, WordExpr]) -> str:
    existing = {
        name
        for expression in environment.values()
        for name in expression_exponents(expression)
    }
    index = 0
    while f"n{index}" in existing:
        index += 1
    return f"n{index}"


def _family_kind(environment: Mapping[str, WordExpr]) -> str:
    depth = max((expression_power_depth(item) for item in environment.values()), default=0)
    if depth == 0:
        return "finite"
    if depth == 1:
        return "power"
    return "nested_power"


def _environment_size(environment: Mapping[str, WordExpr]) -> int:
    return sum(expression_node_count(item) for item in environment.values())


@dataclass(frozen=True)
class _EnvironmentState:
    expression_ids: Tuple[int, ...]
    node_count: int
    terminal_min: int


class _ExpressionArena:
    """Hash-consed internal representation for symbolic environments.

    The public family representation remains unchanged. During graph search,
    expressions are represented by small integer IDs, so state signatures do
    not recursively hash or stringify large dataclass trees.
    """

    def __init__(self) -> None:
        self._nodes: list[tuple[object, ...]] = []
        self._sizes: list[int] = []
        self._depths: list[int] = []
        self._minimum_lengths: list[int] = []
        self._exponents: list[frozenset[str]] = []
        self._atoms: dict[tuple[int, bool], int] = {}
        self._concats: dict[tuple[int, ...], int] = {}
        self._powers: dict[tuple[int, str], int] = {}
        self._inverse: dict[int, int] = {}
        self._materialized: dict[int, WordExpr] = {}
        self.empty = self.concat(())

    def atom(self, variable: int, inverse: bool = False) -> int:
        key = (variable, inverse)
        existing = self._atoms.get(key)
        if existing is not None:
            return existing
        expression_id = len(self._nodes)
        self._atoms[key] = expression_id
        self._nodes.append(("atom", variable, inverse))
        self._sizes.append(1)
        self._depths.append(0)
        self._minimum_lengths.append(1)
        self._exponents.append(frozenset())
        return expression_id

    def concat(self, parts: Sequence[int]) -> int:
        flattened: list[int] = []
        for expression_id in parts:
            node = self._nodes[expression_id]
            if node[0] == "concat":
                flattened.extend(node[1])
            else:
                flattened.append(expression_id)
        if not flattened:
            key: tuple[int, ...] = ()
        elif len(flattened) == 1:
            return flattened[0]
        else:
            key = tuple(flattened)
        existing = self._concats.get(key)
        if existing is not None:
            return existing
        expression_id = len(self._nodes)
        self._concats[key] = expression_id
        self._nodes.append(("concat", key))
        self._sizes.append(1 + sum(self._sizes[item] for item in key))
        self._depths.append(max((self._depths[item] for item in key), default=0))
        self._minimum_lengths.append(sum(self._minimum_lengths[item] for item in key))
        exponent_names: set[str] = set()
        for item in key:
            exponent_names.update(self._exponents[item])
        self._exponents.append(frozenset(exponent_names))
        return expression_id

    def power(self, base: int, exponent: str) -> int:
        key = (base, exponent)
        existing = self._powers.get(key)
        if existing is not None:
            return existing
        expression_id = len(self._nodes)
        self._powers[key] = expression_id
        self._nodes.append(("power", base, exponent))
        self._sizes.append(1 + self._sizes[base])
        self._depths.append(1 + self._depths[base])
        self._minimum_lengths.append(self._minimum_lengths[base])
        self._exponents.append(self._exponents[base] | {exponent})
        return expression_id

    def from_word(self, word: Sequence[int]) -> int:
        return self.concat(
            tuple(self.atom(item >> 1, bool(item & 1)) for item in word)
        )

    def inverse(self, expression_id: int) -> int:
        existing = self._inverse.get(expression_id)
        if existing is not None:
            return existing
        node = self._nodes[expression_id]
        kind = node[0]
        if kind == "atom":
            result = self.atom(int(node[1]), not bool(node[2]))
        elif kind == "concat":
            result = self.concat(
                tuple(self.inverse(item) for item in reversed(node[1]))
            )
        elif kind == "power":
            result = self.power(self.inverse(int(node[1])), str(node[2]))
        else:
            raise AssertionError(kind)
        self._inverse[expression_id] = result
        self._inverse[result] = expression_id
        return result

    def substitute(
        self,
        expression_id: int,
        replacements: Mapping[int, int],
        memo: dict[int, int],
    ) -> int:
        existing = memo.get(expression_id)
        if existing is not None:
            return existing
        node = self._nodes[expression_id]
        kind = node[0]
        if kind == "atom":
            replacement = replacements.get(int(node[1]))
            if replacement is None:
                result = expression_id
            elif bool(node[2]):
                result = self.inverse(replacement)
            else:
                result = replacement
        elif kind == "concat":
            result = self.concat(
                tuple(self.substitute(item, replacements, memo) for item in node[1])
            )
        elif kind == "power":
            result = self.power(
                self.substitute(int(node[1]), replacements, memo), str(node[2])
            )
        else:
            raise AssertionError(kind)
        memo[expression_id] = result
        return result

    def apply_environment(
        self,
        environment: _EnvironmentState,
        replacements: Mapping[int, int],
        contour_indices: Sequence[int],
    ) -> _EnvironmentState:
        memo: dict[int, int] = {}
        expression_ids = tuple(
            self.substitute(expression_id, replacements, memo)
            for expression_id in environment.expression_ids
        )
        return self.make_environment(expression_ids, contour_indices)

    def make_environment(
        self, expression_ids: Sequence[int], contour_indices: Sequence[int]
    ) -> _EnvironmentState:
        expression_tuple = tuple(expression_ids)
        return _EnvironmentState(
            expression_ids=expression_tuple,
            node_count=sum(self._sizes[item] for item in expression_tuple),
            terminal_min=sum(
                self._minimum_lengths[expression_tuple[index]]
                for index in contour_indices
            ),
        )

    def materialize(self, expression_id: int) -> WordExpr:
        existing = self._materialized.get(expression_id)
        if existing is not None:
            return existing
        node = self._nodes[expression_id]
        kind = node[0]
        if kind == "atom":
            result: WordExpr = AtomExpr(f"V{int(node[1])}", bool(node[2]))
        elif kind == "concat":
            result = concat(*(self.materialize(item) for item in node[1]))
        elif kind == "power":
            result = PowerExpr(self.materialize(int(node[1])), str(node[2]))
        else:
            raise AssertionError(kind)
        self._materialized[expression_id] = result
        return result

    def materialize_environment(
        self,
        initial_variables: Sequence[str],
        environment: _EnvironmentState,
    ) -> Dict[str, WordExpr]:
        return {
            variable: self.materialize(expression_id)
            for variable, expression_id in zip(
                initial_variables, environment.expression_ids, strict=True
            )
        }

    def exponent_names(self, environment: _EnvironmentState) -> frozenset[str]:
        names: set[str] = set()
        for expression_id in environment.expression_ids:
            names.update(self._exponents[expression_id])
        return frozenset(names)


def _validate_family(
    original_equations: Sequence[Equation],
    environment: Mapping[str, WordExpr],
    minimums: Mapping[str, int],
    validation_exponent: int,
) -> Tuple[bool, Tuple[Tuple[Tuple[str, int], ...], ...]]:
    assignments: list[Tuple[Tuple[str, int], ...]] = []
    base = {name: int(value) for name, value in minimums.items()}
    assignments.append(tuple(sorted(base.items())))
    for name in sorted(base):
        alternate = dict(base)
        alternate[name] = max(base[name] + 1, validation_exponent)
        assignments.append(tuple(sorted(alternate.items())))

    for assignment in assignments:
        exponent_map = dict(assignment)
        concrete = {
            variable: expand_expression(expression, exponent_map)
            for variable, expression in environment.items()
        }
        substituted = substitute_equations(original_equations, concrete)
        if simplify_system(substituted) != ():
            return False, tuple(assignments)
    return True, tuple(assignments)


class ExactPartialWordSolver:
    """Exact-partial Nielsen-Levi solver.

    Finite branches are emitted directly. A repeated residual state is compiled
    only when its cycle is a fixed-context power loop. Such loops may be met
    successively, yielding nested Power expressions. Any other repeated state is
    recorded as an unsupported complex iterative component and is not unfolded.
    """

    def __init__(
        self,
        equations: Sequence[Equation],
        initial_variables: Sequence[str],
        contour_variables: Sequence[str] | None = None,
    ) -> None:
        self.original_equations = tuple(equations)
        self.initial_variables = tuple(initial_variables)
        self.contour_variables = tuple(
            self.initial_variables if contour_variables is None else contour_variables
        )
        unknown_contour = set(self.contour_variables) - set(self.initial_variables)
        if unknown_contour:
            raise ValueError(
                "contour_variables must be a subset of initial_variables: "
                + ", ".join(sorted(unknown_contour))
            )
        self._contour_indices = tuple(
            self.initial_variables.index(variable) for variable in self.contour_variables
        )
        compact_equations, initial_raw_ids, ordered_names = cw.encode_problem(
            self.original_equations, self.initial_variables
        )
        self._initial_raw_ids = initial_raw_ids
        self._progress: Dict[str, object] = {
            "phase": "initial_canonicalization",
            "visited_states": 0,
            "graph_edges": 0,
            "depth": 0,
            "equation_count": len(self.original_equations),
            "literal_count": sum(
                len(equation.left) + len(equation.right)
                for equation in self.original_equations
            ),
            "variable_count": len(ordered_names),
            "environment_nodes": 0,
            "terminal_min": len(self.contour_variables),
            "terminal_limit": None,
            "terminal_pruned": 0,
            "trace_tail": [],
        }
        initial = cw.canonicalize_residual(
            compact_equations,
            tuple(range(len(ordered_names))),
            len(ordered_names),
        )
        self.initial_residual = initial
        self.unsupported_components: list[UnsupportedComponent] = []
        self._progress["phase"] = "ready" if initial is not None else "exact_unsat"
        self.last_summary = SolverRunSummary(
            visited_states=0,
            graph_edges=0,
            emitted_families=0,
            finite_families=0,
            power_families=0,
            nested_power_families=0,
            unsupported_complex_components=0,
            graph_limit_reached=False,
            expression_limit_reached=False,
            terminal_contour_pruned=0,
            family_limit_reached=False,
            external_stop_reached=False,
            exact_unsat=False,
            status="not_run",
        )

    def progress_snapshot(self) -> Dict[str, object]:
        return dict(self._progress)

    def solve(
        self,
        limits: SolverLimits,
        stop_predicate: Callable[[], bool] | None = None,
    ) -> Iterator[ExactFormalFamily]:
        if self.initial_residual is None:
            self._progress["phase"] = "exact_unsat"
            self.last_summary = SolverRunSummary(
                visited_states=0,
                graph_edges=0,
                emitted_families=0,
                finite_families=0,
                power_families=0,
                nested_power_families=0,
                unsupported_complex_components=0,
                graph_limit_reached=False,
                expression_limit_reached=False,
                terminal_contour_pruned=0,
                family_limit_reached=False,
                external_stop_reached=False,
                exact_unsat=True,
                status="exact_unsat",
            )
            return

        arena = _ExpressionArena()
        initial_rename = self.initial_residual.rename
        initial_expression_ids = tuple(
            arena.atom(initial_rename[raw_id]) for raw_id in self._initial_raw_ids
        )
        initial_environment = arena.make_environment(
            initial_expression_ids, self._contour_indices
        )
        counters = _MutableCounters()
        should_stop = stop_predicate or (lambda: False)
        emitted_signatures: set[object] = set()
        seen_search_signatures: set[object] = set()
        family_id = 0
        stop = False

        def update_progress(
            phase: str,
            *,
            residual: cw.CanonicalResidual | None = None,
            environment: _EnvironmentState | None = None,
            trace: Sequence[str] = (),
            branch: str | None = None,
            raw_equations: Sequence[cw.CompactEquation] | None = None,
        ) -> None:
            equations = (
                tuple(raw_equations)
                if raw_equations is not None
                else (residual.equations if residual is not None else ())
            )
            self._progress = {
                "phase": phase,
                "visited_states": counters.visited_states,
                "graph_edges": counters.graph_edges,
                "emitted_families": family_id,
                "depth": len(trace),
                "equation_count": len(equations),
                "literal_count": sum(
                    len(equation[0]) + len(equation[1]) for equation in equations
                ),
                "variable_count": residual.variable_count if residual is not None else 0,
                "environment_nodes": (
                    environment.node_count if environment is not None else 0
                ),
                "terminal_min": (
                    environment.terminal_min if environment is not None else 0
                ),
                "terminal_limit": limits.max_terminal_contour_segments,
                "terminal_pruned": counters.terminal_contour_pruned,
                "branch": branch,
                "trace_tail": list(trace[-12:]),
            }

        update_progress(
            "search_start",
            residual=self.initial_residual,
            environment=initial_environment,
        )

        def next_exponent_name(environment: _EnvironmentState) -> str:
            existing = arena.exponent_names(environment)
            index = 0
            while f"n{index}" in existing:
                index += 1
            return f"n{index}"

        def loop_replacement_ids(
            variable_count: int, plan: cw.LoopPlan, exponent: str
        ) -> Dict[int, int]:
            replacements: Dict[int, int] = {
                variable: arena.atom(variable) for variable in range(variable_count)
            }
            for variable, prefix, suffix in plan.pivots:
                parts: list[int] = []
                if prefix:
                    parts.append(arena.power(arena.from_word(prefix), exponent))
                parts.append(arena.atom(variable))
                if suffix:
                    parts.append(arena.power(arena.from_word(suffix), exponent))
                replacements[variable] = arena.concat(parts)
            return replacements

        def emit_family(
            environment: _EnvironmentState,
            minimums: Mapping[str, int],
            trace: Sequence[str],
        ) -> Iterator[ExactFormalFamily]:
            nonlocal family_id, stop
            materialized_environment = arena.materialize_environment(
                self.initial_variables, environment
            )
            canonical_environment, canonical_minimums = canonicalize_environment(
                materialized_environment, minimums
            )
            signature = (canonical_environment, canonical_minimums)
            if signature in emitted_signatures:
                return
            canonical_map = dict(canonical_environment)
            minimum_map = dict(canonical_minimums)
            valid, validation_assignments = _validate_family(
                self.original_equations,
                canonical_map,
                minimum_map,
                limits.validation_exponent,
            )
            if not valid:
                return
            emitted_signatures.add(signature)
            kind = _family_kind(canonical_map)
            if kind == "finite":
                counters.finite_families += 1
            elif kind == "power":
                counters.power_families += 1
            else:
                counters.nested_power_families += 1
            result = ExactFormalFamily(
                family_id=family_id,
                kind=kind,
                environment=canonical_environment,
                exponent_minimums=canonical_minimums,
                trace=tuple(trace),
                residual_graph_nodes=counters.visited_states,
                validation_assignments=validation_assignments,
            )
            family_id += 1
            yield result
            if limits.max_families is not None and family_id >= limits.max_families:
                counters.family_limit_reached = True
                stop = True

        def search(
            residual: cw.CanonicalResidual,
            environment: _EnvironmentState,
            minimums: Mapping[str, int],
            trace: list[str],
            used_cycles: frozenset[object],
            path_residuals: list[cw.CanonicalResidual],
            path_environments: list[_EnvironmentState],
            path_edges: list[cw.CompactTransition],
            path_index: dict[Tuple[object, ...], int],
        ) -> Iterator[ExactFormalFamily]:
            nonlocal stop
            update_progress(
                "search_node",
                residual=residual,
                environment=environment,
                trace=trace,
            )
            if stop:
                return
            if should_stop():
                counters.external_stop_reached = True
                stop = True
                return
            if (
                limits.max_terminal_contour_segments is not None
                and environment.terminal_min > limits.max_terminal_contour_segments
            ):
                counters.terminal_contour_pruned += 1
                update_progress(
                    "terminal_contour_cutoff",
                    residual=residual,
                    environment=environment,
                    trace=trace,
                )
                return
            if limits.max_graph_nodes is not None and counters.visited_states >= limits.max_graph_nodes:
                counters.graph_limit_reached = True
                stop = True
                return
            counters.visited_states += 1

            search_signature = (
                residual.signature,
                environment.expression_ids,
                tuple(sorted(minimums.items())),
                used_cycles,
            )
            if search_signature in seen_search_signatures:
                return
            seen_search_signatures.add(search_signature)

            if (
                limits.max_expression_nodes is not None
                and environment.node_count > limits.max_expression_nodes
            ):
                counters.expression_limit_reached = True
                return

            if not residual.equations:
                yield from emit_family(environment, minimums, trace)
                return

            update_progress(
                "branch_generation",
                residual=residual,
                environment=environment,
                trace=trace,
            )
            for branch_name, substitution in cw.branch_substitutions(
                residual.equations, residual.variable_count
            ):
                if stop:
                    return
                if should_stop():
                    counters.external_stop_reached = True
                    stop = True
                    return
                if limits.max_graph_edges is not None and counters.graph_edges >= limits.max_graph_edges:
                    counters.graph_limit_reached = True
                    stop = True
                    return
                counters.graph_edges += 1
                update_progress(
                    "substitute_equations",
                    residual=residual,
                    environment=environment,
                    trace=trace,
                    branch=branch_name,
                )

                raw_equations = cw.substitute_equations(
                    residual.equations, substitution
                )
                raw_transition_words = cw.transition_words(
                    residual.variable_count, substitution
                )
                raw_variables = cw.variables_in_words(
                    tuple(equation[0] for equation in raw_equations)
                    + tuple(equation[1] for equation in raw_equations)
                    + raw_transition_words
                )
                ordered_raw_variables = cw.ordered_raw_variables(
                    raw_variables, residual.variable_count
                )
                update_progress(
                    "canonicalize_residual",
                    residual=residual,
                    environment=environment,
                    trace=trace,
                    branch=branch_name,
                    raw_equations=raw_equations,
                )
                child = cw.canonicalize_residual(
                    raw_equations,
                    ordered_raw_variables,
                    residual.variable_count + 1,
                )
                if child is None:
                    continue

                transition = cw.edge_transition(
                    residual.variable_count, substitution, child.rename
                )
                replacement_ids = {
                    variable: arena.from_word(word)
                    for variable, word in enumerate(transition)
                }
                update_progress(
                    "update_environment",
                    residual=child,
                    environment=environment,
                    trace=trace,
                    branch=branch_name,
                )
                child_environment = arena.apply_environment(
                    environment, replacement_ids, self._contour_indices
                )

                trace.append(branch_name)
                try:
                    ancestor_index = path_index.get(child.signature)
                    if ancestor_index is not None:
                        ancestor = path_residuals[ancestor_index]
                        cycle_edges = tuple(path_edges[ancestor_index:]) + (transition,)
                        loop_transition = cw.compose_transitions(
                            ancestor.variable_count, cycle_edges
                        )
                        cycle_signature = (
                            ancestor.signature,
                            cw.transition_signature(loop_transition),
                        )
                        if cycle_signature in used_cycles:
                            continue
                        if child.variable_count != ancestor.variable_count:
                            plan = None
                            reason = "residual variable set changes around the cycle"
                        else:
                            plan, reason = cw.classify_fixed_context_loop(
                                ancestor.variable_count, loop_transition
                            )
                        if plan is None:
                            counters.unsupported_complex_components += 1
                            self.unsupported_components.append(
                                UnsupportedComponent(
                                    reason=reason,
                                    trace=tuple(trace),
                                    cycle_length=len(cycle_edges),
                                    residual_equations=tuple(
                                        cw.equation_to_text(equation)
                                        for equation in ancestor.equations
                                    ),
                                    transformation=cw.transition_text(loop_transition),
                                )
                            )
                            continue

                        exponent = next_exponent_name(
                            path_environments[ancestor_index]
                        )
                        loop_replacements = loop_replacement_ids(
                            ancestor.variable_count, plan, exponent
                        )
                        generalized_environment = arena.apply_environment(
                            path_environments[ancestor_index],
                            loop_replacements,
                            self._contour_indices,
                        )
                        generalized_minimums = dict(minimums)
                        generalized_minimums[exponent] = 1
                        trace.append(f"compile_power:{exponent}")
                        try:
                            yield from search(
                                ancestor,
                                generalized_environment,
                                generalized_minimums,
                                trace,
                                used_cycles | {cycle_signature},
                                [ancestor],
                                [generalized_environment],
                                [],
                                {ancestor.signature: 0},
                            )
                        finally:
                            trace.pop()
                        continue

                    child_index = len(path_residuals)
                    path_index[child.signature] = child_index
                    path_residuals.append(child)
                    path_environments.append(child_environment)
                    path_edges.append(transition)
                    try:
                        yield from search(
                            child,
                            child_environment,
                            minimums,
                            trace,
                            used_cycles,
                            path_residuals,
                            path_environments,
                            path_edges,
                            path_index,
                        )
                    finally:
                        path_edges.pop()
                        path_environments.pop()
                        path_residuals.pop()
                        del path_index[child.signature]
                finally:
                    trace.pop()

        yield from search(
            self.initial_residual,
            initial_environment,
            {},
            [],
            frozenset(),
            [self.initial_residual],
            [initial_environment],
            [],
            {self.initial_residual.signature: 0},
        )

        emitted = family_id
        update_progress(
            "finalizing",
            residual=self.initial_residual,
            environment=initial_environment,
        )
        exact_unsat = (
            emitted == 0
            and counters.unsupported_complex_components == 0
            and not counters.graph_limit_reached
            and not counters.expression_limit_reached
            and counters.terminal_contour_pruned == 0
            and not counters.family_limit_reached
            and not counters.external_stop_reached
        )
        if counters.external_stop_reached:
            status = "interrupted_external_stop"
        elif counters.family_limit_reached:
            status = "unresolved_family_limit"
        elif counters.graph_limit_reached or counters.expression_limit_reached:
            status = "unresolved_graph_limit"
        elif counters.terminal_contour_pruned:
            status = "restricted_terminal_contour_limit"
        elif counters.unsupported_complex_components:
            status = "exact_unsupported_family_language"
        elif exact_unsat:
            status = "exact_unsat"
        else:
            status = "exact_supported"
        self.last_summary = SolverRunSummary(
            visited_states=counters.visited_states,
            graph_edges=counters.graph_edges,
            emitted_families=emitted,
            finite_families=counters.finite_families,
            power_families=counters.power_families,
            nested_power_families=counters.nested_power_families,
            unsupported_complex_components=counters.unsupported_complex_components,
            graph_limit_reached=counters.graph_limit_reached,
            expression_limit_reached=counters.expression_limit_reached,
            terminal_contour_pruned=counters.terminal_contour_pruned,
            family_limit_reached=counters.family_limit_reached,
            external_stop_reached=counters.external_stop_reached,
            exact_unsat=exact_unsat,
            status=status,
        )
        self._progress = {
            **self._progress,
            "phase": "done",
            "visited_states": counters.visited_states,
            "graph_edges": counters.graph_edges,
            "emitted_families": emitted,
            "terminal_min": initial_environment.terminal_min,
            "terminal_limit": limits.max_terminal_contour_segments,
            "terminal_pruned": counters.terminal_contour_pruned,
            "status": status,
        }

