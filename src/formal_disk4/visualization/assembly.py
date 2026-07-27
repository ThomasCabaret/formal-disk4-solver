from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple

import numpy as np


class AssemblyError(RuntimeError):
    """Raised when mappings do not determine a consistent connected assembly."""


@dataclass(frozen=True)
class Isometry2D:
    matrix: np.ndarray
    translation: np.ndarray

    @staticmethod
    def identity() -> "Isometry2D":
        return Isometry2D(np.eye(2, dtype=float), np.zeros(2, dtype=float))

    @property
    def determinant(self) -> float:
        return float(np.linalg.det(self.matrix))

    def apply(self, points: np.ndarray) -> np.ndarray:
        points = np.asarray(points, dtype=float)
        return points @ self.matrix.T + self.translation

    def inverse(self) -> "Isometry2D":
        inverse_matrix = self.matrix.T
        return Isometry2D(
            inverse_matrix,
            -(inverse_matrix @ self.translation),
        )

    def to_dict(self) -> Dict[str, object]:
        angle = math.atan2(float(self.matrix[1, 0]), float(self.matrix[0, 0]))
        return {
            "matrix": self.matrix.tolist(),
            "translation": self.translation.tolist(),
            "determinant": self.determinant,
            "orientation": "direct" if self.determinant > 0 else "reflected",
            "rotation_component_radians": angle,
        }


@dataclass(frozen=True)
class PiecePlacement:
    piece: str
    transform: Isometry2D
    polygon: np.ndarray

    def to_dict(self) -> Dict[str, object]:
        return {
            "piece": self.piece,
            "transform": self.transform.to_dict(),
            "polygon": self.polygon.tolist(),
        }


@dataclass(frozen=True)
class AssemblyValidation:
    passed: bool
    maximum_interface_error: float
    mean_interface_error: float
    interface_checks: Tuple[Mapping[str, Any], ...]
    connected_piece_count: int
    expected_piece_count: int

    def to_dict(self) -> Dict[str, object]:
        return {
            "passed": self.passed,
            "maximum_interface_error": self.maximum_interface_error,
            "mean_interface_error": self.mean_interface_error,
            "connected_piece_count": self.connected_piece_count,
            "expected_piece_count": self.expected_piece_count,
            "interface_checks": list(self.interface_checks),
        }


@dataclass(frozen=True)
class AssemblySolution:
    assembly_id: str
    geometric_solution_id: str
    formal_profile_id: str
    map_name: str
    reference_piece: str
    placements: Tuple[PiecePlacement, ...]
    validation: AssemblyValidation

    @property
    def placement_map(self) -> Dict[str, PiecePlacement]:
        return {placement.piece: placement for placement in self.placements}

    def to_dict(self) -> Dict[str, object]:
        return {
            "schema_version": "geometric-assembly-v1",
            "assembly_id": self.assembly_id,
            "geometric_solution_id": self.geometric_solution_id,
            "formal_profile_id": self.formal_profile_id,
            "map": self.map_name,
            "reference_piece": self.reference_piece,
            "pieces": [placement.to_dict() for placement in self.placements],
            "validation": self.validation.to_dict(),
        }


def _as_point_array(values: Sequence[Sequence[float]]) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim != 2 or array.shape[1] != 2:
        raise AssemblyError("Expected a two-dimensional point array")
    return array


def _polyline_lengths(points: np.ndarray) -> Tuple[np.ndarray, float]:
    if len(points) < 2:
        raise AssemblyError("A contour occurrence must contain at least two points")
    edge_lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    total = float(np.sum(edge_lengths))
    if total <= 1e-14:
        raise AssemblyError("A contour occurrence has zero chord length")
    cumulative = np.concatenate(([0.0], np.cumsum(edge_lengths)))
    return cumulative, total


def _resample_polyline(points: np.ndarray, count: int) -> np.ndarray:
    count = max(2, int(count))
    cumulative, total = _polyline_lengths(points)
    parameters = np.linspace(0.0, total, count)
    output = []
    edge_index = 0
    for parameter in parameters:
        while edge_index + 1 < len(cumulative) - 1 and parameter > cumulative[edge_index + 1]:
            edge_index += 1
        start = points[edge_index]
        end = points[edge_index + 1]
        edge_length = cumulative[edge_index + 1] - cumulative[edge_index]
        fraction = 0.0 if edge_length <= 1e-14 else (parameter - cumulative[edge_index]) / edge_length
        output.append(start + fraction * (end - start))
    return np.asarray(output, dtype=float)


def _sample_occurrence(occurrence: Mapping[str, Any], count: int) -> np.ndarray:
    if occurrence.get("curve_type") == "circular_arc":
        arc = occurrence.get("circular_arc")
        if not isinstance(arc, Mapping):
            raise AssemblyError("Circular occurrence lacks circular_arc data")
        center = np.asarray(arc["center"], dtype=float)
        start = np.asarray(occurrence["start_point"], dtype=float)
        radius = float(arc["radius"])
        sweep = float(arc["signed_sweep_radians"])
        if radius <= 0.0:
            raise AssemblyError("Circular occurrence has non-positive radius")
        start_angle = math.atan2(float(start[1] - center[1]), float(start[0] - center[0]))
        angles = start_angle + np.linspace(0.0, sweep, max(2, int(count)))
        samples = np.column_stack(
            (center[0] + radius * np.cos(angles), center[1] + radius * np.sin(angles))
        )
        samples[0] = start
        samples[-1] = np.asarray(occurrence["end_point"], dtype=float)
        return samples
    control = _as_point_array(occurrence["control_points"])
    return _resample_polyline(control, count)


def _directed_occurrence_points(
    occurrences: Mapping[int, Mapping[str, Any]],
    reference: Mapping[str, Any],
    count: int,
) -> np.ndarray:
    segment_index = int(reference["segment"])
    try:
        occurrence = occurrences[segment_index]
    except KeyError as exc:
        raise AssemblyError(f"Mapping references absent segment {segment_index}") from exc
    samples = _sample_occurrence(occurrence, count)
    if not bool(reference.get("forward", True)):
        samples = samples[::-1].copy()
    return samples


def _basis(direction: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(direction))
    if norm <= 1e-14:
        raise AssemblyError("Cannot align an interface with coincident endpoints")
    tangent = direction / norm
    normal = np.asarray((-tangent[1], tangent[0]), dtype=float)
    return np.column_stack((tangent, normal))


def _fit_oriented_isometry(
    source: np.ndarray,
    target: np.ndarray,
    determinant_sign: int,
) -> Isometry2D:
    if determinant_sign not in (-1, 1):
        raise AssemblyError(f"Invalid isometry parity {determinant_sign}")
    source_basis = _basis(source[-1] - source[0])
    target_basis = _basis(target[-1] - target[0])
    parity = np.diag((1.0, float(determinant_sign)))
    matrix = target_basis @ parity @ source_basis.T
    translation = target[0] - matrix @ source[0]
    return Isometry2D(matrix, translation)


def _mapping_clouds(
    mapping: Mapping[str, Any],
    occurrences: Mapping[int, Mapping[str, Any]],
    sample_count: int,
) -> Tuple[np.ndarray, np.ndarray]:
    left_cloud = []
    right_cloud = []
    pairs = mapping.get("pairs", [])
    if not isinstance(pairs, Sequence) or not pairs:
        raise AssemblyError(f"Interface {mapping.get('interface')} has no segment pairs")
    for pair in pairs:
        if not isinstance(pair, Mapping):
            raise AssemblyError("Invalid contact mapping pair")
        left = pair.get("left")
        right = pair.get("right")
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            raise AssemblyError("Contact mapping pair lacks left/right references")
        left_cloud.append(_directed_occurrence_points(occurrences, left, sample_count))
        right_cloud.append(_directed_occurrence_points(occurrences, right, sample_count))
    return np.concatenate(left_cloud), np.concatenate(right_cloud)


def _derive_unknown_transform(
    *,
    known_transform: Isometry2D,
    known_local_cloud: np.ndarray,
    unknown_local_cloud: np.ndarray,
    relative_parity: int,
) -> Isometry2D:
    target = known_transform.apply(known_local_cloud)
    absolute_determinant = 1 if known_transform.determinant * relative_parity > 0 else -1
    return _fit_oriented_isometry(unknown_local_cloud, target, absolute_determinant)


def _interface_error(
    left_transform: Isometry2D,
    right_transform: Isometry2D,
    left_cloud: np.ndarray,
    right_cloud: np.ndarray,
) -> Tuple[float, float]:
    residuals = np.linalg.norm(
        left_transform.apply(left_cloud) - right_transform.apply(right_cloud), axis=1
    )
    return float(np.max(residuals)), float(np.sqrt(np.mean(residuals**2)))


def _prototype_polygon(
    occurrences: Sequence[Mapping[str, Any]],
    arc_sample_count: int,
) -> np.ndarray:
    polygon_parts = []
    for index, occurrence in enumerate(occurrences):
        count = arc_sample_count if occurrence.get("curve_type") == "circular_arc" else max(
            2, len(occurrence.get("control_points", []))
        )
        samples = _sample_occurrence(occurrence, count)
        if index:
            samples = samples[1:]
        polygon_parts.append(samples)
    polygon = np.concatenate(polygon_parts)
    if np.linalg.norm(polygon[-1] - polygon[0]) <= 1e-10:
        polygon = polygon[:-1]
    if len(polygon) < 3:
        raise AssemblyError("The piece contour does not define a polygon")
    return polygon


def _assembly_identifier(record: Mapping[str, Any], placements: Iterable[PiecePlacement]) -> str:
    payload = {
        "geometric_solution_id": record.get("geometric_solution", {}).get(
            "geometric_solution_id"
        ),
        "placements": {
            placement.piece: {
                "matrix": np.round(placement.transform.matrix, 12).tolist(),
                "translation": np.round(placement.transform.translation, 12).tolist(),
            }
            for placement in placements
        },
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    return f"assembly-{digest}"


def assemble_geometric_solution(
    record: Mapping[str, Any],
    *,
    interface_sample_count: int = 25,
    polygon_arc_sample_count: int = 64,
    tolerance: float = 1e-6,
) -> AssemblySolution:
    geometric = record.get("geometric_solution")
    formal = record.get("formal_candidate")
    if not isinstance(geometric, Mapping):
        raise AssemblyError("Record does not contain geometric_solution")
    if not isinstance(formal, Mapping):
        raise AssemblyError(
            "Record does not contain formal_candidate; geometry output must include it"
        )
    map_record = formal.get("map")
    profile = formal.get("profile")
    if not isinstance(map_record, Mapping) or not isinstance(profile, Mapping):
        raise AssemblyError("Formal candidate lacks map/profile data")
    raw_pieces = map_record.get("pieces")
    if not isinstance(raw_pieces, Sequence) or not raw_pieces:
        raise AssemblyError("Planar map contains no pieces")
    piece_names = tuple(str(item["name"]) for item in raw_pieces if isinstance(item, Mapping))
    if not piece_names:
        raise AssemblyError("Planar map contains no named pieces")
    reference_piece = str(map_record.get("reference_piece", piece_names[0]))
    if reference_piece not in piece_names:
        raise AssemblyError(f"Unknown reference piece {reference_piece}")

    raw_occurrences = geometric.get("contour_occurrences")
    if not isinstance(raw_occurrences, Sequence) or not raw_occurrences:
        raise AssemblyError("Geometric solution lacks contour occurrences")
    ordered_occurrences = tuple(
        sorted(
            (item for item in raw_occurrences if isinstance(item, Mapping)),
            key=lambda item: int(item["segment_index"]),
        )
    )
    occurrences = {int(item["segment_index"]): item for item in ordered_occurrences}
    prototype_polygon = _prototype_polygon(ordered_occurrences, polygon_arc_sample_count)

    raw_mappings = profile.get("contact_mappings")
    if not isinstance(raw_mappings, Sequence):
        raise AssemblyError("Formal profile lacks contact mappings")
    mappings = tuple(item for item in raw_mappings if isinstance(item, Mapping))

    transforms: Dict[str, Isometry2D] = {reference_piece: Isometry2D.identity()}
    mapping_clouds: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
    for mapping in mappings:
        name = str(mapping.get("interface", f"interface-{len(mapping_clouds)}"))
        mapping_clouds[name] = _mapping_clouds(mapping, occurrences, interface_sample_count)

    while len(transforms) < len(piece_names):
        progress = False
        for mapping in mappings:
            left_piece = str(mapping["left_piece"])
            right_piece = str(mapping["right_piece"])
            parity = int(mapping.get("relative_parity", 1))
            interface_name = str(mapping.get("interface", "interface"))
            left_cloud, right_cloud = mapping_clouds[interface_name]
            left_known = left_piece in transforms
            right_known = right_piece in transforms
            if left_known and not right_known:
                transforms[right_piece] = _derive_unknown_transform(
                    known_transform=transforms[left_piece],
                    known_local_cloud=left_cloud,
                    unknown_local_cloud=right_cloud,
                    relative_parity=parity,
                )
                progress = True
            elif right_known and not left_known:
                transforms[left_piece] = _derive_unknown_transform(
                    known_transform=transforms[right_piece],
                    known_local_cloud=right_cloud,
                    unknown_local_cloud=left_cloud,
                    relative_parity=parity,
                )
                progress = True
        if not progress:
            missing = sorted(set(piece_names) - set(transforms))
            raise AssemblyError(
                "Internal-contact graph does not connect all pieces to the reference: "
                + ", ".join(missing)
            )

    checks = []
    maximum_error = 0.0
    squared_errors = []
    for mapping in mappings:
        interface_name = str(mapping.get("interface", "interface"))
        left_piece = str(mapping["left_piece"])
        right_piece = str(mapping["right_piece"])
        left_cloud, right_cloud = mapping_clouds[interface_name]
        max_error, rms_error = _interface_error(
            transforms[left_piece],
            transforms[right_piece],
            left_cloud,
            right_cloud,
        )
        maximum_error = max(maximum_error, max_error)
        squared_errors.append(rms_error * rms_error)
        expected_parity = int(mapping.get("relative_parity", 1))
        actual_relative = transforms[left_piece].determinant * transforms[right_piece].determinant
        parity_ok = (1 if actual_relative > 0 else -1) == expected_parity
        checks.append(
            {
                "interface": interface_name,
                "left_piece": left_piece,
                "right_piece": right_piece,
                "maximum_error": max_error,
                "rms_error": rms_error,
                "expected_relative_parity": expected_parity,
                "parity_passed": parity_ok,
                "passed": max_error <= tolerance and parity_ok,
            }
        )
    mean_error = math.sqrt(sum(squared_errors) / len(squared_errors)) if squared_errors else 0.0
    passed = len(transforms) == len(piece_names) and all(bool(item["passed"]) for item in checks)

    placements = tuple(
        PiecePlacement(
            piece=piece,
            transform=transforms[piece],
            polygon=transforms[piece].apply(prototype_polygon),
        )
        for piece in piece_names
    )
    validation = AssemblyValidation(
        passed=passed,
        maximum_interface_error=maximum_error,
        mean_interface_error=mean_error,
        interface_checks=tuple(checks),
        connected_piece_count=len(transforms),
        expected_piece_count=len(piece_names),
    )
    if not validation.passed:
        failed = [str(item["interface"]) for item in checks if not item["passed"]]
        raise AssemblyError(
            "Mappings produced an inconsistent assembly; failed interfaces: "
            + ", ".join(failed)
        )

    return AssemblySolution(
        assembly_id=_assembly_identifier(record, placements),
        geometric_solution_id=str(geometric.get("geometric_solution_id", "unknown")),
        formal_profile_id=str(record.get("formal_profile_id", geometric.get("formal_profile_id", "unknown"))),
        map_name=str(map_record.get("name", "unknown")),
        reference_piece=reference_piece,
        placements=placements,
        validation=validation,
    )
