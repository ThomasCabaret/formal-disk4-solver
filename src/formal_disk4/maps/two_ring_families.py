from __future__ import annotations

from typing import Callable, Tuple

from .base import (
    InterfaceSpec,
    InterfaceView,
    MapAutomorphism,
    PieceSpec,
    PlanarMap,
    VertexSpec,
)


def _outer_piece(index: int, size: int) -> str:
    return f"E{index % size + 1}"


def _inner_piece(index: int, size: int) -> str:
    return f"I{index % size + 1}"


def _vertex(prefix: str, index: int, size: int) -> str:
    return f"{prefix}{index % size + 1}"


def _rotation_automorphisms(
    size: int,
    vertex_prefixes: tuple[str, ...],
    *,
    fixed_vertices: tuple[str, ...] = ("Z",),
) -> tuple[MapAutomorphism, ...]:
    automorphisms: list[MapAutomorphism] = []
    for shift in range(size):
        piece_map: list[tuple[str, str]] = []
        vertex_map: list[tuple[str, str]] = [(name, name) for name in fixed_vertices]
        for index in range(size):
            piece_map.append(
                (_outer_piece(index, size), _outer_piece(index + shift, size))
            )
            piece_map.append(
                (_inner_piece(index, size), _inner_piece(index + shift, size))
            )
            for prefix in vertex_prefixes:
                vertex_map.append(
                    (_vertex(prefix, index, size), _vertex(prefix, index + shift, size))
                )
        automorphisms.append(
            MapAutomorphism(f"rotation_{shift}", tuple(piece_map), tuple(vertex_map))
        )
    return tuple(automorphisms)


def build_double_cycle_offset_map(size: int) -> PlanarMap:
    """Build the antiprism two-ring family with cross offsets {0, 1}."""

    if size < 3:
        raise ValueError("A two-ring map requires size >= 3")

    outer_pieces = tuple(
        PieceSpec(
            _outer_piece(index, size),
            (
                _vertex("A", index, size),
                _vertex("A", index + 1, size),
                _vertex("U", index, size),
                _vertex("V", index, size),
                _vertex("U", index - 1, size),
            ),
            True,
            "arc",
        )
        for index in range(size)
    )
    inner_pieces = tuple(
        PieceSpec(
            _inner_piece(index, size),
            (
                _vertex("U", index - 1, size),
                _vertex("V", index, size),
                "Z",
                _vertex("V", index - 1, size),
            ),
            False,
            "none",
        )
        for index in range(size)
    )

    outer_vertices = tuple(
        VertexSpec(
            _vertex("A", index, size),
            "outer",
            (_outer_piece(index - 1, size), _outer_piece(index, size)),
            1.0,
        )
        for index in range(size)
    )
    upper_triangles = tuple(
        VertexSpec(
            _vertex("U", index, size),
            "interior",
            (
                _outer_piece(index, size),
                _outer_piece(index + 1, size),
                _inner_piece(index + 1, size),
            ),
            2.0,
        )
        for index in range(size)
    )
    lower_triangles = tuple(
        VertexSpec(
            _vertex("V", index, size),
            "interior",
            (
                _outer_piece(index, size),
                _inner_piece(index, size),
                _inner_piece(index + 1, size),
            ),
            2.0,
        )
        for index in range(size)
    )
    center = VertexSpec(
        "Z",
        "interior",
        tuple(_inner_piece(index, size) for index in range(size)),
        2.0,
    )

    outer_cycle = tuple(
        InterfaceSpec(
            f"{_outer_piece(index, size)}-{_outer_piece(index + 1, size)}",
            _outer_piece(index, size),
            _outer_piece(index + 1, size),
            (
                InterfaceView(
                    _outer_piece(index, size),
                    _vertex("A", index + 1, size),
                    _vertex("U", index, size),
                ),
                InterfaceView(
                    _outer_piece(index + 1, size),
                    _vertex("U", index, size),
                    _vertex("A", index + 1, size),
                ),
            ),
        )
        for index in range(size)
    )
    cross_same = tuple(
        InterfaceSpec(
            f"{_outer_piece(index, size)}-{_inner_piece(index, size)}",
            _outer_piece(index, size),
            _inner_piece(index, size),
            (
                InterfaceView(
                    _outer_piece(index, size),
                    _vertex("V", index, size),
                    _vertex("U", index - 1, size),
                ),
                InterfaceView(
                    _inner_piece(index, size),
                    _vertex("U", index - 1, size),
                    _vertex("V", index, size),
                ),
            ),
        )
        for index in range(size)
    )
    cross_next = tuple(
        InterfaceSpec(
            f"{_outer_piece(index, size)}-{_inner_piece(index + 1, size)}",
            _outer_piece(index, size),
            _inner_piece(index + 1, size),
            (
                InterfaceView(
                    _outer_piece(index, size),
                    _vertex("U", index, size),
                    _vertex("V", index, size),
                ),
                InterfaceView(
                    _inner_piece(index + 1, size),
                    _vertex("V", index, size),
                    _vertex("U", index, size),
                ),
            ),
        )
        for index in range(size)
    )
    inner_cycle = tuple(
        InterfaceSpec(
            f"{_inner_piece(index, size)}-{_inner_piece(index + 1, size)}",
            _inner_piece(index, size),
            _inner_piece(index + 1, size),
            (
                InterfaceView(
                    _inner_piece(index, size),
                    _vertex("V", index, size),
                    "Z",
                ),
                InterfaceView(
                    _inner_piece(index + 1, size),
                    "Z",
                    _vertex("V", index, size),
                ),
            ),
        )
        for index in range(size)
    )
    outer_arcs = tuple(
        InterfaceSpec(
            f"outer-{_outer_piece(index, size)}",
            _outer_piece(index, size),
            None,
            (
                InterfaceView(
                    _outer_piece(index, size),
                    _vertex("A", index, size),
                    _vertex("A", index + 1, size),
                ),
            ),
            is_outer=True,
        )
        for index in range(size)
    )

    result = PlanarMap(
        name=f"double-cycle-offset-{size}",
        pieces=outer_pieces + inner_pieces,
        vertices=outer_vertices + upper_triangles + lower_triangles + (center,),
        interfaces=outer_cycle + cross_same + cross_next + inner_cycle + outer_arcs,
        automorphisms=_rotation_automorphisms(size, ("A", "U", "V")),
        reference_piece=_inner_piece(0, size),
    )
    result.validate()
    return result


def build_inner_cycle_boundary_points_map(size: int) -> PlanarMap:
    """Build the open outer-ring family with inner tiles reaching the boundary."""

    if size < 3:
        raise ValueError("A two-ring map requires size >= 3")

    outer_pieces = tuple(
        PieceSpec(
            _outer_piece(index, size),
            (
                _vertex("B", index, size),
                _vertex("B", index + 1, size),
                _vertex("V", index, size),
            ),
            True,
            "arc",
        )
        for index in range(size)
    )
    inner_pieces = tuple(
        PieceSpec(
            _inner_piece(index, size),
            (
                _vertex("B", index, size),
                _vertex("V", index, size),
                "Z",
                _vertex("V", index - 1, size),
            ),
            True,
            "point",
        )
        for index in range(size)
    )

    boundary_vertices = tuple(
        VertexSpec(
            _vertex("B", index, size),
            "outer",
            (
                _outer_piece(index - 1, size),
                _outer_piece(index, size),
                _inner_piece(index, size),
            ),
            1.0,
        )
        for index in range(size)
    )
    ring_vertices = tuple(
        VertexSpec(
            _vertex("V", index, size),
            "interior",
            (
                _outer_piece(index, size),
                _inner_piece(index, size),
                _inner_piece(index + 1, size),
            ),
            2.0,
        )
        for index in range(size)
    )
    center = VertexSpec(
        "Z",
        "interior",
        tuple(_inner_piece(index, size) for index in range(size)),
        2.0,
    )

    cross_same = tuple(
        InterfaceSpec(
            f"{_outer_piece(index, size)}-{_inner_piece(index, size)}",
            _outer_piece(index, size),
            _inner_piece(index, size),
            (
                InterfaceView(
                    _outer_piece(index, size),
                    _vertex("V", index, size),
                    _vertex("B", index, size),
                ),
                InterfaceView(
                    _inner_piece(index, size),
                    _vertex("B", index, size),
                    _vertex("V", index, size),
                ),
            ),
        )
        for index in range(size)
    )
    cross_next = tuple(
        InterfaceSpec(
            f"{_outer_piece(index, size)}-{_inner_piece(index + 1, size)}",
            _outer_piece(index, size),
            _inner_piece(index + 1, size),
            (
                InterfaceView(
                    _outer_piece(index, size),
                    _vertex("B", index + 1, size),
                    _vertex("V", index, size),
                ),
                InterfaceView(
                    _inner_piece(index + 1, size),
                    _vertex("V", index, size),
                    _vertex("B", index + 1, size),
                ),
            ),
        )
        for index in range(size)
    )
    inner_cycle = tuple(
        InterfaceSpec(
            f"{_inner_piece(index, size)}-{_inner_piece(index + 1, size)}",
            _inner_piece(index, size),
            _inner_piece(index + 1, size),
            (
                InterfaceView(
                    _inner_piece(index, size),
                    _vertex("V", index, size),
                    "Z",
                ),
                InterfaceView(
                    _inner_piece(index + 1, size),
                    "Z",
                    _vertex("V", index, size),
                ),
            ),
        )
        for index in range(size)
    )
    outer_arcs = tuple(
        InterfaceSpec(
            f"outer-{_outer_piece(index, size)}",
            _outer_piece(index, size),
            None,
            (
                InterfaceView(
                    _outer_piece(index, size),
                    _vertex("B", index, size),
                    _vertex("B", index + 1, size),
                ),
            ),
            is_outer=True,
        )
        for index in range(size)
    )

    result = PlanarMap(
        name=f"inner-cycle-boundary-points-{size}",
        pieces=outer_pieces + inner_pieces,
        vertices=boundary_vertices + ring_vertices + (center,),
        interfaces=cross_same + cross_next + inner_cycle + outer_arcs,
        automorphisms=_rotation_automorphisms(size, ("B", "V")),
        reference_piece=_outer_piece(0, size),
    )
    result.validate()
    return result


def build_outer_cycle_center_points_map(size: int) -> PlanarMap:
    """Build the inverse open-ring family; every tile meets the central vertex.

    The inner tiles are topological digons.  The model marks one extra point W_i
    on the E_i-I_i contact so every contour is represented by at least three
    vertices without changing the positive-contact graph.
    """

    if size < 3:
        raise ValueError("A two-ring map requires size >= 3")

    outer_pieces = tuple(
        PieceSpec(
            _outer_piece(index, size),
            (
                _vertex("A", index, size),
                _vertex("A", index + 1, size),
                _vertex("V", index + 1, size),
                "Z",
                _vertex("W", index, size),
                _vertex("V", index, size),
            ),
            True,
            "arc",
        )
        for index in range(size)
    )
    inner_pieces = tuple(
        PieceSpec(
            _inner_piece(index, size),
            (
                _vertex("V", index, size),
                _vertex("W", index, size),
                "Z",
            ),
            False,
            "none",
        )
        for index in range(size)
    )

    outer_vertices = tuple(
        VertexSpec(
            _vertex("A", index, size),
            "outer",
            (_outer_piece(index - 1, size), _outer_piece(index, size)),
            1.0,
        )
        for index in range(size)
    )
    ring_vertices = tuple(
        VertexSpec(
            _vertex("V", index, size),
            "interior",
            (
                _outer_piece(index - 1, size),
                _outer_piece(index, size),
                _inner_piece(index, size),
            ),
            2.0,
        )
        for index in range(size)
    )
    marked_vertices = tuple(
        VertexSpec(
            _vertex("W", index, size),
            "interior",
            (_outer_piece(index, size), _inner_piece(index, size)),
            2.0,
        )
        for index in range(size)
    )
    center = VertexSpec(
        "Z",
        "interior",
        tuple(
            name
            for index in range(size)
            for name in (_outer_piece(index, size), _inner_piece(index, size))
        ),
        2.0,
    )

    outer_cycle = tuple(
        InterfaceSpec(
            f"{_outer_piece(index, size)}-{_outer_piece(index + 1, size)}",
            _outer_piece(index, size),
            _outer_piece(index + 1, size),
            (
                InterfaceView(
                    _outer_piece(index, size),
                    _vertex("A", index + 1, size),
                    _vertex("V", index + 1, size),
                ),
                InterfaceView(
                    _outer_piece(index + 1, size),
                    _vertex("V", index + 1, size),
                    _vertex("A", index + 1, size),
                ),
            ),
        )
        for index in range(size)
    )
    cross_next = tuple(
        InterfaceSpec(
            f"{_outer_piece(index, size)}-{_inner_piece(index + 1, size)}",
            _outer_piece(index, size),
            _inner_piece(index + 1, size),
            (
                InterfaceView(
                    _outer_piece(index, size),
                    _vertex("V", index + 1, size),
                    "Z",
                ),
                InterfaceView(
                    _inner_piece(index + 1, size),
                    "Z",
                    _vertex("V", index + 1, size),
                ),
            ),
        )
        for index in range(size)
    )
    cross_same_a = tuple(
        InterfaceSpec(
            f"{_outer_piece(index, size)}-{_inner_piece(index, size)}-a",
            _outer_piece(index, size),
            _inner_piece(index, size),
            (
                InterfaceView(
                    _outer_piece(index, size),
                    "Z",
                    _vertex("W", index, size),
                ),
                InterfaceView(
                    _inner_piece(index, size),
                    _vertex("W", index, size),
                    "Z",
                ),
            ),
        )
        for index in range(size)
    )
    cross_same_b = tuple(
        InterfaceSpec(
            f"{_outer_piece(index, size)}-{_inner_piece(index, size)}-b",
            _outer_piece(index, size),
            _inner_piece(index, size),
            (
                InterfaceView(
                    _outer_piece(index, size),
                    _vertex("W", index, size),
                    _vertex("V", index, size),
                ),
                InterfaceView(
                    _inner_piece(index, size),
                    _vertex("V", index, size),
                    _vertex("W", index, size),
                ),
            ),
        )
        for index in range(size)
    )
    outer_arcs = tuple(
        InterfaceSpec(
            f"outer-{_outer_piece(index, size)}",
            _outer_piece(index, size),
            None,
            (
                InterfaceView(
                    _outer_piece(index, size),
                    _vertex("A", index, size),
                    _vertex("A", index + 1, size),
                ),
            ),
            is_outer=True,
        )
        for index in range(size)
    )

    result = PlanarMap(
        name=f"outer-cycle-center-points-{size}",
        pieces=outer_pieces + inner_pieces,
        vertices=outer_vertices + ring_vertices + marked_vertices + (center,),
        interfaces=(
            outer_cycle + cross_next + cross_same_a + cross_same_b + outer_arcs
        ),
        automorphisms=_rotation_automorphisms(size, ("A", "V", "W")),
        reference_piece=_inner_piece(0, size),
    )
    result.validate()
    return result

