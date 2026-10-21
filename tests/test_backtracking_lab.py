from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from formal_disk4.graph_lab.backtracking_lab import (
    _evaluation_config,
    _proof_gaps,
    build_parser,
    run,
)
from formal_disk4.graph_lab.evaluator import GraphEvaluation


ROOT = Path(__file__).resolve().parents[1]


class BacktrackingLabTests(unittest.TestCase):
    def test_evaluation_configuration_has_no_traversal_ceiling(self) -> None:
        config = _evaluation_config(
            ROOT / "config" / "local_graph_campaign" / "formal.json"
        )
        joint = config["joint_arrangement_search"]
        self.assertEqual(joint["strategy"], "tile_frontier")
        self.assertIsNone(joint["max_nodes"])
        self.assertIsNone(joint["time_limit_seconds"])
        limits = config["mapping_search_overrides"]["limits"]
        for name in (
            "max_assignments",
            "max_nodes",
            "max_placements",
            "max_profiles",
            "time_limit_seconds",
        ):
            self.assertIsNone(limits[name])
        self.assertFalse(limits["stop_on_first_profile"])

    def test_proof_gaps_are_not_presented_as_clean_exhaustion(self) -> None:
        self.assertEqual(
            _proof_gaps(
                {
                    "deferred_word_cases_terminal_contour_budget": 3,
                    "profiles_emitted": 2,
                }
            ),
            {"deferred_word_cases_terminal_contour_budget": 3},
        )

    def test_campaign_records_only_explicit_enumerator_exhaustion_as_complete(
        self,
    ) -> None:
        class FakeEvaluator:
            def __init__(self, _root, _config) -> None:
                pass

            def evaluate_joint_arrangements(
                self, candidate, *, progress_sink, **_kwargs
            ) -> GraphEvaluation:
                progress_sink(
                    {
                        "phase": "formal_kernel",
                        "profiles": 0,
                        "counters": {
                            "arrangement_nodes": 17,
                            "joint_arrangement_kernel_calls": 5,
                        },
                    }
                )
                return GraphEvaluation(
                    candidate=candidate,
                    stage_index=0,
                    elapsed_seconds=0.01,
                    stop_reason="joint_arrangement_exhausted",
                    counters={
                        "arrangement_nodes": 17,
                        "joint_arrangement_kernel_calls": 5,
                    },
                    profiles=(),
                    tainted=False,
                )

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "campaign"
            args = build_parser().parse_args(
                [
                    "--root",
                    str(ROOT),
                    "--graph-family",
                    "center-ring",
                    "--min-tiles",
                    "4",
                    "--max-tiles",
                    "4",
                    "--output-directory",
                    str(output),
                    "--no-dashboard",
                    "--exit-when-complete",
                ]
            )
            with patch(
                "formal_disk4.graph_lab.backtracking_lab.GraphFormalEvaluator",
                FakeEvaluator,
            ):
                self.assertEqual(run(args), 0)
            payload = json.loads(
                (output / "results.json").read_text(encoding="utf-8")
            )
            result = next(iter(payload["graphs"].values()))
            self.assertEqual(result["status"], "tree_exhausted")
            self.assertTrue(result["tree_complete"])
            self.assertEqual(result["kernel_calls"], 5)
            status = json.loads((output / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["state"], "completed")
            self.assertEqual(status["completed_graphs"], 1)


if __name__ == "__main__":
    unittest.main()
