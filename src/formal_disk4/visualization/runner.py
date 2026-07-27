from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping

from .validate import validate_solution_file
from .viewer import JsonlSolutionSource, run_visualizer


class VisualizationRunner:
    """Validate mapping-derived assemblies, then open the interactive viewer."""

    def __init__(self, config: Mapping[str, Any]) -> None:
        self.config = dict(config)

    def run(self, *, validate_only: bool = False) -> Dict[str, Any]:
        summary = validate_solution_file(self.config)
        if not validate_only:
            run_visualizer(self.config)
        return summary
