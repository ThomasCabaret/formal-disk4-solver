from __future__ import annotations

import tempfile
import unittest

from formal_disk4.config import load_config
from formal_disk4.pipeline import (
    AssignmentSelection,
    FilterReport,
    FormalSolverAPI,
    SolverAPIRequest,
)
from formal_disk4.pipeline.filter_report import LEARNING_FILTER_IDS


class _FirstWeakOrderPolicy:
    def __init__(self) -> None:
        self.decisions = 0

    def propose_masks(self, _state, masks):
        return tuple(masks[:8])

    def select_actions(self, _state, actions):
        self.decisions += 1
        return (actions[0].mask,)


class _ReverseSpecializationPolicy:
    def __init__(self) -> None:
        self.pools = 0
        self.outcomes = []

    def select_specializations(self, _state, actions):
        self.pools += 1
        return tuple(reversed(range(len(actions))))

    def observe_specialization(self, _state, _action, outcome):
        self.outcomes.append(outcome)


class FilterReportTests(unittest.TestCase):
    def test_report_exposes_stable_conditional_rates_and_ignores_witness_counts(self) -> None:
        report = FilterReport.from_counters(
            {
                "prefix_topology_checks": 8,
                "prefix_topology_cache_hits": 2,
                "prefix_topology_hard_outer_endpoint_passes": 7,
                "prefix_topology_hard_outer_endpoint_rejections": 3,
                "prefix_topology_rejection_witness_detail": 3,
            }
        )

        observation = report.by_id("weak.prefix_topology.hard_outer_endpoint")
        self.assertEqual(observation.entered, 10)
        self.assertEqual(observation.passed, 7)
        self.assertEqual(observation.rejected, 3)
        self.assertEqual(observation.conditional_pass_rate, 0.7)
        self.assertEqual(dict(observation.rejection_reasons), {})
        self.assertEqual(
            tuple(report.to_dict()["target_order"]),
            LEARNING_FILTER_IDS,
        )


class SolverAPITests(unittest.TestCase):
    @staticmethod
    def _small_config(directory: str) -> dict[str, object]:
        config = load_config(None)
        config["maps"] = ["c3"]
        config["checkpoint"]["enabled"] = False
        config["progress"]["enabled"] = False
        config["enumeration"]["track_exact_domain_size"] = False
        config["limits"].update(
            {
                "max_nodes": 500,
                "max_placements": 1,
                "max_profiles": 1,
                "time_limit_seconds": 10,
            }
        )
        config["output"]["directory"] = directory
        return config

    def test_selected_raw_mapping_runs_through_production_kernel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            request = SolverAPIRequest(
                config=self._small_config(directory),
                assignments=(AssignmentSelection("c3", (0,)),),
            )
            result = FormalSolverAPI.evaluate(request)

        counters = result.summary["statistics"]["counters"]
        self.assertEqual(counters["raw_assignments_in_domain"], 1)
        self.assertEqual(counters["assignment_quotient_checks"], 1)
        self.assertEqual(
            result.summary["api_input"]["raw_assignment_ids_by_map"],
            {"c3": [0]},
        )
        self.assertEqual(
            result.summary["filter_report"]["schema_version"],
            "formal-filter-report-v2",
        )
        self.assertEqual(
            result.filters.by_id(
                "assignment.canonical"
            ).entered,
            1,
        )
        self.assertEqual(len(result.assignments), 1, result.assignments)
        self.assertEqual(result.assignments[0].raw_assignment_id, 0)
        self.assertEqual(
            result.assignments[0].filters.by_id(
                "assignment.canonical"
            ).entered,
            1,
        )

    def test_out_of_range_raw_mapping_is_rejected_before_search(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            request = SolverAPIRequest(
                config=self._small_config(directory),
                assignments=(AssignmentSelection("c3", (10**9,)),),
            )
            with self.assertRaisesRegex(ValueError, "outside"):
                FormalSolverAPI.evaluate(request)

    def test_optional_weak_order_policy_drives_one_branch_through_same_api(self) -> None:
        policy = _FirstWeakOrderPolicy()
        with tempfile.TemporaryDirectory() as directory:
            request = SolverAPIRequest(
                config=self._small_config(directory),
                assignments=(AssignmentSelection("c3", (0,)),),
                weak_order_branch_policy=policy,
                collect_learning_diagnostics=True,
            )
            result = FormalSolverAPI.evaluate(request)

        self.assertGreater(policy.decisions, 0)
        self.assertEqual(
            result.summary["api_input"]["weak_order_branch_policy"],
            "_FirstWeakOrderPolicy",
        )
        self.assertLessEqual(
            result.summary["statistics"]["counters"].get(
                "surviving_placements", 0
            ),
            1,
        )

    def test_profiles_can_be_returned_in_memory_without_candidate_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = self._small_config(directory)
            result = FormalSolverAPI.evaluate(
                SolverAPIRequest(
                    config=config,
                    assignments=(AssignmentSelection("c3", (0,)),),
                    collect_profiles=True,
                )
            )

        self.assertEqual(
            len(result.profiles),
            int(result.summary["statistics"]["counters"].get("profiles_emitted", 0)),
        )

    def test_optional_specialization_policy_ranks_complete_word_case_pool(self) -> None:
        policy = _ReverseSpecializationPolicy()
        with tempfile.TemporaryDirectory() as directory:
            result = FormalSolverAPI.evaluate(
                SolverAPIRequest(
                    config=self._small_config(directory),
                    assignments=(AssignmentSelection("c3", (0,)),),
                    family_specialization_policy=policy,
                    collect_profiles=True,
                )
            )

        self.assertGreater(policy.pools, 0)
        self.assertGreater(len(policy.outcomes), 0)
        self.assertEqual(
            result.summary["api_input"]["family_specialization_policy"],
            "_ReverseSpecializationPolicy",
        )
        counters = result.summary["statistics"]["counters"]
        self.assertEqual(
            counters.get("specialization_policy_candidates"),
            len(policy.outcomes),
        )
        self.assertEqual(
            counters.get("specialization_policy_selected"),
            len(policy.outcomes),
        )


if __name__ == "__main__":
    unittest.main()
