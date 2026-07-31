import json
import tempfile
import unittest
from pathlib import Path

from formal_disk4.config import load_config, load_geometry_config, load_visualization_config
from formal_disk4.geometry.runner import GeometryRunner
from formal_disk4.pipeline.runner import SolverRunner
from formal_disk4.visualization.assembly import assemble_geometric_solution
from formal_disk4.visualization.validate import validate_solution_file
from formal_disk4.visualization.viewer import JsonlSolutionSource


def build_pizza_geometry(directory: Path) -> Path:
    formal_output = directory / "formal"
    formal_config = load_config(None)
    formal_config["maps"] = ["c3"]
    formal_config["limits"].update(
        {
            "max_nodes": 1000,
            "max_placements": 10,
            "max_profiles": 1,
            "time_limit_seconds": 10,
            "stop_on_first_profile": True,
        }
    )
    formal_config["progress"]["enabled"] = False
    formal_config["output"].update(
        {
            "directory": str(formal_output),
            "write_candidates": True,
            "write_families": False,
            "write_unsupported": False,
            "write_word_cases": False,
            "write_placements": False,
        }
    )
    formal_config["checkpoint"].update(
        {"enabled": True, "resume": True, "restart": True}
    )
    SolverRunner(formal_config).run()

    geometry_output = directory / "geometry"
    geometry_config = load_geometry_config(None)
    geometry_config["input"]["candidates_file"] = str(formal_output / "candidates.jsonl")
    geometry_config["output"].update(
        {
            "directory": str(geometry_output),
            "include_formal_candidate": True,
            "write_failures": False,
        }
    )
    geometry_config["limits"].update(
        {"max_solutions": 1, "stop_on_first_solution": True}
    )
    geometry_config["checkpoint"].update(
        {"enabled": True, "resume": True, "restart": True}
    )
    GeometryRunner(geometry_config).run()
    return geometry_output / "geometric_solutions.jsonl"


class VisualizationAssemblyTests(unittest.TestCase):
    def test_pizza_copies_are_derived_from_mappings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            solution_path = build_pizza_geometry(Path(temporary))
            record = json.loads(solution_path.read_text(encoding="utf-8").splitlines()[0])
            assembly = assemble_geometric_solution(record)
            self.assertTrue(assembly.validation.passed)
            self.assertEqual(assembly.map_name, "c3")
            self.assertEqual(len(assembly.placements), 3)
            self.assertLess(assembly.validation.maximum_interface_error, 1e-12)
            determinants = [placement.transform.determinant for placement in assembly.placements]
            self.assertTrue(all(value > 0.0 for value in determinants))

    def test_reflected_relative_mapping_produces_reflected_copy(self) -> None:
        occurrences = [
            {
                "segment_index": 0,
                "curve_type": "generic_curve",
                "start_point": [0.0, 0.0],
                "end_point": [1.0, 0.0],
                "control_points": [[0.0, 0.0], [1.0, 0.0]],
            },
            {
                "segment_index": 1,
                "curve_type": "generic_curve",
                "start_point": [1.0, 0.0],
                "end_point": [0.0, 1.0],
                "control_points": [[1.0, 0.0], [0.0, 1.0]],
            },
            {
                "segment_index": 2,
                "curve_type": "generic_curve",
                "start_point": [0.0, 1.0],
                "end_point": [0.0, 0.0],
                "control_points": [[0.0, 1.0], [0.0, 0.0]],
            },
        ]
        record = {
            "formal_profile_id": "fp-synthetic",
            "geometric_solution": {
                "geometric_solution_id": "geo-synthetic",
                "formal_profile_id": "fp-synthetic",
                "contour_occurrences": occurrences,
            },
            "formal_candidate": {
                "map": {
                    "name": "two-piece-test",
                    "reference_piece": "P0",
                    "pieces": [{"name": "P0"}, {"name": "P1"}],
                },
                "profile": {
                    "contact_mappings": [
                        {
                            "interface": "P0-P1",
                            "left_piece": "P0",
                            "right_piece": "P1",
                            "relative_parity": -1,
                            "pairs": [
                                {
                                    "left": {"segment": 0, "forward": True},
                                    "right": {"segment": 0, "forward": True},
                                }
                            ],
                        }
                    ]
                },
            },
        }
        assembly = assemble_geometric_solution(record)
        placements = assembly.placement_map
        self.assertGreater(placements["P0"].transform.determinant, 0.0)
        self.assertLess(placements["P1"].transform.determinant, 0.0)
        self.assertLess(assembly.validation.maximum_interface_error, 1e-12)

    def test_empty_or_missing_solution_file_is_a_valid_empty_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            missing = directory / "missing.jsonl"
            source = JsonlSolutionSource(missing)
            self.assertFalse(source.exists)
            self.assertEqual(len(source), 0)

            empty = directory / "empty.jsonl"
            empty.touch()
            config = load_visualization_config(None)
            config["input"]["solutions_file"] = str(empty)
            summary = validate_solution_file(config)
            self.assertTrue(summary["input_exists"])
            self.assertEqual(summary["available_solutions"], 0)
            self.assertEqual(summary["validated_solutions"], 0)

    def test_jsonl_source_and_validate_only_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            solution_path = build_pizza_geometry(Path(temporary))
            source = JsonlSolutionSource(solution_path)
            self.assertEqual(len(source), 1)
            self.assertIn("geometric_solution", source.read(0))
            config = load_visualization_config(None)
            config["input"]["solutions_file"] = str(solution_path)
            summary = validate_solution_file(config)
            self.assertEqual(summary["validated_solutions"], 1)
            self.assertEqual(summary["assemblies"][0]["piece_count"], 3)


if __name__ == "__main__":
    unittest.main()
