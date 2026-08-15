import tempfile
import unittest
from pathlib import Path

from formal_disk4.geometry.recovery_benchmark import (
    BenchmarkSettings,
    generate_recovery_case,
    run_benchmark,
)
from formal_disk4.geometry.solver import GeometrySolverConfig


class GeometryRecoveryBenchmarkTests(unittest.TestCase):
    def test_generator_certifies_hidden_mixed_nonconvex_witness(self) -> None:
        config = GeometrySolverConfig(
            intermediate_points_per_generic_curve=3,
            max_restarts=4,
            max_function_evaluations=300,
            candidate_timeout_seconds=3.0,
        )
        generated = generate_recovery_case(
            case_index=0,
            case_seed=1234,
            difficulty="strong",
            vertex_count=10,
            solver_config=config,
        )
        metadata = generated.metadata
        self.assertTrue(metadata["oracle_validation"]["passed"])
        self.assertLess(metadata["oracle_formal_residual_norm"], 1e-7)
        self.assertGreaterEqual(metadata["reflex_vertex_count"], 4)
        self.assertLess(metadata["polygon_to_hull_area_ratio"], 0.8)
        self.assertGreater(metadata["curve_counts"]["straight_segment"], 0)
        self.assertGreater(metadata["curve_counts"]["circular_arc"], 0)
        self.assertGreater(metadata["curve_counts"]["generic_curve"], 0)
        self.assertGreater(metadata["oracle_distance_from_solver_initial"], 0.1)
        self.assertTrue(
            all(
                component.search_witness_length is None
                for component in generated.problem.components
            )
        )

    def test_one_case_benchmark_writes_compact_reproducible_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = BenchmarkSettings(
                case_count=1,
                solver_repeats=1,
                generator_seed=77,
                vertex_counts=(8,),
                difficulties=("moderate",),
                output_directory=temporary,
                write_solutions=True,
            )
            config = GeometrySolverConfig(
                intermediate_points_per_generic_curve=3,
                max_restarts=8,
                max_function_evaluations=400,
                candidate_timeout_seconds=4.0,
                random_seed=0,
            )
            report = run_benchmark(settings, config)
            self.assertEqual(report["aggregate"]["trial_count"], 1)
            self.assertEqual(report["aggregate"]["case_count"], 1)
            self.assertEqual(report["aggregate"]["successful_trials"], 1)
            root = Path(temporary)
            self.assertTrue((root / "report.json").is_file())
            self.assertTrue((root / "report.md").is_file())
            self.assertTrue((root / "trials.jsonl").is_file())
            self.assertTrue((root / "witnesses.jsonl").is_file())


if __name__ == "__main__":
    unittest.main()
