from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping

from .assembly import assemble_geometric_solution
from .viewer import JsonlSolutionSource


def validate_solution_file(config: Mapping[str, Any]) -> Dict[str, Any]:
    source = JsonlSolutionSource(Path(config["input"]["solutions_file"]))
    assembly_config = config["assembly"]
    maximum = int(config.get("limits", {}).get("max_solutions") or len(source))
    checked = 0
    maximum_error = 0.0
    records = []
    for index in range(min(len(source), maximum)):
        record = source.read(index)
        assembly = assemble_geometric_solution(
            record,
            interface_sample_count=int(assembly_config.get("interface_sample_count", 25)),
            polygon_arc_sample_count=int(assembly_config.get("polygon_arc_sample_count", 96)),
            tolerance=float(assembly_config.get("mapping_tolerance", 1e-6)),
        )
        checked += 1
        maximum_error = max(maximum_error, assembly.validation.maximum_interface_error)
        records.append(
            {
                "line": index + 1,
                "assembly_id": assembly.assembly_id,
                "map": assembly.map_name,
                "piece_count": len(assembly.placements),
                "maximum_interface_error": assembly.validation.maximum_interface_error,
            }
        )
    return {
        "solutions_file": str(source.path),
        "input_exists": source.exists,
        "available_solutions": len(source),
        "validated_solutions": checked,
        "maximum_interface_error": maximum_error,
        "assemblies": records,
    }
