from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import networkx as nx

from formal_disk4.maps.base import (
    InterfaceSpec,
    InterfaceView,
    MapAutomorphism,
    Occurrence,
    PieceSpec,
    PlanarMap,
    ProblemHypotheses,
    VertexSpec,
)
from formal_disk4.maps.registry import build_map


OUTSIDE = -1
GRAPH_SPACE_VERSION = "dual-planar-graph-space-v1"


def _canonical_cycle(values: Sequence[int]) -> tuple[int, ...]:
    cycle = tuple(int(value) for value in values)
    if not cycle:
        return ()
    variants = []
    for oriented in (cycle, tuple(reversed(cycle))):
        variants.extend(
            oriented[offset:] + oriented[:offset] for offset in range(len(oriented))
        )
    return min(variants)


def _cyclic_equal(left: Sequence[int], right: Sequence[int]) -> bool:
    left = tuple(left)
    right = tuple(right)
    if len(left) != len(right):
        return False
    return any(
        left == right[offset:] + right[:offset] for offset in range(len(right))
    )


def _permutation_order(permutation: Sequence[int]) -> int:
    unseen = set(range(len(permutation)))
    result = 1
    while unseen:
        seed = min(unseen)
        current = seed
        length = 0
        while current in unseen:
            unseen.remove(current)
            current = int(permutation[current])
            length += 1
        result = math.lcm(result, max(1, length))
    return result


def _graph_from_edges(tile_count: int, edges: Sequence[Sequence[int]]) -> nx.Graph:
    graph = nx.Graph()
    graph.add_nodes_from((OUTSIDE, *range(int(tile_count))))
    graph.add_edges_from((int(left), int(right)) for left, right in edges)
    nx.set_node_attributes(
        graph, {node: node == OUTSIDE for node in graph}, "outside"
    )
    return graph


def _normalized_graph(graph: nx.Graph) -> nx.Graph:
    if OUTSIDE not in graph:
        raise ValueError("A dual graph must contain the outside node -1")
    tiles = sorted(int(node) for node in graph if int(node) != OUTSIDE)
    relabel = {old: new for new, old in enumerate(tiles)}
    relabel[OUTSIDE] = OUTSIDE
    result = nx.relabel_nodes(graph, relabel, copy=True)
    nx.set_node_attributes(
        result, {node: node == OUTSIDE for node in result}, "outside"
    )
    return result


def validate_dual_graph(graph: nx.Graph, *, maximum_tiles: int = 13) -> None:
    tiles = tuple(node for node in graph if node != OUTSIDE)
    if not 3 <= len(tiles) <= int(maximum_tiles):
        raise ValueError("A graph-lab candidate needs between 3 and maximum_tiles tiles")
    if graph.is_multigraph() or nx.number_of_selfloops(graph):
        raise ValueError("Only simple dual graphs are supported")
    if set(graph) != {OUTSIDE, *range(len(tiles))}:
        raise ValueError("Tile nodes must be consecutively labelled from zero")
    if not nx.is_connected(graph):
        raise ValueError("The dual graph must be connected")
    planar, _embedding = nx.check_planarity(graph, counterexample=False)
    if not planar:
        raise ValueError("The dual graph must be planar")
    # Three-connectivity gives a unique cellular embedding up to reflection.
    # It also guarantees at least three contour vertices on every tile.
    if nx.node_connectivity(graph) < 3:
        raise ValueError("The first graph space requires a 3-connected dual graph")


def _embedding(graph: nx.Graph) -> nx.PlanarEmbedding:
    planar, embedding = nx.check_planarity(graph, counterexample=False)
    if not planar:
        raise ValueError("The dual graph is not planar")
    embedding.check_structure()
    return embedding


def _faces(
    embedding: nx.PlanarEmbedding,
) -> tuple[tuple[tuple[int, ...], ...], dict[tuple[int, int], int]]:
    visited: set[tuple[int, int]] = set()
    raw: list[tuple[int, ...]] = []
    for left in sorted(embedding, key=lambda value: (value != OUTSIDE, value)):
        for right in embedding.neighbors_cw_order(left):
            if (left, right) in visited:
                continue
            raw.append(tuple(embedding.traverse_face(left, right, visited)))
    ordered = sorted(raw, key=_canonical_cycle)
    halfedge_face: dict[tuple[int, int], int] = {}
    for face_index, face in enumerate(ordered):
        for index, left in enumerate(face):
            halfedge_face[(left, face[(index + 1) % len(face)])] = face_index
    return tuple(ordered), halfedge_face


def _automorphism_permutations(graph: nx.Graph) -> tuple[tuple[int, ...], ...]:
    matcher = nx.algorithms.isomorphism.GraphMatcher(
        graph,
        graph,
        node_match=lambda left, right: bool(left.get("outside"))
        == bool(right.get("outside")),
    )
    output = {
        tuple(int(mapping[index]) for index in range(len(graph) - 1))
        for mapping in matcher.isomorphisms_iter()
        if int(mapping[OUTSIDE]) == OUTSIDE
    }
    return tuple(sorted(output))


def _direct_automorphisms(graph: nx.Graph) -> tuple[tuple[int, ...], ...]:
    embedding = _embedding(graph)
    rotations = {
        node: tuple(embedding.neighbors_cw_order(node)) for node in embedding
    }
    direct: list[tuple[int, ...]] = []
    for permutation in _automorphism_permutations(graph):
        mapping = {OUTSIDE: OUTSIDE}
        mapping.update({index: permutation[index] for index in range(len(permutation))})
        preserving = True
        reversing = True
        for source, rotation in rotations.items():
            mapped = tuple(mapping[value] for value in rotation)
            target = rotations[mapping[source]]
            preserving &= _cyclic_equal(mapped, target)
            reversing &= _cyclic_equal(mapped, tuple(reversed(target)))
        if preserving and not reversing:
            direct.append(permutation)
        elif preserving and permutation == tuple(range(len(permutation))):
            direct.append(permutation)
    return tuple(sorted(set(direct)))


@dataclass(frozen=True)
class DualGraphCandidate:
    tile_count: int
    edges: tuple[tuple[int, int], ...]
    imposed_permutation: tuple[int, ...] | None
    origin: str
    mutation: str
    parent_id: str | None = None
    source_map_name: str | None = None
    source_symmetry: str | None = None

    @property
    def graph_id(self) -> str:
        payload = {
            "version": GRAPH_SPACE_VERSION,
            "tiles": self.tile_count,
            "edges": self.edges,
            "imposed": self.imposed_permutation,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return "dg-" + hashlib.sha256(encoded).hexdigest()[:32]

    @property
    def symmetry_order(self) -> int:
        return (
            _permutation_order(self.imposed_permutation)
            if self.imposed_permutation is not None
            else 1
        )

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    @property
    def is_simple_ring(self) -> bool:
        """Whether this is exactly an outside star plus one tile cycle."""

        if self.tile_count < 3 or len(self.edges) != 2 * self.tile_count:
            return False
        edges = {
            tuple(sorted((int(left), int(right)))) for left, right in self.edges
        }
        if len(edges) != len(self.edges):
            return False
        tiles = set(range(self.tile_count))
        outside = {(OUTSIDE, tile) for tile in tiles}
        if not outside.issubset(edges):
            return False
        internal = edges - outside
        if len(internal) != self.tile_count:
            return False
        adjacency = {tile: set() for tile in tiles}
        for left, right in internal:
            if left not in tiles or right not in tiles:
                return False
            adjacency[left].add(right)
            adjacency[right].add(left)
        if any(len(neighbours) != 2 for neighbours in adjacency.values()):
            return False
        seen = {0}
        pending = [0]
        while pending:
            for neighbour in adjacency[pending.pop()]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    pending.append(neighbour)
        return seen == tiles

    def graph(self) -> nx.Graph:
        return _graph_from_edges(self.tile_count, self.edges)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": GRAPH_SPACE_VERSION,
            "graph_id": self.graph_id,
            "tile_count": self.tile_count,
            "edges": [list(edge) for edge in self.edges],
            "imposed_permutation": (
                list(self.imposed_permutation)
                if self.imposed_permutation is not None
                else None
            ),
            "symmetry_order": self.symmetry_order,
            "origin": self.origin,
            "mutation": self.mutation,
            "parent_id": self.parent_id,
            "source_map_name": self.source_map_name,
            "source_symmetry": self.source_symmetry,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "DualGraphCandidate":
        raw_permutation = payload.get("imposed_permutation")
        return cls(
            tile_count=int(payload["tile_count"]),
            edges=tuple(
                sorted(
                    (min(int(left), int(right)), max(int(left), int(right)))
                    for left, right in payload["edges"]  # type: ignore[misc]
                )
            ),
            imposed_permutation=(
                tuple(int(value) for value in raw_permutation)  # type: ignore[arg-type]
                if raw_permutation is not None
                else None
            ),
            origin=str(payload.get("origin", "restored")),
            mutation=str(payload.get("mutation", "restored")),
            parent_id=(
                str(payload["parent_id"]) if payload.get("parent_id") else None
            ),
            source_map_name=(
                str(payload["source_map_name"])
                if payload.get("source_map_name")
                else None
            ),
            source_symmetry=(
                str(payload["source_symmetry"])
                if payload.get("source_symmetry")
                else None
            ),
        )


@dataclass(frozen=True)
class DynamicPlanarMap:
    planar_map: PlanarMap
    imposed_automorphism: str | None
    imposed_equivariance_mode: str | None
    automorphism_orders: tuple[int, ...]


def _equivariance_mode(
    planar_map: PlanarMap, automorphism_name: str | None
) -> str | None:
    """Choose pointwise equivariance only when every piece orbit closes it.

    A rotation may fix a central piece while rotating the vertices on its
    contour.  Its one-piece orbit then cannot close a pointwise contour
    assignment; the imposed symmetry must instead be expressed as a cyclic
    shift of the weak order.
    """

    if automorphism_name is None:
        return None
    automorphism = next(
        item for item in planar_map.automorphisms if item.name == automorphism_name
    )
    unseen = {piece.name for piece in planar_map.pieces}
    pieces = planar_map.piece_map()
    while unseen:
        seed = min(unseen)
        orbit = []
        current = seed
        while current not in orbit:
            orbit.append(current)
            unseen.discard(current)
            current = automorphism.map_piece(current)
        if current != seed:
            raise ValueError("Imposed automorphism piece map is not a permutation")
        for vertex in pieces[seed].contour_vertices:
            occurrence = Occurrence(seed, vertex)
            mapped = occurrence
            for _step in orbit:
                mapped = automorphism.map_occurrence(mapped)
            if mapped != occurrence:
                return "cyclic_shift"
    return "pointwise"


def _view_for_contour_edge(
    piece: str, contour: Sequence[str], first: str, second: str
) -> InterfaceView:
    target = frozenset((first, second))
    for index, start in enumerate(contour):
        end = contour[(index + 1) % len(contour)]
        if frozenset((start, end)) == target:
            return InterfaceView(piece, start, end)
    raise ValueError(f"No contour edge {first}-{second} on {piece}")


def build_dynamic_planar_map(candidate: DualGraphCandidate) -> DynamicPlanarMap:
    if candidate.source_map_name is not None:
        source = build_map(candidate.source_map_name)
        orders = tuple(
            _permutation_order(
                tuple(
                    next(
                        index
                        for index, piece in enumerate(source.pieces)
                        if piece.name == automorphism.map_piece(source_piece.name)
                    )
                    for source_piece in source.pieces
                )
            )
            for automorphism in source.automorphisms
        )
        return DynamicPlanarMap(
            source,
            candidate.source_symmetry,
            _equivariance_mode(source, candidate.source_symmetry),
            orders,
        )

    graph = candidate.graph()
    validate_dual_graph(graph, maximum_tiles=candidate.tile_count)
    embedding = _embedding(graph)
    faces, halfedge_face = _faces(embedding)
    face_names = tuple(f"V{index}" for index in range(len(faces)))
    piece_names = tuple(f"T{index}" for index in range(candidate.tile_count))

    contours: dict[int, tuple[str, ...]] = {}
    for node in range(candidate.tile_count):
        # PlanarEmbedding lists dual neighbours clockwise.  A primal tile
        # boundary therefore uses the opposite orientation: keeping the dual
        # order would reverse every directed interface, including the hard
        # outer arcs consumed by the pre-word topology filters.
        contours[node] = tuple(
            reversed(
                tuple(
                    face_names[halfedge_face[(node, neighbor)]]
                    for neighbor in embedding.neighbors_cw_order(node)
                )
            )
        )

    vertices = tuple(
        VertexSpec(
            face_names[index],
            "outer" if OUTSIDE in face else "interior",
            tuple(piece_names[node] for node in face if node != OUTSIDE),
            1.0 if OUTSIDE in face else 2.0,
        )
        for index, face in enumerate(faces)
    )
    outer_vertex_names = {
        face_names[index] for index, face in enumerate(faces) if OUTSIDE in face
    }
    pieces = []
    for node, name in enumerate(piece_names):
        has_outer_arc = graph.has_edge(node, OUTSIDE)
        has_outer_point = any(vertex in outer_vertex_names for vertex in contours[node])
        contact = "arc" if has_outer_arc else ("point" if has_outer_point else "none")
        pieces.append(
            PieceSpec(
                name,
                contours[node],
                contact != "none",
                contact,
            )
        )

    interfaces: list[InterfaceSpec] = []
    for left, right in sorted(
        graph.edges(), key=lambda edge: tuple(sorted(edge))
    ):
        if left == OUTSIDE or right == OUTSIDE:
            tile = right if left == OUTSIDE else left
            first = face_names[halfedge_face[(tile, OUTSIDE)]]
            second = face_names[halfedge_face[(OUTSIDE, tile)]]
            interfaces.append(
                InterfaceSpec(
                    f"outer-{piece_names[tile]}",
                    piece_names[tile],
                    None,
                    (
                        _view_for_contour_edge(
                            piece_names[tile], contours[tile], first, second
                        ),
                    ),
                    is_outer=True,
                )
            )
            continue
        first = face_names[halfedge_face[(left, right)]]
        second = face_names[halfedge_face[(right, left)]]
        interfaces.append(
            InterfaceSpec(
                f"{piece_names[left]}-{piece_names[right]}",
                piece_names[left],
                piece_names[right],
                (
                    _view_for_contour_edge(
                        piece_names[left], contours[left], first, second
                    ),
                    _view_for_contour_edge(
                        piece_names[right], contours[right], first, second
                    ),
                ),
            )
        )

    face_index = {_canonical_cycle(face): index for index, face in enumerate(faces)}
    permutations = _automorphism_permutations(graph)
    automorphisms: list[MapAutomorphism] = []
    imposed_name = None
    orders: list[int] = []
    for index, permutation in enumerate(permutations):
        mapping = {OUTSIDE: OUTSIDE}
        mapping.update({node: permutation[node] for node in range(candidate.tile_count)})
        vertex_map = []
        for source_index, face in enumerate(faces):
            mapped_face = _canonical_cycle(tuple(mapping[node] for node in face))
            target_index = face_index.get(mapped_face)
            if target_index is None:
                break
            vertex_map.append((face_names[source_index], face_names[target_index]))
        else:
            name = "identity" if permutation == tuple(range(candidate.tile_count)) else f"auto_{index:03d}"
            automorphisms.append(
                MapAutomorphism(
                    name=name,
                    piece_map=tuple(
                        (piece_names[node], piece_names[permutation[node]])
                        for node in range(candidate.tile_count)
                    ),
                    vertex_map=tuple(vertex_map),
                )
            )
            orders.append(_permutation_order(permutation))
            if candidate.imposed_permutation == permutation:
                imposed_name = name

    result = PlanarMap(
        name=f"graph-lab-{candidate.graph_id[3:15]}",
        pieces=tuple(pieces),
        vertices=vertices,
        interfaces=tuple(interfaces),
        automorphisms=tuple(automorphisms),
        reference_piece=piece_names[0],
        hypotheses=ProblemHypotheses(
            piecewise_c2_boundary=True,
            center_strictly_inside_one_tile=False,
        ),
    )
    result.validate()
    if candidate.imposed_permutation is not None and imposed_name is None:
        raise ValueError("The imposed permutation does not preserve the chosen embedding")
    return DynamicPlanarMap(
        result,
        imposed_name,
        _equivariance_mode(result, imposed_name),
        tuple(orders),
    )


def candidate_from_planar_map(
    map_name: str,
    *,
    imposed_automorphism: str | None,
    origin: str = "catalog_oracle",
) -> DualGraphCandidate:
    planar_map = build_map(map_name)
    piece_index = {piece.name: index for index, piece in enumerate(planar_map.pieces)}
    graph = nx.Graph()
    graph.add_nodes_from((OUTSIDE, *range(len(planar_map.pieces))))
    for interface in planar_map.interfaces:
        left = piece_index[interface.left_piece]
        right = OUTSIDE if interface.is_outer else piece_index[interface.right_piece]
        if graph.has_edge(left, right):
            raise ValueError(f"Map {map_name!r} has repeated dual edges")
        graph.add_edge(left, right)
    graph = _normalized_graph(graph)
    validate_dual_graph(graph, maximum_tiles=len(planar_map.pieces))
    permutation = None
    if imposed_automorphism is not None:
        automorphism = next(
            item
            for item in planar_map.automorphisms
            if item.name == imposed_automorphism
        )
        permutation = tuple(
            piece_index[automorphism.map_piece(piece.name)]
            for piece in planar_map.pieces
        )
    edges = tuple(sorted((min(left, right), max(left, right)) for left, right in graph.edges()))
    return DualGraphCandidate(
        tile_count=len(planar_map.pieces),
        edges=edges,
        imposed_permutation=permutation,
        origin=origin,
        mutation="catalog_seed",
        source_map_name=map_name,
        source_symmetry=imposed_automorphism,
    )


class GraphSpace:
    """Constructive sampler for simple 3-connected planar dual graphs."""

    def __init__(
        self,
        *,
        maximum_tiles: int = 13,
        size_growth_factor: float = 1.4,
        symmetric_prior_fraction: float = 0.45,
        imposed_symmetry_bias: float = 0.75,
        symmetry_order_bias: float = 1.5,
        symmetric_edge_subset_fraction: float = 0.20,
        symmetric_edge_subset_attempts: int = 24,
        exclude_rings: bool = False,
    ) -> None:
        self.maximum_tiles = max(3, min(13, int(maximum_tiles)))
        self.exclude_rings = bool(exclude_rings)
        if self.exclude_rings and self.maximum_tiles < 4:
            raise ValueError(
                "Excluding simple rings leaves no valid 3-connected graph "
                "when maximum_tiles is below four"
            )
        self.size_growth_factor = float(size_growth_factor)
        if not math.isfinite(self.size_growth_factor) or self.size_growth_factor <= 0:
            raise ValueError("size_growth_factor must be finite and strictly positive")
        self.symmetric_prior_fraction = min(1.0, max(0.0, float(symmetric_prior_fraction)))
        self.imposed_symmetry_bias = min(1.0, max(0.0, float(imposed_symmetry_bias)))
        self.symmetry_order_bias = max(0.0, float(symmetry_order_bias))
        self.symmetric_edge_subset_fraction = min(
            1.0, max(0.0, float(symmetric_edge_subset_fraction))
        )
        self.symmetric_edge_subset_attempts = max(
            1, int(symmetric_edge_subset_attempts)
        )

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> "GraphSpace":
        return cls(
            maximum_tiles=int(config.get("maximum_tiles", 13)),
            size_growth_factor=float(config.get("size_growth_factor", 1.4)),
            symmetric_prior_fraction=float(
                config.get("symmetric_prior_fraction", 0.45)
            ),
            imposed_symmetry_bias=float(config.get("imposed_symmetry_bias", 0.75)),
            symmetry_order_bias=float(config.get("symmetry_order_bias", 1.5)),
            symmetric_edge_subset_fraction=float(
                config.get("symmetric_edge_subset_fraction", 0.20)
            ),
            symmetric_edge_subset_attempts=int(
                config.get("symmetric_edge_subset_attempts", 24)
            ),
            exclude_rings=bool(config.get("exclude_rings", False)),
        )

    def size_sampling_distribution(self) -> tuple[tuple[int, float], ...]:
        """Return the tempered combinatorial prior over tile counts.

        Even a uniform distribution over sizes massively over-represents each
        small topology, because the number of planar graph classes grows very
        quickly with the number of vertices.  We therefore give every extra
        tile a configurable multiplicative amount of proposal mass.  A factor
        greater than one favours larger domains, one is uniform by size, and a
        factor below one remains available for deliberately small searches.

        This is intentionally a tempered proxy rather than an attempted exact
        enumeration of graph classes.  Every permitted size keeps strictly
        positive probability.
        """

        minimum = 4 if self.exclude_rings else 3
        sizes = tuple(range(minimum, self.maximum_tiles + 1))
        raw = tuple(
            self.size_growth_factor ** (size - minimum) for size in sizes
        )
        total = math.fsum(raw)
        return tuple((size, weight / total) for size, weight in zip(sizes, raw))

    def size_sampling_weight(self, tile_count: int) -> float:
        """Unnormalised size weight, also used by mutation-parent sampling."""

        minimum = 4 if self.exclude_rings else 3
        return self.size_growth_factor ** (int(tile_count) - minimum)

    def _sample_size(self, rng: random.Random) -> int:
        distribution = self.size_sampling_distribution()
        sizes = tuple(size for size, _probability in distribution)
        weights = tuple(probability for _size, probability in distribution)
        return int(rng.choices(sizes, weights=weights, k=1)[0])

    def _choose_symmetry(
        self, graph: nx.Graph, rng: random.Random
    ) -> tuple[int, ...] | None:
        identity = tuple(range(len(graph) - 1))
        nontrivial = [
            permutation
            for permutation in _direct_automorphisms(graph)
            if permutation != identity
        ]
        if not nontrivial or rng.random() >= self.imposed_symmetry_bias:
            return None
        weights = tuple(max(1, _permutation_order(item) - 1) for item in nontrivial)
        return rng.choices(nontrivial, weights=weights, k=1)[0]

    def _candidate(
        self,
        graph: nx.Graph,
        rng: random.Random,
        *,
        origin: str,
        mutation: str,
        parent_id: str | None = None,
    ) -> DualGraphCandidate:
        graph = _normalized_graph(graph)
        validate_dual_graph(graph, maximum_tiles=self.maximum_tiles)
        edges = tuple(
            sorted((min(left, right), max(left, right)) for left, right in graph.edges())
        )
        return DualGraphCandidate(
            tile_count=len(graph) - 1,
            edges=edges,
            imposed_permutation=self._choose_symmetry(graph, rng),
            origin=origin,
            mutation=mutation,
            parent_id=parent_id,
        )

    @staticmethod
    def _ring_graph(tile_count: int) -> nx.Graph:
        graph = nx.Graph()
        graph.add_nodes_from((OUTSIDE, *range(tile_count)))
        for index in range(tile_count):
            graph.add_edge(index, (index + 1) % tile_count)
            graph.add_edge(OUTSIDE, index)
        return graph

    def _random_polyhedral_graph(
        self, tile_count: int, rng: random.Random
    ) -> nx.Graph:
        graph = nx.complete_graph((OUTSIDE, 0, 1, 2))
        for node in range(3, tile_count):
            embedding = _embedding(graph)
            faces, _lookup = _faces(embedding)
            face = rng.choice(faces)
            graph.add_node(node)
            graph.add_edges_from((node, target) for target in face)

        # Diagonal flips move away from the stacked-triangulation seed. The
        # flip graph connects planar triangulations, so repeated proposals can
        # reach non-stacked structures without ever proposing a non-planar map.
        for _ in range(tile_count * 6):
            flipped = self._edge_flip(graph, rng)
            if flipped is not None:
                graph = flipped

        removable = list(graph.edges())
        rng.shuffle(removable)
        for edge in removable:
            if rng.random() >= 0.35:
                continue
            proposal = graph.copy()
            proposal.remove_edge(*edge)
            try:
                validate_dual_graph(
                    _normalized_graph(proposal), maximum_tiles=self.maximum_tiles
                )
            except ValueError:
                continue
            graph = proposal
        return graph

    @staticmethod
    def _mapped_edge(
        edge: tuple[int, int], permutation: tuple[int, ...]
    ) -> tuple[int, int]:
        left, right = edge
        mapped_left = OUTSIDE if left == OUTSIDE else permutation[left]
        mapped_right = OUTSIDE if right == OUTSIDE else permutation[right]
        return (min(mapped_left, mapped_right), max(mapped_left, mapped_right))

    @classmethod
    def _edge_orbit(
        cls,
        edge: tuple[int, int],
        permutation: tuple[int, ...],
    ) -> tuple[tuple[int, int], ...]:
        canonical = (min(edge), max(edge))
        orbit = []
        current = canonical
        while current not in orbit:
            orbit.append(current)
            current = cls._mapped_edge(current, permutation)
        return tuple(sorted(orbit))

    def _candidate_preserving_symmetry(
        self,
        graph: nx.Graph,
        permutation: tuple[int, ...],
        *,
        origin: str,
        mutation: str,
        parent_id: str | None,
    ) -> DualGraphCandidate:
        graph = _normalized_graph(graph)
        validate_dual_graph(graph, maximum_tiles=self.maximum_tiles)
        tile_count = len(graph) - 1
        if sorted(permutation) != list(range(tile_count)):
            raise ValueError("The imposed permutation does not cover every tile")
        edges = {
            (min(left, right), max(left, right)) for left, right in graph.edges()
        }
        if any(
            self._mapped_edge(edge, permutation) not in edges for edge in edges
        ):
            raise ValueError("The equivariant mutation broke the imposed symmetry")
        if permutation not in _direct_automorphisms(graph):
            raise ValueError(
                "The imposed cyclic action is not an orientation-preserving "
                "automorphism of the planar embedding"
            )
        return DualGraphCandidate(
            tile_count=tile_count,
            edges=tuple(sorted(edges)),
            imposed_permutation=permutation,
            origin=origin,
            mutation=mutation,
            parent_id=parent_id,
        )

    @staticmethod
    def _feasible_symmetry_orders(tile_count: int) -> tuple[int, ...]:
        """Orders of orientation-preserving cyclic actions on a sphere.

        A non-identity finite rotation of the sphere has two fixed points.  The
        distinguished outside vertex consumes one of them, so tile vertices
        consist of full orbits of length ``order`` and at most one fixed tile.
        This is both more general and more accurate than naming a catalog
        family such as rings or double rings.
        """

        return tuple(
            order
            for order in range(2, int(tile_count) + 1)
            if int(tile_count) % order in (0, 1)
        )

    @staticmethod
    def _cyclic_permutation(tile_count: int, order: int) -> tuple[int, ...]:
        if order < 2 or tile_count % order not in (0, 1):
            raise ValueError("Invalid cyclic action for this number of tiles")
        permutation = list(range(tile_count))
        moving_tiles = tile_count - tile_count % order
        for start in range(0, moving_tiles, order):
            for offset in range(order):
                permutation[start + offset] = start + (offset + 1) % order
        result = tuple(permutation)
        if _permutation_order(result) != order:
            raise ValueError("Generated permutation has the wrong order")
        return result

    def _choose_cyclic_action(
        self, tile_count: int, rng: random.Random
    ) -> tuple[int, tuple[int, ...]] | None:
        orders = self._feasible_symmetry_orders(tile_count)
        if not orders:
            return None
        # The additive floor keeps every feasible order reachable even when a
        # strong high-order bias is requested.
        weights = tuple(0.25 + order**self.symmetry_order_bias for order in orders)
        order = int(rng.choices(orders, weights=weights, k=1)[0])
        return order, self._cyclic_permutation(tile_count, order)

    def _all_edge_orbits(
        self, tile_count: int, permutation: tuple[int, ...]
    ) -> tuple[tuple[tuple[int, int], ...], ...]:
        nodes = (OUTSIDE, *range(tile_count))
        return tuple(
            sorted(
                {
                    self._edge_orbit((left, right), permutation)
                    for left_index, left in enumerate(nodes)
                    for right in nodes[left_index + 1 :]
                }
            )
        )

    def _sample_invariant_edge_subset(
        self,
        tile_count: int,
        permutation: tuple[int, ...],
        rng: random.Random,
        *,
        attempts: int | None = None,
    ) -> DualGraphCandidate | None:
        """Sample complete edge orbits without assuming a graph family.

        Every invariant labelled simple graph is a union of these edge orbits.
        Every orbit is independently included with a probability strictly
        between zero and one, so every graph admitting the selected action has
        non-zero probability of being proposed.  Planarity, 3-connectivity and
        directness are rejection conditions, not generator-specific shortcuts.
        """

        orbits = self._all_edge_orbits(tile_count, permutation)
        vertex_count = tile_count + 1
        minimum_edges = math.ceil(3 * vertex_count / 2)
        maximum_edges = 3 * vertex_count - 6
        total_edges = vertex_count * (vertex_count - 1) // 2
        for _attempt in range(
            self.symmetric_edge_subset_attempts if attempts is None else attempts
        ):
            target_edges = rng.randint(minimum_edges, maximum_edges)
            probability = min(0.80, max(0.08, target_edges / total_edges))
            graph = nx.Graph()
            graph.add_nodes_from((OUTSIDE, *range(tile_count)))
            for orbit in orbits:
                if rng.random() < probability:
                    graph.add_edges_from(orbit)
            if not minimum_edges <= graph.number_of_edges() <= maximum_edges:
                continue
            if any(degree < 3 for _node, degree in graph.degree()):
                continue
            if not nx.is_connected(graph):
                continue
            if not nx.check_planarity(graph, counterexample=False)[0]:
                continue
            if nx.node_connectivity(graph) < 3:
                continue
            try:
                candidate = self._candidate_preserving_symmetry(
                    graph,
                    permutation,
                    origin="prior",
                    mutation="symmetric_edge_orbit_subset",
                    parent_id=None,
                )
            except (ValueError, nx.NetworkXError):
                continue
            if self.exclude_rings and candidate.is_simple_ring:
                continue
            return candidate
        return None

    def _symmetric_scaffold(
        self,
        tile_count: int,
        order: int,
        permutation: tuple[int, ...],
        rng: random.Random,
    ) -> DualGraphCandidate | None:
        """Build a generic cyclic planar scaffold from orbit data alone.

        Free tile orbits are arranged into one or more equal cyclic shells.  A
        possible fixed tile caps the innermost shell.  The construction knows
        only ``tile_count`` and the abstract group action; no catalog topology
        or known positive graph is consulted.
        """

        fixed_count = tile_count % order
        moving_tiles = tile_count - fixed_count
        orbit_count = moving_tiles // order
        orbit_blocks = tuple(
            tuple(range(start, start + order))
            for start in range(0, moving_tiles, order)
        )
        divisors = [
            width
            for width in range(1, orbit_count + 1)
            if orbit_count % width == 0 and width * order >= 3
        ]
        if self.exclude_rings and fixed_count == 0:
            nonring_divisors = [width for width in divisors if width < orbit_count]
            if nonring_divisors:
                divisors = nonring_divisors
        if not divisors:
            return None
        shell_width = int(rng.choice(divisors))
        shell_count = orbit_count // shell_width
        shells: list[tuple[int, ...]] = []
        for shell_index in range(shell_count):
            blocks = orbit_blocks[
                shell_index * shell_width : (shell_index + 1) * shell_width
            ]
            shell = tuple(
                blocks[block_index][phase]
                for phase in range(order)
                for block_index in range(shell_width)
            )
            shells.append(shell)

        graph = nx.Graph()
        graph.add_nodes_from((OUTSIDE, *range(tile_count)))
        for shell in shells:
            for index, node in enumerate(shell):
                graph.add_edge(node, shell[(index + 1) % len(shell)])
        graph.add_edges_from((OUTSIDE, node) for node in shells[0])
        for outer, inner in zip(shells, shells[1:]):
            phase = rng.randrange(len(inner))
            graph.add_edges_from(
                (node, inner[(index + phase) % len(inner)])
                for index, node in enumerate(outer)
            )
        if fixed_count:
            fixed_tile = tile_count - 1
            graph.add_edges_from((fixed_tile, node) for node in shells[-1])
            # The smallest half-turn action has only two moving vertices.  Its
            # unique 3-connected scaffold is K4, whose two fixed vertices are
            # also adjacent.
            if len(shells[-1]) == 2:
                graph.add_edge(OUTSIDE, fixed_tile)
        try:
            candidate = self._candidate_preserving_symmetry(
                graph,
                permutation,
                origin="prior",
                mutation="symmetric_orbit_scaffold",
                parent_id=None,
            )
        except (ValueError, nx.NetworkXError):
            return None
        if self.exclude_rings and candidate.is_simple_ring:
            return None
        return candidate

    def _mutate_equivariant_edges(
        self, parent: DualGraphCandidate, rng: random.Random
    ) -> DualGraphCandidate | None:
        """Apply one whole edge-orbit edit under the imposed permutation.

        Local single-edge mutations almost always destroy a high-order
        automorphism.  Editing the complete orbit provides a genuine random
        neighbourhood of symmetric structures without replaying a catalog case
        directly.
        """

        permutation = parent.imposed_permutation
        if permutation is None or parent.symmetry_order <= 1:
            return None
        base = parent.graph()
        existing = {
            (min(left, right), max(left, right)) for left, right in base.edges()
        }
        possible = {
            (min(left, right), max(left, right))
            for left, right in nx.non_edges(base)
        }
        actions = ["symmetric_edge_add", "symmetric_edge_delete"]
        rng.shuffle(actions)
        for action in actions:
            source = possible if action == "symmetric_edge_add" else existing
            orbits = list(
                {
                    self._edge_orbit(edge, permutation)
                    for edge in source
                }
            )
            rng.shuffle(orbits)
            for orbit in orbits:
                proposal = base.copy()
                if action == "symmetric_edge_add":
                    proposal.add_edges_from(orbit)
                    if not nx.check_planarity(proposal, counterexample=False)[0]:
                        continue
                else:
                    proposal.remove_edges_from(orbit)
                    if nx.node_connectivity(proposal) < 3:
                        continue
                try:
                    candidate = self._candidate_preserving_symmetry(
                        proposal,
                        permutation,
                        origin="mutation",
                        mutation=action,
                        parent_id=parent.graph_id,
                    )
                except (ValueError, nx.NetworkXError):
                    continue
                if candidate.graph_id != parent.graph_id:
                    return candidate
        return None

    def _sample_symmetric_prior(
        self, tile_count: int, rng: random.Random
    ) -> DualGraphCandidate | None:
        """Sample a general high-order cyclic graph with no catalog knowledge."""

        def apply_imposition(candidate: DualGraphCandidate) -> DualGraphCandidate:
            if rng.random() < self.imposed_symmetry_bias:
                return candidate
            return DualGraphCandidate(
                tile_count=candidate.tile_count,
                edges=candidate.edges,
                imposed_permutation=None,
                origin=candidate.origin,
                mutation=candidate.mutation + ":symmetry_unconstrained",
            )

        for _attempt in range(16):
            action = self._choose_cyclic_action(tile_count, rng)
            if action is None:
                return None
            order, permutation = action
            if rng.random() < self.symmetric_edge_subset_fraction:
                complete = self._sample_invariant_edge_subset(
                    tile_count, permutation, rng
                )
                if complete is not None:
                    return apply_imposition(complete)
            current = self._symmetric_scaffold(
                tile_count, order, permutation, rng
            )
            if current is None:
                # This also gives difficult orbit types a full-support chance
                # when the cheap shell scaffold has no valid realization.
                current = self._sample_invariant_edge_subset(
                    tile_count, permutation, rng
                )
                if current is None:
                    continue
            mutations = []
            for _step in range(rng.randrange(0, 7)):
                mutated = self._mutate_equivariant_edges(current, rng)
                if mutated is None:
                    break
                current = mutated
                mutations.append(mutated.mutation)
            if self.exclude_rings and current.is_simple_ring:
                continue
            if mutations:
                current = DualGraphCandidate(
                    tile_count=current.tile_count,
                    edges=current.edges,
                    imposed_permutation=current.imposed_permutation,
                    origin="prior",
                    mutation="symmetric_orbit_walk:" + "+".join(mutations),
                )
            return apply_imposition(current)
        return None

    @staticmethod
    def _edge_flip(graph: nx.Graph, rng: random.Random) -> nx.Graph | None:
        embedding = _embedding(graph)
        edges = list(graph.edges())
        rng.shuffle(edges)
        for left, right in edges:
            first = tuple(embedding.traverse_face(left, right))
            second = tuple(embedding.traverse_face(right, left))
            if len(first) != 3 or len(second) != 3:
                continue
            opposite_left = next(node for node in first if node not in (left, right))
            opposite_right = next(node for node in second if node not in (left, right))
            if opposite_left == opposite_right or graph.has_edge(opposite_left, opposite_right):
                continue
            proposal = graph.copy()
            proposal.remove_edge(left, right)
            proposal.add_edge(opposite_left, opposite_right)
            planar, _ = nx.check_planarity(proposal, counterexample=False)
            if planar and nx.node_connectivity(proposal) >= 3:
                return proposal
        return None

    def sample_prior(self, rng: random.Random) -> DualGraphCandidate:
        tile_count = self._sample_size(rng)
        if rng.random() < self.symmetric_prior_fraction:
            symmetric = self._sample_symmetric_prior(tile_count, rng)
            if symmetric is not None:
                return symmetric
        for _attempt in range(40):
            graph = self._random_polyhedral_graph(tile_count, rng)
            candidate = self._candidate(
                graph, rng, origin="prior", mutation="random_polyhedral"
            )
            if not (self.exclude_rings and candidate.is_simple_ring):
                return candidate
        # This can only be reached in a very small, heavily constrained graph
        # space.  Retry through the general symmetric sampler rather than
        # leaking an explicitly excluded topology to the caller.
        symmetric = self._sample_symmetric_prior(tile_count, rng)
        if symmetric is not None:
            return symmetric
        raise RuntimeError("Could not sample a non-ring 3-connected planar graph")

    def mutate(
        self, parent: DualGraphCandidate, rng: random.Random
    ) -> DualGraphCandidate | None:
        if (
            parent.imposed_permutation is not None
            and parent.symmetry_order > 1
            and rng.random() < self.imposed_symmetry_bias
        ):
            equivariant = self._mutate_equivariant_edges(parent, rng)
            if equivariant is not None and not (
                self.exclude_rings and equivariant.is_simple_ring
            ):
                return equivariant
        base = parent.graph()
        actions = ["edge_add", "edge_delete", "edge_flip"]
        if parent.tile_count < self.maximum_tiles:
            actions.append("tile_add")
        if parent.tile_count > 3:
            actions.append("tile_delete")
        for _ in range(40):
            action = rng.choice(actions)
            proposal = base.copy()
            if action == "edge_add":
                missing = list(nx.non_edges(proposal))
                rng.shuffle(missing)
                changed = False
                for edge in missing:
                    proposal.add_edge(*edge)
                    if nx.check_planarity(proposal, counterexample=False)[0]:
                        changed = True
                        break
                    proposal.remove_edge(*edge)
                if not changed:
                    continue
            elif action == "edge_delete":
                edges = list(proposal.edges())
                rng.shuffle(edges)
                changed = False
                for edge in edges:
                    proposal.remove_edge(*edge)
                    if nx.node_connectivity(proposal) >= 3:
                        changed = True
                        break
                    proposal.add_edge(*edge)
                if not changed:
                    continue
            elif action == "edge_flip":
                flipped = self._edge_flip(proposal, rng)
                if flipped is None:
                    continue
                proposal = flipped
            elif action == "tile_add":
                embedding = _embedding(proposal)
                faces, _lookup = _faces(embedding)
                face = rng.choice(faces)
                node = max(node for node in proposal if node != OUTSIDE) + 1
                proposal.add_node(node)
                proposal.add_edges_from((node, target) for target in face)
            else:
                tiles = [node for node in proposal if node != OUTSIDE]
                rng.shuffle(tiles)
                changed = False
                for node in tiles:
                    candidate = proposal.copy()
                    candidate.remove_node(node)
                    if nx.node_connectivity(candidate) >= 3:
                        proposal = candidate
                        changed = True
                        break
                if not changed:
                    continue
            try:
                candidate = self._candidate(
                    proposal,
                    rng,
                    origin="mutation",
                    mutation=action,
                    parent_id=parent.graph_id,
                )
            except (ValueError, nx.NetworkXError):
                continue
            if candidate.graph_id != parent.graph_id:
                return candidate
        return None


def graph_feature_payload(candidate: DualGraphCandidate) -> dict[str, object]:
    graph = candidate.graph()
    degrees = dict(graph.degree())
    tile_degrees = [degrees[index] for index in range(candidate.tile_count)]
    boundary = [graph.has_edge(index, OUTSIDE) for index in range(candidate.tile_count)]
    return {
        "tile_count": candidate.tile_count,
        "edge_count": candidate.edge_count,
        "symmetry_order": candidate.symmetry_order,
        "boundary_tile_count": sum(boundary),
        "minimum_tile_degree": min(tile_degrees),
        "maximum_tile_degree": max(tile_degrees),
        "mean_tile_degree": sum(tile_degrees) / len(tile_degrees),
    }
