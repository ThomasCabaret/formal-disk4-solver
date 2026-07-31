from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from formal_disk4.enumeration.weak_orders import Placement
from formal_disk4.maps.base import PlanarMap
from formal_disk4.words.compile import CompiledWordCase

from .arc_topology import RadiusArcTopologyFilter, RadiusArcTopologyResult
from .linear_invariants import (
    PrewordLinearInvariantFilter,
    PrewordLinearInvariantResult,
)


@dataclass(frozen=True)
class PrewordPruningResult:
    feasible: bool
    reason: str
    topology: RadiusArcTopologyResult
    linear_invariants: PrewordLinearInvariantResult | None

    def to_dict(self) -> Dict[str, object]:
        return {
            "feasible": self.feasible,
            "reason": self.reason,
            "topology": self.topology.to_dict(),
            "linear_invariants": (
                self.linear_invariants.to_dict()
                if self.linear_invariants is not None
                else None
            ),
        }


class PrewordPruningPipeline:
    """Independent necessary conditions applied before word resolution.

    Structural interval checks run first because they are cheaper and highly
    selective. The exact linear systems are built only for survivors, keeping
    the expensive Nielsen--Levi graph behind all available low-cost pruning.
    """

    def __init__(
        self,
        *,
        topology_filter: RadiusArcTopologyFilter,
        linear_filter: PrewordLinearInvariantFilter,
        enable_topology: bool = True,
        enable_linear_invariants: bool = True,
    ) -> None:
        self.topology_filter = topology_filter
        self.linear_filter = linear_filter
        self.enable_topology = bool(enable_topology)
        self.enable_linear_invariants = bool(enable_linear_invariants)
        self._current_phase = "idle"

    def progress_snapshot(self) -> Dict[str, object]:
        return {"phase": self._current_phase}

    def analyze(
        self,
        planar_map: PlanarMap,
        placement: Placement,
        compiled: CompiledWordCase,
    ) -> PrewordPruningResult:
        self._current_phase = "topology"
        topology = (
            self.topology_filter.analyze(planar_map, placement, compiled)
            if self.enable_topology
            else self.topology_filter.seed_only(compiled)
        )
        if not topology.feasible:
            self._current_phase = "done"
            return PrewordPruningResult(False, topology.reason, topology, None)
        if not self.enable_linear_invariants:
            self._current_phase = "done"
            return PrewordPruningResult(True, "feasible", topology, None)
        self._current_phase = "linear_invariants"
        linear = self.linear_filter.analyze(planar_map, placement, compiled, topology)
        self._current_phase = "done"
        return PrewordPruningResult(
            linear.feasible,
            linear.reason,
            topology,
            linear,
        )
