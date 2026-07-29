import json
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from formal_disk4.config import load_config
from formal_disk4.constraints.angle_lp import AngleFeasibilityOracle
from formal_disk4.constraints.length_lp import LengthFeasibilityOracle
from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.enumeration.weak_orders import WeakOrderEnumerator
from formal_disk4.maps import build_c4_map
from formal_disk4.pipeline.runner import SolverRunner
from formal_disk4.profiles.build import build_formal_profile
from formal_disk4.profiles.filters import ProfileFilterPipeline
from formal_disk4.words.compile import compile_word_case
from formal_disk4.words.exact_partial import ExactPartialWordSolver, SolverLimits
from formal_disk4.words.families import FamilyExpansionPolicy, expand_family


class FourPiecePizzaTests(unittest.TestCase):
    def test_map_invariants(self) -> None:
        planar_map = build_c4_map()
        planar_map.validate()
        self.assertEqual(len(planar_map.pieces), 4)
        self.assertEqual(len(planar_map.vertices), 5)
        self.assertEqual(len(planar_map.internal_interfaces()), 4)
        self.assertEqual(len(planar_map.outer_interfaces()), 4)
        self.assertEqual(len(planar_map.occurrences()), 12)
        self.assertEqual(len(planar_map.automorphisms), 8)
        self.assertEqual(
            len(planar_map.vertices) - len(planar_map.interfaces) + 5,
            2,
        )

    def test_assignment_counts(self) -> None:
        planar_map = build_c4_map()
        enumerator = AssignmentEnumerator(
            planar_map, allow_reflections=True, symmetry_mode="assignment"
        )
        self.assertEqual(enumerator.raw_assignment_count(), 648)
        self.assertEqual(len(tuple(enumerator.enumerate())), 99)

    def test_obvious_quarter_sector_profile_survives(self) -> None:
        planar_map = build_c4_map()
        assignment_enumerator = AssignmentEnumerator(
            planar_map, allow_reflections=True, symmetry_mode="incremental"
        )
        assignment = next(assignment_enumerator.enumerate())
        placement = next(
            WeakOrderEnumerator(
                planar_map,
                assignment,
                assignment_enumerator.occurrence_names,
                LengthFeasibilityOracle(),
                AngleFeasibilityOracle(),
            ).enumerate()
        )
        compiled = compile_word_case(planar_map, placement)
        solver = ExactPartialWordSolver(compiled.equations, compiled.atomic_variables)
        family = next(
            solver.solve(
                SolverLimits(
                    max_graph_nodes=100,
                    max_graph_edges=400,
                    max_families=8,
                    max_expression_nodes=500,
                    validation_exponent=2,
                )
            )
        )
        self.assertEqual(family.kind, "finite")
        specialization = next(
            expand_family(family, FamilyExpansionPolicy(kind="none"))
        )
        profile = build_formal_profile(
            planar_map,
            assignment_enumerator.occurrence_names,
            placement,
            compiled,
            family,
            specialization,
        )
        filtered, statuses = ProfileFilterPipeline().apply(profile)
        self.assertIsNotNone(filtered, statuses)
        self.assertEqual(len(profile.contact_mappings), 4)
        self.assertEqual(len(profile.outer_arcs), 4)
        self.assertEqual(profile.decorated_terminal_contour()["word"], "T0^-1 T1 T0")

        point_angles = [
            point.prototype_angle_expression.exact_value
            for point in profile.point_decorations
        ]
        self.assertEqual(point_angles, [Fraction(1, 2), None, None])
        self.assertEqual(
            [point.prototype_angle_expression.to_text() for point in profile.point_decorations],
            ["1/2", "1 - alpha_B2", "alpha_B2"],
        )

        components = {component.representative: component for component in profile.curve_components}
        self.assertEqual(components["T0"].curve_type, "generic_curve")
        self.assertEqual(components["T1"].curve_type, "circular_arc")
        self.assertEqual(
            components["T1"].disk_normalized_length.exact_value,
            Fraction(1, 4),
        )
        self.assertEqual(
            components["T1"].curve_turn_pi.exact_value,
            Fraction(1, 2),
        )

    def test_streaming_run_finds_quarter_sector(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = load_config(None)
            config["maps"] = ["c4"]
            config["limits"].update(
                {
                    "max_nodes": 100,
                    "max_placements": 10,
                    "max_profiles": 1,
                    "time_limit_seconds": 10,
                    "stop_on_first_profile": True,
                }
            )
            config["progress"]["enabled"] = False
            config["output"].update(
                {
                    "directory": temporary,
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
            summary = SolverRunner(config).run()
            self.assertEqual(summary["statistics"]["stop_reason"], "first_profile")
            records = [
                json.loads(line)
                for line in (Path(temporary) / "candidates.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            ]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["map"]["name"], "c4")
            self.assertEqual(len(records[0]["profile"]["contact_mappings"]), 4)
            self.assertIn(
                "1/4*C_disk",
                records[0]["profile"]["decorated_terminal_contour"]["text"],
            )


if __name__ == "__main__":
    unittest.main()
