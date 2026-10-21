from fractions import Fraction

from formal_disk4.search.linear import Form, LinearState, LinearTheory
from formal_disk4.search.contact_words import ForcedLengthComparison
from formal_disk4.search.word_propagation import (
    Corner, Factor, REVERSE, MIRROR, propagate, transform_word,
)


def constants(*values):
    return tuple(Form.scalar(1, v) for v in values)


def compare(a, b):
    assert not any(a.coefficients) and not any(b.coefficients)
    return (a.constant > b.constant) - (a.constant < b.constant)


def test_two_distinct_involutions_and_corner_signs():
    word = (Factor(0), Corner(0), Factor(1))
    assert transform_word(word, REVERSE) == (Factor(1, REVERSE), Corner(0, -1), Factor(0, REVERSE))
    assert transform_word(word, MIRROR) == (Factor(0, MIRROR), Corner(0, -1), Factor(1, MIRROR))
    for a in range(4):
        for b in range(4):
            assert transform_word(transform_word(word, a), b) == transform_word(word, a ^ b)


def test_equal_factors_transport_interior_corner_with_correct_sign():
    left = (Factor(0), Corner(0), Factor(1))
    right = (Factor(2), Corner(1), Factor(3))
    for transform in range(4):
        result = propagate(((left, transform_word(right, transform)),), constants(1, 1, 1, 1), 2, compare)
        sign = -1 if transform in (REVERSE, MIRROR) else 1
        assert (0, 1, sign) in result.relations
        assert result.feasible


def test_forced_levi_split_creates_corner_not_assumed_smooth():
    for transform in range(4):
        result = propagate(( ((Factor(0), Corner(0), Factor(1)), (Factor(2, transform),)), ),
                           constants(1, 2, 3), 1, compare)
        assert result.feasible and result.splits == 1
        assert result.point_count == 2
        assert result.relations == ((0, 1, 1),)


def test_propagation_reaches_other_equations_after_split():
    result = propagate((
        ((Factor(0), Corner(0), Factor(1)), (Factor(2),)),
        ((Factor(3), Corner(1), Factor(4)), (Factor(2, MIRROR),)),
    ), constants(1, 2, 3, 1, 2), 2, compare)
    assert result.feasible and result.splits == 1
    assert (0, 2, 1) in result.relations
    assert (1, 2, -1) in result.relations


def test_nonempty_cancellation_contradiction_and_self_symmetry():
    result = propagate((((Factor(0),), (Factor(0), Corner(0), Factor(1))),), constants(1, 1), 1, compare)
    assert not result.feasible
    for transform in (REVERSE, MIRROR, REVERSE | MIRROR):
        result = propagate((((Factor(0),), (Factor(0, transform),)),), constants(1), 0, compare)
        assert result.feasible and result.residual_equations


def test_ambiguous_or_budget_limited_propagation_preserves_branch():
    equations = (((Factor(0), Corner(0), Factor(1)), (Factor(2),)),)
    result = propagate(equations, constants(1, 2, 3), 1, lambda a, b: None)
    assert result.feasible and result.residual_equations and not result.splits
    result = propagate(equations, constants(1, 2, 3), 1, compare, max_steps=0)
    assert result.feasible and result.limited


def test_length_comparison_is_entailment_not_a_chosen_witness():
    x, y = Form.variable(2, 0), Form.variable(2, 1)
    state = LinearState().positive(x).positive(y).equal(x+y-Form.scalar(2, 1))
    assert ForcedLengthComparison(state, LinearTheory(2))(x, y) is None
    state = state.equal(x-y)
    assert ForcedLengthComparison(state, LinearTheory(2), max_queries=0)(x, y) == 0
    state = LinearState().positive(x-y).equal(x-y-Form.scalar(2, Fraction(1, 10**12)))
    assert ForcedLengthComparison(state, LinearTheory(2))(x, y) == 1


def test_persistent_snapshot_resumes_without_mutating_siblings():
    x = Form.variable(1, 0)
    one = Form.scalar(1, 1)
    equations = (((Factor(0), Corner(0), Factor(1)), (Factor(2),)),)
    initial = propagate(equations, (x, one-x, one), 1, lambda a, b: None)
    assert initial.ambiguous is not None
    saved = initial.state
    linear = LinearState().positive(x).positive(one-x)
    resumed = propagate((), (), 0, ForcedLengthComparison(linear, LinearTheory(1)), resume=saved)
    fresh = propagate(equations, (x, one-x, one), 1, ForcedLengthComparison(linear, LinearTheory(1)))
    assert resumed == fresh
    assert initial.state == saved and not saved.replacements


def test_levi_lookahead_closes_only_if_all_three_cases_fail():
    from formal_disk4.search.word_propagation import Propagation
    from formal_disk4.search.word_refinement import WordRefinement
    diff = Form.variable(1, 0)
    initial = Propagation(True, 0, (), ambiguous=diff)
    for good in (None, -1, 0, 1):
        visited = []
        def continuation(snapshot, linear):
            sign = ForcedLengthComparison(linear, LinearTheory(1), max_queries=0)(diff, Form.scalar(1, 0))
            visited.append(sign)
            return Propagation(sign == good, 0, ())
        checker = WordRefinement(LinearTheory(1), continuation, lambda r: True)
        assert checker.check(initial, LinearState()) == (good is not None)
        if good is None:
            assert visited == [0, -1, 1]
            assert checker.statistics.closed == 1


def test_levi_budget_and_open_residual_keep_unrestricted_parent():
    from formal_disk4.search.word_propagation import Propagation
    from formal_disk4.search.word_refinement import WordRefinement
    initial = Propagation(True, 0, (), ambiguous=Form.variable(1, 0))
    checker = WordRefinement(LinearTheory(1), lambda s, l: initial, lambda r: True, max_depth=2)
    parent = LinearState()
    assert checker.check(initial, parent)
    assert parent == LinearState()
    assert checker.statistics.deferred == 1
    assert checker.statistics.closed == 0


def test_cli_transmits_levi_depth_without_a_global_tree_limit():
    from pathlib import Path
    from formal_disk4.graph_lab.backtracking_lab import build_parser, _evaluation_config
    args = build_parser().parse_args(['--engine', 'contact-types', '--contact-word-refinement-depth', '2'])
    config = _evaluation_config(Path('config/local_graph_campaign/formal.json'),
        engine=args.engine, contact_word_refinement_depth=args.contact_word_refinement_depth)
    assert config['contact_word_refinement_depth'] == 2
    assert config['joint_arrangement_search']['max_nodes'] is None
    assert config['joint_arrangement_search']['time_limit_seconds'] is None
