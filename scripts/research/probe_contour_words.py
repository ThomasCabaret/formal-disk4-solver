"""CPLX-002 algebra probe, not a replacement word or geometry solver.

Run from the repository root with its Python environment. The linear witness
uses the existing exact simplex; the signed-cover check deliberately expands
SMALL length instances to validate a reduction, not to implement AHT.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from itertools import product
import json
from math import gcd, lcm
from pathlib import Path
import random
from time import perf_counter

from formal_disk4.constraints.rational_lp import RationalSimplex
from formal_disk4.words.algebra import Equation, Literal, substitute_word


def positive_length_witness(equations, variables, equal_lengths=()):
    """Exact A*n=0, n>=1 witness; no general polynomial bound for this simplex."""
    columns = {name: i for i, name in enumerate(variables)}
    rows = []
    for equation in equations:
        row = [0] * len(variables)
        for side, sign in ((equation.left, 1), (equation.right, -1)):
            for literal in side:
                row[columns[literal.variable]] += sign
        rows.append(row)
    for left, right in equal_lengths:
        row = [0] * len(variables)
        row[columns[left]] += 1
        row[columns[right]] -= 1
        rows.append(row)
    matrix, bounds = [], []
    for row in rows:
        matrix.extend((row, [-x for x in row]))
        bounds.extend((-sum(row), sum(row)))
    result = RationalSimplex(matrix, bounds, [0] * len(variables)).solve()
    if result.status != "optimal":
        return None, result.status
    rational = [1 + x for x in result.solution]
    scale = lcm(*(x.denominator for x in rational))
    weights = [int(x * scale) for x in rational]
    common = gcd(*weights)
    return dict(zip(variables, (x // common for x in weights))), result.status


def palindromic_witness(weights):
    block = (Literal("probe_atom"), Literal("probe_atom", True))
    return {variable: block * length for variable, length in weights.items()}


class _Union:
    def __init__(self, count):
        self.parent = list(range(count))

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def join(self, x, y):
        self.parent[self.find(x)] = self.find(y)

    def count(self):
        return len({self.find(x) for x in range(len(self.parent))})


def explicit_signed_cover(equations, lengths):
    """Small-instance control for the compact pairing/double-cover argument."""
    offsets, size = {}, 0
    for name, length in lengths.items():
        if length < 1:
            raise ValueError("Lengths must be positive integers")
        offsets[name], size = size, size + length
    if size > 10000:
        raise ValueError("This diagnostic expands cells; keep sum(lengths)<=10000")

    def positions(word):
        output = []
        for literal in word:
            start = offsets[literal.variable]
            cells = range(start, start + lengths[literal.variable])
            if literal.inverse:
                cells = reversed(cells)
            output.extend((cell, int(literal.inverse)) for cell in cells)
        return output

    base, cover = _Union(size), _Union(2 * size)
    for equation in equations:
        left, right = positions(equation.left), positions(equation.right)
        if len(left) != len(right):
            return False, None, None
        for (p, a), (q, b) in zip(left, right):
            flip = a ^ b
            base.join(p, q)
            for sheet in (0, 1):
                cover.join(p + sheet * size, q + (sheet ^ flip) * size)
    base_count, cover_count = base.count(), cover.count()
    return cover_count == 2 * base_count, base_count, cover_count


def brute_binary_words(equations, lengths):
    names = tuple(lengths)
    choices = [tuple(product((False, True), repeat=lengths[name])) for name in names]
    for words in product(*choices):
        environment = {
            name: tuple(Literal("a", bit) for bit in word)
            for name, word in zip(names, words)
        }
        if all(substitute_word(e.left, environment) == substitute_word(e.right, environment)
               for e in equations):
            return True
    return False


def algebra_controls():
    x, y = Literal("X"), Literal("Y")
    cases = [
        ((Equation((x,), (x.flipped(),)),), {"X": 1}),
        ((Equation((x,), (x.flipped(),)),), {"X": 2}),
        ((Equation((x, y), (y, x)),), {"X": 2, "Y": 3}),
        ((Equation((x,), (x, x)),), {"X": 1}),
    ]
    rng = random.Random(27021)
    for _ in range(160):
        lengths = {"X": rng.randint(1, 3), "Y": rng.randint(1, 3)}
        equations = tuple(Equation(
            tuple(Literal(rng.choice(("X", "Y")), bool(rng.randrange(2)))
                  for _ in range(rng.randint(1, 3))),
            tuple(Literal(rng.choice(("X", "Y")), bool(rng.randrange(2)))
                  for _ in range(rng.randint(1, 3))))
            for _ in range(rng.randint(1, 3)))
        cases.append((equations, lengths))
    positive_controls = 0
    infeasible_controls = 0
    for equations, lengths in cases:
        assert explicit_signed_cover(equations, lengths)[0] == brute_binary_words(equations, lengths)
        variables = tuple(sorted({literal.variable for equation in equations
                                  for side in (equation.left, equation.right) for literal in side}))
        weights, status = positive_length_witness(equations, variables)
        if weights is not None:
            environment = palindromic_witness(weights)
            assert all(substitute_word(e.left, environment) == substitute_word(e.right, environment)
                       for e in equations)
            positive_controls += 1
        else:
            assert status == "infeasible", status
            infeasible_controls += 1
    assert explicit_signed_cover(*cases[0])[0] is False
    assert explicit_signed_cover(*cases[1])[0] is True
    weights, _ = positive_length_witness(cases[3][0], ("X",))
    assert weights is None
    return {"seed": 27021, "signed_cover_vs_bruteforce": len(cases),
            "bare_lp_constructed_witnesses": positive_controls,
            "bare_lp_infeasible": infeasible_controls}


def compiler_controls():
    from formal_disk4.constraints.angle_lp import AngleFeasibilityOracle
    from formal_disk4.constraints.length_lp import LengthFeasibilityOracle
    from formal_disk4.enumeration.assignments import AssignmentEnumerator
    from formal_disk4.enumeration.weak_orders import WeakOrderEnumerator
    from formal_disk4.maps import build_c3_map, build_c4_map
    from formal_disk4.profiles.build import build_formal_profile
    from formal_disk4.profiles.decorations import DecorationInfeasible
    from formal_disk4.profiles.filters import ProfileFilterPipeline
    from formal_disk4.words.compile import compile_word_case
    from formal_disk4.words.exact_partial import ExactPartialWordSolver, SolverLimits
    from formal_disk4.words.families import (
        ExactFormalFamily, FamilyExpansionPolicy, FamilySpecialization, expand_family, expr_from_word,
    )

    records = []
    for builder in (build_c3_map, build_c4_map):
        original = builder()
        for boundary in ("disk", "free"):
            model = original
            if boundary == "free":
                model = replace(original, name=original.name + "-probe-free",
                    pieces=tuple(replace(p, touches_outer_boundary=False, outer_boundary_contact="none")
                                 for p in original.pieces),
                    vertices=tuple(replace(v, kind="free", angle_sum_pi=2.0)
                                   if v.is_outer_boundary else v for v in original.vertices),
                    interfaces=tuple(replace(e, is_outer=False, is_free=True)
                                     if e.is_outer else e for e in original.interfaces),
                    outer_boundary_is_complete=False)
            model.validate()
            assignments = AssignmentEnumerator(model, allow_reflections=False, symmetry_mode="incremental")
            assignment = next(assignments.enumerate())
            started = perf_counter()
            iterator = WeakOrderEnumerator(model, assignment, assignments.occurrence_names,
                LengthFeasibilityOracle(), AngleFeasibilityOracle(),
                stop_predicate=lambda: perf_counter() - started > 10).enumerate()
            placement = next(iterator, None)
            iterator.close()
            if placement is None:
                records.append({"map": model.name, "status": "no_control_placement_within_budget"})
                continue
            compiled = compile_word_case(model, placement)
            solve_started = perf_counter()
            weights, status = positive_length_witness(compiled.effective_solver_equations,
                compiled.solver_variables,
                tuple((a, b) for a, b in compiled.mirror_variables if b in compiled.solver_variables))
            assert weights is not None, status
            environment = palindromic_witness(weights)
            assert all(substitute_word(e.left, environment) == substitute_word(e.right, environment)
                       for e in compiled.effective_solver_equations)
            witness_seconds = perf_counter() - solve_started
            specialization = FamilySpecialization(0, "diagnostic_periodic",
                (), tuple(environment.items()), ())
            family = ExactFormalFamily(0, "diagnostic_periodic",
                tuple((v, expr_from_word(w)) for v, w in environment.items()), (), (), 0)
            try:
                profile = build_formal_profile(model, assignments.occurrence_names, placement,
                    compiled, family, specialization)
                decoration = "profile_built_not_geometry_validated"
                reason = ""
            except DecorationInfeasible as error:
                decoration, reason = error.stage, error.reason
            ordinary_control = "not_requested_for_free_boundary"
            if boundary == "disk":
                solver = ExactPartialWordSolver(compiled.effective_solver_equations,
                    compiled.solver_variables, contour_variables=compiled.atomic_variables)
                iterator = solver.solve(SolverLimits(max_graph_nodes=100, max_graph_edges=400,
                    max_families=1, max_expression_nodes=500))
                try:
                    ordinary_family = next(iterator)
                    ordinary_specialization = next(expand_family(ordinary_family,
                        FamilyExpansionPolicy(kind="minimum")))
                    ordinary_profile = build_formal_profile(model, assignments.occurrence_names,
                        placement, compiled, ordinary_family, ordinary_specialization)
                    filtered, statuses = ProfileFilterPipeline().apply(ordinary_profile)
                    assert filtered is not None, statuses
                    ordinary_control = "usual_first_family_passes_profile_filters_not_geometry_checked"
                finally:
                    iterator.close()
            counts = Counter(l.variable for e in compiled.effective_solver_equations
                             for side in (e.left, e.right) for l in side)
            records.append({"map": model.name, "boundary": boundary,
                "variables": list(compiled.solver_variables),
                "equations": [e.to_text() for e in compiled.effective_solver_equations],
                "weights": weights, "max_raw_variable_occurrences": max(counts.values(), default=0),
                "lp_and_witness_seconds": witness_seconds,
                "formal_word_witness_valid": True,
                "ordinary_positive_control": ordinary_control,
                "decoration_outcome": decoration, "decoration_reason": reason})
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    started = perf_counter()
    report = {"schema": "CPLX-002-word-probe-v1", "algebra": algebra_controls(),
              "compiler_controls": compiler_controls(),
              "limitations": "Not an AHT implementation, geometry solver, speedup benchmark or completeness proof."}
    report["elapsed_seconds"] = perf_counter() - started
    payload = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
