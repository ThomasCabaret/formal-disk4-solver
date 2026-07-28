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
    family_limit_reached: bool = False
    external_stop_reached: bool = False


def _local_pattern(word: Word, known: Mapping[str, str]) -> Tuple[Tuple[int, bool], ...]:
    local: Dict[str, int] = {}
    output = []
    for literal in word:
        if literal.variable in known:
            token = int(known[literal.variable][1:])
        else:
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
    renaming: Dict[str, str] = {}
    canonical_equations: List[Equation] = []

    def rename_word(word: Word) -> Word:
        output = []
        for literal in word:
            if literal.variable not in renaming:
                renaming[literal.variable] = f"V{len(renaming)}"
            output.append(Literal(renaming[literal.variable], literal.inverse))
        return tuple(output)

    while order:
        equation_index, flip = order.pop(0)
        equation = equations[equation_index]
        left, right = (equation.right, equation.left) if flip else (equation.left, equation.right)
        canonical_equations.append(Equation(rename_word(left), rename_word(right)))
        if not remaining:
            continue
        choices = []
        for candidate_index in remaining:
            candidate = equations[candidate_index]
            for candidate_flip in (False, True):
                candidate_left, candidate_right = (
                    (candidate.right, candidate.left)
                    if candidate_flip
                    else (candidate.left, candidate.right)
                )
                choices.append(
                    (
                        (
                            _local_pattern(candidate_left, renaming),
                            _local_pattern(candidate_right, renaming),
                        ),
                        candidate_index,
                        candidate_flip,
                    )
                )
        _, selected_index, selected_flip = min(choices)
        remaining.remove(selected_index)
        order.append((selected_index, selected_flip))

    for variable in sorted(set(all_variables)):
        if variable not in renaming:
            renaming[variable] = f"V{len(renaming)}"

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
        rename=tuple(sorted(renaming.items())),
    )


def canonicalize_residual(
    equations: Sequence[Equation], all_variables: Sequence[str]
) -> _CanonicalResidual | None:
    simplified = simplify_system(equations)
    if simplified is None:
        return None
    if not simplified:
        renaming = {
            variable: f"V{index}" for index, variable in enumerate(sorted(set(all_variables)))
        }
        return _CanonicalResidual(
            equations=(),
            variables=tuple(renaming.values()),
            rename=tuple(sorted(renaming.items())),
        )
    candidates = []
    for seed_index in range(len(simplified)):
        for seed_flip in (False, True):
            candidates.append(
                _canonicalize_candidate(
                    tuple(simplified), all_variables, seed_index, seed_flip
                )
            )
    return min(candidates, key=lambda item: item[0])[1]


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

    def __init__(self, equations: Sequence[Equation], initial_variables: Sequence[str]) -> None:
        self.original_equations = tuple(equations)
        self.initial_variables = tuple(initial_variables)
        initial = canonicalize_residual(self.original_equations, self.initial_variables)
        self.initial_residual = initial
        self.unsupported_components: list[UnsupportedComponent] = []
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
            family_limit_reached=False,
            external_stop_reached=False,
            exact_unsat=False,
            status="not_run",
        )

    def solve(
        self,
        limits: SolverLimits,
        stop_predicate: Callable[[], bool] | None = None,
    ) -> Iterator[ExactFormalFamily]:
        if self.initial_residual is None:
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
                family_limit_reached=False,
                external_stop_reached=False,
                exact_unsat=True,
                status="exact_unsat",
            )
            return

        initial_rename = self.initial_residual.rename_map()
        initial_environment: Dict[str, WordExpr] = {
            variable: AtomExpr(initial_rename[variable])
            for variable in self.initial_variables
        }
        counters = _MutableCounters()
        should_stop = stop_predicate or (lambda: False)
        emitted_signatures: set[object] = set()
        seen_search_signatures: set[object] = set()
        family_id = 0
        stop = False

        def emit_family(
            environment: Mapping[str, WordExpr],
            minimums: Mapping[str, int],
            trace: Tuple[str, ...],
        ) -> Iterator[ExactFormalFamily]:
            nonlocal family_id, stop
            canonical_environment, canonical_minimums = canonicalize_environment(
                environment, minimums
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
                trace=trace,
                residual_graph_nodes=counters.visited_states,
                validation_assignments=validation_assignments,
            )
            family_id += 1
            yield result
            if limits.max_families is not None and family_id >= limits.max_families:
                counters.family_limit_reached = True
                stop = True

        def search(
            residual: _CanonicalResidual,
            environment: Mapping[str, WordExpr],
            minimums: Mapping[str, int],
            trace: Tuple[str, ...],
            used_cycles: frozenset[object],
            path_residuals: Tuple[_CanonicalResidual, ...],
            path_environments: Tuple[Mapping[str, WordExpr], ...],
            path_edges: Tuple[Mapping[str, Word], ...],
        ) -> Iterator[ExactFormalFamily]:
            nonlocal stop
            if stop:
                return
            if should_stop():
                counters.external_stop_reached = True
                stop = True
                return
            if limits.max_graph_nodes is not None and counters.visited_states >= limits.max_graph_nodes:
                counters.graph_limit_reached = True
                stop = True
                return
            counters.visited_states += 1

            search_signature = (
                residual.key,
                tuple(sorted((name, repr(expr)) for name, expr in environment.items())),
                tuple(sorted(minimums.items())),
                tuple(sorted(repr(item) for item in used_cycles)),
            )
            if search_signature in seen_search_signatures:
                return
            seen_search_signatures.add(search_signature)

            if limits.max_expression_nodes is not None and _environment_size(environment) > limits.max_expression_nodes:
                counters.expression_limit_reached = True
                return

            if not residual.equations:
                yield from emit_family(environment, minimums, trace)
                return

            path_keys = tuple(item.key for item in path_residuals)
            for branch_name, substitution in branch_substitutions(
                residual.equations, residual.variables
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
                raw_equations = substitute_equations(residual.equations, substitution)
                raw_transition_words = [
                    substitution.get(variable, (Literal(variable),))
                    for variable in residual.variables
                ]
                raw_variables = _variables_in_words(
                    tuple(raw_equations[index].left for index in range(len(raw_equations)))
                    + tuple(raw_equations[index].right for index in range(len(raw_equations)))
                    + tuple(raw_transition_words)
                )
                child = canonicalize_residual(raw_equations, raw_variables)
                if child is None:
                    continue
                renaming = child.rename_map()
                transition = _edge_transition(
                    residual.variables, substitution, renaming
                )
                replacements = {
                    variable: expr_from_word(word)
                    for variable, word in transition.items()
                }
                child_environment = {
                    initial: substitute_expr(expression, replacements)
                    for initial, expression in environment.items()
                }
                child_trace = trace + (branch_name,)

                if child.key in path_keys:
                    ancestor_index = path_keys.index(child.key)
                    ancestor = path_residuals[ancestor_index]
                    cycle_edges = path_edges[ancestor_index:] + (transition,)
                    loop_transition = _compose_transitions(
                        ancestor.variables, cycle_edges
                    )
                    cycle_signature = (
                        ancestor.key,
                        tuple(sorted(loop_transition.items())),
                    )
                    if cycle_signature in used_cycles:
                        continue
                    if child.variables != ancestor.variables:
                        plan = None
                        reason = "residual variable set changes around the cycle"
                    else:
                        plan, reason = _classify_fixed_context_loop(
                            ancestor.variables, loop_transition
                        )
                    if plan is None:
                        counters.unsupported_complex_components += 1
                        self.unsupported_components.append(
                            UnsupportedComponent(
                                reason=reason,
                                trace=child_trace,
                                cycle_length=len(cycle_edges),
                                residual_equations=tuple(
                                    equation.to_text() for equation in ancestor.equations
                                ),
                                transformation=_transition_text(loop_transition),
                            )
                        )
                        continue

                    exponent = _next_exponent_name(
                        path_environments[ancestor_index]
                    )
                    loop_replacements = _loop_replacements(
                        ancestor.variables, plan, exponent
                    )
                    generalized_environment = {
                        initial: substitute_expr(expression, loop_replacements)
                        for initial, expression in path_environments[ancestor_index].items()
                    }
                    generalized_minimums = dict(minimums)
                    generalized_minimums[exponent] = 1
                    yield from search(
                        ancestor,
                        generalized_environment,
                        generalized_minimums,
                        child_trace + (f"compile_power:{exponent}",),
                        used_cycles | {cycle_signature},
                        (ancestor,),
                        (generalized_environment,),
                        (),
                    )
                    continue

                yield from search(
                    child,
                    child_environment,
                    minimums,
                    child_trace,
                    used_cycles,
                    path_residuals + (child,),
                    path_environments + (child_environment,),
                    path_edges + (transition,),
                )

        yield from search(
            self.initial_residual,
            initial_environment,
            {},
            (),
            frozenset(),
            (self.initial_residual,),
            (initial_environment,),
            (),
        )

        emitted = family_id
        exact_unsat = (
            emitted == 0
            and counters.unsupported_complex_components == 0
            and not counters.graph_limit_reached
            and not counters.expression_limit_reached
            and not counters.family_limit_reached
            and not counters.external_stop_reached
        )
        if counters.external_stop_reached:
            status = "interrupted_external_stop"
        elif counters.family_limit_reached:
            status = "unresolved_family_limit"
        elif counters.graph_limit_reached or counters.expression_limit_reached:
            status = "unresolved_graph_limit"
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
            family_limit_reached=counters.family_limit_reached,
            external_stop_reached=counters.external_stop_reached,
            exact_unsat=exact_unsat,
            status=status,
        )
