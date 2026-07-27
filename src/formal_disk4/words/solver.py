from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

from .algebra import (
    Equation,
    Literal,
    Word,
    inverse_word,
    simplify_system,
    substitute_equations,
    substitute_word,
)


@dataclass(frozen=True)
class SolverLimits:
    max_depth: int | None = 8
    max_states: int | None = 5_000
    max_terminals: int | None = 16
    max_environment_word_length: int | None = 80


@dataclass(frozen=True)
class SolverState:
    equations: Tuple[Equation, ...]
    environment: Tuple[Tuple[str, Word], ...]
    depth: int
    derivation: Tuple[str, ...]

    def environment_map(self) -> Dict[str, Word]:
        return dict(self.environment)


@dataclass(frozen=True)
class TerminalSolution:
    depth: int
    environment: Tuple[Tuple[str, Word], ...]
    derivation: Tuple[str, ...]
    visited_states: int

    def environment_map(self) -> Dict[str, Word]:
        return dict(self.environment)


@dataclass(frozen=True)
class SolverRunSummary:
    visited_states: int
    emitted_terminals: int
    depth_pruned: int
    size_pruned: int
    state_limit_reached: bool


def _local_pattern(word: Word, known: Mapping[str, str]) -> Tuple[Tuple[int, bool], ...]:
    local: Dict[str, int] = {}
    next_local = 0
    output = []
    for literal in word:
        if literal.variable in known:
            token = int(known[literal.variable][1:])
        else:
            if literal.variable not in local:
                local[literal.variable] = next_local
                next_local += 1
            token = 1_000_000 + local[literal.variable]
        output.append((token, literal.inverse))
    return tuple(output)


def _canonicalize_candidate(
    equations: Tuple[Equation, ...],
    environment: Mapping[str, Word],
    seed_index: int,
    seed_flip: bool,
) -> Tuple[Tuple[object, ...], Tuple[Equation, ...], Tuple[Tuple[str, Word], ...]]:
    remaining = set(range(len(equations)))
    order: List[Tuple[int, bool]] = [(seed_index, seed_flip)]
    remaining.remove(seed_index)
    renaming: Dict[str, str] = {}
    next_index = 0
    canonical_equations: List[Equation] = []

    def rename_word(word: Word) -> Word:
        nonlocal next_index
        output = []
        for literal in word:
            if literal.variable not in renaming:
                renaming[literal.variable] = f"V{next_index}"
                next_index += 1
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

    canonical_environment = []
    for initial_variable, word in sorted(environment.items()):
        canonical_environment.append((initial_variable, rename_word(word)))

    serialization = (
        tuple(
            (
                tuple((int(literal.variable[1:]), literal.inverse) for literal in equation.left),
                tuple((int(literal.variable[1:]), literal.inverse) for literal in equation.right),
            )
            for equation in canonical_equations
        ),
        tuple(
            (
                initial,
                tuple((int(literal.variable[1:]), literal.inverse) for literal in word),
            )
            for initial, word in canonical_environment
        ),
    )
    return serialization, tuple(canonical_equations), tuple(canonical_environment)


def canonicalize_state(
    equations: Sequence[Equation], environment: Mapping[str, Word]
) -> Tuple[Tuple[Equation, ...], Tuple[Tuple[str, Word], ...]] | None:
    simplified = simplify_system(equations)
    if simplified is None:
        return None
    if not simplified:
        renaming: Dict[str, str] = {}
        next_index = 0
        canonical_environment = []
        for initial_variable, word in sorted(environment.items()):
            output = []
            for literal in word:
                if literal.variable not in renaming:
                    renaming[literal.variable] = f"V{next_index}"
                    next_index += 1
                output.append(Literal(renaming[literal.variable], literal.inverse))
            canonical_environment.append((initial_variable, tuple(output)))
        return (), tuple(canonical_environment)

    candidates = []
    for seed_index in range(len(simplified)):
        for seed_flip in (False, True):
            candidates.append(
                _canonicalize_candidate(simplified, environment, seed_index, seed_flip)
            )
    _, canonical_equations, canonical_environment = min(candidates, key=lambda item: item[0])
    return canonical_equations, canonical_environment


def _current_variables(
    equations: Sequence[Equation], environment: Mapping[str, Word]
) -> set[str]:
    output = set()
    for equation in equations:
        for word in (equation.left, equation.right):
            output.update(literal.variable for literal in word)
    for word in environment.values():
        output.update(literal.variable for literal in word)
    return output


def _fresh_variable(
    equations: Sequence[Equation], environment: Mapping[str, Word]
) -> str:
    used = _current_variables(equations, environment)
    index = 0
    while f"R{index}" in used or f"V{index}" in used:
        index += 1
    return f"R{index}"


def branch_substitutions(
    equations: Tuple[Equation, ...], environment: Mapping[str, Word]
) -> Iterator[Tuple[str, Dict[str, Word]]]:
    equation = equations[0]
    left_literal = equation.left[0]
    right_literal = equation.right[0]
    residual = Literal(_fresh_variable(equations, environment))

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


class NielsenLeviSolver:
    """Lazy bounded Nielsen-Levi solver for non-erasing word equations."""

    def __init__(self, equations: Sequence[Equation], initial_variables: Sequence[str]) -> None:
        self.original_equations = tuple(equations)
        self.initial_variables = tuple(initial_variables)
        environment = {variable: (Literal(variable),) for variable in self.initial_variables}
        canonical = canonicalize_state(self.original_equations, environment)
        self.initial_state = (
            SolverState(canonical[0], canonical[1], 0, ()) if canonical is not None else None
        )
        self.last_summary = SolverRunSummary(0, 0, 0, 0, False)

    def _valid_terminal(self, state: SolverState) -> bool:
        if state.equations:
            return False
        substituted = substitute_equations(self.original_equations, state.environment_map())
        return simplify_system(substituted) == ()

    def solve(self, limits: SolverLimits) -> Iterator[TerminalSolution]:
        if self.initial_state is None:
            self.last_summary = SolverRunSummary(0, 0, 0, 0, False)
            return

        queue = deque([self.initial_state])
        seen: set[Tuple[Tuple[Equation, ...], Tuple[Tuple[str, Word], ...]]] = set()
        terminal_signatures: set[Tuple[Tuple[str, Word], ...]] = set()
        visited_states = 0
        emitted_terminals = 0
        depth_pruned = 0
        size_pruned = 0
        state_limit_reached = False

        while queue:
            if limits.max_states is not None and visited_states >= limits.max_states:
                state_limit_reached = True
                break
            state = queue.popleft()
            visited_states += 1
            key = (state.equations, state.environment)
            if key in seen:
                continue
            seen.add(key)

            if not state.equations:
                if self._valid_terminal(state) and state.environment not in terminal_signatures:
                    terminal_signatures.add(state.environment)
                    emitted_terminals += 1
                    yield TerminalSolution(
                        state.depth,
                        state.environment,
                        state.derivation,
                        visited_states,
                    )
                    if limits.max_terminals is not None and emitted_terminals >= limits.max_terminals:
                        break
                continue

            if limits.max_depth is not None and state.depth >= limits.max_depth:
                depth_pruned += 1
                continue

            environment = state.environment_map()
            for branch_name, substitution in branch_substitutions(state.equations, environment):
                new_equations = substitute_equations(state.equations, substitution)
                new_environment = {
                    initial: substitute_word(word, substitution)
                    for initial, word in environment.items()
                }
                if limits.max_environment_word_length is not None:
                    total_length = sum(len(word) for word in new_environment.values())
                    if total_length > limits.max_environment_word_length:
                        size_pruned += 1
                        continue
                canonical = canonicalize_state(new_equations, new_environment)
                if canonical is None:
                    continue
                queue.append(
                    SolverState(
                        canonical[0],
                        canonical[1],
                        state.depth + 1,
                        state.derivation + (branch_name,),
                    )
                )

        self.last_summary = SolverRunSummary(
            visited_states,
            emitted_terminals,
            depth_pruned,
            size_pruned,
            state_limit_reached,
        )
