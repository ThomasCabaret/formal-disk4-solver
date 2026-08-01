import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from formal_disk4.config import load_config
from formal_disk4.constraints.angle_lp import AngleFeasibilityOracle
from formal_disk4.constraints.length_lp import LengthFeasibilityOracle
from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.enumeration.weak_orders import WeakOrderEnumerator
from formal_disk4.maps.k4 import build_k4_map
from formal_disk4.maps.registry import build_map
from formal_disk4.pipeline.runner import SolverRunner
from formal_disk4.words.algebra import Equation, Literal
from formal_disk4.words.exact_partial import ExactPartialWordSolver, SolverLimits
from formal_disk4.words.families import FamilyExpansionPolicy, expand_family


class CheckpointTests(unittest.TestCase):
    def test_default_policy_does_not_expand_power_families(self) -> None:
        config = load_config(None)
        self.assertEqual(config["solver"]["family_expansion"]["policy"], "none")
        equation = Equation((Literal("X"), Literal("Y")), (Literal("Y"), Literal("X")))
        families = list(
            ExactPartialWordSolver((equation,), ("X", "Y")).solve(
                SolverLimits(max_graph_nodes=200, max_graph_edges=1000, max_families=10)
            )
        )
        power_families = [family for family in families if family.exponent_minimums]
        self.assertTrue(power_families)
        for family in power_families:
            self.assertEqual(list(expand_family(family, FamilyExpansionPolicy())), [])

    def test_weak_order_cursor_resumes_after_completed_subtree(self) -> None:
        planar_map = build_k4_map()
        assignment_enumerator = AssignmentEnumerator(planar_map, symmetry_mode="incremental")
        assignment = next(assignment_enumerator.enumerate())
        first = WeakOrderEnumerator(
            planar_map,
            assignment,
            assignment_enumerator.occurrence_names,
            LengthFeasibilityOracle(),
            AngleFeasibilityOracle(),
            enable_length_filter=False,
            enable_angle_filter=False,
        )
        iterator = first.enumerate()
        first_placement = next(iterator)
        second_placement = next(iterator)  # commits the first leaf before yielding
        state = first.checkpoint_state()
        self.assertGreater(state["processed_leaf_mass"], 0)

        resumed = WeakOrderEnumerator(
            planar_map,
            assignment,
            assignment_enumerator.occurrence_names,
            LengthFeasibilityOracle(),
            AngleFeasibilityOracle(),
            enable_length_filter=False,
            enable_angle_filter=False,
            resume_state=state,
        )
        resumed_first = next(resumed.enumerate())
        self.assertEqual(resumed_first.blocks, second_placement.blocks)
        self.assertNotEqual(resumed_first.blocks, first_placement.blocks)

    def test_cyclic_shift_cursor_continues_after_a_completed_split(self) -> None:
        planar_map = build_map("wheel-4")
        assignments = AssignmentEnumerator(planar_map, symmetry_mode="off")
        assignment = assignments.assignment_at(0)
        transform = assignments.transform_for_automorphism("rotation_2")
        captured_states = []
        first_split_complete = [False]

        def capture(state: dict[str, object]) -> None:
            captured_states.append(dict(state))
            if state["last_completed_path"] == [-1]:
                first_split_complete[0] = True

        first = WeakOrderEnumerator(
            planar_map,
            assignment,
            assignments.occurrence_names,
            LengthFeasibilityOracle(),
            AngleFeasibilityOracle(),
            symmetry_mode="off",
            enable_length_filter=False,
            enable_angle_filter=False,
            enable_exterior_arc_repetition_filter=False,
            track_exact_leaf_mass=True,
            stop_predicate=lambda: first_split_complete[0],
            checkpoint_sink=capture,
            required_cyclic_shift_transform=transform,
        )
        first_split = tuple(first.enumerate())
        split_state = next(
            state
            for state in reversed(captured_states)
            if state["last_completed_path"] == [-1]
        )

        resumed = WeakOrderEnumerator(
            planar_map,
            assignment,
            assignments.occurrence_names,
            LengthFeasibilityOracle(),
            AngleFeasibilityOracle(),
            symmetry_mode="off",
            enable_length_filter=False,
            enable_angle_filter=False,
            enable_exterior_arc_repetition_filter=False,
            track_exact_leaf_mass=True,
            resume_state=split_state,
            required_cyclic_shift_transform=transform,
        )
        remaining = tuple(resumed.enumerate())

        self.assertEqual(len(first._cyclic_shift_splits), 4)
        self.assertEqual(len(first_split), 8_736)
        self.assertEqual(len(remaining), 26_208)
        self.assertEqual(len(first_split) + len(remaining), first.total_leaf_mass)
        self.assertEqual(remaining[0].placement_id, len(first_split))

    def test_default_run_uses_compact_checkpoint_and_no_bulk_audits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = load_config(None)
            config["output"]["directory"] = temporary
            config["progress"]["enabled"] = False
            config["limits"].update(
                {
                    "max_assignments": 1,
                    "max_nodes": 200,
                    "max_placements": None,
                    "max_profiles": None,
                    "time_limit_seconds": None,
                }
            )
            SolverRunner(config).run()
            root = Path(temporary)
            self.assertTrue((root / "checkpoint.sqlite3").exists())
            self.assertTrue((root / "candidates.jsonl").exists())
            self.assertFalse((root / "word_case_audit.jsonl").exists())
            self.assertFalse((root / "word_families.jsonl").exists())
            self.assertFalse((root / "unsupported_word_components.jsonl").exists())

            connection = sqlite3.connect(root / "checkpoint.sqlite3")
            try:
                checkpoint_rows = connection.execute(
                    "SELECT COUNT(*) FROM search_checkpoint"
                ).fetchone()[0]
                survivor_rows = connection.execute(
                    "SELECT COUNT(*) FROM survivors"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(checkpoint_rows, 1)
            self.assertGreaterEqual(survivor_rows, 0)

            summary = json.loads((root / "run_summary.json").read_text(encoding="utf-8"))
            self.assertFalse(summary["checkpoint"]["stores_rejected_cases"])
            self.assertFalse(summary["checkpoint"]["stores_solver_states"])

    def test_second_run_resumes_same_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = load_config(None)
            config["output"]["directory"] = temporary
            config["progress"]["enabled"] = False
            config["limits"].update(
                {
                    "max_assignments": 1,
                    "max_nodes": 120,
                    "max_placements": None,
                    "max_profiles": None,
                    "time_limit_seconds": None,
                }
            )
            first_summary = SolverRunner(config).run()
            first_nodes = first_summary["statistics"]["counters"].get("placement_nodes", 0)

            config["limits"]["max_nodes"] = 240
            second_summary = SolverRunner(config).run()
            self.assertTrue(second_summary["checkpoint"]["resumed"])
            second_nodes = second_summary["statistics"]["counters"].get("placement_nodes", 0)
            self.assertGreaterEqual(second_nodes, first_nodes)

    def test_unexpected_errors_taint_without_stopping_the_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = load_config(None)
            config["maps"] = ["c3"]
            config["output"]["directory"] = temporary
            config["progress"]["enabled"] = False
            config["checkpoint"].update(
                {"enabled": False, "resume": False, "restart": True}
            )
            config["limits"].update(
                {
                    "max_assignments": 1,
                    "max_nodes": 100,
                    "max_placements": None,
                    "max_profiles": None,
                    "time_limit_seconds": None,
                }
            )
            with patch(
                "formal_disk4.pipeline.runner.compile_word_case",
                side_effect=RuntimeError("synthetic compile failure"),
            ):
                summary = SolverRunner(config).run()

            self.assertTrue(summary["tainted"])
            self.assertGreater(summary["unexpected_error_count"], 0)
            self.assertEqual(
                summary["unexpected_errors_by_stage"]["compile_word_case"],
                summary["unexpected_error_count"],
            )
            self.assertEqual(summary["statistics"]["stop_reason"], "max_nodes")
            error_records = [
                json.loads(line)
                for line in (Path(temporary) / "errors.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            ]
            self.assertTrue(error_records)
            self.assertEqual(error_records[0]["stage"], "compile_word_case")
            self.assertIn("Traceback", error_records[0]["traceback"])


if __name__ == "__main__":
    unittest.main()
