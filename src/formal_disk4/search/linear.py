from __future__ import annotations

"""Small persistent affine theory. Only exact contradictions remove branches."""

from collections import OrderedDict
from dataclasses import dataclass
from fractions import Fraction
from time import perf_counter

from formal_disk4.constraints.hybrid_linear import HybridMarginOracle, LinearConstraint


@dataclass(frozen=True)
class Form:
    coefficients: tuple[int | Fraction, ...]
    constant: int | Fraction = 0

    @classmethod
    def scalar(cls, width: int, value: int | Fraction) -> Form:
        return cls((0,) * width, value)

    @classmethod
    def variable(cls, width: int, index: int) -> Form:
        return cls(tuple(int(i == index) for i in range(width)))

    def __add__(self, other: Form) -> Form:
        if len(self.coefficients) != len(other.coefficients):
            raise ValueError("Affine expression width mismatch")
        return Form(tuple(a + b for a, b in zip(self.coefficients, other.coefficients)),
                    self.constant + other.constant)

    def __neg__(self) -> Form:
        return Form(tuple(-a for a in self.coefficients), -self.constant)

    def __sub__(self, other: Form) -> Form:
        return self + -other


@dataclass(frozen=True)
class LinearState:
    equalities: tuple[Form, ...] = ()  # form == 0
    strict: tuple[Form, ...] = ()      # form > 0
    nonstrict: tuple[Form, ...] = ()   # form >= 0

    def equal(self, form: Form) -> LinearState:
        return LinearState(self.equalities + (form,), self.strict, self.nonstrict)

    def positive(self, form: Form) -> LinearState:
        return LinearState(self.equalities, self.strict + (form,), self.nonstrict)

    def nonnegative(self, form: Form) -> LinearState:
        return LinearState(self.equalities, self.strict, self.nonstrict + (form,))


class LinearTheory:
    """Strict affine feasibility using one shared margin, with bounded memory.

    A positive floating witness retains a branch. Any negative result must be
    verified by rational simplex. The margin has an upper bound, so the exact
    problem cannot be unbounded; an unknown status is retained, never rejected.
    """

    def __init__(self, width: int, cache_size: int = 2048) -> None:
        self.width = width
        self.oracle = HybridMarginOracle(cache_size=cache_size)
        self.cache_size = cache_size
        self._cache: OrderedDict[LinearState, bool] = OrderedDict()
        self.calls = self.rejections = self.cache_hits = self.unknown = 0
        self.elapsed_seconds = 0.0

    def check(self, state: LinearState) -> bool:
        started = perf_counter()
        self.calls += 1
        try:
            if state in self._cache:
                self.cache_hits += 1
                self._cache.move_to_end(state)
                return self._cache[state]
            for forms, relation in ((state.equalities, 0), (state.strict, 1),
                                    (state.nonstrict, 2)):
                for form in forms:
                    if len(form.coefficients) != self.width:
                        raise ValueError("Affine constraint width mismatch")
                    if not any(form.coefficients) and (
                        (relation == 0 and form.constant != 0)
                        or (relation == 1 and form.constant <= 0)
                        or (relation == 2 and form.constant < 0)
                    ):
                        return self._remember(state, False)
            equalities = tuple(LinearConstraint.build((*f.coefficients, 0), -f.constant)
                               for f in state.equalities if any(f.coefficients))
            inequalities = [LinearConstraint.build((*(-v for v in f.coefficients), 1),
                                                   f.constant) for f in state.strict]
            inequalities.extend(LinearConstraint.build((*(-v for v in f.coefficients), 0),
                                                       f.constant) for f in state.nonstrict)
            inequalities.append(LinearConstraint.build((0,) * self.width + (1,), 1))
            result = self.oracle.analyze(
                variable_domains=("free",) * self.width + ("nonnegative",),
                equalities=equalities, inequalities=inequalities, margin_index=self.width,
            )
            rejected = (not result.feasible and result.exact_certificate_used
                        and result.status in {"exact:infeasible", "exact:optimal"})
            if not result.feasible and not rejected:
                self.unknown += 1
            return self._remember(state, not rejected)
        finally:
            self.elapsed_seconds += perf_counter() - started

    def _remember(self, state: LinearState, feasible: bool) -> bool:
        if not feasible:
            self.rejections += 1
        self._cache[state] = feasible
        if len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)
        return feasible
