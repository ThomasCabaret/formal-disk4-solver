from __future__ import annotations

"""Numerical Euclidean-copy checks for complete and partial arrangements.

The audit asks whether landmark incidences already fixed by a mapping and weak
order admit a common set of direct/reflected Euclidean copy isometries.  A
failed numerical solve is ``unresolved`` rather than a proof of impossibility.
The complete-leaf API is therefore observational.  The optional partial-state
pruner may use the same bounded solve experimentally, but marks every removed
subtree uncertified so exhaustion can never masquerade as a proof.

The incidence/holonomy model does not assume a disk boundary.  Unit-circle and
disk-containment residuals are a separate, explicit option and are disabled by
the free-boundary mode.
"""

from dataclasses import dataclass
from hashlib import blake2b
from math import cos, pi, sin
from time import perf_counter
from typing import Callable, Literal, Sequence

import numpy as np
from scipy.optimize import least_squares

from formal_disk4.enumeration.weak_orders import Placement
from formal_disk4.enumeration.assignments import cyclic_orientation_phase
from formal_disk4.enumeration.frontier_arrangements import (
    PartialArrangementState,
    PartialValidationResult,
)
from formal_disk4.maps.base import Occurrence, PlanarMap


BoundaryMode = Literal["auto", "free", "unit_disk"]


@dataclass(frozen=True)
class EuclideanPlacementAuditConfig:
    restarts: int = 4
    max_nfev: int = 300
    tolerance: float = 1.0e-7
    boundary_mode: BoundaryMode = "auto"

    def __post_init__(self) -> None:
        if self.restarts < 1:
            raise ValueError("Euclidean placement audit needs at least one restart")
        if self.max_nfev < 1:
            raise ValueError("Euclidean placement audit max_nfev must be positive")
        if self.tolerance <= 0.0:
            raise ValueError("Euclidean placement audit tolerance must be positive")
        if self.boundary_mode not in {"auto", "free", "unit_disk"}:
            raise ValueError(
                "Euclidean placement audit boundary_mode must be auto, free, or unit_disk"
            )


@dataclass(frozen=True)
class EuclideanPlacementAuditResult:
    status: str
    boundary_mode: str
    maximum_residual: float
    rms_residual: float
    variable_count: int
    residual_count: int
    jacobian_rank: int
    restarts: int
    evaluations: int

    @property
    def numerically_feasible(self) -> bool:
        return self.status == "numerically_feasible"

    @property
    def underdetermined(self) -> bool:
        return self.jacobian_rank < self.variable_count


class _EuclideanLeafSystem:
    def __init__(
        self,
        planar_map: PlanarMap,
        *,
        blocks: Sequence[Sequence[int]],
        positions: Sequence[int],
        active_piece_indices: Sequence[int],
        orientation_signs: Sequence[int | None],
        boundary_mode: BoundaryMode,
    ) -> None:
        self.planar_map = planar_map
        self.blocks = tuple(tuple(int(item) for item in block) for block in blocks)
        self.positions = tuple(int(item) for item in positions)
        self.active_piece_indices = tuple(int(item) for item in active_piece_indices)
        self.orientation_signs = tuple(orientation_signs)
        self.piece_names = tuple(piece.name for piece in planar_map.pieces)
        self.piece_index = {name: index for index, name in enumerate(self.piece_names)}
        self.reference_index = self.piece_index[planar_map.reference_piece]
        self.block_count = len(self.blocks)
        self.occurrence_index = {
            occurrence: index
            for index, occurrence in enumerate(planar_map.occurrences())
        }
        active_pieces = set(self.active_piece_indices)
        self.vertex_occurrences = tuple(
            tuple(
                (
                    self.piece_index[piece],
                    self.positions[
                        self.occurrence_index[Occurrence(piece, vertex.name)]
                    ],
                )
                for piece in vertex.incident_pieces
                if self.piece_index[piece] in active_pieces
            )
            for vertex in planar_map.vertices
        )

        if boundary_mode == "auto":
            # A relaxed/free outer boundary rewrites the corresponding map
            # vertices to kind='free'.  Retained outer or free_outer vertices,
            # including those of a partial crown, still lie on the unit circle.
            self.boundary_mode = (
                "unit_disk"
                if any(vertex.is_outer_boundary for vertex in planar_map.vertices)
                else "free"
            )
        else:
            self.boundary_mode = boundary_mode

        self._free_gauge = self.boundary_mode == "free"
        if self._free_gauge and self.block_count < 2:
            raise ValueError("Free-boundary Euclidean gauge needs two contour landmarks")

        self._point_variable_offset = 0
        self._point_variable_count = (
            2 * self.block_count
            if not self._free_gauge
            else 2 * (self.block_count - 2)
        )
        self._copy_variable_offset = self._point_variable_count
        self._copy_variable_index: dict[int, int] = {}
        cursor = self._copy_variable_offset
        for piece in self.active_piece_indices:
            if piece == self.reference_index:
                continue
            self._copy_variable_index[piece] = cursor
            cursor += 3
        self.variable_count = cursor

        self.outer_vertex_indices = tuple(
            index
            for index, vertex in enumerate(planar_map.vertices)
            if vertex.is_outer_boundary
        )

    def _points(self, values: np.ndarray) -> np.ndarray:
        if not self._free_gauge:
            return values[: self._point_variable_count].reshape(self.block_count, 2)
        points = np.zeros((self.block_count, 2), dtype=float)
        points[1, 0] = 1.0
        if self.block_count > 2:
            points[2:, :] = values[: self._point_variable_count].reshape(
                self.block_count - 2, 2
            )
        return points

    def _copy_parameters(
        self, values: np.ndarray, piece: int
    ) -> tuple[float, float, float]:
        if piece == self.reference_index:
            return 0.0, 0.0, 0.0
        offset = self._copy_variable_index[piece]
        return tuple(float(item) for item in values[offset : offset + 3])  # type: ignore[return-value]

    def _physical_point(
        self, values: np.ndarray, points: np.ndarray, piece: int, block: int
    ) -> np.ndarray:
        angle, tx, ty = self._copy_parameters(values, piece)
        raw_parity = self.orientation_signs[piece]
        if raw_parity is None:
            raise ValueError("Active Euclidean copy has no selected orientation")
        parity = int(raw_parity)
        cosine = cos(angle)
        sine = sin(angle)
        # Rotation followed by an optional prototype reflection.  Its
        # determinant is exactly the mapping parity selected by the formal leaf.
        matrix = np.asarray(
            ((cosine, -parity * sine), (sine, parity * cosine)), dtype=float
        )
        return matrix @ points[block] + np.asarray((tx, ty), dtype=float)

    def residuals(self, values: np.ndarray) -> np.ndarray:
        points = self._points(values)
        residuals: list[float] = []
        physical_vertices: list[np.ndarray] = []
        for occurrences in self.vertex_occurrences:
            if not occurrences:
                physical_vertices.append(np.asarray((np.nan, np.nan)))
                continue
            anchor_piece, anchor_block = occurrences[0]
            anchor = self._physical_point(
                values, points, anchor_piece, anchor_block
            )
            physical_vertices.append(anchor)
            for piece, block in occurrences[1:]:
                difference = (
                    self._physical_point(values, points, piece, block) - anchor
                )
                residuals.extend((float(difference[0]), float(difference[1])))

        if self.boundary_mode == "unit_disk":
            # These are the only disk-specific equations in this first audit.
            # They disappear entirely in free mode.
            for index in self.outer_vertex_indices:
                physical = physical_vertices[index]
                if np.isnan(physical).any():
                    continue
                residuals.append(float(np.dot(physical, physical) - 1.0))

            # Every prototype landmark must remain in the disk under every copy.
            # A one-sided residual records only violations; it does not pretend
            # to certify containment of the unknown curves between landmarks.
            for piece in self.active_piece_indices:
                for block in range(self.block_count):
                    physical = self._physical_point(values, points, piece, block)
                    excess = float(np.dot(physical, physical) - 1.0)
                    residuals.append(max(0.0, excess))

        return np.asarray(residuals or (0.0,), dtype=float)

    def initial_values(self, rng: np.random.Generator, restart: int) -> np.ndarray:
        values = np.zeros(self.variable_count, dtype=float)
        if self.block_count > 1:
            roots = np.exp(2j * pi * np.arange(self.block_count) / self.block_count)
            normalized = (roots - roots[0]) / (roots[1] - roots[0])
            base_points = np.column_stack((normalized.real, normalized.imag))
        else:
            base_points = np.zeros((self.block_count, 2), dtype=float)

        if self._free_gauge:
            if self.block_count > 2:
                values[: self._point_variable_count] = base_points[2:].reshape(-1)
        else:
            # In disk mode the disk center and radius fix translation and scale;
            # start with a centered contour instead of applying the free gauge.
            centered = base_points - np.mean(base_points, axis=0)
            radius = max(1.0e-9, float(np.max(np.linalg.norm(centered, axis=1))))
            values[: self._point_variable_count] = (0.8 * centered / radius).reshape(-1)

        for ordinal, (piece, offset) in enumerate(
            self._copy_variable_index.items(), 1
        ):
            values[offset] = 2.0 * pi * ordinal / max(
                1, len(self.active_piece_indices)
            )

        if restart:
            values += rng.normal(0.0, 0.35, size=self.variable_count)
        return values


def _stable_seed(
    planar_map: PlanarMap,
    blocks: Sequence[Sequence[int]],
    orientation_signs: Sequence[int | None],
) -> int:
    digest = blake2b(digest_size=8)
    digest.update(planar_map.name.encode("utf-8"))
    digest.update(
        ",".join("?" if item is None else str(item) for item in orientation_signs).encode(
            "ascii"
        )
    )
    for block in blocks:
        digest.update(b"|")
        digest.update(",".join(str(item) for item in block).encode("ascii"))
    return int.from_bytes(digest.digest(), "little")


def _run_audit(
    planar_map: PlanarMap,
    *,
    blocks: Sequence[Sequence[int]],
    positions: Sequence[int],
    active_piece_indices: Sequence[int],
    orientation_signs: Sequence[int | None],
    settings: EuclideanPlacementAuditConfig,
) -> EuclideanPlacementAuditResult:
    system = _EuclideanLeafSystem(
        planar_map,
        blocks=blocks,
        positions=positions,
        active_piece_indices=active_piece_indices,
        orientation_signs=orientation_signs,
        boundary_mode=settings.boundary_mode,
    )
    rng = np.random.default_rng(
        _stable_seed(planar_map, blocks, orientation_signs)
    )
    best = None
    total_evaluations = 0
    for restart in range(settings.restarts):
        result = least_squares(
            system.residuals,
            system.initial_values(rng, restart),
            max_nfev=settings.max_nfev,
            xtol=1.0e-10,
            ftol=1.0e-10,
            gtol=1.0e-10,
        )
        total_evaluations += int(result.nfev)
        residual = system.residuals(result.x)
        maximum = float(np.max(np.abs(residual))) if residual.size else 0.0
        if best is None or maximum < best[0]:
            best = (maximum, residual, result.jac)
        if maximum <= settings.tolerance:
            break

    assert best is not None
    maximum, residual, jacobian = best
    rms = float(np.sqrt(np.mean(np.square(residual)))) if residual.size else 0.0
    rank = int(np.linalg.matrix_rank(jacobian, tol=1.0e-9))
    return EuclideanPlacementAuditResult(
        status=(
            "numerically_feasible"
            if maximum <= settings.tolerance
            else "numerically_unresolved"
        ),
        boundary_mode=system.boundary_mode,
        maximum_residual=maximum,
        rms_residual=rms,
        variable_count=system.variable_count,
        residual_count=int(residual.size),
        jacobian_rank=rank,
        restarts=settings.restarts,
        evaluations=total_evaluations,
    )


def audit_euclidean_placement(
    planar_map: PlanarMap,
    placement: Placement,
    config: EuclideanPlacementAuditConfig | None = None,
) -> EuclideanPlacementAuditResult:
    """Numerically audit one complete mapping/weak-order leaf.

    ``numerically_unresolved`` is not an infeasibility result.  In particular,
    local optimization failure, an underdetermined system, and a genuinely
    contradictory incidence pattern are deliberately not conflated.
    """

    return _run_audit(
        planar_map,
        blocks=placement.blocks,
        positions=placement.positions,
        active_piece_indices=range(len(planar_map.pieces)),
        orientation_signs=placement.assignment.orientation_signs,
        settings=config or EuclideanPlacementAuditConfig(),
    )


def audit_partial_euclidean_placement(
    planar_map: PlanarMap,
    state: PartialArrangementState,
    config: EuclideanPlacementAuditConfig | None = None,
) -> EuclideanPlacementAuditResult:
    """Audit the Euclidean incidence system visible at one frontier node."""

    occurrences = planar_map.occurrences()
    occurrence_index = {
        occurrence: index for index, occurrence in enumerate(occurrences)
    }
    base_sequences = tuple(
        tuple(
            occurrence_index[Occurrence(piece.name, vertex)]
            for vertex in piece.contour_vertices
        )
        for piece in planar_map.pieces
    )
    orientations: list[int | None] = [None] * len(planar_map.pieces)
    for piece in state.placed_piece_indices:
        sequence = state.selected_sequences[piece]
        if sequence is None:
            raise ValueError("Placed frontier tile has no contour mapping")
        orientation, _phase = cyclic_orientation_phase(
            sequence, base_sequences[piece]
        )
        orientations[piece] = orientation
    return _run_audit(
        planar_map,
        blocks=state.blocks,
        positions=state.positions,
        active_piece_indices=state.placed_piece_indices,
        orientation_signs=orientations,
        settings=config or EuclideanPlacementAuditConfig(),
    )


class EuclideanPartialPlacementPruner:
    """Experimental numerical pruning at cycle-closing frontier nodes.

    Numerical failure is intentionally returned as an uncertified rejection.
    The surrounding exhaustive-search accounting therefore becomes tainted and
    cannot be used as a negative mathematical certificate.
    """

    def __init__(
        self,
        planar_map: PlanarMap,
        *,
        config: EuclideanPlacementAuditConfig | None = None,
        minimum_depth: int = 3,
        minimum_closed_neighbors: int = 2,
        event_sink: Callable[[str, int], None] | None = None,
    ) -> None:
        self.planar_map = planar_map
        self.config = config or EuclideanPlacementAuditConfig()
        self.minimum_depth = max(1, int(minimum_depth))
        self.minimum_closed_neighbors = max(1, int(minimum_closed_neighbors))
        self.event_sink = event_sink or (lambda _name, _amount=1: None)
        piece_index = {piece.name: index for index, piece in enumerate(planar_map.pieces)}
        neighbors = [set() for _piece in planar_map.pieces]
        for interface in planar_map.internal_interfaces():
            if interface.right_piece is None:
                continue
            left = piece_index[interface.left_piece]
            right = piece_index[interface.right_piece]
            neighbors[left].add(right)
            neighbors[right].add(left)
        self.neighbors = tuple(frozenset(items) for items in neighbors)

    def __call__(self, state: PartialArrangementState) -> PartialValidationResult:
        depth = len(state.placed_piece_indices)
        previously_placed = set(state.placed_piece_indices)
        previously_placed.discard(state.last_piece_index)
        closed_neighbors = sum(
            neighbor in previously_placed
            for neighbor in self.neighbors[state.last_piece_index]
        )
        if (
            depth < self.minimum_depth
            or closed_neighbors < self.minimum_closed_neighbors
        ):
            return PartialValidationResult(True)

        started = perf_counter()
        self.event_sink("euclidean_partial_audits", 1)
        self.event_sink(f"euclidean_partial_depth_{depth}_audits", 1)
        try:
            audit = audit_partial_euclidean_placement(
                self.planar_map, state, self.config
            )
        except Exception:
            # Fail open on implementation/optimizer errors.  Only a completed
            # bounded audit may participate in this experimental pruning mode.
            self.event_sink("euclidean_partial_audit_errors", 1)
            return PartialValidationResult(True)
        finally:
            self.event_sink(
                "euclidean_partial_audit_milliseconds",
                max(1, int(round(1000.0 * (perf_counter() - started)))),
            )

        if audit.numerically_feasible:
            self.event_sink("euclidean_partial_numerically_feasible", 1)
            self.event_sink(f"euclidean_partial_depth_{depth}_feasible", 1)
            return PartialValidationResult(True)

        self.event_sink("euclidean_partial_numerically_unresolved", 1)
        self.event_sink("euclidean_partial_pruned_subtrees", 1)
        self.event_sink(f"euclidean_partial_depth_{depth}_pruned", 1)
        return PartialValidationResult(
            False,
            reason=(
                "bounded Euclidean placement search found no witness; "
                f"depth={depth}, residual={audit.maximum_residual:.3g}"
            ),
            certified=False,
        )
