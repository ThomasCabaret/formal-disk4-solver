from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import ceil, isqrt, sqrt
from typing import Dict, Iterable, Mapping, Sequence, Tuple

from formal_disk4.constraints.hybrid_linear import (
    HybridLinearResult,
    HybridMarginOracle,
    LinearConstraint,
)
from formal_disk4.enumeration.weak_orders import Placement
from formal_disk4.maps.base import PlanarMap
from formal_disk4.words.algebra import Word
from formal_disk4.words.compile import CompiledWordCase

from .arc_topology import RadiusArcTopologyResult


@dataclass(frozen=True)
class PrewordLinearInvariantResult:
    feasible: bool
    reason: str
    metric_status: str
    point_angle_status: str
    metric_exact_certificate_used: bool
    point_angle_exact_certificate_used: bool
    signed_radius_balance_derived: bool
    smooth_turn_balance_derived: bool
    point_turn_balance_derived: bool
    radius_concavity_required: bool
    isoperimetric_bound: Fraction | None

    def to_dict(self) -> Dict[str, object]:
        return {
            "feasible": self.feasible,
            "reason": self.reason,
            "metric_status": self.metric_status,
            "point_angle_status": self.point_angle_status,
            "metric_exact_certificate_used": self.metric_exact_certificate_used,
            "point_angle_exact_certificate_used": self.point_angle_exact_certificate_used,
            "signed_radius_balance_derived": self.signed_radius_balance_derived,
            "smooth_turn_balance_derived": self.smooth_turn_balance_derived,
            "point_turn_balance_derived": self.point_turn_balance_derived,
            "radius_concavity_required": self.radius_concavity_required,
            "isoperimetric_sqrt_upper_bound": (
                {
                    "numerator": self.isoperimetric_bound.numerator,
                    "denominator": self.isoperimetric_bound.denominator,
                    "float": float(self.isoperimetric_bound),
                }
                if self.isoperimetric_bound is not None
                else None
            ),
        }


class _AffineRowSpace:
    """Exact affine row-space test used only for invariant audits."""

    def __init__(self, width: int, equations: Iterable[LinearConstraint]) -> None:
        rows = [list(item.coefficients) + [item.rhs] for item in equations]
        current = 0
        pivots: list[tuple[int, list[Fraction]]] = []
        for column in range(width):
            pivot = next(
                (index for index in range(current, len(rows)) if rows[index][column]),
                None,
            )
            if pivot is None:
                continue
            rows[current], rows[pivot] = rows[pivot], rows[current]
            factor = rows[current][column]
            rows[current] = [value / factor for value in rows[current]]
            for index in range(len(rows)):
                if index == current:
                    continue
                multiplier = rows[index][column]
                if multiplier:
                    rows[index] = [
                        value - multiplier * pivot_value
                        for value, pivot_value in zip(rows[index], rows[current])
                    ]
            pivots.append((column, rows[current]))
            current += 1
            if current == len(rows):
                break
        self._pivots = tuple(pivots)
        self._width = width

    def implies(self, equation: LinearConstraint) -> bool:
        row = list(equation.coefficients) + [equation.rhs]
        for column, pivot in self._pivots:
            factor = row[column]
            if factor:
                row = [
                    value - factor * pivot_value
                    for value, pivot_value in zip(row, pivot)
                ]
        return not any(row)


def _safe_sqrt_upper_bound(value: int, denominator: int) -> Fraction:
    root = isqrt(value)
    if root * root == value:
        return Fraction(root)
    denominator = max(1, int(denominator))
    # The ceiling produces a certified upper bound, hence a weaker but sound
    # linear form of the isoperimetric inequality for non-square tile counts.
    numerator = ceil(sqrt(value) * denominator)
    return Fraction(numerator, denominator)


class PrewordLinearInvariantFilter:
    """Necessary metric and turning conditions before Nielsen--Levi.

    The metric system combines positive atomic lengths, same-radius convex and
    concave measures, and smooth curve turns scaled by the disk circumference.
    This scaling keeps the circle relation linear: H = +/-2 L on a radius-R arc.

    Point angles remain a separate LP because their local vertex equations do
    not share variables with lengths. Both systems use a floating screen and an
    exact rational certificate before rejecting a placement.
    """

    def __init__(
        self,
        *,
        tolerance: float = 1e-9,
        enable_radius_measures: bool = True,
        enable_smooth_turns: bool = True,
        enable_point_turns: bool = True,
        enforce_global_point_turn_balance: bool = True,
        enable_isoperimetric: bool = True,
        sqrt_upper_bound_denominator: int = 1000,
    ) -> None:
        self.metric_oracle = HybridMarginOracle(tolerance=tolerance)
        self.point_oracle = HybridMarginOracle(tolerance=tolerance)
        self.enable_radius_measures = bool(enable_radius_measures)
        self.enable_smooth_turns = bool(enable_smooth_turns)
        self.enable_point_turns = bool(enable_point_turns)
        self.enforce_global_point_turn_balance = bool(
            enforce_global_point_turn_balance
        )
        self.enable_isoperimetric = bool(enable_isoperimetric)
        self.sqrt_upper_bound_denominator = max(1, int(sqrt_upper_bound_denominator))

    @staticmethod
    def _word_counts(word: Word, variable_index: Mapping[str, int], size: int) -> Tuple[int, ...]:
        counts = [0] * size
        for literal in word:
            counts[variable_index[literal.variable]] += 1
        return tuple(counts)

    @staticmethod
    def _physical_turn_counts(
        word: Word,
        piece: str,
        placement: Placement,
        variable_index: Mapping[str, int],
        size: int,
    ) -> Tuple[int, ...]:
        piece_index = placement.assignment.piece_names.index(piece)
        copy_parity = placement.assignment.orientation_signs[piece_index]
        counts = [0] * size
        for literal in word:
            traversal = -1 if literal.inverse else 1
            counts[variable_index[literal.variable]] += copy_parity * traversal
        return tuple(counts)

    @staticmethod
    def _add_block(
        row: list[Fraction],
        offset: int,
        coefficients: Sequence[int | Fraction],
        scale: int | Fraction = 1,
    ) -> None:
        factor = Fraction(scale)
        for index, coefficient in enumerate(coefficients):
            row[offset + index] += factor * Fraction(coefficient)

    def analyze(
        self,
        planar_map: PlanarMap,
        placement: Placement,
        compiled: CompiledWordCase,
        topology: RadiusArcTopologyResult,
    ) -> PrewordLinearInvariantResult:
        if not topology.feasible:
            return PrewordLinearInvariantResult(
                False,
                topology.reason,
                "not_run",
                "not_run",
                False,
                False,
                False,
                False,
                False,
                planar_map.hypotheses.requires_radius_r_concavity,
                None,
            )

        metric, metric_audit, sqrt_bound = self._analyze_metric(
            planar_map, placement, compiled, topology
        )
        if not metric.feasible:
            return PrewordLinearInvariantResult(
                False,
                "preword metric/radius/turn system is infeasible",
                metric.status,
                "not_run",
                metric.exact_certificate_used,
                False,
                metric_audit[0],
                metric_audit[1],
                False,
                planar_map.hypotheses.requires_radius_r_concavity,
                sqrt_bound,
            )

        point, point_derived = self._analyze_point_turns(planar_map, placement)
        if not point.feasible:
            return PrewordLinearInvariantResult(
                False,
                "preword point-angle system is infeasible",
                metric.status,
                point.status,
                metric.exact_certificate_used,
                point.exact_certificate_used,
                metric_audit[0],
                metric_audit[1],
                point_derived,
                planar_map.hypotheses.requires_radius_r_concavity,
                sqrt_bound,
            )

        return PrewordLinearInvariantResult(
            True,
            "feasible",
            metric.status,
            point.status,
            metric.exact_certificate_used,
            point.exact_certificate_used,
            metric_audit[0],
            metric_audit[1],
            point_derived,
            planar_map.hypotheses.requires_radius_r_concavity,
            sqrt_bound,
        )

    def _analyze_metric(
        self,
        planar_map: PlanarMap,
        placement: Placement,
        compiled: CompiledWordCase,
        topology: RadiusArcTopologyResult,
    ) -> tuple[HybridLinearResult, tuple[bool, bool], Fraction | None]:
        size = len(compiled.atomic_variables)
        variable_index = {name: index for index, name in enumerate(compiled.atomic_variables)}
        length_offset = 0
        positive_offset = size
        negative_offset = 2 * size
        turn_offset = 3 * size
        margin_index = 4 * size
        width = margin_index + 1
        domains = (
            ("nonnegative",) * (3 * size)
            + ("free",) * size
            + ("nonnegative",)
        )
        equalities: list[LinearConstraint] = []
        inequalities: list[LinearConstraint] = []

        def row() -> list[Fraction]:
            return [Fraction(0) for _ in range(width)]

        def add_equality(values: Sequence[int | Fraction], rhs: int | Fraction = 0) -> None:
            equalities.append(LinearConstraint.build(values, rhs))

        def add_inequality(values: Sequence[int | Fraction], rhs: int | Fraction = 0) -> None:
            inequalities.append(LinearConstraint.build(values, rhs))

        # Existing interface-length equations remain the primary geometric scale
        # constraints. The normalization only removes the common scale factor.
        for length_equation in placement.length_rows:
            values = row()
            self._add_block(values, length_offset, length_equation)
            add_equality(values)
        values = row()
        self._add_block(values, length_offset, (1,) * size)
        add_equality(values, 1)

        for index in range(size):
            values = row()
            values[length_offset + index] = -1
            values[margin_index] = 1
            add_inequality(values, 0)

            if self.enable_radius_measures:
                # Radius-R portions are measures inside an atomic curve; they may
                # occupy only part of a generic atom before word subdivision.
                values = row()
                values[positive_offset + index] = 1
                values[negative_offset + index] = 1
                values[length_offset + index] = -1
                add_inequality(values, 0)

        outer_counts = [0] * size
        for outer in compiled.outer_arcs:
            counts = self._word_counts(outer.positive_word, variable_index, size)
            outer_counts = [left + right for left, right in zip(outer_counts, counts)]

        local_equalities_before_globals: list[LinearConstraint] = list(equalities)
        if self.enable_radius_measures:
            for interface in compiled.interfaces:
                left = self._word_counts(interface.left_positive_word, variable_index, size)
                right = self._word_counts(interface.right_positive_word, variable_index, size)

                values = row()
                self._add_block(values, positive_offset, left)
                self._add_block(values, negative_offset, right, -1)
                add_equality(values)

                values = row()
                self._add_block(values, negative_offset, left)
                self._add_block(values, positive_offset, right, -1)
                add_equality(values)

            for index, sign in enumerate(topology.forced_atomic_signs):
                if sign == 0:
                    continue
                values = row()
                values[(positive_offset if sign > 0 else negative_offset) + index] = 1
                values[length_offset + index] = -1
                add_equality(values)

                values = row()
                values[(negative_offset if sign > 0 else positive_offset) + index] = 1
                add_equality(values, 0)

        if self.enable_smooth_turns and planar_map.hypotheses.piecewise_c2_boundary:
            for interface in compiled.interfaces:
                left = self._physical_turn_counts(
                    interface.left_positive_word,
                    interface.left_piece,
                    placement,
                    variable_index,
                    size,
                )
                right = self._physical_turn_counts(
                    interface.right_positive_word,
                    interface.right_piece,
                    placement,
                    variable_index,
                    size,
                )
                values = row()
                self._add_block(values, turn_offset, left)
                self._add_block(values, turn_offset, right)
                add_equality(values)

            # H_i = C_disk * K_i/pi. On a radius-R arc this becomes H_i=+/-2 L_i,
            # avoiding any division by the unknown disk circumference.
            for index, sign in enumerate(topology.forced_atomic_signs):
                if sign == 0:
                    continue
                values = row()
                values[turn_offset + index] = 1
                values[length_offset + index] = -2 * sign
                add_equality(values)

        local_equalities_before_globals = list(equalities)
        tile_count = len(planar_map.pieces)

        radius_global = row()
        self._add_block(radius_global, positive_offset, (tile_count,) * size)
        self._add_block(radius_global, negative_offset, (-tile_count,) * size)
        self._add_block(radius_global, length_offset, outer_counts, -1)
        radius_equation = LinearConstraint.build(radius_global, 0)
        radius_derived = (
            self.enable_radius_measures
            and _AffineRowSpace(width, local_equalities_before_globals).implies(radius_equation)
        )
        if self.enable_radius_measures:
            # This theorem is valid even if local propagation is incomplete. Keeping
            # it explicit strengthens the LP while the audit checks our local model.
            equalities.append(radius_equation)

        smooth_global = row()
        self._add_block(smooth_global, turn_offset, (tile_count,) * size)
        self._add_block(smooth_global, length_offset, outer_counts, -2)
        smooth_equation = LinearConstraint.build(smooth_global, 0)
        smooth_derived = (
            self.enable_smooth_turns
            and planar_map.hypotheses.piecewise_c2_boundary
            and _AffineRowSpace(width, local_equalities_before_globals).implies(smooth_equation)
        )
        if self.enable_smooth_turns and planar_map.hypotheses.piecewise_c2_boundary:
            equalities.append(smooth_equation)

        if (
            self.enable_radius_measures
            and planar_map.hypotheses.requires_radius_r_concavity
        ):
            values = row()
            self._add_block(values, negative_offset, (-1,) * size)
            values[margin_index] = 1
            add_inequality(values, 0)

        sqrt_bound: Fraction | None = None
        if self.enable_isoperimetric:
            sqrt_bound = _safe_sqrt_upper_bound(
                tile_count, self.sqrt_upper_bound_denominator
            )
            values = row()
            self._add_block(values, length_offset, outer_counts)
            self._add_block(values, length_offset, (-sqrt_bound,) * size)
            add_inequality(values, 0)

        values = row()
        values[margin_index] = 1
        add_inequality(values, 1)

        result = self.metric_oracle.analyze(
            variable_domains=domains,
            equalities=equalities,
            inequalities=inequalities,
            margin_index=margin_index,
        )
        return result, (radius_derived, smooth_derived), sqrt_bound

    def _analyze_point_turns(
        self,
        planar_map: PlanarMap,
        placement: Placement,
    ) -> tuple[HybridLinearResult, bool]:
        point_count = placement.interval_count
        margin_index = point_count
        width = point_count + 1
        domains = ("free",) * point_count + ("nonnegative",)
        equalities: list[LinearConstraint] = []
        inequalities: list[LinearConstraint] = []

        for equation in placement.angle_equations:
            values = [Fraction(value) for value in equation.coefficients] + [Fraction(0)]
            equalities.append(LinearConstraint.build(values, Fraction(str(equation.rhs))))

        tile_count = len(planar_map.pieces)
        global_values = [Fraction(1) for _ in range(point_count)] + [Fraction(0)]
        global_equation = LinearConstraint.build(
            global_values,
            Fraction(2) - Fraction(2, tile_count),
        )
        derived = _AffineRowSpace(width, equalities).implies(global_equation)
        if (
            self.enable_point_turns
            and self.enforce_global_point_turn_balance
            and planar_map.hypotheses.piecewise_c2_boundary
        ):
            equalities.append(global_equation)

        for index in range(point_count):
            upper = [Fraction(0) for _ in range(width)]
            upper[index] = 1
            upper[margin_index] = 1
            inequalities.append(LinearConstraint.build(upper, 1))

            lower = [Fraction(0) for _ in range(width)]
            lower[index] = -1
            lower[margin_index] = 1
            inequalities.append(LinearConstraint.build(lower, 1))

        margin_upper = [Fraction(0) for _ in range(width)]
        margin_upper[margin_index] = 1
        inequalities.append(LinearConstraint.build(margin_upper, 1))

        if not self.enable_point_turns or not planar_map.hypotheses.piecewise_c2_boundary:
            return HybridLinearResult(True, None, "disabled", False), derived

        return self.point_oracle.analyze(
            variable_domains=domains,
            equalities=equalities,
            inequalities=inequalities,
            margin_index=margin_index,
        ), derived
