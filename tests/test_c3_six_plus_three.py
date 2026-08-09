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

CASE_IDS = (
    "c3-6plus3-s3",
    "c3-6plus3-s3b",
    "c3-6plus3-t2",
    "c3-6plus3-t3",
    "c3-6plus3-t2b",
    "c3-6plus3-t3b",
)


def _pairs(*values: tuple[str, str]) -> set[frozenset[str]]:
    return {frozenset(value) for value in values}


OUTER_CYCLE = _pairs(
    ("O1", "O2"),
    ("O2", "O3"),
    ("O3", "O4"),
    ("O4", "O5"),
    ("O5", "O6"),
    ("O6", "O1"),
)
BROKEN_GAPS = _pairs(("O6", "O1"), ("O2", "O3"), ("O4", "O5"))
INNER_TRIANGLE = _pairs(("I1", "I2"), ("I2", "I3"), ("I3", "I1"))
S3_INNER_OUTER = _pairs(
    ("I1", "O6"),
    ("I1", "O1"),
    ("I1", "O2"),
    ("I2", "O2"),
    ("I2", "O3"),
    ("I2", "O4"),
    ("I3", "O4"),
    ("I3", "O5"),
    ("I3", "O6"),
)
T2_INNER_OUTER = _pairs(
    ("I1", "O6"),
    ("I1", "O1"),
    ("I2", "O2"),
    ("I2", "O3"),
    ("I3", "O4"),
    ("I3", "O5"),
)

EXPECTED_CONTACTS = {
    "c3-6plus3-s3": S3_INNER_OUTER | OUTER_CYCLE,
    "c3-6plus3-s3b": S3_INNER_OUTER | (OUTER_CYCLE - BROKEN_GAPS),
    "c3-6plus3-t2": INNER_TRIANGLE | T2_INNER_OUTER | OUTER_CYCLE,
    "c3-6plus3-t3": INNER_TRIANGLE | S3_INNER_OUTER | OUTER_CYCLE,
    "c3-6plus3-t2b": (
        INNER_TRIANGLE | T2_INNER_OUTER | (OUTER_CYCLE - BROKEN_GAPS)
    ),
    "c3-6plus3-t3b": (
        INNER_TRIANGLE | S3_INNER_OUTER | (OUTER_CYCLE - BROKEN_GAPS)
    ),
}


class C3SixPlusThreeMapTests(unittest.TestCase):
    def test_maps_match_the_six_schematic_contact_graphs(self) -> None:
        expected_pieces = {
            *(f"O{index}" for index in range(1, 7)),
            *(f"I{index}" for index in range(1, 4)),
        }
        for case_id in CASE_IDS:
            with self.subTest(case_id=case_id):
                planar_map = build_map(case_id)
                planar_map.validate()
                contacts = {
                    frozenset((interface.left_piece, interface.right_piece))
                    for interface in planar_map.internal_interfaces()
                }
                self.assertEqual({piece.name for piece in planar_map.pieces}, expected_pieces)
                self.assertEqual(contacts, EXPECTED_CONTACTS[case_id])
                self.assertEqual(len(planar_map.outer_interfaces()), 6)
                self.assertEqual(
                    len(planar_map.vertices)
                    - len(planar_map.interfaces)
                    + len(planar_map.pieces),
                    1,
                )
                self.assertEqual(canonical_map_name(case_id), case_id)

    def test_boundary_point_variants_mark_exactly_the_three_inner_tiles(self) -> None:
        for case_id in CASE_IDS:
            with self.subTest(case_id=case_id):
                pieces = build_map(case_id).piece_map()
                inner_contacts = {
                    pieces[f"I{index}"].outer_boundary_contact
                    for index in range(1, 4)
                }
                self.assertEqual(
                    inner_contacts,
                    {"point"} if case_id.endswith("b") else {"none"},
                )
                self.assertTrue(
                    all(
                        pieces[f"O{index}"].outer_boundary_contact == "arc"
                        for index in range(1, 7)
                    )
                )

    def test_all_six_maps_impose_the_source_c3_rotation(self) -> None:
        expected_piece_rotation = {
            "I1": "I2",
            "I2": "I3",
            "I3": "I1",
            "O1": "O3",
            "O3": "O5",
            "O5": "O1",
            "O2": "O4",
            "O4": "O6",
            "O6": "O2",
        }
        for case_id in CASE_IDS:
            with self.subTest(case_id=case_id):
                planar_map = build_map(case_id)
                self.assertEqual(len(planar_map.automorphisms), 3)
                rotation = next(
                    item
                    for item in planar_map.automorphisms
                    if item.name == "rotation_1"
                )
                self.assertEqual(dict(rotation.piece_map), expected_piece_rotation)
                assignments = AssignmentEnumerator(
                    planar_map,
                    symmetry_mode="incremental",
                    required_equivariance="rotation_1",
                )
                self.assertEqual(len(assignments.mapping_symmetry.group), 3)
                first = next(assignments.enumerate())
                self.assertEqual(first.required_equivariance, "rotation_1")


class C3SixPlusThreeCatalogTests(unittest.TestCase):
    def test_catalog_exposes_six_isolated_c3_search_cases(self) -> None:
        catalog = CaseCatalog.load(ROOT)
        source = ROOT / "config" / "case_families" / "c3-six-plus-three.json"
        with tempfile.TemporaryDirectory() as directory:
            generated = Path(directory)
            for task_index, case_id in enumerate(CASE_IDS):
                with self.subTest(case_id=case_id):
                    case = catalog.get(case_id)
                    self.assertEqual(case.map_name, case_id)
                    self.assertEqual(case.source, source)
                    self.assertEqual(
                        case.output_directory,
                        Path("output") / "cases" / case_id,
                    )
                    materialized = materialize_task(
                        ROOT,
                        case,
                        PipelineTask(case_id, "search"),
                        generated,
                        task_index,
                    )
                    config = json.loads(
                        materialized.config_path.read_text(encoding="utf-8")
                    )
                    self.assertEqual(config["maps"], [case_id])
                    equivariance = config["enumeration"]["cyclic_equivariance"]
                    self.assertTrue(equivariance["enabled"])
                    self.assertTrue(equivariance["enforce_weak_orders"])
                    self.assertEqual(equivariance["automorphism"], "rotation_1")


if __name__ == "__main__":
    unittest.main()
