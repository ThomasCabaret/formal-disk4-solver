from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from formal_disk4.mapping_lab.deep_support import (
    DEEP_STAGES,
    WORD_SOLVER_DEPTH,
    DeepArchive,
    PersistentSeen,
    deep_failure_name,
    deep_learning_depth,
)


class DeepMappingLabTests(unittest.TestCase):
    def test_preword_curriculum_refines_only_the_coarse_linear_stage(self) -> None:
        before_linear = {"stage_index": 7, "diagnostics": {}}
        first_exact_failure = {
            "stage_index": 8,
            "diagnostics": {
                "preword_linear_curriculum": {"passed_steps": 0}
            },
        }
        three_exact_steps = {
            "stage_index": 8,
            "diagnostics": {
                "preword_linear_curriculum": {"passed_steps": 3}
            },
        }
        production_word_stage = {"stage_index": 9, "diagnostics": {}}

        self.assertEqual(deep_learning_depth(before_linear), 7)
        self.assertEqual(deep_learning_depth(first_exact_failure), 8)
        self.assertEqual(deep_failure_name(first_exact_failure), "preword_positive_lengths")
        self.assertEqual(deep_learning_depth(three_exact_steps), 11)
        self.assertEqual(
            deep_learning_depth(production_word_stage), WORD_SOLVER_DEPTH
        )

    def test_persistent_seen_survives_reopening_and_ignores_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path = Path(raw_directory) / "seen.sqlite3"
            seen = PersistentSeen(path)
            seen.add_many(("a", "b", "a"))
            self.assertEqual(len(seen), 2)
            seen.close()

            reopened = PersistentSeen(path)
            self.assertIn("a", reopened)
            self.assertIn("b", reopened)
            self.assertNotIn("c", reopened)
            reopened.add("c")
            self.assertEqual(len(reopened), 3)
            reopened.close()

    def test_archive_retains_exact_curriculum_depth_and_failure(self) -> None:
        archive = DeepArchive(capacity=4, per_failure=2)
        evaluation = {
            "candidate_id": "candidate",
            "masks": [1, 2, 4],
            "stage_index": 8,
            "reason": "exact metric infeasible",
            "diagnostics": {
                "preword_linear_curriculum": {"passed_steps": 1}
            },
        }
        self.assertTrue(archive.add(evaluation))
        self.assertEqual(archive.entries[0].depth, 9)
        self.assertEqual(archive.entries[0].failure, DEEP_STAGES[10])


if __name__ == "__main__":
    unittest.main()
