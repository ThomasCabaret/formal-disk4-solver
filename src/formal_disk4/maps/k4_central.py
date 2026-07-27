from __future__ import annotations

from itertools import permutations
from typing import Dict, Iterable, Tuple

from .base import (
    InterfaceSpec,
    InterfaceView,
    MapAutomorphism,
    PieceSpec,
    PlanarMap,
    VertexSpec,
)


def _pair_name(prefix: str, first: int, second: int) -> str:
    a, b = sorted((first, second))
    return f"{prefix}{a}{b}"


def _piece_name(index: int) -> str:
    return f"P{index}"


def _map_vertex_name(name: str, permutation: Tuple[int, int, int]) -> str:
    prefix = name[0]
    first = int(name[1])
    second = int(name[2])
    return _pair_name(prefix, permutation[first], permutation[second])


def build_k4_central_map() -> PlanarMap:
    """Return the fixed K4 contact map with one central and three peripheral pieces."""

    central = PieceSpec("C", ("I01", "I02", "I12"), touches_outer_boundary=False)
    peripheral = (
        PieceSpec("P0", ("I02", "I01", "O01", "O02"), True),
        PieceSpec("P1", ("I01", "I12", "O12", "O01"), True),
        PieceSpec("P2", ("I12", "I02", "O02", "O12"), True),
    )

    vertices = (
        VertexSpec("I01", "interior", ("C", "P0", "P1"), 2.0),
        VertexSpec("I12", "interior", ("C", "P1", "P2"), 2.0),
        VertexSpec("I02", "interior", ("C", "P0", "P2"), 2.0),
        VertexSpec("O01", "outer", ("P0", "P1"), 1.0),
        VertexSpec("O12", "outer", ("P1", "P2"), 1.0),
        VertexSpec("O02", "outer", ("P0", "P2"), 1.0),
    )

    interfaces = (
        InterfaceSpec(
            "C-P0",
            "C",
            "P0",
            (
                InterfaceView("C", "I01", "I02"),
                InterfaceView("P0", "I02", "I01"),
            ),
        ),
        InterfaceSpec(
            "C-P1",
            "C",
            "P1",
            (
                InterfaceView("C", "I12", "I01"),
                InterfaceView("P1", "I01", "I12"),
            ),
        ),
        InterfaceSpec(
            "C-P2",
            "C",
            "P2",
            (
                InterfaceView("C", "I02", "I12"),
                InterfaceView("P2", "I12", "I02"),
            ),
        ),
        InterfaceSpec(
            "P0-P1",
            "P0",
            "P1",
            (
                InterfaceView("P0", "I01", "O01"),
                InterfaceView("P1", "O01", "I01"),
            ),
        ),
        InterfaceSpec(
            "P1-P2",
            "P1",
            "P2",
            (
                InterfaceView("P1", "I12", "O12"),
                InterfaceView("P2", "O12", "I12"),
            ),
        ),
        InterfaceSpec(
            "P0-P2",
            "P0",
            "P2",
            (
                InterfaceView("P0", "O02", "I02"),
                InterfaceView("P2", "I02", "O02"),
            ),
        ),
        InterfaceSpec(
            "outer-P0",
            "P0",
            None,
            (InterfaceView("P0", "O01", "O02"),),
            is_outer=True,
        ),
        InterfaceSpec(
            "outer-P1",
            "P1",
            None,
            (InterfaceView("P1", "O12", "O01"),),
            is_outer=True,
        ),
        InterfaceSpec(
            "outer-P2",
            "P2",
            None,
            (InterfaceView("P2", "O02", "O12"),),
            is_outer=True,
        ),
    )

    automorphisms = []
    for permutation in permutations(range(3)):
        piece_map = (("C", "C"),) + tuple(
            (_piece_name(index), _piece_name(permutation[index])) for index in range(3)
        )
        vertex_map = tuple(
            (vertex.name, _map_vertex_name(vertex.name, permutation)) for vertex in vertices
        )
        automorphisms.append(
            MapAutomorphism(
                name="sigma_" + "".join(str(value) for value in permutation),
                piece_map=piece_map,
                vertex_map=vertex_map,
            )
        )

    result = PlanarMap(
        name="k4-central",
        pieces=(central,) + peripheral,
        vertices=vertices,
        interfaces=interfaces,
        automorphisms=tuple(automorphisms),
        reference_piece="C",
    )
    result.validate()
    return result
