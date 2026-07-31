from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import time
from typing import Iterable, Sequence, Tuple

import numpy as np
from scipy.optimize import linprog


@dataclass(frozen=True)
class AngleEquation:
    """Linear equation in signed contour turns, measured in units of pi."""

    coefficients: Tuple[int, ...]
    rhs: float


@dataclass(frozen=True)
class AngleFeasibilityResult:
    feasible: bool
    margin: float
    turns_pi: Tuple[float, ...]
    status: str

    @property
    def angles_pi(self) -> Tuple[float, ...]:
        """Backward-compatible prototype angles for the positive contour orientation."""
        return tuple(1.0 - value for value in self.turns_pi)


def _exactly_consistent(
    point_count: int,
    equations: Sequence[Tuple[Tuple[int, ...], float]],
) -> bool:
    """Check equality consistency over rationals before using the float LP."""
    matrix = []
    for coefficients, rhs in equations:
        if len(coefficients) != point_count:
            raise ValueError("Angle equation coefficient count does not match point_count")
        matrix.append(
            [Fraction(value) for value in coefficients] + [Fraction(str(rhs))]
        )
    row = 0
    for column in range(point_count):
        pivot = next(
            (index for index in range(row, len(matrix)) if matrix[index][column]),
            None,
        )
        if pivot is None:
            continue
        matrix[row], matrix[pivot] = matrix[pivot], matrix[row]
        pivot_value = matrix[row][column]
        matrix[row] = [value / pivot_value for value in matrix[row]]
        for index in range(len(matrix)):
            if index == row or not matrix[index][column]:
                continue
            factor = matrix[index][column]
            matrix[index] = [
                value - factor * pivot_entry
                for value, pivot_entry in zip(matrix[index], matrix[row])
            ]
        row += 1
        if row == len(matrix):
            break
    return not any(
        all(value == 0 for value in equation[:-1]) and equation[-1] != 0
        for equation in matrix
    )


class AngleFeasibilityOracle:
    """Feasibility oracle for signed point-angle classes.

    A prototype point carries a signed turn t in (-1, 1), in units of pi,
    with polygonal interior angle alpha = 1 - t.  Direct and reflected
    congruent copies have the same solid interior angle.  Copy parity is used
    only when transporting signed turns at points strictly inside a mapped
    interface.  At a geometric map vertex the enumerator simply sums all
    incident solid angles: 2*pi for an interior vertex and pi for an outer
    vertex.  This oracle maximizes a common strict margin.
    """

    def __init__(self, tolerance: float = 1e-9) -> None:
        self.tolerance = tolerance
        self.calls = 0
        self.cache_hits = 0
        self.elapsed_seconds = 0.0
        self.lp_seconds = 0.0
        self._cache: dict[
            Tuple[int, Tuple[Tuple[Tuple[int, ...], float], ...]], AngleFeasibilityResult
        ] = {}

    def analyze(
        self,
        point_count: int,
        equations: Iterable[AngleEquation],
        need_witness: bool = False,
    ) -> AngleFeasibilityResult:
        started = time.perf_counter()
        try:
            return self._analyze(point_count, equations, need_witness)
        finally:
            self.elapsed_seconds += time.perf_counter() - started

    def _analyze(
        self,
        point_count: int,
        equations: Iterable[AngleEquation],
        need_witness: bool = False,
    ) -> AngleFeasibilityResult:
        if point_count <= 0:
            raise ValueError("point_count must be positive")
        normalized = tuple(
            sorted(
                ((tuple(equation.coefficients), float(equation.rhs)) for equation in equations),
                key=lambda item: (item[0], item[1]),
            )
        )
        key = (point_count, normalized)
        self.calls += 1
        cached = self._cache.get(key)
        if cached is not None:
            self.cache_hits += 1
            return cached

        if not _exactly_consistent(point_count, normalized):
            result = AngleFeasibilityResult(
                False, 0.0, (), "infeasible_certified:inconsistent_equalities"
            )
            self._cache[key] = result
            return result

        variable_count = point_count + 1
        epsilon_index = point_count
        objective = np.zeros(variable_count, dtype=float)
        objective[epsilon_index] = -1.0

        a_eq = []
        b_eq = []
        for coefficients, rhs in normalized:
            a_eq.append(list(coefficients) + [0.0])
            b_eq.append(rhs)

        a_ub = []
        b_ub = []
        for index in range(point_count):
            upper = [0.0] * variable_count
            upper[index] = 1.0
            upper[epsilon_index] = 1.0
            a_ub.append(upper)
            b_ub.append(1.0)

            lower = [0.0] * variable_count
            lower[index] = -1.0
            lower[epsilon_index] = 1.0
            a_ub.append(lower)
            b_ub.append(1.0)

        lp_started = time.perf_counter()
        try:
            try:
                solution = linprog(
                    objective,
                    A_ub=np.asarray(a_ub, dtype=float),
                    b_ub=np.asarray(b_ub, dtype=float),
                    A_eq=np.asarray(a_eq, dtype=float) if a_eq else None,
                    b_eq=np.asarray(b_eq, dtype=float) if b_eq else None,
                    bounds=[(None, None)] * point_count + [(0.0, None)],
                    method="highs",
                )
            except Exception as error:
                result = AngleFeasibilityResult(
                    True,
                    0.0,
                    (),
                    f"unknown:linprog_exception:{type(error).__name__}",
                )
                self._cache[key] = result
                return result
        finally:
            self.lp_seconds += time.perf_counter() - lp_started

        if not solution.success or solution.x is None:
            result = AngleFeasibilityResult(
                True, 0.0, (), f"unknown:linprog_status:{solution.status}"
            )
            self._cache[key] = result
            return result

        margin = float(solution.x[epsilon_index])
        turns = tuple(float(value) for value in solution.x[:point_count])
        verified = margin > self.tolerance and self._verify(
            turns, normalized, margin
        )
        result = AngleFeasibilityResult(
            True,
            margin if verified else 0.0,
            turns if verified else (),
            "feasible" if verified else "unknown:zero_or_unverified_strict_margin",
        )
        if len(self._cache) > 200_000:
            self._cache.clear()
        self._cache[key] = result
        return result

    def _verify(
        self,
        turns: Sequence[float],
        equations: Sequence[Tuple[Tuple[int, ...], float]],
        margin: float,
    ) -> bool:
        tolerance = max(self.tolerance * 100.0, 1e-8)
        if not turns:
            return False
        if max(abs(value) for value in turns) > 1.0 - margin + tolerance:
            return False
        for coefficients, rhs in equations:
            residual = sum(coefficient * value for coefficient, value in zip(coefficients, turns))
            if abs(residual - rhs) > tolerance:
                return False
        return True
