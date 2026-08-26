from __future__ import annotations

import json
import random
import tempfile
import time
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping, Sequence

from formal_disk4.config import load_config
from formal_disk4.enumeration.assignments import AssignmentEnumerator, ContourAssignment
from formal_disk4.enumeration.cyclic_arrangements import CyclicArrangementEnumerator
from formal_disk4.pipeline.api import (
    AssignmentSelection,
    FormalSolverAPI,
    PlacementSelection,
    SolverAPIRequest,
)
from formal_disk4.pipeline.filter_report import LEARNING_FILTER_IDS, FilterReport
from formal_disk4.pipeline.runner import SolverRunner

from .mapping import MappingEvaluation, MappingProposal, sum_counters
from .feedback import formal_profile_ids
from .free_outer_boundary import (
    free_outer_boundary_descriptor,
    free_outer_boundary_model_candidate,
    relax_outer_boundary,
)
from .outer_crown import (
    OuterCrownError,
    extract_outer_crown,
    outer_crown_descriptor,
    outer_crown_model_candidate,
)
from .space import DynamicPlanarMap, DualGraphCandidate, build_dynamic_planar_map

if TYPE_CHECKING:
    from .specialization_model import (
        SpecializationLearningModel,
        SpecializationPoolObservation,
    )
    from .weak_model import WeakOrderLearningModel, WeakOrderRolloutObservation


GRAPH_STAGES = (
    "generated_graph",
    "assignment",
    "placement",
    "preword_pass",
    "word_family",
    "geometry_ready",
)


def _deep_merge(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = deepcopy(value)


def _positive_count_domain(
    value: str | Sequence[int] | None,
) -> tuple[int, ...] | None:
    if value is None:
        return None
    counts: set[int] = set()
    if isinstance(value, str):
        for raw_token in value.split(","):
            token = raw_token.strip()
            if not token:
                raise ValueError("Partial crown tile domain contains an empty item")
            if "-" in token:
                parts = token.split("-")
                if len(parts) != 2:
                    raise ValueError(f"Invalid partial crown range {token!r}")
                first, last = (int(part.strip()) for part in parts)
                if first > last:
                    raise ValueError(f"Descending partial crown range {token!r}")
                counts.update(range(first, last + 1))
            else:
                counts.add(int(token))
    else:
        counts.update(int(item) for item in value)
    if not counts or min(counts) < 1:
        raise ValueError("Partial crown tile counts must be positive")
    return tuple(sorted(counts))


@dataclass(frozen=True)
class GraphEvaluation:
    candidate: DualGraphCandidate
    stage_index: int
    elapsed_seconds: float
    stop_reason: str
    counters: Mapping[str, int]
    profiles: tuple[Mapping[str, object], ...]
    tainted: bool
    error: str | None = None
    evaluated_structure: Mapping[str, object] | None = None

    @property
    def stage_name(self) -> str:
        return GRAPH_STAGES[self.stage_index]

    @property
    def geometry_ready(self) -> bool:
        return bool(self.profiles)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "graph-lab-observation-v2",
            "candidate": self.candidate.to_dict(),
            "stage_index": self.stage_index,
            "stage_name": self.stage_name,
            "elapsed_seconds": self.elapsed_seconds,
            "stop_reason": self.stop_reason,
            "counters": dict(self.counters),
            "profile_count": len(self.profiles),
            "profile_ids": list(formal_profile_ids(self.profiles)),
            "geometry_ready": self.geometry_ready,
            "tainted": self.tainted,
            "error": self.error,
            "evaluated_structure": (
                dict(self.evaluated_structure)
                if self.evaluated_structure is not None
                else None
            ),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "GraphEvaluation":
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
        return cls(
            candidate=DualGraphCandidate.from_dict(payload["candidate"]),  # type: ignore[arg-type]
            stage_index=int(payload["stage_index"]),
            elapsed_seconds=float(payload.get("elapsed_seconds", 0.0)),
            stop_reason=str(payload.get("stop_reason", "restored")),
            counters={
                str(name): int(value)
                for name, value in dict(payload.get("counters", {})).items()  # type: ignore[arg-type]
            },
            profiles=tuple(restored_profiles),
            tainted=bool(payload.get("tainted", False)),
            error=str(payload["error"]) if payload.get("error") else None,
            evaluated_structure=(
                dict(payload["evaluated_structure"])  # type: ignore[arg-type]
                if isinstance(payload.get("evaluated_structure"), Mapping)
                else None
            ),
        )


class GraphFormalEvaluator:
    """Run one dynamic structural map through a bounded production search."""

    def __init__(
        self,
        root: Path,
        config: Mapping[str, object],
    ) -> None:
        self.root = root.resolve()
        base_path = Path(str(config.get("base_search_config", "config/cycle_campaign/search.json")))
        if not base_path.is_absolute():
            base_path = self.root / base_path
        self.base_config = load_config(base_path)
        self.overrides = dict(config.get("search_overrides", {}))
        self.mapping_overrides = dict(config.get("mapping_search_overrides", {}))
        arrangement_config = dict(config.get("joint_arrangement_search", {}))
        self.joint_arrangement_search_enabled = bool(
            arrangement_config.get("enabled", False)
        )
        self.joint_arrangement_max_nodes = max(
            1, int(arrangement_config.get("max_nodes", 100_000))
        )
        self.joint_arrangement_max_placements = max(
            1, int(arrangement_config.get("max_placements", 32))
        )
        self.joint_arrangement_time_limit_seconds = max(
            0.01, float(arrangement_config.get("time_limit_seconds", 30.0))
        )
        self.partial_crown_tile_counts = _positive_count_domain(
            config.get("partial_crown_tile_counts")  # type: ignore[arg-type]
        )
        self.outer_crown_only = bool(
            config.get("outer_crown_only", False)
            or self.partial_crown_tile_counts is not None
        )
        self.free_outer_boundary = bool(
            config.get("free_outer_boundary", False)
        )
        if self.outer_crown_only and self.free_outer_boundary:
            raise ValueError(
                "outer_crown_only and free_outer_boundary are mutually exclusive"
            )
        default_prototype_mode = "structural" if self.outer_crown_only else "none"
        self.prototype_symmetry_mode = str(
            config.get("prototype_symmetry_mode", default_prototype_mode)
        )
        if self.prototype_symmetry_mode not in {"none", "structural"}:
            raise ValueError(
                "prototype_symmetry_mode must be 'none' or 'structural'"
            )
        if not self.outer_crown_only and self.prototype_symmetry_mode != "none":
            raise ValueError(
                "Prototype symmetry control is currently defined only for crown regions"
            )

    def _partial_crown_size(
        self, candidate: DualGraphCandidate, dynamic: DynamicPlanarMap
    ) -> int | None:
        if self.partial_crown_tile_counts is None:
            return None
        available = sum(
            1 for piece in dynamic.planar_map.pieces if piece.touches_outer_boundary
        )
        eligible = tuple(
            count for count in self.partial_crown_tile_counts if count <= available
        )
        if not eligible:
            raise OuterCrownError(
                f"No requested partial crown size fits the {available}-tile crown"
            )
        return eligible[int(candidate.graph_id[-8:], 16) % len(eligible)]

    def _dynamic(self, candidate: DualGraphCandidate) -> DynamicPlanarMap:
        dynamic = build_dynamic_planar_map(candidate)
        if self.free_outer_boundary:
            return relax_outer_boundary(dynamic)
        if not self.outer_crown_only:
            return dynamic
        if candidate.stein_center_tile is None or candidate.symmetry_order < 2:
            raise OuterCrownError(
                "outer_crown_only requires a symmetric Stein source graph"
            )
        prototype_rotation_order = (
            candidate.symmetry_order
            if self.prototype_symmetry_mode == "structural"
            else 1
        )
        return extract_outer_crown(
            dynamic,
            prototype_rotation_order=prototype_rotation_order,
            retained_tile_count=self._partial_crown_size(candidate, dynamic),
            selection_key=candidate.graph_id,
        )

    def _structure_descriptor(
        self,
        candidate: DualGraphCandidate,
        dynamic: DynamicPlanarMap | None = None,
    ) -> Mapping[str, object] | None:
        if self.free_outer_boundary:
            resolved = dynamic if dynamic is not None else self._dynamic(candidate)
            return free_outer_boundary_descriptor(candidate, resolved)
        if not self.outer_crown_only:
            return None
        try:
            resolved = dynamic if dynamic is not None else self._dynamic(candidate)
            return outer_crown_descriptor(candidate, resolved)
        except OuterCrownError as error:
            return {
                "kind": "stein_crown_region_ineligible_v1",
                "source_tile_count": candidate.tile_count,
                "error": str(error),
            }

    def _configured_dynamic(
        self,
        candidate: DualGraphCandidate,
        directory: Path,
        *,
        mapping_rollout: bool = False,
    ) -> tuple[DynamicPlanarMap, dict[str, Any]]:
        dynamic = self._dynamic(candidate)
        config = deepcopy(self.base_config)
        _deep_merge(config, self.overrides)
        if mapping_rollout:
            _deep_merge(config, self.mapping_overrides)
        config["maps"] = [dynamic.planar_map.name]
        config["output"].update(
            {
                "directory": str(directory),
                "write_candidates": True,
                "write_families": False,
                "write_unsupported": False,
                "write_word_cases": False,
                "write_deferred_word_cases": False,
                "write_placements": False,
                "write_errors": True,
                "max_error_records": 100,
            }
        )
        config["checkpoint"].update(
            {"enabled": False, "resume": False, "restart": False}
        )
        config["progress"]["enabled"] = False
        config["enumeration"]["track_exact_domain_size"] = False
        pointwise_config = config["enumeration"].setdefault(
            "cyclic_equivariance", {}
        )
        cyclic_shift_config = config["enumeration"].setdefault(
            "cyclic_shift_equivariance", {}
        )
        dihedral_config = config["enumeration"].setdefault(
            "dihedral_equivariance", {}
        )
        pointwise_config["enabled"] = False
        cyclic_shift_config["enabled"] = False
        dihedral_config["enabled"] = False
        if dynamic.imposed_automorphism is None:
            pass
        elif dynamic.imposed_equivariance_mode == "pointwise":
            pointwise_config.update(
                {
                    "enabled": True,
                    "automorphism": dynamic.imposed_automorphism,
                    "enforce_weak_orders": True,
                }
            )
        elif dynamic.imposed_equivariance_mode == "cyclic_shift":
            cyclic_shift_config.update(
                {
                    "enabled": True,
                    "automorphism": dynamic.imposed_automorphism,
                }
            )
        else:
            raise ValueError("Unknown imposed Graph Lab equivariance mode")
        if dynamic.imposed_reflections:
            if dynamic.imposed_equivariance_mode != "cyclic_shift":
                raise ValueError(
                    "A theorem-forced Stein reflection needs cyclic rotation equivariance"
                )
            dihedral_config.update(
                {
                    "enabled": True,
                    "automorphisms": list(dynamic.imposed_reflections),
                }
            )
        return dynamic, config

    @staticmethod
    def _assignment_enumerator(
        dynamic: DynamicPlanarMap, config: Mapping[str, Any]
    ) -> AssignmentEnumerator:
        enumeration = config["enumeration"]
        pointwise = enumeration.get("cyclic_equivariance", {})
        return AssignmentEnumerator(
            dynamic.planar_map,
            allow_reflections=bool(enumeration["allow_reflections"]),
            symmetry_mode=str(enumeration["symmetry_mode"]),
            required_equivariance=(
                str(pointwise.get("automorphism", "rotation_1"))
                if pointwise.get("enabled", False)
                else None
            ),
            required_equivariance_on_weak_orders=bool(
                pointwise.get("enforce_weak_orders", True)
            ),
        )

    def mapping_pool(
        self,
        candidate: DualGraphCandidate,
        rng: random.Random,
        amount: int,
    ) -> tuple[MappingProposal, ...]:
        """Sample cheap complete mappings; quotient rejection remains a target.

        Cyclic-shift equivariance is an imposed search restriction, not a rare
        downstream event.  Sampling the unrestricted raw assignment space here
        would make almost every Stein mapping die before its first weak-order
        decision, leaving the ranker with no useful contrast.
        """

        with tempfile.TemporaryDirectory(prefix="formal-disk4-mapping-domain-") as raw:
            try:
                dynamic, config = self._configured_dynamic(candidate, Path(raw))
            except OuterCrownError:
                return ()
            enumerator = self._assignment_enumerator(dynamic, config)
            cyclic_automorphism = (
                dynamic.imposed_automorphism
                if dynamic.imposed_equivariance_mode == "cyclic_shift"
                else None
            )
            reflection_names = tuple(dynamic.imposed_reflections)
            if cyclic_automorphism is not None and reflection_names:
                strata = tuple(
                    (
                        reflection_name,
                        enumerator.cyclic_dihedral_compatible_assignment_count(
                            cyclic_automorphism, reflection_name
                        ),
                    )
                    for reflection_name in reflection_names
                )
                strata = tuple(item for item in strata if item[1] > 0)
                total = sum(count for _name, count in strata)
            else:
                strata = ()
                total = (
                    enumerator.cyclic_shift_compatible_assignment_count(
                        cyclic_automorphism
                    )
                    if cyclic_automorphism is not None
                    else enumerator.raw_assignment_count()
                )
            if total <= 0:
                return ()
            target = min(max(1, int(amount)), total)
            selected: dict[int, ContourAssignment] = {}
            attempts = 0
            maximum_attempts = max(256, target * 64)
            while len(selected) < target and attempts < maximum_attempts:
                attempts += 1
                assignment_index = rng.randrange(total)
                if strata:
                    offset = assignment_index
                    for reflection_name, stratum_count in strata:
                        if offset < stratum_count:
                            assignment = (
                                enumerator.cyclic_dihedral_compatible_assignment_at(
                                    cyclic_automorphism,
                                    reflection_name,
                                    offset,
                                )
                            )
                            break
                        offset -= stratum_count
                    else:  # pragma: no cover - guarded by the total above
                        raise RuntimeError("Invalid dihedral mapping stratum")
                elif cyclic_automorphism is not None:
                    assignment = enumerator.cyclic_shift_compatible_assignment_at(
                        cyclic_automorphism, assignment_index
                    )
                else:
                    assignment = enumerator.assignment_at(assignment_index)
                selected.setdefault(assignment.assignment_id, assignment)
            if self.outer_crown_only:
                model_candidate = outer_crown_model_candidate(candidate, dynamic)
            elif self.free_outer_boundary:
                model_candidate = free_outer_boundary_model_candidate(
                    candidate, dynamic
                )
            else:
                model_candidate = candidate
            projected_structure = self.outer_crown_only or self.free_outer_boundary
            return tuple(
                MappingProposal.from_assignment(
                    model_candidate,
                    assignment,
                    dynamic.planar_map,
                    source_candidate=(candidate if projected_structure else None),
                )
                for _assignment_id, assignment in sorted(selected.items())
            )

    def evaluate_mapping(
        self,
        proposal: MappingProposal,
        *,
        rollouts: int,
        random_seed: int,
        weak_model: WeakOrderLearningModel | None = None,
        weak_sampling: Mapping[str, object] | None = None,
        rollout_sink: Callable[[WeakOrderRolloutObservation], None] | None = None,
        specialization_model: SpecializationLearningModel | None = None,
        specialization_sampling: Mapping[str, object] | None = None,
        specialization_sink: Callable[[SpecializationPoolObservation], None]
        | None = None,
    ) -> MappingEvaluation:
        """Run bounded stochastic weak-order descendants of one fixed mapping."""

        started = time.perf_counter()
        counter_values: list[Mapping[str, int]] = []
        clean_rollout_reports: list[FilterReport] = []
        profiles: list[Mapping[str, object]] = []
        reasons: list[str] = []
        tainted = False
        weak_config = dict(weak_sampling or {})
        rollout_total = max(1, int(rollouts))
        exploration_rollouts = min(
            rollout_total,
            max(
                1,
                int(
                    round(
                        rollout_total
                        * float(weak_config.get("exploration_fraction", 0.25))
                    )
                ),
            ),
        )
        joint_fraction = min(
            0.95,
            max(0.0, float(weak_config.get("joint_length_fraction", 0.0))),
        )
        joint_rollout_count = min(
            max(0, rollout_total - 1),
            int(round(rollout_total * joint_fraction)),
        )
        if (
            not self.outer_crown_only
            and not self.free_outer_boundary
            and
            proposal.candidate.stein_center_tile is not None
            and proposal.candidate.imposed_permutation is not None
        ):
            # The Stein theorem supplies the outer-arc disjunction used by the
            # joint oracle.  Prefer that direct construction while retaining
            # one ordinary stochastic rollout as an independent full-support
            # safety/control route.
            joint_rollout_count = max(
                joint_rollout_count, max(0, rollout_total - 1)
            )
        joint_rollouts = set(
            range(rollout_total - joint_rollout_count, rollout_total)
        )
        try:
            for rollout in range(rollout_total):
                rollout_started = time.perf_counter()
                rollout_seed = int(random_seed) + rollout * 104729
                use_joint_length = rollout in joint_rollouts
                selection_mode = (
                    "joint_length"
                    if use_joint_length
                    else (
                        "exploration"
                        if rollout < exploration_rollouts
                        else "learned"
                    )
                )
                if weak_model is not None:
                    from .weak_model import WeakOrderRankedPolicy

                branch_policy = (
                    WeakOrderRankedPolicy(
                        proposal,
                        weak_model,
                        weak_config,
                        random_seed=rollout_seed,
                        selection_mode=selection_mode,
                    )
                    if weak_model is not None
                    else None
                )
                specialization_policy = None
                if specialization_model is not None:
                    from .specialization_model import SpecializationRankedPolicy

                    specialization_policy = SpecializationRankedPolicy(
                        proposal,
                        specialization_model,
                        dict(specialization_sampling or {}),
                        random_seed=rollout_seed + 7919,
                    )
                with tempfile.TemporaryDirectory(
                    prefix="formal-disk4-mapping-rollout-"
                ) as raw:
                    directory = Path(raw)
                    dynamic, config = self._configured_dynamic(
                        proposal.evaluation_source,
                        directory,
                        mapping_rollout=True,
                    )
                    joint_config = config["enumeration"].setdefault(
                        "joint_weak_length", {}
                    )
                    joint_config.update(
                        {
                            "enabled": bool(
                                use_joint_length
                                and dynamic.imposed_equivariance_mode
                                == "cyclic_shift"
                            ),
                            "random_seed": rollout_seed + 15_485_863,
                            "witness_attempts": max(
                                0,
                                int(
                                    weak_config.get(
                                        "joint_length_witness_attempts", 6
                                    )
                                ),
                            ),
                            "minimum_margin_fraction": min(
                                1.0,
                                max(
                                    0.0,
                                    float(
                                        weak_config.get(
                                            "joint_length_minimum_margin_fraction",
                                            0.10,
                                        )
                                    ),
                                ),
                            ),
                            "exact_max_tableau_cells": max(
                                1,
                                int(
                                    weak_config.get(
                                        "joint_length_exact_max_tableau_cells",
                                        50_000,
                                    )
                                ),
                            ),
                            "exact_max_pivots": max(
                                0,
                                int(
                                    weak_config.get(
                                        "joint_length_exact_max_pivots", 512
                                    )
                                ),
                            ),
                            "exact_max_coefficient_bits": max(
                                1,
                                int(
                                    weak_config.get(
                                        "joint_length_exact_max_coefficient_bits",
                                        2_048,
                                    )
                                ),
                            ),
                            "exact_time_limit_seconds": max(
                                0.0,
                                float(
                                    weak_config.get(
                                        "joint_length_exact_time_limit_seconds",
                                        0.10,
                                    )
                                ),
                            ),
                        }
                    )
                    with (directory / "solver.log").open(
                        "w", encoding="utf-8"
                    ) as diagnostic_stream:
                        with redirect_stdout(diagnostic_stream), redirect_stderr(
                            diagnostic_stream
                        ):
                            result = FormalSolverAPI.evaluate(
                                SolverAPIRequest(
                                    config=config,
                                    planar_maps=(dynamic.planar_map,),
                                    assignments=(
                                        AssignmentSelection(
                                            dynamic.planar_map.name,
                                            (proposal.raw_assignment_id,),
                                        ),
                                    ),
                                    weak_order_random_seed=(
                                        rollout_seed if branch_policy is None else None
                                    ),
                                    weak_order_branch_policy=branch_policy,
                                    family_specialization_policy=specialization_policy,
                                    collect_learning_diagnostics=True,
                                    collect_profiles=True,
                                )
                            )
                    if not bool(result.summary.get("tainted", False)):
                        clean_rollout_reports.append(result.filters)
                    statistics = dict(result.summary.get("statistics", {}))
                    counters = {
                        str(name): int(value)
                        for name, value in dict(
                            statistics.get("counters", {})
                        ).items()
                    }
                    counter_values.append(counters)
                    reasons.append(str(statistics.get("stop_reason", "unknown")))
                    tainted |= bool(result.summary.get("tainted", False))
                    rollout_profiles = list(result.profiles)
                    profiles.extend(rollout_profiles)
                    if specialization_policy is not None and specialization_sink is not None:
                        for pool_observation in specialization_policy.observations:
                            specialization_sink(pool_observation)
                    if branch_policy is not None and rollout_sink is not None:
                        from .weak_model import WeakOrderRolloutObservation

                        actual_modes = {
                            decision.selection_mode
                            for decision in branch_policy.decisions
                        }
                        actual_mode = (
                            next(iter(actual_modes))
                            if len(actual_modes) == 1
                            else (
                                "mixed"
                                if actual_modes
                                else (
                                    "joint_length"
                                    if use_joint_length
                                    else "uncontrolled"
                                )
                            )
                        )
                        rollout_sink(
                            WeakOrderRolloutObservation(
                                proposal=proposal,
                                decisions=tuple(branch_policy.decisions),
                                filters=result.filters,
                                elapsed_seconds=time.perf_counter()
                                - rollout_started,
                                profile_count=len(rollout_profiles),
                                profile_ids=formal_profile_ids(rollout_profiles),
                                selection_mode=actual_mode,
                                random_seed=rollout_seed,
                                tainted=bool(result.summary.get("tainted", False)),
                            )
                        )
            counters = sum_counters(counter_values)
            reach_vector = tuple(
                sum(
                    1.0 if report.observations[index].entered else 0.0
                    for report in clean_rollout_reports
                )
                / len(clean_rollout_reports)
                for index in range(len(LEARNING_FILTER_IDS))
            ) if clean_rollout_reports else tuple(None for _ in LEARNING_FILTER_IDS)
            return MappingEvaluation(
                proposal=proposal,
                filters=FilterReport.from_counters(counters),
                counters=counters,
                rollout_count=rollout_total,
                elapsed_seconds=time.perf_counter() - started,
                profiles=tuple(profiles),
                tainted=tainted,
                stop_reasons=tuple(reasons),
                reach_vector=reach_vector,
            )
        except Exception as error:
            counters = sum_counters(counter_values)
            reach_vector = tuple(
                sum(
                    1.0 if report.observations[index].entered else 0.0
                    for report in clean_rollout_reports
                )
                / len(clean_rollout_reports)
                for index in range(len(LEARNING_FILTER_IDS))
            ) if clean_rollout_reports else tuple(None for _ in LEARNING_FILTER_IDS)
            return MappingEvaluation(
                proposal=proposal,
                filters=FilterReport.from_counters(counters),
                counters=counters,
                rollout_count=len(counter_values),
                elapsed_seconds=time.perf_counter() - started,
                profiles=tuple(profiles),
                tainted=True,
                stop_reasons=tuple(reasons),
                reach_vector=reach_vector,
                error=f"{type(error).__name__}: {error}",
            )

    def aggregate_mappings(
        self,
        candidate: DualGraphCandidate,
        mappings: list[MappingEvaluation],
    ) -> GraphEvaluation:
        counters = sum_counters([item.counters for item in mappings])
        profiles = tuple(
            profile for item in mappings for profile in item.profiles
        )
        return GraphEvaluation(
            candidate=candidate,
            stage_index=self._stage(counters),
            elapsed_seconds=sum(item.elapsed_seconds for item in mappings),
            stop_reason="mapping_rollouts",
            counters=counters,
            profiles=profiles,
            tainted=any(item.tainted for item in mappings),
            error="; ".join(item.error for item in mappings if item.error) or None,
            evaluated_structure=self._structure_descriptor(candidate),
        )

    def evaluate_joint_arrangements(
        self, candidate: DualGraphCandidate
    ) -> GraphEvaluation:
        """Search mapping and weak order together for one fixed graph.

        This path deliberately bypasses every mapping/weak-order ranker.  It
        constructs a complete cyclic arrangement by backtracking, then hands
        the resulting placements to the same pre-word, word, decoration, and
        profile kernel as ordinary searches.
        """

        started = time.perf_counter()
        counters: dict[str, int] = {}
        try:
            with tempfile.TemporaryDirectory(
                prefix="formal-disk4-joint-arrangement-"
            ) as raw:
                directory = Path(raw)
                dynamic, config = self._configured_dynamic(
                    candidate, directory, mapping_rollout=True
                )
                assignments = AssignmentEnumerator(
                    dynamic.planar_map,
                    allow_reflections=bool(
                        config["enumeration"]["allow_reflections"]
                    ),
                    symmetry_mode="off",
                )
                if dynamic.imposed_automorphism is None:
                    pointwise = None
                    rotation = None
                    reflections = ()
                elif dynamic.imposed_equivariance_mode == "pointwise":
                    pointwise = assignments.transform_for_automorphism(
                        dynamic.imposed_automorphism
                    )
                    rotation = None
                    reflections = ()
                elif dynamic.imposed_equivariance_mode == "cyclic_shift":
                    pointwise = None
                    rotation = assignments.transform_for_automorphism(
                        dynamic.imposed_automorphism
                    )
                    reflections = tuple(
                        assignments.transform_for_automorphism(name)
                        for name in dynamic.imposed_reflections
                    )
                else:
                    raise ValueError(
                        "Unknown imposed Graph Lab equivariance mode"
                    )

                deadline = started + self.joint_arrangement_time_limit_seconds

                def stop() -> bool:
                    return time.perf_counter() >= deadline

                def count(name: str, amount: int = 1) -> None:
                    counters[name] = counters.get(name, 0) + int(amount)

                search = CyclicArrangementEnumerator(
                    dynamic.planar_map,
                    allow_reflections=bool(
                        config["enumeration"]["allow_reflections"]
                    ),
                    required_pointwise_transform=pointwise,
                    required_cyclic_shift_transform=rotation,
                    required_reflection_transforms=reflections,
                    event_sink=count,
                    stop_predicate=stop,
                    max_nodes=self.joint_arrangement_max_nodes,
                )
                placements = []
                for placement in search.enumerate():
                    placements.append(placement)
                    if len(placements) >= self.joint_arrangement_max_placements:
                        break

                counters.setdefault("assignments_processed", 1)
                counters["joint_arrangement_placements"] = len(placements)
                if not placements:
                    reason = (
                        "joint_arrangement_time_limit"
                        if stop()
                        else "joint_arrangement_exhausted_or_node_limit"
                    )
                    return GraphEvaluation(
                        candidate=candidate,
                        stage_index=self._stage(counters),
                        elapsed_seconds=time.perf_counter() - started,
                        stop_reason=reason,
                        counters=counters,
                        profiles=(),
                        tainted=False,
                        evaluated_structure=self._structure_descriptor(
                            candidate, dynamic
                        ),
                    )

                # The arrangement has already enforced every mapping and weak
                # symmetry.  Disable the historical enumeration layer for the
                # hand-off; it must not quotient or expand the supplied leaves.
                enumeration = config["enumeration"]
                enumeration["symmetry_mode"] = "off"
                enumeration["track_exact_domain_size"] = False
                enumeration.setdefault("cyclic_equivariance", {})[
                    "enabled"
                ] = False
                enumeration.setdefault("cyclic_shift_equivariance", {})[
                    "enabled"
                ] = False
                enumeration.setdefault("dihedral_equivariance", {})[
                    "enabled"
                ] = False
                config["limits"]["max_assignments"] = len(
                    {item.assignment.assignment_id for item in placements}
                )
                config["limits"]["max_placements"] = len(placements)
                result = FormalSolverAPI.evaluate(
                    SolverAPIRequest(
                        config=config,
                        planar_maps=(dynamic.planar_map,),
                        placements=(
                            PlacementSelection(
                                dynamic.planar_map.name, tuple(placements)
                            ),
                        ),
                        collect_learning_diagnostics=False,
                        collect_profiles=True,
                    )
                )
                kernel_counters = {
                    str(name): int(value)
                    for name, value in dict(
                        dict(result.summary.get("statistics", {})).get(
                            "counters", {}
                        )
                    ).items()
                }
                for name, amount in kernel_counters.items():
                    counters[name] = counters.get(name, 0) + amount
                return GraphEvaluation(
                    candidate=candidate,
                    stage_index=self._stage(counters),
                    elapsed_seconds=time.perf_counter() - started,
                    stop_reason=str(
                        dict(result.summary.get("statistics", {})).get(
                            "stop_reason", "joint_arrangement_kernel"
                        )
                    ),
                    counters=counters,
                    profiles=tuple(result.profiles),
                    tainted=bool(result.summary.get("tainted", False)),
                    evaluated_structure=self._structure_descriptor(
                        candidate, dynamic
                    ),
                )
        except Exception as error:
            return GraphEvaluation(
                candidate=candidate,
                stage_index=self._stage(counters),
                elapsed_seconds=time.perf_counter() - started,
                stop_reason="joint_arrangement_error",
                counters=counters,
                profiles=(),
                tainted=True,
                error=f"{type(error).__name__}: {error}",
                evaluated_structure=self._structure_descriptor(candidate),
            )
    @staticmethod
    def _stage(counters: Mapping[str, int]) -> int:
        stage = 0
        if int(counters.get("assignments_processed", 0)) > 0:
            stage = 1
        if int(counters.get("surviving_placements", 0)) > 0:
            stage = 2
        if int(counters.get("solver_cases", 0)) > 0:
            stage = 3
        if int(counters.get("word_families", 0)) > 0:
            stage = 4
        if int(counters.get("profiles_emitted", 0)) > 0:
            stage = 5
        return stage

    def evaluate(self, candidate: DualGraphCandidate) -> GraphEvaluation:
        started = time.perf_counter()
        try:
            with tempfile.TemporaryDirectory(prefix="formal-disk4-graph-lab-") as raw:
                directory = Path(raw)
                dynamic, config = self._configured_dynamic(candidate, directory)
                # Production diagnostics can contain thousands of deferred word
                # cases. Keep the long-running Graph Lab console focused on one
                # compact line per graph and explicit GEOMETRY READY events.
                with (directory / "solver.log").open(
                    "w", encoding="utf-8"
                ) as diagnostic_stream:
                    with redirect_stdout(diagnostic_stream), redirect_stderr(
                        diagnostic_stream
                    ):
                        summary = SolverRunner(
                            config, planar_maps=(dynamic.planar_map,)
                        ).run()
                statistics = dict(summary.get("statistics", {}))
                counters = {
                    str(name): int(value)
                    for name, value in dict(statistics.get("counters", {})).items()
                }
                profiles = []
                candidate_path = directory / str(config["output"]["candidates_file"])
                if candidate_path.exists():
                    with candidate_path.open("r", encoding="utf-8") as stream:
                        for line in stream:
                            if line.strip():
                                value = json.loads(line)
                                if isinstance(value, dict):
                                    profiles.append(value)
                return GraphEvaluation(
                    candidate=candidate,
                    stage_index=self._stage(counters),
                    elapsed_seconds=time.perf_counter() - started,
                    stop_reason=str(statistics.get("stop_reason", "unknown")),
                    counters=counters,
                    profiles=tuple(profiles),
                    tainted=bool(summary.get("tainted", False)),
                    evaluated_structure=self._structure_descriptor(
                        candidate, dynamic
                    ),
                )
        except Exception as error:
            return GraphEvaluation(
                candidate=candidate,
                stage_index=0,
                elapsed_seconds=time.perf_counter() - started,
                stop_reason="evaluation_error",
                counters={},
                profiles=(),
                tainted=True,
                error=f"{type(error).__name__}: {error}",
                evaluated_structure=(
                    {
                        "kind": "stein_crown_region_ineligible_v1",
                        "source_tile_count": candidate.tile_count,
                        "error": str(error),
                    }
                    if self.outer_crown_only
                    else None
                ),
            )
