import unittest

from formal_disk4.maps import build_k4_central_map


class K4MapTests(unittest.TestCase):
    def test_invariants(self) -> None:
        planar_map = build_k4_central_map()
        planar_map.validate()
        self.assertEqual(len(planar_map.pieces), 4)
        self.assertEqual(len(planar_map.vertices), 6)
        self.assertEqual(len(planar_map.internal_interfaces()), 6)
        self.assertEqual(len(planar_map.outer_interfaces()), 3)
        self.assertEqual(len(planar_map.occurrences()), 15)
        self.assertEqual(len(planar_map.automorphisms), 6)
        geometric_edges = len(planar_map.interfaces)
        faces_including_exterior = 5
        self.assertEqual(len(planar_map.vertices) - geometric_edges + faces_including_exterior, 2)

    def test_shared_internal_edges_have_opposite_piece_orientation(self) -> None:
        planar_map = build_k4_central_map()
        for interface in planar_map.internal_interfaces():
            left, right = interface.views
            self.assertEqual(
                {left.start_vertex, left.end_vertex},
                {right.start_vertex, right.end_vertex},
            )
            self.assertEqual(left.start_vertex, right.end_vertex)
            self.assertEqual(left.end_vertex, right.start_vertex)


if __name__ == "__main__":
    unittest.main()
