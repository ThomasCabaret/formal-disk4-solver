from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Sequence, Tuple


FILTER_REPORT_SCHEMA_VERSION = "formal-filter-report-v1"


@dataclass(frozen=True)
class FilterSpec:
    """Stable public description of one decision gate in the formal pipeline."""

    filter_id: str
    block: str
    label: str
    entered_counters: Tuple[str, ...]
    rejected_counters: Tuple[str, ...] = ()
    deferred_counters: Tuple[str, ...] = ()
    error_counters: Tuple[str, ...] = ()
    reason_prefixes: Tuple[str, ...] = ()
    passed_counters: Tuple[str, ...] = ()


@dataclass(frozen=True)
class FilterObservation:
    filter_id: str
    block: str
    label: str
    entered: int
    passed: int
    rejected: int
    deferred: int
    errors: int
    unaccounted: int
    rejection_reasons: Tuple[Tuple[str, int], ...] = ()

    @property
    def decided(self) -> int:
        return self.passed + self.rejected

    @property
    def conditional_pass_rate(self) -> float | None:
        return self.passed / self.decided if self.decided else None

    def to_dict(self) -> Dict[str, object]:
        return {
            "filter_id": self.filter_id,
            "block": self.block,
            "label": self.label,
            "entered": self.entered,
            "passed": self.passed,
            "rejected": self.rejected,
            "deferred": self.deferred,
            "errors": self.errors,
            "unaccounted": self.unaccounted,
            "conditional_pass_rate": self.conditional_pass_rate,
            "rejection_reasons": dict(self.rejection_reasons),
        }


# This order is part of the public API.  A learning client can therefore use the
# report as a fixed target vector without depending on internal counter names.
FILTER_SPECS: Tuple[FilterSpec, ...] = (
    FilterSpec(
        "assignment.intrinsic_symmetry_quotient",
        "assignment",
        "Contour assignment is canonical under intrinsic map symmetries",
        ("assignment_quotient_checks",),
        ("symmetry_pruned_assignments",),
    ),
    FilterSpec(
        "weak.mapping_subdomain_prefix",
        "weak_order",
        "Weak-order prefix remains inside the requested search shard",
        ("mapping_subdomain_prefix_checks",),
        ("mapping_subdomain_pruned_nodes",),
    ),
    FilterSpec(
        "weak.mapping_subdomain_leaf",
        "weak_order",
        "Complete weak order remains inside the requested search shard",
        ("mapping_subdomain_leaf_checks",),
        ("mapping_subdomain_pruned_leaves",),
    ),
    FilterSpec(
        "weak.exterior_arc_repetition_assignment",
        "weak_order",
        "Assignment admits a possible repeated exterior arc",
        ("exterior_arc_repetition_assignment_checks",),
        ("exterior_arc_repetition_pruned_assignments",),
    ),
    FilterSpec(
        "weak.exterior_arc_repetition_prefix",
        "weak_order",
        "Weak-order prefix can still identify the required exterior arcs",
        ("exterior_arc_repetition_checks",),
        ("exterior_arc_repetition_pruned_nodes",),
    ),
    FilterSpec(
        "weak.intrinsic_symmetry_prefix",
        "weak_order",
        "Weak-order prefix is canonical under the assignment stabilizer",
        ("symmetry_prefix_checks",),
        ("symmetry_pruned_nodes",),
    ),
    FilterSpec(
        "weak.intrinsic_symmetry_leaf",
        "weak_order",
        "Complete weak order is canonical under intrinsic symmetries",
        ("symmetry_leaf_checks",),
        ("symmetry_pruned_leaves",),
    ),
    FilterSpec(
        "weak.prefix_topology",
        "weak_order",
        "Resolved radius-arc topology is feasible at this prefix",
        ("prefix_topology_checks", "prefix_topology_cache_hits", "prefix_topology_errors"),
        ("prefix_topology_pruned_nodes",),
        error_counters=("prefix_topology_errors",),
        reason_prefixes=("prefix_topology_rejection_",),
    ),
    FilterSpec(
        "weak.length_system",
        "weak_order",
        "Resolved positive-length equations are feasible",
        ("length_checks",),
        ("length_pruned_nodes",),
    ),
    FilterSpec(
        "weak.angle_system",
        "weak_order",
        "Resolved point-angle equations are feasible",
        ("angle_checks",),
        ("angle_pruned_nodes",),
    ),
    FilterSpec(
        "weak.complete_topology",
        "weak_order",
        "Complete radius-arc topology is feasible",
        ("complete_topology_checks", "complete_topology_cache_hits", "complete_topology_errors"),
        ("complete_topology_pruned_placements",),
        error_counters=("complete_topology_errors",),
        reason_prefixes=("complete_topology_rejection_",),
    ),
    FilterSpec(
        "word.compile",
        "formal_word",
        "Formal word system compiles successfully",
        ("word_compilation_checks",),
        error_counters=("compile_errors",),
    ),
    FilterSpec(
        "preword.topology",
        "preword",
        "Pre-word radius-arc topology is feasible",
        ("preword_topology_checks",),
        ("preword_topology_rejections",),
        error_counters=("preword_topology_errors",),
        reason_prefixes=("preword_topology_rejection_",),
    ),
    FilterSpec(
        "preword.metric",
        "preword",
        "Pre-word metric/radius/turn system is feasible",
        ("preword_metric_checks",),
        ("preword_metric_rejections",),
        error_counters=("preword_metric_errors",),
        reason_prefixes=("preword_metric_rejection_",),
    ),
    FilterSpec(
        "preword.point_angle",
        "preword",
        "Pre-word point-angle system is feasible",
        ("preword_point_angle_checks",),
        ("preword_point_angle_rejections",),
        error_counters=("preword_point_angle_errors",),
        reason_prefixes=("preword_point_angle_rejection_",),
    ),
    FilterSpec(
        "word.exact_solver",
        "formal_word",
        "Exact partial-word solver reaches a supported terminal status",
        ("solver_cases",),
        ("word_solver_status_exact_unsat",),
        (
            "word_solver_status_interrupted_external_stop",
            "word_solver_status_unresolved_residual_literal_limit",
            "word_solver_status_unresolved_family_limit",
            "word_solver_status_unresolved_graph_limit",
            "word_solver_status_restricted_terminal_contour_limit",
            "word_solver_status_exact_unsupported_family_language",
            "word_solver_status_not_run",
        ),
        ("solver_errors",),
        passed_counters=("word_solver_status_exact_supported",),
    ),
)


def _counter_sum(counters: Mapping[str, int], names: Sequence[str]) -> int:
    return sum(max(0, int(counters.get(name, 0))) for name in names)


def _reason_counts(
    counters: Mapping[str, int], prefixes: Sequence[str]
) -> Tuple[Tuple[str, int], ...]:
    values: dict[str, int] = {}
    for name, raw_count in counters.items():
        # Witness counters refine a reason but are not mutually exclusive
        # outcomes, so including them would double-count rejection labels.
        if "_witness_" in name:
            continue
        prefix = next((item for item in prefixes if name.startswith(item)), None)
        if prefix is None:
            continue
        reason = name[len(prefix) :] or "unspecified"
        count = max(0, int(raw_count))
        if count:
            values[reason] = values.get(reason, 0) + count
    return tuple(sorted(values.items()))


@dataclass(frozen=True)
class FilterReport:
    observations: Tuple[FilterObservation, ...]

    @classmethod
    def from_counters(cls, counters: Mapping[str, int]) -> "FilterReport":
        observations = []
        for spec in FILTER_SPECS:
            entered = _counter_sum(counters, spec.entered_counters)
            rejected = _counter_sum(counters, spec.rejected_counters)
            deferred = _counter_sum(counters, spec.deferred_counters)
            errors = _counter_sum(counters, spec.error_counters)
            # Every entered gate has one terminal outcome.  Errors are
            # conservative passes in production but remain a distinct label so
            # learning never treats an implementation failure as evidence.
            passed = (
                _counter_sum(counters, spec.passed_counters)
                if spec.passed_counters
                else max(0, entered - rejected - deferred - errors)
            )
            unaccounted = max(
                0, entered - passed - rejected - deferred - errors
            )
            observations.append(
                FilterObservation(
                    filter_id=spec.filter_id,
                    block=spec.block,
                    label=spec.label,
                    entered=entered,
                    passed=passed,
                    rejected=rejected,
                    deferred=deferred,
                    errors=errors,
                    unaccounted=unaccounted,
                    rejection_reasons=_reason_counts(counters, spec.reason_prefixes),
                )
            )
        return cls(tuple(observations))

    def by_id(self, filter_id: str) -> FilterObservation:
        return next(item for item in self.observations if item.filter_id == filter_id)

    def target_vector(self) -> Tuple[float | None, ...]:
        """Conditional pass probability in stable pipeline order."""

        return tuple(item.conditional_pass_rate for item in self.observations)

    def to_dict(self) -> Dict[str, object]:
        return {
            "schema_version": FILTER_REPORT_SCHEMA_VERSION,
            "semantics": (
                "entered counts candidates that reached a gate; pass rates are "
                "conditional on decided outcomes and exclude deferred/error cases"
            ),
            "target_order": [item.filter_id for item in self.observations],
            "target_vector": list(self.target_vector()),
            "filters": [item.to_dict() for item in self.observations],
        }


@dataclass(frozen=True)
class AssignmentFilterEvaluation:
    """Filter labels attributable to one raw contour assignment."""

    map_name: str
    raw_assignment_id: int
    canonical_assignment_id: int | None
    complete: bool
    stop_reason: str
    counters: Tuple[Tuple[str, int], ...]
    filters: FilterReport

    def to_dict(self) -> Dict[str, object]:
        return {
            "map_name": self.map_name,
            "raw_assignment_id": self.raw_assignment_id,
            "canonical_assignment_id": self.canonical_assignment_id,
            "complete": self.complete,
            "stop_reason": self.stop_reason,
            "counters": dict(self.counters),
            "filter_report": self.filters.to_dict(),
        }
