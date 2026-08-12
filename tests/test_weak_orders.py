import unittest

from formal_disk4.constraints.angle_lp import AngleFeasibilityOracle
from formal_disk4.constraints.length_lp import LengthFeasibilityOracle
from formal_disk4.enumeration.assignments import AssignmentEnumerator
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
