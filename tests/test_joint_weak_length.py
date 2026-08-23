from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from formal_disk4.enumeration.assignments import (
    AssignmentTransform,
    ContourAssignment,
)
from formal_disk4.enumeration.joint_weak_length import (
    CyclicJointWeakLengthOracle,
)
from formal_disk4.constraints.rational_lp import RationalSimplex


def _assignment(sequences: tuple[tuple[int, ...], ...]) -> ContourAssignment:
    piece_count = len(sequences)
    return ContourAssignment(
        assignment_id=0,
        piece_names=tuple(f"T{index}" for index in range(piece_count)),
        sequences=sequences,
        orientation_signs=(1,) * piece_count,
        cyclic_offsets=(0,) * piece_count,
        stabilizer=(),
        canonical_key=sequences,
        required_equivariance="test_rotation",
    )


def test_prefix_oracle_returns_positive_length_witness_actions() -> None:
    assignment = _assignment(((0, 1), (2, 3)))
    transform = AssignmentTransform(
        automorphism_name="half_turn",
        piece_map=(1, 0),
        occurrence_map=(2, 3, 0, 1),
        reverse_cycle=False,
    )
    counters: dict[str, int] = {}

    def event(name: str, amount: int) -> None:
        counters[name] = counters.get(name, 0) + amount

    oracle = CyclicJointWeakLengthOracle(
        assignment,
        transform,
        splits=((2, 0),),
        positive_arc_endpoints={(0, 0): (0, 1), (0, 1): (2, 3)},
        interface_count=1,
        reference_index=0,
        random_seed=7,
        witness_attempts=4,
        event_sink=event,
    )

    root = oracle.prefix_extension(0, ())
    assert root is not None
    assert root.margin > 0.0
    assert root.next_masks == (1,)

    second = oracle.prefix_extension(0, ((0,),))
    assert second is not None
    assert second.next_masks == (1,)

    complete = oracle.prefix_extension(0, ((0,), (1,)))
    assert complete is not None
    assert complete.next_masks == ()
    assert counters["joint_weak_length_prefix_feasible"] == 3
    assert counters["joint_weak_length_witness_masks"] >= 2


def test_random_witness_objectives_expose_distinct_feasible_next_blocks() -> None:
    assignment = _assignment(((0, 1), (2, 3), (4, 5), (6, 7)))
    transform = AssignmentTransform(
        automorphism_name="half_turn",
        piece_map=(2, 3, 0, 1),
        occurrence_map=(4, 5, 6, 7, 0, 1, 2, 3),
        reverse_cycle=False,
    )
    oracle = CyclicJointWeakLengthOracle(
        assignment,
        transform,
        splits=((2, 2, 0, 0),),
        positive_arc_endpoints={},
        interface_count=0,
        reference_index=0,
        random_seed=19,
        witness_attempts=48,
        minimum_margin_fraction=0.05,
    )

    extension = oracle.prefix_extension(0, ())
    assert extension is not None
    assert len(extension.next_masks) > 1
    for mask in extension.next_masks:
        block = tuple(
            assignment.sequences[piece_index][0]
            for piece_index in range(len(assignment.sequences))
            if mask & (1 << piece_index)
        )
        assert 0 in block
        assert oracle.prefix_margin(0, (block,)) is not None


def test_prefix_oracle_rejects_only_length_infeasible_prefixes() -> None:
    assignment = _assignment(((0, 1), (2, 3), (4, 5), (6, 7)))
    transform = AssignmentTransform(
        automorphism_name="half_turn",
        piece_map=(2, 3, 0, 1),
        occurrence_map=(4, 5, 6, 7, 0, 1, 2, 3),
        reverse_cycle=False,
    )
    counters: dict[str, int] = {}

    def event(name: str, amount: int) -> None:
        counters[name] = counters.get(name, 0) + amount

    oracle = CyclicJointWeakLengthOracle(
        assignment,
        transform,
        splits=((2, 2, 0, 0),),
        positive_arc_endpoints={},
        interface_count=0,
        reference_index=0,
        random_seed=23,
        event_sink=event,
    )

    assert oracle.prefix_margin(0, ()) is not None
    assert oracle.prefix_margin(0, ((0, 2), (1, 3))) is not None
    # Consecutive occurrences of one tile cannot occupy the same weak block:
    # their intervening prototype arc is required to have positive length.
    assert oracle.prefix_margin(0, ((0, 1),)) is None
    assert counters["joint_weak_length_prefix_feasible"] == 2
    assert (
        counters.get("joint_weak_length_prefix_infeasible", 0)
        + counters.get("joint_weak_length_prefix_zero_margin", 0)
        == 1
    )


def test_invalid_joint_domain_returns_no_extension() -> None:
    assignment = _assignment(((0, 1), (2, 3)))
    transform = AssignmentTransform(
        automorphism_name="half_turn",
        piece_map=(1, 0),
        occurrence_map=(2, 3, 0, 1),
        reverse_cycle=False,
    )
    oracle = CyclicJointWeakLengthOracle(
        assignment,
        transform,
        # This is not a fundamental domain: occurrence orbits overlap.
        splits=((2, 2),),
        positive_arc_endpoints={},
        interface_count=0,
        reference_index=0,
        random_seed=3,
    )

    assert oracle.prefix_extension(0, ()) is None


def test_outer_arc_pair_disjunction_is_solved_inside_the_joint_system() -> None:
    assignment = _assignment(((0, 1), (2, 3), (4, 5), (6, 7)))
    transform = AssignmentTransform(
        automorphism_name="half_turn",
        piece_map=(2, 3, 0, 1),
        occurrence_map=(4, 5, 6, 7, 0, 1, 2, 3),
        reverse_cycle=False,
    )
    counters: dict[str, int] = {}

    def event(name: str, amount: int) -> None:
        counters[name] = counters.get(name, 0) + amount

    oracle = CyclicJointWeakLengthOracle(
        assignment,
        transform,
        splits=((2, 2, 0, 0),),
        positive_arc_endpoints={},
        interface_count=0,
        reference_index=0,
        # Equality of rotational copies 0 and 4 is impossible.  The second
        # alternative instead identifies two coordinates in one domain.
        outer_arc_equalities=(((0, 4),), ((0, 2), (1, 3))),
        random_seed=29,
        witness_attempts=0,
        event_sink=event,
    )

    extension = oracle.prefix_extension(0, ())
    assert extension is not None
    assert extension.margin > 0.0
    assert counters["joint_outer_arc_pair_checks"] == 2
    assert counters["joint_outer_arc_pair_infeasible"] == 1
    assert counters["joint_outer_arc_pair_feasible"] == 1
    # The rejected floating branch was confirmed by exact rational simplex.
    assert counters["joint_weak_length_exact_lp_calls"] == 1


def test_exact_outer_arc_infeasibility_closes_the_only_pair_branch() -> None:
    assignment = _assignment(((0, 1), (2, 3), (4, 5), (6, 7)))
    transform = AssignmentTransform(
        automorphism_name="half_turn",
        piece_map=(2, 3, 0, 1),
        occurrence_map=(4, 5, 6, 7, 0, 1, 2, 3),
        reverse_cycle=False,
    )
    oracle = CyclicJointWeakLengthOracle(
        assignment,
        transform,
        splits=((2, 2, 0, 0),),
        positive_arc_endpoints={},
        interface_count=0,
        reference_index=0,
        outer_arc_equalities=(((0, 4),),),
        random_seed=31,
    )

    assert oracle.prefix_extension(0, ()) is None


def test_exact_resource_limit_keeps_the_outer_arc_branch_open() -> None:
    assignment = _assignment(((0, 1), (2, 3), (4, 5), (6, 7)))
    transform = AssignmentTransform(
        automorphism_name="half_turn",
        piece_map=(2, 3, 0, 1),
        occurrence_map=(4, 5, 6, 7, 0, 1, 2, 3),
        reverse_cycle=False,
    )
    counters: dict[str, int] = {}

    def event(name: str, amount: int) -> None:
        counters[name] = counters.get(name, 0) + amount

    oracle = CyclicJointWeakLengthOracle(
        assignment,
        transform,
        splits=((2, 2, 0, 0),),
        positive_arc_endpoints={},
        interface_count=0,
        reference_index=0,
        # The second alternative must not be visited once the first one is
        # unknown: existential infeasibility can no longer be certified.
        outer_arc_equalities=(((0, 4),), ((0, 2), (1, 3))),
        random_seed=37,
        exact_max_tableau_cells=1,
        event_sink=event,
    )

    # Force the fast LP down the exact-certification path.  The deliberately
    # tiny exact budget must produce "unknown", never a false rejection.
    failed_float_lp = SimpleNamespace(success=False, x=None)
    with patch(
        "formal_disk4.enumeration.joint_weak_length.linprog",
        return_value=failed_float_lp,
    ) as mocked_linprog:
        extension = oracle.prefix_extension(0, ())
        repeated = oracle.prefix_extension(0, ())

    assert extension is not None
    assert extension.margin == 0.0
    assert extension.next_masks == ()
    assert repeated is not None
    assert counters["joint_weak_length_exact_resource_limit"] == 1
    assert counters["joint_weak_length_exact_tableau_limit"] == 1
    assert counters["joint_weak_length_exact_skipped"] == 1
    assert counters["joint_outer_arc_pair_unknown"] == 2
    assert counters["joint_outer_arc_pair_search_short_circuits"] == 2
    assert counters["joint_weak_length_prefix_unknown"] == 2
    assert mocked_linprog.call_count == 2
    assert counters.get("joint_outer_arc_pair_infeasible", 0) == 0
    assert counters.get("joint_weak_length_prefix_infeasible", 0) == 0


def test_rational_simplex_reports_a_pivot_budget_as_inconclusive() -> None:
    result = RationalSimplex(
        ((1,),),
        (1,),
        (1,),
        max_pivots=0,
    ).solve()

    assert result.status == "resource_limit"
    assert result.optimum is None
    assert result.solution == ()
