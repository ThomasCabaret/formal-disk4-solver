from __future__ import annotations

from dataclasses import dataclass
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
        self._cache: dict[
            Tuple[int, Tuple[Tuple[Tuple[int, ...], float], ...]], AngleFeasibilityResult
        ] = {}

    def analyze(
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

        solution = linprog(
            objective,
            A_ub=np.asarray(a_ub, dtype=float),
            b_ub=np.asarray(b_ub, dtype=float),
            A_eq=np.asarray(a_eq, dtype=float) if a_eq else None,
            b_eq=np.asarray(b_eq, dtype=float) if b_eq else None,
            bounds=[(None, None)] * point_count + [(0.0, None)],
            method="highs",
        )

        if not solution.success or solution.x is None:
            result = AngleFeasibilityResult(False, 0.0, (), f"linprog:{solution.status}")
            self._cache[key] = result
            return result

        margin = float(solution.x[epsilon_index])
        turns = tuple(float(value) for value in solution.x[:point_count])
        feasible = margin > self.tolerance and self._verify(turns, normalized, margin)
        result = AngleFeasibilityResult(
            feasible,
            margin,
            turns if need_witness or feasible else (),
            "feasible" if feasible else "zero strict margin",
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
