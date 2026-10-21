from collections import Counter
from fractions import Fraction
from pathlib import Path

from formal_disk4.maps.base import PlanarMap, PieceSpec, VertexSpec, InterfaceSpec, InterfaceView
from formal_disk4.enumeration.frontier_arrangements import FrontierArrangementEnumerator
from formal_disk4.search.angles import ContactAngleTheory
from formal_disk4.search.linear import Form, LinearState, LinearTheory
from formal_disk4.search.placement_adapter import ContactArrangementEnumerator


def two_triangles():
    pieces = (PieceSpec('a', ('A', 'B', 'C'), False),
              PieceSpec('b', ('B', 'A', 'D'), False))
    vertices = tuple(VertexSpec(v, 'free', tuple(p.name for p in pieces if v in p.contour_vertices), 2)
                     for v in 'ABCD')
    edges = [InterfaceSpec('AB', 'a', 'b', (InterfaceView('a', 'A', 'B'), InterfaceView('b', 'B', 'A')))]
    for p, a, b in [('a', 'B', 'C'), ('a', 'C', 'A'), ('b', 'A', 'D'), ('b', 'D', 'B')]:
        edges.append(InterfaceSpec(a+b, p, None, (InterfaceView(p, a, b),), is_free=True))
    return PlanarMap('two-triangles', pieces, vertices, tuple(edges), (), 'a', outer_boundary_is_complete=False)


def test_affine_strict_and_nonstrict():
    x, y = Form.variable(2, 0), Form.variable(2, 1)
    theory = LinearTheory(2)
    assert theory.check(LinearState().equal(x).nonnegative(x))
    assert not theory.check(LinearState().equal(x-y).positive(x-y))
    assert not theory.check(LinearState().positive(x).positive(y).equal(x+y))
    assert theory.check(LinearState().positive(x).positive(y).equal(x+y-Form.scalar(2, 1)))
    assert theory.check(LinearState().positive(x).equal(x-Form.scalar(2, Fraction(1, 10**12))))


def test_unknown_linear_outcome_does_not_prune(monkeypatch):
    from types import SimpleNamespace
    theory = LinearTheory(1)
    monkeypatch.setattr(theory.oracle, 'analyze', lambda **_: SimpleNamespace(
        feasible=False, exact_certificate_used=False, status='float:failure'))
    assert theory.check(LinearState().positive(Form.variable(1, 0)))
    assert theory.unknown == 1


def test_contact_matches_exhaustive_legacy_with_exact_metric_filter():
    m = two_triangles()
    angle = ContactAngleTheory(m)
    expected = set()
    reference = {}
    for p in FrontierArrangementEnumerator(m, allow_reflections=True).enumerate():
        n = len(p.blocks)
        state = LinearState(equalities=tuple(Form(tuple(row)) for row in p.length_rows))
        state = state.equal(Form((1,)*n, -1))
        for i in range(n):
            state = state.positive(Form.variable(n, i))
        if LinearTheory(n).check(state) and angle.check(p.blocks):
            expected.add(p.blocks)
            reference[p.blocks] = p
    counts = Counter()
    search = ContactArrangementEnumerator(m, propagate_turns=False, propagate_words=False,
                                        event_sink=lambda k, v=1: counts.update({k:v}))
    placements = list(search.enumerate())
    actual = {p.blocks for p in placements}
    assert expected
    assert actual == expected
    assert len(placements) == len(actual)
    assert {p.assignment.orientation_signs[1] for p in placements} == {-1, 1}
    assert any(len(b)>1 for p in placements for b in p.blocks)
    assert counts['contact_cut_length_rejections'] > 0
    for p in placements:
        old = reference[p.blocks]
        assert p.length_rows == old.length_rows
        assert p.angle_equations == old.angle_equations
        assert p.angle_inequalities == old.angle_inequalities
        assert p.assignment == old.assignment


def test_contact_node_budget_reports_stop_without_exhaustion():
    search = ContactArrangementEnumerator(two_triangles(), max_nodes=1)
    assert list(search.enumerate()) == []
    assert search.search.stopped


def test_contact_turns_keep_triangular_patches_and_reject_complementary_contacts():
    from formal_disk4.search.contact_model import ContactModel
    from formal_disk4.search.contact_turns import ContactTurnTheory
    theory = ContactTurnTheory(ContactModel(two_triangles()))
    # Equilateral triangles: all marked turns 2/3, all interval turns zero.
    assert theory.check(((0, 3), (1, 4), (2, 5)), (1, 1))
    assert theory.check(((0, 4), (1, 3), (2, 5)), (1, -1))
    # Here the two contact factors cover complementary prototype arcs.
    # Their sum of interior turns is zero; total contour turning would then
    # require the two remaining endpoint turns to sum to 2, impossible with
    # each strictly below 1. This is not a numerical geometric failure.
    assert not theory.check(((0, 4), (5,), (1, 3), (2,)), (1, 1))
    # Missing future corners belong to unrestricted interval turn, not zero.
    assert theory.check(((0,), (1,), (2,)), (1, 0))


def test_contact_reaches_existing_formal_profile_kernel():
    from formal_disk4.graph_lab.evaluator import GraphFormalEvaluator
    from formal_disk4.graph_lab.space import candidate_from_planar_map
    config = {'base_search_config': 'config/cycle_campaign/search.json',
              'contact_word_refinement_depth': 2,
              'joint_arrangement_search': {'enabled': True, 'strategy': 'contact_types',
                                          'max_nodes': 1000, 'time_limit_seconds': 10}}
    evaluator = GraphFormalEvaluator(Path.cwd(), config)
    snapshots = []
    result = evaluator.evaluate_joint_arrangements(
        candidate_from_planar_map('k3-pizza', imposed_automorphism=None),
        progress_sink=snapshots.append, profile_consumer=lambda _: True)
    assert result.error is None
    assert result.profiles
    assert result.counters['arrangement_engine_contact_types'] == 1
    assert snapshots[-1]['search_progress']['engine'] == 'contact_types'
