from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Mapping


DEFAULT_CONFIG: Dict[str, Any] = {
    "maps": ["k4-central"],
    "enumeration": {
        "allow_reflections": True,
        "symmetry_mode": "incremental",
        "enable_length_filter": True,
        "enable_angle_filter": True,
        "lp_tolerance": 1e-9,
    },
    "solver": {
        "enabled": True,
        "mode": "exact_partial",
        "max_graph_nodes_per_placement": 3000,
        "max_graph_edges_per_placement": 12000,
        "max_families_per_placement": 8,
        "max_expression_nodes": 2000,
        "validation_exponent": 2,
        "family_expansion": {
            "policy": "none",
            "maximum_exponent": 1,
            "max_specializations_per_family": 64,
        },
    },
    "filters": {
        "enable_subsumption_hook": True,
        "enable_geometry_hook": True,
        "enable_cyclic_no_backtracking_heuristic": False,
        "deduplicate_exact_profiles": True,
    },
    "limits": {
        "max_assignments": None,
        "max_nodes": 200000,
        "max_placements": 200,
        "max_profiles": 100,
        "time_limit_seconds": None,
        "stop_on_first_profile": False,
    },
    "output": {
        "directory": "output/default_run",
        "candidates_file": "candidates.jsonl",
        "families_file": "word_families.jsonl",
        "unsupported_file": "unsupported_word_components.jsonl",
        "word_cases_file": "word_case_audit.jsonl",
        "placements_file": "placements.jsonl",
        "write_candidates": True,
        "write_families": False,
        "write_unsupported": False,
        "write_word_cases": False,
        "write_placements": False,
        "write_errors": True,
        "max_family_records": 10000,
        "max_unsupported_records": 10000,
        "max_word_case_records": 10000,
        "max_placement_records": 10000,
        "max_error_records": 1000,
        "flush_every": 1,
    },
    "checkpoint": {
        "enabled": True,
        "resume": True,
        "restart": False,
        "file": "checkpoint.sqlite3",
        "interval_seconds": 60.0,
    },
    "progress": {
        "enabled": True,
        "interval_seconds": 5.0,
        "percentage_step": 0.1,
    },
}


def _deep_merge(base: Dict[str, Any], override: Mapping[str, Any]) -> Dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _migrate_legacy_solver_keys(config: Dict[str, Any]) -> None:
    solver = config["solver"]
    if "max_states_per_placement" in solver and "max_graph_nodes_per_placement" not in solver:
        solver["max_graph_nodes_per_placement"] = solver["max_states_per_placement"]
    if "max_terminals_per_placement" in solver and "max_families_per_placement" not in solver:
        solver["max_families_per_placement"] = solver["max_terminals_per_placement"]
    # max_depth and max_environment_word_length belonged to the old bounded
    # unfolding solver. They are intentionally ignored in exact_partial mode.


def load_config(path: Path | None) -> Dict[str, Any]:
    if path is None:
        result = deepcopy(DEFAULT_CONFIG)
        _migrate_legacy_solver_keys(result)
        return result
    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ValueError("Configuration root must be a JSON object")
    result = _deep_merge(DEFAULT_CONFIG, loaded)
    _migrate_legacy_solver_keys(result)
    return result


def save_config(config: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


DEFAULT_GEOMETRY_CONFIG: Dict[str, Any] = {
    "input": {
        "candidates_file": "output/default_run/candidates.jsonl",
    },
    "output": {
        "directory": "output/default_run/geometry",
        "solutions_file": "geometric_solutions.jsonl",
        "summary_file": "geometry_summary.json",
        "checkpoint_file": "geometry_checkpoint.json",
        "failures_file": "geometry_failures.jsonl",
        "write_failures": False,
        "max_failure_records": 1000,
        "include_formal_candidate": True,
    },
    "geometry": {
        "intermediate_points_per_generic_curve": 1,
        "arc_sample_count": 48,
        "max_restarts": 32,
        "max_function_evaluations": 5000,
        "random_seed": 0,
        "maximum_curve_length": 4.0,
        "minimum_curve_length": 1e-6,
        "maximum_generic_turn_per_joint_pi": 0.95,
        "optimization_clearance": 1e-5,
        "closure_tolerance": 1e-8,
        "tangent_tolerance": 1e-7,
        "angle_tolerance": 1e-7,
        "length_tolerance": 1e-8,
        "intersection_tolerance": 1e-7,
        "minimum_area": 1e-8,
        "minimum_sample_edge_length": 1e-9,
    },
    "limits": {
        "max_candidates": None,
        "max_solutions": None,
        "stop_on_first_solution": False,
    },
    "checkpoint": {
        "enabled": True,
        "resume": True,
        "restart": False,
    },
}


def load_geometry_config(path: Path | None) -> Dict[str, Any]:
    if path is None:
        return deepcopy(DEFAULT_GEOMETRY_CONFIG)
    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ValueError("Geometry configuration root must be a JSON object")
    return _deep_merge(DEFAULT_GEOMETRY_CONFIG, loaded)



DEFAULT_VISUALIZATION_CONFIG: Dict[str, Any] = {
    "input": {
        "solutions_file": "output/default_run/geometry/geometric_solutions.jsonl",
    },
    "viewer": {
        "title": "Formal contour assembly viewer",
        "width": 1050,
        "height": 820,
        "background": "#62676d",
        "margin_pixels": 48,
        "start_index": 0,
        "cache_size": 4,
        "piece_palette": [
            "#e76f51",
            "#2a9d8f",
            "#e9c46a",
            "#457b9d",
            "#9b5de5",
            "#f4a261",
            "#4cc9f0",
            "#f15bb5"
        ],
    },
    "assembly": {
        "interface_sample_count": 25,
        "polygon_arc_sample_count": 96,
        "mapping_tolerance": 1e-6,
    },
    "limits": {
        "max_solutions": None,
    },
}


def _migrate_visualization_keys(config: Dict[str, Any]) -> None:
    # Compatibility with the short-lived development schema used before 0.5.0.
    input_config = config.setdefault("input", {})
    if "geometric_solutions_file" in input_config:
        input_config["solutions_file"] = input_config["geometric_solutions_file"]
    legacy = config.get("visualization")
    if isinstance(legacy, Mapping):
        viewer = config.setdefault("viewer", {})
        assembly = config.setdefault("assembly", {})
        if "background" in legacy:
            viewer["background"] = legacy["background"]
        if "interface_sample_count" in legacy:
            assembly["interface_sample_count"] = legacy["interface_sample_count"]
        if "contour_sample_count" in legacy:
            assembly["polygon_arc_sample_count"] = legacy["contour_sample_count"]


def load_visualization_config(path: Path | None) -> Dict[str, Any]:
    if path is None:
        result = deepcopy(DEFAULT_VISUALIZATION_CONFIG)
        _migrate_visualization_keys(result)
        return result
    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ValueError("Visualization configuration root must be a JSON object")
    result = _deep_merge(DEFAULT_VISUALIZATION_CONFIG, loaded)
    _migrate_visualization_keys(result)
    return result
