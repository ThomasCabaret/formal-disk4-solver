from __future__ import annotations

from collections import Counter
from pathlib import Path
import random
import unittest

from formal_disk4.graph_lab.evaluator import GraphFormalEvaluator
from formal_disk4.graph_lab.outer_crown import (
    CROWN_REGION_STRUCTURE_KIND,
    dynamic_from_structure_descriptor,
    extract_outer_crown,
    outer_crown_descriptor,
    outer_crown_model_candidate,
)
from formal_disk4.graph_lab.space import GraphSpace, build_dynamic_planar_map
from formal_disk4.geometry.model import parse_formal_geometry_problem
from formal_disk4.orchestration.catalog_diagrams import build_catalog_schematic


ROOT = Path(__file__).resolve().parents[1]


class OuterCrownModeTests(unittest.TestCase):
    @staticmethod
    def _candidate():
        return GraphSpace(
            tile_counts=(19,),
            stein_symmetric=True,
            symmetry_orders=(3,),
        ).sample_prior(random.Random(20260824))

    def test_real_c3_stein_graph_becomes_one_free_outer_crown(self) -> None:
        candidate = self._candidate()
        source = build_dynamic_planar_map(candidate)
        crown = extract_outer_crown(source, prototype_rotation_order=3)
        planar_map = crown.planar_map

        expected = {
            piece.name
            for piece in source.planar_map.pieces
            if piece.outer_boundary_contact in {"arc", "point"}
        }
        self.assertEqual({piece.name for piece in planar_map.pieces}, expected)
        self.assertNotIn(
            f"T{candidate.stein_center_tile}",
            {piece.name for piece in planar_map.pieces},
        )
        self.assertTrue(planar_map.has_free_boundary)
        self.assertTrue(planar_map.outer_boundary_is_complete)
        self.assertEqual(planar_map.prototype_rotation_order, 3)
        self.assertFalse(planar_map.hypotheses.center_strictly_inside_one_tile)
        self.assertEqual(crown.imposed_equivariance_mode, "pointwise")

        degree: Counter[str] = Counter()
        for interface in planar_map.free_interfaces():
            view = interface.views[0]
            degree[view.start_vertex] += 1
            degree[view.end_vertex] += 1
        self.assertTrue(degree)
        self.assertEqual(set(degree.values()), {2})

        model_candidate = outer_crown_model_candidate(candidate, crown)
        self.assertEqual(model_candidate.tile_count, len(planar_map.pieces))
        self.assertEqual(model_candidate.symmetry_order, 3)
        self.assertIsNone(model_candidate.stein_center_tile)
        descriptor = outer_crown_descriptor(candidate, crown)
        self.assertEqual(descriptor["kind"], CROWN_REGION_STRUCTURE_KIND)
        self.assertEqual(descriptor["region_mode"], "full")
        self.assertEqual(descriptor["source_tile_count"], 19)
        self.assertEqual(
            descriptor["retained_tile_count"], len(planar_map.pieces)
        )

    def test_mapping_ranker_domain_is_aligned_with_the_partial_map(self) -> None:
        candidate = self._candidate()
        evaluator = GraphFormalEvaluator(
            ROOT,
            {
                "base_search_config": "config/cycle_campaign/search.json",
                "outer_crown_only": True,
            },
        )
        pool = evaluator.mapping_pool(candidate, random.Random(19), 4)

        self.assertEqual(len(pool), 4)
        retained = len(evaluator._dynamic(candidate).planar_map.pieces)
        for proposal in pool:
            self.assertEqual(proposal.evaluation_source, candidate)
            self.assertEqual(proposal.candidate.tile_count, retained)
            self.assertEqual(len(proposal.orientation_signs), retained)
            self.assertEqual(
                len(proposal.edge_ports), len(proposal.candidate.edges)
            )

    def test_one_tile_region_opens_the_crown_without_outer_angle_equality(self) -> None:
        candidate = self._candidate()
        source = build_dynamic_planar_map(candidate)
        region = extract_outer_crown(
            source,
            prototype_rotation_order=1,
            retained_tile_count=1,
            selection_key=candidate.graph_id,
        )
        planar_map = region.planar_map

        self.assertEqual(len(planar_map.pieces), 1)
        self.assertEqual(planar_map.prototype_rotation_order, 1)
        self.assertIsNone(region.imposed_automorphism)
        self.assertIsNone(region.imposed_equivariance_mode)
        self.assertTrue(planar_map.has_free_boundary)
        self.assertFalse(planar_map.outer_boundary_is_complete)
        self.assertTrue(planar_map.pieces[0].has_outer_boundary_arc)
        free_outer = tuple(
            vertex for vertex in planar_map.vertices if vertex.kind == "free_outer"
        )
        self.assertTrue(free_outer)
        self.assertTrue(
            all(vertex.solid_angle_relation == "strict_upper" for vertex in free_outer)
        )
        self.assertTrue(
            all(float(vertex.solid_angle_limit_pi) == 1.0 for vertex in free_outer)
        )
        # The same schematic renderer used by the dashboard must support an
        # open disk arc completed by a free cut.
        schematic = build_catalog_schematic(planar_map)
        self.assertEqual(len(schematic.pieces), 1)

        descriptor = outer_crown_descriptor(candidate, region)
        self.assertEqual(descriptor["kind"], CROWN_REGION_STRUCTURE_KIND)
        self.assertEqual(descriptor["region_mode"], "connected_subset")
        self.assertFalse(descriptor["prototype_symmetry_imposed"])
        restored = dynamic_from_structure_descriptor(candidate, descriptor)
        self.assertEqual(
            tuple(piece.name for piece in restored.planar_map.pieces),
            tuple(piece.name for piece in planar_map.pieces),
        )

    def test_partial_region_can_independently_impose_prototype_rotation(self) -> None:
        candidate = self._candidate()
        evaluator = GraphFormalEvaluator(
            ROOT,
            {
                "base_search_config": "config/cycle_campaign/search.json",
                "outer_crown_only": True,
                "partial_crown_tile_counts": "3",
                "prototype_symmetry_mode": "structural",
            },
        )
        region = evaluator._dynamic(candidate)

        self.assertEqual(len(region.planar_map.pieces), 3)
        self.assertEqual(region.planar_map.prototype_rotation_order, 3)
        self.assertIsNone(region.imposed_automorphism)

        unconstrained = GraphFormalEvaluator(
            ROOT,
            {
                "base_search_config": "config/cycle_campaign/search.json",
                "partial_crown_tile_counts": "3",
                "prototype_symmetry_mode": "none",
            },
        )._dynamic(candidate)
        self.assertEqual(unconstrained.planar_map.prototype_rotation_order, 1)

    def test_one_tile_unconstrained_region_reaches_a_formal_profile(self) -> None:
        candidate = self._candidate()
        evaluator = GraphFormalEvaluator(
            ROOT,
            {
                "base_search_config": "config/cycle_campaign/search.json",
                "partial_crown_tile_counts": "1",
                "prototype_symmetry_mode": "none",
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
        pool = evaluator.mapping_pool(candidate, random.Random(1901), 1)
        self.assertEqual(len(pool), 1)
        evaluation = evaluator.evaluate_mapping(
            pool[0],
            rollouts=1,
            random_seed=20260825,
        )

        self.assertFalse(evaluation.tainted, evaluation.error)
        self.assertTrue(evaluation.profiles, evaluation.counters)
        geometry_problem = parse_formal_geometry_problem(
            evaluation.profiles[0],
            source_path=Path("one-tile-crown-test.jsonl"),
            source_line=1,
        )
        self.assertTrue(geometry_problem.strict_angle_constraints)
        self.assertTrue(
            any(
                float(constraint.upper_pi) == 1.0
                for constraint in geometry_problem.strict_angle_constraints
            )
        )
        self.assertIn("L_OUTER_GAP", geometry_problem.parameter_names)
        circular = tuple(
            component
            for component in geometry_problem.components
            if component.circle_class == "disk_boundary"
        )
        self.assertEqual(len(circular), 1)
        self.assertIn("L_OUTER_GAP", circular[0].length.parameters)
        self.assertIsNotNone(circular[0].search_witness_length)
        self.assertLess(circular[0].search_witness_length, 1.0)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
