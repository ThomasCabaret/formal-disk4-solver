from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Dict, Iterable, Iterator, Mapping, Sequence, Tuple


@dataclass(frozen=True, order=True)
class Occurrence:
    """One occurrence of a geometric vertex on one piece contour."""

    piece: str
    vertex: str

    @property
    def name(self) -> str:
        return f"{self.piece}:{self.vertex}"


@dataclass(frozen=True)
class VertexSpec:
    name: str
    kind: str  # "interior" or "outer"
    incident_pieces: Tuple[str, ...]
    angle_sum_pi: float


@dataclass(frozen=True)
class PieceSpec:
    name: str
    contour_vertices: Tuple[str, ...]
    touches_outer_boundary: bool

    def directed_edges(self) -> Iterator[Tuple[str, str]]:
        cycle = self.contour_vertices
        for index, start in enumerate(cycle):
            yield start, cycle[(index + 1) % len(cycle)]


@dataclass(frozen=True)
class InterfaceView:
    piece: str
    start_vertex: str
    end_vertex: str

    @property
    def start_occurrence(self) -> Occurrence:
        return Occurrence(self.piece, self.start_vertex)

    @property
    def end_occurrence(self) -> Occurrence:
        return Occurrence(self.piece, self.end_vertex)


@dataclass(frozen=True)
class InterfaceSpec:
    name: str
    left_piece: str
    right_piece: str | None
    views: Tuple[InterfaceView, ...]
    is_outer: bool = False

    def __post_init__(self) -> None:
        if self.is_outer:
            if self.right_piece is not None or len(self.views) != 1:
                raise ValueError("An outer interface must have exactly one piece view")
        elif self.right_piece is None or len(self.views) != 2:
            raise ValueError("An internal interface must have exactly two piece views")


@dataclass(frozen=True)
class MapAutomorphism:
    name: str
    piece_map: Tuple[Tuple[str, str], ...]
    vertex_map: Tuple[Tuple[str, str], ...]

    def map_piece(self, piece: str) -> str:
        return dict(self.piece_map)[piece]

    def map_vertex(self, vertex: str) -> str:
        return dict(self.vertex_map)[vertex]

    def map_occurrence(self, occurrence: Occurrence) -> Occurrence:
        return Occurrence(self.map_piece(occurrence.piece), self.map_vertex(occurrence.vertex))


@dataclass(frozen=True)
class PlanarMap:
    name: str
    pieces: Tuple[PieceSpec, ...]
    vertices: Tuple[VertexSpec, ...]
    interfaces: Tuple[InterfaceSpec, ...]
    automorphisms: Tuple[MapAutomorphism, ...]
    reference_piece: str

    def piece_map(self) -> Dict[str, PieceSpec]:
        return {piece.name: piece for piece in self.pieces}

    def vertex_map(self) -> Dict[str, VertexSpec]:
        return {vertex.name: vertex for vertex in self.vertices}

    def internal_interfaces(self) -> Tuple[InterfaceSpec, ...]:
        return tuple(interface for interface in self.interfaces if not interface.is_outer)

    def outer_interfaces(self) -> Tuple[InterfaceSpec, ...]:
        return tuple(interface for interface in self.interfaces if interface.is_outer)

    def occurrences(self) -> Tuple[Occurrence, ...]:
        return tuple(
            Occurrence(piece.name, vertex)
            for piece in self.pieces
            for vertex in piece.contour_vertices
        )

    def validate(self) -> None:
        pieces = self.piece_map()
        vertices = self.vertex_map()
        if self.reference_piece not in pieces:
            raise ValueError("Unknown reference piece")

        occurrence_names = {occurrence.name for occurrence in self.occurrences()}
        if len(occurrence_names) != sum(len(piece.contour_vertices) for piece in self.pieces):
            raise ValueError("Duplicate occurrence in a piece contour")

        for piece in self.pieces:
            if len(piece.contour_vertices) < 3:
                raise ValueError(f"Piece {piece.name} has fewer than three contour vertices")
            if len(set(piece.contour_vertices)) != len(piece.contour_vertices):
                raise ValueError(f"Piece {piece.name} repeats a geometric vertex")
            for vertex in piece.contour_vertices:
                if vertex not in vertices:
                    raise ValueError(f"Unknown vertex {vertex} on piece {piece.name}")

        edge_views: Dict[Tuple[str, frozenset[str]], str] = {}
        for interface in self.interfaces:
            for view in interface.views:
                if view.piece not in pieces:
                    raise ValueError(f"Unknown piece {view.piece} in {interface.name}")
                contour_edges = set(pieces[view.piece].directed_edges())
                if (view.start_vertex, view.end_vertex) not in contour_edges:
                    raise ValueError(
                        f"Interface {interface.name} is not oriented along piece {view.piece}"
                    )
                key = (view.piece, frozenset((view.start_vertex, view.end_vertex)))
                if key in edge_views:
                    raise ValueError(f"Piece edge reused by {interface.name}")
                edge_views[key] = interface.name

        expected_edges = sum(len(piece.contour_vertices) for piece in self.pieces)
        if len(edge_views) != expected_edges:
            raise ValueError(
                f"Interfaces cover {len(edge_views)} piece edges, expected {expected_edges}"
            )

        for vertex in self.vertices:
            actual = tuple(
                sorted(piece.name for piece in self.pieces if vertex.name in piece.contour_vertices)
            )
            if actual != tuple(sorted(vertex.incident_pieces)):
                raise ValueError(f"Incorrect incidence list for vertex {vertex.name}")

        for automorphism in self.automorphisms:
            piece_map = dict(automorphism.piece_map)
            vertex_map = dict(automorphism.vertex_map)
            if set(piece_map) != set(pieces) or set(piece_map.values()) != set(pieces):
                raise ValueError(f"Invalid piece permutation {automorphism.name}")
            if set(vertex_map) != set(vertices) or set(vertex_map.values()) != set(vertices):
                raise ValueError(f"Invalid vertex permutation {automorphism.name}")
            for piece in self.pieces:
                mapped_cycle = tuple(vertex_map[vertex] for vertex in piece.contour_vertices)
                target_cycle = pieces[piece_map[piece.name]].contour_vertices
                if not _cyclic_equal(mapped_cycle, target_cycle) and not _cyclic_equal(
                    mapped_cycle, tuple(reversed(target_cycle))
                ):
                    raise ValueError(
                        f"Automorphism {automorphism.name} does not preserve contour of {piece.name}"
                    )

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "reference_piece": self.reference_piece,
            "pieces": [
                {
                    "name": piece.name,
                    "contour_vertices": list(piece.contour_vertices),
                    "touches_outer_boundary": piece.touches_outer_boundary,
                }
                for piece in self.pieces
            ],
            "vertices": [
                {
                    "name": vertex.name,
                    "kind": vertex.kind,
                    "incident_pieces": list(vertex.incident_pieces),
                    "angle_sum_pi": vertex.angle_sum_pi,
                }
                for vertex in self.vertices
            ],
            "interfaces": [
                {
                    "name": interface.name,
                    "left_piece": interface.left_piece,
                    "right_piece": interface.right_piece,
                    "is_outer": interface.is_outer,
                    "views": [
                        {
                            "piece": view.piece,
                            "start": view.start_vertex,
                            "end": view.end_vertex,
                        }
                        for view in interface.views
                    ],
                }
                for interface in self.interfaces
            ],
            "automorphism_count": len(self.automorphisms),
            "occurrence_count": len(self.occurrences()),
        }


def _cyclic_equal(left: Sequence[str], right: Sequence[str]) -> bool:
    if len(left) != len(right):
        return False
    if not left:
        return True
    doubled = tuple(right) + tuple(right)
    size = len(left)
    return any(tuple(left) == doubled[offset : offset + size] for offset in range(size))
