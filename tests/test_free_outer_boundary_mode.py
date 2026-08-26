from __future__ import annotations

from pathlib import Path
import random
import unittest

from formal_disk4.graph_lab.evaluator import GraphFormalEvaluator
from formal_disk4.graph_lab.free_outer_boundary import (
    FREE_OUTER_BOUNDARY_STRUCTURE_KIND,
    free_outer_boundary_descriptor,
    free_outer_boundary_model_candidate,
    relax_outer_boundary,
)
from formal_disk4.graph_lab.space import (
    OUTSIDE,
    DualGraphCandidate,
    build_dynamic_planar_map,
)


ROOT = Path(__file__).resolve().parents[1]


def four_tile_ring() -> DualGraphCandidate:
    return DualGraphCandidate(
        tile_count=4,
        edges=tuple(
            sorted(
                (
                    (OUTSIDE, 0),
                    (OUTSIDE, 1),
                    (OUTSIDE, 2),
                    (OUTSIDE, 3),
                    (0, 1),
                    (1, 2),
                    (2, 3),
                    (0, 3),
                )
            )
        ),
        imposed_permutation=(1, 2, 3, 0),
        origin="test",
        mutation="four_tile_ring",
    )


class FreeOuterBoundaryModeTests(unittest.TestCase):
    def test_relaxation_keeps_the_complete_map_and_only_frees_its_exterior(self) -> None:
        candidate = four_tile_ring()
        source = build_dynamic_planar_map(candidate)
        relaxed = relax_outer_boundary(source)
        source_map = source.planar_map
        planar_map = relaxed.planar_map

        self.assertEqual(
            tuple(piece.name for piece in planar_map.pieces),
            tuple(piece.name for piece in source_map.pieces),
        )
        self.assertEqual(
            planar_map.internal_interfaces(), source_map.internal_interfaces()
        )
        self.assertFalse(planar_map.outer_interfaces())
        self.assertEqual(
            len(planar_map.free_interfaces()), len(source_map.outer_interfaces())
        )
        self.assertTrue(
            all(piece.outer_boundary_contact == "none" for piece in planar_map.pieces)
        )
        source_outer_vertices = {
            vertex.name for vertex in source_map.vertices if vertex.is_outer_boundary
        }
        relaxed_vertices = planar_map.vertex_map()
        self.assertTrue(source_outer_vertices)
        self.assertTrue(
            all(relaxed_vertices[name].kind == "free" for name in source_outer_vertices)
        )
        self.assertTrue(
            all(
                relaxed_vertices[name].solid_angle_relation == "strict_upper"
                and float(relaxed_vertices[name].solid_angle_limit_pi) == 2.0
                for name in source_outer_vertices
            )
        )
        self.assertEqual(planar_map.automorphisms, source_map.automorphisms)
        self.assertEqual(
            relaxed.imposed_automorphism, source.imposed_automorphism
        )
        self.assertFalse(planar_map.hypotheses.center_strictly_inside_one_tile)
        self.assertFalse(planar_map.outer_boundary_is_complete)
        planar_map.validate()

    def test_mapping_ranker_drops_only_the_outside_node(self) -> None:
        candidate = four_tile_ring()
        relaxed = relax_outer_boundary(build_dynamic_planar_map(candidate))
        model = free_outer_boundary_model_candidate(candidate, relaxed)

        self.assertEqual(model.tile_count, candidate.tile_count)
        self.assertEqual(model.imposed_permutation, candidate.imposed_permutation)
        self.assertEqual(
            set(model.edges),
            {edge for edge in candidate.edges if OUTSIDE not in edge},
        )
        self.assertIsNone(model.stein_center_tile)
        descriptor = free_outer_boundary_descriptor(candidate, relaxed)
        self.assertEqual(descriptor["kind"], FREE_OUTER_BOUNDARY_STRUCTURE_KIND)
        self.assertEqual(descriptor["retained_tile_count"], 4)

    def test_evaluator_samples_mappings_on_the_relaxed_complete_map(self) -> None:
        candidate = four_tile_ring()
        evaluator = GraphFormalEvaluator(
            ROOT,
            {
                "base_search_config": "config/cycle_campaign/search.json",
                "free_outer_boundary": True,
            },
        )
        pool = evaluator.mapping_pool(candidate, random.Random(20260825), 3)

        # This highly symmetric four-tile ring has a single compatible
        # contour assignment after the imposed equivariance quotient.
        self.assertGreaterEqual(len(pool), 1)
        self.assertLessEqual(len(pool), 3)
        self.assertTrue(evaluator.free_outer_boundary)
        for proposal in pool:
            self.assertEqual(proposal.evaluation_source, candidate)
            self.assertEqual(proposal.candidate.tile_count, candidate.tile_count)
            self.assertTrue(
                all(OUTSIDE not in edge for edge in proposal.candidate.edges)
            )
            self.assertEqual(
                len(proposal.edge_ports), len(proposal.candidate.edges)
            )

    def test_relaxed_ring_reaches_a_geometry_ready_formal_profile(self) -> None:
        candidate = four_tile_ring()
        evaluator = GraphFormalEvaluator(
            ROOT,
            {
                "base_search_config": "config/cycle_campaign/search.json",
                "free_outer_boundary": True,
                "mapping_search_overrides": {
                    "limits": {
                        "max_nodes": 2_000,
                        "max_placements": 20,
                        "max_profiles": 2,
                        "time_limit_seconds": 5,
                        "stop_on_first_profile": True,
                    },
                    "solver": {"max_seconds_per_word_case": 2},
                },
            },
        )
        proposal = evaluator.mapping_pool(candidate, random.Random(1), 1)[0]
        evaluation = evaluator.evaluate_mapping(
            proposal, rollouts=1, random_seed=7
        )

        self.assertFalse(evaluation.tainted, evaluation.error)
        self.assertTrue(evaluation.profiles, evaluation.counters)
        profile = evaluation.profiles[0]
        self.assertEqual(profile["profile"]["expected_outer_arc_count"], 0)
        self.assertEqual(profile["profile"]["expected_free_boundary_count"], 4)
        interfaces = profile["map"]["interfaces"]
        self.assertFalse(any(item["is_outer"] for item in interfaces))
        self.assertEqual(sum(bool(item["is_free"]) for item in interfaces), 4)

    def test_free_outer_boundary_and_crown_projection_are_exclusive(self) -> None:
        with self.assertRaisesRegex(ValueError, "mutually exclusive"):
            GraphFormalEvaluator(
                ROOT,
                {
                    "base_search_config": "config/cycle_campaign/search.json",
                    "outer_crown_only": True,
                    "free_outer_boundary": True,
                },
            )


if __name__ == "__main__":
    unittest.main()
