from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import time
from typing import Iterable, Sequence, Tuple

import numpy as np
from scipy.optimize import linprog

from formal_disk4.constraints.rational_lp import maximize_free_variables


@dataclass(frozen=True)
class HybridLinearResult:
    feasible: bool
    margin: Fraction | None
    status: str
    exact_certificate_used: bool


@dataclass(frozen=True)
class LinearConstraint:
    coefficients: Tuple[Fraction, ...]
    rhs: Fraction

    @staticmethod
    def build(
        coefficients: Sequence[int | Fraction],
        rhs: int | Fraction = 0,
    ) -> "LinearConstraint":
        return LinearConstraint(
            tuple(Fraction(value) for value in coefficients),
            Fraction(rhs),
        )


class HybridMarginOracle:
    """Fast floating screen with exact rational rejection certificates.

    The caller supplies linear equalities, non-strict inequalities and one
    non-negative margin variable to maximize. A case is rejected only when the
    exact simplex proves that the best margin is not positive. Floating-point
    errors can therefore only lose pruning opportunities, never valid cases.
    """

    def __init__(self, tolerance: float = 1e-9, cache_size: int = 100_000) -> None:
        self.tolerance = float(tolerance)
        self.cache_size = int(cache_size)
        self.calls = 0
        self.cache_hits = 0
        self.exact_calls = 0
        self.elapsed_seconds = 0.0
        self.float_seconds = 0.0
        self.exact_seconds = 0.0
        self._cache: dict[tuple[object, ...], HybridLinearResult] = {}

    @staticmethod
    def _canonical_constraint(
        constraint: LinearConstraint,
    ) -> tuple[tuple[Fraction, ...], Fraction]:
        coefficients = constraint.coefficients
        rhs = constraint.rhs
        first = next((value for value in coefficients if value), None)
        if first is not None and first < 0:
            coefficients = tuple(-value for value in coefficients)
            rhs = -rhs
        return coefficients, rhs

    def analyze(
        self,
        *,
        variable_domains: Sequence[str],
        equalities: Iterable[LinearConstraint],
        inequalities: Iterable[LinearConstraint],
        margin_index: int,
    ) -> HybridLinearResult:
        started = time.perf_counter()
        try:
            domains = tuple(str(value) for value in variable_domains)
            if not domains:
                raise ValueError("At least one LP variable is required")
            if not 0 <= margin_index < len(domains):
                raise ValueError("margin_index is out of range")
            if domains[margin_index] != "nonnegative":
                raise ValueError("The strict-margin variable must be non-negative")
            if any(value not in {"nonnegative", "free"} for value in domains):
                raise ValueError("Variable domains must be 'nonnegative' or 'free'")

            equality_tuple = tuple(equalities)
            inequality_tuple = tuple(inequalities)
            width = len(domains)
            if any(len(item.coefficients) != width for item in equality_tuple + inequality_tuple):
                raise ValueError("Linear constraint width mismatch")

            key = (
                domains,
                tuple(sorted(self._canonical_constraint(item) for item in equality_tuple)),
                tuple(sorted((item.coefficients, item.rhs) for item in inequality_tuple)),
                int(margin_index),
            )
            self.calls += 1
            cached = self._cache.get(key)
            if cached is not None:
                self.cache_hits += 1
                return cached

            floating = self._solve_float(
                domains,
                equality_tuple,
                inequality_tuple,
                margin_index,
            )
            if floating.feasible:
                result = floating
            else:
                result = self._solve_exact(
                    domains,
                    equality_tuple,
                    inequality_tuple,
                    margin_index,
                )
            if len(self._cache) >= self.cache_size:
                self._cache.clear()
            self._cache[key] = result
            return result
        finally:
            self.elapsed_seconds += time.perf_counter() - started

    def _solve_float(
        self,
        domains: Sequence[str],
        equalities: Sequence[LinearConstraint],
        inequalities: Sequence[LinearConstraint],
        margin_index: int,
    ) -> HybridLinearResult:
        started = time.perf_counter()
        try:
            width = len(domains)
            objective = np.zeros(width, dtype=float)
            objective[margin_index] = -1.0
            a_eq = np.asarray(
                [[float(value) for value in item.coefficients] for item in equalities],
                dtype=float,
            ) if equalities else None
            b_eq = np.asarray([float(item.rhs) for item in equalities], dtype=float) if equalities else None
            a_ub = np.asarray(
                [[float(value) for value in item.coefficients] for item in inequalities],
                dtype=float,
            ) if inequalities else None
            b_ub = np.asarray([float(item.rhs) for item in inequalities], dtype=float) if inequalities else None
            bounds = [
                (0.0, None) if domain == "nonnegative" else (None, None)
                for domain in domains
            ]
            solution = linprog(
                objective,
                A_ub=a_ub,
                b_ub=b_ub,
                A_eq=a_eq,
                b_eq=b_eq,
                bounds=bounds,
                method="highs",
            )
            if not solution.success or solution.x is None:
                return HybridLinearResult(False, None, f"float:{solution.status}", False)
            margin = float(solution.x[margin_index])
            if margin <= self.tolerance:
                return HybridLinearResult(False, Fraction(str(margin)), "float:zero_margin", False)
            return HybridLinearResult(True, Fraction(str(margin)), "float:feasible", False)
        finally:
            self.float_seconds += time.perf_counter() - started

    @staticmethod
    def _reduce_equalities(
        width: int,
        equalities: Sequence[LinearConstraint],
    ) -> tuple[
        bool,
        tuple[int, ...],
        tuple[Fraction, ...],
        tuple[tuple[Fraction, ...], ...],
    ]:
        """Eliminate exact equalities and parameterize the affine solution space.

        Returns ``(consistent, free_columns, constants, coefficients)`` with
        ``x_j = constants[j] + sum(coefficients[j][k] * y_k)``.  Arithmetic is
        entirely rational, so this is only a change of representation before
        the exact simplex, not a new pruning rule.
        """

        rows = [
            [*item.coefficients, item.rhs]
            for item in equalities
        ]
        pivot_columns: list[int] = []
        pivot_row = 0
        for column in range(width):
            selected = next(
                (index for index in range(pivot_row, len(rows)) if rows[index][column]),
                None,
            )
            if selected is None:
                continue
            rows[pivot_row], rows[selected] = rows[selected], rows[pivot_row]
            divisor = rows[pivot_row][column]
            rows[pivot_row] = [value / divisor for value in rows[pivot_row]]
            for row_index, row in enumerate(rows):
                if row_index == pivot_row:
                    continue
                factor = row[column]
                if factor:
                    rows[row_index] = [
                        value - factor * pivot_value
                        for value, pivot_value in zip(row, rows[pivot_row])
                    ]
            pivot_columns.append(column)
            pivot_row += 1
            if pivot_row == len(rows):
                break

        for row in rows[pivot_row:]:
            if not any(row[:width]) and row[width]:
                return False, (), (), ()

        pivot_set = set(pivot_columns)
        free_columns = tuple(
            column for column in range(width) if column not in pivot_set
        )
        free_index = {column: index for index, column in enumerate(free_columns)}
        constants = [Fraction(0) for _ in range(width)]
        coefficients = [
            [Fraction(0) for _ in free_columns]
            for _ in range(width)
        ]
        for column in free_columns:
            coefficients[column][free_index[column]] = Fraction(1)
        for row_index, column in enumerate(pivot_columns):
            row = rows[row_index]
            constants[column] = row[width]
            for free_column in free_columns:
                coefficients[column][free_index[free_column]] = -row[free_column]
        return (
            True,
            free_columns,
            tuple(constants),
            tuple(tuple(row) for row in coefficients),
        )

    @staticmethod
    def _substitute_reduced_constraint(
        constraint: LinearConstraint,
        constants: Sequence[Fraction],
        coefficients: Sequence[Sequence[Fraction]],
    ) -> tuple[tuple[Fraction, ...], Fraction]:
        reduced = [Fraction(0) for _ in range(len(coefficients[0]) if coefficients else 0)]
        constant = Fraction(0)
        for variable_index, value in enumerate(constraint.coefficients):
            if not value:
                continue
            constant += value * constants[variable_index]
            for free_index, coefficient in enumerate(coefficients[variable_index]):
                reduced[free_index] += value * coefficient
        return tuple(reduced), constraint.rhs - constant

    def _solve_exact(
        self,
        domains: Sequence[str],
        equalities: Sequence[LinearConstraint],
        inequalities: Sequence[LinearConstraint],
        margin_index: int,
    ) -> HybridLinearResult:
        started = time.perf_counter()
        self.exact_calls += 1
        try:
            width = len(domains)
            consistent, free_columns, constants, coefficients = self._reduce_equalities(
                width, equalities
            )
            if not consistent:
                return HybridLinearResult(
                    feasible=False,
                    margin=None,
                    status="exact:infeasible",
                    exact_certificate_used=True,
                )

            reduced_inequalities = [
                self._substitute_reduced_constraint(item, constants, coefficients)
                for item in inequalities
            ]
            # Preserve every original non-negativity domain after eliminating
            # pivot variables.  A variable x >= 0 is encoded as -x <= 0.
            for variable_index, domain in enumerate(domains):
                if domain != "nonnegative":
                    continue
                reduced_inequalities.append(
                    (
                        tuple(-value for value in coefficients[variable_index]),
                        constants[variable_index],
                    )
                )

            objective = tuple(coefficients[margin_index])
            objective_constant = constants[margin_index]
            if not free_columns:
                feasible_region = all(
                    not any(row) and Fraction(0) <= rhs
                    for row, rhs in reduced_inequalities
                )
                status = "optimal" if feasible_region else "infeasible"
                optimum = objective_constant if feasible_region else None
            else:
                solution = maximize_free_variables(reduced_inequalities, objective)
                status = solution.status
                optimum = (
                    None
                    if solution.optimum is None
                    else objective_constant + solution.optimum
                )

            feasible = status == "optimal" and optimum is not None and optimum > 0
            return HybridLinearResult(
                feasible=feasible,
                margin=optimum,
                status=f"exact:{status}",
                exact_certificate_used=True,
            )
        finally:
            self.exact_seconds += time.perf_counter() - started

