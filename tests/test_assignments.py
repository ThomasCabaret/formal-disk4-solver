import unittest

from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.maps import build_k4_central_map


class AssignmentTests(unittest.TestCase):
    def test_direct_assignments_defer_reflection_quotient(self) -> None:
        enumerator = AssignmentEnumerator(
            build_k4_central_map(),
            allow_reflections=False,
            symmetry_mode="assignment",
        )
        self.assertEqual(enumerator.raw_assignment_count(), 64)
        self.assertEqual(len(list(enumerator.enumerate())), 64)
        self.assertTrue(
            all(
                action.orientation_sign == 1
                for action in enumerator.mapping_symmetry.assignment_group
            )
        )

    def test_reflected_assignments_defer_reflection_quotient(self) -> None:
        enumerator = AssignmentEnumerator(
            build_k4_central_map(),
            allow_reflections=True,
            symmetry_mode="assignment",
        )
        self.assertEqual(enumerator.raw_assignment_count(), 512)
        self.assertEqual(len(list(enumerator.enumerate())), 512)
        self.assertTrue(
            all(
                action.orientation_sign == 1
                for action in enumerator.mapping_symmetry.assignment_group
            )
        )


if __name__ == "__main__":
    unittest.main()
