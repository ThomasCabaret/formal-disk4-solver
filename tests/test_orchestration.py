from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from formal_disk4.orchestration.catalog import CaseCatalog, CaseDefinition
from formal_disk4.orchestration.pipeline import (
    PipelineCallbacks,
    PipelineExecutor,
    PipelinePlan,
    PipelineTask,
    TaskProgress,
    _TaskLease,
    materialize_task,
    task_checkpoint_completed,
)
from formal_disk4.pipeline.checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    search_fingerprint,
)


ROOT = Path(__file__).resolve().parents[1]


def _minimal_search_config(output_directory: str) -> dict[str, object]:
    return {
        "maps": ["c3"],
        "enumeration": {},
        "solver": {},
        "filters": {},
        "output": {"directory": output_directory},
        "checkpoint": {
            "enabled": True,
            "resume": True,
            "restart": False,
            "file": "checkpoint.sqlite3",
        },
    }


def _write_search_checkpoint(path: Path, config: dict[str, object], *, completed: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE search_checkpoint("
            "singleton INTEGER PRIMARY KEY, schema_version INTEGER, "
            "config_fingerprint TEXT, updated_utc TEXT, completed INTEGER, "
            "state_json TEXT, stats_json TEXT)"
        )
        connection.execute(
            "CREATE TABLE survivors("
            "profile_key TEXT PRIMARY KEY, created_utc TEXT, payload_json TEXT)"
        )
        connection.execute(
            "INSERT INTO search_checkpoint VALUES(1, ?, ?, '', ?, '{}', '{}')",
            (
                CHECKPOINT_SCHEMA_VERSION,
                search_fingerprint(config),
                1 if completed else 0,
            ),
        )
        connection.commit()
    finally:
        connection.close()



class CaseCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = CaseCatalog.load(ROOT)

    def test_catalog_discovers_static_and_parameterized_cases(self) -> None:
        ids = {case.case_id for case in self.catalog.cases}
        self.assertIn("k4", ids)
        self.assertIn("double-cycle-offset-4", ids)
        self.assertIn("inner-cycle-boundary-points-6", ids)
        self.assertIn("double-cycle-6", ids)
        self.assertFalse(any(case.structurally_impossible for case in self.catalog.cases))
        self.assertEqual(len(ids), len(self.catalog.cases))

    def test_double_cycle_6_is_loaded_from_the_parameterized_family(self) -> None:
        case = self.catalog.get("double-cycle-6")
        self.assertEqual(case.map_name, "double-cycle-6")
        self.assertEqual(
            case.source,
            ROOT / "config" / "case_families" / "cyclic-two-ring.json",
        )

    def test_rotation_2_size_4_cases_are_available(self) -> None:
        expected = {
            "double-cycle-4-rotation-2": "double-cycle-4",
            "double-cycle-offset-4-rotation-2": "double-cycle-offset-4",
            "inner-cycle-boundary-points-4-rotation-2":
                "inner-cycle-boundary-points-4",
            "outer-cycle-center-points-4-rotation-2":
                "outer-cycle-center-points-4",
        }
        for case_id, map_name in expected.items():
            with self.subTest(case_id=case_id):
                case = self.catalog.get(case_id)
                self.assertEqual(case.map_name, map_name)
                self.assertEqual(
                    case.output_directory, Path("output") / "cases" / case_id
                )
                with tempfile.TemporaryDirectory() as directory:
                    materialized = materialize_task(
                        ROOT,
                        case,
                        PipelineTask(case_id, "search"),
                        Path(directory),
                        task_index=0,
                    )
                    config = json.loads(
                        materialized.config_path.read_text(encoding="utf-8")
                    )
                equivariance = config["enumeration"]["cyclic_equivariance"]
                self.assertTrue(equivariance["enabled"])
                self.assertTrue(equivariance["enforce_weak_orders"])
                self.assertEqual(equivariance["automorphism"], "rotation_2")

    def test_wheel_half_turn_case_uses_cyclic_shift_equivariance(self) -> None:
        case = self.catalog.get("k4-rotation-2")
        self.assertEqual(case.map_name, "wheel-4")
        with tempfile.TemporaryDirectory() as directory:
            materialized = materialize_task(
                ROOT,
                case,
                PipelineTask(case.case_id, "search"),
                Path(directory),
                task_index=0,
            )
            config = json.loads(
                materialized.config_path.read_text(encoding="utf-8")
            )
        self.assertFalse(config["enumeration"]["cyclic_equivariance"]["enabled"])
        self.assertTrue(config["enumeration"]["track_exact_domain_size"])
        cyclic_shift = config["enumeration"]["cyclic_shift_equivariance"]
        self.assertTrue(cyclic_shift["enabled"])
        self.assertEqual(cyclic_shift["automorphism"], "rotation_2")

    def test_wheel_rotation_one_catalog_covers_sizes_three_through_six(self) -> None:
        for size in range(3, 7):
            case = self.catalog.get(f"wheel-{size}-rotation-1")
            self.assertEqual(case.map_name, f"wheel-{size}")
            with tempfile.TemporaryDirectory() as directory:
                materialized = materialize_task(
                    ROOT,
                    case,
                    PipelineTask(case.case_id, "search"),
                    Path(directory),
                    task_index=0,
                )
                config = json.loads(
                    materialized.config_path.read_text(encoding="utf-8")
                )
            self.assertFalse(
                config["enumeration"]["cyclic_equivariance"]["enabled"]
            )
            cyclic_shift = config["enumeration"]["cyclic_shift_equivariance"]
            self.assertTrue(cyclic_shift["enabled"])
            self.assertEqual(cyclic_shift["automorphism"], "rotation_1")

    def test_static_visualizer_alias_is_exposed_as_visualize(self) -> None:
        case = self.catalog.get("k4")
        self.assertTrue(case.config_for("visualize").name.endswith("visualizer.json"))

    def test_dynamic_case_materializes_existing_pipeline_config(self) -> None:
        case = self.catalog.get("double-cycle-offset-4")
        task = PipelineTask(case.case_id, "search", ("--max-nodes", "10"))
        with tempfile.TemporaryDirectory() as directory:
            materialized = materialize_task(
                ROOT, case, task, Path(directory), task_index=0
            )
            config = json.loads(materialized.config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["maps"], ["double-cycle-offset-4"])
        self.assertEqual(
            config["output"]["directory"],
            "output/cases/double-cycle-offset-4",
        )
        equivariance = config["enumeration"]["cyclic_equivariance"]
        self.assertTrue(equivariance["enabled"])
        self.assertEqual(equivariance["automorphism"], "rotation_1")
        self.assertEqual(materialized.command[-2:], ("--max-nodes", "10"))

    def test_visualize_materialization_has_case_specific_empty_state(self) -> None:
        case = self.catalog.get("double-cycle-6")
        task = PipelineTask(case.case_id, "visualize")
        with tempfile.TemporaryDirectory() as directory:
            materialized = materialize_task(
                ROOT, case, task, Path(directory), task_index=0
            )
            config = json.loads(materialized.config_path.read_text(encoding="utf-8"))
        self.assertIn("Double cycle 6", config["viewer"]["title"])
        self.assertIn("No geometric solution", config["viewer"]["empty_message"])

    def test_geometry_materialization_uses_the_case_output(self) -> None:
        case = self.catalog.get("inner-cycle-boundary-points-6")
        task = PipelineTask(case.case_id, "geometry")
        with tempfile.TemporaryDirectory() as directory:
            materialized = materialize_task(
                ROOT, case, task, Path(directory), task_index=2
            )
            config = json.loads(materialized.config_path.read_text(encoding="utf-8"))
        self.assertEqual(
            config["input"]["candidates_file"],
            "output/cases/inner-cycle-boundary-points-6/candidates.jsonl",
        )
        self.assertEqual(
            config["output"]["directory"],
            "output/cases/inner-cycle-boundary-points-6/geometry",
        )


class PipelineModelTests(unittest.TestCase):
    def test_plan_roundtrip_and_fingerprint(self) -> None:
        plan = PipelinePlan(
            "demo",
            "Demo",
            (
                PipelineTask("double-cycle-3", "search", ("--restart",)),
                PipelineTask("double-cycle-3", "geometry"),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "demo.json"
            plan.save(path)
            loaded = PipelinePlan.load(path)
        self.assertEqual(plan.tasks, loaded.tasks)
        self.assertEqual(plan.fingerprint, loaded.fingerprint)

    def test_search_progress_parser(self) -> None:
        catalog = CaseCatalog.load(ROOT)
        case = catalog.get("double-cycle-3")
        tracker = TaskProgress(ROOT, PipelineTask(case.case_id, "search"), case)
        self.assertAlmostEqual(
            tracker.feed("[ 12.0s] map=x overall~ 47.2% assignment=1/2"),
            0.472,
        )
        self.assertIsNone(tracker.feed("ordinary line"))


    def test_fresh_materialization_restarts_search_and_geometry_checkpoints(self) -> None:
        catalog = CaseCatalog.load(ROOT)
        with tempfile.TemporaryDirectory() as directory:
            generated = Path(directory)
            search = materialize_task(
                ROOT,
                catalog.get("k4"),
                PipelineTask("k4", "search"),
                generated,
                task_index=0,
                restart_checkpoint=True,
            )
            geometry = materialize_task(
                ROOT,
                catalog.get("k4"),
                PipelineTask("k4", "geometry"),
                generated,
                task_index=1,
                restart_checkpoint=True,
            )
            visualize = materialize_task(
                ROOT,
                catalog.get("k4"),
                PipelineTask("k4", "visualize"),
                generated,
                task_index=2,
                restart_checkpoint=True,
            )
        self.assertEqual(search.command[-1], "--restart")
        self.assertEqual(geometry.command[-1], "--restart")
        self.assertNotIn("--restart", visualize.command)

    def test_fresh_materialization_does_not_duplicate_explicit_restart(self) -> None:
        catalog = CaseCatalog.load(ROOT)
        with tempfile.TemporaryDirectory() as directory:
            materialized = materialize_task(
                ROOT,
                catalog.get("k4"),
                PipelineTask("k4", "search", ("--restart",)),
                Path(directory),
                task_index=0,
                restart_checkpoint=True,
            )
        self.assertEqual(materialized.command.count("--restart"), 1)

    def test_stage_checkpoint_not_pipeline_state_controls_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "search.json"
            config = _minimal_search_config("output/cases/demo")
            config_path.write_text(json.dumps(config), encoding="utf-8")
            case = CaseDefinition(
                case_id="demo",
                label="Demo",
                description="",
                map_name="c3",
                group="Test",
                config_paths={"search": config_path},
                output_directory=Path("output/cases/demo"),
            )
            catalog = CaseCatalog(root, (case,))
            executor = PipelineExecutor(root, catalog)
            calls: list[tuple[str, ...]] = []

            def run_process(materialized, _index, _count, _callbacks, _log):
                calls.append(materialized.command)
                return 0

            executor._run_process = run_process  # type: ignore[method-assign]
            plan = PipelinePlan(
                "same-plan", "Same plan", (PipelineTask("demo", "search"),)
            )
            self.assertEqual(executor.run(plan, resume=False), 0)
            # The first run marks the pipeline task complete, but no solver
            # checkpoint exists. Resume must execute the task again.
            self.assertEqual(executor.run(plan, resume=True), 0)

        self.assertEqual(len(calls), 2)
        self.assertIn("--restart", calls[0])
        self.assertNotIn("--restart", calls[1])

    def test_only_compatible_completed_search_checkpoint_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "search.json"
            config = _minimal_search_config("output/cases/demo")
            config_path.write_text(json.dumps(config), encoding="utf-8")
            case = CaseDefinition(
                case_id="demo",
                label="Demo",
                description="",
                map_name="c3",
                group="Test",
                config_paths={"search": config_path},
                output_directory=Path("output/cases/demo"),
            )
            materialized = materialize_task(
                root, case, PipelineTask("demo", "search"), root / "generated", 0
            )
            effective = json.loads(
                materialized.config_path.read_text(encoding="utf-8")
            )
            checkpoint = root / "output/cases/demo/checkpoint.sqlite3"
            candidates = root / "output/cases/demo/candidates.jsonl"
            candidates.parent.mkdir(parents=True, exist_ok=True)
            candidates.write_text("", encoding="utf-8")
            _write_search_checkpoint(checkpoint, effective, completed=False)
            self.assertFalse(task_checkpoint_completed(root, materialized))
            checkpoint.unlink()
            _write_search_checkpoint(checkpoint, effective, completed=True)
            self.assertTrue(task_checkpoint_completed(root, materialized))

    def test_active_task_lease_blocks_a_second_solver_for_the_same_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "search.json"
            config = _minimal_search_config("output/cases/demo")
            config_path.write_text(json.dumps(config), encoding="utf-8")
            case = CaseDefinition(
                case_id="demo",
                label="Demo",
                description="",
                map_name="c3",
                group="Test",
                config_paths={"search": config_path},
                output_directory=Path("output/cases/demo"),
            )
            materialized = materialize_task(
                root, case, PipelineTask("demo", "search"), root / "generated", 0
            )
            lease = _TaskLease.acquire(root, materialized)
            lease.attach_child(os.getpid())
            try:
                with self.assertRaisesRegex(RuntimeError, "still active"):
                    _TaskLease.acquire(root, materialized)
            finally:
                lease.release()

    def test_interrupt_request_signals_the_active_child(self) -> None:
        if sys.platform == "win32":
            self.skipTest("The Windows console-group signal is covered on Windows.")
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "interrupted.txt"
            ready = Path(temporary) / "ready.txt"
            script = (
                "import pathlib,signal,time\n"
                f"p=pathlib.Path({str(marker)!r})\n"
                f"ready=pathlib.Path({str(ready)!r})\n"
                "def stop(_s,_f): p.write_text('ok'); raise SystemExit(0)\n"
                "signal.signal(signal.SIGINT, stop)\n"
                "ready.write_text('ready')\n"
                "while True: time.sleep(0.05)\n"
            )
            process = subprocess.Popen([sys.executable, "-S", "-c", script])
            executor = PipelineExecutor(ROOT, CaseCatalog.load(ROOT))
            with executor._process_lock:
                executor.current_process = process
            deadline = time.monotonic() + 5.0
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(ready.exists())
            executor.request_interrupt_current()
            process.wait(timeout=5)
            with executor._process_lock:
                executor.current_process = None
            self.assertTrue(marker.exists())

    def test_visualize_tasks_are_launched_without_waiting_for_previous_viewers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "visualizer.json"
            config.write_text(
                json.dumps(
                    {
                        "input": {"solutions_file": "unused.jsonl"},
                        "viewer": {},
                        "assembly": {},
                        "limits": {"max_solutions": None},
                    }
                ),
                encoding="utf-8",
            )
            cases = tuple(
                CaseDefinition(
                    case_id=f"case-{index}",
                    label=f"Case {index}",
                    description="",
                    map_name="c3",
                    group="Test",
                    config_paths={"visualize": config},
                    output_directory=Path("output") / f"case-{index}",
                )
                for index in (1, 2)
            )
            catalog = CaseCatalog(root, cases)
            executor = PipelineExecutor(root, catalog)
            launched: list[str] = []

            def launch(materialized, _index, _callbacks, _directory):
                launched.append(materialized.task.case_id)
                return 0

            executor._launch_visualizer = launch  # type: ignore[method-assign]
            plan = PipelinePlan(
                "visualizers",
                "Visualizers",
                tuple(PipelineTask(case.case_id, "visualize") for case in cases),
            )
            progress: list[float] = []
            result = executor.run(
                plan,
                PipelineCallbacks(on_pipeline_progress=progress.append),
                resume=False,
            )

        self.assertEqual(result, 0)
        self.assertEqual(launched, ["case-1", "case-2"])
        self.assertEqual(progress[-1], 1.0)


if __name__ == "__main__":
    unittest.main()
