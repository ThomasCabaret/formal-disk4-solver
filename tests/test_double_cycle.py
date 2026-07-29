from __future__ import annotations

import json
import unittest
from pathlib import Path

from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.maps.double_cycle import build_double_cycle_map
from formal_disk4.maps.registry import build_map, canonical_map_name


class DoubleCycleMapTests(unittest.TestCase):
    def test_six_ring_topology(self) -> None:
        planar_map = build_double_cycle_map(6)
        self.assertEqual(planar_map.name, "double-cycle-6")
        self.assertEqual(len(planar_map.pieces), 12)
        self.assertEqual(len(planar_map.internal_interfaces()), 18)
        self.assertEqual(len(planar_map.outer_interfaces()), 6)
        self.assertEqual(len(planar_map.automorphisms), 12)
        self.assertEqual(len(planar_map.occurrences()), 42)
        self.assertFalse(planar_map.hypotheses.center_strictly_inside_one_tile)

        contacts = {
            frozenset((interface.left_piece, interface.right_piece))
            for interface in planar_map.internal_interfaces()
        }
        for index in range(6):
            next_index = (index + 1) % 6
            self.assertIn(
                frozenset((f"E{index + 1}", f"E{next_index + 1}")), contacts
            )
            self.assertIn(
                frozenset((f"I{index + 1}", f"I{next_index + 1}")), contacts
            )
            self.assertIn(frozenset((f"E{index + 1}", f"I{index + 1}")), contacts)

    def test_family_builder_is_parameterized(self) -> None:
        self.assertEqual(build_double_cycle_map(3).name, "double-cycle-3")
        self.assertEqual(build_map("double-cycle-7").name, "double-cycle-7")
        self.assertEqual(canonical_map_name("dc6"), "double-cycle-6")
        with self.assertRaises(ValueError):
            build_double_cycle_map(2)

    def test_large_assignment_domain_has_random_access(self) -> None:
        planar_map = build_map("double-cycle-6")
        enumerator = AssignmentEnumerator(planar_map, symmetry_mode="off")
        self.assertEqual(enumerator.raw_assignment_count(), 6_115_295_232)
        first = enumerator.assignment_at(0)
        second = enumerator.assignment_at(1)
        self.assertEqual(first.assignment_id, 0)
        self.assertEqual(second.assignment_id, 1)
        self.assertTrue(all(sign == 1 for sign in first.orientation_signs))
        self.assertTrue(all(offset == 0 for offset in first.cyclic_offsets))
        self.assertNotEqual(first.sequences, second.sequences)

    def test_case_manifest_uses_independent_output(self) -> None:
        root = Path(__file__).resolve().parents[1]
        case_root = root / "config" / "cases" / "double-cycle-6"
        manifest = json.loads((case_root / "case.json").read_text(encoding="utf-8"))
        search = json.loads((case_root / "search.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["map"], "double-cycle-6")
        self.assertEqual(search["maps"], ["double-cycle-6"])
        self.assertEqual(search["enumeration"]["symmetry_mode"], "off")
        self.assertFalse(search["enumeration"]["track_exact_domain_size"])
        self.assertEqual(
            search["output"]["directory"], "output/cases/double-cycle-6"
        )
        self.assertEqual(search["checkpoint"]["file"], "checkpoint.sqlite3")


if __name__ == "__main__":
    unittest.main()
