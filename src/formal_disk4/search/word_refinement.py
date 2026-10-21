"""Bounded existential Levi lookahead, not a replacement for the leaf solver.

Sibling branches resume immutable word snapshots. A node is rejected only when
ALL three exhaustive length cases have exact contradictions. An open case,
including work-budget exhaustion, keeps the parent without committing to that
case: the leaf kernel still receives the unrestricted original equations.
"""
from dataclasses import dataclass

from .word_propagation import Propagation


@dataclass
class RefinementStatistics:
    decisions: int = 0
    cases: int = 0
    length_rejections: int = 0
    word_rejections: int = 0
    closed: int = 0
    deferred: int = 0


class WordRefinement:
    def __init__(self, theory, propagate_state, angle_check, *, max_depth=2):
        self.theory = theory
        self.propagate_state = propagate_state
        self.angle_check = angle_check
        self.max_depth = max_depth
        self.statistics = RefinementStatistics()

    def check(self, result: Propagation, linear, depth=0):
        if not result.feasible or not self.angle_check(result):
            self.statistics.word_rejections += 1
            return False
        if result.limited or result.ambiguous is None:
            self.statistics.deferred += int(result.limited)
            return True
        if depth >= self.max_depth:
            self.statistics.deferred += 1
            return True
        diff = result.ambiguous
        self.statistics.decisions += 1
        # Disjoint and exhaustive over real arclengths. Try coincidence first;
        # successful lookahead does NOT select it for the main traversal.
        for child in (linear.equal(diff), linear.positive(-diff), linear.positive(diff)):
            self.statistics.cases += 1
            if not self.theory.check(child):
                self.statistics.length_rejections += 1
                continue
            propagated = self.propagate_state(result.state, child)
            if self.check(propagated, child, depth+1):
                return True
        self.statistics.closed += 1
        return False
