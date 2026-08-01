from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, Dict, Iterator, Sequence

from .base import PlanarMap
from .c3 import build_c3_map
from .c4 import build_c4_map
from .centered_two_ring import (
    build_centered_double_cycle_map,
    build_centered_double_cycle_offset_map,
    build_centered_inner_cycle_boundary_points_map,
    build_centered_outer_cycle_center_points_map,
)
from .double_cycle import build_double_cycle_map
from .k4 import build_k4_map
from .k4_minus_arc import build_k4_minus_arc_map
from .k4_minus_point import build_k4_minus_point_map
from .wheel import build_wheel_4_map, build_wheel_map
from .two_ring_families import (
    build_double_cycle_offset_map,
    build_inner_cycle_boundary_points_map,
    build_outer_cycle_center_points_map,
)
from .three_ring_families import (
    build_three_ring_boundary_points_map,
    build_three_ring_inner_offset_map,
    build_three_ring_offset_opposite_map,
    build_three_ring_offset_same_map,
    build_three_ring_outer_offset_map,
    build_three_ring_parallel_map,
)


@dataclass(frozen=True)
class MapRegistration:
    name: str
    builder: Callable[[], PlanarMap]
    description: str
    aliases: tuple[str, ...] = ()


_REGISTRATIONS = (
    MapRegistration(
        "c3",
        build_c3_map,
        "Three-sector cycle validation case",
        aliases=("k3-pizza",),
    ),
    MapRegistration(
        "c4",
        build_c4_map,
        "Four-sector cycle validation case",
        aliases=("k4-pizza",),
    ),
    MapRegistration(
        "k4",
        build_k4_map,
        "Complete four-piece contact graph with an internal central tile",
        aliases=("k4-central",),
    ),
    MapRegistration(
        "k4-minus-point",
        build_k4_minus_point_map,
        "K4 minus T1-T3; the central tile reaches the boundary at one point",
    ),
    MapRegistration(
        "k4-minus-arc",
        build_k4_minus_arc_map,
        "K4 minus T1-T3; the central tile owns one outer boundary arc",
    ),
    MapRegistration(
        "wheel-4",
        build_wheel_4_map,
        "Four outer tiles forming a cycle around one central tile (wheel W5)",
        aliases=("four-cycle-center",),
    ),
)

_DYNAMIC_MAP_PATTERNS = (
    ("wheel", re.compile(r"^wheel-(\d+)$"), build_wheel_map),
    (
        "centered-double-cycle",
        re.compile(r"^centered-double-cycle-(\d+)$"),
        build_centered_double_cycle_map,
    ),
    (
        "centered-double-cycle-offset",
        re.compile(r"^centered-double-cycle-offset-(\d+)$"),
        build_centered_double_cycle_offset_map,
    ),
    (
        "centered-inner-cycle-boundary-points",
        re.compile(r"^centered-inner-cycle-boundary-points-(\d+)$"),
        build_centered_inner_cycle_boundary_points_map,
    ),
    (
        "centered-outer-cycle-center-points",
        re.compile(r"^centered-outer-cycle-center-points-(\d+)$"),
        build_centered_outer_cycle_center_points_map,
    ),
    ("double-cycle", re.compile(r"^double-cycle-(\d+)$"), build_double_cycle_map),
    (
        "double-cycle-offset",
        re.compile(r"^double-cycle-offset-(\d+)$"),
        build_double_cycle_offset_map,
    ),
    (
        "inner-cycle-boundary-points",
        re.compile(r"^inner-cycle-boundary-points-(\d+)$"),
        build_inner_cycle_boundary_points_map,
    ),
    (
        "outer-cycle-center-points",
        re.compile(r"^outer-cycle-center-points-(\d+)$"),
        build_outer_cycle_center_points_map,
    ),
    (
        "three-ring-parallel",
        re.compile(r"^three-ring-parallel-(\d+)$"),
        build_three_ring_parallel_map,
    ),
    (
        "three-ring-boundary-points",
        re.compile(r"^three-ring-boundary-points-(\d+)$"),
        build_three_ring_boundary_points_map,
    ),
    (
        "three-ring-outer-offset",
        re.compile(r"^three-ring-outer-offset-(\d+)$"),
        build_three_ring_outer_offset_map,
    ),
    (
        "three-ring-inner-offset",
        re.compile(r"^three-ring-inner-offset-(\d+)$"),
        build_three_ring_inner_offset_map,
    ),
    (
        "three-ring-offset-same",
        re.compile(r"^three-ring-offset-same-(\d+)$"),
        build_three_ring_offset_same_map,
    ),
    (
        "three-ring-offset-opposite",
        re.compile(r"^three-ring-offset-opposite-(\d+)$"),
        build_three_ring_offset_opposite_map,
    ),
)

_DYNAMIC_ALIASES = {
    "dc6": "double-cycle-6",
}

_FEATURED_DYNAMIC_MAPS = {
    "double-cycle-6": (
        "Twelve-tile validation family: two 6-cycles joined by matching contacts"
    ),
}

_CANONICAL: Dict[str, MapRegistration] = {
    registration.name: registration for registration in _REGISTRATIONS
}
_LOOKUP: Dict[str, MapRegistration] = dict(_CANONICAL)
for registration in _REGISTRATIONS:
    for alias in registration.aliases:
        if alias in _LOOKUP:
            raise RuntimeError(f"Duplicate map name or alias: {alias}")
        _LOOKUP[alias] = registration


def available_maps() -> tuple[str, ...]:
    """Return stable canonical case identifiers, excluding legacy aliases."""

    names = [registration.name for registration in _REGISTRATIONS]
    names[2:2] = _FEATURED_DYNAMIC_MAPS
    return tuple(names)


def map_descriptions() -> Dict[str, str]:
    descriptions = {
        registration.name: registration.description
        for registration in _REGISTRATIONS
    }
    descriptions.update(_FEATURED_DYNAMIC_MAPS)
    return descriptions


def canonical_map_name(name: str) -> str:
    name = _DYNAMIC_ALIASES.get(name, name)
    registration = _LOOKUP.get(name)
    if registration is not None:
        return registration.name
    for prefix, pattern, _builder in _DYNAMIC_MAP_PATTERNS:
        match = pattern.fullmatch(name)
        if match is not None and int(match.group(1)) >= 3:
            return f"{prefix}-{int(match.group(1))}"
    raise ValueError(
        f"Unknown map {name!r}; available: {', '.join(available_maps())}, "
        "or a supported cyclic family ending in -N with N >= 3"
    )


def build_map(name: str) -> PlanarMap:
    canonical = canonical_map_name(name)
    registration = _CANONICAL.get(canonical)
    if registration is not None:
        return registration.builder()
    for _prefix, pattern, builder in _DYNAMIC_MAP_PATTERNS:
        match = pattern.fullmatch(canonical)
        if match is not None:
            return builder(int(match.group(1)))
    raise RuntimeError(f"No builder for canonical map {canonical!r}")


def iterate_maps(names: Sequence[str]) -> Iterator[PlanarMap]:
    for name in names:
        yield build_map(name)
