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


_SIZE = 4


def _index(value: int) -> int:
    return value % _SIZE


def _inner(index: int) -> str:
    return f"I{_index(index)}"


def _outer(index: int) -> str:
    return f"O{_index(index)}"


def _peripheral(index: int) -> str:
    return f"P{_index(index)}"


def _rotation(step: int) -> MapAutomorphism:
    step = _index(step)
    return MapAutomorphism(
        name=f"rotation_{step}",
        piece_map=(("C", "C"),)
        + tuple((_peripheral(i), _peripheral(i + step)) for i in range(_SIZE)),
        vertex_map=tuple((_inner(i), _inner(i + step)) for i in range(_SIZE))
        + tuple((_outer(i), _outer(i + step)) for i in range(_SIZE)),
    )


def _reflection(axis: int) -> MapAutomorphism:
    """Reflection i -> axis-i on vertices and i -> axis-i-1 on sectors."""

    axis = _index(axis)
    return MapAutomorphism(
        name=f"reflection_{axis}",
        piece_map=(("C", "C"),)
        + tuple(
            (_peripheral(i), _peripheral(axis - i - 1)) for i in range(_SIZE)
        ),
        vertex_map=tuple((_inner(i), _inner(axis - i)) for i in range(_SIZE))
        + tuple((_outer(i), _outer(axis - i)) for i in range(_SIZE)),
    )


def build_wheel_4_map() -> PlanarMap:
    """Four outer tiles in a cycle surrounding one central tile.

    The contact graph is the wheel W5: the outer pieces P0,...,P3 form a
    4-cycle and the central piece C touches every Pi.  The map declares the
    complete dihedral D4 action, including the required half-turn rotation_2.
    """

    central = PieceSpec(
        "C",
        tuple(_inner(i) for i in range(_SIZE)),
        False,
        "none",
    )
    peripheral = tuple(
        PieceSpec(
            _peripheral(i),
            (
                _inner(i + 1),
                _inner(i),
                _outer(i),
                _outer(i + 1),
            ),
            True,
            "arc",
        )
        for i in range(_SIZE)
    )

    vertices = tuple(
        VertexSpec(
            _inner(i),
            "interior",
            ("C", _peripheral(i - 1), _peripheral(i)),
            2.0,
        )
        for i in range(_SIZE)
    ) + tuple(
        VertexSpec(
            _outer(i),
            "outer",
            (_peripheral(i - 1), _peripheral(i)),
            1.0,
        )
        for i in range(_SIZE)
    )

    center_interfaces = tuple(
        InterfaceSpec(
            f"C-{_peripheral(i)}",
            "C",
            _peripheral(i),
            (
                InterfaceView("C", _inner(i), _inner(i + 1)),
                InterfaceView(_peripheral(i), _inner(i + 1), _inner(i)),
            ),
        )
        for i in range(_SIZE)
    )
    radial_interfaces = tuple(
        InterfaceSpec(
            f"{_peripheral(i - 1)}-{_peripheral(i)}",
            _peripheral(i - 1),
            _peripheral(i),
            (
                InterfaceView(_peripheral(i - 1), _outer(i), _inner(i)),
                InterfaceView(_peripheral(i), _inner(i), _outer(i)),
            ),
        )
        for i in range(_SIZE)
    )
    outer_interfaces = tuple(
        InterfaceSpec(
            f"outer-{_peripheral(i)}",
            _peripheral(i),
            None,
            (InterfaceView(_peripheral(i), _outer(i), _outer(i + 1)),),
            is_outer=True,
        )
        for i in range(_SIZE)
    )

    result = PlanarMap(
        name="wheel-4",
        pieces=(central,) + peripheral,
        vertices=vertices,
        interfaces=center_interfaces + radial_interfaces + outer_interfaces,
        automorphisms=tuple(_rotation(step) for step in range(_SIZE))
        + tuple(_reflection(axis) for axis in range(_SIZE)),
        reference_piece="C",
        hypotheses=ProblemHypotheses(
            piecewise_c2_boundary=True,
            center_strictly_inside_one_tile=True,
        ),
    )
    result.validate()
    return result
