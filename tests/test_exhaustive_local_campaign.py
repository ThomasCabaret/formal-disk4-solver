from __future__ import annotations

import unittest
from pathlib import Path

import networkx as nx

from formal_disk4.graph_lab.exhaustive_local import (
    NATIVE_MAXIMUM_TILES,
    _formal_config,
    _print_result_table,
    atlas_candidates,
    center_ring_candidates,
    classify_completed_formal_search,
)
from formal_disk4.graph_lab.space import OUTSIDE, validate_dual_graph


ROOT = Path(__file__).resolve().parents[1]


class ExhaustiveLocalCampaignTests(unittest.TestCase):
    def test_native_catalog_is_rooted_isomorph_free_and_admissible(self) -> None:
        candidates = atlas_candidates(3, NATIVE_MAXIMUM_TILES)
        self.assertTrue(candidates)
        self.assertEqual(len({item.graph_id for item in candidates}), len(candidates))
        self.assertEqual(
            tuple(item.tile_count for item in candidates),
            tuple(sorted(item.tile_count for item in candidates)),
        )
        counts = {
            tile_count: sum(
                candidate.tile_count == tile_count for candidate in candidates
            )
            for tile_count in range(3, NATIVE_MAXIMUM_TILES + 1)
        }
        self.assertEqual(counts, {3: 1, 4: 4, 5: 17, 6: 155})
        for candidate in candidates:
            self.assertIsNone(candidate.imposed_permutation)
            graph = candidate.graph()
            validate_dual_graph(graph, maximum_tiles=candidate.tile_count)
            self.assertTrue(nx.is_connected(graph))
            self.assertGreaterEqual(nx.node_connectivity(graph), 3)
            self.assertTrue(all(graph.degree(tile) >= 3 for tile in graph if tile != OUTSIDE))

    def test_native_catalog_refuses_an_unproved_larger_range(self) -> None:
        with self.assertRaisesRegex(ValueError, "exhaustive only through 6 tiles"):
            atlas_candidates(3, NATIVE_MAXIMUM_TILES + 1)

    def test_center_ring_reference_family_has_exact_declared_contacts(self) -> None:
        candidates = center_ring_candidates(4, 10)
        self.assertEqual(tuple(item.tile_count for item in candidates), tuple(range(4, 11)))
        for candidate in candidates:
            graph = candidate.graph()
            ring = tuple(range(1, candidate.tile_count))
            self.assertIsNone(candidate.imposed_permutation)
            self.assertEqual(set(graph.neighbors(0)), set(ring))
            self.assertEqual(set(graph.neighbors(OUTSIDE)), set(ring))
            for index, tile in enumerate(ring):
                self.assertEqual(
                    set(graph.neighbors(tile)),
                    {
                        OUTSIDE,
                        0,
                        ring[index - 1],
                        ring[(index + 1) % len(ring)],
                    },
                )
            self.assertTrue(nx.is_planar(graph))
            self.assertGreaterEqual(nx.node_connectivity(graph), 3)

    def test_formal_configuration_keeps_word_guardrails_and_no_symmetry(self) -> None:
        config = _formal_config(
            ROOT / "config" / "local_graph_campaign" / "formal.json",
            planar_map_name="dynamic-test",
            output=ROOT / "output" / "test-only",
            word_seconds=None,
            graph_seconds=None,
        )
        self.assertTrue(config["enumeration"]["allow_reflections"])
        self.assertEqual(config["enumeration"]["symmetry_mode"], "incremental")
        self.assertTrue(config["enumeration"]["track_exact_domain_size"])
        self.assertFalse(config["enumeration"]["cyclic_equivariance"]["enabled"])
        for name in (
            "max_assignments",
            "max_nodes",
            "max_placements",
            "max_profiles",
            "time_limit_seconds",
        ):
            self.assertIsNone(config["limits"][name])
        self.assertIsNone(config["solver"]["max_seconds_per_word_case"])
        self.assertEqual(config["solver"]["max_terminal_contour_segments"], 40)
        self.assertEqual(config["solver"]["max_graph_nodes_per_placement"], 50000)
        linear = config["filters"]["preword_pruning"]["linear_invariants"]
        self.assertFalse(linear["enable_radius_measures"])
        self.assertFalse(linear["enable_smooth_turns"])
        survey = _formal_config(
            ROOT / "config" / "local_graph_campaign" / "formal.json",
            planar_map_name="dynamic-test",
            output=ROOT / "output" / "test-only",
            word_seconds=2.5,
            graph_seconds=30.0,
        )
        self.assertEqual(survey["solver"]["max_seconds_per_word_case"], 2.5)
        self.assertEqual(survey["limits"]["time_limit_seconds"], 30.0)
        scalable = _formal_config(
            ROOT / "config" / "local_graph_campaign" / "formal.json",
            planar_map_name="dynamic-test",
            output=ROOT / "output" / "test-only",
            track_exact_domain_size=False,
        )
        self.assertFalse(scalable["enumeration"]["track_exact_domain_size"])

    def test_negative_certificate_requires_clean_completion(self) -> None:
        clean = {
            "statistics": {
                "stop_reason": "completed",
                "counters": {"profiles_emitted": 0},
            }
        }
        self.assertEqual(
            classify_completed_formal_search(clean, formal_profile_count=0),
            ("formal_unsat_certified", {}),
        )
        deferred = {
            "statistics": {
                "stop_reason": "completed",
                "counters": {"deferred_word_cases": 1},
            }
        }
        status, blockers = classify_completed_formal_search(
            deferred, formal_profile_count=0
        )
        self.assertEqual(status, "formal_exhausted_with_proof_gaps")
        self.assertEqual(blockers, {"deferred_word_cases": 1})
        symbolic = {
            "statistics": {
                "stop_reason": "completed",
                "counters": {"word_family_power": 3},
            }
        }
        status, blockers = classify_completed_formal_search(
            symbolic, formal_profile_count=0
        )
        self.assertEqual(status, "formal_exhausted_with_proof_gaps")
        self.assertEqual(blockers, {"word_family_power": 3})
        stopped = {
            "statistics": {"stop_reason": "keyboard_interrupt", "counters": {}}
        }
        status, blockers = classify_completed_formal_search(
            stopped, formal_profile_count=0
        )
        self.assertEqual(status, "incomplete")
        self.assertEqual(blockers, {"stop_reason:keyboard_interrupt": 1})


if __name__ == "__main__":
    unittest.main()
