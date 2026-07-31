from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.maps.registry import build_map, canonical_map_name
from formal_disk4.orchestration.catalog import CaseCatalog
from formal_disk4.orchestration.pipeline import PipelineTask, materialize_task


ROOT = Path(__file__).resolve().parents[1]


THREE_RING_CASES = (
    "three-ring-parallel-3",
    "three-ring-boundary-points-3",
    "three-ring-outer-offset-3",
    "three-ring-inner-offset-3",
    "three-ring-offset-same-3",
    "three-ring-offset-opposite-3",
)


class ThreeRingMapTests(unittest.TestCase):
    def _contacts(self, map_name: str) -> set[frozenset[str]]:
        planar_map = build_map(map_name)
        return {
            frozenset((interface.left_piece, interface.right_piece))
            for interface in planar_map.internal_interfaces()
        }

    def test_three_ring_maps_are_valid_nine_tile_disk_maps(self) -> None:
        for map_name in THREE_RING_CASES:
            with self.subTest(map_name=map_name):
                planar_map = build_map(map_name)
                planar_map.validate()
                self.assertEqual(len(planar_map.pieces), 9)
                self.assertEqual(
                    len(planar_map.vertices)
                    - len(planar_map.interfaces)
                    + len(planar_map.pieces),
                    1,
                )
                self.assertEqual(len(planar_map.automorphisms), 3)
                assignments = AssignmentEnumerator(
                    planar_map,
                    symmetry_mode="incremental",
                    required_equivariance="rotation_1",
                )
                self.assertEqual(len(assignments.mapping_symmetry.group), 3)

    def test_parallel_family_has_three_cycles_and_matching_radials(self) -> None:
        contacts = self._contacts("three-ring-parallel-3")
        for index in range(3):
            current = index + 1
            next_index = (index + 1) % 3 + 1
            self.assertIn(frozenset((f"E{current}", f"E{next_index}")), contacts)
            self.assertIn(frozenset((f"M{current}", f"M{next_index}")), contacts)
            self.assertIn(frozenset((f"I{current}", f"I{next_index}")), contacts)
            self.assertIn(frozenset((f"E{current}", f"M{current}")), contacts)
            self.assertIn(frozenset((f"M{current}", f"I{current}")), contacts)

    def test_boundary_point_variant_opens_only_the_outer_cycle(self) -> None:
        planar_map = build_map("three-ring-boundary-points-3")
        contacts = self._contacts(planar_map.name)
        self.assertFalse(
            any(all(piece.startswith("E") for piece in contact) for contact in contacts)
        )
        self.assertTrue(
            all(
                planar_map.piece_map()[f"M{index}"].outer_boundary_contact == "point"
                for index in range(1, 4)
            )
        )
        self.assertTrue(
            any(all(piece.startswith("M") for piece in contact) for contact in contacts)
        )
        self.assertTrue(
            any(all(piece.startswith("I") for piece in contact) for contact in contacts)
        )

    def test_same_and_opposite_chirality_are_distinct_maps(self) -> None:
        same = build_map("three-ring-offset-same-3")
        opposite = build_map("three-ring-offset-opposite-3")
        same_rotation = dict(same.automorphisms[1].piece_map)
        opposite_rotation = dict(opposite.automorphisms[1].piece_map)
        self.assertEqual(same_rotation["I1"], "I2")
        self.assertEqual(opposite_rotation["I1"], "I3")
        self.assertNotEqual(same.to_dict(), opposite.to_dict())

    def test_registry_accepts_parameterized_three_ring_names(self) -> None:
        for map_name in THREE_RING_CASES:
            with self.subTest(map_name=map_name):
                self.assertEqual(canonical_map_name(map_name), map_name)


class ThreeRingCatalogTests(unittest.TestCase):
    def test_catalog_discovers_all_three_ring_cases(self) -> None:
        catalog = CaseCatalog.load(ROOT)
        for case_id in THREE_RING_CASES:
            with self.subTest(case_id=case_id):
                case = catalog.get(case_id)
                self.assertEqual(case.map_name, case_id)
                self.assertEqual(
                    case.source,
                    ROOT / "config" / "case_families" / "cyclic-three-ring.json",
                )
                self.assertEqual(
                    case.output_directory, Path("output") / "cases" / case_id
                )

    def test_three_ring_search_materializes_rotation_1_equivariance(self) -> None:
        catalog = CaseCatalog.load(ROOT)
        case = catalog.get("three-ring-offset-opposite-3")
        with tempfile.TemporaryDirectory() as directory:
            materialized = materialize_task(
                ROOT,
                case,
                PipelineTask(case.case_id, "search"),
                Path(directory),
                task_index=0,
            )
            config = json.loads(materialized.config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["maps"], ["three-ring-offset-opposite-3"])
        equivariance = config["enumeration"]["cyclic_equivariance"]
        self.assertTrue(equivariance["enabled"])
        self.assertTrue(equivariance["enforce_weak_orders"])
        self.assertEqual(equivariance["automorphism"], "rotation_1")


if __name__ == "__main__":
    unittest.main()
