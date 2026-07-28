from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import time
from typing import Iterable, Sequence, Tuple

import numpy as np
from scipy.optimize import linprog

from formal_disk4.constraints.rational_lp import RationalSimplex


def _normalize_integer_row(row: Sequence[int]) -> Tuple[int, ...] | None:
    values = tuple(int(value) for value in row)
    if not any(values):
        return None
    first = next(value for value in values if value)
    if first < 0:
        values = tuple(-value for value in values)
    return values




def _canonical_key(
    interval_count: int,
    equality_rows: Iterable[Sequence[int]],
    inequality_rows: Iterable[Sequence[int]],
) -> Tuple[int, Tuple[Tuple[int, ...], ...], Tuple[Tuple[int, ...], ...]]:
    equalities = sorted(
        row
        for row in (_normalize_integer_row(item) for item in equality_rows)
        if row is not None
    )
    inequalities = sorted(
        tuple(int(value) for value in item)
        for item in inequality_rows
        if any(int(value) for value in item)
    )
    return interval_count, tuple(dict.fromkeys(equalities)), tuple(dict.fromkeys(inequalities))


@dataclass(frozen=True)
class StrictLengthFeasibilityResult:
    feasible: bool
    margin: float
    status: str


class StrictLengthFeasibilityOracle:
    """Feasibility of tiny homogeneous length systems with strict positivity.

    The oracle maximizes a common epsilon under

        A_eq x = 0,
        A_ub x <= 0,
        sum(x) = 1,
        x_i >= epsilon.

    A positive optimum is equivalent to existence of a strictly positive length
    vector satisfying the homogeneous equalities and inequalities.  It is used
    only as a conservative pre-word oracle; no numerical witness is exported as
    a mathematical conclusion.
    """

    def __init__(self, tolerance: float = 1e-9, cache_size: int = 200_000) -> None:
        self.tolerance = float(tolerance)
        self.cache_size = int(cache_size)
        self.calls = 0
        self.cache_hits = 0
        self.elapsed_seconds = 0.0
        self.lp_seconds = 0.0
        self._cache: dict[
            Tuple[int, Tuple[Tuple[int, ...], ...], Tuple[Tuple[int, ...], ...]],
            StrictLengthFeasibilityResult,
        ] = {}

    def analyze(
        self,
        interval_count: int,
        equality_rows: Iterable[Sequence[int]],
        inequality_rows: Iterable[Sequence[int]],
    ) -> StrictLengthFeasibilityResult:
        started = time.perf_counter()
        try:
            return self._analyze(interval_count, equality_rows, inequality_rows)
        finally:
            self.elapsed_seconds += time.perf_counter() - started

    def _analyze(
        self,
        interval_count: int,
        equality_rows: Iterable[Sequence[int]],
        inequality_rows: Iterable[Sequence[int]],
    ) -> StrictLengthFeasibilityResult:
        if interval_count <= 0:
            raise ValueError("interval_count must be positive")
        key = _canonical_key(interval_count, equality_rows, inequality_rows)
        self.calls += 1
        cached = self._cache.get(key)
        if cached is not None:
            self.cache_hits += 1
            return cached

        _, equalities, inequalities = key
        variable_count = interval_count + 1
        epsilon_index = interval_count
        objective = np.zeros(variable_count, dtype=float)
        objective[epsilon_index] = -1.0

        A_eq = [list(row) + [0.0] for row in equalities]
        b_eq = [0.0] * len(A_eq)
        A_eq.append([1.0] * interval_count + [0.0])
        b_eq.append(1.0)

        A_ub = [list(row) + [0.0] for row in inequalities]
        b_ub = [0.0] * len(A_ub)
        for index in range(interval_count):
            row = [0.0] * variable_count
            row[index] = -1.0
            row[epsilon_index] = 1.0
            A_ub.append(row)
            b_ub.append(0.0)

        lp_started = time.perf_counter()
        try:
            solution = linprog(
                objective,
                A_ub=np.asarray(A_ub, dtype=float),
                b_ub=np.asarray(b_ub, dtype=float),
                A_eq=np.asarray(A_eq, dtype=float),
                b_eq=np.asarray(b_eq, dtype=float),
                bounds=[(0.0, None)] * variable_count,
                method="highs",
            )
        finally:
            self.lp_seconds += time.perf_counter() - lp_started

        if not solution.success or solution.x is None:
            result = StrictLengthFeasibilityResult(False, 0.0, f"linprog:{solution.status}")
        else:
            margin = float(solution.x[epsilon_index])
            result = StrictLengthFeasibilityResult(
                margin > self.tolerance,
                margin,
                "feasible" if margin > self.tolerance else "zero strict margin",
            )
        if len(self._cache) >= self.cache_size:
            self._cache.clear()
        self._cache[key] = result
        return result


class ExactStrictLengthFeasibilityOracle:
    """Exact rational certificate for strict positive homogeneous feasibility.

    This slower oracle is used only to certify a rejection first suggested by
    the floating HiGHS oracle.  Hence numerical roundoff can at worst suppress a
    pruning opportunity; it cannot remove a valid formal case.
    """

    def __init__(self, cache_size: int = 50_000) -> None:
        self.cache_size = int(cache_size)
        self.calls = 0
        self.cache_hits = 0
        self.elapsed_seconds = 0.0
        self._cache: dict[
            Tuple[int, Tuple[Tuple[int, ...], ...], Tuple[Tuple[int, ...], ...]],
            StrictLengthFeasibilityResult,
        ] = {}

    def analyze(
        self,
        interval_count: int,
        equality_rows: Iterable[Sequence[int]],
        inequality_rows: Iterable[Sequence[int]],
    ) -> StrictLengthFeasibilityResult:
        started = time.perf_counter()
        try:
            key = _canonical_key(interval_count, equality_rows, inequality_rows)
            self.calls += 1
            cached = self._cache.get(key)
            if cached is not None:
                self.cache_hits += 1
                return cached
            _, equalities, inequalities = key
            width = interval_count + 1
            epsilon_index = interval_count
            A: list[list[Fraction]] = []
            b: list[Fraction] = []

            def append_inequality(coefficients: Sequence[int | Fraction], rhs: int | Fraction) -> None:
                A.append([Fraction(value) for value in coefficients])
                b.append(Fraction(rhs))

            for row in equalities:
                expanded = list(row) + [0]
                append_inequality(expanded, 0)
                append_inequality([-value for value in expanded], 0)
            for row in inequalities:
                append_inequality(list(row) + [0], 0)

            total = [1] * interval_count + [0]
            append_inequality(total, 1)
            append_inequality([-value for value in total], -1)
            for index in range(interval_count):
                row = [0] * width
                row[index] = -1
                row[epsilon_index] = 1
                append_inequality(row, 0)

            objective = [0] * width
            objective[epsilon_index] = 1
            solution = RationalSimplex(A, b, objective).solve()
            feasible = (
                solution.status == "optimal"
                and solution.optimum is not None
                and solution.optimum > 0
            )
            result = StrictLengthFeasibilityResult(
                feasible,
                float(solution.optimum) if solution.optimum is not None else 0.0,
                f"exact:{solution.status}",
            )
            if len(self._cache) >= self.cache_size:
                self._cache.clear()
            self._cache[key] = result
            return result
        finally:
            self.elapsed_seconds += time.perf_counter() - started
