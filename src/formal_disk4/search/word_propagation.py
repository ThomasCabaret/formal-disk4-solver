"""Small deterministic Levi propagator; ambiguity is residual, never rejection.

Words alternate nonempty curve factors and interior corner turns. Reversal and
geometric mirror are distinct commuting involutions. Both negate corner turns;
only reversal reverses token order. Atomic self-involutions remain residual
constraints for the existing complete word solver, not impossible equations.
"""
from dataclasses import dataclass
from typing import Callable

from .linear import Form

REVERSE = 1
MIRROR = 2


@dataclass(frozen=True)
class Factor:
    index: int
    transform: int = 0


@dataclass(frozen=True)
class Corner:
    index: int
    sign: int = 1


Token = Factor | Corner
Word = tuple[Token, ...]


def transform_word(word: Word, transform: int) -> Word:
    sequence = reversed(word) if transform & REVERSE else word
    sign = -1 if transform in (REVERSE, MIRROR) else 1
    return tuple(Factor(t.index, t.transform ^ transform) if isinstance(t, Factor)
                 else Corner(t.index, t.sign * sign) for t in sequence)


@dataclass(frozen=True)
class WordState:
    equations: tuple[tuple[Word, Word], ...]
    lengths: tuple[Form, ...]
    replacements: tuple[tuple[int, Word], ...]
    relations: tuple[tuple[int, int, int], ...]
    point_count: int
    symmetries: int = 0


@dataclass(frozen=True)
class Propagation:
    feasible: bool
    point_count: int
    relations: tuple[tuple[int, int, int], ...]
    splits: int = 0
    unions: int = 0
    residual_equations: int = 0
    limited: bool = False
    reason: str = ""
    state: WordState | None = None
    ambiguous: Form | None = None


def propagate(equations: tuple[tuple[Word, Word], ...], lengths: tuple[Form, ...],
              point_count: int, compare: Callable[[Form, Form], int | None], *,
              max_steps: int = 96, max_tokens: int = 2048,
              resume: WordState | None = None) -> Propagation:
    """Propagate only forced cases. compare is an exact entailment query.

Operational bounds stop this optional propagator, NOT the search branch. Its
original equations still go to the production solver. Derived factors and
corners are local existential variables, with no chosen numerical length.
    """
    pending = list(resume.equations if resume else equations)
    sizes = list(resume.lengths if resume else lengths)
    replacements: dict[int, Word] = dict(resume.replacements) if resume else {}
    relations = list(resume.relations) if resume else []
    point_count = resume.point_count if resume else point_count
    splits = unions = 0
    symmetries = resume.symmetries if resume else 0
    ambiguous = None

    def result(feasible=True, limited=False, reason=""):
        return Propagation(feasible, point_count, tuple(relations), splits, unions,
                           sum(bool(a or b) for a, b in pending) + symmetries, limited, reason,
                           WordState(tuple(pending), tuple(sizes), tuple(replacements.items()),
                                     tuple(relations), point_count, symmetries), ambiguous)

    def expand(word):
        # Iterative expansion avoids recursion limits on long refinement chains.
        stack, output = list(reversed(word)), []
        while stack:
            t = stack.pop()
            if isinstance(t, Factor) and t.index in replacements:
                stack.extend(reversed(transform_word(replacements[t.index], t.transform)))
            else:
                output.append(t)
            if len(stack) + len(output) > max_tokens:
                raise OverflowError
        return tuple(output)

    try:
        for _ in range(max_steps):
            changed = False
            ambiguous = None
            for i, (left, right) in enumerate(pending):
                left, right = expand(left), expand(right)
                pending[i] = left, right
                if not left and not right:
                    continue
                if not left or not right:
                    if any(isinstance(t, Factor) for t in left + right):
                        return result(False, reason="nonempty_factor_equals_empty")
                    # A point-only residual is not interpreted as an empty arc.
                    continue
                # Prefix then suffix; either end can expose a forced match.
                for tail in (False, True):
                    a, b = (left[-1], right[-1]) if tail else (left[0], right[0])
                    if isinstance(a, Corner) and isinstance(b, Corner):
                        relations.append((a.index, b.index, a.sign * b.sign))
                        pending[i] = ((left[:-1], right[:-1]) if tail else (left[1:], right[1:]))
                        changed = True
                        break
                    if not isinstance(a, Factor) or not isinstance(b, Factor):
                        continue
                    relation = compare(sizes[a.index], sizes[b.index])
                    if relation is None:
                        if ambiguous is None:
                            ambiguous = sizes[a.index] - sizes[b.index]
                        continue
                    if relation == 0:
                        if a.index != b.index:
                            source, target = (a, b) if a.index > b.index else (b, a)
                            replacements[source.index] = (Factor(target.index, source.transform ^ target.transform),)
                            unions += 1
                        elif a.transform != b.transform:
                            symmetries += 1
                        pending[i] = ((left[:-1], right[:-1]) if tail else (left[1:], right[1:]))
                    else:
                        short, long = (a, b) if relation < 0 else (b, a)
                        if short.index == long.index:
                            raise ValueError("Inconsistent length comparison for one factor")
                        remainder = Factor(len(sizes))
                        sizes.append(sizes[long.index] - sizes[short.index])
                        point = Corner(point_count)
                        point_count += 1
                        split = (remainder, point, short) if tail else (short, point, remainder)
                        replacements[long.index] = transform_word(split, long.transform)
                        splits += 1
                    changed = True
                    break
                if changed:
                    break
            if not changed:
                return result()
        return result(limited=True)
    except OverflowError:
        return result(limited=True)
