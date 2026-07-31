from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .base import (
    InterfaceSpec,
    InterfaceView,
    MapAutomorphism,
    PieceSpec,
    PlanarMap,
    VertexSpec,
)


@dataclass(frozen=True)
class _Annulus:
    upper_inner_paths: tuple[tuple[str, ...], ...]
    lower_outer_paths: tuple[tuple[str, ...], ...]
    lower_next: tuple[int, ...]
    vertices: tuple[VertexSpec, ...]
    interfaces: tuple[InterfaceSpec, ...]
    local_vertex_prefixes: tuple[str, ...]
    lower_index_map: tuple[int, ...]


def _piece(prefix: str, index: int, size: int) -> str:
    return f"{prefix}{index % size + 1}"


def _vertex(prefix: str, index: int, size: int) -> str:
    return f"{prefix}{index % size + 1}"


def _identity_index(index: int, size: int) -> int:
    return index % size


def _reverse_index(index: int, size: int) -> int:
    return (-index) % size


def _parallel_annulus(
    *,
    size: int,
    upper_prefix: str,
    lower_prefix: str,
    vertex_prefix: str,
) -> _Annulus:
    upper_paths = tuple(
        (
            _vertex(vertex_prefix, index, size),
            _vertex(vertex_prefix, index - 1, size),
        )
        for index in range(size)
    )
    lower_paths = tuple(
        (
            _vertex(vertex_prefix, index - 1, size),
            _vertex(vertex_prefix, index, size),
        )
        for index in range(size)
    )
    vertices = tuple(
        VertexSpec(
            _vertex(vertex_prefix, index, size),
            "interior",
            (
                _piece(upper_prefix, index, size),
                _piece(upper_prefix, index + 1, size),
                _piece(lower_prefix, index, size),
                _piece(lower_prefix, index + 1, size),
            ),
            2.0,
        )
        for index in range(size)
    )
    interfaces = tuple(
        InterfaceSpec(
            f"{_piece(upper_prefix, index, size)}-"
            f"{_piece(lower_prefix, index, size)}",
            _piece(upper_prefix, index, size),
            _piece(lower_prefix, index, size),
            (
                InterfaceView(
                    _piece(upper_prefix, index, size),
                    _vertex(vertex_prefix, index, size),
                    _vertex(vertex_prefix, index - 1, size),
                ),
                InterfaceView(
                    _piece(lower_prefix, index, size),
                    _vertex(vertex_prefix, index - 1, size),
                    _vertex(vertex_prefix, index, size),
                ),
            ),
        )
        for index in range(size)
    )
    return _Annulus(
        upper_inner_paths=upper_paths,
        lower_outer_paths=lower_paths,
        lower_next=tuple((index + 1) % size for index in range(size)),
        vertices=vertices,
        interfaces=interfaces,
        local_vertex_prefixes=(vertex_prefix,),
        lower_index_map=tuple(range(size)),
    )


def _offset_annulus(
    *,
    size: int,
    upper_prefix: str,
    lower_prefix: str,
    upper_vertex_prefix: str,
    lower_vertex_prefix: str,
    reverse_lower_indexing: bool,
) -> _Annulus:
    index_map: Callable[[int, int], int] = (
        _reverse_index if reverse_lower_indexing else _identity_index
    )
    lower_index_map = tuple(index_map(index, size) for index in range(size))
    inverse_lower_index = {
        actual: local for local, actual in enumerate(lower_index_map)
    }

    upper_paths = tuple(
        (
            _vertex(upper_vertex_prefix, index, size),
            _vertex(lower_vertex_prefix, index, size),
            _vertex(upper_vertex_prefix, index - 1, size),
        )
        for index in range(size)
    )
    local_lower_paths = tuple(
        (
            _vertex(lower_vertex_prefix, index - 1, size),
            _vertex(upper_vertex_prefix, index - 1, size),
            _vertex(lower_vertex_prefix, index, size),
        )
        for index in range(size)
    )
    lower_paths = tuple(
        local_lower_paths[inverse_lower_index[actual]]
        for actual in range(size)
    )
    lower_next = [0] * size
    for local_index, actual_index in enumerate(lower_index_map):
        lower_next[actual_index] = lower_index_map[(local_index + 1) % size]

    vertices: list[VertexSpec] = []
    for index in range(size):
        lower_current = lower_index_map[index]
        lower_next_index = lower_index_map[(index + 1) % size]
        vertices.append(
            VertexSpec(
                _vertex(upper_vertex_prefix, index, size),
                "interior",
                (
                    _piece(upper_prefix, index, size),
                    _piece(upper_prefix, index + 1, size),
                    _piece(lower_prefix, lower_next_index, size),
                ),
                2.0,
            )
        )
        vertices.append(
            VertexSpec(
                _vertex(lower_vertex_prefix, index, size),
                "interior",
                (
                    _piece(upper_prefix, index, size),
                    _piece(lower_prefix, lower_current, size),
                    _piece(lower_prefix, lower_next_index, size),
                ),
                2.0,
            )
        )

    interfaces: list[InterfaceSpec] = []
    for index in range(size):
        lower_current = lower_index_map[index]
        lower_next_index = lower_index_map[(index + 1) % size]
        interfaces.append(
            InterfaceSpec(
                f"{_piece(upper_prefix, index, size)}-"
                f"{_piece(lower_prefix, lower_next_index, size)}",
                _piece(upper_prefix, index, size),
                _piece(lower_prefix, lower_next_index, size),
                (
                    InterfaceView(
                        _piece(upper_prefix, index, size),
                        _vertex(upper_vertex_prefix, index, size),
                        _vertex(lower_vertex_prefix, index, size),
                    ),
                    InterfaceView(
                        _piece(lower_prefix, lower_next_index, size),
                        _vertex(lower_vertex_prefix, index, size),
                        _vertex(upper_vertex_prefix, index, size),
                    ),
                ),
            )
        )
        interfaces.append(
            InterfaceSpec(
                f"{_piece(upper_prefix, index, size)}-"
                f"{_piece(lower_prefix, lower_current, size)}",
                _piece(upper_prefix, index, size),
                _piece(lower_prefix, lower_current, size),
                (
                    InterfaceView(
                        _piece(upper_prefix, index, size),
                        _vertex(lower_vertex_prefix, index, size),
                        _vertex(upper_vertex_prefix, index - 1, size),
                    ),
                    InterfaceView(
                        _piece(lower_prefix, lower_current, size),
                        _vertex(upper_vertex_prefix, index - 1, size),
                        _vertex(lower_vertex_prefix, index, size),
                    ),
                ),
            )
        )

    return _Annulus(
        upper_inner_paths=upper_paths,
        lower_outer_paths=lower_paths,
        lower_next=tuple(lower_next),
        vertices=tuple(vertices),
        interfaces=tuple(interfaces),
        local_vertex_prefixes=(upper_vertex_prefix, lower_vertex_prefix),
        lower_index_map=lower_index_map,
    )


def _rotation_automorphisms(
    *,
    size: int,
    inner_index_direction: int,
    vertex_prefixes: tuple[str, ...],
) -> tuple[MapAutomorphism, ...]:
    automorphisms: list[MapAutomorphism] = []
    for shift in range(size):
        piece_map: list[tuple[str, str]] = []
        for index in range(size):
            piece_map.append(
                (_piece("E", index, size), _piece("E", index + shift, size))
            )
            piece_map.append(
                (_piece("M", index, size), _piece("M", index + shift, size))
            )
            piece_map.append(
                (
                    _piece("I", index, size),
                    _piece("I", index + inner_index_direction * shift, size),
                )
            )
        vertex_map: list[tuple[str, str]] = [("Z", "Z")]
        for index in range(size):
            vertex_map.append(
                (_vertex("A", index, size), _vertex("A", index + shift, size))
            )
            for prefix in vertex_prefixes:
                vertex_map.append(
                    (
                        _vertex(prefix, index, size),
                        _vertex(prefix, index + shift, size),
                    )
                )
        automorphisms.append(
            MapAutomorphism(
                f"rotation_{shift}", tuple(piece_map), tuple(vertex_map)
            )
        )
    return tuple(automorphisms)


def build_three_ring_map(
    size: int,
    *,
    outer_coupling: str,
    inner_coupling: str,
    opposite_inner_chirality: bool = False,
    name: str | None = None,
) -> PlanarMap:
    """Build three cyclic tile layers joined by parallel or offset annuli.

    ``outer_coupling`` describes the E/M annulus and ``inner_coupling`` the
    M/I annulus.  ``parallel`` gives one E_i-M_i (or M_i-I_i) interface.
    ``offset`` gives the antiprism pattern with contacts to two consecutive
    tiles.  The optional opposite chirality reverses only the I-layer indexing.
    """

    if size < 3:
        raise ValueError("A three-ring map requires size >= 3")
    if outer_coupling not in {"parallel", "offset"}:
        raise ValueError(f"Unknown outer coupling {outer_coupling!r}")
    if inner_coupling not in {"parallel", "offset"}:
        raise ValueError(f"Unknown inner coupling {inner_coupling!r}")
    if opposite_inner_chirality and inner_coupling != "offset":
        raise ValueError("Opposite chirality only applies to an offset inner annulus")

    outer_annulus = (
        _parallel_annulus(
            size=size,
            upper_prefix="E",
            lower_prefix="M",
            vertex_prefix="U",
        )
        if outer_coupling == "parallel"
        else _offset_annulus(
            size=size,
            upper_prefix="E",
            lower_prefix="M",
            upper_vertex_prefix="U",
            lower_vertex_prefix="V",
            reverse_lower_indexing=False,
        )
    )
    inner_annulus = (
        _parallel_annulus(
            size=size,
            upper_prefix="M",
            lower_prefix="I",
            vertex_prefix="W",
        )
        if inner_coupling == "parallel"
        else _offset_annulus(
            size=size,
            upper_prefix="M",
            lower_prefix="I",
            upper_vertex_prefix="W",
            lower_vertex_prefix="X",
            reverse_lower_indexing=opposite_inner_chirality,
        )
    )

    outer_pieces = tuple(
        PieceSpec(
            _piece("E", index, size),
            (
                _vertex("A", index, size),
                _vertex("A", index + 1, size),
            )
            + outer_annulus.upper_inner_paths[index],
            True,
            "arc",
        )
        for index in range(size)
    )
    middle_pieces = tuple(
        PieceSpec(
            _piece("M", index, size),
            outer_annulus.lower_outer_paths[index]
            + inner_annulus.upper_inner_paths[index],
            False,
            "none",
        )
        for index in range(size)
    )
    inner_pieces = tuple(
        PieceSpec(
            _piece("I", index, size),
            inner_annulus.lower_outer_paths[index] + ("Z",),
            False,
            "none",
        )
        for index in range(size)
    )

    outer_vertices = tuple(
        VertexSpec(
            _vertex("A", index, size),
            "outer",
            (_piece("E", index - 1, size), _piece("E", index, size)),
            1.0,
        )
        for index in range(size)
    )
    center = VertexSpec(
        "Z",
        "interior",
        tuple(_piece("I", index, size) for index in range(size)),
        2.0,
    )

    outer_cycle = tuple(
        InterfaceSpec(
            f"{_piece('E', index, size)}-{_piece('E', index + 1, size)}",
            _piece("E", index, size),
            _piece("E", index + 1, size),
            (
                InterfaceView(
                    _piece("E", index, size),
                    _vertex("A", index + 1, size),
                    outer_annulus.upper_inner_paths[index][0],
                ),
                InterfaceView(
                    _piece("E", index + 1, size),
                    outer_annulus.upper_inner_paths[(index + 1) % size][-1],
                    _vertex("A", index + 1, size),
                ),
            ),
        )
        for index in range(size)
    )
    middle_cycle = tuple(
        InterfaceSpec(
            f"{_piece('M', index, size)}-{_piece('M', index + 1, size)}",
            _piece("M", index, size),
            _piece("M", index + 1, size),
            (
                InterfaceView(
                    _piece("M", index, size),
                    outer_annulus.lower_outer_paths[index][-1],
                    inner_annulus.upper_inner_paths[index][0],
                ),
                InterfaceView(
                    _piece("M", index + 1, size),
                    inner_annulus.upper_inner_paths[(index + 1) % size][-1],
                    outer_annulus.lower_outer_paths[(index + 1) % size][0],
                ),
            ),
        )
        for index in range(size)
    )
    inner_cycle_list: list[InterfaceSpec] = []
    seen_inner_edges: set[frozenset[int]] = set()
    for index in range(size):
        next_index = inner_annulus.lower_next[index]
        edge_key = frozenset((index, next_index))
        if edge_key in seen_inner_edges:
            continue
        seen_inner_edges.add(edge_key)
        inner_cycle_list.append(
            InterfaceSpec(
                f"{_piece('I', index, size)}-{_piece('I', next_index, size)}",
                _piece("I", index, size),
                _piece("I", next_index, size),
                (
                    InterfaceView(
                        _piece("I", index, size),
                        inner_annulus.lower_outer_paths[index][-1],
                        "Z",
                    ),
                    InterfaceView(
                        _piece("I", next_index, size),
                        "Z",
                        inner_annulus.lower_outer_paths[next_index][0],
                    ),
                ),
            )
        )
    inner_cycle = tuple(inner_cycle_list)
    outer_arcs = tuple(
        InterfaceSpec(
            f"outer-{_piece('E', index, size)}",
            _piece("E", index, size),
            None,
            (
                InterfaceView(
                    _piece("E", index, size),
                    _vertex("A", index, size),
                    _vertex("A", index + 1, size),
                ),
            ),
            is_outer=True,
        )
        for index in range(size)
    )

    inner_direction = -1 if opposite_inner_chirality else 1
    automorphisms = _rotation_automorphisms(
        size=size,
        inner_index_direction=inner_direction,
        vertex_prefixes=(
            outer_annulus.local_vertex_prefixes
            + inner_annulus.local_vertex_prefixes
        ),
    )

    if name is None:
        suffix = f"{outer_coupling}-{inner_coupling}"
        if opposite_inner_chirality:
            suffix += "-opposite"
        name = f"three-ring-{suffix}-{size}"

    result = PlanarMap(
        name=name,
        pieces=outer_pieces + middle_pieces + inner_pieces,
        vertices=(
            outer_vertices
            + outer_annulus.vertices
            + inner_annulus.vertices
            + (center,)
        ),
        interfaces=(
            outer_cycle
            + outer_annulus.interfaces
            + middle_cycle
            + inner_annulus.interfaces
            + inner_cycle
            + outer_arcs
        ),
        automorphisms=automorphisms,
        reference_piece=_piece("I", 0, size),
    )
    result.validate()
    return result


def build_three_ring_parallel_map(size: int) -> PlanarMap:
    return build_three_ring_map(
        size,
        outer_coupling="parallel",
        inner_coupling="parallel",
        name=f"three-ring-parallel-{size}",
    )


def build_three_ring_outer_offset_map(size: int) -> PlanarMap:
    return build_three_ring_map(
        size,
        outer_coupling="offset",
        inner_coupling="parallel",
        name=f"three-ring-outer-offset-{size}",
    )


def build_three_ring_inner_offset_map(size: int) -> PlanarMap:
    return build_three_ring_map(
        size,
        outer_coupling="parallel",
        inner_coupling="offset",
        name=f"three-ring-inner-offset-{size}",
    )


def build_three_ring_offset_same_map(size: int) -> PlanarMap:
    return build_three_ring_map(
        size,
        outer_coupling="offset",
        inner_coupling="offset",
        name=f"three-ring-offset-same-{size}",
    )


def build_three_ring_offset_opposite_map(size: int) -> PlanarMap:
    return build_three_ring_map(
        size,
        outer_coupling="offset",
        inner_coupling="offset",
        opposite_inner_chirality=True,
        name=f"three-ring-offset-opposite-{size}",
    )


def build_three_ring_boundary_points_map(size: int) -> PlanarMap:
    """Build an open outer layer whose middle tiles reach the disk boundary.

    The E_i tiles own the boundary arcs but have no E_i-E_(i+1) interfaces.
    Each M_i reaches the boundary at B_i, then the M and I layers form two
    parallel  cycles around the central vertex.
    """

    if size < 3:
        raise ValueError("A three-ring map requires size >= 3")

    outer_pieces = tuple(
        PieceSpec(
            _piece("E", index, size),
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
    middle_pieces = tuple(
        PieceSpec(
            _piece("M", index, size),
            (
                _vertex("B", index, size),
                _vertex("V", index, size),
                _vertex("W", index, size),
                _vertex("W", index - 1, size),
                _vertex("V", index - 1, size),
            ),
            True,
            "point",
        )
        for index in range(size)
    )
    inner_pieces = tuple(
        PieceSpec(
            _piece("I", index, size),
            (
                _vertex("W", index - 1, size),
                _vertex("W", index, size),
                "Z",
            ),
            False,
            "none",
        )
        for index in range(size)
    )

    boundary_vertices = tuple(
        VertexSpec(
            _vertex("B", index, size),
            "outer",
            (
                _piece("E", index - 1, size),
                _piece("E", index, size),
                _piece("M", index, size),
            ),
            1.0,
        )
        for index in range(size)
    )
    outer_middle_vertices = tuple(
        VertexSpec(
            _vertex("V", index, size),
            "interior",
            (
                _piece("E", index, size),
                _piece("M", index, size),
                _piece("M", index + 1, size),
            ),
            2.0,
        )
        for index in range(size)
    )
    middle_inner_vertices = tuple(
        VertexSpec(
            _vertex("W", index, size),
            "interior",
            (
                _piece("M", index, size),
                _piece("M", index + 1, size),
                _piece("I", index, size),
                _piece("I", index + 1, size),
            ),
            2.0,
        )
        for index in range(size)
    )
    center = VertexSpec(
        "Z",
        "interior",
        tuple(_piece("I", index, size) for index in range(size)),
        2.0,
    )

    cross_same = tuple(
        InterfaceSpec(
            f"{_piece('E', index, size)}-{_piece('M', index, size)}",
            _piece("E", index, size),
            _piece("M", index, size),
            (
                InterfaceView(
                    _piece("E", index, size),
                    _vertex("V", index, size),
                    _vertex("B", index, size),
                ),
                InterfaceView(
                    _piece("M", index, size),
                    _vertex("B", index, size),
                    _vertex("V", index, size),
                ),
            ),
        )
        for index in range(size)
    )
    cross_next = tuple(
        InterfaceSpec(
            f"{_piece('E', index, size)}-{_piece('M', index + 1, size)}",
            _piece("E", index, size),
            _piece("M", index + 1, size),
            (
                InterfaceView(
                    _piece("E", index, size),
                    _vertex("B", index + 1, size),
                    _vertex("V", index, size),
                ),
                InterfaceView(
                    _piece("M", index + 1, size),
                    _vertex("V", index, size),
                    _vertex("B", index + 1, size),
                ),
            ),
        )
        for index in range(size)
    )
    middle_cycle = tuple(
        InterfaceSpec(
            f"{_piece('M', index, size)}-{_piece('M', index + 1, size)}",
            _piece("M", index, size),
            _piece("M", index + 1, size),
            (
                InterfaceView(
                    _piece("M", index, size),
                    _vertex("V", index, size),
                    _vertex("W", index, size),
                ),
                InterfaceView(
                    _piece("M", index + 1, size),
                    _vertex("W", index, size),
                    _vertex("V", index, size),
                ),
            ),
        )
        for index in range(size)
    )
    radial = tuple(
        InterfaceSpec(
            f"{_piece('M', index, size)}-{_piece('I', index, size)}",
            _piece("M", index, size),
            _piece("I", index, size),
            (
                InterfaceView(
                    _piece("M", index, size),
                    _vertex("W", index, size),
                    _vertex("W", index - 1, size),
                ),
                InterfaceView(
                    _piece("I", index, size),
                    _vertex("W", index - 1, size),
                    _vertex("W", index, size),
                ),
            ),
        )
        for index in range(size)
    )
    inner_cycle = tuple(
        InterfaceSpec(
            f"{_piece('I', index, size)}-{_piece('I', index + 1, size)}",
            _piece("I", index, size),
            _piece("I", index + 1, size),
            (
                InterfaceView(
                    _piece("I", index, size),
                    _vertex("W", index, size),
                    "Z",
                ),
                InterfaceView(
                    _piece("I", index + 1, size),
                    "Z",
                    _vertex("W", index, size),
                ),
            ),
        )
        for index in range(size)
    )
    outer_arcs = tuple(
        InterfaceSpec(
            f"outer-{_piece('E', index, size)}",
            _piece("E", index, size),
            None,
            (
                InterfaceView(
                    _piece("E", index, size),
                    _vertex("B", index, size),
                    _vertex("B", index + 1, size),
                ),
            ),
            is_outer=True,
        )
        for index in range(size)
    )

    automorphisms: list[MapAutomorphism] = []
    for shift in range(size):
        piece_map = tuple(
            (source, target)
            for index in range(size)
            for source, target in (
                (_piece("E", index, size), _piece("E", index + shift, size)),
                (_piece("M", index, size), _piece("M", index + shift, size)),
                (_piece("I", index, size), _piece("I", index + shift, size)),
            )
        )
        vertex_map = [("Z", "Z")]
        for index in range(size):
            for prefix in ("B", "V", "W"):
                vertex_map.append(
                    (
                        _vertex(prefix, index, size),
                        _vertex(prefix, index + shift, size),
                    )
                )
        automorphisms.append(
            MapAutomorphism(f"rotation_{shift}", piece_map, tuple(vertex_map))
        )

    result = PlanarMap(
        name=f"three-ring-boundary-points-{size}",
        pieces=outer_pieces + middle_pieces + inner_pieces,
        vertices=(
            boundary_vertices
            + outer_middle_vertices
            + middle_inner_vertices
            + (center,)
        ),
        interfaces=(
            cross_same
            + cross_next
            + middle_cycle
            + radial
            + inner_cycle
            + outer_arcs
        ),
        automorphisms=tuple(automorphisms),
        reference_piece=_piece("I", 0, size),
    )
    result.validate()
    return result
