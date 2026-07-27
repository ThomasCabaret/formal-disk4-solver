from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Sequence, Tuple


@dataclass(frozen=True, order=True)
class Literal:
    variable: str
    inverse: bool = False

    def flipped(self) -> "Literal":
        return Literal(self.variable, not self.inverse)

    def to_text(self) -> str:
        return f"{self.variable}^-1" if self.inverse else self.variable


Word = Tuple[Literal, ...]


@dataclass(frozen=True, order=True)
class Equation:
    left: Word
    right: Word

    def to_text(self) -> str:
        return f"{word_to_text(self.left)} = {word_to_text(self.right)}"


def word_to_text(word: Sequence[Literal]) -> str:
    return "1" if not word else " ".join(literal.to_text() for literal in word)


def inverse_word(word: Sequence[Literal]) -> Word:
    return tuple(literal.flipped() for literal in reversed(word))


def substitute_word(word: Sequence[Literal], substitution: Mapping[str, Word]) -> Word:
    output: list[Literal] = []
    for literal in word:
        replacement = substitution.get(literal.variable, (Literal(literal.variable),))
        if literal.inverse:
            replacement = inverse_word(replacement)
        output.extend(replacement)
    return tuple(output)


def substitute_equations(
    equations: Sequence[Equation], substitution: Mapping[str, Word]
) -> Tuple[Equation, ...]:
    return tuple(
        Equation(
            substitute_word(equation.left, substitution),
            substitute_word(equation.right, substitution),
        )
        for equation in equations
    )


def simplify_equation(equation: Equation) -> Equation | bool | None:
    left = list(equation.left)
    right = list(equation.right)
    while left and right and left[0] == right[0]:
        left.pop(0)
        right.pop(0)
    while left and right and left[-1] == right[-1]:
        left.pop()
        right.pop()
    if not left and not right:
        return None
    if not left or not right:
        return False
    return Equation(tuple(left), tuple(right))


def simplify_system(equations: Sequence[Equation]) -> Tuple[Equation, ...] | None:
    output: list[Equation] = []
    seen: set[Tuple[Word, Word]] = set()
    for equation in equations:
        simplified = simplify_equation(equation)
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


def variables_in_words(words: Iterable[Sequence[Literal]]) -> set[str]:
    return {literal.variable for word in words for literal in word}
