from dataclasses import replace
from fractions import Fraction
from types import SimpleNamespace

import pytest

from formal_disk4.constraints.length_sector import LengthSectorRow
from formal_disk4.profiles.decorations import _terminal_lengths, DecorationInfeasible
from formal_disk4.profiles.canonical import conservative_profile_key
from formal_disk4.words.algebra import Literal
from formal_disk4.search.linear import Form
from formal_disk4.search.linear import LinearState, LinearTheory
from formal_disk4.search.contact_words import ForcedLengthComparison
from formal_disk4.search.contact_types import ContactTypeSearch
from formal_disk4.search.placement_adapter import PlacementAdapter
from test_contact_search import two_triangles


def terminal_lengths(row, same_component=False):
    compiled = SimpleNamespace(atomic_variables=('X0', 'X1'), outer_arcs=())
    environment = {'X0': (Literal('a'),), 'X1': (Literal('b'),)}
    placement = SimpleNamespace(length_rows=(), length_sector=(row,))
    mapping = {'a': 0, 'b': 0 if same_component else 1}
    return _terminal_lengths(compiled, environment, placement,
                             (None,) if same_component else (None, None), mapping, 1e-9)


def test_strict_sector_is_retained_as_positive_slack():
    lengths, margin, solution = terminal_lengths(LengthSectorRow((Fraction(1), Fraction(-1)), True))
    assert lengths[0] > lengths[1] and margin > 0
    assert 'L_SECTOR_0' in solution.variable_order
    expressions = solution.expression_map()
    assert (expressions['L_C0'] + expressions['L_C1'].scale(-1)
            + expressions['L_SECTOR_0'].scale(-1)).normalized().exact_value == 0


def test_terminal_identification_can_reject_a_strict_sector():
    with pytest.raises(DecorationInfeasible):
        terminal_lengths(LengthSectorRow((Fraction(1), Fraction(-1)), True), same_component=True)


def test_equal_sector_does_not_introduce_positive_slack():
    lengths, _, solution = terminal_lengths(LengthSectorRow((Fraction(1), Fraction(-1))))
    assert lengths == pytest.approx((.5, .5))
    assert all(not name.startswith('L_SECTOR') for name in solution.variable_order)


def test_sector_projection_is_homogeneous_and_handles_offsets_and_reflections():
    m = two_triangles()
    search = ContactTypeSearch(m, propagate_words=False, propagate_turns=False)
    adapter = PlacementAdapter(m)
    count = 0
    for contact in search.enumerate():
        model = search.model
        for chart in contact.charts:
            for occurrence, coordinate in zip(chart.sequence, chart.coordinates):
                enriched = replace(contact, sector=((coordinate, True), (model.one, True)))
                placement = adapter.materialize(enriched, 0)
                position = placement.positions[occurrence]
                # Shared physical interfaces may use the other tile's view:
                # equality holds modulo contact length equations, not spelling.
                width = len(contact.blocks)
                linear = LinearState(equalities=tuple(Form(tuple(r)) for r in placement.length_rows))
                actual = Form(placement.length_sector[0].coefficients)
                expected = Form(tuple(int(j < position) for j in range(width)))
                assert ForcedLengthComparison(linear, LinearTheory(width), max_queries=0)(actual, expected) == 0
                assert placement.length_sector[1].coefficients == (1,) * len(contact.blocks)
        count += 1
    assert count > 1


def test_distinct_sectors_cannot_be_deduplicated_as_one_profile():
    args = ('map', (), (), {'X': (Literal('a'),)})
    left = conservative_profile_key(*args, length_sector=(LengthSectorRow((1, -1), True),))
    right = conservative_profile_key(*args, length_sector=(LengthSectorRow((-1, 1), True),))
    assert left != right
    assert conservative_profile_key(*args) == conservative_profile_key(*args, length_sector=())


def test_sector_dfs_emits_constraints_without_changing_direct_incidence_coverage():
    m = two_triangles()
    before = list(ContactTypeSearch(m).enumerate())
    search = ContactTypeSearch(m, word_sectors=True, word_refinement_depth=1)
    after = list(search.enumerate())
    # A retained sector is attached to the leaf, not forgotten on insertion.
    assert search.word_sector_cases > 0
    assert any(contact.sector for contact in after)
    assert {c.blocks for c in after} <= {c.blocks for c in before}
    assert after


def test_full_profile_exports_sector_and_geometry_checks_it(tmp_path):
    import json
    from formal_disk4.maps import build_c3_map
    from formal_disk4.enumeration.assignments import AssignmentEnumerator
    from formal_disk4.enumeration.weak_orders import WeakOrderEnumerator
    from formal_disk4.constraints.length_lp import LengthFeasibilityOracle
    from formal_disk4.constraints.angle_lp import AngleFeasibilityOracle
    from formal_disk4.words.compile import compile_word_case
    from formal_disk4.words.exact_partial import ExactPartialWordSolver, SolverLimits
    from formal_disk4.words.families import expand_family, FamilyExpansionPolicy
    from formal_disk4.profiles.build import build_formal_profile
    from formal_disk4.geometry.model import parse_formal_geometry_problem, LinearFormula
    from formal_disk4.geometry.solver import NumericalContourSolver, GeometrySolverConfig
    m = build_c3_map()
    assignments = AssignmentEnumerator(m, allow_reflections=True, symmetry_mode='incremental')
    assignment = next(assignments.enumerate())
    placement = next(WeakOrderEnumerator(m, assignment, assignments.occurrence_names,
                        LengthFeasibilityOracle(), AngleFeasibilityOracle()).enumerate())
    placement = replace(placement, length_sector=(LengthSectorRow((Fraction(1),)*placement.interval_count, True),))
    compiled = compile_word_case(m, placement)
    family = next(ExactPartialWordSolver(compiled.equations, compiled.atomic_variables).solve(
        SolverLimits(max_graph_nodes=100, max_graph_edges=400, max_families=8,
                     max_expression_nodes=500, validation_exponent=2)))
    specialization = next(expand_family(family, FamilyExpansionPolicy(kind='none')))
    profile = build_formal_profile(m, assignments.occurrence_names, placement, compiled, family, specialization)
    payload = json.loads(json.dumps({'profile': profile.to_dict()}))
    problem = parse_formal_geometry_problem(payload, source_path=tmp_path/'profile.jsonl', source_line=1)
    assert len(problem.positive_length_sectors) == 1
    solver = NumericalContourSolver(GeometrySolverConfig())
    # Even an otherwise accepted contour cannot escape its length sector.
    problem = replace(problem, strict_angle_constraints=(),
                      positive_length_sectors=(LinearFormula(-1, (), '-1'),))
    # dataclasses.replace is used by the real validator.
    from formal_disk4.geometry.model import GeometryValidation
    validation = GeometryValidation(True, 0, 0, 0, 0, 1, None, 0, 1, ())
    checked = solver._validate_formal_constraints(problem,
        SimpleNamespace(parameter_values={}, target_angles=()), validation)
    assert not checked.passed
    assert ('formal_length_sector', False) in tuple((name, passed) for name, passed, _ in checked.checks)
