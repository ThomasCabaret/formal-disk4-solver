from __future__ import annotations

from dataclasses import replace
from typing import Protocol, Tuple

from .model import FormalProfile


class ProfileFilter(Protocol):
    name: str

    def apply(self, profile: FormalProfile) -> Tuple[bool, str]: ...


class NonemptyContourFilter:
    """INTEGRITY FILTER: a geometric prototype must have boundary data."""

    name = "nonempty_contour"

    def apply(self, profile: FormalProfile) -> Tuple[bool, str]:
        return bool(profile.terminal_contour), "pass" if profile.terminal_contour else "empty"


class CyclicNoBacktrackingFilter:
    """HEURISTIC ONLY: reject an apparent immediate inverse traversal.

    Congruent curve variables need not denote the same geometric occurrence,
    so this is not a necessary condition and is disabled by default.
    """

    name = "cyclic_no_backtracking"

    def apply(self, profile: FormalProfile) -> Tuple[bool, str]:
        contour = profile.terminal_contour
        if len(contour) < 2:
            return True, "pass"
        for index, literal in enumerate(contour):
            following = contour[(index + 1) % len(contour)]
            if literal.variable == following.variable and literal.inverse != following.inverse:
                return False, f"immediate retracing at terminal segment {index}"
        return True, "pass"


class PositiveTerminalLengthFilter:
    """FILTER JUSTIFICATION (local): retained contour atoms are non-erasing.

    Therefore every terminal component must receive a strictly positive length
    from the already certified exact joint-linear witness.
    """

    name = "positive_terminal_curve_lengths"

    def apply(self, profile: FormalProfile) -> Tuple[bool, str]:
        analysis = profile.joint_angular_feasibility
        witness = analysis.witness_map()
        names = analysis.length_variables
        if not profile.curve_components or len(names) != len(profile.curve_components):
            return False, "missing terminal component length"
        if any(name not in witness or witness[name] <= 0 for name in names):
            return False, "missing or nonpositive exact terminal component length"
        return True, "pass:exact"


class SignedAngleClassFilter:
    """FILTER JUSTIFICATION (local): a Jordan-boundary angle lies in (0, 2pi)."""

    name = "signed_angle_classes"

    def apply(self, profile: FormalProfile) -> Tuple[bool, str]:
        if not profile.point_decorations:
            return False, "missing point decorations"
        analysis = profile.joint_angular_feasibility
        witness = analysis.witness_map()
        names = analysis.point_angle_variables
        if len(names) != len(profile.point_decorations):
            return False, "missing exact point angle"
        for name in names:
            value = witness.get(name)
            if value is None or not (0 < value < 2):
                return False, f"invalid exact prototype angle {name}"
        return True, "pass:exact"


class JointAngularFeasibilityFilter:
    """FILTER JUSTIFICATION (local): all point and turn identities are necessary.

    Strict feasibility is required because degenerate zero/full point angles do
    not describe the boundary of a Jordan region in the supported formal model.
    """

    name = "joint_point_curve_turn_feasibility"

    def apply(self, profile: FormalProfile) -> Tuple[bool, str]:
        analysis = profile.joint_angular_feasibility
        if not analysis.feasible:
            return False, analysis.status
        if analysis.strict_margin <= 0:
            return False, "exact joint angular system has no strict margin"
        kinds = {item.kind for item in analysis.equations}
        has_total = "prototype_total_turn" in kinds
        has_split = {
            "prototype_smooth_turn_balance",
            "prototype_point_turn_balance",
        }.issubset(kinds)
        if not has_total and not has_split:
            return False, "missing prototype winding equations"
        return True, f"pass:exact_margin={analysis.strict_margin}"


class MappingCoverageFilter:
    """INTEGRITY FILTER: each declared interface needs one nonempty map."""

    name = "mapping_coverage"

    def apply(self, profile: FormalProfile) -> Tuple[bool, str]:
        expected = profile.expected_internal_mapping_count
        if len(profile.contact_mappings) != expected:
            return False, (
                f"expected {expected} internal mappings, "
                f"got {len(profile.contact_mappings)}"
            )
        if any(not mapping.pairs for mapping in profile.contact_mappings):
            return False, "empty contact mapping"
        return True, "pass"


class CurveTemplateCompatibilityFilter:
    """FILTER JUSTIFICATION (local): a positive arc cannot be straight and circular."""

    name = "curve_template_compatibility"

    def apply(self, profile: FormalProfile) -> Tuple[bool, str]:
        if not profile.curve_components:
            return False, "missing curve-template components"
        for component in profile.curve_components:
            if component.forced_straight and component.circular:
                return False, f"{component.component_id} is both straight and circular"
        return True, "pass"


class OuterCircleDecorationFilter:
    """INTEGRITY FILTER: require the complete outer-circle formalization.

    This rejects incomplete decorated profiles, not candidates merely because a
    numerical geometry backend failed to construct them.
    """

    name = "outer_circle_decorations"

    def apply(self, profile: FormalProfile) -> Tuple[bool, str]:
        expected = profile.expected_outer_arc_count
        if len(profile.outer_arcs) != expected:
            return False, (
                f"expected {expected} outer circle arcs, "
                f"got {len(profile.outer_arcs)}"
            )
        if any(not item.terminal_word for item in profile.outer_arcs):
            return False, "empty outer circle arc"
        circular_components = {item.component_id for item in profile.curve_components if item.circular}
        if not circular_components:
            return False, "no terminal curve component marked as disk-circle arc"
        required_kinds = {
            "outer_circle_positivity",
            "outer_circle_total_turn",
            "outer_circle_total_length",
            "outer_arc_length_definition",
            "common_circle_length_turn_relation",
        }
        present = {str(item.get("kind")) for item in profile.formal_constraints}
        missing = sorted(required_kinds - present)
        if missing:
            return False, "missing circle constraints: " + ", ".join(missing)
        return True, "pass"


class DeferredSubsumptionFilter:
    """DEFERRED, NOT REJECTED: subsumption is a cross-profile quotient step."""

    name = "decorated_subsumption"

    def apply(self, profile: FormalProfile) -> Tuple[bool, str]:
        return True, "deferred:global cross-profile reduction runs outside the local filter chain"


class DeferredPolynomialGeometryFilter:
    """DEFERRED, NOT REJECTED: geometry is checked by the later backend."""

    name = "polynomial_geometry"

    def apply(self, profile: FormalProfile) -> Tuple[bool, str]:
        return True, "deferred:profile is ready for chord/closure/area/Z3/numerical geometry"


class ProfileFilterPipeline:
    def __init__(
        self,
        enable_subsumption_hook: bool = True,
        enable_geometry_hook: bool = True,
        enable_cyclic_no_backtracking_heuristic: bool = False,
    ) -> None:
        self.filters: list[ProfileFilter] = [
            NonemptyContourFilter(),
        ]
        # Equal curve variables denote congruent curve templates, not the same
        # geometric occurrence.  Therefore A followed cyclically by A^-1 does
        # not by itself prove geometric retracing (a pizza sector is the basic
        # counterexample).  Keep the old test only as an explicitly enabled,
        # non-mathematical debugging heuristic.
        if enable_cyclic_no_backtracking_heuristic:
            self.filters.append(CyclicNoBacktrackingFilter())
        self.filters.extend([
            PositiveTerminalLengthFilter(),
            SignedAngleClassFilter(),
            JointAngularFeasibilityFilter(),
            MappingCoverageFilter(),
            CurveTemplateCompatibilityFilter(),
            OuterCircleDecorationFilter(),
        ])
        if enable_subsumption_hook:
            self.filters.append(DeferredSubsumptionFilter())
        if enable_geometry_hook:
            self.filters.append(DeferredPolynomialGeometryFilter())

    def apply(self, profile: FormalProfile) -> Tuple[FormalProfile | None, Tuple[Tuple[str, str], ...]]:
        statuses = []
        for profile_filter in self.filters:
            accepted, status = profile_filter.apply(profile)
            statuses.append((profile_filter.name, status))
            if not accepted:
                return None, tuple(statuses)
        return replace(profile, filter_status=tuple(statuses)), tuple(statuses)
