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


def _inner(index: int, size: int) -> str:
    return f"I{index % size}"


def _outer(index: int, size: int) -> str:
    return f"O{index % size}"


def _peripheral(index: int, size: int) -> str:
    return f"P{index % size}"


def _rotation(step: int, size: int) -> MapAutomorphism:
    step %= size
    return MapAutomorphism(
        name=f"rotation_{step}",
        piece_map=(("C", "C"),)
        + tuple(
            (_peripheral(i, size), _peripheral(i + step, size))
            for i in range(size)
        ),
        vertex_map=tuple(
            (_inner(i, size), _inner(i + step, size)) for i in range(size)
        )
        + tuple((_outer(i, size), _outer(i + step, size)) for i in range(size)),
    )


def _reflection(axis: int, size: int) -> MapAutomorphism:
    """Reflection i -> axis-i on vertices and i -> axis-i-1 on sectors."""

    axis %= size
    return MapAutomorphism(
        name=f"reflection_{axis}",
        piece_map=(("C", "C"),)
        + tuple(
            (_peripheral(i, size), _peripheral(axis - i - 1, size))
            for i in range(size)
        ),
        vertex_map=tuple(
            (_inner(i, size), _inner(axis - i, size)) for i in range(size)
        )
        + tuple((_outer(i, size), _outer(axis - i, size)) for i in range(size)),
    )


def build_wheel_map(size: int) -> PlanarMap:
    """``size`` outer tiles in a cycle surrounding one central tile.

    The contact graph is the wheel W(size + 1).  The map declares its complete
    dihedral action; ``rotation_1`` advances every outer tile and every contour
    vertex by one sector while fixing the central tile as a set.
    """

    if size < 3:
        raise ValueError("A wheel map needs at least three outer tiles")

    central = PieceSpec(
        "C",
        tuple(_inner(i, size) for i in range(size)),
        False,
        "none",
    )
    peripheral = tuple(
        PieceSpec(
            _peripheral(i, size),
            (
                _inner(i + 1, size),
                _inner(i, size),
                _outer(i, size),
                _outer(i + 1, size),
            ),
            True,
            "arc",
        )
        for i in range(size)
    )

    vertices = tuple(
        VertexSpec(
            _inner(i, size),
            "interior",
            ("C", _peripheral(i - 1, size), _peripheral(i, size)),
            2.0,
        )
        for i in range(size)
    ) + tuple(
        VertexSpec(
            _outer(i, size),
            "outer",
            (_peripheral(i - 1, size), _peripheral(i, size)),
            1.0,
        )
        for i in range(size)
    )

    center_interfaces = tuple(
        InterfaceSpec(
            f"C-{_peripheral(i, size)}",
            "C",
            _peripheral(i, size),
            (
                InterfaceView("C", _inner(i, size), _inner(i + 1, size)),
                InterfaceView(
                    _peripheral(i, size),
                    _inner(i + 1, size),
                    _inner(i, size),
                ),
            ),
        )
        for i in range(size)
    )
    radial_interfaces = tuple(
        InterfaceSpec(
            f"{_peripheral(i - 1, size)}-{_peripheral(i, size)}",
            _peripheral(i - 1, size),
            _peripheral(i, size),
            (
                InterfaceView(
                    _peripheral(i - 1, size),
                    _outer(i, size),
                    _inner(i, size),
                ),
                InterfaceView(
                    _peripheral(i, size),
                    _inner(i, size),
                    _outer(i, size),
                ),
            ),
        )
        for i in range(size)
    )
    outer_interfaces = tuple(
        InterfaceSpec(
            f"outer-{_peripheral(i, size)}",
            _peripheral(i, size),
            None,
            (
                InterfaceView(
                    _peripheral(i, size),
                    _outer(i, size),
                    _outer(i + 1, size),
                ),
            ),
            is_outer=True,
        )
        for i in range(size)
    )

    result = PlanarMap(
        name=f"wheel-{size}",
        pieces=(central,) + peripheral,
        vertices=vertices,
        interfaces=center_interfaces + radial_interfaces + outer_interfaces,
        automorphisms=tuple(_rotation(step, size) for step in range(size))
        + tuple(_reflection(axis, size) for axis in range(size)),
        reference_piece="C",
        hypotheses=ProblemHypotheses(
            piecewise_c2_boundary=True,
            center_strictly_inside_one_tile=True,
        ),
    )
    result.validate()
    return result


def build_wheel_4_map() -> PlanarMap:
    """Compatibility wrapper for the original four-sector wheel."""

    return build_wheel_map(4)
