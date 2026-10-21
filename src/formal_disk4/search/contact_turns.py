"""Necessary turning equations on partial contacts, without word refinement.

An open prototype interval carries an unrestricted signed turn: it includes
curvature AND any corners not inserted yet. A marked corner has turn 1-alpha/pi.
The whole simple positive contour turns by 2*pi. Two CCW tile boundaries traverse
a common interface oppositely, so their interior turns sum to zero. Reflection
does not change this equation: reversing traversal and mirroring cancel signs.
No disk radius, convexity or bound on interval turning is assumed here.
"""
from collections import OrderedDict
from time import perf_counter

from .linear import Form, LinearState, LinearTheory


class ContactTurnTheory:
    def __init__(self, model):
        self.model = model
        self.calls = self.rejections = self.cache_hits = 0
        self.elapsed_seconds = 0.0
        self.cache = OrderedDict()

    def check(self, blocks, parities):
        start = perf_counter()
        self.calls += 1
        key = (blocks, parities)
        try:
            if key in self.cache:
                self.cache_hits += 1
                return self.cache[key]
            m = self.model
            positions = {o: i for i, block in enumerate(blocks) for o in block}
            representatives = {o: min(block) for block in blocks for o in block}
            roots = sorted({representatives.get(o, o) for o in range(len(m.occurrences))})
            indices = {r: i for i, r in enumerate(roots)}
            width = len(roots) + len(blocks)
            zero, one = Form.scalar(width, 0), Form.scalar(width, 1)
            turns = {o: Form.variable(width, indices[representatives.get(o, o)])
                     for o in range(len(m.occurrences))}
            gaps = tuple(Form.variable(width, len(roots)+i) for i in range(len(blocks)))
            state = LinearState(strict=tuple(f for r in roots for f in
                                           (one-turns[r], one+turns[r])))
            for vertex in m.planar_map.vertices:
                ids = [i for i, o in enumerate(m.occurrences) if o.vertex == vertex.name]
                expression = sum((turns[i] for i in ids), zero) - Form.scalar(
                    width, len(ids)-vertex.solid_angle_limit_pi)
                state = (state.equal(expression) if vertex.solid_angle_relation == 'equal'
                         else state.positive(expression))
            total = sum(gaps, zero) + sum((turns[b[0]] for b in blocks), zero)
            state = state.equal(total-Form.scalar(width, 2))
            for interface in m.planar_map.internal_interfaces():
                endpoints = [(m.occurrence_index[v.start_occurrence],
                              m.occurrence_index[v.end_occurrence]) for v in interface.views]
                if not all(o in positions for pair in endpoints for o in pair):
                    continue
                row = zero
                for view, (a, b) in zip(interface.views, endpoints):
                    a, b = positions[a], positions[b]
                    if parities[m.piece_names.index(view.piece)] < 0:
                        a, b = b, a
                    if a == b:
                        raise ValueError('Collapsed physical contact')
                    while a != b:
                        row = row + gaps[a]
                        a = (a+1) % len(blocks)
                        if a != b:
                            row = row + turns[blocks[a][0]]
                state = state.equal(row)
            result = LinearTheory(width, cache_size=1).check(state)
            self.cache[key] = result
            if len(self.cache) > 1024:
                self.cache.popitem(last=False)
            self.rejections += int(not result)
            return result
        finally:
            self.elapsed_seconds += perf_counter()-start
