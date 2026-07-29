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


def _outer_vertex(index: int, size: int) -> str:
    """Boundary junction between E[index-1] and E[index]."""

    return f"A{index % size + 1}"


def _ring_vertex(index: int, size: int) -> str:
    """Four-way junction E_i,E_{i+1},I_i,I_{i+1}."""

    return f"V{index % size + 1}"


def _dihedral_index_maps(size: int) -> Tuple[Tuple[str, Callable[[int], int]], ...]:
    transforms: list[tuple[str, Callable[[int], int]]] = []
    for shift in range(size):
        transforms.append(
            (
                f"rotation_{shift}",
                lambda index, shift=shift: (index + shift) % size,
            )
        )
    for shift in range(size):
        transforms.append(
            (
                f"reflection_{shift}",
                lambda index, shift=shift: (shift - index) % size,
            )
        )
    return tuple(transforms)


def build_double_cycle_map(size: int) -> PlanarMap:
    """Build two N-cycles joined by matching radial contacts.

    E_i touches E_(i-1), E_(i+1), I_i, and the disk boundary.
    I_i touches I_(i-1), I_(i+1), and E_i.  The inner pieces all meet at
    the central map vertex Z, but no tile is declared to contain Z strictly.
    """

    if size < 3:
        raise ValueError("A double-cycle map requires size >= 3")

    outer_pieces = tuple(
        PieceSpec(
            _outer_piece(index, size),
            (
                _outer_vertex(index, size),
                _outer_vertex(index + 1, size),
                _ring_vertex(index, size),
                _ring_vertex(index - 1, size),
            ),
            True,
            "arc",
        )
        for index in range(size)
    )
    inner_pieces = tuple(
        PieceSpec(
            _inner_piece(index, size),
            (_ring_vertex(index - 1, size), _ring_vertex(index, size), "Z"),
            False,
            "none",
        )
        for index in range(size)
    )

    outer_vertices = tuple(
        VertexSpec(
            _outer_vertex(index, size),
            "outer",
            (_outer_piece(index - 1, size), _outer_piece(index, size)),
            1.0,
        )
        for index in range(size)
    )
    ring_vertices = tuple(
        VertexSpec(
            _ring_vertex(index, size),
            "interior",
            (
                _outer_piece(index, size),
                _outer_piece(index + 1, size),
                _inner_piece(index, size),
                _inner_piece(index + 1, size),
            ),
            2.0,
        )
        for index in range(size)
    )
    center_vertex = VertexSpec(
        "Z",
        "interior",
        tuple(_inner_piece(index, size) for index in range(size)),
        2.0,
    )

    outer_cycle_interfaces = tuple(
        InterfaceSpec(
            f"{_outer_piece(index, size)}-{_outer_piece(index + 1, size)}",
            _outer_piece(index, size),
            _outer_piece(index + 1, size),
            (
                InterfaceView(
                    _outer_piece(index, size),
                    _outer_vertex(index + 1, size),
                    _ring_vertex(index, size),
                ),
                InterfaceView(
                    _outer_piece(index + 1, size),
                    _ring_vertex(index, size),
                    _outer_vertex(index + 1, size),
                ),
            ),
        )
        for index in range(size)
    )
    radial_interfaces = tuple(
        InterfaceSpec(
            f"{_outer_piece(index, size)}-{_inner_piece(index, size)}",
            _outer_piece(index, size),
            _inner_piece(index, size),
            (
                InterfaceView(
                    _outer_piece(index, size),
                    _ring_vertex(index, size),
                    _ring_vertex(index - 1, size),
                ),
                InterfaceView(
                    _inner_piece(index, size),
                    _ring_vertex(index - 1, size),
                    _ring_vertex(index, size),
                ),
            ),
        )
        for index in range(size)
    )
    inner_cycle_interfaces = tuple(
        InterfaceSpec(
            f"{_inner_piece(index, size)}-{_inner_piece(index + 1, size)}",
            _inner_piece(index, size),
            _inner_piece(index + 1, size),
            (
                InterfaceView(
                    _inner_piece(index, size),
                    _ring_vertex(index, size),
                    "Z",
                ),
                InterfaceView(
                    _inner_piece(index + 1, size),
                    "Z",
                    _ring_vertex(index, size),
                ),
            ),
        )
        for index in range(size)
    )
    exterior_interfaces = tuple(
        InterfaceSpec(
            f"outer-{_outer_piece(index, size)}",
            _outer_piece(index, size),
            None,
            (
                InterfaceView(
                    _outer_piece(index, size),
                    _outer_vertex(index, size),
                    _outer_vertex(index + 1, size),
                ),
            ),
            is_outer=True,
        )
        for index in range(size)
    )

    automorphisms = []
    for name, index_map in _dihedral_index_maps(size):
        piece_map = []
        for index in range(size):
            piece_map.append(
                (_outer_piece(index, size), _outer_piece(index_map(index), size))
            )
            piece_map.append(
                (_inner_piece(index, size), _inner_piece(index_map(index), size))
            )
        vertex_map = [("Z", "Z")]
        preserves_index_direction = (index_map(1) - index_map(0)) % size == 1
        for index in range(size):
            outer_target = (
                index_map(index)
                if preserves_index_direction
                else index_map(index) + 1
            )
            ring_target = (
                index_map(index)
                if preserves_index_direction
                else index_map(index + 1)
            )
            vertex_map.append(
                (_outer_vertex(index, size), _outer_vertex(outer_target, size))
            )
            vertex_map.append(
                (_ring_vertex(index, size), _ring_vertex(ring_target, size))
            )
        automorphisms.append(
            MapAutomorphism(name, tuple(piece_map), tuple(vertex_map))
        )

    result = PlanarMap(
        name=f"double-cycle-{size}",
        pieces=outer_pieces + inner_pieces,
        vertices=outer_vertices + ring_vertices + (center_vertex,),
        interfaces=(
            outer_cycle_interfaces
            + radial_interfaces
            + inner_cycle_interfaces
            + exterior_interfaces
        ),
        automorphisms=tuple(automorphisms),
        # The shorter inner contour keeps the anchored assignment domain smaller.
        reference_piece=_inner_piece(0, size),
    )
    result.validate()
    return result


def build_double_cycle_6_map() -> PlanarMap:
    return build_double_cycle_map(6)
