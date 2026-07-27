from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Dict, Iterable, Mapping, Sequence, Tuple


def as_fraction(value: int | float | str | Fraction) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value, 1)
    if isinstance(value, float):
        return Fraction(str(value))
    return Fraction(value)


def fraction_text(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def fraction_record(value: Fraction) -> Dict[str, object]:
    return {
        "numerator": value.numerator,
        "denominator": value.denominator,
        "text": fraction_text(value),
        "float": float(value),
    }


@dataclass(frozen=True)
class LinearExpression:
    constant: Fraction = Fraction(0)
    terms: Tuple[Tuple[str, Fraction], ...] = ()

    @staticmethod
    def parameter(name: str) -> "LinearExpression":
        return LinearExpression(Fraction(0), ((name, Fraction(1)),))

    @staticmethod
    def value(value: int | float | str | Fraction) -> "LinearExpression":
        return LinearExpression(as_fraction(value), ())

    def normalized(self) -> "LinearExpression":
        combined: Dict[str, Fraction] = {}
        for name, coefficient in self.terms:
            coefficient = as_fraction(coefficient)
            if coefficient:
                combined[name] = combined.get(name, Fraction(0)) + coefficient
        return LinearExpression(
            as_fraction(self.constant),
            tuple(sorted((name, coefficient) for name, coefficient in combined.items() if coefficient)),
        )

    def __add__(self, other: "LinearExpression") -> "LinearExpression":
        return LinearExpression(
            self.constant + other.constant,
            self.terms + other.terms,
        ).normalized()

    def __sub__(self, other: "LinearExpression") -> "LinearExpression":
        return self + (-other)

    def __neg__(self) -> "LinearExpression":
        return LinearExpression(
            -self.constant,
            tuple((name, -coefficient) for name, coefficient in self.terms),
        )

    def scale(self, coefficient: int | float | str | Fraction) -> "LinearExpression":
        factor = as_fraction(coefficient)
        return LinearExpression(
            self.constant * factor,
            tuple((name, value * factor) for name, value in self.terms),
        ).normalized()

    @property
    def exact_value(self) -> Fraction | None:
        normalized = self.normalized()
        return normalized.constant if not normalized.terms else None

    @property
    def free_parameters(self) -> Tuple[str, ...]:
        return tuple(name for name, _coefficient in self.normalized().terms)

    def to_text(self) -> str:
        expression = self.normalized()
        pieces: list[Tuple[int, str]] = []
        if expression.constant:
            pieces.append((1 if expression.constant > 0 else -1, fraction_text(abs(expression.constant))))
        for name, coefficient in expression.terms:
            sign = 1 if coefficient > 0 else -1
            magnitude = abs(coefficient)
            term = name if magnitude == 1 else f"{fraction_text(magnitude)}*{name}"
            pieces.append((sign, term))
        if not pieces:
            return "0"
        output = ""
        for index, (sign, text) in enumerate(pieces):
            if index == 0:
                output = text if sign > 0 else f"-{text}"
            else:
                output += f" {'+' if sign > 0 else '-'} {text}"
        return output

    def to_dict(self) -> Dict[str, object]:
        expression = self.normalized()
        value = expression.exact_value
        return {
            "text": expression.to_text(),
            "constant": fraction_record(expression.constant),
            "terms": [
                {"parameter": name, "coefficient": fraction_record(coefficient)}
                for name, coefficient in expression.terms
            ],
            "free_parameters": list(expression.free_parameters),
            "exact": value is not None,
            "exact_value": fraction_record(value) if value is not None else None,
        }


@dataclass(frozen=True)
class ExactLinearSolution:
    variable_order: Tuple[str, ...]
    expressions: Tuple[Tuple[str, LinearExpression], ...]
    free_parameters: Tuple[str, ...]
    rank: int
    equation_count: int

    def expression_map(self) -> Dict[str, LinearExpression]:
        return dict(self.expressions)

    def to_dict(self) -> Dict[str, object]:
        return {
            "variables": list(self.variable_order),
            "rank": self.rank,
            "equation_count": self.equation_count,
            "free_parameters": list(self.free_parameters),
            "expressions": {
                name: expression.to_dict() for name, expression in self.expressions
            },
        }


class ExactLinearInfeasible(ValueError):
    pass


def solve_exact_linear_system(
    variable_names: Sequence[str],
    equations: Iterable[Tuple[Mapping[str, int | float | str | Fraction], int | float | str | Fraction]],
) -> ExactLinearSolution:
    variables = tuple(variable_names)
    column = {name: index for index, name in enumerate(variables)}
    rows: list[list[Fraction]] = []
    for coefficients, rhs in equations:
        row = [Fraction(0) for _ in range(len(variables) + 1)]
        for name, coefficient in coefficients.items():
            if name not in column:
                raise KeyError(f"Unknown linear variable {name}")
            row[column[name]] += as_fraction(coefficient)
        row[-1] = as_fraction(rhs)
        if any(row[:-1]) or row[-1]:
            rows.append(row)

    pivot_rows: Dict[int, int] = {}
    current_row = 0
    for pivot_column in range(len(variables)):
        pivot = next(
            (row_index for row_index in range(current_row, len(rows)) if rows[row_index][pivot_column]),
            None,
        )
        if pivot is None:
            continue
        rows[current_row], rows[pivot] = rows[pivot], rows[current_row]
        pivot_value = rows[current_row][pivot_column]
        rows[current_row] = [value / pivot_value for value in rows[current_row]]
        for row_index in range(len(rows)):
            if row_index == current_row:
                continue
            factor = rows[row_index][pivot_column]
            if factor:
                rows[row_index] = [
                    value - factor * pivot_value
                    for value, pivot_value in zip(rows[row_index], rows[current_row])
                ]
        pivot_rows[pivot_column] = current_row
        current_row += 1
        if current_row == len(rows):
            break

    for row in rows:
        if not any(row[:-1]) and row[-1]:
            raise ExactLinearInfeasible("Exact linear equations are inconsistent")

    free_columns = [index for index in range(len(variables)) if index not in pivot_rows]
    free_parameters = tuple(variables[index] for index in free_columns)
    expressions: Dict[str, LinearExpression] = {
        variables[index]: LinearExpression.parameter(variables[index]) for index in free_columns
    }
    for pivot_column, row_index in sorted(pivot_rows.items(), reverse=True):
        row = rows[row_index]
        expression = LinearExpression.value(row[-1])
        for free_column in free_columns:
            coefficient = row[free_column]
            if coefficient:
                expression = expression - LinearExpression.parameter(variables[free_column]).scale(coefficient)
        expressions[variables[pivot_column]] = expression.normalized()

    return ExactLinearSolution(
        variable_order=variables,
        expressions=tuple((name, expressions[name]) for name in variables),
        free_parameters=free_parameters,
        rank=len(pivot_rows),
        equation_count=len(rows),
    )
