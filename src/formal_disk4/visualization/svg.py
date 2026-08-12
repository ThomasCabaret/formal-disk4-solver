from __future__ import annotations

import html
from typing import Any, Mapping, Sequence

import numpy as np

from .assembly import AssemblySolution, assemble_geometric_solution


DEFAULT_PALETTE = (
    "#e76f51",
    "#2a9d8f",
    "#e9c46a",
    "#457b9d",
    "#9b5de5",
    "#f4a261",
    "#4cc9f0",
    "#f15bb5",
    "#90be6d",
    "#f94144",
    "#577590",
    "#f8961e",
)


def assembly_svg(
    assembly: AssemblySolution,
    *,
    width: int = 360,
    height: int = 260,
    margin: float = 14.0,
    palette: Sequence[str] = DEFAULT_PALETTE,
) -> str:
    """Render an assembled geometric solution as a self-contained SVG."""

    if not assembly.placements:
        raise ValueError("Cannot render an empty assembly")
    arrays = [placement.polygon for placement in assembly.placements]
    points = np.concatenate(arrays)
    minimum = np.min(points, axis=0)
    maximum = np.max(points, axis=0)
    world_width = max(1e-12, float(maximum[0] - minimum[0]))
    world_height = max(1e-12, float(maximum[1] - minimum[1]))
    usable_width = max(1.0, float(width) - 2.0 * margin)
    usable_height = max(1.0, float(height) - 2.0 * margin)
    scale = min(usable_width / world_width, usable_height / world_height)
    center_x = 0.5 * float(minimum[0] + maximum[0])
    center_y = 0.5 * float(minimum[1] + maximum[1])

    polygons = []
    for index, placement in enumerate(assembly.placements):
        coordinates = []
        for point in placement.polygon:
            x = 0.5 * width + scale * (float(point[0]) - center_x)
            y = 0.5 * height - scale * (float(point[1]) - center_y)
            coordinates.append(f"{x:.3f},{y:.3f}")
        polygons.append(
            '<polygon points="{}" fill="{}" stroke="#20242a" '
            'stroke-width="0.8"><title>{}</title></polygon>'.format(
                " ".join(coordinates),
                html.escape(str(palette[index % len(palette)]), quote=True),
                html.escape(placement.piece),
            )
        )
    title = html.escape(
        f"{assembly.map_name} — {assembly.formal_profile_id}"
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="{title}"><title>{title}</title>'
        '<rect width="100%" height="100%" fill="#62676d"/>'
        + "".join(polygons)
        + "</svg>"
    )


def geometric_solution_svg(
    record: Mapping[str, Any],
    *,
    width: int = 360,
    height: int = 260,
    margin: float = 14.0,
    palette: Sequence[str] = DEFAULT_PALETTE,
) -> str:
    assembly = assemble_geometric_solution(record)
    return assembly_svg(
        assembly,
        width=width,
        height=height,
        margin=margin,
        palette=palette,
    )
