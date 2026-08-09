from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from formal_disk4.maps.base import PlanarMap
from formal_disk4.maps.registry import build_map
from formal_disk4.orchestration.catalog import CaseCatalog, CaseDefinition


Point = tuple[float, float]


@dataclass(frozen=True)
class SchematicPiece:
    name: str
    points: tuple[Point, ...]
    label_position: Point
    outer_contact: str


@dataclass(frozen=True)
class CatalogSchematic:
    map_name: str
    vertex_positions: Mapping[str, Point]
    outer_cycle: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]
    pieces: tuple[SchematicPiece, ...]
    point_contacts: tuple[str, ...]


def _outer_cycle(planar_map: PlanarMap) -> tuple[str, ...]:
    outer_vertices = {
        vertex.name for vertex in planar_map.vertices if vertex.kind == "outer"
    }
    directed: dict[str, str] = {}
    directed_valid = True
    undirected: dict[str, set[str]] = {name: set() for name in outer_vertices}
    for interface in planar_map.outer_interfaces():
        view = interface.views[0]
        if view.start_vertex in directed:
            directed_valid = False
        directed[view.start_vertex] = view.end_vertex
        undirected[view.start_vertex].add(view.end_vertex)
        undirected[view.end_vertex].add(view.start_vertex)

    if directed_valid and set(directed) == outer_vertices:
        start = min(outer_vertices)
        order = []
        current = start
        while current not in order:
            order.append(current)
            current = directed.get(current, "")
            if not current:
                break
        if current == start and set(order) == outer_vertices:
            return tuple(order)

    if not outer_vertices or any(len(undirected[name]) != 2 for name in outer_vertices):
        raise ValueError(
            f"Map {planar_map.name!r} does not expose one simple outer boundary cycle"
        )
    start = min(outer_vertices)
    order = [start]
    previous = None
    current = start
    while True:
        choices = sorted(undirected[current] - ({previous} if previous else set()))
        if not choices:
            raise ValueError(f"Open outer boundary in map {planar_map.name!r}")
        following = choices[0]
        if following == start:
            break
        if following in order:
            raise ValueError(f"Repeated outer boundary vertex in {planar_map.name!r}")
        order.append(following)
        previous, current = current, following
    if set(order) != outer_vertices:
        raise ValueError(f"Disconnected outer boundary in map {planar_map.name!r}")
    return tuple(order)


def _skeleton_edges(planar_map: PlanarMap) -> tuple[tuple[str, str], ...]:
    edges = set()
    for piece in planar_map.pieces:
        contour = piece.contour_vertices
        for index, start in enumerate(contour):
            end = contour[(index + 1) % len(contour)]
            edges.add(tuple(sorted((start, end))))
    return tuple(sorted(edges))


def _harmonic_positions(
    planar_map: PlanarMap,
    outer_cycle: Sequence[str],
    edges: Sequence[tuple[str, str]],
) -> dict[str, Point]:
    positions: dict[str, Point] = {}
    count = len(outer_cycle)
    if count < 3:
        raise ValueError(f"Map {planar_map.name!r} needs at least three outer vertices")
    for index, vertex in enumerate(outer_cycle):
        angle = math.pi / 2.0 - 2.0 * math.pi * index / count
        positions[vertex] = (math.cos(angle), math.sin(angle))

    neighbours: dict[str, set[str]] = {
        vertex.name: set() for vertex in planar_map.vertices
    }
    for left, right in edges:
        neighbours[left].add(right)
        neighbours[right].add(left)
    internal = [
        vertex.name for vertex in planar_map.vertices if vertex.name not in positions
    ]
    if not internal:
        return positions
    internal_index = {name: index for index, name in enumerate(internal)}
    matrix = np.zeros((len(internal), len(internal)), dtype=float)
    target_x = np.zeros(len(internal), dtype=float)
    target_y = np.zeros(len(internal), dtype=float)
    for name, row in internal_index.items():
        adjacent = neighbours[name]
        if not adjacent:
            raise ValueError(f"Isolated schematic vertex {name!r}")
        matrix[row, row] = 1.0
        weight = 1.0 / len(adjacent)
        for neighbour in adjacent:
            if neighbour in internal_index:
                matrix[row, internal_index[neighbour]] -= weight
            else:
                x, y = positions[neighbour]
                target_x[row] += weight * x
                target_y[row] += weight * y
    try:
        solved_x = np.linalg.solve(matrix, target_x)
        solved_y = np.linalg.solve(matrix, target_y)
    except np.linalg.LinAlgError as exc:
        raise ValueError(
            f"Cannot construct a harmonic schematic for {planar_map.name!r}"
        ) from exc
    for name, index in internal_index.items():
        positions[name] = (float(solved_x[index]), float(solved_y[index]))

    # A degree-two vertex can intentionally mark a bend on an otherwise
    # topological digon.  Pure barycentric coordinates put it exactly on the
    # chord between its neighbours and visually collapse both adjacent faces.
    # Give only such collinear subdivision vertices a small, deterministic
    # normal offset; all incidences and shared interfaces remain unchanged.
    for name in sorted(internal):
        if len(neighbours[name]) != 2:
            continue
        adjacent = tuple(neighbours[name])
        first = positions[adjacent[0]]
        second = positions[adjacent[1]]
        point = positions[name]
        dx = second[0] - first[0]
        dy = second[1] - first[1]
        length = math.hypot(dx, dy)
        if length <= 1e-10:
            continue
        distance_cross = abs(
            (point[0] - first[0]) * dy - (point[1] - first[1]) * dx
        )
        if distance_cross > 1e-8 * length:
            continue
        incident_piece = next(
            piece for piece in planar_map.pieces if name in piece.contour_vertices
        )
        contour = incident_piece.contour_vertices
        vertex_index = contour.index(name)
        previous = positions[contour[vertex_index - 1]]
        following = positions[contour[(vertex_index + 1) % len(contour)]]
        oriented_dx = following[0] - previous[0]
        oriented_dy = following[1] - previous[1]
        oriented_length = math.hypot(oriented_dx, oriented_dy)
        if oriented_length <= 1e-10:
            continue
        normal = (-oriented_dy / oriented_length, oriented_dx / oriented_length)
        offset = 0.12 * length
        candidate = (point[0] + offset * normal[0], point[1] + offset * normal[1])
        if math.hypot(*candidate) >= 0.98:
            candidate = (point[0] - offset * normal[0], point[1] - offset * normal[1])
        positions[name] = candidate
    return positions


def _polygon_centroid(points: Sequence[Point]) -> Point:
    twice_area = 0.0
    x_sum = 0.0
    y_sum = 0.0
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        cross = x1 * y2 - x2 * y1
        twice_area += cross
        x_sum += (x1 + x2) * cross
        y_sum += (y1 + y2) * cross
    if abs(twice_area) <= 1e-10:
        return (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )
    return (x_sum / (3.0 * twice_area), y_sum / (3.0 * twice_area))


def _piece_points(
    contour: Sequence[str],
    positions: Mapping[str, Point],
    outer_edges: set[frozenset[str]],
) -> tuple[Point, ...]:
    points: list[Point] = []
    for index, start in enumerate(contour):
        end = contour[(index + 1) % len(contour)]
        start_point = positions[start]
        points.append(start_point)
        if frozenset((start, end)) not in outer_edges:
            continue
        start_angle = math.atan2(start_point[1], start_point[0])
        end_point = positions[end]
        end_angle = math.atan2(end_point[1], end_point[0])
        delta = (end_angle - start_angle + math.pi) % (2.0 * math.pi) - math.pi
        for step in range(1, 8):
            angle = start_angle + delta * step / 8.0
            points.append((math.cos(angle), math.sin(angle)))
    return tuple(points)


def polygon_area(points: Sequence[Point]) -> float:
    return 0.5 * abs(
        sum(
            x1 * points[(index + 1) % len(points)][1]
            - points[(index + 1) % len(points)][0] * y1
            for index, (x1, y1) in enumerate(points)
        )
    )


def build_catalog_schematic(planar_map: PlanarMap) -> CatalogSchematic:
    """Create a deterministic non-congruent polygonal view of a catalog map."""

    planar_map.validate()
    outer_cycle = _outer_cycle(planar_map)
    edges = _skeleton_edges(planar_map)
    positions = _harmonic_positions(planar_map, outer_cycle, edges)
    outer_edges = {
        frozenset(
            (interface.views[0].start_vertex, interface.views[0].end_vertex)
        )
        for interface in planar_map.outer_interfaces()
    }
    pieces = []
    for piece in planar_map.pieces:
        points = _piece_points(piece.contour_vertices, positions, outer_edges)
        if polygon_area(points) <= 1e-8:
            raise ValueError(
                f"Schematic layout collapses piece {piece.name!r} in {planar_map.name!r}"
            )
        pieces.append(
            SchematicPiece(
                piece.name,
                points,
                _polygon_centroid(points),
                str(piece.outer_boundary_contact),
            )
        )
    point_contacts = tuple(
        sorted(
            {
                vertex
                for piece in planar_map.pieces
                if piece.outer_boundary_contact == "point"
                for vertex in piece.contour_vertices
                if planar_map.vertex_map()[vertex].kind == "outer"
            }
        )
    )
    return CatalogSchematic(
        planar_map.name,
        positions,
        outer_cycle,
        edges,
        tuple(pieces),
        point_contacts,
    )


def _imposed_symmetry(case: CaseDefinition) -> str:
    enumeration = dict(case.stage_overrides.get("search", {}).get("enumeration", {}))
    for key, label in (
        ("cyclic_equivariance", "pointwise"),
        ("cyclic_shift_equivariance", "cyclic shift"),
    ):
        config = dict(enumeration.get(key, {}))
        if bool(config.get("enabled", False)):
            return f"{config.get('automorphism', 'rotation_1')} ({label})"
    return "none imposed"


class CatalogDiagramWindow:
    """Tk catalog browser whose drawings come from the production map data."""

    ARC_COLOR = "#79b8d1"
    POINT_COLOR = "#efc35a"
    INTERNAL_COLOR = "#e68a63"
    BACKGROUND = "#f0f1f2"
    DISK_COLOR = "#ffffff"
    OUTLINE = "#25282a"

    def __init__(
        self,
        parent: Any,
        catalog: CaseCatalog,
        *,
        initial_case_id: str | None = None,
    ) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.catalog = catalog
        self.cache: dict[str, CatalogSchematic] = {}
        self.current_case: CaseDefinition | None = None
        self.window = tk.Toplevel(parent)
        self.window.title("Formal Disk4 structural catalog")
        self.window.geometry("1240x820")
        self.window.minsize(820, 560)
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)

        pane = ttk.Panedwindow(self.window, orient=tk.HORIZONTAL)
        pane.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        left = ttk.Frame(pane, padding=6)
        right = ttk.Frame(pane, padding=6)
        pane.add(left, weight=1)
        pane.add(right, weight=3)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)

        ttk.Label(left, text="Catalog cases", font=("TkDefaultFont", 11, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.filter_var = tk.StringVar()
        entry = ttk.Entry(left, textvariable=self.filter_var)
        entry.grid(row=1, column=0, sticky="ew", pady=(6, 6))
        entry.bind("<KeyRelease>", lambda _event: self._populate_tree())
        self.tree = ttk.Treeview(
            left,
            columns=("map",),
            show="tree headings",
            selectmode="browse",
        )
        self.tree.heading("#0", text="Case")
        self.tree.heading("map", text="Map")
        self.tree.column("#0", width=260, stretch=True)
        self.tree.column("map", width=180, stretch=False)
        scroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=2, column=0, sticky="nsew")
        scroll.grid(row=2, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._tree_selected)

        header = ttk.Frame(right)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Button(header, text="Previous", command=lambda: self._navigate(-1)).grid(
            row=0, column=0
        )
        self.title_var = tk.StringVar()
        ttk.Label(
            header,
            textvariable=self.title_var,
            font=("TkDefaultFont", 12, "bold"),
            anchor="center",
        ).grid(row=0, column=1, sticky="ew", padx=10)
        ttk.Button(header, text="Next", command=lambda: self._navigate(1)).grid(
            row=0, column=2
        )
        self.description_var = tk.StringVar()
        ttk.Label(
            right,
            textvariable=self.description_var,
            wraplength=760,
            justify="left",
        ).grid(row=1, column=0, sticky="ew", pady=(7, 0))
        self.detail_var = tk.StringVar()
        ttk.Label(right, textvariable=self.detail_var).grid(
            row=2, column=0, sticky="w", pady=(5, 6)
        )
        self.canvas = tk.Canvas(
            right,
            background=self.BACKGROUND,
            highlightthickness=0,
            borderwidth=0,
        )
        self.canvas.grid(row=3, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda _event: self._redraw())
        ttk.Label(
            right,
            text=(
                "Blue: boundary arc   ·   Gold: boundary point   ·   "
                "Orange: internal piece   ·   Schematics do not assert congruence"
            ),
        ).grid(row=4, column=0, sticky="w", pady=(6, 0))

        self._populate_tree(preferred=initial_case_id)
        self.window.bind("<Left>", lambda _event: self._navigate(-1))
        self.window.bind("<Right>", lambda _event: self._navigate(1))

    def _visible_cases(self) -> tuple[CaseDefinition, ...]:
        query = self.filter_var.get().strip().casefold()
        return tuple(
            case
            for case in self.catalog.cases
            if not query
            or query in case.case_id.casefold()
            or query in case.label.casefold()
            or query in case.map_name.casefold()
            or query in case.group.casefold()
        )

    def _populate_tree(self, preferred: str | None = None) -> None:
        current = preferred or (self.current_case.case_id if self.current_case else None)
        self.tree.delete(*self.tree.get_children(""))
        visible = self._visible_cases()
        for group in self.catalog.groups():
            cases = [case for case in visible if case.group == group]
            if not cases:
                continue
            group_id = self.tree.insert("", "end", text=group, open=True)
            for case in cases:
                self.tree.insert(
                    group_id,
                    "end",
                    iid="diagram:" + case.case_id,
                    text=case.label,
                    values=(case.map_name,),
                )
        target = "diagram:" + current if current else ""
        if target and self.tree.exists(target):
            self.tree.selection_set(target)
            self.tree.focus(target)
            self.tree.see(target)
            self._show_case(current)
        elif visible:
            self.tree.selection_set("diagram:" + visible[0].case_id)
            self.tree.focus("diagram:" + visible[0].case_id)
            self._show_case(visible[0].case_id)
        else:
            self.current_case = None
            self.title_var.set("No matching case")
            self.description_var.set("")
            self.detail_var.set("")
            self._redraw()

    def _tree_selected(self, _event: Any) -> None:
        selected = self.tree.selection()
        if selected and selected[0].startswith("diagram:"):
            self._show_case(selected[0][8:])

    def _show_case(self, case_id: str) -> None:
        case = self.catalog.get(case_id)
        try:
            schematic = self.cache.get(case.map_name)
            if schematic is None:
                schematic = build_catalog_schematic(build_map(case.map_name))
                self.cache[case.map_name] = schematic
        except Exception as exc:
            self.current_case = case
            self.title_var.set(case.label)
            self.description_var.set(case.description)
            self.detail_var.set(f"Diagram unavailable: {type(exc).__name__}: {exc}")
            self._redraw(error=str(exc))
            return
        self.current_case = case
        self.title_var.set(case.label)
        self.description_var.set(case.description)
        self.detail_var.set(
            f"{case.case_id}   ·   map {case.map_name}   ·   "
            f"{len(schematic.pieces)} pieces   ·   imposed symmetry: {_imposed_symmetry(case)}"
        )
        self._redraw()

    def _navigate(self, delta: int) -> None:
        visible = self._visible_cases()
        if not visible:
            return
        current_id = self.current_case.case_id if self.current_case else visible[0].case_id
        index = next(
            (position for position, case in enumerate(visible) if case.case_id == current_id),
            0,
        )
        target = visible[max(0, min(len(visible) - 1, index + delta))]
        item = "diagram:" + target.case_id
        if self.tree.exists(item):
            self.tree.selection_set(item)
            self.tree.focus(item)
            self.tree.see(item)
        self._show_case(target.case_id)

    def _screen(self, point: Point) -> Point:
        width = max(1.0, float(self.canvas.winfo_width()))
        height = max(1.0, float(self.canvas.winfo_height()))
        scale = 0.43 * min(width, height)
        return (0.5 * width + scale * point[0], 0.5 * height - scale * point[1])

    def _redraw(self, *, error: str | None = None) -> None:
        self.canvas.delete("all")
        if error or self.current_case is None:
            self.canvas.create_text(
                max(1, self.canvas.winfo_width()) / 2,
                max(1, self.canvas.winfo_height()) / 2,
                text=error or "No catalog case selected",
                fill=self.OUTLINE,
                width=max(200, self.canvas.winfo_width() - 80),
                justify="center",
            )
            return
        schematic = self.cache.get(self.current_case.map_name)
        if schematic is None:
            return
        center = self._screen((0.0, 0.0))
        radius = 0.43 * min(
            max(1.0, float(self.canvas.winfo_width())),
            max(1.0, float(self.canvas.winfo_height())),
        )
        self.canvas.create_oval(
            center[0] - radius,
            center[1] - radius,
            center[0] + radius,
            center[1] + radius,
            fill=self.DISK_COLOR,
            outline="",
        )
        colors = {
            "arc": self.ARC_COLOR,
            "point": self.POINT_COLOR,
            "none": self.INTERNAL_COLOR,
        }
        for piece in schematic.pieces:
            coordinates = [value for point in piece.points for value in self._screen(point)]
            self.canvas.create_polygon(
                coordinates,
                fill=colors.get(piece.outer_contact, self.INTERNAL_COLOR),
                outline="",
            )
        outer_edges = {
            frozenset(
                (
                    schematic.outer_cycle[index],
                    schematic.outer_cycle[(index + 1) % len(schematic.outer_cycle)],
                )
            )
            for index in range(len(schematic.outer_cycle))
        }
        for left, right in schematic.edges:
            if frozenset((left, right)) in outer_edges:
                continue
            start = self._screen(schematic.vertex_positions[left])
            end = self._screen(schematic.vertex_positions[right])
            self.canvas.create_line(*start, *end, fill=self.OUTLINE, width=1.4)
        self.canvas.create_oval(
            center[0] - radius,
            center[1] - radius,
            center[0] + radius,
            center[1] + radius,
            outline=self.OUTLINE,
            width=2.5,
        )
        for vertex in schematic.point_contacts:
            x, y = self._screen(schematic.vertex_positions[vertex])
            self.canvas.create_oval(
                x - 4,
                y - 4,
                x + 4,
                y + 4,
                fill=self.DISK_COLOR,
                outline=self.OUTLINE,
                width=1.5,
            )
        for piece in schematic.pieces:
            x, y = self._screen(piece.label_position)
            self.canvas.create_text(
                x,
                y,
                text=piece.name,
                fill=self.OUTLINE,
                font=("TkDefaultFont", 9, "bold"),
            )
