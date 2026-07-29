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


def build_k4_minus_arc_map() -> PlanarMap:
    """K4 minus T1--T3, with a non-degenerate outer arc owned by T0.

    The outer cyclic order is T0,T1,T2,T3.  T1 and T3 are disjoint, while
    X=(T0,T1,T2) and Y=(T0,T2,T3) are the two internal triple vertices.
    """

    pieces = (
        PieceSpec("T0", ("A", "B", "X", "Y"), True, "arc"),
        PieceSpec("T1", ("B", "C", "X"), True, "arc"),
        PieceSpec("T2", ("X", "C", "D", "Y"), True, "arc"),
        PieceSpec("T3", ("Y", "D", "A"), True, "arc"),
    )
    vertices = (
        VertexSpec("A", "outer", ("T0", "T3"), 1.0),
        VertexSpec("B", "outer", ("T0", "T1"), 1.0),
        VertexSpec("C", "outer", ("T1", "T2"), 1.0),
        VertexSpec("D", "outer", ("T2", "T3"), 1.0),
        VertexSpec("X", "interior", ("T0", "T1", "T2"), 2.0),
        VertexSpec("Y", "interior", ("T0", "T2", "T3"), 2.0),
    )
    interfaces = (
        InterfaceSpec(
            "T0-T1",
            "T0",
            "T1",
            (InterfaceView("T0", "B", "X"), InterfaceView("T1", "X", "B")),
        ),
        InterfaceSpec(
            "T1-T2",
            "T1",
            "T2",
            (InterfaceView("T1", "C", "X"), InterfaceView("T2", "X", "C")),
        ),
        InterfaceSpec(
            "T0-T2",
            "T0",
            "T2",
            (InterfaceView("T0", "X", "Y"), InterfaceView("T2", "Y", "X")),
        ),
        InterfaceSpec(
            "T2-T3",
            "T2",
            "T3",
            (InterfaceView("T2", "D", "Y"), InterfaceView("T3", "Y", "D")),
        ),
        InterfaceSpec(
            "T0-T3",
            "T0",
            "T3",
            (InterfaceView("T0", "Y", "A"), InterfaceView("T3", "A", "Y")),
        ),
        InterfaceSpec(
            "outer-T0", "T0", None, (InterfaceView("T0", "A", "B"),), True
        ),
        InterfaceSpec(
            "outer-T1", "T1", None, (InterfaceView("T1", "B", "C"),), True
        ),
        InterfaceSpec(
            "outer-T2", "T2", None, (InterfaceView("T2", "C", "D"),), True
        ),
        InterfaceSpec(
            "outer-T3", "T3", None, (InterfaceView("T3", "D", "A"),), True
        ),
    )
    automorphisms = (
        MapAutomorphism(
            "identity",
            (("T0", "T0"), ("T1", "T1"), ("T2", "T2"), ("T3", "T3")),
            (
                ("A", "A"),
                ("B", "B"),
                ("C", "C"),
                ("D", "D"),
                ("X", "X"),
                ("Y", "Y"),
            ),
        ),
        MapAutomorphism(
            "swap_T1_T3",
            (("T0", "T0"), ("T1", "T3"), ("T2", "T2"), ("T3", "T1")),
            (
                ("A", "B"),
                ("B", "A"),
                ("C", "D"),
                ("D", "C"),
                ("X", "Y"),
                ("Y", "X"),
            ),
        ),
    )
    result = PlanarMap(
        name="k4-minus-arc",
        pieces=pieces,
        vertices=vertices,
        interfaces=interfaces,
        automorphisms=automorphisms,
        reference_piece="T0",
        hypotheses=ProblemHypotheses(
            piecewise_c2_boundary=True,
            center_strictly_inside_one_tile=True,
        ),
    )
    result.validate()
    return result
