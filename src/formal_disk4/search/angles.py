from __future__ import annotations

from collections import OrderedDict

from formal_disk4.maps.base import PlanarMap
from .linear import Form, LinearState, LinearTheory


class ContactAngleTheory:
    """Necessary junction equations, with coincident prototype corners merged.

    Reflection leaves the physical solid angle unchanged. Free boundaries use
    their own strict upper bound from VertexSpec; no disk winding invariant is
    inferred. Unknown derived corners are not constrained by this relaxation.
    """

    def __init__(self, planar_map: PlanarMap) -> None:
        self.occurrences = planar_map.occurrences()
        self.vertices = tuple((v.solid_angle_relation, v.solid_angle_limit_pi,
                               tuple(i for i, o in enumerate(self.occurrences)
                                     if o.vertex == v.name)) for v in planar_map.vertices)
        self._cache: OrderedDict[tuple, bool] = OrderedDict()
        self.calls = self.rejections = 0
        self.elapsed_seconds = 0.0

    def check(self, groups: tuple[tuple[int, ...], ...], *,
              relations: tuple[tuple[int, int, int], ...] = (),
              point_count: int | None = None) -> bool:
        from time import perf_counter
        start = perf_counter()
        self.calls += 1
        try:
            merged = tuple(sorted(tuple(sorted(g)) for g in groups if len(g) > 1))
            count = max(len(self.occurrences), point_count or 0)
            key = (merged, relations, count)
            if key in self._cache:
                return self._cache[key]
            parents = list(range(count))

            def find(i):
                while parents[i] != i:
                    i = parents[i]
                return i

            for group in merged:
                for i in group[1:]:
                    parents[find(i)] = find(group[0])
            roots = sorted({find(i) for i in range(len(parents))})
            index = {r: i for i, r in enumerate(roots)}
            width = len(roots)
            variables = tuple(Form.variable(width, i) for i in range(width))
            one, zero = Form.scalar(width, 1), Form.scalar(width, 0)
            state = LinearState(strict=tuple(f for v in variables for f in (one - v, one + v)))
            for a, b, sign in relations:
                if sign not in (-1, 1):
                    raise ValueError("Corner relation sign must be +1 or -1")
                left, right = variables[index[find(a)]], variables[index[find(b)]]
                state = state.equal(left - right if sign == 1 else left + right)
            for relation, limit, incidences in self.vertices:
                total = zero
                for i in incidences:
                    total = total + variables[index[find(i)]]
                # sum(alpha)<limit*pi iff sum(turn)>degree-limit.
                expression = total - Form.scalar(width, len(incidences) - limit)
                state = state.equal(expression) if relation == "equal" else state.positive(expression)
            result = LinearTheory(width, cache_size=1).check(state)
            self._cache[key] = result
            if len(self._cache) > 2048:
                self._cache.popitem(last=False)
            if not result:
                self.rejections += 1
            return result
        finally:
            self.elapsed_seconds += perf_counter() - start
