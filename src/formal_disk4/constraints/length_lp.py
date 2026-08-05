from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import time
from typing import Iterable, Sequence, Tuple

import numpy as np
from scipy.optimize import linprog


@dataclass(frozen=True)
class LengthFeasibilityResult:
    feasible: bool
    margin: float
    lengths: Tuple[float, ...]
    status: str


def _normalize_row(row: Sequence[int]) -> Tuple[int, ...] | None:
    values = tuple(int(value) for value in row)
    if not any(values):
        return None
    first = next(value for value in values if value)
    if first < 0:
        values = tuple(-value for value in values)
    return values


class LengthFeasibilityOracle:
    """LP oracle for positive atomic contour lengths.

    It solves max epsilon under A x = 0, sum(x)=1 and x_i >= epsilon.
    FILTER JUSTIFICATION (local): interface length preservation gives the
    homogeneous equalities, and every non-erasing contour atom has positive
    length. Thus a certified absence of a positive null-vector is necessary.

    The combinatorial matrices are integral. SciPy/HiGHS is only a fast witness
    finder: failure, zero margin, or an unverified result is reported as unknown
    and accepted. The only direct rejection below is the exact same-sign-row
    contradiction.
    """

    def __init__(self, tolerance: float = 1e-9, cache_size: int = 200_000) -> None:
        self.tolerance = tolerance
        self.cache_size = cache_size
        self.calls = 0
        self.cache_hits = 0
        self.elapsed_seconds = 0.0
        self.lp_seconds = 0.0
        self._cache: dict[Tuple[int, Tuple[Tuple[int, ...], ...]], LengthFeasibilityResult] = {}

    def canonical_key(
        self, interval_count: int, rows: Iterable[Sequence[int]]
    ) -> Tuple[int, Tuple[Tuple[int, ...], ...]]:
        normalized = sorted(
            row
            for row in (_normalize_row(item) for item in rows)
            if row is not None
        )
        unique: list[Tuple[int, ...]] = []
        for row in normalized:
            if not unique or unique[-1] != row:
                unique.append(row)
        return interval_count, tuple(unique)

    def analyze(
        self,
        interval_count: int,
        rows: Iterable[Sequence[int]],
        need_witness: bool = False,
    ) -> LengthFeasibilityResult:
        started = time.perf_counter()
        try:
            return self._analyze(interval_count, rows, need_witness)
        finally:
            self.elapsed_seconds += time.perf_counter() - started

    def _analyze(
        self,
        interval_count: int,
        rows: Iterable[Sequence[int]],
        need_witness: bool = False,
    ) -> LengthFeasibilityResult:
        if interval_count <= 0:
            raise ValueError("interval_count must be positive")
        key = self.canonical_key(interval_count, rows)
        self.calls += 1
        cached = self._cache.get(key)
        if cached is not None:
            self.cache_hits += 1
            return cached

        _, matrix_rows = key
        for row in matrix_rows:
            nonzero = [value for value in row if value]
            # FILTER JUSTIFICATION (local): a nonzero homogeneous row with one
            # coefficient sign cannot vanish
            # when every atomic contour length is strictly positive.
            if nonzero and (all(value > 0 for value in nonzero) or all(value < 0 for value in nonzero)):
                result = LengthFeasibilityResult(False, 0.0, (), "same-sign contradiction")
                self._remember(key, result)
                return result

        variable_count = interval_count + 1
        epsilon_index = interval_count
        objective = np.zeros(variable_count, dtype=float)
        objective[epsilon_index] = -1.0

        equalities = []
        rhs = []
        for row in matrix_rows:
            equalities.append(list(row) + [0.0])
            rhs.append(0.0)
        equalities.append([1.0] * interval_count + [0.0])
        rhs.append(1.0)

        inequalities = []
        inequality_rhs = []
        for index in range(interval_count):
            row = [0.0] * variable_count
            row[index] = -1.0
            row[epsilon_index] = 1.0
            inequalities.append(row)
            inequality_rhs.append(0.0)

        lp_started = time.perf_counter()
        try:
            try:
                solution = linprog(
                    objective,
                    A_ub=np.asarray(inequalities, dtype=float),
                    b_ub=np.asarray(inequality_rhs, dtype=float),
                    A_eq=np.asarray(equalities, dtype=float),
                    b_eq=np.asarray(rhs, dtype=float),
                    bounds=[(0.0, None)] * variable_count,
                    method="highs",
                )
            except Exception as error:
                result = LengthFeasibilityResult(
                    True,
                    0.0,
                    (),
                    f"unknown:linprog_exception:{type(error).__name__}",
                )
                self._remember(key, result)
                return result
        finally:
            self.lp_seconds += time.perf_counter() - lp_started

        if not solution.success or solution.x is None:
            result = LengthFeasibilityResult(
                True, 0.0, (), f"unknown:linprog_status:{solution.status}"
            )
            self._remember(key, result)
            return result

        margin = float(solution.x[epsilon_index])
        lengths = tuple(float(value) for value in solution.x[:interval_count])
        verified = margin > self.tolerance and self._verify(
            lengths, matrix_rows, margin
        )
        result = LengthFeasibilityResult(
            feasible=True,
            margin=margin if verified else 0.0,
            lengths=lengths if verified else (),
            status="feasible" if verified else "unknown:zero_or_unverified_strict_margin",
        )
        self._remember(key, result)
        return result

    def _verify(
        self,
        lengths: Sequence[float],
        rows: Sequence[Sequence[int]],
        margin: float,
    ) -> bool:
        tolerance = max(self.tolerance * 100.0, 1e-8)
        if abs(sum(lengths) - 1.0) > tolerance:
            return False
        if not lengths or min(lengths) + tolerance < margin:
            return False
        for row in rows:
            residual = sum(coefficient * value for coefficient, value in zip(row, lengths))
            if abs(residual) > tolerance:
                return False
        return True

    def _remember(
        self,
        key: Tuple[int, Tuple[Tuple[int, ...], ...]],
        result: LengthFeasibilityResult,
    ) -> None:
        if len(self._cache) >= self.cache_size:
            self._cache.clear()
        self._cache[key] = result
