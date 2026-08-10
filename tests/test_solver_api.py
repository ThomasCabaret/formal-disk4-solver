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


class FilterReportTests(unittest.TestCase):
    def test_report_exposes_stable_conditional_rates_and_ignores_witness_counts(self) -> None:
        report = FilterReport.from_counters(
            {
                "prefix_topology_checks": 8,
                "prefix_topology_cache_hits": 2,
                "prefix_topology_pruned_nodes": 3,
                "prefix_topology_rejection_crossing": 3,
                "prefix_topology_rejection_witness_detail": 3,
            }
        )

        observation = report.by_id("weak.prefix_topology")
        self.assertEqual(observation.entered, 10)
        self.assertEqual(observation.passed, 7)
        self.assertEqual(observation.rejected, 3)
        self.assertEqual(observation.conditional_pass_rate, 0.7)
        self.assertEqual(dict(observation.rejection_reasons), {"crossing": 3})
        self.assertEqual(
            len(report.target_vector()),
            len(report.to_dict()["target_order"]),
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
            "formal-filter-report-v1",
        )
        self.assertEqual(
            result.filters.by_id(
                "assignment.intrinsic_symmetry_quotient"
            ).entered,
            1,
        )
        self.assertEqual(len(result.assignments), 1, result.assignments)
        self.assertEqual(result.assignments[0].raw_assignment_id, 0)
        self.assertEqual(
            result.assignments[0].filters.by_id(
                "assignment.intrinsic_symmetry_quotient"
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


if __name__ == "__main__":
    unittest.main()
