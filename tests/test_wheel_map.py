from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from formal_disk4.config import load_config
from formal_disk4.constraints.angle_lp import AngleFeasibilityOracle
from formal_disk4.constraints.length_lp import LengthFeasibilityOracle
from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.enumeration.weak_orders import WeakOrderEnumerator
from formal_disk4.maps.registry import build_map
from formal_disk4.pipeline.runner import SolverRunner


ROOT = Path(__file__).resolve().parents[1]


class WheelFourMapTests(unittest.TestCase):
    def test_wheel_invariants_and_half_turn_are_certified(self) -> None:
        planar_map = build_map("wheel-4")
        planar_map.validate()
        self.assertEqual(len(planar_map.pieces), 5)
        self.assertEqual(len(planar_map.vertices), 8)
        self.assertEqual(len(planar_map.internal_interfaces()), 8)
        self.assertEqual(len(planar_map.outer_interfaces()), 4)
        self.assertEqual(len(planar_map.occurrences()), 20)
        self.assertEqual(len(planar_map.automorphisms), 8)
        self.assertIn("rotation_2", {item.name for item in planar_map.automorphisms})

        assignments = AssignmentEnumerator(
            planar_map,
            symmetry_mode="incremental",
        )
        required = assignments.transform_for_automorphism("rotation_2")
        piece_names = tuple(piece.name for piece in planar_map.pieces)
        piece_map = {
            piece_names[index]: piece_names[target]
            for index, target in enumerate(required.piece_map)
        }
        self.assertEqual(piece_map["C"], "C")
        self.assertEqual(piece_map["P0"], "P2")
        self.assertEqual(piece_map["P1"], "P3")

    def test_cyclic_shift_enumerator_emits_a_certified_half_turn_mapping(self) -> None:
        planar_map = build_map("wheel-4")
        assignments = AssignmentEnumerator(planar_map, symmetry_mode="off")
        assignment = assignments.assignment_at(0)
        transform = assignments.transform_for_automorphism("rotation_2")
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
        block_count = len(placement.blocks)
        self.assertEqual(block_count % 2, 0)
        half = block_count // 2
        for index in range(half):
            mapped = tuple(
                sorted(transform.map_occurrence_id(item) for item in placement.blocks[index])
            )
            self.assertEqual(mapped, placement.blocks[index + half])

    def test_intrinsic_quotient_preserves_the_half_turn_domain(self) -> None:
        planar_map = build_map("wheel-4")
        assignments = AssignmentEnumerator(planar_map, symmetry_mode="incremental")
        transform = assignments.transform_for_automorphism("rotation_2")
        required_action = assignments.mapping_symmetry.action_by_name("rotation_2")
        self.assertTrue(
            all(
                action.commutes_with(required_action)
                for action in assignments.mapping_symmetry.quotient_group
            )
        )

        assignment = assignments.assignment_at(0)
        weak_orders = WeakOrderEnumerator(
            planar_map,
            assignment,
            assignments.occurrence_names,
            LengthFeasibilityOracle(),
            AngleFeasibilityOracle(),
            symmetry_mode="incremental",
            enable_length_filter=False,
            enable_angle_filter=False,
            enable_exterior_arc_repetition_filter=False,
            track_exact_leaf_mass=False,
            required_cyclic_shift_transform=transform,
            mapping_symmetry=assignments.mapping_symmetry,
        )
        placement = next(weak_orders.enumerate())
        for action in assignments.mapping_symmetry.mapping_actions:
            image = assignments.mapping_symmetry.normalize_blocks(
                placement.blocks, action
            )
            half = len(image) // 2
            self.assertEqual(len(image) % 2, 0)
            for index in range(half):
                mapped = tuple(
                    sorted(transform.map_occurrence_id(item) for item in image[index])
                )
                self.assertEqual(mapped, image[index + half])

    def test_euler_characteristic_is_a_disk(self) -> None:
        planar_map = build_map("wheel-4")
        vertices = len(planar_map.vertices)
        edges = len(planar_map.interfaces)
        faces_including_exterior = len(planar_map.pieces) + 1
        self.assertEqual(vertices - edges + faces_including_exterior, 2)

    def test_exact_progress_counts_the_cyclic_shift_domain(self) -> None:
        config = load_config(ROOT / "config" / "cycle_campaign" / "search.json")
        config["maps"] = ["wheel-4"]
        config["enumeration"]["track_exact_domain_size"] = True
        config["enumeration"]["cyclic_equivariance"]["enabled"] = False
        config["enumeration"]["cyclic_shift_equivariance"] = {
            "enabled": True,
            "automorphism": "rotation_2",
        }
        with tempfile.TemporaryDirectory() as directory:
            config["output"]["directory"] = str(Path(directory) / "output")
            config["checkpoint"]["enabled"] = False
            runner = SolverRunner(config)
            try:
                contexts = runner._build_map_contexts()
                runner._search_state["completed_leaf_mass"] = (
                    runner._total_leaf_mass // 2
                )
                progress_line = runner._progress_message()
            finally:
                runner.checkpoint_store.close()

        self.assertEqual(contexts[0].assignment_count, 4096)
        self.assertEqual(len(contexts[0].assignment_masses), 4096)
        self.assertEqual(runner._total_leaf_mass, 233_178_112)
        self.assertIn("overall~ 50.0%", progress_line)


if __name__ == "__main__":
    unittest.main()
