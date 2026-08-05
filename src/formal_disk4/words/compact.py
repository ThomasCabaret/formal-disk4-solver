from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Mapping, Sequence, Tuple

from .algebra import Equation, Literal, Word

# A token packs both pieces of data used in the residual graph:
#   token >> 1 : dense variable identifier
#   token & 1  : inverse flag
# Flipping a literal is therefore a single XOR operation.
Token = int
CompactWord = Tuple[Token, ...]
CompactEquation = Tuple[CompactWord, CompactWord]
CompactSubstitution = Tuple[int, CompactWord]
CompactTransition = Tuple[CompactWord, ...]


def token(variable: int, inverse: bool = False) -> Token:
    return (variable << 1) | int(inverse)


def variable_of(item: Token) -> int:
    return item >> 1


def is_inverse(item: Token) -> bool:
    return bool(item & 1)


def inverse_word(word: Sequence[Token]) -> CompactWord:
    return tuple(item ^ 1 for item in reversed(word))


def identity_word(variable: int) -> CompactWord:
    return (token(variable),)


def word_to_text(word: Sequence[Token]) -> str:
    if not word:
        return "1"
    return " ".join(
        f"V{item >> 1}^-1" if item & 1 else f"V{item >> 1}"
        for item in word
    )


def equation_to_text(equation: CompactEquation) -> str:
    return f"{word_to_text(equation[0])} = {word_to_text(equation[1])}"


@dataclass(frozen=True)
class CanonicalResidual:
    equations: Tuple[CompactEquation, ...]
    variable_count: int
    # Dense raw-variable id -> canonical id. Missing raw variables are -1.
    rename: Tuple[int, ...]
    signature: Tuple[object, ...]

    @property
    def variables(self) -> range:
        return range(self.variable_count)


@dataclass(frozen=True)
class LoopPlan:
    fixed_variables: Tuple[int, ...]
    pivots: Tuple[Tuple[int, CompactWord, CompactWord], ...]


def encode_problem(
    equations: Sequence[Equation], initial_variables: Sequence[str]
) -> tuple[Tuple[CompactEquation, ...], Tuple[int, ...], Tuple[str, ...]]:
    names = set(initial_variables)
    for equation in equations:
        names.update(item.variable for item in equation.left)
        names.update(item.variable for item in equation.right)
    ordered_names = tuple(sorted(names))
    name_to_id = {name: index for index, name in enumerate(ordered_names)}

    def encode_word(word: Word) -> CompactWord:
        return tuple((name_to_id[item.variable] << 1) | int(item.inverse) for item in word)

    compact_equations = tuple(
        (encode_word(equation.left), encode_word(equation.right))
        for equation in equations
    )
    initial_ids = tuple(name_to_id[name] for name in initial_variables)
    return compact_equations, initial_ids, ordered_names


def simplify_equation(equation: CompactEquation) -> CompactEquation | bool | None:
    """Cancel common ends; reject only empty=nonempty under non-erasure.

    FILTER JUSTIFICATION (theorem): cancellation and the non-erasing
    contradiction are the first step of docs/six_structural_results.tex,
    Theorem 1.4.
    """
    left, right = equation
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
    return left[prefix:left_end], right[prefix:right_end]


def simplify_system(
    equations: Sequence[CompactEquation],
) -> Tuple[CompactEquation, ...] | None:
    output: list[CompactEquation] = []
    seen: set[CompactEquation] = set()
    for equation in equations:
        simplified = simplify_equation(equation)
        if simplified is False:
            return None
        if simplified is None:
            continue
        reverse = (simplified[1], simplified[0])
        key = min(simplified, reverse)
        if key not in seen:
            seen.add(key)
            output.append(simplified)
    return tuple(output)


def _local_pattern(
    word: CompactWord,
    renaming: Sequence[int],
    known_count: int,
) -> CompactWord:
    local = [-1] * len(renaming)
    local_count = 0
    output: list[int] = []
    append = output.append
    for item in word:
        raw_variable = item >> 1
        canonical_variable = renaming[raw_variable]
        if canonical_variable < 0:
            canonical_variable = local[raw_variable]
            if canonical_variable < 0:
                canonical_variable = known_count + local_count
                local[raw_variable] = canonical_variable
                local_count += 1
        append((canonical_variable << 1) | (item & 1))
    return tuple(output)


def _canonicalize_candidate(
    equations: Tuple[CompactEquation, ...],
    all_variables: Sequence[int],
    raw_variable_capacity: int,
    seed_index: int,
    seed_flip: bool,
) -> tuple[Tuple[object, ...], CanonicalResidual]:
    remaining = set(range(len(equations)))
    order: list[tuple[int, bool]] = [(seed_index, seed_flip)]
    remaining.remove(seed_index)
    renaming = [-1] * raw_variable_capacity
    next_variable = 0
    canonical_equations: list[CompactEquation] = []
    order_index = 0

    def rename_word(word: CompactWord) -> CompactWord:
        nonlocal next_variable
        output: list[int] = []
        append = output.append
        for item in word:
            raw_variable = item >> 1
            canonical_variable = renaming[raw_variable]
            if canonical_variable < 0:
                canonical_variable = next_variable
                next_variable += 1
                renaming[raw_variable] = canonical_variable
            append((canonical_variable << 1) | (item & 1))
        return tuple(output)

    while order_index < len(order):
        equation_index, flip = order[order_index]
        order_index += 1
        left, right = equations[equation_index]
        if flip:
            left, right = right, left
        canonical_equations.append((rename_word(left), rename_word(right)))
        if not remaining:
            continue

        selected: tuple[object, ...] | None = None
        selected_index = -1
        selected_flip = False
        for candidate_index in remaining:
            candidate_left, candidate_right = equations[candidate_index]
            for candidate_flip in (False, True):
                if candidate_flip:
                    candidate_left, candidate_right = candidate_right, candidate_left
                choice: tuple[object, ...] = (
                    _local_pattern(candidate_left, renaming, next_variable),
                    _local_pattern(candidate_right, renaming, next_variable),
                    candidate_index,
                    candidate_flip,
                )
                if selected is None or choice < selected:
                    selected = choice
                    selected_index = candidate_index
                    selected_flip = candidate_flip
                if candidate_flip:
                    candidate_left, candidate_right = candidate_right, candidate_left
        remaining.remove(selected_index)
        order.append((selected_index, selected_flip))

    for raw_variable in all_variables:
        if renaming[raw_variable] < 0:
            renaming[raw_variable] = next_variable
            next_variable += 1

    canonical_tuple = tuple(canonical_equations)
    signature: Tuple[object, ...] = (canonical_tuple, next_variable)
    return signature, CanonicalResidual(
        equations=canonical_tuple,
        variable_count=next_variable,
        rename=tuple(renaming),
        signature=signature,
    )


def canonicalize_residual(
    equations: Sequence[CompactEquation],
    all_variables: Sequence[int],
    raw_variable_capacity: int,
) -> CanonicalResidual | None:
    simplified = simplify_system(equations)
    if simplified is None:
        return None
    if not simplified:
        renaming = [-1] * raw_variable_capacity
        for index, raw_variable in enumerate(all_variables):
            renaming[raw_variable] = index
        signature: Tuple[object, ...] = ((), len(all_variables))
        return CanonicalResidual(
            equations=(),
            variable_count=len(all_variables),
            rename=tuple(renaming),
            signature=signature,
        )

    equations_tuple = tuple(simplified)
    best: tuple[Tuple[object, ...], CanonicalResidual] | None = None
    for seed_index in range(len(equations_tuple)):
        for seed_flip in (False, True):
            candidate = _canonicalize_candidate(
                equations_tuple,
                all_variables,
                raw_variable_capacity,
                seed_index,
                seed_flip,
            )
            if best is None or candidate[0] < best[0]:
                best = candidate
    assert best is not None
    return best[1]


def variables_in_words(words: Sequence[CompactWord]) -> Tuple[int, ...]:
    return tuple(sorted({item >> 1 for word in words for item in word}))



def ordered_raw_variables(variables: Sequence[int], parent_variable_count: int) -> Tuple[int, ...]:
    """Match the legacy lexical order of V* variables and the single fresh R*."""

    def legacy_name(variable: int) -> str:
        return f"R{parent_variable_count}" if variable == parent_variable_count else f"V{variable}"

    return tuple(sorted(set(variables), key=legacy_name))


def branch_substitutions(
    equations: Tuple[CompactEquation, ...], variable_count: int
) -> Iterator[Tuple[str, CompactSubstitution]]:
    """Enumerate the complete non-erasing prefix branches.

    FILTER JUSTIFICATION (theorem): docs/six_structural_results.tex, Theorem
    1.4. The same-variable/opposite-orientation case additionally uses Theorem
    1.5; packed tokens form fixed-point-free inverse pairs, and signed canonical
    renamings preserve that involution.
    """
    left, right = equations[0]
    left_literal = left[0]
    right_literal = right[0]
    left_variable = left_literal >> 1
    right_variable = right_literal >> 1
    residual = token(variable_count)

    if left_variable == right_variable:
        if (left_literal & 1) == (right_literal & 1):
            raise RuntimeError("Identical literals should have been cancelled")
        # Theorem 1.5 gives the unique factorization X = R mu(R).
        yield "involutive_palindrome", (left_variable, (residual, residual ^ 1))
        return

    equal_orientation = bool((left_literal ^ right_literal) & 1)
    yield "equal_length", (
        left_variable,
        (token(right_variable, equal_orientation),),
    )

    oriented_right = (left_literal, residual)
    right_positive = inverse_word(oriented_right) if right_literal & 1 else oriented_right
    yield "left_strictly_shorter", (right_variable, right_positive)

    oriented_left = (right_literal, residual)
    left_positive = inverse_word(oriented_left) if left_literal & 1 else oriented_left
    yield "right_strictly_shorter", (left_variable, left_positive)


def substitute_equations(
    equations: Sequence[CompactEquation], substitution: CompactSubstitution
) -> Tuple[CompactEquation, ...]:
    target, replacement = substitution
    inverse_replacement = inverse_word(replacement)

    def substitute(word: CompactWord) -> CompactWord:
        output: list[int] = []
        extend = output.extend
        append = output.append
        for item in word:
            if item >> 1 != target:
                append(item)
            elif item & 1:
                extend(inverse_replacement)
            else:
                extend(replacement)
        return tuple(output)

    return tuple((substitute(left), substitute(right)) for left, right in equations)


def transition_words(variable_count: int, substitution: CompactSubstitution) -> Tuple[CompactWord, ...]:
    target, replacement = substitution
    return tuple(replacement if variable == target else identity_word(variable) for variable in range(variable_count))


def edge_transition(
    parent_variable_count: int,
    substitution: CompactSubstitution,
    child_renaming: Sequence[int],
) -> CompactTransition:
    target, replacement = substitution

    def rename_word(word: CompactWord) -> CompactWord:
        return tuple(
            (child_renaming[item >> 1] << 1) | (item & 1)
            for item in word
        )

    return tuple(
        rename_word(replacement if variable == target else identity_word(variable))
        for variable in range(parent_variable_count)
    )


def substitute_word(word: CompactWord, transition: CompactTransition) -> CompactWord:
    output: list[int] = []
    extend = output.extend
    for item in word:
        replacement = transition[item >> 1]
        extend(inverse_word(replacement) if item & 1 else replacement)
    return tuple(output)


def compose_transitions(
    domain_variable_count: int, transitions: Sequence[CompactTransition]
) -> CompactTransition:
    current: CompactTransition = tuple(identity_word(variable) for variable in range(domain_variable_count))
    for transition in transitions:
        current = tuple(substitute_word(word, transition) for word in current)
    return current


def transition_signature(transition: CompactTransition) -> CompactTransition:
    return transition


def transition_text(transition: CompactTransition) -> Tuple[Tuple[str, str], ...]:
    return tuple((f"V{index}", word_to_text(word)) for index, word in enumerate(transition))


def classify_fixed_context_loop(
    variable_count: int, transition: CompactTransition
) -> tuple[LoopPlan | None, str]:
    """Recognize exactly the unary fixed-context loops of Theorem 1.6.

    This local classification does not establish global exhaustiveness when
    distinct loops coexist. ExactPartialWordSolver separately audits residual
    SCCs using Theorem 1.7 and Corollary 8.2 of
    docs/six_structural_results.tex.
    """
    variable_set = set(range(variable_count))
    codomain = {item >> 1 for word in transition for item in word}
    if not codomain <= variable_set:
        return None, "cycle introduces a fresh residual parameter on every iteration"

    fixed = {
        variable
        for variable in range(variable_count)
        if transition[variable] == identity_word(variable)
    }
    pivots: list[tuple[int, CompactWord, CompactWord]] = []
    for variable in range(variable_count):
        word = transition[variable]
        if variable in fixed:
            continue
        core_positions = [
            index
            for index, item in enumerate(word)
            if item >> 1 == variable and not (item & 1)
        ]
        if len(core_positions) != 1:
            return None, f"V{variable} is not preserved exactly once by the cycle"
        if any(item >> 1 == variable and item & 1 for item in word):
            return None, f"V{variable} is inverted inside its cycle image"
        core = core_positions[0]
        prefix = word[:core]
        suffix = word[core + 1 :]
        context_variables = {item >> 1 for item in prefix + suffix}
        if not context_variables <= fixed:
            return None, f"V{variable} depends on another evolving variable"
        if not prefix and not suffix:
            return None, f"V{variable} changes only by an unsupported renaming"
        pivots.append((variable, prefix, suffix))

    if not pivots:
        return None, "cycle has no expanding fixed-context variable"
    return LoopPlan(tuple(sorted(fixed)), tuple(pivots)), "supported_fixed_context_power"


def to_public_word(word: CompactWord) -> Word:
    return tuple(Literal(f"V{item >> 1}", bool(item & 1)) for item in word)


def to_public_equation(equation: CompactEquation) -> Equation:
    return Equation(to_public_word(equation[0]), to_public_word(equation[1]))


def public_simplify_system(equations: Sequence[Equation]) -> Tuple[Equation, ...] | None:
    compact, _initial_ids, names = encode_problem(
        equations,
        tuple(sorted({item.variable for eq in equations for item in (*eq.left, *eq.right)})),
    )
    simplified = simplify_system(compact)
    if simplified is None:
        return None
    return tuple(
        Equation(
            tuple(Literal(names[item >> 1], bool(item & 1)) for item in left),
            tuple(Literal(names[item >> 1], bool(item & 1)) for item in right),
        )
        for left, right in simplified
    )


def public_classify_fixed_context_loop(
    variables: Sequence[str], transition: Mapping[str, Word]
) -> tuple[object | None, str]:
    variable_index = {name: index for index, name in enumerate(variables)}

    def encode_public_word(word: Word) -> CompactWord:
        return tuple((variable_index[item.variable] << 1) | int(item.inverse) for item in word)

    compact_transition = tuple(
        encode_public_word(transition.get(variable, (Literal(variable),)))
        for variable in variables
    )
    plan, reason = classify_fixed_context_loop(len(variables), compact_transition)
    if plan is None:
        return None, reason
    # Import lazily to avoid exposing the compact representation through the
    # compatibility helper used by older tests and external scripts.
    public_plan = (
        tuple(variables[index] for index in plan.fixed_variables),
        tuple(
            (
                variables[variable],
                tuple(Literal(variables[item >> 1], bool(item & 1)) for item in prefix),
                tuple(Literal(variables[item >> 1], bool(item & 1)) for item in suffix),
            )
            for variable, prefix, suffix in plan.pivots
        ),
    )
    return public_plan, reason
