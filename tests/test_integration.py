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
            config["maps"] = ["k3-pizza"]
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


if __name__ == "__main__":
    unittest.main()
