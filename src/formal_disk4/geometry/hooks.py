from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Tuple

from formal_disk4.profiles.model import FormalProfile


class GeometryHook(Protocol):
    name: str

    def evaluate(self, profile: FormalProfile) -> Tuple[bool, str]: ...


@dataclass(frozen=True)
class DeferredGeometryHook:
    """Placeholder for chord, closure, isometry, signed-area and disk constraints."""

    name: str = "deferred_geometry"

    def evaluate(self, profile: FormalProfile) -> Tuple[bool, str]:
        return True, "not implemented"
