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


def build_k4_minus_point_map() -> PlanarMap:
    """K4 minus T1--T3, with T0 meeting the outer circle only at A.

    The point A is shared by T0, T1 and T3.  T1 and T3 have no positive-length
    interface; their only contact is A.  The remaining internal triple vertices
    are X=(T0,T1,T2) and Y=(T0,T2,T3).
    """

    pieces = (
        PieceSpec("T0", ("A", "X", "Y"), True, "point"),
        PieceSpec("T1", ("A", "B", "X"), True, "arc"),
        PieceSpec("T2", ("X", "B", "C", "Y"), True, "arc"),
        PieceSpec("T3", ("Y", "C", "A"), True, "arc"),
    )
    vertices = (
        VertexSpec("A", "outer", ("T0", "T1", "T3"), 1.0),
        VertexSpec("B", "outer", ("T1", "T2"), 1.0),
        VertexSpec("C", "outer", ("T2", "T3"), 1.0),
        VertexSpec("X", "interior", ("T0", "T1", "T2"), 2.0),
        VertexSpec("Y", "interior", ("T0", "T2", "T3"), 2.0),
    )
    interfaces = (
        InterfaceSpec(
            "T0-T1",
            "T0",
            "T1",
            (InterfaceView("T0", "A", "X"), InterfaceView("T1", "X", "A")),
        ),
        InterfaceSpec(
            "T1-T2",
            "T1",
            "T2",
            (InterfaceView("T1", "B", "X"), InterfaceView("T2", "X", "B")),
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
            (InterfaceView("T2", "C", "Y"), InterfaceView("T3", "Y", "C")),
        ),
        InterfaceSpec(
            "T0-T3",
            "T0",
            "T3",
            (InterfaceView("T0", "Y", "A"), InterfaceView("T3", "A", "Y")),
        ),
        InterfaceSpec(
            "outer-T1", "T1", None, (InterfaceView("T1", "A", "B"),), True
        ),
        InterfaceSpec(
            "outer-T2", "T2", None, (InterfaceView("T2", "B", "C"),), True
        ),
        InterfaceSpec(
            "outer-T3", "T3", None, (InterfaceView("T3", "C", "A"),), True
        ),
    )
    automorphisms = (
        MapAutomorphism(
            "identity",
            (("T0", "T0"), ("T1", "T1"), ("T2", "T2"), ("T3", "T3")),
            (("A", "A"), ("B", "B"), ("C", "C"), ("X", "X"), ("Y", "Y")),
        ),
        MapAutomorphism(
            "swap_T1_T3",
            (("T0", "T0"), ("T1", "T3"), ("T2", "T2"), ("T3", "T1")),
            (("A", "A"), ("B", "C"), ("C", "B"), ("X", "Y"), ("Y", "X")),
        ),
    )
    result = PlanarMap(
        name="k4-minus-point",
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
