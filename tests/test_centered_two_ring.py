from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from formal_disk4.constraints.angle_lp import AngleFeasibilityOracle
from formal_disk4.constraints.length_lp import LengthFeasibilityOracle
from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.enumeration.weak_orders import WeakOrderEnumerator
from formal_disk4.maps.registry import build_map, canonical_map_name
from formal_disk4.orchestration.catalog import CaseCatalog
from formal_disk4.orchestration.pipeline import PipelineTask, materialize_task


ROOT = Path(__file__).resolve().parents[1]
FAMILIES = {
    "centered-double-cycle": "double-cycle",
    "centered-double-cycle-offset": "double-cycle-offset",
    "centered-inner-cycle-boundary-points": "inner-cycle-boundary-points",
    "centered-outer-cycle-center-points": "outer-cycle-center-points",
}


class CenteredTwoRingMapTests(unittest.TestCase):
    @staticmethod
    def _contacts(planar_map) -> set[frozenset[str]]:
        return {
            frozenset((interface.left_piece, interface.right_piece))
            for interface in planar_map.internal_interfaces()
        }

    def test_center_truncation_preserves_contacts_and_adds_expected_spokes(self) -> None:
        for centered_prefix, base_prefix in FAMILIES.items():
            for size in range(3, 7):
                with self.subTest(family=centered_prefix, size=size):
                    base = build_map(f"{base_prefix}-{size}")
                    centered = build_map(f"{centered_prefix}-{size}")
                    centered.validate()

                    self.assertEqual(len(centered.pieces), len(base.pieces) + 1)
                    self.assertNotIn("Z", centered.vertex_map())
                    self.assertTrue(
                        centered.hypotheses.center_strictly_inside_one_tile
                    )
                    self.assertEqual(
                        centered.piece_map()["C"].outer_boundary_contact, "none"
                    )

                    base_contacts = self._contacts(base)
                    centered_contacts = self._contacts(centered)
                    self.assertTrue(base_contacts <= centered_contacts)
                    central_neighbors = {
                        next(iter(contact - {"C"}))
                        for contact in centered_contacts
                        if "C" in contact
                    }
                    self.assertEqual(
                        central_neighbors,
                        set(base.vertex_map()["Z"].incident_pieces),
                    )

                    vertices = len(centered.vertices)
                    edges = len(centered.interfaces)
                    faces = len(centered.pieces) + 1
                    self.assertEqual(vertices - edges + faces, 2)

    def test_rotation_one_is_certified_and_fixes_center_setwise(self) -> None:
        for centered_prefix in FAMILIES:
            for size in range(3, 7):
                with self.subTest(family=centered_prefix, size=size):
                    planar_map = build_map(f"{centered_prefix}-{size}")
                    assignments = AssignmentEnumerator(
                        planar_map, symmetry_mode="off"
                    )
                    rotation = assignments.transform_for_automorphism("rotation_1")
                    piece_names = tuple(piece.name for piece in planar_map.pieces)
                    piece_map = {
                        piece_names[index]: piece_names[target]
                        for index, target in enumerate(rotation.piece_map)
                    }
                    self.assertEqual(piece_map["C"], "C")
                    for index in range(size):
                        self.assertEqual(
                            piece_map[f"E{index + 1}"],
                            f"E{(index + 1) % size + 1}",
                        )
                        self.assertEqual(
                            piece_map[f"I{index + 1}"],
                            f"I{(index + 1) % size + 1}",
                        )

    def test_rotation_one_builds_a_full_cyclic_weak_order(self) -> None:
        for centered_prefix in FAMILIES:
            for size in range(3, 7):
                with self.subTest(family=centered_prefix, size=size):
                    planar_map = build_map(f"{centered_prefix}-{size}")
                    assignments = AssignmentEnumerator(
                        planar_map, symmetry_mode="off"
                    )
                    assignment = assignments.assignment_at(0)
                    transform = assignments.transform_for_automorphism("rotation_1")
                    weak_orders = WeakOrderEnumerator(
                        planar_map,
                        assignment,
                        assignments.occurrence_names,
                        LengthFeasibilityOracle(),
                        AngleFeasibilityOracle(),
                        symmetry_mode="off",
                        enable_length_filter=False,
                        enable_angle_filter=False,
                        enable_exterior_arc_repetition_filter=False,
                        track_exact_leaf_mass=False,
                        required_cyclic_shift_transform=transform,
                    )
                    placement = next(weak_orders.enumerate())
                    self.assertEqual(len(placement.blocks) % size, 0)
                    domain_length = len(placement.blocks) // size
                    for sector in range(1, size):
                        for index in range(domain_length):
                            previous = placement.blocks[
                                (sector - 1) * domain_length + index
                            ]
                            mapped = tuple(
                                sorted(
                                    transform.map_occurrence_id(item)
                                    for item in previous
                                )
                            )
                            self.assertEqual(
                                mapped,
                                placement.blocks[sector * domain_length + index],
                            )

    def test_dynamic_registry_names(self) -> None:
        for prefix in FAMILIES:
            name = f"{prefix}-4"
            self.assertEqual(canonical_map_name(name), name)
            self.assertEqual(build_map(name).name, name)


class CenteredTwoRingCatalogTests(unittest.TestCase):
    def test_catalog_contains_sixteen_isolated_rotation_one_cases(self) -> None:
        catalog = CaseCatalog.load(ROOT)
        for prefix in FAMILIES:
            for size in range(3, 7):
                case_id = f"{prefix}-{size}"
                with self.subTest(case=case_id), tempfile.TemporaryDirectory() as directory:
                    case = catalog.get(case_id)
                    self.assertEqual(case.map_name, case_id)
                    materialized = materialize_task(
                        ROOT,
                        case,
                        PipelineTask(case_id, "search"),
                        Path(directory),
                        task_index=0,
                    )
                    config = json.loads(
                        materialized.config_path.read_text(encoding="utf-8")
                    )
                    self.assertFalse(
                        config["enumeration"]["cyclic_equivariance"]["enabled"]
                    )
                    self.assertFalse(
                        config["enumeration"]["track_exact_domain_size"]
                    )
                    cyclic_shift = config["enumeration"][
                        "cyclic_shift_equivariance"
                    ]
                    self.assertTrue(cyclic_shift["enabled"])
                    self.assertEqual(cyclic_shift["automorphism"], "rotation_1")
                    self.assertEqual(
                        config["output"]["directory"],
                        f"output/cases/{case_id}",
                    )


if __name__ == "__main__":
    unittest.main()
