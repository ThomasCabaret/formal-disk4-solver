import json
import tempfile
import unittest
from pathlib import Path

from formal_disk4.config import load_config
from formal_disk4.pipeline.runner import SolverRunner


class IntegrationTests(unittest.TestCase):
    def test_small_run_writes_exact_partial_audit_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = load_config(None)
            config["maps"] = ["c3"]
            config["limits"].update(
                {
                    "max_assignments": 1,
                    "max_nodes": 5000,
                    "max_placements": 2,
                    "max_profiles": 2,
                    "time_limit_seconds": 10,
                }
            )
            config["solver"].update(
                {
                    "max_graph_nodes_per_placement": 100,
                    "max_graph_edges_per_placement": 400,
                    "max_families_per_placement": 2,
                    "max_expression_nodes": 300,
                }
            )
            config["progress"]["enabled"] = False
            config["output"].update({
                "directory": temporary,
                "write_families": True,
                "write_unsupported": True,
                "write_word_cases": True,
                "max_family_records": 100,
                "max_unsupported_records": 100,
                "max_word_case_records": 100,
            })
            SolverRunner(config).run()
            summary_path = Path(temporary) / "run_summary.json"
            self.assertTrue(summary_path.exists())
            loaded = json.loads(summary_path.read_text(encoding="utf-8"))
            counters = loaded["statistics"]["counters"]
            self.assertGreater(counters.get("placement_nodes", 0), 0)
            self.assertGreater(counters.get("solver_cases", 0), 0)
            self.assertTrue((Path(temporary) / "word_case_audit.jsonl").exists())
            self.assertTrue((Path(temporary) / "word_families.jsonl").exists())
            self.assertTrue((Path(temporary) / "unsupported_word_components.jsonl").exists())
            self.assertIn("exact_partial_word_solver", loaded["statistics"]["timings_seconds"])

    def test_word_case_timeout_is_reported_and_search_continues(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = load_config(None)
            config["maps"] = ["c3"]
            config["limits"].update(
                {
                    "max_assignments": 1,
                    "max_nodes": 5000,
                    "max_placements": 2,
                    "max_profiles": 2,
                    "time_limit_seconds": 10,
                }
            )
            config["solver"]["max_seconds_per_word_case"] = 0
            config["checkpoint"]["enabled"] = False
            config["progress"]["enabled"] = False
            config["output"]["directory"] = temporary

            summary = SolverRunner(config).run()
            deferred = Path(temporary) / "deferred_word_cases.jsonl"

            self.assertEqual(
                summary["statistics"]["counters"].get("deferred_word_cases"),
                1,
            )
            self.assertTrue(deferred.exists())
            record = json.loads(deferred.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(record["reason"], "wall_time_budget")
            self.assertEqual(
                record["solver_summary"]["status"],
                "interrupted_external_stop",
            )


if __name__ == "__main__":
    unittest.main()
