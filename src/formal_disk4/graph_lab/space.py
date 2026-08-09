from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, replace
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
    origin: str = "known_seed",
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
        size_bias: float = 1.4,
        symmetric_prior_fraction: float = 0.45,
        imposed_symmetry_bias: float = 0.75,
        known_seeds: Sequence[Mapping[str, object] | str] = (),
    ) -> None:
        self.maximum_tiles = max(3, min(13, int(maximum_tiles)))
        self.size_bias = max(0.0, float(size_bias))
        self.symmetric_prior_fraction = min(1.0, max(0.0, float(symmetric_prior_fraction)))
        self.imposed_symmetry_bias = min(1.0, max(0.0, float(imposed_symmetry_bias)))
        seeds = []
        for raw in known_seeds:
            if isinstance(raw, str):
                map_name = raw
                symmetry = None
            else:
                map_name = str(raw["map"])
                symmetry = str(raw["symmetry"]) if raw.get("symmetry") else None
            candidate = candidate_from_planar_map(
                map_name, imposed_automorphism=symmetry
            )
            if candidate.tile_count <= self.maximum_tiles:
                seeds.append(candidate)
        self.known_seeds = tuple(seeds)

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> "GraphSpace":
        return cls(
            maximum_tiles=int(config.get("maximum_tiles", 13)),
            size_bias=float(config.get("size_bias", 1.4)),
            symmetric_prior_fraction=float(
                config.get("symmetric_prior_fraction", 0.45)
            ),
            imposed_symmetry_bias=float(config.get("imposed_symmetry_bias", 0.75)),
            known_seeds=config.get("known_seeds", ()),  # type: ignore[arg-type]
        )

    def _sample_size(self, rng: random.Random) -> int:
        sizes = tuple(range(3, self.maximum_tiles + 1))
        weights = tuple(
            0.15 + (self.maximum_tiles - size + 1) ** self.size_bias
            for size in sizes
        )
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
            graph = self._ring_graph(tile_count)
            return self._candidate(
                graph, rng, origin="prior", mutation="symmetric_ring"
            )
        graph = self._random_polyhedral_graph(tile_count, rng)
        return self._candidate(
            graph, rng, origin="prior", mutation="random_polyhedral"
        )

    def mutate(
        self, parent: DualGraphCandidate, rng: random.Random
    ) -> DualGraphCandidate | None:
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
