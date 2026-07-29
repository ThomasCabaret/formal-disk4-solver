import unittest
from fractions import Fraction

from formal_disk4.maps import build_k4_map
from formal_disk4.maps.base import PlanarMap, VertexSpec


class K4MapTests(unittest.TestCase):
    def test_invariants(self) -> None:
        planar_map = build_k4_map()
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


    def test_vertex_angle_sum_is_determined_by_disk_location(self) -> None:
        planar_map = build_k4_map()
        for vertex in planar_map.vertices:
            expected = Fraction(2) if vertex.kind == "interior" else Fraction(1)
            self.assertEqual(vertex.required_solid_angle_sum_pi, expected)

    def test_invalid_declared_vertex_angle_sum_is_rejected(self) -> None:
        planar_map = build_k4_map()
        bad_vertex = VertexSpec(
            planar_map.vertices[0].name,
            "interior",
            planar_map.vertices[0].incident_pieces,
            1.0,
        )
        invalid = PlanarMap(
            name=planar_map.name,
            pieces=planar_map.pieces,
            vertices=(bad_vertex,) + planar_map.vertices[1:],
            interfaces=planar_map.interfaces,
            automorphisms=planar_map.automorphisms,
            reference_piece=planar_map.reference_piece,
        )
        with self.assertRaisesRegex(ValueError, "requires 2"):
            invalid.validate()

    def test_shared_internal_edges_have_opposite_piece_orientation(self) -> None:
        planar_map = build_k4_map()
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
