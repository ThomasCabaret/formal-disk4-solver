from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import random
from typing import Callable, Mapping, Sequence, Tuple

import numpy as np
from scipy.optimize import linprog

from formal_disk4.constraints.rational_lp import RationalSimplex
from formal_disk4.enumeration.assignments import AssignmentTransform, ContourAssignment


@dataclass(frozen=True)
class JointPrefixExtension:
    """A positive-length extension and LP-witnessed next weak-order blocks."""

    margin: float
    next_masks: Tuple[int, ...]


@dataclass(frozen=True)
class _ExactMarginOutcome:
    """Tri-state result: only ``infeasible`` is an exact rejection proof."""

    verdict: str  # feasible, infeasible, unknown
    margin: Fraction | None = None
    solution: Tuple[Fraction, ...] = ()


class CyclicJointWeakLengthOracle:
    """Certify and guide cyclic weak-order prefixes with a length LP.

    A cyclic-shift solution of order ``m`` divides the prototype contour into
    ``m`` congruent metric domains.  Each occurrence in the first domain gets a
    coordinate ``z`` in ``[0, 1)``; its ``j``-th rotated copy has normalized
    contour coordinate ``(j + z) / m``.  The assignment order constraints and
    every interface length equality are therefore linear.  Maximizing a common
    positive margin proves that the induced weak order has positive atomic
    contour lengths before that order is committed to the formal pipeline.

    The LP only owns the constraints it can state exactly: positive atomic
    contour lengths and equality of both views of every interface length.  It
    does not absorb the topology predicates.  Instead, its solutions provide
    one or more legal next blocks which the ordinary enumerator checks with its
    independent exact topology filters.

    Random secondary objectives expose different witnesses.  The caller also
    retains uniformly sampled legal actions and conventional rollouts, so this
    oracle can improve ordering without removing stochastic full support.
    """

    def __init__(
        self,
        assignment: ContourAssignment,
        transform: AssignmentTransform,
        splits: Sequence[Sequence[int]],
        positive_arc_endpoints: Mapping[Tuple[int, int], Tuple[int, int]],
        interface_count: int,
        reference_index: int,
        outer_arc_equalities: Sequence[
            Sequence[Tuple[int, int]]
        ] = (),
        *,
        random_seed: int,
        tolerance: float = 1e-9,
        witness_attempts: int = 6,
        minimum_margin_fraction: float = 0.10,
        exact_max_tableau_cells: int = 50_000,
        exact_max_pivots: int = 512,
        exact_max_coefficient_bits: int = 2_048,
        exact_time_limit_seconds: float = 0.10,
        event_sink: Callable[[str, int], None] | None = None,
    ) -> None:
        self.assignment = assignment
        self.transform = transform
        self.splits = tuple(tuple(int(value) for value in split) for split in splits)
        self.positive_arc_endpoints = dict(positive_arc_endpoints)
        self.interface_count = int(interface_count)
        self.reference_index = int(reference_index)
        self.outer_arc_equalities = tuple(
            tuple(
                (int(left), int(right))
                for left, right in alternative
            )
            for alternative in outer_arc_equalities
        )
        self.rng = random.Random(int(random_seed))
        self.tolerance = max(1e-12, float(tolerance))
        self.witness_attempts = max(0, int(witness_attempts))
        self.minimum_margin_fraction = min(
            1.0, max(0.0, float(minimum_margin_fraction))
        )
        self.exact_max_tableau_cells = max(1, int(exact_max_tableau_cells))
        self.exact_max_pivots = max(0, int(exact_max_pivots))
        self.exact_max_coefficient_bits = max(
            1, int(exact_max_coefficient_bits)
        )
        self.exact_time_limit_seconds = max(
            0.0, float(exact_time_limit_seconds)
        )
        # One pathological exact LP is enough evidence that this oracle's
        # remaining, closely related prefix systems should use the ordinary
        # full-support route.  This circuit breaker is a performance decision,
        # never a rejection decision.
        self._exact_budget_exhausted = False
        self.event_sink = event_sink or (lambda _name, _amount=1: None)
        self.order = self._permutation_order(transform.occurrence_map)
        if self.order < 2 or transform.reverse_cycle:
            raise ValueError(
                "Joint cyclic length sampling needs a direct nontrivial action"
            )
        self.occurrence_count = len(transform.occurrence_map)
        self._sequence_positions = self._build_sequence_positions()

    @staticmethod
    def _permutation_order(permutation: Sequence[int]) -> int:
        unseen = set(range(len(permutation)))
        order = 1
        while unseen:
            seed = min(unseen)
            current = seed
            length = 0
            while current in unseen:
                unseen.remove(current)
                current = int(permutation[current])
                length += 1
            if current != seed:
                raise ValueError("Cyclic action is not a permutation")
            order = int(np.lcm(order, length))
        return order

    def _build_sequence_positions(self) -> dict[int, tuple[int, int, int]]:
        result: dict[int, tuple[int, int, int]] = {}
        for piece_index, sequence in enumerate(self.assignment.sequences):
            for position, occurrence_id in enumerate(sequence):
                if occurrence_id in result:
                    raise ValueError("An occurrence belongs to multiple tile contours")
                result[int(occurrence_id)] = (
                    piece_index,
                    position,
                    len(sequence),
                )
        if len(result) != self.occurrence_count:
            raise ValueError("Assignment sequences do not cover every occurrence")
        return result

    def _arc_wrap(self, start: int, end: int) -> int:
        start_piece, start_position, size = self._sequence_positions[start]
        end_piece, end_position, end_size = self._sequence_positions[end]
        if start_piece != end_piece or size != end_size:
            raise ValueError("Positive arc endpoints belong to different pieces")
        if (start_position + 1) % size != end_position:
            raise ValueError("Positive arc endpoints are not consecutive")
        return 1 if start_position + 1 == size else 0

    def _domain_coordinates(
        self, split: Sequence[int]
    ) -> tuple[tuple[int, ...], dict[int, tuple[int, int]]] | None:
        fundamental = tuple(
            sorted(
                occurrence_id
                for piece_index, sequence in enumerate(self.assignment.sequences)
                for occurrence_id in sequence[: int(split[piece_index])]
            )
        )
        if not fundamental:
            return None
        reference_occurrence = self.assignment.sequences[self.reference_index][0]
        if reference_occurrence not in fundamental:
            return None
        coordinates: dict[int, tuple[int, int]] = {}
        for variable_index, base_occurrence in enumerate(fundamental):
            current = int(base_occurrence)
            for domain_index in range(self.order):
                if current in coordinates:
                    return None
                coordinates[current] = (variable_index, domain_index)
                current = int(self.transform.occurrence_map[current])
            if current != base_occurrence:
                return None
        if set(coordinates) != set(range(self.occurrence_count)):
            return None
        return fundamental, coordinates

    def _build_system(
        self, split: Sequence[int]
    ) -> tuple[
        tuple[int, ...],
        dict[int, tuple[int, int]],
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        list[tuple[float | None, float | None]],
    ] | None:
        domain = self._domain_coordinates(split)
        if domain is None:
            return None
        fundamental, coordinates = domain
        variable_count = len(fundamental)
        epsilon_index = variable_count
        width = variable_count + 1
        inequalities: list[list[float]] = []
        inequality_rhs: list[float] = []
        equalities: list[list[float]] = []
        equality_rhs: list[float] = []

        # Every consecutive prototype contour edge has strictly positive
        # length.  Coordinates are scaled to one rotational domain, whereas
        # epsilon is measured on the full normalized contour.
        for sequence in self.assignment.sequences:
            for position, start in enumerate(sequence):
                end = sequence[(position + 1) % len(sequence)]
                start_variable, start_domain = coordinates[int(start)]
                end_variable, end_domain = coordinates[int(end)]
                wrap = 1 if position + 1 == len(sequence) else 0
                row = [0.0] * width
                row[start_variable] += 1.0
                row[end_variable] -= 1.0
                row[epsilon_index] += float(self.order)
                rhs = float(end_domain - start_domain + self.order * wrap)
                inequalities.append(row)
                inequality_rhs.append(rhs)

        # Both views of one positive-length interface describe the same
        # prototype arclength.  The weak order is not needed to write this in
        # cumulative coordinates.
        for interface_index in range(self.interface_count):
            left_start, left_end = self.positive_arc_endpoints[
                (interface_index, 0)
            ]
            right_start, right_end = self.positive_arc_endpoints[
                (interface_index, 1)
            ]
            row = [0.0] * width
            constant = 0.0
            for occurrence_id, coefficient in (
                (left_end, 1.0),
                (left_start, -1.0),
                (right_end, -1.0),
                (right_start, 1.0),
            ):
                variable_index, domain_index = coordinates[occurrence_id]
                row[variable_index] += coefficient
                constant += coefficient * domain_index
            constant += self.order * (
                self._arc_wrap(left_start, left_end)
                - self._arc_wrap(right_start, right_end)
            )
            equalities.append(row)
            equality_rhs.append(-constant)

        reference_occurrence = self.assignment.sequences[self.reference_index][0]
        reference_variable, reference_domain = coordinates[reference_occurrence]
        if reference_domain != 0:
            return None
        anchor = [0.0] * width
        anchor[reference_variable] = 1.0
        equalities.append(anchor)
        equality_rhs.append(0.0)

        # A half-open fundamental domain avoids representing the same boundary
        # block once at z=1 and again at z=0 in the next rotated copy.  Every
        # genuine cyclic order has an equivalent choice of boundary with this
        # convention; the conventional rollout route remains a safety net.
        upper = 1.0 - max(1e-10, self.tolerance * 10.0)
        bounds: list[tuple[float | None, float | None]] = [
            (0.0, upper) for _ in fundamental
        ] + [(0.0, 1.0)]
        return (
            fundamental,
            coordinates,
            np.asarray(inequalities, dtype=float),
            np.asarray(inequality_rhs, dtype=float),
            np.asarray(equalities, dtype=float),
            np.asarray(equality_rhs, dtype=float),
            bounds,
        )

    @staticmethod
    def _with_coordinate_equalities(
        equalities: np.ndarray,
        equality_rhs: np.ndarray,
        coordinates: Mapping[int, Tuple[int, int]],
        occurrence_pairs: Sequence[Tuple[int, int]],
        width: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Add exact equal-prototype-coordinate equations for one arc pair."""

        rows: list[list[float]] = []
        rhs: list[float] = []
        for left_occurrence, right_occurrence in occurrence_pairs:
            left_variable, left_domain = coordinates[int(left_occurrence)]
            right_variable, right_domain = coordinates[int(right_occurrence)]
            row = [0.0] * width
            row[left_variable] += 1.0
            row[right_variable] -= 1.0
            rows.append(row)
            rhs.append(float(right_domain - left_domain))
        if not rows:
            return equalities, equality_rhs
        return (
            np.vstack((equalities, np.asarray(rows, dtype=float))),
            np.concatenate((equality_rhs, np.asarray(rhs, dtype=float))),
        )

    @staticmethod
    def _fraction(value: float) -> Fraction:
        rounded = round(float(value))
        if abs(float(value) - rounded) <= 1e-12:
            return Fraction(int(rounded))
        return Fraction(str(float(value)))

    def _exact_margin(
        self,
        A_ub: np.ndarray,
        b_ub: np.ndarray,
        A_eq: np.ndarray,
        b_eq: np.ndarray,
        width: int,
    ) -> _ExactMarginOutcome:
        """Solve the prefix system exactly and certify strict feasibility.

        All combinatorial coefficients are rational.  Variables are
        nonnegative; explicit upper bounds make the LP bounded.  Equality rows
        are represented by their two opposite inequalities.  Consequently a
        non-positive exact optimum is a sound rejection certificate, unlike a
        floating ``linprog`` status.
        """

        if self._exact_budget_exhausted:
            self.event_sink("joint_weak_length_exact_skipped", 1)
            return _ExactMarginOutcome("unknown")

        row_count = len(A_ub) + 2 * len(A_eq) + width
        tableau_cells = (row_count + 2) * (width + 2)
        if tableau_cells > self.exact_max_tableau_cells:
            self._exact_budget_exhausted = True
            self.event_sink("joint_weak_length_exact_resource_limit", 1)
            self.event_sink("joint_weak_length_exact_tableau_limit", 1)
            return _ExactMarginOutcome("unknown")

        inequalities: list[list[Fraction]] = []
        rhs: list[Fraction] = []
        for row, value in zip(A_ub, b_ub):
            inequalities.append([self._fraction(item) for item in row])
            rhs.append(self._fraction(value))
        for row, value in zip(A_eq, b_eq):
            normalized = [self._fraction(item) for item in row]
            target = self._fraction(value)
            inequalities.append(normalized)
            rhs.append(target)
            inequalities.append([-item for item in normalized])
            rhs.append(-target)
        for variable_index in range(width):
            row = [Fraction(0) for _ in range(width)]
            row[variable_index] = Fraction(1)
            inequalities.append(row)
            rhs.append(Fraction(1))
        objective = [Fraction(0) for _ in range(width)]
        objective[-1] = Fraction(1)
        self.event_sink("joint_weak_length_exact_lp_calls", 1)
        result = RationalSimplex(
            inequalities,
            rhs,
            objective,
            max_tableau_cells=self.exact_max_tableau_cells,
            max_pivots=self.exact_max_pivots,
            max_coefficient_bits=self.exact_max_coefficient_bits,
            max_seconds=self.exact_time_limit_seconds,
        ).solve()
        if result.status == "resource_limit":
            self._exact_budget_exhausted = True
            self.event_sink("joint_weak_length_exact_resource_limit", 1)
            return _ExactMarginOutcome("unknown")
        if result.status == "infeasible":
            self.event_sink("joint_weak_length_exact_infeasible", 1)
            return _ExactMarginOutcome("infeasible")
        if result.status != "optimal" or result.optimum is None:
            # An unexpected/unbounded exact result is not an infeasibility
            # certificate.  Preserve the branch conservatively.
            self.event_sink("joint_weak_length_exact_unknown", 1)
            return _ExactMarginOutcome("unknown")
        if result.optimum <= 0:
            self.event_sink("joint_weak_length_exact_zero_margin", 1)
            return _ExactMarginOutcome("infeasible")
        self.event_sink("joint_weak_length_exact_feasible", 1)
        return _ExactMarginOutcome(
            "feasible", result.optimum, result.solution
        )

    def prefix_extension(
        self,
        split_index: int,
        fundamental_blocks: Sequence[Sequence[int]],
        *,
        include_witnesses: bool = True,
    ) -> JointPrefixExtension | None:
        """Return length feasibility and suggested next blocks for a prefix.

        The blocks are a fixed prefix of the rotational fundamental domain.
        Occurrences in one block have equal contour coordinates, consecutive
        blocks are strictly separated, and every unresolved occurrence must
        lie strictly after the current frontier.  The remaining coordinates
        stay free, so feasibility means that *some* descendant weak order also
        satisfies every interface-length equation.

        The first solve maximizes the common positive-length margin.  Optional
        secondary objectives expose alternative next blocks without fixing a
        complete weak order.  These masks are proposals only: the caller still
        applies every topology predicate and retains uniform legal proposals.
        """

        if split_index < 0 or split_index >= len(self.splits):
            return None
        built = self._build_system(self.splits[split_index])
        if built is None:
            return None
        (
            fundamental,
            coordinates,
            A_ub,
            b_ub,
            A_eq,
            b_eq,
            bounds,
        ) = built
        fundamental_set = set(fundamental)
        normalized_blocks = tuple(
            tuple(int(occurrence_id) for occurrence_id in block)
            for block in fundamental_blocks
        )
        flattened = tuple(
            occurrence_id
            for block in normalized_blocks
            for occurrence_id in block
        )
        if (
            any(not block for block in normalized_blocks)
            or len(flattened) != len(set(flattened))
            or not set(flattened) <= fundamental_set
        ):
            return None

        variable_count = len(fundamental)
        epsilon_index = variable_count
        width = variable_count + 1
        variable_for_occurrence = {
            occurrence_id: variable_index
            for occurrence_id, (variable_index, domain_index) in coordinates.items()
            if domain_index == 0
        }
        extra_inequalities: list[list[float]] = []
        extra_inequality_rhs: list[float] = []
        extra_equalities: list[list[float]] = []
        extra_equality_rhs: list[float] = []

        for block in normalized_blocks:
            representative = variable_for_occurrence[block[0]]
            for occurrence_id in block[1:]:
                row = [0.0] * width
                row[variable_for_occurrence[occurrence_id]] += 1.0
                row[representative] -= 1.0
                extra_equalities.append(row)
                extra_equality_rhs.append(0.0)

        for previous, current in zip(
            normalized_blocks, normalized_blocks[1:]
        ):
            row = [0.0] * width
            row[variable_for_occurrence[previous[0]]] += 1.0
            row[variable_for_occurrence[current[0]]] -= 1.0
            row[epsilon_index] += float(self.order)
            extra_inequalities.append(row)
            extra_inequality_rhs.append(0.0)

        if normalized_blocks:
            last_variable = variable_for_occurrence[normalized_blocks[-1][0]]
            unresolved = fundamental_set - set(flattened)
            for occurrence_id in unresolved:
                row = [0.0] * width
                row[last_variable] += 1.0
                row[variable_for_occurrence[occurrence_id]] -= 1.0
                row[epsilon_index] += float(self.order)
                extra_inequalities.append(row)
                extra_inequality_rhs.append(0.0)

        if extra_inequalities:
            A_ub = np.vstack(
                (A_ub, np.asarray(extra_inequalities, dtype=float))
            )
            b_ub = np.concatenate(
                (b_ub, np.asarray(extra_inequality_rhs, dtype=float))
            )
        if extra_equalities:
            A_eq = np.vstack(
                (A_eq, np.asarray(extra_equalities, dtype=float))
            )
            b_eq = np.concatenate(
                (b_eq, np.asarray(extra_equality_rhs, dtype=float))
            )

        objective = np.zeros(width, dtype=float)
        objective[epsilon_index] = -1.0
        alternatives = self.outer_arc_equalities or ((),)
        solutions: list[Sequence[float]] = []
        feasible_margins: list[float] = []
        unknown_alternative = False
        unresolved_variables = {
            variable_for_occurrence[occurrence_id]
            for occurrence_id in fundamental_set - set(flattened)
        }
        for alternative in alternatives:
            branch_A_eq, branch_b_eq = self._with_coordinate_equalities(
                A_eq,
                b_eq,
                coordinates,
                alternative,
                width,
            )
            if self.outer_arc_equalities:
                self.event_sink("joint_outer_arc_pair_checks", 1)
            self.event_sink("joint_weak_length_prefix_lp_calls", 1)
            result = linprog(
                objective,
                A_ub=A_ub,
                b_ub=b_ub,
                A_eq=branch_A_eq,
                b_eq=branch_b_eq,
                bounds=bounds,
                method="highs",
            )
            margin = (
                float(result.x[epsilon_index])
                if result.success and result.x is not None
                else 0.0
            )
            if margin <= self.tolerance:
                # HiGHS remains a fast witness finder, never a rejection
                # oracle.  Only an exact rational non-positive optimum closes
                # this arc-pair branch.
                exact = self._exact_margin(
                    A_ub,
                    b_ub,
                    branch_A_eq,
                    branch_b_eq,
                    width,
                )
                if exact.verdict == "unknown":
                    unknown_alternative = True
                    if self.outer_arc_equalities:
                        self.event_sink("joint_outer_arc_pair_unknown", 1)
                    # The alternatives form an existential disjunction.  One
                    # unknown branch already prevents exact rejection of the
                    # prefix, so solving the remaining alternatives cannot
                    # strengthen the sound verdict.  Fall back immediately.
                    self.event_sink(
                        "joint_outer_arc_pair_search_short_circuits", 1
                    )
                    break
                if exact.verdict == "infeasible":
                    if self.outer_arc_equalities:
                        self.event_sink("joint_outer_arc_pair_infeasible", 1)
                    continue
                assert exact.margin is not None
                margin = float(exact.margin)
                solutions.append(
                    tuple(float(value) for value in exact.solution)
                )
            else:
                solutions.append(result.x)
            feasible_margins.append(margin)
            self.event_sink("joint_weak_length_prefix_feasible", 1)
            if self.outer_arc_equalities:
                self.event_sink("joint_outer_arc_pair_feasible", 1)

            if include_witnesses and len(flattened) < len(fundamental):
                minimum_margin = max(
                    self.tolerance * 100.0,
                    margin * self.minimum_margin_fraction,
                )
                margin_row = np.zeros(width, dtype=float)
                margin_row[epsilon_index] = -1.0
                witness_A_ub = np.vstack((A_ub, margin_row))
                witness_b_ub = np.concatenate(
                    (b_ub, np.asarray([-minimum_margin], dtype=float))
                )
                for _attempt in range(self.witness_attempts):
                    random_objective = np.zeros(width, dtype=float)
                    for variable_index in unresolved_variables:
                        random_objective[variable_index] = self.rng.uniform(
                            -1.0, 1.0
                        )
                    random_objective[epsilon_index] = -1e-6
                    self.event_sink("joint_weak_length_witness_lp_calls", 1)
                    witness = linprog(
                        random_objective,
                        A_ub=witness_A_ub,
                        b_ub=witness_b_ub,
                        A_eq=branch_A_eq,
                        b_eq=branch_b_eq,
                        bounds=bounds,
                        method="highs",
                    )
                    if witness.success and witness.x is not None:
                        solutions.append(witness.x)

            # One feasible member proves the existential arc-pair
            # disjunction.  Its witnesses are sufficient as heuristic
            # proposals; uniform actions retain full support for descendants
            # associated with the other feasible pairs.
            if self.outer_arc_equalities:
                self.event_sink(
                    "joint_outer_arc_pair_search_short_circuits", 1
                )
            break

        if not feasible_margins:
            if unknown_alternative:
                # Fail open.  No LP witness is available to guide ranking, but
                # the conventional stochastic child domain remains intact.
                self.event_sink("joint_weak_length_prefix_unknown", 1)
                return JointPrefixExtension(margin=0.0, next_masks=())
            self.event_sink("joint_weak_length_prefix_infeasible", 1)
            return None
        margin = max(feasible_margins)

        masks: list[int] = []
        seen_masks: set[int] = set()
        for solution in solutions:
            mask = self._next_mask_from_solution(
                split_index,
                normalized_blocks,
                fundamental,
                variable_for_occurrence,
                solution,
            )
            if mask is None or mask in seen_masks:
                continue
            seen_masks.add(mask)
            masks.append(mask)
        if masks:
            self.event_sink("joint_weak_length_witness_masks", len(masks))
        return JointPrefixExtension(margin=margin, next_masks=tuple(masks))

    def _next_mask_from_solution(
        self,
        split_index: int,
        fundamental_blocks: Sequence[Sequence[int]],
        fundamental: Sequence[int],
        variable_for_occurrence: Mapping[int, int],
        solution: Sequence[float],
    ) -> int | None:
        """Translate the next coordinate level of an LP witness to a mask."""

        split = self.splits[split_index]
        resolved_counts = [0 for _ in self.assignment.sequences]
        resolved: set[int] = set()
        for block in fundamental_blocks:
            pieces_in_block: set[int] = set()
            for occurrence_id in block:
                piece_index, position, _size = self._sequence_positions[
                    int(occurrence_id)
                ]
                if (
                    piece_index in pieces_in_block
                    or position != resolved_counts[piece_index]
                    or position >= int(split[piece_index])
                ):
                    return None
                pieces_in_block.add(piece_index)
                resolved_counts[piece_index] += 1
                resolved.add(int(occurrence_id))

        expected: list[tuple[float, int]] = []
        fundamental_set = set(int(value) for value in fundamental)
        for piece_index, sequence in enumerate(self.assignment.sequences):
            position = resolved_counts[piece_index]
            if position >= int(split[piece_index]):
                continue
            occurrence_id = int(sequence[position])
            if occurrence_id not in fundamental_set or occurrence_id in resolved:
                return None
            expected.append(
                (
                    float(solution[variable_for_occurrence[occurrence_id]]),
                    piece_index,
                )
            )
        if not expected:
            return None
        minimum = min(value for value, _piece_index in expected)
        tie_tolerance = max(1e-10, self.tolerance * 10.0)
        mask = 0
        for value, piece_index in expected:
            if abs(value - minimum) <= tie_tolerance:
                mask |= 1 << piece_index
        return mask or None

    def prefix_margin(
        self,
        split_index: int,
        fundamental_blocks: Sequence[Sequence[int]],
    ) -> float | None:
        """Compatibility helper for feasibility-only callers and tests."""

        extension = self.prefix_extension(
            split_index, fundamental_blocks, include_witnesses=False
        )
        return None if extension is None else extension.margin
