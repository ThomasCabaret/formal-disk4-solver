from __future__ import annotations

from itertools import permutations
from typing import Tuple

from .base import (
    InterfaceSpec,
    InterfaceView,
    MapAutomorphism,
    PieceSpec,
    PlanarMap,
    VertexSpec,
)


def _pair_name(first: int, second: int) -> str:
    a, b = sorted((first, second))
    return f"O{a}{b}"


def _piece_name(index: int) -> str:
    return f"P{index}"


def _map_vertex_name(name: str, permutation: Tuple[int, int, int]) -> str:
    if name == "Z":
        return "Z"
    if not (len(name) == 3 and name[0] == "O"):
        raise ValueError(f"Unexpected pizza-map vertex name: {name}")
    return _pair_name(permutation[int(name[1])], permutation[int(name[2])])


def build_k3_pizza_map() -> PlanarMap:
    """Three congruent disk sectors meeting at one central point.

    Each pair of pieces shares one radial interface and every piece owns one
    nonzero arc of the disk boundary.  The contact graph on pieces is K3.
    """

    pieces = (
        PieceSpec("P0", ("Z", "O01", "O02"), True),
        PieceSpec("P1", ("Z", "O12", "O01"), True),
        PieceSpec("P2", ("Z", "O02", "O12"), True),
    )

    vertices = (
        VertexSpec("Z", "interior", ("P0", "P1", "P2"), 2.0),
        VertexSpec("O01", "outer", ("P0", "P1"), 1.0),
        VertexSpec("O12", "outer", ("P1", "P2"), 1.0),
        VertexSpec("O02", "outer", ("P0", "P2"), 1.0),
    )

    interfaces = (
        InterfaceSpec(
            "P0-P1",
            "P0",
            "P1",
            (
                InterfaceView("P0", "Z", "O01"),
                InterfaceView("P1", "O01", "Z"),
            ),
        ),
        InterfaceSpec(
            "P1-P2",
            "P1",
            "P2",
            (
                InterfaceView("P1", "Z", "O12"),
                InterfaceView("P2", "O12", "Z"),
            ),
        ),
        InterfaceSpec(
            "P0-P2",
            "P0",
            "P2",
            (
                InterfaceView("P0", "O02", "Z"),
                InterfaceView("P2", "Z", "O02"),
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
        piece_map = tuple(
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
        name="k3-pizza",
        pieces=pieces,
        vertices=vertices,
        interfaces=interfaces,
        automorphisms=tuple(automorphisms),
        reference_piece="P0",
    )
    result.validate()
    return result
