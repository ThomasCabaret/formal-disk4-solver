from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Dict, Iterable, Iterator, Mapping, Sequence, Tuple, Union

from .algebra import Literal, Word, inverse_word, word_to_text


@dataclass(frozen=True)
class AtomExpr:
    variable: str
    inverse: bool = False


@dataclass(frozen=True)
class ConcatExpr:
    parts: Tuple["WordExpr", ...]


@dataclass(frozen=True)
class PowerExpr:
    base: "WordExpr"
    exponent: str


WordExpr = Union[AtomExpr, ConcatExpr, PowerExpr]


def atom(variable: str, inverse: bool = False) -> WordExpr:
    return AtomExpr(variable, inverse)


def concat(*parts: WordExpr) -> WordExpr:
    flattened = []
    for part in parts:
        if isinstance(part, ConcatExpr):
            flattened.extend(part.parts)
        else:
            flattened.append(part)
    flattened = [item for item in flattened if not (isinstance(item, ConcatExpr) and not item.parts)]
    if not flattened:
        return ConcatExpr(())
    if len(flattened) == 1:
        return flattened[0]
    return ConcatExpr(tuple(flattened))


def expr_from_word(word: Sequence[Literal]) -> WordExpr:
    return concat(*(AtomExpr(item.variable, item.inverse) for item in word))


def inverse_expr(expression: WordExpr) -> WordExpr:
    if isinstance(expression, AtomExpr):
        return AtomExpr(expression.variable, not expression.inverse)
    if isinstance(expression, ConcatExpr):
        return concat(*(inverse_expr(item) for item in reversed(expression.parts)))
    if isinstance(expression, PowerExpr):
        return PowerExpr(inverse_expr(expression.base), expression.exponent)
    raise TypeError(type(expression))


def substitute_expr(expression: WordExpr, substitutions: Mapping[str, WordExpr]) -> WordExpr:
    if isinstance(expression, AtomExpr):
        replacement = substitutions.get(expression.variable, expression)
        return inverse_expr(replacement) if expression.inverse else replacement
    if isinstance(expression, ConcatExpr):
        return concat(*(substitute_expr(item, substitutions) for item in expression.parts))
    if isinstance(expression, PowerExpr):
        return PowerExpr(substitute_expr(expression.base, substitutions), expression.exponent)
    raise TypeError(type(expression))


def expression_atoms(expression: WordExpr) -> Tuple[str, ...]:
    output: list[str] = []

    def visit(item: WordExpr) -> None:
        if isinstance(item, AtomExpr):
            output.append(item.variable)
        elif isinstance(item, ConcatExpr):
            for child in item.parts:
                visit(child)
        elif isinstance(item, PowerExpr):
            visit(item.base)
        else:
            raise TypeError(type(item))

    visit(expression)
    return tuple(output)


def expression_exponents(expression: WordExpr) -> Tuple[str, ...]:
    output: list[str] = []

    def visit(item: WordExpr) -> None:
        if isinstance(item, AtomExpr):
            return
        if isinstance(item, ConcatExpr):
            for child in item.parts:
                visit(child)
            return
        if isinstance(item, PowerExpr):
            output.append(item.exponent)
            visit(item.base)
            return
        raise TypeError(type(item))

    visit(expression)
    return tuple(output)


def expression_power_depth(expression: WordExpr) -> int:
    if isinstance(expression, AtomExpr):
        return 0
    if isinstance(expression, ConcatExpr):
        return max((expression_power_depth(item) for item in expression.parts), default=0)
    if isinstance(expression, PowerExpr):
        return 1 + expression_power_depth(expression.base)
    raise TypeError(type(expression))


def expression_node_count(expression: WordExpr) -> int:
    if isinstance(expression, AtomExpr):
        return 1
    if isinstance(expression, ConcatExpr):
        return 1 + sum(expression_node_count(item) for item in expression.parts)
    if isinstance(expression, PowerExpr):
        return 1 + expression_node_count(expression.base)
    raise TypeError(type(expression))


def expand_expression(expression: WordExpr, exponents: Mapping[str, int]) -> Word:
    if isinstance(expression, AtomExpr):
        return (Literal(expression.variable, expression.inverse),)
    if isinstance(expression, ConcatExpr):
        output: list[Literal] = []
        for part in expression.parts:
            output.extend(expand_expression(part, exponents))
        return tuple(output)
    if isinstance(expression, PowerExpr):
        count = int(exponents[expression.exponent])
        if count < 0:
            raise ValueError(f"Negative exponent {expression.exponent}={count}")
        base = expand_expression(expression.base, exponents)
        return tuple(base * count)
    raise TypeError(type(expression))


def expression_to_dict(expression: WordExpr) -> Dict[str, object]:
    if isinstance(expression, AtomExpr):
        return {
            "type": "atom",
            "variable": expression.variable,
            "inverse": expression.inverse,
        }
    if isinstance(expression, ConcatExpr):
        return {
            "type": "concat",
            "parts": [expression_to_dict(item) for item in expression.parts],
        }
    if isinstance(expression, PowerExpr):
        return {
            "type": "power",
            "base": expression_to_dict(expression.base),
            "exponent": expression.exponent,
        }
    raise TypeError(type(expression))


def expression_to_text(expression: WordExpr) -> str:
    if isinstance(expression, AtomExpr):
        return f"{expression.variable}^-1" if expression.inverse else expression.variable
    if isinstance(expression, ConcatExpr):
        if not expression.parts:
            return "1"
        return " ".join(
            f"({expression_to_text(item)})" if isinstance(item, ConcatExpr) else expression_to_text(item)
            for item in expression.parts
        )
    if isinstance(expression, PowerExpr):
        return f"({expression_to_text(expression.base)})^{expression.exponent}"
    raise TypeError(type(expression))


def _rename_expression(
    expression: WordExpr,
    atom_names: Dict[str, str],
    exponent_names: Dict[str, str],
) -> WordExpr:
    if isinstance(expression, AtomExpr):
        if expression.variable not in atom_names:
            atom_names[expression.variable] = f"T{len(atom_names)}"
        return AtomExpr(atom_names[expression.variable], expression.inverse)
    if isinstance(expression, ConcatExpr):
        return concat(*(_rename_expression(item, atom_names, exponent_names) for item in expression.parts))
    if isinstance(expression, PowerExpr):
        if expression.exponent not in exponent_names:
            exponent_names[expression.exponent] = f"n{len(exponent_names)}"
        return PowerExpr(
            _rename_expression(expression.base, atom_names, exponent_names),
            exponent_names[expression.exponent],
        )
    raise TypeError(type(expression))


def canonicalize_environment(
    environment: Mapping[str, WordExpr],
    exponent_minimums: Mapping[str, int],
) -> Tuple[Tuple[Tuple[str, WordExpr], ...], Tuple[Tuple[str, int], ...]]:
    atom_names: Dict[str, str] = {}
    exponent_names: Dict[str, str] = {}
    canonical_environment = []
    for initial, expression in sorted(environment.items()):
        canonical_environment.append(
            (initial, _rename_expression(expression, atom_names, exponent_names))
        )
    canonical_minimums = tuple(
        sorted(
            (exponent_names[name], int(minimum))
            for name, minimum in exponent_minimums.items()
            if name in exponent_names
        )
    )
    return tuple(canonical_environment), canonical_minimums


@dataclass(frozen=True)
class ExactFormalFamily:
    family_id: int
    kind: str
    environment: Tuple[Tuple[str, WordExpr], ...]
    exponent_minimums: Tuple[Tuple[str, int], ...]
    trace: Tuple[str, ...]
    residual_graph_nodes: int
    validation_assignments: Tuple[Tuple[Tuple[str, int], ...], ...] = ()

    def environment_map(self) -> Dict[str, WordExpr]:
        return dict(self.environment)

    def exponent_minimum_map(self) -> Dict[str, int]:
        return dict(self.exponent_minimums)

    @property
    def power_depth(self) -> int:
        return max((expression_power_depth(expr) for _, expr in self.environment), default=0)

    def to_dict(self) -> Dict[str, object]:
        return {
            "family_id": self.family_id,
            "kind": self.kind,
            "environment": {
                variable: {
                    "text": expression_to_text(expression),
                    "ast": expression_to_dict(expression),
                }
                for variable, expression in self.environment
            },
            "exponent_minimums": dict(self.exponent_minimums),
            "trace": list(self.trace),
            "residual_graph_nodes_at_emission": self.residual_graph_nodes,
            "power_depth": self.power_depth,
            "validation_assignments": [dict(item) for item in self.validation_assignments],
        }


@dataclass(frozen=True)
class FamilyExpansionPolicy:
    kind: str = "none"
    maximum_exponent: int = 1
    max_specializations: int | None = 64

    def __post_init__(self) -> None:
        if self.kind not in {"none", "minimum", "fixed", "range"}:
            raise ValueError("family expansion policy must be none, minimum, fixed, or range")
        if self.maximum_exponent < 0:
            raise ValueError("maximum_exponent must be nonnegative")


@dataclass(frozen=True)
class FamilySpecialization:
    family_id: int
    family_kind: str
    exponent_assignment: Tuple[Tuple[str, int], ...]
    environment: Tuple[Tuple[str, Word], ...]
    trace: Tuple[str, ...]

    def environment_map(self) -> Dict[str, Word]:
        return dict(self.environment)

    def to_dict(self) -> Dict[str, object]:
        return {
            "family_id": self.family_id,
            "family_kind": self.family_kind,
            "exponent_assignment": dict(self.exponent_assignment),
            "environment": {
                variable: word_to_text(word) for variable, word in self.environment
            },
            "trace": list(self.trace),
        }


def _assignments_for_policy(
    minimums: Mapping[str, int], policy: FamilyExpansionPolicy
) -> Iterator[Tuple[Tuple[str, int], ...]]:
    if not minimums:
        yield ()
        return
    if policy.kind == "none":
        return
    names = tuple(sorted(minimums))
    choices = []
    for name in names:
        minimum = int(minimums[name])
        if policy.kind == "minimum":
            values = (minimum,)
        elif policy.kind == "fixed":
            if policy.maximum_exponent < minimum:
                return
            values = (policy.maximum_exponent,)
        else:
            if policy.maximum_exponent < minimum:
                return
            values = tuple(range(minimum, policy.maximum_exponent + 1))
        choices.append(values)
    emitted = 0
    for values in product(*choices):
        if policy.max_specializations is not None and emitted >= policy.max_specializations:
            return
        emitted += 1
        yield tuple(zip(names, values))


def expand_family(
    family: ExactFormalFamily,
    policy: FamilyExpansionPolicy,
) -> Iterator[FamilySpecialization]:
    minimums = family.exponent_minimum_map()
    for assignment in _assignments_for_policy(minimums, policy):
        exponent_map = dict(assignment)
        environment = tuple(
            (variable, expand_expression(expression, exponent_map))
            for variable, expression in family.environment
        )
        yield FamilySpecialization(
            family_id=family.family_id,
            family_kind=family.kind,
            exponent_assignment=assignment,
            environment=environment,
            trace=family.trace,
        )
