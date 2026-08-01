from __future__ import annotations

from .base import (
    InterfaceSpec,
    InterfaceView,
    MapAutomorphism,
    PieceSpec,
    PlanarMap,
    ProblemHypotheses,
    VertexSpec,
)
from .double_cycle import build_double_cycle_map
from .two_ring_families import (
    build_double_cycle_offset_map,
    build_inner_cycle_boundary_points_map,
    build_outer_cycle_center_points_map,
)


def _inflate_center_vertex(base: PlanarMap, name: str) -> PlanarMap:
    """Replace the central junction ``Z`` by one fully internal tile ``C``.

    Each old interface ending at Z receives its own new endpoint.  The wedge
    formerly occupied by each incident piece becomes one C-piece interface.
    This is the combinatorial truncation of the vertex Z and preserves every
    pre-existing positive contact.
    """

    if "C" in base.piece_map():
        raise ValueError("The source map already contains a central tile C")
    center = base.vertex_map().get("Z")
    if center is None or center.kind != "interior":
        raise ValueError("Centered two-ring construction needs interior vertex Z")

    incident_interfaces = tuple(
        interface
        for interface in base.internal_interfaces()
        if any(
            view.start_vertex == "Z" or view.end_vertex == "Z"
            for view in interface.views
        )
    )
    if len(incident_interfaces) != len(center.incident_pieces):
        raise ValueError("Central junction is not bounded by one edge per piece")
    endpoint_by_interface = {
        interface.name: f"Q{index + 1}"
        for index, interface in enumerate(incident_interfaces)
    }

    incoming_by_piece: dict[str, InterfaceSpec] = {}
    outgoing_by_piece: dict[str, InterfaceSpec] = {}
    for interface in incident_interfaces:
        for view in interface.views:
            if view.end_vertex == "Z":
                incoming_by_piece[view.piece] = interface
            if view.start_vertex == "Z":
                outgoing_by_piece[view.piece] = interface

    pieces = []
    central_edges: list[tuple[str, str, str]] = []
    for piece in base.pieces:
        if "Z" not in piece.contour_vertices:
            pieces.append(piece)
            continue
        incoming = incoming_by_piece.get(piece.name)
        outgoing = outgoing_by_piece.get(piece.name)
        if incoming is None or outgoing is None or incoming is outgoing:
            raise ValueError(f"Cannot truncate central wedge of {piece.name}")
        incoming_vertex = endpoint_by_interface[incoming.name]
        outgoing_vertex = endpoint_by_interface[outgoing.name]
        center_index = piece.contour_vertices.index("Z")
        contour = (
            piece.contour_vertices[:center_index]
            + (incoming_vertex, outgoing_vertex)
            + piece.contour_vertices[center_index + 1 :]
        )
        pieces.append(
            PieceSpec(
                piece.name,
                contour,
                piece.touches_outer_boundary,
                piece.outer_boundary_contact,
            )
        )
        # The central contour traverses this edge opposite to the old piece.
        central_edges.append((outgoing_vertex, incoming_vertex, piece.name))

    successor = {start: end for start, end, _piece in central_edges}
    if set(successor) != set(successor.values()):
        raise ValueError("Truncated central edges do not form a cycle")
    start = min(successor)
    central_contour = []
    current = start
    while current not in central_contour:
        central_contour.append(current)
        current = successor[current]
    if current != start or len(central_contour) != len(successor):
        raise ValueError("Truncated central boundary is not one simple cycle")
    pieces.append(PieceSpec("C", tuple(central_contour), False, "none"))

    vertices = tuple(vertex for vertex in base.vertices if vertex.name != "Z")
    vertices += tuple(
        VertexSpec(
            endpoint_by_interface[interface.name],
            "interior",
            (interface.left_piece, interface.right_piece, "C"),
            2.0,
        )
        for interface in incident_interfaces
    )

    interfaces = []
    for interface in base.interfaces:
        endpoint = endpoint_by_interface.get(interface.name)
        views = tuple(
            InterfaceView(
                view.piece,
                endpoint if view.start_vertex == "Z" else view.start_vertex,
                endpoint if view.end_vertex == "Z" else view.end_vertex,
            )
            for view in interface.views
        )
        interfaces.append(
            InterfaceSpec(
                interface.name,
                interface.left_piece,
                interface.right_piece,
                views,
                interface.is_outer,
            )
        )
    interfaces.extend(
        InterfaceSpec(
            f"C-{piece}",
            "C",
            piece,
            (
                InterfaceView("C", central_start, central_end),
                InterfaceView(piece, central_end, central_start),
            ),
        )
        for central_start, central_end, piece in central_edges
    )

    def interface_signature(
        interface: InterfaceSpec,
        automorphism: MapAutomorphism | None = None,
    ) -> frozenset[tuple[str, str]]:
        signature = []
        for view in interface.views:
            other = view.end_vertex if view.start_vertex == "Z" else view.start_vertex
            signature.append(
                (
                    automorphism.map_piece(view.piece) if automorphism else view.piece,
                    automorphism.map_vertex(other) if automorphism else other,
                )
            )
        return frozenset(signature)

    incident_by_signature = {
        interface_signature(interface): interface
        for interface in incident_interfaces
    }
    automorphisms = []
    for automorphism in base.automorphisms:
        vertex_map = [
            pair for pair in automorphism.vertex_map if pair[0] != "Z"
        ]
        for interface in incident_interfaces:
            target = incident_by_signature.get(
                interface_signature(interface, automorphism)
            )
            if target is None:
                raise ValueError(
                    f"Cannot transport central edge under {automorphism.name}"
                )
            vertex_map.append(
                (
                    endpoint_by_interface[interface.name],
                    endpoint_by_interface[target.name],
                )
            )
        automorphisms.append(
            MapAutomorphism(
                automorphism.name,
                automorphism.piece_map + (("C", "C"),),
                tuple(vertex_map),
            )
        )

    result = PlanarMap(
        name=name,
        pieces=tuple(pieces),
        vertices=vertices,
        interfaces=tuple(interfaces),
        automorphisms=tuple(automorphisms),
        reference_piece=base.reference_piece,
        hypotheses=ProblemHypotheses(
            piecewise_c2_boundary=base.hypotheses.piecewise_c2_boundary,
            center_strictly_inside_one_tile=True,
        ),
    )
    result.validate()
    return result


def build_centered_double_cycle_map(size: int) -> PlanarMap:
    return _inflate_center_vertex(
        build_double_cycle_map(size), f"centered-double-cycle-{size}"
    )


def build_centered_double_cycle_offset_map(size: int) -> PlanarMap:
    return _inflate_center_vertex(
        build_double_cycle_offset_map(size),
        f"centered-double-cycle-offset-{size}",
    )


def build_centered_inner_cycle_boundary_points_map(size: int) -> PlanarMap:
    return _inflate_center_vertex(
        build_inner_cycle_boundary_points_map(size),
        f"centered-inner-cycle-boundary-points-{size}",
    )


def build_centered_outer_cycle_center_points_map(size: int) -> PlanarMap:
    return _inflate_center_vertex(
        build_outer_cycle_center_points_map(size),
        f"centered-outer-cycle-center-points-{size}",
    )
