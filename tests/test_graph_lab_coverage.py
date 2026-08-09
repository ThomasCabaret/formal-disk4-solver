from __future__ import annotations

import unittest
from pathlib import Path

from formal_disk4.graph_lab.coverage import (
    CatalogCoverageDomain,
    CatalogGraphClass,
    collect_catalog_graph_classes,
    measure_prior_coverage,
)
from formal_disk4.graph_lab.space import GraphSpace, candidate_from_planar_map


ROOT = Path(__file__).resolve().parents[1]


class GraphLabCoverageTests(unittest.TestCase):
    def test_catalog_targets_are_partitioned_into_representable_classes(self) -> None:
        domain = collect_catalog_graph_classes(ROOT, maximum_tiles=13)
        self.assertTrue(domain.classes)
        self.assertTrue(
            all(target.representative.tile_count <= 13 for target in domain.classes)
        )
        self.assertEqual(
            len({case_id for target in domain.classes for case_id in target.case_ids}),
            sum(len(target.case_ids) for target in domain.classes),
        )

    def test_unlearned_prior_quickly_rediscovers_small_cycle_controls(self) -> None:
        targets = tuple(
            CatalogGraphClass(
                candidate_from_planar_map(name, imposed_automorphism=None),
                case_ids=[name],
                map_names=[name],
            )
            for name in ("c3", "c4")
        )
        domain = CatalogCoverageDomain(
            classes=targets,
            excluded_cases=(),
            selectable_case_count=2,
        )
        space = GraphSpace(
            maximum_tiles=4,
            symmetric_prior_fraction=1.0,
            imposed_symmetry_bias=0.0,
        )
        report = measure_prior_coverage(
            space,
            domain,
            samples=100,
            seed=1234,
            report_every=0,
        )
        self.assertTrue(report["complete"])
        self.assertLessEqual(report["samples_drawn"], 100)


if __name__ == "__main__":
    unittest.main()
