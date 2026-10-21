from dataclasses import replace

import pytest

from formal_disk4.words.completed_cache import CompletedWordCache
from formal_disk4.words.exact_partial import ExactPartialWordSolver, SolverLimits
from formal_disk4.words.families import ExactFormalFamily, atom


FAMILY = ExactFormalFamily(1, 'finite', (('X', atom('a')),), (), (), 1)


class Solver:
    def __init__(self, status='exact_supported', **flags):
        self.last_summary = ExactPartialWordSolver((), ()).last_summary
        self.final = replace(self.last_summary, status=status, visited_states=12,
                             graph_edges=15, exact_unsat=status == 'exact_unsat', **flags)
        self.calls = 0

    def solve(self, *args, **kwargs):
        self.calls += 1
        if self.final.status != 'exact_unsat':
            yield FAMILY
        self.last_summary = self.final


def run(cache, key, solver, stop=lambda: False):
    return cache.iterate(key, solver, SolverLimits(), stop_predicate=stop,
                         family_predicate=lambda _: True)


def test_reuses_only_algebraic_results_and_does_not_recount_graph_work():
    cache = CompletedWordCache()
    first, second = Solver(), Solver()
    assert list(run(cache, 'same-equations-and-policy', first)) == [FAMILY]
    assert list(run(cache, 'same-equations-and-policy', second)) == [FAMILY]
    assert first.calls == 1 and second.calls == 0
    assert second.last_summary.status == 'exact_supported'
    assert second.last_summary.visited_states == second.last_summary.graph_edges == 0


@pytest.mark.parametrize('status,flags', [
    ('interrupted_external_stop', {'external_stop_reached': True}),
    ('unresolved_family_limit', {'family_limit_reached': True}),
    ('exact_unsupported_family_language', {'unsupported_complex_components': 1}),
    ('exact_supported', {'terminal_contour_pruned': 1}),
])
def test_incomplete_or_unsupported_result_never_freezes_future_search(status, flags):
    cache = CompletedWordCache()
    list(run(cache, 'key', Solver(status, **flags)))
    second = Solver()
    list(run(cache, 'key', second))
    assert second.calls == 1


def test_consumer_break_is_not_cached_and_replay_break_is_not_exhaustion():
    cache = CompletedWordCache()
    iterator = run(cache, 'key', Solver())
    next(iterator)
    iterator.close()
    assert not cache.entries
    list(run(cache, 'key', Solver()))
    solver = Solver()
    replay = run(cache, 'key', solver)
    next(replay)
    replay.close()
    assert solver.last_summary.external_stop_reached
    assert solver.last_summary.status == 'interrupted_external_stop'
    assert not solver.last_summary.exact_unsat


def test_empty_exact_unsat_reuse_and_key_isolation():
    cache = CompletedWordCache()
    list(run(cache, ('equations', 'limits', 'policy1'), Solver('exact_unsat')))
    second = Solver()
    assert list(run(cache, ('equations', 'limits', 'policy1'), second)) == []
    assert second.calls == 0 and second.last_summary.exact_unsat
    third = Solver()
    list(run(cache, ('equations', 'limits', 'policy2'), third))
    assert third.calls == 1


def test_cache_is_bounded_and_large_result_is_not_retained():
    cache = CompletedWordCache(max_entries=1)
    list(run(cache, 'a', Solver()))
    list(run(cache, 'b', Solver()))
    assert tuple(cache.entries) == ('b',)
    cache = CompletedWordCache(max_weight=1)
    list(run(cache, 'large', Solver()))
    assert not cache.entries and cache.weight == 0


def test_real_word_solver_language_is_replayed_identically():
    from formal_disk4.words.algebra import Equation, Literal
    equations = (Equation((Literal('X'),), (Literal('Y'),)),)
    limits = SolverLimits(max_families=None)
    cache = CompletedWordCache()
    first = ExactPartialWordSolver(equations, ('X', 'Y'))
    key = (equations, limits)
    expected = list(cache.iterate(key, first, limits, stop_predicate=lambda: False,
                                 family_predicate=lambda _: True))
    assert expected and first.last_summary.status == 'exact_supported'
    second = ExactPartialWordSolver(equations, ('X', 'Y'))
    second.solve = lambda *a, **k: (_ for _ in ()).throw(AssertionError('Should reuse completed language'))
    actual = list(cache.iterate(key, second, limits, stop_predicate=lambda: False,
                               family_predicate=lambda _: True))
    assert actual == expected
