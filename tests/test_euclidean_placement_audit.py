from __future__ import annotations

import unittest
from unittest.mock import patch

from formal_disk4.enumeration.frontier_arrangements import (
    FrontierArrangementEnumerator,
)
from formal_disk4.geometry.placement_audit import (
    EuclideanPartialPlacementPruner,
    EuclideanPlacementAuditConfig,
    EuclideanPlacementAuditResult,
    audit_euclidean_placement,
)
from formal_disk4.graph_lab.free_outer_boundary import relax_outer_boundary
from formal_disk4.graph_lab.space import (
    build_dynamic_planar_map,
    candidate_from_planar_map,
)
from formal_disk4.maps.registry import build_map


class EuclideanPlacementAuditTests(unittest.TestCase):
    @staticmethod
    def _known_pizza_leaf():
        planar_map = build_map("k3-pizza")
        placement = next(
            FrontierArrangementEnumerator(planar_map, max_nodes=10_000).enumerate()
        )
        return planar_map, placement

    def test_known_leaf_satisfies_unit_disk_incidence_audit(self) -> None:
        planar_map, placement = self._known_pizza_leaf()

        result = audit_euclidean_placement(
            planar_map,
            placement,
            EuclideanPlacementAuditConfig(restarts=2, max_nfev=100),
        )

        self.assertEqual(result.boundary_mode, "unit_disk")
        self.assertTrue(result.numerically_feasible)
        self.assertLess(result.maximum_residual, 1.0e-7)

    def test_free_mode_has_no_unit_circle_or_containment_residuals(self) -> None:
        planar_map, placement = self._known_pizza_leaf()

        disk = audit_euclidean_placement(
            planar_map,
            placement,
            EuclideanPlacementAuditConfig(
                restarts=1, max_nfev=100, boundary_mode="unit_disk"
            ),
        )
        free = audit_euclidean_placement(
            planar_map,
            placement,
            EuclideanPlacementAuditConfig(
                restarts=1, max_nfev=100, boundary_mode="free"
            ),
        )

        self.assertEqual(free.boundary_mode, "free")
        self.assertTrue(free.numerically_feasible)
        self.assertLess(free.residual_count, disk.residual_count)

    def test_auto_mode_detects_a_relaxed_outer_boundary(self) -> None:
        dynamic = relax_outer_boundary(
            build_dynamic_planar_map(
                candidate_from_planar_map(
                    "k3-pizza", imposed_automorphism=None
                )
            )
        )
        placement = next(
            FrontierArrangementEnumerator(
                dynamic.planar_map, max_nodes=10_000
            ).enumerate()
        )

        result = audit_euclidean_placement(
            dynamic.planar_map,
            placement,
            EuclideanPlacementAuditConfig(restarts=1, max_nfev=100),
        )

        self.assertEqual(result.boundary_mode, "free")
        self.assertTrue(result.numerically_feasible)

    def test_partial_pruner_cuts_a_cycle_closing_subtree_and_taints_it(self) -> None:
        planar_map = build_map("k3-pizza")
        events: dict[str, int] = {}

        def count(name: str, amount: int = 1) -> None:
            events[name] = events.get(name, 0) + amount

        unresolved = EuclideanPlacementAuditResult(
            status="numerically_unresolved",
            boundary_mode="unit_disk",
            maximum_residual=0.25,
            rms_residual=0.1,
            variable_count=8,
            residual_count=8,
            jacobian_rank=8,
            restarts=1,
            evaluations=10,
        )
        pruner = EuclideanPartialPlacementPruner(
            planar_map,
            event_sink=count,
        )
        with patch(
            "formal_disk4.geometry.placement_audit."
            "audit_partial_euclidean_placement",
            return_value=unresolved,
        ):
            search = FrontierArrangementEnumerator(
                planar_map,
                partial_validators=(pruner,),
                event_sink=count,
                max_nodes=10_000,
            )
            placements = list(search.enumerate())

        self.assertEqual(placements, [])
        self.assertGreater(events.get("euclidean_partial_audits", 0), 0)
        self.assertGreater(events.get("euclidean_partial_pruned_subtrees", 0), 0)
        self.assertTrue(search.heuristic_pruning_used)


if __name__ == "__main__":
    unittest.main()
