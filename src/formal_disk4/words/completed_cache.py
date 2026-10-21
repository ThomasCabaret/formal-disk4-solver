"""Small run-local cache of fully resolved word languages.

Keys include the compiled problem, solver limits and family acceptance policy,
but not metric sectors: those are applied separately during decoration. Partial
iteration, resource limits and unsupported languages are deliberately not cached.
No solver object, residual graph, profile or disk checkpoint is retained.
"""
from collections import OrderedDict
from dataclasses import replace

from .families import ConcatExpr, PowerExpr


class CompletedWordCache:
    def __init__(self, *, max_entries=32, max_weight=50_000, event_sink=None):
        self.entries = OrderedDict()
        self.weight = 0
        self.max_entries, self.max_weight = max_entries, max_weight
        self.event = event_sink or (lambda name, amount=1: None)

    def iterate(self, key, solver, limits, *, stop_predicate, family_predicate):
        cached = self.entries.get(key)
        if cached is not None:
            self.entries.move_to_end(key)
            families, summary, _weight = cached
            self.event('word_cache_hits')
            # Preserve the verdict, but do not count old graph construction as
            # work done again. A caller breaking iteration must not get a false
            # completed status for this invocation.
            completed = False
            try:
                for family in families:
                    if stop_predicate():
                        return
                    yield family
                if stop_predicate():
                    return
                completed = True
            finally:
                solver.last_summary = replace(summary, visited_states=0, graph_edges=0,
                    external_stop_reached=not completed,
                    exact_unsat=summary.exact_unsat if completed else False,
                    status=summary.status if completed else 'interrupted_external_stop')
            return

        self.event('word_cache_misses')
        families, weight = [], 1
        for family in solver.solve(limits, stop_predicate=stop_predicate,
                                   family_predicate=family_predicate):
            if families is not None:
                weight += (1 + sum(len(item) for item in family.trace)
                           + sum(len(item) for item in family.validation_assignments))
                pending = [expr for _, expr in family.environment]
                while pending and weight <= self.max_weight:
                    expression = pending.pop()
                    weight += 1
                    if isinstance(expression, ConcatExpr):
                        pending.extend(expression.parts)
                    elif isinstance(expression, PowerExpr):
                        pending.append(expression.base)
                if weight <= self.max_weight:
                    families.append(family)
                else:
                    families = None
            yield family
        summary = solver.last_summary
        if (families is None or weight > self.max_weight or self.max_entries < 1 or stop_predicate()
                or summary.status not in {'exact_supported', 'exact_unsat'}
                or summary.external_stop_reached or summary.graph_limit_reached
                or summary.expression_limit_reached or summary.family_limit_reached
                or summary.residual_literal_limit_reached or summary.terminal_contour_pruned
                or summary.unsupported_complex_components):
            self.event('word_cache_not_stored')
            return
        while self.entries and (len(self.entries) >= self.max_entries
                                or self.weight + weight > self.max_weight):
            _key, (_families, _summary, old_weight) = self.entries.popitem(last=False)
            self.weight -= old_weight
        self.entries[key] = tuple(families), summary, weight
        self.weight += weight
        self.event('word_cache_stored')
