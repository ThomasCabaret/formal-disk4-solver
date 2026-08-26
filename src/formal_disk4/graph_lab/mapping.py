from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from formal_disk4.enumeration.assignments import ContourAssignment
from formal_disk4.maps.base import InterfaceView, PlanarMap
from formal_disk4.pipeline.filter_report import FilterReport

from .feedback import formal_profile_ids

from .space import DualGraphCandidate


@dataclass(frozen=True)
class MappingProposal:
    """One complete contour mapping, before the intrinsic quotient filter."""

    candidate: DualGraphCandidate
    raw_assignment_id: int
    orientation_signs: tuple[int, ...]
    cyclic_offsets: tuple[int, ...]
    contour_lengths: tuple[int, ...]
    edge_ports: tuple[tuple[float, ...], ...]
    source_candidate: DualGraphCandidate | None = None

    @property
    def evaluation_source(self) -> DualGraphCandidate:
        """Complete graph from which an experimental partial map was cut."""

        return self.source_candidate or self.candidate

    @property
    def mapping_id(self) -> str:
        payload = (
            self.candidate.graph_id,
            self.raw_assignment_id,
            self.orientation_signs,
            self.cyclic_offsets,
            self.contour_lengths,
            self.edge_ports,
        )
        if self.source_candidate is not None:
            payload = (*payload, ("source", self.source_candidate.graph_id))
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return "mp-" + hashlib.sha256(encoded).hexdigest()[:32]

    @classmethod
    def from_assignment(
        cls,
        candidate: DualGraphCandidate,
        assignment: ContourAssignment,
        planar_map: PlanarMap,
        *,
        source_candidate: DualGraphCandidate | None = None,
    ) -> "MappingProposal":
        piece_index = {
            name: index for index, name in enumerate(assignment.piece_names)
        }
        occurrence_index = {
            occurrence: index
            for index, occurrence in enumerate(planar_map.occurrences())
        }
        positions = tuple(
            {occurrence_id: position for position, occurrence_id in enumerate(sequence)}
            for sequence in assignment.sequences
        )

        def port(piece_name: str, view: InterfaceView) -> tuple[float, ...]:
            index = piece_index[piece_name]
            length = len(assignment.sequences[index])
            start = positions[index][occurrence_index[view.start_occurrence]]
            end = positions[index][occurrence_index[view.end_occurrence]]
            angle = 2.0 * math.pi * float(start) / max(1, length)
            delta = (end - start) % length
            direction = 1.0 if delta == 1 else (-1.0 if delta == length - 1 else 0.0)
            return (math.sin(angle), math.cos(angle), direction, 1.0)

        interface_by_edge: dict[tuple[int, int], object] = {}
        for interface in planar_map.interfaces:
            # A free cut is not the disk exterior and therefore has no dual
            # graph edge. In a crown, the same tile commonly owns both an
            # outer-circle arc and an unrelated free inner edge; allowing the
            # latter to reuse the OUTSIDE key would silently encode the wrong
            # contour port for the mapping ranker.
            if interface.is_free:
                continue
            left = piece_index[interface.left_piece]
            right = (
                -1
                if interface.right_piece is None
                else piece_index[interface.right_piece]
            )
            interface_by_edge[(min(left, right), max(left, right))] = interface
        edge_ports = []
        absent = (0.0, 0.0, 0.0, 0.0)
        for edge in candidate.edges:
            interface = interface_by_edge[edge]
            views = {view.piece: view for view in interface.views}  # type: ignore[attr-defined]
            sides = []
            for node in edge:
                if node == -1:
                    sides.append(absent)
                else:
                    piece_name = assignment.piece_names[node]
                    sides.append(port(piece_name, views[piece_name]))
            edge_ports.append(tuple((*sides[0], *sides[1])))
        return cls(
            candidate=candidate,
            raw_assignment_id=int(assignment.assignment_id),
            orientation_signs=tuple(int(value) for value in assignment.orientation_signs),
            cyclic_offsets=tuple(int(value) for value in assignment.cyclic_offsets),
            contour_lengths=tuple(len(sequence) for sequence in assignment.sequences),
            edge_ports=tuple(edge_ports),
            source_candidate=source_candidate,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "graph-lab-mapping-proposal-v2",
            "mapping_id": self.mapping_id,
            "candidate": self.candidate.to_dict(),
            "raw_assignment_id": self.raw_assignment_id,
            "orientation_signs": list(self.orientation_signs),
            "cyclic_offsets": list(self.cyclic_offsets),
            "contour_lengths": list(self.contour_lengths),
            "edge_ports": [list(value) for value in self.edge_ports],
            "source_candidate": (
                self.source_candidate.to_dict()
                if self.source_candidate is not None
                else None
            ),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "MappingProposal":
        return cls(
            candidate=DualGraphCandidate.from_dict(payload["candidate"]),  # type: ignore[arg-type]
            raw_assignment_id=int(payload["raw_assignment_id"]),
            orientation_signs=tuple(
                int(value) for value in payload["orientation_signs"]  # type: ignore[union-attr]
            ),
            cyclic_offsets=tuple(
                int(value) for value in payload["cyclic_offsets"]  # type: ignore[union-attr]
            ),
            contour_lengths=tuple(
                int(value) for value in payload["contour_lengths"]  # type: ignore[union-attr]
            ),
            edge_ports=tuple(
                tuple(float(item) for item in value)
                for value in payload["edge_ports"]  # type: ignore[union-attr]
            ),
            source_candidate=(
                DualGraphCandidate.from_dict(payload["source_candidate"])  # type: ignore[arg-type]
                if isinstance(payload.get("source_candidate"), Mapping)
                else None
            ),
        )


@dataclass(frozen=True)
class MappingEvaluation:
    """Aggregated descendants of one fixed graph + contour mapping."""

    proposal: MappingProposal
    filters: FilterReport
    counters: Mapping[str, int]
    rollout_count: int
    elapsed_seconds: float
    profiles: tuple[Mapping[str, object], ...]
    tainted: bool
    stop_reasons: tuple[str, ...]
    reach_vector: tuple[float | None, ...] = ()
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.reach_vector:
            object.__setattr__(
                self,
                "reach_vector",
                tuple(
                    None if self.tainted else (1.0 if observation.entered else 0.0)
                    for observation in self.filters.observations
                ),
            )
        if len(self.reach_vector) != len(self.filters.observations):
            raise ValueError("Mapping reach vector does not align with filter report")

    @property
    def target_vector(self) -> tuple[float | None, ...]:
        return self.filters.target_vector()

    @property
    def deepest_filter_index(self) -> int:
        deepest = -1
        for index, observation in enumerate(self.filters.observations):
            if observation.entered or observation.passed:
                deepest = index
        return deepest

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "graph-lab-mapping-observation-v1",
            "proposal": self.proposal.to_dict(),
            "filter_report": self.filters.to_dict(),
            "target_vector": list(self.target_vector),
            "reach_vector": list(self.reach_vector),
            "deepest_filter_index": self.deepest_filter_index,
            "counters": dict(self.counters),
            "rollout_count": self.rollout_count,
            "elapsed_seconds": self.elapsed_seconds,
            "profile_count": len(self.profiles),
            "profile_ids": list(formal_profile_ids(self.profiles)),
            "tainted": self.tainted,
            "stop_reasons": list(self.stop_reasons),
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "MappingEvaluation":
        report_payload = payload.get("filter_report")
        if not isinstance(report_payload, Mapping):
            raise ValueError("Mapping observation has no filter_report")
        identifiers = tuple(
            str(value) for value in payload.get("profile_ids", ())  # type: ignore[union-attr]
        )
        profile_count = int(payload.get("profile_count", len(identifiers)))
        restored_profiles = [
            {"formal_profile_id": profile_id} for profile_id in identifiers
        ]
        restored_profiles.extend(
            {} for _ in range(max(0, profile_count - len(restored_profiles)))
        )
        filters = FilterReport.from_dict(report_payload)
        raw_reach = payload.get("reach_vector")
        reach_vector = (
            tuple(None if value is None else float(value) for value in raw_reach)
            if isinstance(raw_reach, Sequence)
            and not isinstance(raw_reach, (str, bytes))
            else tuple(
                None
                if bool(payload.get("tainted", False))
                else (1.0 if observation.entered else 0.0)
                for observation in filters.observations
            )
        )
        return cls(
            proposal=MappingProposal.from_dict(payload["proposal"]),  # type: ignore[arg-type]
            filters=filters,
            counters={
                str(name): int(value)
                for name, value in dict(payload.get("counters", {})).items()  # type: ignore[arg-type]
            },
            rollout_count=int(payload.get("rollout_count", 1)),
            elapsed_seconds=float(payload.get("elapsed_seconds", 0.0)),
            profiles=tuple(restored_profiles),
            tainted=bool(payload.get("tainted", False)),
            stop_reasons=tuple(
                str(value) for value in payload.get("stop_reasons", ())  # type: ignore[union-attr]
            ),
            reach_vector=reach_vector,
            error=str(payload["error"]) if payload.get("error") else None,
        )


def sum_counters(values: Sequence[Mapping[str, int]]) -> dict[str, int]:
    output: dict[str, int] = {}
    for counters in values:
        for name, value in counters.items():
            output[str(name)] = output.get(str(name), 0) + int(value)
    return output
