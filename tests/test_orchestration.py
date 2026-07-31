from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from formal_disk4.orchestration.catalog import CaseCatalog, CaseDefinition
from formal_disk4.orchestration.pipeline import (
    PipelineCallbacks,
    PipelineExecutor,
    PipelinePlan,
    PipelineTask,
    TaskProgress,
    materialize_task,
)


ROOT = Path(__file__).resolve().parents[1]


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
