import json
import math
import tempfile
import unittest
from pathlib import Path

from formal_disk4.config import load_config, load_geometry_config
from formal_disk4.geometry.model import parse_formal_geometry_problem
from formal_disk4.geometry.runner import GeometryRunner
from formal_disk4.geometry.solver import GeometrySolverConfig, NumericalContourSolver
from formal_disk4.pipeline.runner import SolverRunner


def build_pizza_candidate(directory: Path) -> Path:
    formal_output = directory / "formal"
    config = load_config(None)
    config["maps"] = ["k3-pizza"]
    config["limits"].update(
        {
            "max_assignments": None,
            "max_nodes": 1000,
            "max_placements": 10,
            "max_profiles": 1,
            "time_limit_seconds": 10,
            "stop_on_first_profile": True,
        }
    )
    config["progress"]["enabled"] = False
    config["output"].update(
        {
            "directory": str(formal_output),
            "write_candidates": True,
            "write_families": False,
            "write_unsupported": False,
            "write_word_cases": False,
            "write_placements": False,
        }
    )
    config["checkpoint"].update(
        {"enabled": True, "resume": True, "restart": True}
    )
    SolverRunner(config).run()
    return formal_output / "candidates.jsonl"


class GeometrySolverTests(unittest.TestCase):
    def test_pizza_profile_has_a_simple_closed_realization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            candidate_path = build_pizza_candidate(Path(temporary))
            candidate = json.loads(candidate_path.read_text(encoding="utf-8").splitlines()[0])
            problem = parse_formal_geometry_problem(
                candidate, source_path=candidate_path, source_line=1
            )
            result = NumericalContourSolver(
                GeometrySolverConfig(max_restarts=4, random_seed=0)
            ).solve(problem)
            self.assertIsNotNone(result.solution, result.reason)
            solution = result.solution
            assert solution is not None
            self.assertTrue(solution.validation.passed)
            self.assertLess(solution.validation.closure_error, 1e-8)
            self.assertEqual(solution.validation.self_intersection_count, 0)
            parameters = dict(solution.parameter_values)
            self.assertAlmostEqual(parameters["L_C0"], 1.0 / (2.0 * math.pi), places=8)
            templates = {item["component_id"]: item for item in solution.templates}
            self.assertEqual(templates["C0"]["curve_type"], "generic_curve")
            self.assertEqual(len(templates["C0"]["local_control_points"]), 3)
            self.assertEqual(templates["C1"]["curve_type"], "circular_arc")
            self.assertAlmostEqual(
                templates["C1"]["circular_arc"]["radius"],
                1.0 / (2.0 * math.pi),
                places=8,
            )
            self.assertAlmostEqual(
                templates["C1"]["circular_arc"]["signed_sweep_radians"],
                2.0 * math.pi / 3.0,
                places=8,
            )

    def test_geometry_runner_writes_reference_and_full_formal_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate_path = build_pizza_candidate(root)
            geometry_output = root / "geometry"
            config = load_geometry_config(None)
            config["input"]["candidates_file"] = str(candidate_path)
            config["output"].update(
                {
                    "directory": str(geometry_output),
                    "include_formal_candidate": True,
                    "write_failures": False,
                }
            )
            config["limits"].update(
                {"max_solutions": 1, "stop_on_first_solution": True}
            )
            config["checkpoint"].update(
                {"enabled": True, "resume": True, "restart": True}
            )
            summary = GeometryRunner(config).run()
            self.assertEqual(summary["stop_reason"], "first_solution")
            solution_path = geometry_output / "geometric_solutions.jsonl"
            records = [
                json.loads(line)
                for line in solution_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(records), 1)
            record = records[0]
            self.assertEqual(
                record["formal_profile_id"],
                record["geometric_solution"]["formal_profile_id"],
            )
            self.assertEqual(
                record["formal_profile_id"],
                record["formal_candidate"]["formal_profile_id"],
            )
            self.assertTrue(record["geometric_solution"]["validation"]["passed"])
            self.assertEqual(
                record["geometric_solution"]["scope"], "single_piece_contour_only"
            )
            checkpoint = json.loads(
                (geometry_output / "geometry_checkpoint.json").read_text(encoding="utf-8")
            )
            self.assertEqual(checkpoint["next_line"], 2)
            self.assertEqual(checkpoint["candidates_solved"], 1)


if __name__ == "__main__":
    unittest.main()
