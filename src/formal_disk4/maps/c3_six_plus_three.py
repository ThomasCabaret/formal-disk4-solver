from __future__ import annotations

from collections import Counter, defaultdict
from typing import Mapping, Sequence

from .base import (
    InterfaceSpec,
    InterfaceView,
    MapAutomorphism,
    PieceSpec,
    PlanarMap,
    VertexSpec,
)

def _index(prefix: str, value: int, modulus: int) -> str:
    return f"{prefix}{(value - 1) % modulus + 1}"


def _rotate_indexed(name: str, modulus: int, step: int, power: int) -> str:
    return _index(name[0], int(name[1:]) + step * power, modulus)


def _rotation_automorphisms(
    piece_names: Sequence[str],
    vertex_names: Sequence[str],
    vertex_orbits: Mapping[str, tuple[int, int]],
) -> tuple[MapAutomorphism, ...]:
    result = []
    for power in range(3):
        piece_map = []
        for name in piece_names:
            if name.startswith("O"):
                target = _rotate_indexed(name, 6, 2, power)
            elif name.startswith("I"):
                target = _rotate_indexed(name, 3, 1, power)
            else:
                raise ValueError(f"Unknown six-plus-three piece {name!r}")
            piece_map.append((name, target))

        vertex_map = []
        for name in vertex_names:
            if name == "Z":
                target = "Z"
            else:
                try:
                    modulus, step = vertex_orbits[name[0]]
                except KeyError as exc:
                    raise ValueError(
                        f"No C3 vertex orbit declared for {name!r}"
                    ) from exc
                target = _rotate_indexed(name, modulus, step, power)
            vertex_map.append((name, target))
        result.append(
            MapAutomorphism(
                f"rotation_{power}", tuple(piece_map), tuple(vertex_map)
            )
        )
    return tuple(result)


def _is_outer_edge(start: str, end: str) -> bool:
    if not start.startswith("A") or not end.startswith("A"):
        return False
    left = int(start[1:])
    right = int(end[1:])
    return (right - left) % 6 in {1, 5}


def _build_from_contours(
    name: str,
    contours: Mapping[str, Sequence[str]],
    *,
    vertex_orbits: Mapping[str, tuple[int, int]],
) -> PlanarMap:
    """Build the combinatorial disk map encoded by polygonal face contours.

    The source schematic is a polygonal partition.  Matching undirected edges
    therefore determine all positive-length contacts, while a lone A_i-A_(i+1)
    edge is one disk-boundary arc.  Merely containing A_i records a point-only
    boundary contact, as in the three ``b`` variants.
    """

    piece_names = tuple(
        [f"O{index}" for index in range(1, 7)]
        + [f"I{index}" for index in range(1, 4)]
    )
    if set(contours) != set(piece_names):
        raise ValueError("A six-plus-three map must contain O1..O6 and I1..I3")

    edge_uses: dict[
        frozenset[str], list[tuple[str, str, str]]
    ] = defaultdict(list)
    incidences: dict[str, set[str]] = defaultdict(set)
    pieces = []
    for piece_name in piece_names:
        contour = tuple(str(vertex) for vertex in contours[piece_name])
        for vertex in contour:
            incidences[vertex].add(piece_name)
        directed_edges = tuple(
            (contour[index], contour[(index + 1) % len(contour)])
            for index in range(len(contour))
        )
        for start, end in directed_edges:
            edge_uses[frozenset((start, end))].append(
                (piece_name, start, end)
            )
        has_outer_arc = any(
            _is_outer_edge(start, end) for start, end in directed_edges
        )
        has_outer_point = any(vertex.startswith("A") for vertex in contour)
        contact = "arc" if has_outer_arc else "point" if has_outer_point else "none"
        pieces.append(
            PieceSpec(
                piece_name,
                contour,
                contact != "none",
                contact,
            )
        )

    interfaces = []
    repeated_contacts: Counter[tuple[str, str]] = Counter()
    for edge, uses in edge_uses.items():
        if len(edge) != 2:
            raise ValueError(f"Degenerate edge in {name}: {sorted(edge)}")
        if len(uses) == 1:
            piece, start, end = uses[0]
            if not _is_outer_edge(start, end):
                raise ValueError(
                    f"Unpaired non-boundary edge in {name}: {piece}:{start}-{end}"
                )
            interfaces.append(
                InterfaceSpec(
                    f"outer-{piece}",
                    piece,
                    None,
                    (InterfaceView(piece, start, end),),
                    is_outer=True,
                )
            )
            continue
        if len(uses) != 2:
            raise ValueError(
                f"Edge {sorted(edge)} in {name} belongs to {len(uses)} faces"
            )
        left, right = uses
        pair = tuple(sorted((left[0], right[0])))
        repeated_contacts[pair] += 1
        suffix = (
            f"-{repeated_contacts[pair]}"
            if repeated_contacts[pair] > 1
            else ""
        )
        interfaces.append(
            InterfaceSpec(
                f"{pair[0]}-{pair[1]}{suffix}",
                left[0],
                right[0],
                (
                    InterfaceView(left[0], left[1], left[2]),
                    InterfaceView(right[0], right[1], right[2]),
                ),
            )
        )

    vertex_names = tuple(sorted(incidences, key=lambda item: (item == "Z", item)))
    vertices = tuple(
        VertexSpec(
            vertex,
            "outer" if vertex.startswith("A") else "interior",
            tuple(sorted(incidences[vertex])),
            1.0 if vertex.startswith("A") else 2.0,
        )
        for vertex in vertex_names
    )
    result = PlanarMap(
        name=name,
        pieces=tuple(pieces),
        vertices=vertices,
        interfaces=tuple(interfaces),
        automorphisms=_rotation_automorphisms(
            piece_names,
            vertex_names,
            {"A": (6, 2), **dict(vertex_orbits)},
        ),
        reference_piece="I1",
    )
    result.validate()
    return result


def _s3_contours(*, boundary_points: bool) -> dict[str, tuple[str, ...]]:
    contours: dict[str, tuple[str, ...]] = {}
    if boundary_points:
        for index in range(1, 7):
            next_index = index % 6 + 1
            if index % 2:
                contours[f"O{index}"] = (
                    f"A{index}",
                    f"A{next_index}",
                    f"V{next_index}",
                )
            else:
                contours[f"O{index}"] = (
                    f"A{index}",
                    f"A{next_index}",
                    "Z",
                    f"V{index}",
                )
        for inner in range(1, 4):
            odd = 2 * inner - 1
            even = 2 * inner
            contours[f"I{inner}"] = ("Z", f"A{odd}", f"V{even}")
        return contours

    for index in range(1, 7):
        next_index = index % 6 + 1
        inner_path = (f"V{next_index}", f"V{index}")
        if index % 2 == 0:
            inner_path = (f"V{next_index}", "Z", f"V{index}")
        contours[f"O{index}"] = (
            f"A{index}",
            f"A{next_index}",
            *inner_path,
        )
    for inner in range(1, 4):
        first = 2 * inner - 1
        contours[f"I{inner}"] = ("Z", f"V{first}", f"V{first + 1}")
    return contours


def _t2_contours(*, boundary_points: bool) -> dict[str, tuple[str, ...]]:
    contours: dict[str, tuple[str, ...]] = {}
    if boundary_points:
        for index in range(1, 7):
            next_index = index % 6 + 1
            corner = index + 1 if index % 2 else index
            contours[f"O{index}"] = (
                f"A{index}",
                f"A{next_index}",
                f"C{corner}",
            )
        for inner in range(1, 4):
            previous_corner = (2 * inner - 2) % 6 or 6
            point = 2 * inner - 1
            next_corner = 2 * inner
            contours[f"I{inner}"] = (
                "Z",
                f"C{previous_corner}",
                f"A{point}",
                f"C{next_corner}",
            )
        return contours

    for index in range(1, 7):
        next_index = index % 6 + 1
        contours[f"O{index}"] = (
            f"A{index}",
            f"A{next_index}",
            f"B{next_index}",
            f"B{index}",
        )
    for inner in range(1, 4):
        previous = (2 * inner - 2) % 6 or 6
        contours[f"I{inner}"] = (
            "Z",
            f"B{previous}",
            f"B{2 * inner - 1}",
            f"B{2 * inner}",
        )
    return contours


def _t3_contours(*, boundary_points: bool) -> dict[str, tuple[str, ...]]:
    contours: dict[str, tuple[str, ...]] = {}
    if boundary_points:
        for index in range(1, 7):
            next_index = index % 6 + 1
            if index % 2:
                contours[f"O{index}"] = (
                    f"A{index}",
                    f"A{next_index}",
                    f"P{next_index}",
                )
            else:
                contours[f"O{index}"] = (
                    f"A{index}",
                    f"A{next_index}",
                    f"Q{index}",
                    f"P{index}",
                )
        for inner in range(1, 4):
            previous = (2 * inner - 2) % 6 or 6
            point = 2 * inner - 1
            current = 2 * inner
            contours[f"I{inner}"] = (
                "Z",
                f"Q{previous}",
                f"A{point}",
                f"P{current}",
                f"Q{current}",
            )
        return contours

    inner_paths = {
        1: ("R1", "R2"),
        2: ("R2", "R3", "R4"),
        3: ("R4", "R5"),
        4: ("R5", "R6", "R7"),
        5: ("R7", "R8"),
        6: ("R8", "R9", "R1"),
    }
    for index in range(1, 7):
        next_index = index % 6 + 1
        contours[f"O{index}"] = (
            f"A{index}",
            f"A{next_index}",
            *reversed(inner_paths[index]),
        )
    contours.update(
        {
            "I1": ("Z", "R9", "R1", "R2", "R3"),
            "I2": ("Z", "R3", "R4", "R5", "R6"),
            "I3": ("Z", "R6", "R7", "R8", "R9"),
        }
    )
    return contours


def build_c3_six_plus_three_s3_map() -> PlanarMap:
    return _build_from_contours(
        "c3-6plus3-s3",
        _s3_contours(boundary_points=False),
        vertex_orbits={"V": (6, 2)},
    )


def build_c3_six_plus_three_s3b_map() -> PlanarMap:
    return _build_from_contours(
        "c3-6plus3-s3b",
        _s3_contours(boundary_points=True),
        vertex_orbits={"V": (6, 2)},
    )


def build_c3_six_plus_three_t2_map() -> PlanarMap:
    return _build_from_contours(
        "c3-6plus3-t2",
        _t2_contours(boundary_points=False),
        vertex_orbits={"B": (6, 2)},
    )


def build_c3_six_plus_three_t3_map() -> PlanarMap:
    return _build_from_contours(
        "c3-6plus3-t3",
        _t3_contours(boundary_points=False),
        vertex_orbits={"R": (9, 3)},
    )


def build_c3_six_plus_three_t2b_map() -> PlanarMap:
    return _build_from_contours(
        "c3-6plus3-t2b",
        _t2_contours(boundary_points=True),
        vertex_orbits={"C": (6, 2)},
    )


def build_c3_six_plus_three_t3b_map() -> PlanarMap:
    return _build_from_contours(
        "c3-6plus3-t3b",
        _t3_contours(boundary_points=True),
        vertex_orbits={"P": (6, 2), "Q": (6, 2)},
    )
