from __future__ import annotations

"""Graph-Lab relaxation that removes the fixed disk-circle boundary.

The complete source map, all tiles, and every internal interface are kept.
Only the interfaces formerly incident with the disk exterior become generic
one-sided free interfaces.  This is deliberately a Graph-Lab projection: the
generic formal and geometric solvers merely consume the resulting
``PlanarMap`` and do not need a special-case execution path.
"""

from formal_disk4.maps.base import (
    InterfaceSpec,
    PieceSpec,
    PlanarMap,
    ProblemHypotheses,
    VertexSpec,
)

from .space import OUTSIDE, DualGraphCandidate, DynamicPlanarMap


FREE_OUTER_BOUNDARY_STRUCTURE_KIND = "free_outer_boundary_v1"


def relax_outer_boundary(source: DynamicPlanarMap) -> DynamicPlanarMap:
    """Replace the complete disk circle by an unconstrained free boundary."""

    planar_map = source.planar_map
    pieces = tuple(
        PieceSpec(
            name=piece.name,
            contour_vertices=piece.contour_vertices,
            touches_outer_boundary=False,
            outer_boundary_contact="none",
        )
        for piece in planar_map.pieces
    )
    vertices = tuple(
        VertexSpec(
            name=vertex.name,
            kind=("free" if vertex.is_outer_boundary else vertex.kind),
            incident_pieces=vertex.incident_pieces,
            angle_sum_pi=(2.0 if vertex.is_outer_boundary else vertex.angle_sum_pi),
        )
        for vertex in planar_map.vertices
    )
    interfaces = tuple(
        InterfaceSpec(
            name=interface.name,
            left_piece=interface.left_piece,
            right_piece=interface.right_piece,
            views=interface.views,
            is_outer=False,
            is_free=True,
        )
        if interface.is_outer
        else interface
        for interface in planar_map.interfaces
    )
    relaxed = PlanarMap(
        name=f"{planar_map.name}-free-outer-boundary",
        pieces=pieces,
        vertices=vertices,
        interfaces=interfaces,
        automorphisms=planar_map.automorphisms,
        reference_piece=planar_map.reference_piece,
        hypotheses=ProblemHypotheses(
            piecewise_c2_boundary=planar_map.hypotheses.piecewise_c2_boundary,
            # There is no distinguished disk centre or radius after removing
            # the circular outer boundary.
            center_strictly_inside_one_tile=False,
        ),
        prototype_rotation_order=planar_map.prototype_rotation_order,
        outer_boundary_is_complete=False,
    )
    relaxed.validate()
    return DynamicPlanarMap(
        planar_map=relaxed,
        imposed_automorphism=source.imposed_automorphism,
        imposed_equivariance_mode=source.imposed_equivariance_mode,
        imposed_reflections=source.imposed_reflections,
        automorphism_orders=source.automorphism_orders,
    )


def free_outer_boundary_model_candidate(
    source_candidate: DualGraphCandidate,
    relaxed: DynamicPlanarMap,
) -> DualGraphCandidate:
    """Return the ranker graph after deleting the artificial OUTSIDE node.

    The tile indices and imposed tile permutation are unchanged because this
    relaxation keeps every tile.  ``stein_center_tile`` is intentionally
    cleared: disk-specific Stein joint-oracle deductions are not valid once
    the disk circle and its centre have been removed.
    """

    if len(relaxed.planar_map.pieces) != source_candidate.tile_count:
        raise ValueError(
            "A free-outer-boundary relaxation must retain every source tile"
        )
    internal_edges = tuple(
        edge for edge in source_candidate.edges if OUTSIDE not in edge
    )
    return DualGraphCandidate(
        tile_count=source_candidate.tile_count,
        edges=internal_edges,
        imposed_permutation=source_candidate.imposed_permutation,
        origin=f"{source_candidate.origin}:free_outer_boundary",
        mutation=f"{source_candidate.mutation}:free_outer_boundary",
        parent_id=source_candidate.graph_id,
        source_map_name=source_candidate.source_map_name,
        source_symmetry=source_candidate.source_symmetry,
        stein_center_tile=None,
    )


def free_outer_boundary_descriptor(
    source_candidate: DualGraphCandidate,
    relaxed: DynamicPlanarMap,
) -> dict[str, object]:
    model_candidate = free_outer_boundary_model_candidate(
        source_candidate, relaxed
    )
    return {
        "kind": FREE_OUTER_BOUNDARY_STRUCTURE_KIND,
        "source_tile_count": source_candidate.tile_count,
        "retained_tile_count": len(relaxed.planar_map.pieces),
        "retained_edge_count": model_candidate.edge_count,
        "free_interface_count": len(relaxed.planar_map.free_interfaces()),
        "structural_symmetry_order": source_candidate.symmetry_order,
        "prototype_rotation_order": relaxed.planar_map.prototype_rotation_order,
    }
