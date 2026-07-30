import unittest

from formal_disk4.cli import _apply_geometry_overrides, _apply_overrides, build_parser
from formal_disk4.config import load_config, load_geometry_config


class CliOverrideTests(unittest.TestCase):
    def test_continue_after_profile_disables_first_profile_stop(self) -> None:
        args = build_parser().parse_args(
            ["run", "--continue-after-profile"]
        )
        config = load_config(None)
        config["limits"]["stop_on_first_profile"] = True
        _apply_overrides(config, args)
        self.assertFalse(config["limits"]["stop_on_first_profile"])

    def test_continue_after_solution_disables_first_solution_stop(self) -> None:
        args = build_parser().parse_args(
            ["geometry", "--continue-after-solution"]
        )
        config = load_geometry_config(None)
        config["limits"]["stop_on_first_solution"] = True
        _apply_geometry_overrides(config, args)
        self.assertFalse(config["limits"]["stop_on_first_solution"])

    def test_geometry_resource_limits_have_cli_overrides(self) -> None:
        args = build_parser().parse_args(
            [
                "geometry",
                "--max-restarts",
                "3",
                "--max-function-evaluations",
                "7",
                "--candidate-timeout",
                "1.5",
            ]
        )
        config = load_geometry_config(None)
        _apply_geometry_overrides(config, args)
        self.assertEqual(config["geometry"]["max_restarts"], 3)
        self.assertEqual(config["geometry"]["max_function_evaluations"], 7)
        self.assertEqual(config["geometry"]["candidate_timeout_seconds"], 1.5)


if __name__ == "__main__":
    unittest.main()
