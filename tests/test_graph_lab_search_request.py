from __future__ import annotations

import random
import json
import tempfile
import unittest
from pathlib import Path

from formal_disk4.graph_lab.policy import PriorOnlyGraphPolicy
from formal_disk4.graph_lab.runner import GraphLabRunner
from formal_disk4.graph_lab.search_request import (
    ArrangementStrategy,
    GraphLabSearchRequest,
    OuterBoundaryMode,
    PolicyMode,
    PrototypeSymmetryMode,
    RegionMode,
)
from formal_disk4.graph_lab.space import DualGraphCandidate


ROOT = Path(__file__).resolve().parents[1]


class GraphLabSearchRequestTests(unittest.TestCase):
    def test_default_policy_is_prior_only(self) -> None:
        request = GraphLabSearchRequest.from_config({})

        self.assertEqual(request.policy, PolicyMode.PRIOR)
        self.assertEqual(request.region.mode, RegionMode.FULL)
        self.assertEqual(
            request.arrangement, ArrangementStrategy.JOINT_BACKTRACKING
        )

    def test_cli_style_overrides_form_one_valid_typed_request(self) -> None:
        request = GraphLabSearchRequest.from_config({}).with_overrides(
            tile_counts="5-13",
            stein_symmetric=True,
            symmetry_orders="2-4",
            partial_crown_tile_counts="1-3",
            joint_arrangement_search=True,
            policy_mode="learned",
        )

        self.assertEqual(request.domain.tile_counts, tuple(range(5, 14)))
        self.assertEqual(request.domain.symmetry_orders, (2, 3, 4))
        self.assertEqual(request.region.mode, RegionMode.CROWN_REGION)
        self.assertEqual(request.region.tile_counts, (1, 2, 3))
        self.assertEqual(
            request.prototype.symmetry, PrototypeSymmetryMode.STRUCTURAL
        )
        self.assertEqual(
            request.arrangement, ArrangementStrategy.JOINT_BACKTRACKING
        )
        self.assertEqual(request.policy, PolicyMode.LEARNED)

    def test_incompatible_boundary_constraints_are_rejected_early(self) -> None:
        with self.assertRaisesRegex(ValueError, "exclusive"):
            GraphLabSearchRequest.from_config({}).with_overrides(
                stein_symmetric=True,
                outer_crown_only=True,
                free_outer_boundary=True,
            )

    def test_config_round_trip_keeps_strategy_separate_from_domain(self) -> None:
        request = GraphLabSearchRequest.from_config({}).with_overrides(
            tile_counts="3-6",
            free_outer_boundary=True,
            joint_arrangement_search=True,
        )
        payload = request.apply_to_config({"evaluation": {"search_overrides": {}}})
        restored = GraphLabSearchRequest.from_config(payload)

        self.assertEqual(restored, request)
        self.assertEqual(restored.boundary.outer, OuterBoundaryMode.FREE)
        self.assertEqual(payload["evaluation"]["search_overrides"], {})

    def test_no_imposed_symmetry_keeps_symmetric_topologies_unconstrained(self) -> None:
        request = GraphLabSearchRequest.from_config({}).with_overrides(
            allow_imposed_symmetry=False
        )
        payload = request.apply_to_config({})

        self.assertFalse(request.structure.allow_imposed_symmetry)
        self.assertEqual(payload["space"]["imposed_symmetry_bias"], 0.0)
        self.assertFalse(
            GraphLabSearchRequest.from_config(payload).structure.allow_imposed_symmetry
        )


class PriorOnlyGraphPolicyTests(unittest.TestCase):
    @staticmethod
    def _candidate(index: int) -> DualGraphCandidate:
        return DualGraphCandidate(
            tile_count=3,
            edges=(
                (-1, 0),
                (-1, 1),
                (-1, 2),
                (0, 1),
                (1, 2),
                (0, 2),
            ),
            imposed_permutation=(0, 1, 2),
            origin="prior",
            mutation=f"test-{index}",
        )

    def test_prior_policy_selects_without_learned_predictions(self) -> None:
        policy = PriorOnlyGraphPolicy()
        selected = policy.select(
            tuple(self._candidate(index) for index in range(3)),
            novelty=lambda candidate: float(candidate.graph_id[-1] != "0"),
            rng=random.Random(7),
            amount=2,
        )

        self.assertEqual(len(selected), 2)
        self.assertTrue(
            all(metadata["selection_mode"] == "exploration" for _, metadata in selected)
        )
        self.assertTrue(
            all(
                metadata["predicted_transition_probabilities"] == []
                for _, metadata in selected
            )
        )

    def test_prior_run_keeps_stochastic_mapping_sampling_without_models(self) -> None:
        output_root = ROOT / "output"
        output_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output_root) as raw_output:
            runner = GraphLabRunner(
                ROOT,
                {
                    "output": {"directory": raw_output},
                    "space": {
                        "maximum_tiles": 3,
                        "symmetric_prior_fraction": 0.0,
                        "imposed_symmetry_bias": 0.0,
                    },
                    "sampling": {
                        "seed": 11,
                        "generations": 1,
                        "batch_size": 1,
                        "pool_multiplier": 1,
                    },
                    "mapping_sampling": {
                        "enabled": True,
                        "mappings_per_graph": 1,
                        "pool_multiplier": 2,
                        "rollouts_per_mapping": 1,
                    },
                    "weak_order_sampling": {"rollouts_per_mapping": 1},
                    "evaluation": {
                        "base_search_config": "config/cycle_campaign/search.json",
                        "mapping_search_overrides": {
                            "limits": {
                                "max_nodes": 200,
                                "max_placements": 2,
                                "max_profiles": 1,
                                "time_limit_seconds": 3,
                                "stop_on_first_profile": True,
                            }
                        },
                    },
                },
            )
            result = runner.run(restart=True)
            output = Path(raw_output)
            observation = json.loads(
                (output / "observations.jsonl").read_text(encoding="utf-8")
            )
            report = json.loads(
                (output / "report.json").read_text(encoding="utf-8")
            )

            self.assertEqual(result.observations, 1)
            self.assertEqual(
                observation["selection"]["selection_mode"], "exploration"
            )
            self.assertEqual(observation["selection"]["policy_mode"], "prior")
            self.assertEqual(report["policy_mode"], "prior")
            self.assertFalse((output / "model.pt").exists())
            self.assertFalse((output / "mapping_model.pt").exists())
            self.assertFalse((output / "mapping_observations.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
