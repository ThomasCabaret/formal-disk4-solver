from __future__ import annotations

import unittest
from dataclasses import replace

from formal_disk4.config import load_config
from formal_disk4.pipeline.checkpoint import search_fingerprint
from formal_disk4.targeted_three_ring_18 import (
    SIZE,
    TILE_COUNT,
    build_target_candidate,
    build_target_map,
    expected_edges,
    imposed_rotation,
    raw_assignment_count,
)


class TargetedThreeRing18Tests(unittest.TestCase):
    def test_exact_declared_contacts(self) -> None:
        candidate = build_target_candidate()
        self.assertEqual(candidate.tile_count, 18)
        self.assertEqual(len(candidate.edges), 36)
        self.assertEqual(candidate.edges, expected_edges())
        self.assertEqual(
            set(candidate.edges),
            {
                edge
                for index in range(SIZE)
                for edge in (
                    (-1, index),
                    (index, SIZE + index),
                    (SIZE + index, 2 * SIZE + index),
                    (index, 2 * SIZE + (index + 1) % SIZE),
                    (SIZE + index, 2 * SIZE + (index + 1) % SIZE),
                    tuple(
                        sorted(
                            (
                                2 * SIZE + index,
                                2 * SIZE + (index + 1) % SIZE,
                            )
                        )
                    ),
                )
            },
        )

    def test_imposed_index_shift_is_order_six(self) -> None:
        permutation = imposed_rotation()
        current = tuple(range(TILE_COUNT))
        for _step in range(SIZE):
            current = tuple(permutation[index] for index in current)
        self.assertEqual(current, tuple(range(TILE_COUNT)))
        self.assertNotEqual(permutation, tuple(range(TILE_COUNT)))
        self.assertEqual(build_target_candidate().symmetry_order, SIZE)

    def test_dynamic_map_and_equivariant_assignment_domain(self) -> None:
        dynamic = build_target_map()
        dynamic.planar_map.validate()
        self.assertEqual(dynamic.imposed_equivariance_mode, "pointwise")
        self.assertEqual(raw_assignment_count(dynamic), 60)

    def test_dynamic_map_structure_is_part_of_checkpoint_fingerprint(self) -> None:
        dynamic = build_target_map().planar_map
        config = load_config(None)
        config["maps"] = [dynamic.name]
        first = search_fingerprint(config, planar_maps=(dynamic,))
        changed = replace(dynamic, reference_piece=dynamic.pieces[1].name)
        second = search_fingerprint(config, planar_maps=(changed,))
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
