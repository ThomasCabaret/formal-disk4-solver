"""Incremental interface-word consequences for a partial contact state.

Only interfaces with placed endpoints are compiled. Every remaining prototype
gap is an arbitrary nonempty factor, NOT a smooth curve. Thus future corners
can be absorbed or introduced by exact Levi refinement without closing sectors.
The leaf kernel receives the original system and retains responsibility for
unresolved comparisons, periodicity and atomic self-involutions.
Reference: docs/contact_type_enumerator_design.tex, sec:word (deterministic
rules and forced Levi cases). Undecided comparisons are exposed to DFS, or to
optional existential lookahead; this module never silently selects a sector.
"""
from collections import OrderedDict
from time import perf_counter

from formal_disk4.constraints.hybrid_linear import HybridMarginOracle, LinearConstraint
from .angles import ContactAngleTheory
from .linear import Form
from .word_propagation import Corner, Factor, MIRROR, REVERSE, propagate, transform_word
from .word_refinement import WordRefinement


class ForcedLengthComparison:
    def __init__(self, state, theory, max_queries=8):
        self.state, self.theory = state, theory
        self.max_queries, self.queries = max_queries, 0
        self.exhausted = False
        rows = tuple(LinearConstraint.build(f.coefficients, -f.constant) for f in state.equalities)
        self.consistent, _, self.constants, self.coefficients = HybridMarginOracle._reduce_equalities(
            theory.width, rows)
        self.cache = {}
        self.strict_keys = {self.reduced(f) for f in state.strict}

    def reduced(self, form):
        coefficients, rhs = HybridMarginOracle._substitute_reduced_constraint(
            LinearConstraint.build(form.coefficients, -form.constant), self.constants, self.coefficients)
        return coefficients, -rhs

    def __call__(self, left, right):
        diff = left - right
        if not self.consistent:
            return None  # Main feasibility oracle owns rejection.
        key = self.reduced(diff)
        if not any(key[0]):
            return (key[1] > 0) - (key[1] < 0)
        if key in self.strict_keys:
            return 1
        if self.reduced(-diff) in self.strict_keys:
            return -1
        if key in self.cache:
            return self.cache[key]
        # Negations are checked exactly by LinearTheory. Numerical uncertainty
        # retains all alternatives; exhausted query allowance also means unknown.
        answer = None
        if self.queries + 2 <= self.max_queries:
            self.queries += 2
            if not self.theory.check(self.state.nonnegative(-diff)):
                answer = 1
            elif not self.theory.check(self.state.nonnegative(diff)):
                answer = -1
        else:
            self.exhausted = True
        self.cache[key] = answer
        return answer


class ContactWordTheory:
    def __init__(self, model, theory, *, max_steps=96, max_queries=8, refinement_depth=0):
        self.model, self.theory = model, theory
        self.max_steps, self.max_queries = max_steps, max_queries
        self.refinement_depth = refinement_depth
        self.refinement_decisions = self.refinement_cases = self.refinement_closed = 0
        self.refinement_deferred = self.refinement_length_rejections = 0
        self.angles = ContactAngleTheory(model.planar_map)
        self.calls = self.rejections = self.splits = self.unions = 0
        self.point_relations = self.residuals = self.limited = self.cache_hits = 0
        self.elapsed_seconds = 0.0
        self.cache = OrderedDict()
        self.last_reason = ""
        self.last_result = None

    def check(self, state):
        start = perf_counter()
        self.calls += 1
        parities = tuple(c.parity if c else 0 for c in state.charts)
        snapshot = getattr(state, "word_snapshot", None)
        key = (state.blocks, parities, state.linear, snapshot)
        try:
            if key in self.cache:
                self.cache_hits += 1
                feasible, self.last_reason, self.last_result = self.cache[key]
                return feasible
            m = self.model
            positions = {o: i for i, block in enumerate(state.blocks) for o in block}
            active = [e for e in m.planar_map.internal_interfaces() if all(
                m.occurrence_index[o] in positions for v in e.views
                for o in (v.start_occurrence, v.end_occurrence))]
            if not active:
                self.last_result = None
                return True
            coordinates = tuple(state.coordinates[b[0]] for b in state.blocks)
            lengths = tuple((coordinates[i+1] if i+1 < len(coordinates) else m.one)-q
                            for i, q in enumerate(coordinates))

            def word(view):
                a, b = (positions[m.occurrence_index[o]]
                        for o in (view.start_occurrence, view.end_occurrence))
                if parities[m.piece_names.index(view.piece)] < 0:
                    a, b = b, a
                tokens = []
                while a != b:
                    tokens.append(Factor(a))
                    a = (a+1) % len(state.blocks)
                    if a != b:
                        tokens.append(Corner(state.blocks[a][0]))
                return tuple(tokens)

            equations = []
            for edge in active:
                a, b = edge.views
                same = parities[m.piece_names.index(a.piece)] == parities[m.piece_names.index(b.piece)]
                equations.append((word(a), transform_word(word(b), REVERSE if same else MIRROR)))
            compare = ForcedLengthComparison(state.linear, self.theory, self.max_queries)
            result = propagate(tuple(equations), lengths, len(m.occurrences), compare,
                               max_steps=self.max_steps, resume=snapshot)
            self.last_result = result
            self.splits += result.splits
            self.unions += result.unions
            self.point_relations += len(result.relations)
            self.residuals += int(result.residual_equations > 0)
            self.limited += int(result.limited or compare.exhausted)
            def resume(snapshot, linear):
                comparison = ForcedLengthComparison(linear, self.theory, self.max_queries)
                continuation = propagate((), (), 0, comparison, max_steps=self.max_steps, resume=snapshot)
                self.splits += continuation.splits
                self.unions += continuation.unions
                self.limited += int(continuation.limited or comparison.exhausted)
                return continuation

            refinement = WordRefinement(self.theory, resume,
                lambda r: self.angles.check(state.blocks, relations=r.relations, point_count=r.point_count),
                max_depth=self.refinement_depth)
            feasible = refinement.check(result, state.linear)
            stats = refinement.statistics
            self.refinement_decisions += stats.decisions
            self.refinement_cases += stats.cases
            self.refinement_closed += stats.closed
            self.refinement_deferred += stats.deferred
            self.refinement_length_rejections += stats.length_rejections
            self.last_reason = ("" if feasible else result.reason or "propagated_corner_angles_inconsistent")
            if not feasible and stats.closed:
                self.last_reason = "all_levi_cases_inconsistent"
            self.rejections += int(not feasible)
            self.cache[key] = feasible, self.last_reason, result
            if len(self.cache) > 512:
                self.cache.popitem(last=False)
            return feasible
        finally:
            self.elapsed_seconds += perf_counter()-start
