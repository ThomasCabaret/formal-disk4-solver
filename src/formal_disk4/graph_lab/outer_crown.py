from __future__ import annotations

"""Experimental projection of a complete Stein map onto its outer crown.

This module is deliberately kept out of the generic map builder.  The Graph
Lab may use it to generate a complete, mathematically audited Stein graph and
then solve only the collar made of tiles incident with the disk boundary.  The
new inner cut is represented by the generic free-boundary API.
"""

import math
import hashlib
from collections import defaultdict
from typing import Mapping, Sequence

from formal_disk4.maps.base import (
    InterfaceSpec,
    MapAutomorphism,
    PlanarMap,
    ProblemHypotheses,
    VertexSpec,
)

from .space import (
    OUTSIDE,
    DualGraphCandidate,
    DynamicPlanarMap,
    _equivariance_mode,
)


OUTER_CROWN_STRUCTURE_KIND = "stein_outer_crown_v1"
CROWN_REGION_STRUCTURE_KIND = "stein_crown_region_v1"
PARTIAL_BOUNDARY_CONTRACT_VERSION = "open-outer-v2"


class OuterCrownError(ValueError):
    """The boundary tiles of a source map do not form one annular collar."""


def _permutation_order(mapping: Mapping[str, str]) -> int:
    unseen = set(mapping)
    order = 1
    while unseen:
        seed = min(unseen)
        current = seed
        length = 0
        while current in unseen:
            unseen.remove(current)
            current = mapping[current]
            length += 1
        if current != seed:
            raise OuterCrownError("An automorphism restriction is not a permutation")
        order = math.lcm(order, max(1, length))
    return order


def _validate_one_free_cycle(planar_map: PlanarMap) -> None:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for interface in planar_map.free_interfaces():
        view = interface.views[0]
        if view.start_vertex == view.end_vertex:
            raise OuterCrownError("The inner cut contains a loop edge")
        adjacency[view.start_vertex].add(view.end_vertex)
        adjacency[view.end_vertex].add(view.start_vertex)
    if not adjacency:
        raise OuterCrownError("The outer crown leaves no free inner boundary")
    if any(len(neighbours) != 2 for neighbours in adjacency.values()):
        raise OuterCrownError("The inner cut is not one non-branching boundary")
    seen = set()
    pending = [min(adjacency)]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        pending.extend(adjacency[current] - seen)
    if seen != set(adjacency):
        raise OuterCrownError("The inner cut has several boundary components")


def _validate_connected_crown(planar_map: PlanarMap) -> None:
    adjacency = {piece.name: set() for piece in planar_map.pieces}
    for interface in planar_map.internal_interfaces():
        assert interface.right_piece is not None
        adjacency[interface.left_piece].add(interface.right_piece)
        adjacency[interface.right_piece].add(interface.left_piece)
    seen = set()
    pending = [min(adjacency)]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        pending.extend(adjacency[current] - seen)
    if seen != set(adjacency):
        raise OuterCrownError("The outer-boundary tiles do not form one crown")


def _outer_crown_piece_names(planar_map: PlanarMap) -> tuple[str, ...]:
    return tuple(
        piece.name for piece in planar_map.pieces if piece.touches_outer_boundary
    )


def _select_connected_region(
    planar_map: PlanarMap,
    crown_names: Sequence[str],
    target_count: int,
    *,
    selection_key: str,
) -> tuple[str, ...]:
    """Select one deterministic connected patch of the outer crown.

    On the usual cycle this is an opened consecutive arc.  The more general
    breadth-first form also handles crowns with additional contacts without
    hard-coding a cycle topology.  Different source graphs choose different
    seeds, while a restored descriptor records the exact retained names.
    """

    names = tuple(crown_names)
    if not 1 <= target_count <= len(names):
        raise OuterCrownError(
            f"Requested crown region size {target_count} is outside 1..{len(names)}"
        )
    crown = set(names)
    adjacency = {name: set() for name in names}
    for interface in planar_map.internal_interfaces():
        assert interface.right_piece is not None
        left = interface.left_piece
        right = interface.right_piece
        if left in crown and right in crown:
            adjacency[left].add(right)
            adjacency[right].add(left)
    arc_seeds = tuple(
        piece.name
        for piece in planar_map.pieces
        if piece.name in crown and piece.has_outer_boundary_arc
    )
    seeds = arc_seeds or names
    digest = hashlib.sha256(selection_key.encode("utf-8")).digest()
    seed = seeds[int.from_bytes(digest[:8], "big") % len(seeds)]
    selected: list[str] = []
    seen = {seed}
    pending = [seed]
    while pending and len(selected) < target_count:
        current = pending.pop(0)
        selected.append(current)
        for neighbour in sorted(adjacency[current]):
            if neighbour not in seen:
                seen.add(neighbour)
                pending.append(neighbour)
    if len(selected) != target_count:
        raise OuterCrownError(
            "The requested outer-crown region is not connected in the retained graph"
        )
    return tuple(selected)


def extract_outer_crown(
    source: DynamicPlanarMap,
    *,
    prototype_rotation_order: int,
    retained_tile_count: int | None = None,
    retained_piece_names: Sequence[str] | None = None,
    selection_key: str = "outer-crown",
) -> DynamicPlanarMap:
    """Keep a connected region of tiles incident with the disk boundary.

    Interfaces towards removed tiles become one-sided free interfaces.  A
    source interior vertex becomes free precisely when at least one of its
    incident tiles was removed.  At a cut meeting the disk circle, the strict
    bound is ``sum(angles) < pi``; elsewhere it is ``sum(angles) < 2*pi``.
    Thus no complete-tiling equality is invented on the cut.
    """

    if prototype_rotation_order < 1:
        raise OuterCrownError("Prototype rotation order must be positive")
    if retained_piece_names is not None and retained_tile_count is not None:
        raise OuterCrownError(
            "Specify either retained_piece_names or retained_tile_count, not both"
        )
    planar_map = source.planar_map
    crown_names = _outer_crown_piece_names(planar_map)
    crown = set(crown_names)
    if not crown:
        raise OuterCrownError("No tile touches the disk boundary")
    if len(crown) == len(planar_map.pieces):
        raise OuterCrownError("The source graph has no interior to remove")
    if retained_piece_names is not None:
        selected_names = tuple(str(name) for name in retained_piece_names)
        if not selected_names or len(set(selected_names)) != len(selected_names):
            raise OuterCrownError("A restored crown region has invalid retained names")
        if not set(selected_names) <= crown:
            raise OuterCrownError("A crown region contains a non-boundary tile")
    elif retained_tile_count is not None and retained_tile_count < len(crown_names):
        selected_names = _select_connected_region(
            planar_map,
            crown_names,
            int(retained_tile_count),
            selection_key=selection_key,
        )
    else:
        if retained_tile_count is not None and retained_tile_count > len(crown_names):
            raise OuterCrownError(
                f"Requested {retained_tile_count} crown tiles, only {len(crown_names)} exist"
            )
        selected_names = crown_names
    retained = set(selected_names)

    pieces = tuple(piece for piece in planar_map.pieces if piece.name in retained)
    retained_vertices = {
        vertex for piece in pieces for vertex in piece.contour_vertices
    }
    vertices = []
    for vertex in planar_map.vertices:
        if vertex.name not in retained_vertices:
            continue
        incident = tuple(
            piece for piece in vertex.incident_pieces if piece in retained
        )
        removed_incidence = len(incident) != len(vertex.incident_pieces)
        if vertex.is_outer_boundary:
            kind = "free_outer" if vertex.is_free_boundary or removed_incidence else "outer"
        else:
            kind = "free" if vertex.is_free_boundary or removed_incidence else "interior"
        vertices.append(
            VertexSpec(
                name=vertex.name,
                kind=kind,
                incident_pieces=incident,
                angle_sum_pi=1.0 if kind in {"outer", "free_outer"} else 2.0,
            )
        )

    interfaces = []
    for interface in planar_map.interfaces:
        retained_views = tuple(
            view for view in interface.views if view.piece in retained
        )
        if not retained_views:
            continue
        if interface.is_outer or interface.is_free:
            if len(retained_views) != 1:
                raise OuterCrownError("A source boundary interface has invalid incidence")
            interfaces.append(interface)
            continue
        if len(retained_views) == 2:
            interfaces.append(interface)
            continue
        view = retained_views[0]
        interfaces.append(
            InterfaceSpec(
                name=f"free-cut-{interface.name}",
                left_piece=view.piece,
                right_piece=None,
                views=(view,),
                is_free=True,
            )
        )

    vertex_kind = {vertex.name: vertex.kind for vertex in vertices}
    automorphisms = []
    for automorphism in planar_map.automorphisms:
        piece_map = dict(automorphism.piece_map)
        mapped_pieces = {piece_map[piece] for piece in retained}
        if mapped_pieces != retained:
            continue
        raw_vertex_map = dict(automorphism.vertex_map)
        mapped_vertices = {
            raw_vertex_map[vertex] for vertex in retained_vertices
        }
        if mapped_vertices != retained_vertices:
            continue
        if any(
            vertex_kind[vertex] != vertex_kind[raw_vertex_map[vertex]]
            for vertex in retained_vertices
        ):
            continue
        automorphisms.append(
            MapAutomorphism(
                name=automorphism.name,
                piece_map=tuple(
                    (piece.name, piece_map[piece.name]) for piece in pieces
                ),
                vertex_map=tuple(
                    (vertex.name, raw_vertex_map[vertex.name]) for vertex in vertices
                ),
            )
        )

    automorphism_names = {item.name for item in automorphisms}
    imposed = source.imposed_automorphism
    if imposed not in automorphism_names:
        # Opening a rotational crown normally destroys the global action.  It
        # remains metadata of the complete source graph, but must not be
        # imposed as a symmetry of the smaller partial problem.
        imposed = None
    result = PlanarMap(
        name=(
            f"{planar_map.name}-crown-region-{len(pieces)}"
            f"-prototype-c{prototype_rotation_order}"
            f"-{PARTIAL_BOUNDARY_CONTRACT_VERSION}"
        ),
        pieces=pieces,
        vertices=tuple(vertices),
        interfaces=tuple(interfaces),
        automorphisms=tuple(automorphisms),
        reference_piece=pieces[0].name,
        hypotheses=ProblemHypotheses(
            piecewise_c2_boundary=planar_map.hypotheses.piecewise_c2_boundary,
            center_strictly_inside_one_tile=False,
        ),
        prototype_rotation_order=prototype_rotation_order,
        outer_boundary_is_complete=all(
            interface.views[0].piece in retained
            for interface in planar_map.outer_interfaces()
        ),
    )
    result.validate()
    _validate_connected_crown(result)
    if retained == crown:
        _validate_one_free_cycle(result)

    orders = tuple(
        _permutation_order(dict(automorphism.piece_map))
        for automorphism in automorphisms
    )
    reflections = (
        tuple(name for name in source.imposed_reflections if name in automorphism_names)
        if imposed is not None
        else ()
    )
    return DynamicPlanarMap(
        planar_map=result,
        imposed_automorphism=imposed,
        imposed_equivariance_mode=_equivariance_mode(result, imposed),
        imposed_reflections=reflections,
        automorphism_orders=orders,
    )


def outer_crown_model_candidate(
    source_candidate: DualGraphCandidate,
    crown: DynamicPlanarMap,
) -> DualGraphCandidate:
    """Build the graph tensor domain aligned with the retained pieces.

    Free cut edges are deliberately absent from the dual graph: unlike the
    disk exterior they are not a shared neighbouring region.  Their exact
    contour positions remain available to the mapping and weak-order layers.
    """

    planar_map = crown.planar_map
    piece_index = {piece.name: index for index, piece in enumerate(planar_map.pieces)}
    edges: set[tuple[int, int]] = set()
    for interface in planar_map.interfaces:
        if interface.is_free:
            continue
        left = piece_index[interface.left_piece]
        right = (
            OUTSIDE
            if interface.is_outer
            else piece_index[str(interface.right_piece)]
        )
        edges.add((min(left, right), max(left, right)))
    imposed = None
    if crown.imposed_automorphism is not None:
        automorphism = next(
            item
            for item in planar_map.automorphisms
            if item.name == crown.imposed_automorphism
        )
        imposed = tuple(
            piece_index[automorphism.map_piece(piece.name)]
            for piece in planar_map.pieces
        )
    return DualGraphCandidate(
        tile_count=len(planar_map.pieces),
        edges=tuple(sorted(edges)),
        imposed_permutation=imposed,
        origin=f"{source_candidate.origin}:outer_crown",
        mutation=f"{source_candidate.mutation}:outer_crown",
        parent_id=source_candidate.graph_id,
    )


def outer_crown_descriptor(
    source_candidate: DualGraphCandidate,
    crown: DynamicPlanarMap,
) -> dict[str, object]:
    model_candidate = outer_crown_model_candidate(source_candidate, crown)
    # Point-only contacts with the disk are not dual edges to OUTSIDE, so the
    # complete source map—not merely its outside-star degree—is authoritative.
    from .space import build_dynamic_planar_map

    source_planar_map = build_dynamic_planar_map(source_candidate).planar_map
    source_crown_tile_count = sum(
        1 for piece in source_planar_map.pieces if piece.touches_outer_boundary
    )
    retained_piece_names = [piece.name for piece in crown.planar_map.pieces]
    return {
        "kind": CROWN_REGION_STRUCTURE_KIND,
        "region_mode": (
            "full" if len(retained_piece_names) == source_crown_tile_count else "connected_subset"
        ),
        "source_tile_count": source_candidate.tile_count,
        "source_crown_tile_count": source_crown_tile_count,
        "retained_tile_count": len(crown.planar_map.pieces),
        "retained_edge_count": model_candidate.edge_count,
        "retained_piece_names": retained_piece_names,
        "retained_imposed_permutation": (
            list(model_candidate.imposed_permutation)
            if model_candidate.imposed_permutation is not None
            else None
        ),
        "free_interface_count": len(crown.planar_map.free_interfaces()),
        "structural_symmetry_order": source_candidate.symmetry_order,
        "prototype_rotation_order": crown.planar_map.prototype_rotation_order,
        "prototype_symmetry_imposed": crown.planar_map.prototype_rotation_order > 1,
    }


def dynamic_from_structure_descriptor(
    candidate: DualGraphCandidate,
    descriptor: Mapping[str, object] | None,
) -> DynamicPlanarMap:
    from .space import build_dynamic_planar_map

    dynamic = build_dynamic_planar_map(candidate)
    if not descriptor or descriptor.get("kind") not in {
        OUTER_CROWN_STRUCTURE_KIND,
        CROWN_REGION_STRUCTURE_KIND,
    }:
        return dynamic
    return extract_outer_crown(
        dynamic,
        prototype_rotation_order=int(descriptor["prototype_rotation_order"]),
        retained_piece_names=(
            tuple(str(name) for name in descriptor["retained_piece_names"])
            if descriptor.get("kind") == CROWN_REGION_STRUCTURE_KIND
            and isinstance(descriptor.get("retained_piece_names"), list)
            else None
        ),
    )
