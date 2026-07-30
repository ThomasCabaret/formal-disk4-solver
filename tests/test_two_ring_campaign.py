from __future__ import annotations

import json
import unittest
from pathlib import Path

from formal_disk4.campaigns.cyclic import (
    FAMILY_MAP_PREFIXES,
    load_suite,
    make_case,
    suite_forwarded_arguments,
)
from formal_disk4.maps.registry import build_map, canonical_map_name
from formal_disk4.maps.two_ring_families import wide_family_obstruction


class TwoRingFamilyMapTests(unittest.TestCase):
    def _contacts(self, map_name: str) -> set[frozenset[str]]:
        planar_map = build_map(map_name)
        return {
            frozenset((interface.left_piece, interface.right_piece))
            for interface in planar_map.internal_interfaces()
        }

    def test_offset_family_has_both_cross_offsets(self) -> None:
        for size in (3, 4, 5):
            planar_map = build_map(f"double-cycle-offset-{size}")
            planar_map.validate()
            contacts = self._contacts(planar_map.name)
            for index in range(size):
                current = index + 1
                next_index = (index + 1) % size + 1
                self.assertIn(frozenset((f"E{current}", f"E{next_index}")), contacts)
                self.assertIn(frozenset((f"I{current}", f"I{next_index}")), contacts)
                self.assertIn(frozenset((f"E{current}", f"I{current}")), contacts)
                self.assertIn(frozenset((f"E{current}", f"I{next_index}")), contacts)
            self.assertEqual(len(planar_map.automorphisms), size)
            self.assertEqual(planar_map.automorphisms[1].name, "rotation_1")

    def test_boundary_point_family_has_no_outer_cycle_edges(self) -> None:
        for size in (3, 4, 5):
            planar_map = build_map(f"inner-cycle-boundary-points-{size}")
            planar_map.validate()
            contacts = self._contacts(planar_map.name)
            self.assertFalse(
                any(
                    all(piece.startswith("E") for piece in contact)
                    for contact in contacts
                )
            )
            self.assertTrue(
                all(
                    planar_map.piece_map()[f"I{index + 1}"].outer_boundary_contact
                    == "point"
                    for index in range(size)
                )
            )

    def test_center_point_family_has_no_inner_cycle_edges(self) -> None:
        for size in (3, 4, 5):
            planar_map = build_map(f"outer-cycle-center-points-{size}")
            planar_map.validate()
            contacts = self._contacts(planar_map.name)
            self.assertFalse(
                any(
                    all(piece.startswith("I") for piece in contact)
                    for contact in contacts
                )
            )
            self.assertEqual(
                set(planar_map.vertex_map()["Z"].incident_pieces),
                {f"E{index + 1}" for index in range(size)}
                | {f"I{index + 1}" for index in range(size)},
            )

    def test_dynamic_registry_names(self) -> None:
        names = (
            "double-cycle-offset-4",
            "inner-cycle-boundary-points-4",
            "outer-cycle-center-points-4",
        )
        for name in names:
            self.assertEqual(canonical_map_name(name), name)
            self.assertEqual(build_map(name).name, name)

    def test_wide_family_is_recorded_as_structurally_impossible(self) -> None:
        for size in (3, 4, 5):
            result = wide_family_obstruction(size)
            self.assertEqual(result["requested_edges"], 5 * size)
            self.assertEqual(result["annulus_maximum_edges"], 4 * size)
            self.assertEqual(result["excess_edges"], size)
            self.assertEqual(result["status"], "structurally_impossible")


class CyclicCampaignTests(unittest.TestCase):
    def test_family_names_cover_dc1_through_dc5(self) -> None:
        self.assertEqual(
            tuple(FAMILY_MAP_PREFIXES),
            ("parallel", "offset", "wide", "boundary-points", "center-points"),
        )
        self.assertEqual(make_case("dc1", 3).case_id, "double-cycle-3")
        self.assertEqual(make_case("dc5", 5).case_id, "outer-cycle-center-points-5")

    def test_small_suite_contains_fifteen_independent_cases(self) -> None:
        root = Path(__file__).resolve().parents[1]
        previous = Path.cwd()
        try:
            # load_suite resolves relative to the supplied project root.
            suite_id, cases = load_suite(root, "cyclic-small")
        finally:
            _ = previous
        self.assertEqual(suite_id, "cyclic-small")
        self.assertEqual(len(cases), 15)
        self.assertEqual(len({case.case_id for case in cases}), 15)
        self.assertEqual({case.size for case in cases}, {3, 4, 5})
        self.assertEqual({case.family for case in cases}, set(FAMILY_MAP_PREFIXES))

    def test_restart_all_is_only_used_for_fresh_campaigns(self) -> None:
        resumed, restarted = suite_forwarded_arguments(
            "search", ["--continue-after-profile"]
        )
        self.assertFalse(restarted)
        self.assertNotIn("--restart", resumed)

        fresh, restarted = suite_forwarded_arguments(
            "search", ["--restart-all", "--continue-after-profile"]
        )
        self.assertTrue(restarted)
        self.assertIn("--restart", fresh)
        self.assertNotIn("--restart-all", fresh)

        with self.assertRaises(ValueError):
            suite_forwarded_arguments("search", ["--restart"])

    def test_suite_files_are_external_case_lists(self) -> None:
        root = Path(__file__).resolve().parents[1] / "config" / "suites"
        for size in (3, 4, 5):
            data = json.loads((root / f"cyclic-n{size}.json").read_text(encoding="utf-8"))
            self.assertEqual(len(data["cases"]), 5)
            self.assertEqual({entry["size"] for entry in data["cases"]}, {size})
        small = json.loads((root / "cyclic-small.json").read_text(encoding="utf-8"))
        self.assertEqual(len(small["cases"]), 15)


if __name__ == "__main__":
    unittest.main()
