from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterator, Sequence

from .base import PlanarMap
from .c3 import build_c3_map
from .c4 import build_c4_map
from .k4 import build_k4_map
from .k4_minus_arc import build_k4_minus_arc_map
from .k4_minus_point import build_k4_minus_point_map


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
)

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

    return tuple(registration.name for registration in _REGISTRATIONS)


def map_descriptions() -> Dict[str, str]:
    return {
        registration.name: registration.description
        for registration in _REGISTRATIONS
    }


def canonical_map_name(name: str) -> str:
    try:
        return _LOOKUP[name].name
    except KeyError as error:
        raise ValueError(
            f"Unknown map {name!r}; available: {', '.join(available_maps())}"
        ) from error


def build_map(name: str) -> PlanarMap:
    canonical = canonical_map_name(name)
    return _CANONICAL[canonical].builder()


def iterate_maps(names: Sequence[str]) -> Iterator[PlanarMap]:
    for name in names:
        yield build_map(name)
