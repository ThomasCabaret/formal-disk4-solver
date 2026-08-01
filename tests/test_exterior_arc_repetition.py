import unittest

from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.enumeration.exterior_arc_repetition import (
    build_exterior_arc_repetition_constraint,
)
from formal_disk4.maps import build_c3_map, build_k4_map


class ExteriorArcRepetitionTests(unittest.TestCase):
    def test_k4_filter_is_applicable_but_does_not_reduce_phase_assignments(self) -> None:
        planar_map = build_k4_map()
        enumerator = AssignmentEnumerator(planar_map, symmetry_mode="incremental")
        assignments = tuple(enumerator.enumerate())
        self.assertEqual(len(assignments), 512)

        candidate_counts = []
        for assignment in assignments:
            constraint = build_exterior_arc_repetition_constraint(
                planar_map,
                assignment.piece_names,
                assignment.sequences,
                enumerator.occurrence_index,
                enabled=True,
            )
            self.assertTrue(constraint.applicable)
            self.assertTrue(constraint.candidate_pairs)
            candidate_counts.append(len(constraint.candidate_pairs))

        self.assertEqual(set(candidate_counts), {1, 3})

    def test_prefix_prunes_once_every_candidate_pair_has_split_an_endpoint(self) -> None:
        planar_map = build_k4_map()
        enumerator = AssignmentEnumerator(planar_map, symmetry_mode="incremental")
        assignment = next(enumerator.enumerate())
        constraint = build_exterior_arc_repetition_constraint(
            planar_map,
            assignment.piece_names,
            assignment.sequences,
            enumerator.occurrence_index,
            enabled=True,
        )
        self.assertEqual(len(constraint.candidate_pairs), 3)

        positions = [-1] * len(enumerator.occurrences)
        positions[constraint.arcs[0].start_occurrence] = 0
        self.assertTrue(constraint.prefix_is_feasible(positions))
        positions[constraint.arcs[1].start_occurrence] = 1
        self.assertFalse(constraint.prefix_is_feasible(positions))

    def test_filter_is_not_activated_for_non_stein_validation_maps(self) -> None:
        planar_map = build_c3_map()
        enumerator = AssignmentEnumerator(planar_map, symmetry_mode="incremental")
        assignment = next(enumerator.enumerate())
        constraint = build_exterior_arc_repetition_constraint(
            planar_map,
            assignment.piece_names,
            assignment.sequences,
            enumerator.occurrence_index,
            enabled=True,
        )
        self.assertFalse(constraint.applicable)
        self.assertEqual(constraint.reason, "requires_exactly_four_pieces")


if __name__ == "__main__":
    unittest.main()
