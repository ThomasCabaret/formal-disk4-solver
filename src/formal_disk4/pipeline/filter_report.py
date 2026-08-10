from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Sequence, Tuple


FILTER_REPORT_SCHEMA_VERSION = "formal-filter-report-v2"


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

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "FilterObservation":
        raw_reasons = payload.get("rejection_reasons", {})
        reasons = (
            tuple(
                sorted(
                    (str(name), int(value))
                    for name, value in raw_reasons.items()
                )
            )
            if isinstance(raw_reasons, Mapping)
            else ()
        )
        return cls(
            filter_id=str(payload["filter_id"]),
            block=str(payload["block"]),
            label=str(payload["label"]),
            entered=int(payload.get("entered", 0)),
            passed=int(payload.get("passed", 0)),
            rejected=int(payload.get("rejected", 0)),
            deferred=int(payload.get("deferred", 0)),
            errors=int(payload.get("errors", 0)),
            unaccounted=int(payload.get("unaccounted", 0)),
            rejection_reasons=reasons,
        )


# This order is part of the public API.  A learning client can therefore use the
# report as a fixed target vector without depending on internal counter names.
FILTER_SPECS: Tuple[FilterSpec, ...] = (
    FilterSpec(
        "assignment.canonical",
        "assignment",
        "Contour assignment is canonical under intrinsic map symmetries",
        ("assignment_quotient_checks",),
        ("symmetry_pruned_assignments",),
    ),
    FilterSpec(
        "weak.exterior_arc_repetition",
        "weak_order",
        "Repeated exterior circular arcs can still coincide",
        (
            "exterior_arc_repetition_assignment_checks",
            "exterior_arc_repetition_checks",
        ),
        (
            "exterior_arc_repetition_pruned_assignments",
            "exterior_arc_repetition_pruned_nodes",
        ),
    ),
    FilterSpec(
        "weak.symmetry_prefix_canonical",
        "weak_order",
        "Weak-order prefix is canonical under the assignment stabilizer",
        ("symmetry_prefix_checks",),
        ("symmetry_pruned_nodes",),
    ),
    FilterSpec(
        "weak.prefix_topology.hard_outer_endpoint",
        "weak_order",
        "Prefix propagation does not cross a hard outer endpoint",
        (
            "prefix_topology_checks",
            "prefix_topology_cache_hits",
        ),
        ("prefix_topology_hard_outer_endpoint_rejections",),
        error_counters=("prefix_topology_errors",),
        passed_counters=("prefix_topology_hard_outer_endpoint_passes",),
    ),
    FilterSpec(
        "weak.prefix_topology.opposite_circular_sign",
        "weak_order",
        "Prefix propagation does not force opposite circular signs to overlap",
        (
            "prefix_topology_checks",
            "prefix_topology_cache_hits",
        ),
        ("prefix_topology_opposite_circular_sign_rejections",),
        error_counters=("prefix_topology_errors",),
        passed_counters=("prefix_topology_opposite_circular_sign_passes",),
    ),
    FilterSpec(
        "weak.positive_length",
        "weak_order",
        "Resolved positive-length equations are feasible",
        ("length_checks",),
        ("length_pruned_nodes",),
    ),
    FilterSpec(
        "weak.point_angle",
        "weak_order",
        "Resolved point-angle equations are feasible",
        ("angle_checks",),
        ("angle_pruned_nodes",),
    ),
    FilterSpec(
        "weak.leaf_canonical",
        "weak_order",
        "Complete weak order is canonical under intrinsic symmetries",
        ("symmetry_leaf_checks",),
        ("symmetry_pruned_leaves",),
    ),
    FilterSpec(
        "weak.complete_length",
        "weak_order",
        "Complete positive-length system is feasible",
        ("complete_length_checks",),
        ("complete_length_rejections",),
    ),
    FilterSpec(
        "weak.complete_angle",
        "weak_order",
        "Complete point-angle system is feasible",
        ("complete_angle_checks",),
        ("complete_angle_rejections",),
    ),
    FilterSpec(
        "weak.complete_topology.hard_outer_endpoint",
        "weak_order",
        "Complete propagation does not cross a hard outer endpoint",
        (
            "complete_topology_checks",
            "complete_topology_cache_hits",
        ),
        ("complete_topology_hard_outer_endpoint_rejections",),
        error_counters=("complete_topology_errors",),
        passed_counters=("complete_topology_hard_outer_endpoint_passes",),
    ),
    FilterSpec(
        "preword.topology.hard_outer_endpoint",
        "preword",
        "Pre-word propagation does not cross a hard outer endpoint",
        ("preword_topology_checks",),
        ("preword_topology_hard_outer_endpoint_rejections",),
        error_counters=("preword_topology_errors",),
        passed_counters=("preword_topology_hard_outer_endpoint_passes",),
    ),
    FilterSpec(
        "preword.topology.opposite_circular_sign",
        "preword",
        "Pre-word propagation does not force opposite circular signs to overlap",
        ("preword_topology_checks",),
        ("preword_topology_opposite_circular_sign_rejections",),
        error_counters=("preword_topology_errors",),
        passed_counters=("preword_topology_opposite_circular_sign_passes",),
    ),
    FilterSpec(
        "preword.metric.positive_lengths",
        "preword",
        "Pre-word variables admit strictly positive lengths",
        ("preword_curriculum_positive_lengths_checks",),
        ("preword_curriculum_positive_lengths_rejections",),
    ),
    FilterSpec(
        "preword.metric.local_radius_transport",
        "preword",
        "Local radius transport identities are feasible",
        ("preword_curriculum_radius_local_checks",),
        ("preword_curriculum_radius_local_rejections",),
    ),
    FilterSpec(
        "preword.metric.local_smooth_turn",
        "preword",
        "Local smooth-turn transport identities are feasible",
        ("preword_curriculum_smooth_turn_local_checks",),
        ("preword_curriculum_smooth_turn_local_rejections",),
    ),
    FilterSpec(
        "preword.metric.point_turn",
        "preword",
        "Point-turn equations are feasible",
        ("preword_curriculum_point_turns_checks",),
        ("preword_curriculum_point_turns_rejections",),
    ),
    FilterSpec(
        "preword.metric.global_radius_balance",
        "preword",
        "Global signed-radius balance is feasible",
        ("preword_curriculum_radius_global_checks",),
        ("preword_curriculum_radius_global_rejections",),
    ),
    FilterSpec(
        "preword.metric.global_turn_balance",
        "preword",
        "Global smooth-turn balance is feasible",
        ("preword_curriculum_smooth_turn_global_checks",),
        ("preword_curriculum_smooth_turn_global_rejections",),
    ),
    FilterSpec(
        "preword.metric.strict_concavity",
        "preword",
        "Strict radius-R concavity constraints are feasible",
        ("preword_curriculum_radius_concavity_checks",),
        ("preword_curriculum_radius_concavity_rejections",),
    ),
    FilterSpec(
        "preword.metric.isoperimetric",
        "preword",
        "The isoperimetric necessary bound is feasible",
        ("preword_curriculum_isoperimetric_checks",),
        ("preword_curriculum_isoperimetric_rejections",),
    ),
    FilterSpec(
        "word.exact_contradiction",
        "formal_word",
        "Exact word solving does not prove a contradiction",
        ("word_exact_contradiction_checks",),
        ("word_solver_status_exact_unsat",),
        error_counters=("solver_errors",),
        passed_counters=("word_exact_contradiction_passes",),
    ),
    FilterSpec(
        "word.unsupported_cycle",
        "formal_word",
        "Residual cycles remain in the supported exact family language",
        ("word_unsupported_cycle_checks",),
        ("unsupported_language_word_cases",),
        passed_counters=("word_unsupported_cycle_passes",),
    ),
    FilterSpec(
        "word.resource_limit",
        "formal_word",
        "Exact word solving terminates without a resource limit",
        ("word_resource_limit_checks",),
        ("deferred_word_cases",),
        passed_counters=("word_resource_limit_passes",),
    ),
    FilterSpec(
        "word.family_emitted",
        "formal_word",
        "At least one supported exact word family is emitted",
        ("word_family_emission_checks",),
        ("word_family_emission_rejections",),
        passed_counters=("word_cases_with_supported_family",),
    ),
    FilterSpec(
        "profile.emitted",
        "profile",
        "A word-family specialization emits a formal profile",
        ("profile_emission_checks",),
        ("profile_emission_rejections",),
        error_counters=("profile_emission_errors",),
        passed_counters=("profiles_emitted",),
    ),
)

LEARNING_FILTER_IDS: Tuple[str, ...] = tuple(
    spec.filter_id for spec in FILTER_SPECS
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

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "FilterReport":
        raw = payload.get("filters", ())
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise ValueError("filter report filters must be a sequence")
        observations = tuple(
            FilterObservation.from_dict(item)
            for item in raw
            if isinstance(item, Mapping)
        )
        by_id = {item.filter_id: item for item in observations}
        return cls(
            tuple(
                by_id.get(
                    spec.filter_id,
                    FilterObservation(
                        spec.filter_id,
                        spec.block,
                        spec.label,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                    ),
                )
                for spec in FILTER_SPECS
            )
        )

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
