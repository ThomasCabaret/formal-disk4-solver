import random
import unittest
from types import SimpleNamespace

from formal_disk4.constraints.angle_lp import AngleFeasibilityOracle
from formal_disk4.constraints.length_lp import LengthFeasibilityOracle
from formal_disk4.enumeration.assignments import AssignmentEnumerator, AssignmentTransform
from formal_disk4.enumeration.exterior_arc_repetition import (
    ExteriorArcRepetitionConstraint,
    OrderedOuterArc,
)
from formal_disk4.enumeration.weak_orders import WeakOrderEnumerator
from formal_disk4.enumeration.weak_policy import WeakOrderStateView
from formal_disk4.maps import build_k4_central_map


class _RecordingPolicy:
    def __init__(self) -> None:
        self.proposals = 0

    def propose_masks(self, _state, masks):
        self.proposals += 1
        return masks

    def select_actions(self, _state, actions):
        return tuple(action.mask for action in actions)


class WeakOrderTests(unittest.TestCase):
    def test_dihedral_leaf_accepts_any_cut_but_not_a_wrong_reflection(self) -> None:
        enumerator = object.__new__(WeakOrderEnumerator)
        good = AssignmentTransform(
            automorphism_name="reflection_good",
            piece_map=(0,),
            occurrence_map=(0, 3, 2, 1),
            reverse_cycle=True,
        )
        bad = AssignmentTransform(
            automorphism_name="reflection_bad",
            piece_map=(0,),
            occurrence_map=(0, 2, 1, 3),
            reverse_cycle=True,
        )
        blocks = ((2,), (3,), (0,), (1,))

        enumerator.required_reflection_transforms = (good,)
        self.assertTrue(enumerator._dihedral_leaf_is_invariant(blocks))
        enumerator.required_reflection_transforms = (bad,)
        self.assertFalse(enumerator._dihedral_leaf_is_invariant(blocks))

    def test_cyclic_prefix_topology_receives_every_open_copy_frontier(self) -> None:
        calls = []
        counters = {}

        class RecordingTopologyFilter:
            def analyze(self, positions, block_count, *, open_frontiers=None):
                calls.append((tuple(positions), block_count, tuple(open_frontiers)))
                return SimpleNamespace(
                    applicable=True,
                    feasible=bool(open_frontiers),
                    reason=(
                        "feasible"
                        if open_frontiers
                        else "mapped circular arc crosses a hard outer endpoint"
                    ),
                    cache_hit=False,
                    topology=None,
                )

        def event(name: str, amount: int) -> None:
            counters[name] = counters.get(name, 0) + amount

        enumerator = object.__new__(WeakOrderEnumerator)
        enumerator.required_cyclic_shift_transform = AssignmentTransform(
            automorphism_name="half_turn",
            piece_map=(0, 1),
            occurrence_map=(2, 3, 0, 1),
            reverse_cycle=False,
        )
        enumerator._cyclic_shift_order = 2
        enumerator.occurrences = tuple(range(4))
        enumerator.event_sink = event
        enumerator.prefix_topology_filter = RecordingTopologyFilter()

        self.assertTrue(
            enumerator._cyclic_topology_allows_partial_blocks(
                ((0,),), complete=False
            )
        )
        self.assertFalse(
            enumerator._cyclic_topology_allows_partial_blocks(
                ((0,),), complete=True
            )
        )
        self.assertEqual(calls[0], ((0, -1, 1, -1), 2, (0, 1)))
        self.assertEqual(calls[1], ((0, -1, 1, -1), 2, ()))
        self.assertEqual(counters["prefix_topology_checks"], 2)
        self.assertEqual(counters["prefix_topology_pruned_nodes"], 1)

    def test_cyclic_prefix_applies_outer_arc_matching_before_the_leaf(self) -> None:
        counters = {}

        def event(name: str, amount: int) -> None:
            counters[name] = counters.get(name, 0) + amount

        enumerator = object.__new__(WeakOrderEnumerator)
        enumerator.required_cyclic_shift_transform = AssignmentTransform(
            automorphism_name="half_turn",
            piece_map=(0, 1),
            occurrence_map=(2, 3, 0, 1),
            reverse_cycle=False,
        )
        enumerator._cyclic_shift_order = 2
        enumerator.occurrences = tuple(range(4))
        enumerator.event_sink = event
        enumerator.exterior_arc_repetition = ExteriorArcRepetitionConstraint(
            applicable=True,
            reason="test",
            arcs=(
                OrderedOuterArc(0, "T0", 0, 2, False),
                OrderedOuterArc(1, "T1", 1, 3, False),
            ),
            candidate_pairs=((0, 1),),
        )

        # Advancing only one member permanently separates the two starts.
        self.assertFalse(
            enumerator._cyclic_repetition_allows_partial_blocks(((0,),))
        )
        # Advancing the pair together makes both endpoint coincidences hold
        # after the fundamental block is expanded by the half-turn.
        self.assertTrue(
            enumerator._cyclic_repetition_allows_partial_blocks(((0, 1),))
        )
        self.assertEqual(counters["exterior_arc_repetition_checks"], 2)
        self.assertEqual(counters["exterior_arc_repetition_pruned_nodes"], 1)

    def test_lazy_mask_domain_matches_expanded_domain(self) -> None:
        enumerator = object.__new__(WeakOrderEnumerator)
        enumerator.piece_names = tuple(f"T{index}" for index in range(5))
        enumerator.reference_index = 2
        enumerator.required_equivariance_transform = None

        available = 0b10111
        expanded = enumerator._candidate_masks(
            available, require_reference=True
        )
        lazy = enumerator._candidate_mask_domain(
            available, require_reference=True
        )

        self.assertEqual(tuple(lazy), expanded)
        self.assertEqual(len(lazy), len(expanded))
        self.assertTrue(all(mask in lazy for mask in expanded))
        self.assertNotIn(0b01000, lazy)

        enumerator.required_equivariance_transform = object()
        enumerator._equivariance_orbit_masks = (0b00011, 0b01100, 0b10000)
        enumerator.reference_index = 0
        equivariant = enumerator._candidate_masks(
            0b11111, require_reference=True
        )
        lazy_equivariant = enumerator._candidate_mask_domain(
            0b11111, require_reference=True
        )
        self.assertEqual(tuple(lazy_equivariant), equivariant)

    def test_nineteen_tile_policy_domain_stays_lazy_and_uniformly_sampleable(
        self,
    ) -> None:
        enumerator = object.__new__(WeakOrderEnumerator)
        enumerator.piece_names = tuple(f"T{index}" for index in range(19))
        enumerator.reference_index = 0
        enumerator.required_equivariance_transform = None
        domain = enumerator._candidate_mask_domain(
            (1 << 19) - 1, require_reference=True
        )

        self.assertEqual(len(domain), 1 << 18)
        self.assertNotIsInstance(domain, tuple)
        sample = random.Random(123).sample(domain, 64)
        self.assertEqual(len(sample), 64)
        self.assertEqual(len(set(sample)), 64)
        self.assertTrue(all(mask & 1 for mask in sample))

    def test_empty_legal_action_set_is_a_dead_leaf_not_a_policy_error(self) -> None:
        policy = _RecordingPolicy()
        enumerator = object.__new__(WeakOrderEnumerator)
        enumerator.branch_policy = policy
        state = WeakOrderStateView(
            assignment_id=0,
            path=(),
            counters=(0,),
            targets=(1,),
            block_count=0,
            resolved_length_equations=0,
            resolved_angle_equations=0,
            available_mask=0,
            reference_index=0,
            cyclic_shift_half=False,
        )

        self.assertEqual(enumerator._policy_propose_masks(state, ()), ())
        self.assertEqual(policy.proposals, 0)

    def test_first_survivor_has_all_constraints(self) -> None:
        planar_map = build_k4_central_map()
        assignments = AssignmentEnumerator(
            planar_map,
            allow_reflections=True,
            symmetry_mode="incremental",
        )
        assignment = next(assignments.enumerate())
        nodes = 0

        def event(name: str, amount: int) -> None:
            nonlocal nodes
            if name == "placement_nodes":
                nodes += amount

        enumerator = WeakOrderEnumerator(
            planar_map,
            assignment,
            assignments.occurrence_names,
            LengthFeasibilityOracle(),
            AngleFeasibilityOracle(),
            event_sink=event,
            stop_predicate=lambda: nodes >= 20_000,
        )
        placement = next(enumerator.enumerate())
        self.assertEqual(len(placement.length_rows), 6)
        self.assertEqual(len(placement.angle_equations), 6)
        # Float LPs are pruning oracles only. An inconclusive result is kept
        # conservatively and is represented by a zero margin with no witness.
        self.assertGreaterEqual(placement.length_margin, 0.0)
        self.assertGreaterEqual(placement.angle_margin, 0.0)
        if placement.length_margin > 0.0:
            self.assertTrue(placement.length_witness)
        if placement.angle_margin > 0.0:
            self.assertTrue(placement.angle_witness)


if __name__ == "__main__":
    unittest.main()
