from __future__ import annotations

import math
from typing import Iterable, Sequence, Tuple

import numpy as np

from .model import GeometryValidation, OccurrenceGeometry, angle_wrap


def _cross(left: np.ndarray, right: np.ndarray) -> float:
    return float(left[0] * right[1] - left[1] * right[0])


def _point_segment_distance(point: np.ndarray, start: np.ndarray, end: np.ndarray) -> float:
    direction = end - start
    denominator = float(np.dot(direction, direction))
    if denominator <= 1e-30:
        return float(np.linalg.norm(point - start))
    parameter = float(np.dot(point - start, direction) / denominator)
    parameter = min(1.0, max(0.0, parameter))
    closest = start + parameter * direction
    return float(np.linalg.norm(point - closest))


def segment_distance(
    first_start: np.ndarray,
    first_end: np.ndarray,
    second_start: np.ndarray,
    second_end: np.ndarray,
    tolerance: float = 1e-12,
) -> Tuple[float, bool]:
    first_direction = first_end - first_start
    second_direction = second_end - second_start
    denominator = _cross(first_direction, second_direction)
    offset = second_start - first_start
    if abs(denominator) > tolerance:
        first_parameter = _cross(offset, second_direction) / denominator
        second_parameter = _cross(offset, first_direction) / denominator
        if (
            -tolerance <= first_parameter <= 1.0 + tolerance
            and -tolerance <= second_parameter <= 1.0 + tolerance
        ):
            return 0.0, True
    distance = min(
        _point_segment_distance(first_start, second_start, second_end),
        _point_segment_distance(first_end, second_start, second_end),
        _point_segment_distance(second_start, first_start, first_end),
        _point_segment_distance(second_end, first_start, first_end),
    )
    return distance, distance <= tolerance


def _segment_bbox_distance(
    first_start: np.ndarray,
    first_end: np.ndarray,
    second_start: np.ndarray,
    second_end: np.ndarray,
) -> float:
    first_min = np.minimum(first_start, first_end)
    first_max = np.maximum(first_start, first_end)
    second_min = np.minimum(second_start, second_end)
    second_max = np.maximum(second_start, second_end)
    gap = np.maximum(0.0, np.maximum(first_min - second_max, second_min - first_max))
    return float(np.linalg.norm(gap))


def pairwise_clearance_penalties(
    points: np.ndarray, clearance: float
) -> np.ndarray:
    """Fixed-size coarse collision residual for refinement only."""
    if len(points) < 4:
        return np.zeros(0, dtype=float)
    segment_count = len(points) - 1
    penalties = []
    for left in range(segment_count):
        for right in range(left + 1, segment_count):
            if right == left + 1:
                continue
            if left == 0 and right == segment_count - 1:
                continue
            lower_bound = _segment_bbox_distance(
                points[left], points[left + 1], points[right], points[right + 1]
            )
            if lower_bound >= clearance:
                penalties.append(0.0)
                continue
            distance, intersects = segment_distance(
                points[left], points[left + 1], points[right], points[right + 1]
            )
            penalty = max(0.0, clearance - distance)
            if intersects:
                penalty += 1.0
            penalties.append(penalty)
    return np.asarray(penalties, dtype=float)


def sampled_polyline(occurrences: Sequence[OccurrenceGeometry]) -> np.ndarray:
    points = []
    for occurrence in occurrences:
        samples = occurrence.sample_points
        if not points:
            points.extend(samples)
        else:
            points.extend(samples[1:])
    return np.asarray(points, dtype=float)


def nonadjacent_distances(points: np.ndarray) -> Tuple[float | None, int]:
    if len(points) < 4:
        return None, 0
    segment_count = len(points) - 1
    minimum = math.inf
    intersections = 0
    for left in range(segment_count):
        for right in range(left + 1, segment_count):
            if right == left + 1:
                continue
            if left == 0 and right == segment_count - 1:
                continue
            lower_bound = _segment_bbox_distance(
                points[left], points[left + 1], points[right], points[right + 1]
            )
            if lower_bound > minimum:
                continue
            distance, intersects = segment_distance(
                points[left], points[left + 1], points[right], points[right + 1]
            )
            minimum = min(minimum, distance)
            if intersects:
                intersections += 1
    return (None if math.isinf(minimum) else minimum), intersections


def signed_area(points: np.ndarray) -> float:
    if len(points) < 3:
        return 0.0
    if np.linalg.norm(points[0] - points[-1]) > 1e-12:
        closed = np.vstack((points, points[0]))
    else:
        closed = points
    return 0.5 * float(
        np.sum(closed[:-1, 0] * closed[1:, 1] - closed[:-1, 1] * closed[1:, 0])
    )


def validate_geometry(
    occurrences: Sequence[OccurrenceGeometry],
    target_angles: Sequence[float],
    *,
    closure_tolerance: float,
    tangent_tolerance: float,
    angle_tolerance: float,
    length_tolerance: float,
    intersection_tolerance: float,
    minimum_area: float,
    minimum_edge_length: float,
) -> GeometryValidation:
    if not occurrences:
        checks = (("nonempty_contour", False, "No curve occurrence was generated"),)
        return GeometryValidation(False, math.inf, math.inf, math.inf, math.inf, 0.0, None, 0, 0.0, checks)

    closure_error = float(np.linalg.norm(occurrences[-1].end_point - occurrences[0].start_point))
    final_vertex_turn = math.pi - float(target_angles[0])
    tangent_error = abs(
        angle_wrap(
            occurrences[-1].end_tangent + final_vertex_turn - occurrences[0].start_tangent
        )
    )

    angle_errors = []
    for boundary_index, target in enumerate(target_angles):
        incoming = occurrences[(boundary_index - 1) % len(occurrences)].end_tangent
        outgoing = occurrences[boundary_index].start_tangent
        measured_turn = angle_wrap(outgoing - incoming)
        target_turn = math.pi - float(target)
        angle_errors.append(abs(angle_wrap(measured_turn - target_turn)))
    maximum_angle_error = max(angle_errors, default=0.0)

    length_errors = []
    edge_lengths = []
    for occurrence in occurrences:
        sample_differences = np.diff(occurrence.control_points, axis=0)
        control_length = float(np.sum(np.linalg.norm(sample_differences, axis=1)))
        if occurrence.curve_type == "circular_arc":
            measured_length = abs(float(occurrence.arc_radius or 0.0) * float(occurrence.arc_sweep or 0.0))
        else:
            measured_length = control_length
        length_errors.append(abs(measured_length - occurrence.length))
        sample_edges = np.diff(occurrence.sample_points, axis=0)
        edge_lengths.extend(float(value) for value in np.linalg.norm(sample_edges, axis=1))
    maximum_length_error = max(length_errors, default=0.0)
    minimum_observed_edge = min(edge_lengths, default=0.0)

    circle_radii = {}
    for occurrence in occurrences:
        if occurrence.circle_class is None or occurrence.arc_radius is None:
            continue
        circle_radii.setdefault(occurrence.circle_class, []).append(float(occurrence.arc_radius))
    maximum_circle_radius_spread = 0.0
    circle_radius_valid = True
    for radii in circle_radii.values():
        if any((not math.isfinite(radius) or radius <= 0.0) for radius in radii):
            circle_radius_valid = False
            continue
        maximum_circle_radius_spread = max(
            maximum_circle_radius_spread, max(radii) - min(radii)
        )
    circle_radius_valid = (
        circle_radius_valid and maximum_circle_radius_spread <= length_tolerance
    )

    polyline = sampled_polyline(occurrences)
    minimum_distance, intersections = nonadjacent_distances(polyline)
    area = signed_area(polyline)

    checks = (
        (
            "closed_contour",
            closure_error <= closure_tolerance,
            f"closure_error={closure_error:.3e}, tolerance={closure_tolerance:.3e}",
        ),
        (
            "closed_tangent_cycle",
            tangent_error <= tangent_tolerance,
            f"tangent_error={tangent_error:.3e}, tolerance={tangent_tolerance:.3e}",
        ),
        (
            "formal_point_angles",
            maximum_angle_error <= angle_tolerance,
            f"max_angle_error={maximum_angle_error:.3e}, tolerance={angle_tolerance:.3e}",
        ),
        (
            "formal_curve_lengths",
            maximum_length_error <= length_tolerance,
            f"max_length_error={maximum_length_error:.3e}, tolerance={length_tolerance:.3e}",
        ),
        (
            "positive_sample_edges",
            minimum_observed_edge >= minimum_edge_length,
            f"minimum_sample_edge={minimum_observed_edge:.3e}, minimum={minimum_edge_length:.3e}",
        ),
        (
            "common_circle_radii",
            circle_radius_valid,
            f"maximum_radius_spread={maximum_circle_radius_spread:.3e}, tolerance={length_tolerance:.3e}",
        ),
        (
            "nonzero_enclosed_area",
            abs(area) >= minimum_area,
            f"signed_area={area:.9g}, minimum_absolute_area={minimum_area:.3e}",
        ),
        (
            "no_sampled_self_intersection",
            intersections == 0
            and (minimum_distance is None or minimum_distance > intersection_tolerance),
            (
                f"intersections={intersections}, minimum_nonadjacent_distance="
                f"{minimum_distance if minimum_distance is not None else 'n/a'}, "
                f"tolerance={intersection_tolerance:.3e}"
            ),
        ),
    )
    return GeometryValidation(
        passed=all(passed for _name, passed, _detail in checks),
        closure_error=closure_error,
        tangent_closure_error=tangent_error,
        maximum_angle_error=maximum_angle_error,
        maximum_length_error=maximum_length_error,
        signed_area=area,
        minimum_nonadjacent_distance=minimum_distance,
        self_intersection_count=intersections,
        minimum_edge_length=minimum_observed_edge,
        checks=checks,
    )
