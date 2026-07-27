from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

import numpy as np

from .assembly import AssemblyError, AssemblySolution, assemble_geometric_solution


class JsonlSolutionSource:
    """Random-access JSONL reader storing only byte offsets in memory."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        self.offsets: list[int] = []
        with self.path.open("rb") as handle:
            while True:
                offset = handle.tell()
                line = handle.readline()
                if not line:
                    break
                if line.strip():
                    self.offsets.append(offset)
        if not self.offsets:
            raise ValueError(f"No geometric solutions found in {self.path}")

    def __len__(self) -> int:
        return len(self.offsets)

    def read(self, index: int) -> Dict[str, Any]:
        if index < 0 or index >= len(self.offsets):
            raise IndexError(index)
        with self.path.open("rb") as handle:
            handle.seek(self.offsets[index])
            line = handle.readline()
        payload = json.loads(line.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Solution line {index + 1} is not a JSON object")
        return payload


class AssemblyViewer:
    def __init__(self, config: Mapping[str, Any]) -> None:
        # Tk is imported lazily so non-GUI commands and headless tests do not
        # depend on a working display server.
        import tkinter as tk
        from tkinter import messagebox, ttk

        self.tk = tk
        self.ttk = ttk
        self.messagebox = messagebox
        self.config = dict(config)
        self.source = JsonlSolutionSource(Path(self.config["input"]["solutions_file"]))
        configured_limit = self.config.get("limits", {}).get("max_solutions")
        self.solution_count = (
            len(self.source)
            if configured_limit is None
            else min(len(self.source), max(1, int(configured_limit)))
        )
        viewer = self.config["viewer"]
        assembly = self.config["assembly"]
        self.interface_sample_count = int(assembly.get("interface_sample_count", 25))
        self.polygon_arc_sample_count = int(assembly.get("polygon_arc_sample_count", 96))
        self.tolerance = float(assembly.get("mapping_tolerance", 1e-6))
        self.background = str(viewer.get("background", "#62676d"))
        self.margin = float(viewer.get("margin_pixels", 48.0))
        self.palette = tuple(
            str(value)
            for value in viewer.get(
                "piece_palette",
                ["#e76f51", "#2a9d8f", "#e9c46a", "#457b9d", "#9b5de5"],
            )
        )
        self.index = min(
            max(0, int(viewer.get("start_index", 0))), self.solution_count - 1
        )
        self.cache: OrderedDict[int, tuple[Mapping[str, Any], AssemblySolution]] = OrderedDict()
        self.cache_size = max(1, int(viewer.get("cache_size", 4)))
        self.visible_vars: Dict[str, Any] = {}
        self.current_record: Mapping[str, Any] | None = None
        self.current_assembly: AssemblySolution | None = None

        self.root = tk.Tk()
        self.root.title(str(viewer.get("title", "Formal contour assembly viewer")))
        self.root.geometry(
            f"{int(viewer.get('width', 1050))}x{int(viewer.get('height', 820))}"
        )
        self.root.minsize(640, 480)

        self.toolbar = ttk.Frame(self.root, padding=(10, 8))
        self.toolbar.pack(side=tk.TOP, fill=tk.X)
        self.previous_button = ttk.Button(
            self.toolbar, text="Previous", command=lambda: self.navigate(-1)
        )
        self.previous_button.pack(side=tk.LEFT)
        self.next_button = ttk.Button(
            self.toolbar, text="Next", command=lambda: self.navigate(1)
        )
        self.next_button.pack(side=tk.LEFT, padx=(6, 14))
        self.solution_label = ttk.Label(self.toolbar, text="")
        self.solution_label.pack(side=tk.LEFT)
        self.visibility_frame = ttk.Frame(self.toolbar)
        self.visibility_frame.pack(side=tk.RIGHT)

        self.canvas = tk.Canvas(
            self.root,
            background=self.background,
            highlightthickness=0,
            borderwidth=0,
        )
        self.canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.status = ttk.Label(self.root, padding=(10, 6), anchor="w")
        self.status.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.bind("<Configure>", lambda _event: self.redraw())
        self.root.bind("<Left>", lambda _event: self.navigate(-1))
        self.root.bind("<Right>", lambda _event: self.navigate(1))
        self.root.bind("<Home>", lambda _event: self.show_index(0))
        self.root.bind("<End>", lambda _event: self.show_index(self.solution_count - 1))
        self.show_index(self.index)

    def run(self) -> None:
        self.root.mainloop()

    def _load(self, index: int) -> tuple[Mapping[str, Any], AssemblySolution]:
        if index in self.cache:
            value = self.cache.pop(index)
            self.cache[index] = value
            return value
        record = self.source.read(index)
        assembly = assemble_geometric_solution(
            record,
            interface_sample_count=self.interface_sample_count,
            polygon_arc_sample_count=self.polygon_arc_sample_count,
            tolerance=self.tolerance,
        )
        value = (record, assembly)
        self.cache[index] = value
        while len(self.cache) > self.cache_size:
            self.cache.popitem(last=False)
        return value

    def show_index(self, index: int) -> None:
        index = max(0, min(index, self.solution_count - 1))
        try:
            record, assembly = self._load(index)
        except Exception as exc:
            self.messagebox.showerror(
                "Assembly reconstruction failed",
                f"Could not reconstruct solution {index + 1}:\n\n{exc}",
            )
            return
        self.index = index
        self.current_record = record
        self.current_assembly = assembly
        self._rebuild_visibility_controls()
        self.previous_button.configure(state=("disabled" if index == 0 else "normal"))
        self.next_button.configure(
            state=("disabled" if index == self.solution_count - 1 else "normal")
        )
        self.solution_label.configure(
            text=f"Solution {index + 1} / {self.solution_count}    {assembly.map_name}"
        )
        validation = assembly.validation
        self.status.configure(
            text=(
                f"{assembly.geometric_solution_id}   |   "
                f"mapping residual max={validation.maximum_interface_error:.3e}   |   "
                f"reference={assembly.reference_piece}"
            )
        )
        self.redraw()

    def navigate(self, delta: int) -> None:
        self.show_index(self.index + delta)

    def _rebuild_visibility_controls(self) -> None:
        for child in self.visibility_frame.winfo_children():
            child.destroy()
        self.visible_vars.clear()
        if self.current_assembly is None:
            return
        for placement in self.current_assembly.placements:
            variable = self.tk.BooleanVar(value=True)
            self.visible_vars[placement.piece] = variable
            checkbox = self.ttk.Checkbutton(
                self.visibility_frame,
                text=placement.piece,
                variable=variable,
                command=self.redraw,
            )
            checkbox.pack(side=self.tk.LEFT, padx=(8, 0))

    def _world_bounds(self) -> tuple[float, float, float, float]:
        assert self.current_assembly is not None
        arrays = [placement.polygon for placement in self.current_assembly.placements]
        points = np.concatenate(arrays)
        minimum = np.min(points, axis=0)
        maximum = np.max(points, axis=0)
        width = float(maximum[0] - minimum[0])
        height = float(maximum[1] - minimum[1])
        if width <= 1e-12:
            width = 1.0
        if height <= 1e-12:
            height = 1.0
        padding = 0.03 * max(width, height)
        return (
            float(minimum[0] - padding),
            float(minimum[1] - padding),
            float(maximum[0] + padding),
            float(maximum[1] + padding),
        )

    def _screen_coordinates(self, polygon: np.ndarray) -> list[float]:
        minimum_x, minimum_y, maximum_x, maximum_y = self._world_bounds()
        canvas_width = max(1.0, float(self.canvas.winfo_width()))
        canvas_height = max(1.0, float(self.canvas.winfo_height()))
        usable_width = max(1.0, canvas_width - 2.0 * self.margin)
        usable_height = max(1.0, canvas_height - 2.0 * self.margin)
        world_width = maximum_x - minimum_x
        world_height = maximum_y - minimum_y
        scale = min(usable_width / world_width, usable_height / world_height)
        center_x = 0.5 * (minimum_x + maximum_x)
        center_y = 0.5 * (minimum_y + maximum_y)
        output = []
        for point in polygon:
            x = 0.5 * canvas_width + scale * (float(point[0]) - center_x)
            y = 0.5 * canvas_height - scale * (float(point[1]) - center_y)
            output.extend((x, y))
        return output

    def redraw(self) -> None:
        self.canvas.delete("all")
        if self.current_assembly is None:
            return
        for index, placement in enumerate(self.current_assembly.placements):
            variable = self.visible_vars.get(placement.piece)
            if variable is not None and not bool(variable.get()):
                continue
            color = self.palette[index % len(self.palette)]
            self.canvas.create_polygon(
                self._screen_coordinates(placement.polygon),
                fill=color,
                outline="",
                width=0,
            )


def run_visualizer(config: Mapping[str, Any]) -> None:
    AssemblyViewer(config).run()
