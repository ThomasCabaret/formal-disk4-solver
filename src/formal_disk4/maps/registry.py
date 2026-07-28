from __future__ import annotations

from typing import Callable, Dict, Iterator, Sequence

from .base import PlanarMap
from .k3_pizza import build_k3_pizza_map
from .k4_central import build_k4_central_map
from .k4_pizza import build_k4_pizza_map


_MAP_BUILDERS: Dict[str, Callable[[], PlanarMap]] = {
    "k3-pizza": build_k3_pizza_map,
    "k4-central": build_k4_central_map,
    "k4-pizza": build_k4_pizza_map,
}


def available_maps() -> tuple[str, ...]:
    return tuple(sorted(_MAP_BUILDERS))


def build_map(name: str) -> PlanarMap:
    try:
        return _MAP_BUILDERS[name]()
    except KeyError as error:
        raise ValueError(f"Unknown map {name!r}; available: {', '.join(available_maps())}") from error


def iterate_maps(names: Sequence[str]) -> Iterator[PlanarMap]:
    for name in names:
        yield build_map(name)
