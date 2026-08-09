from __future__ import annotations

import math
import unittest
from pathlib import Path

from formal_disk4.maps.registry import build_map
from formal_disk4.orchestration.catalog import CaseCatalog
from formal_disk4.orchestration.catalog_diagrams import (
    build_catalog_schematic,
    polygon_area,
)


ROOT = Path(__file__).resolve().parents[1]


class CatalogDiagramTests(unittest.TestCase):
    def test_every_catalog_map_has_a_non_degenerate_schematic(self) -> None:
        catalog = CaseCatalog.load(ROOT)
        for map_name in sorted({case.map_name for case in catalog.cases}):
            with self.subTest(map_name=map_name):
                planar_map = build_map(map_name)
                schematic = build_catalog_schematic(planar_map)
                self.assertEqual(
                    {piece.name for piece in schematic.pieces},
                    {piece.name for piece in planar_map.pieces},
                )
                self.assertTrue(
                    all(polygon_area(piece.points) > 1e-8 for piece in schematic.pieces)
                )
                total_area = sum(
                    polygon_area(piece.points) for piece in schematic.pieces
                )
                self.assertGreater(total_area, 2.5)
                self.assertLess(total_area, 3.8)
                for vertex in schematic.outer_cycle:
                    x, y = schematic.vertex_positions[vertex]
                    self.assertAlmostEqual(math.hypot(x, y), 1.0, places=10)
                for interface in planar_map.interfaces:
                    view = interface.views[0]
                    start = schematic.vertex_positions[view.start_vertex]
                    end = schematic.vertex_positions[view.end_vertex]
                    self.assertGreater(math.dist(start, end), 1e-8)

    def test_boundary_point_contacts_remain_points_without_outer_edges(self) -> None:
        planar_map = build_map("c3-6plus3-t3b")
        schematic = build_catalog_schematic(planar_map)
        self.assertEqual(len(schematic.point_contacts), 3)
        outer_edges = {
            frozenset(
                (interface.views[0].start_vertex, interface.views[0].end_vertex)
            )
            for interface in planar_map.outer_interfaces()
        }
        for piece in planar_map.pieces:
            if piece.outer_boundary_contact != "point":
                continue
            outer_vertices = [
                vertex
                for vertex in piece.contour_vertices
                if planar_map.vertex_map()[vertex].kind == "outer"
            ]
            self.assertEqual(len(outer_vertices), 1)
            self.assertTrue(
                all(
                    outer_vertices[0] not in edge
                    for edge in outer_edges
                    if edge <= set(piece.contour_vertices)
                )
            )


if __name__ == "__main__":
    unittest.main()
