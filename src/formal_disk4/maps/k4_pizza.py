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


_PIECE_COUNT = 4


def _piece_name(index: int) -> str:
    return f"P{index % _PIECE_COUNT}"


def _outer_vertex_name(first: int, second: int) -> str:
    a, b = sorted((first % _PIECE_COUNT, second % _PIECE_COUNT))
    return f"O{a}{b}"


def _piece_cycle(index: int) -> Tuple[str, str, str]:
    return (
        "Z",
        _outer_vertex_name(index, index + 1),
        _outer_vertex_name(index - 1, index),
    )


def _dihedral_index_maps() -> Tuple[Tuple[str, Callable[[int], int]], ...]:
    transforms: list[tuple[str, Callable[[int], int]]] = []
    for shift in range(_PIECE_COUNT):
        transforms.append(
            (
                f"rotation_{shift}",
                lambda index, shift=shift: (index + shift) % _PIECE_COUNT,
            )
        )
    for shift in range(_PIECE_COUNT):
        transforms.append(
            (
                f"reflection_{shift}",
                lambda index, shift=shift: (shift - index) % _PIECE_COUNT,
            )
        )
    return tuple(transforms)


def build_k4_pizza_map() -> PlanarMap:
    """Four congruent sectors arranged cyclically around one interior vertex.

    The piece contact graph is the four-cycle P0-P1-P2-P3-P0.  Every piece
    also owns one nonzero arc of the disk boundary.  This is the four-sector
    analogue of ``k3-pizza`` and is intentionally described only through the
    generic planar-map data structures used by the rest of the pipeline.
    """

    pieces = tuple(
        PieceSpec(_piece_name(index), _piece_cycle(index), True)
        for index in range(_PIECE_COUNT)
    )

    outer_vertices = tuple(
        _outer_vertex_name(index, index + 1) for index in range(_PIECE_COUNT)
    )
    vertices = (
        VertexSpec(
            "Z",
            "interior",
            tuple(_piece_name(index) for index in range(_PIECE_COUNT)),
            2.0,
        ),
    ) + tuple(
        VertexSpec(
            vertex_name,
            "outer",
            (_piece_name(index), _piece_name(index + 1)),
            1.0,
        )
        for index, vertex_name in enumerate(outer_vertices)
    )

    internal_interfaces = tuple(
        InterfaceSpec(
            f"P{index}-P{(index + 1) % _PIECE_COUNT}",
            _piece_name(index),
            _piece_name(index + 1),
            (
                InterfaceView(
                    _piece_name(index),
                    "Z",
                    _outer_vertex_name(index, index + 1),
                ),
                InterfaceView(
                    _piece_name(index + 1),
                    _outer_vertex_name(index, index + 1),
                    "Z",
                ),
            ),
        )
        for index in range(_PIECE_COUNT)
    )
    outer_interfaces = tuple(
        InterfaceSpec(
            f"outer-P{index}",
            _piece_name(index),
            None,
            (
                InterfaceView(
                    _piece_name(index),
                    _outer_vertex_name(index, index + 1),
                    _outer_vertex_name(index - 1, index),
                ),
            ),
            is_outer=True,
        )
        for index in range(_PIECE_COUNT)
    )

    automorphisms = []
    for name, index_map in _dihedral_index_maps():
        piece_map = tuple(
            (_piece_name(index), _piece_name(index_map(index)))
            for index in range(_PIECE_COUNT)
        )
        vertex_map = [("Z", "Z")]
        for index in range(_PIECE_COUNT):
            source = _outer_vertex_name(index, index + 1)
            target = _outer_vertex_name(index_map(index), index_map(index + 1))
            vertex_map.append((source, target))
        automorphisms.append(
            MapAutomorphism(
                name=name,
                piece_map=piece_map,
                vertex_map=tuple(vertex_map),
            )
        )

    result = PlanarMap(
        name="k4-pizza",
        pieces=pieces,
        vertices=vertices,
        interfaces=internal_interfaces + outer_interfaces,
        automorphisms=tuple(automorphisms),
        reference_piece="P0",
    )
    result.validate()
    return result
