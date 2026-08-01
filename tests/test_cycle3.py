import json
from fractions import Fraction
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from formal_disk4.config import load_config
from formal_disk4.constraints.angle_lp import AngleFeasibilityOracle
from formal_disk4.constraints.length_lp import LengthFeasibilityOracle
from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.enumeration.weak_orders import WeakOrderEnumerator
from formal_disk4.maps import build_c3_map
from formal_disk4.pipeline.runner import SolverRunner
from formal_disk4.profiles.build import build_formal_profile
from formal_disk4.profiles.filters import ProfileFilterPipeline
from formal_disk4.words.compile import compile_word_case
from formal_disk4.words.exact_partial import ExactPartialWordSolver, SolverLimits
from formal_disk4.words.families import FamilyExpansionPolicy, expand_family


class CycleThreeMapTests(unittest.TestCase):
    def test_map_invariants(self) -> None:
        planar_map = build_c3_map()
        planar_map.validate()
        self.assertEqual(len(planar_map.pieces), 3)
        self.assertEqual(len(planar_map.vertices), 4)
        self.assertEqual(len(planar_map.internal_interfaces()), 3)
        self.assertEqual(len(planar_map.outer_interfaces()), 3)
        self.assertEqual(len(planar_map.occurrences()), 9)
        self.assertEqual(len(planar_map.automorphisms), 6)
        self.assertEqual(
            len(planar_map.vertices) - len(planar_map.interfaces) + 4,
            2,
        )

    def test_assignment_quotient_defers_unsafe_reference_actions(self) -> None:
        planar_map = build_c3_map()
        direct = AssignmentEnumerator(
            planar_map, allow_reflections=False, symmetry_mode="assignment"
        )
        reflected = AssignmentEnumerator(
            planar_map, allow_reflections=True, symmetry_mode="assignment"
        )
        self.assertEqual(direct.raw_assignment_count(), 9)
        self.assertEqual(len(tuple(direct.enumerate())), 9)
        self.assertEqual(reflected.raw_assignment_count(), 36)
        self.assertEqual(len(tuple(reflected.enumerate())), 36)

    def test_obvious_sector_profile_survives_current_filters(self) -> None:
        planar_map = build_c3_map()
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
        self.assertEqual(len(profile.contact_mappings), 3)
        self.assertEqual(len(profile.outer_arcs), 3)
        self.assertEqual(
            profile.terminal_contour[0].variable,
            profile.terminal_contour[-1].variable,
        )
        self.assertNotEqual(
            profile.terminal_contour[0].inverse,
            profile.terminal_contour[-1].inverse,
        )

        decorated = profile.decorated_terminal_contour()
        self.assertIn("T1{circular_arc:disk_boundary,L=1/3*C_disk", decorated["text"])
        point_angles = [
            point.prototype_angle_expression.exact_value
            for point in profile.point_decorations
        ]
        self.assertEqual(point_angles, [Fraction(2, 3), None, None])
        angle_expressions = [
            point.prototype_angle_expression.to_text()
            for point in profile.point_decorations
        ]
        self.assertEqual(
            angle_expressions,
            ["2/3", "1 - alpha_B2", "alpha_B2"],
        )
        self.assertEqual(
            profile.exact_angle_solution.free_parameters,
            ("alpha_B2",),
        )

        components = {component.representative: component for component in profile.curve_components}
        self.assertEqual(components["T0"].curve_type, "generic_curve")
        self.assertIsNone(components["T0"].disk_normalized_length.exact_value)
        self.assertEqual(components["T1"].curve_type, "circular_arc")
        self.assertEqual(components["T1"].disk_normalized_length.exact_value, Fraction(1, 3))
        self.assertEqual(components["T1"].disk_normalized_turn_pi.exact_value, Fraction(2, 3))
        self.assertEqual(components["T1"].curve_turn_pi.exact_value, Fraction(2, 3))
        self.assertIn("K_C0", components["T0"].curve_turn_pi.free_parameters)
        self.assertGreater(profile.joint_angular_feasibility.strict_margin, 0)
        point_turns = [
            point.prototype_turn_expression.exact_value
            for point in profile.point_decorations
        ]
        self.assertEqual(point_turns, [Fraction(1, 3), None, None])
        self.assertEqual(
            [point.prototype_turn_expression.to_text() for point in profile.point_decorations],
            ["1/3", "alpha_B2", "1 - alpha_B2"],
        )
        equation_kinds = {
            equation.kind for equation in profile.joint_angular_feasibility.equations
        }
        self.assertIn("prototype_smooth_turn_balance", equation_kinds)
        self.assertIn("prototype_point_turn_balance", equation_kinds)

        relation_keys = {
            (item.relation, item.terms, item.rhs_pi) for item in profile.angle_equations
        }
        self.assertIn(
            ("incident_piece_angles_sum_to_pi", ((1, 1), (2, 1)), Fraction(1)),
            relation_keys,
        )
        self.assertFalse(
            any(relation == "equal_interior_angles" for relation, _terms, _rhs in relation_keys)
        )

    def test_exact_profile_fallback_survives_floating_lp_failure(self) -> None:
        with patch(
            "formal_disk4.profiles.decorations.linprog",
            side_effect=RuntimeError("synthetic floating-point solver failure"),
        ):
            self.test_obvious_sector_profile_survives_current_filters()

    def test_streaming_run_finds_cycle_survivor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = load_config(None)
            config["maps"] = ["c3"]
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
            self.assertEqual(
                summary["statistics"]["counters"].get("profiles_emitted"), 1
            )
            candidate_path = Path(temporary) / "candidates.jsonl"
            records = [
                json.loads(line)
                for line in candidate_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["schema_version"], "formal-contour-survivor-v7")
            self.assertTrue(records[0]["formal_profile_id"].startswith("fp-"))
            self.assertEqual(records[0]["map"]["name"], "c3")
            self.assertEqual(len(records[0]["profile"]["contact_mappings"]), 3)
            decorated = records[0]["profile"]["decorated_terminal_contour"]
            segments = [
                item["segment_after_point"] for item in decorated["cycle"]
            ]
            self.assertEqual(len(segments), 3)
            self.assertEqual(segments[0]["variable"], segments[-1]["variable"])
            self.assertNotEqual(
                segments[0]["template_orientation"],
                segments[-1]["template_orientation"],
            )
            self.assertEqual(
                records[0]["profile"]["canonical_contour_signature"],
                [[0, False], [0, True], [1, False]],
            )
            self.assertIn("1/3*C_disk", decorated["text"])
            self.assertIn("2/3*pi", decorated["text"])


if __name__ == "__main__":
    unittest.main()
