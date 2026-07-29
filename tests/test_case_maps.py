from __future__ import annotations

import json
import unittest
from pathlib import Path

from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.enumeration.exterior_arc_repetition import (
    build_exterior_arc_repetition_constraint,
)
from formal_disk4.maps.registry import available_maps, build_map, canonical_map_name


class CaseMapTests(unittest.TestCase):
    def test_canonical_case_names_and_legacy_aliases(self) -> None:
        self.assertEqual(
            available_maps(),
            (
                "c3",
                "c4",
                "double-cycle-6",
                "k4",
                "k4-minus-point",
                "k4-minus-arc",
            ),
        )
        self.assertEqual(canonical_map_name("k3-pizza"), "c3")
        self.assertEqual(canonical_map_name("k4-pizza"), "c4")
        self.assertEqual(canonical_map_name("k4-central"), "k4")

    def test_point_contact_case_topology(self) -> None:
        planar_map = build_map("k4-minus-point")
        piece = planar_map.piece_map()["T0"]
        self.assertEqual(piece.outer_boundary_contact, "point")
        self.assertEqual(
            {interface.name for interface in planar_map.internal_interfaces()},
            {"T0-T1", "T0-T2", "T0-T3", "T1-T2", "T2-T3"},
        )
        self.assertEqual(
            {interface.views[0].piece for interface in planar_map.outer_interfaces()},
            {"T1", "T2", "T3"},
        )
        self.assertEqual(planar_map.vertex_map()["A"].incident_pieces, ("T0", "T1", "T3"))

    def test_arc_contact_case_topology(self) -> None:
        planar_map = build_map("k4-minus-arc")
        self.assertEqual(planar_map.piece_map()["T0"].outer_boundary_contact, "arc")
        self.assertEqual(
            {interface.name for interface in planar_map.internal_interfaces()},
            {"T0-T1", "T0-T2", "T0-T3", "T1-T2", "T2-T3"},
        )
        self.assertEqual(
            tuple(interface.views[0].piece for interface in planar_map.outer_interfaces()),
            ("T0", "T1", "T2", "T3"),
        )

    def test_peripheral_repetition_filter_applies_to_all_three_stein_cases(self) -> None:
        for name in ("k4", "k4-minus-point", "k4-minus-arc"):
            planar_map = build_map(name)
            enumerator = AssignmentEnumerator(planar_map, symmetry_mode="incremental")
            assignment = next(iter(enumerator.enumerate()))
            constraint = build_exterior_arc_repetition_constraint(
                planar_map,
                assignment.piece_names,
                assignment.sequences,
                enumerator.occurrence_index,
                enabled=True,
            )
            self.assertTrue(constraint.applicable, name)
            self.assertEqual(len(constraint.arcs), 3, name)

    def test_each_case_has_isolated_checkpoint_configuration(self) -> None:
        root = Path(__file__).resolve().parents[1] / "config" / "cases"
        output_directories = set()
        for name in available_maps():
            case_root = root / name
            manifest = json.loads((case_root / "case.json").read_text(encoding="utf-8"))
            search = json.loads((case_root / manifest["configs"]["search"]).read_text(encoding="utf-8"))
            self.assertEqual(search["maps"], [name])
            output = search["output"]["directory"]
            self.assertNotIn(output, output_directories)
            output_directories.add(output)
            self.assertEqual(search["checkpoint"]["file"], "checkpoint.sqlite3")


if __name__ == "__main__":
    unittest.main()
