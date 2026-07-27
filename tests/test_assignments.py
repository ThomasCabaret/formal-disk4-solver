import unittest

from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.maps import build_k4_central_map


class AssignmentTests(unittest.TestCase):
    def test_direct_assignment_orbits(self) -> None:
        enumerator = AssignmentEnumerator(
            build_k4_central_map(),
            allow_reflections=False,
            symmetry_mode="assignment",
        )
        self.assertEqual(enumerator.raw_assignment_count(), 192)
        self.assertEqual(len(list(enumerator.enumerate())), 32)

    def test_reflected_assignment_orbits(self) -> None:
        enumerator = AssignmentEnumerator(
            build_k4_central_map(),
            allow_reflections=True,
            symmetry_mode="assignment",
        )
        self.assertEqual(enumerator.raw_assignment_count(), 1536)
        self.assertEqual(len(list(enumerator.enumerate())), 256)


if __name__ == "__main__":
    unittest.main()
