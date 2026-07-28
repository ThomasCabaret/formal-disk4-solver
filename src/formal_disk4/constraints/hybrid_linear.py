from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import time
from typing import Iterable, Sequence, Tuple

import numpy as np
from scipy.optimize import linprog

from formal_disk4.constraints.rational_lp import RationalSimplex


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
            columns: list[tuple[int, int | None]] = []
            expanded_width = 0
            for domain in domains:
                if domain == "nonnegative":
                    columns.append((expanded_width, None))
                    expanded_width += 1
                else:
                    columns.append((expanded_width, expanded_width + 1))
                    expanded_width += 2

            def expand(coefficients: Sequence[Fraction]) -> list[Fraction]:
                row = [Fraction(0) for _ in range(expanded_width)]
                for coefficient, (positive, negative) in zip(coefficients, columns):
                    row[positive] += coefficient
                    if negative is not None:
                        row[negative] -= coefficient
                return row

            matrix: list[list[Fraction]] = []
            rhs: list[Fraction] = []
            for item in equalities:
                row = expand(item.coefficients)
                matrix.append(row)
                rhs.append(item.rhs)
                matrix.append([-value for value in row])
                rhs.append(-item.rhs)
            for item in inequalities:
                matrix.append(expand(item.coefficients))
                rhs.append(item.rhs)

            objective = [Fraction(0) for _ in range(expanded_width)]
            margin_positive, margin_negative = columns[margin_index]
            objective[margin_positive] = Fraction(1)
            if margin_negative is not None:
                objective[margin_negative] = Fraction(-1)

            solution = RationalSimplex(matrix, rhs, objective).solve()
            feasible = (
                solution.status == "optimal"
                and solution.optimum is not None
                and solution.optimum > 0
            )
            return HybridLinearResult(
                feasible=feasible,
                margin=solution.optimum,
                status=f"exact:{solution.status}",
                exact_certificate_used=True,
            )
        finally:
            self.exact_seconds += time.perf_counter() - started
