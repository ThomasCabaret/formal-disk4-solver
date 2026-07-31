from __future__ import annotations

import json
import sys
from copy import deepcopy
from dataclasses import dataclass
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

from formal_disk4.config import save_config
from formal_disk4.constraints.angle_lp import AngleFeasibilityOracle
from formal_disk4.constraints.length_lp import LengthFeasibilityOracle
from formal_disk4.enumeration.assignments import AssignmentEnumerator, ContourAssignment
from formal_disk4.enumeration.weak_orders import (
    WeakOrderEnumerator,
    count_weak_orders_for_lengths,
)
from formal_disk4.maps.base import PlanarMap
from formal_disk4.maps.registry import iterate_maps
from formal_disk4.profiles.build import build_formal_profile
from formal_disk4.profiles.canonical import conservative_profile_key
from formal_disk4.profiles.decorations import DecorationInfeasible
from formal_disk4.profiles.filters import ProfileFilterPipeline
from formal_disk4.preword import (
    PrewordLinearInvariantFilter,
    PrewordPruningPipeline,
    RadiusArcTopologyFilter,
)
from formal_disk4.words.compile import compile_word_case
from formal_disk4.words.exact_partial import ExactPartialWordSolver, SolverLimits
from formal_disk4.words.families import FamilyExpansionPolicy, expand_family

from .checkpoint import CheckpointStore, search_fingerprint
from .output import JsonlWriter, NullJsonlWriter, atomic_write_json
from .stats import RunStats


@dataclass(frozen=True)
class MapContext:
    planar_map: PlanarMap
    assignment_enumerator: AssignmentEnumerator
    assignment_count: int
    mass_per_assignment: int

    def assignment_at(self, assignment_id: int) -> ContourAssignment | None:
        return self.assignment_enumerator.canonical_assignment_at(assignment_id)


class SolverRunner:
    def __init__(self, config: Mapping[str, Any]) -> None:
        self.config = dict(config)
        self.stats = RunStats()
        self._last_progress = self.stats.started_at
        self._stop_requested = False
        self._seen_profile_keys: set[str] = set()
        self._current_weak_orders: WeakOrderEnumerator | None = None
        self._current_map_name = "pending"
        self._search_state: Dict[str, Any] = {
            "version": 1,
            "map_index": 0,
            "assignment_id": 0,
            "map_started": False,
            "assignment_started": False,
            "completed_leaf_mass": 0,
            "weak_order": {},
        }
        self._total_leaf_mass = 0
        self._total_assignment_count = 0
        self._resumed = False
        self._checkpoint_completed = False
        self._safe_stats_payload: Dict[str, object] = self.stats.checkpoint_payload()
        self._safe_search_state: Dict[str, Any] = deepcopy(self._search_state)

        output_config = self.config["output"]
        self.output_directory = Path(output_config["directory"]).resolve()
        self.output_directory.mkdir(parents=True, exist_ok=True)
        save_config(self.config, self.output_directory / "effective_config.json")

        checkpoint_config = self.config.get("checkpoint", {})
        checkpoint_path = self.output_directory / str(
            checkpoint_config.get("file", "checkpoint.sqlite3")
        )
        self.checkpoint_store = CheckpointStore(
            checkpoint_path,
            fingerprint=search_fingerprint(self.config),
            interval_seconds=float(checkpoint_config.get("interval_seconds", 60.0)),
            enabled=bool(checkpoint_config.get("enabled", True)),
            resume=bool(checkpoint_config.get("resume", True)),
            restart=bool(checkpoint_config.get("restart", False)),
        )
        loaded = self.checkpoint_store.load()
        self._resumed = loaded.resumed
        self._checkpoint_completed = loaded.completed
        if loaded.resumed:
            self._search_state.update(loaded.state)
            self._safe_search_state = deepcopy(self._search_state)
            stats_payload = loaded.stats
            self.stats.restore(
                stats_payload.get("counters", {}),
                stats_payload.get("timings", {}),
                float(stats_payload.get("elapsed_seconds", 0.0)),
            )
            self._safe_stats_payload = self.stats.checkpoint_payload()
            print(
                "[RESUME] Loaded checkpoint "
                f"from {checkpoint_path} (updated {loaded.updated_utc}).",
                file=sys.stderr,
                flush=True,
            )

        tolerance = float(self.config["enumeration"]["lp_tolerance"])
        self.length_oracle = LengthFeasibilityOracle(tolerance=tolerance)
        self.angle_oracle = AngleFeasibilityOracle(tolerance=tolerance)
        preword_config = self.config["filters"].get("preword_pruning", {})
        topology_config = preword_config.get("topology", {})
        linear_config = preword_config.get("linear_invariants", {})
        self.preword_pruning = PrewordPruningPipeline(
            topology_filter=RadiusArcTopologyFilter(
                tolerance=tolerance,
                enable_endpoint_crossing=bool(
                    topology_config.get("enable_endpoint_crossing", True)
                ),
                max_intervals=int(topology_config.get("max_intervals", 1024)),
            ),
            linear_filter=PrewordLinearInvariantFilter(
                tolerance=tolerance,
                enable_radius_measures=bool(
                    linear_config.get("enable_radius_measures", True)
                ),
                enable_smooth_turns=bool(
                    linear_config.get("enable_smooth_turns", True)
                ),
                enable_point_turns=bool(
                    linear_config.get("enable_point_turns", True)
                ),
                enforce_global_point_turn_balance=bool(
                    linear_config.get("enforce_global_point_turn_balance", True)
                ),
                enable_isoperimetric=bool(
                    linear_config.get("enable_isoperimetric", True)
                ),
                sqrt_upper_bound_denominator=int(
                    linear_config.get("sqrt_upper_bound_denominator", 1000)
                ),
            ),
            enable_topology=bool(topology_config.get("enabled", True)),
            enable_linear_invariants=bool(linear_config.get("enabled", True)),
        )
        self.filter_pipeline = ProfileFilterPipeline(
            enable_subsumption_hook=bool(
                self.config["filters"]["enable_subsumption_hook"]
            ),
            enable_geometry_hook=bool(self.config["filters"]["enable_geometry_hook"]),
            enable_cyclic_no_backtracking_heuristic=bool(
                self.config["filters"].get(
                    "enable_cyclic_no_backtracking_heuristic", False
                )
            ),
        )

    def _event(self, name: str, amount: int = 1) -> None:
        self.stats.increment(name, amount)
        self._maybe_progress()

    def _limit_reached(self, counter_name: str, config_name: str) -> bool:
        value = self.config["limits"].get(config_name)
        return value is not None and self.stats.get(counter_name) >= int(value)

    def _should_stop(self) -> bool:
        if self._stop_requested:
            return True
        limits = self.config["limits"]
        time_limit = limits.get("time_limit_seconds")
        if time_limit is not None and self.stats.session_elapsed_seconds >= float(time_limit):
            self.stats.stop_reason = "time_limit_seconds"
            self._stop_requested = True
        elif self._limit_reached("placement_nodes", "max_nodes"):
            self.stats.stop_reason = "max_nodes"
            self._stop_requested = True
        elif self._limit_reached("profiles_emitted", "max_profiles"):
            self.stats.stop_reason = "max_profiles"
            self._stop_requested = True
        return self._stop_requested

    def _current_processed_leaf_mass(self) -> int:
        completed = int(self._search_state.get("completed_leaf_mass", 0))
        if self._current_weak_orders is not None:
            return completed + self._current_weak_orders.processed_leaf_mass
        weak_state = self._search_state.get("weak_order", {})
        if isinstance(weak_state, Mapping):
            return completed + int(weak_state.get("processed_leaf_mass", 0))
        return completed

    def _progress_percentage(self) -> float:
        if self._total_leaf_mass <= 0:
            return 100.0 if self._checkpoint_completed else 0.0
        return min(100.0, 100.0 * self._current_processed_leaf_mass() / self._total_leaf_mass)

    def _current_assignment_progress(self) -> Tuple[int, int, float]:
        weak_state = (
            self._current_weak_orders.checkpoint_state()
            if self._current_weak_orders is not None
            else self._search_state.get("weak_order", {})
        )
        processed = (
            int(weak_state.get("processed_leaf_mass", 0))
            if isinstance(weak_state, Mapping)
            else 0
        )
        total = (
            self._current_weak_orders.total_leaf_mass
            if self._current_weak_orders is not None
            else 0
        )
        if total <= 0 and self._total_assignment_count > 0:
            total = self._total_leaf_mass // self._total_assignment_count
        percent = min(100.0, 100.0 * processed / total) if total else 0.0
        return processed, total, percent

    def _maybe_progress(self, force: bool = False) -> None:
        progress = self.config["progress"]
        if not progress.get("enabled", True):
            return
        now = time.perf_counter()
        interval = float(progress.get("interval_seconds", 5.0))
        if not force and now - self._last_progress < interval:
            return
        self._last_progress = now
        elapsed = self.stats.elapsed_seconds
        nodes = self.stats.get("placement_nodes")
        rate = nodes / elapsed if elapsed else 0.0
        percent = self._progress_percentage()
        _assignment_mass, _assignment_total, assignment_percent = self._current_assignment_progress()
        exact_progress = bool(
            self.config["enumeration"].get("track_exact_domain_size", True)
        )
        overall_text = f"{percent:5.1f}%" if exact_progress else "  n/a "
        assignment_text = (
            f"{assignment_percent:5.1f}%" if exact_progress else "  n/a "
        )
        assignment_position = int(self._search_state.get("assignment_id", 0)) + 1
        rejected_profiles = (
            self.stats.get("decoration_rejections")
            + self.stats.get("profile_filter_rejections")
        )
        message = (
            f"[{elapsed:9.2f}s] map={self._current_map_name} "
            f"overall~{overall_text} "
            f"assignment={assignment_position}/{max(1, self._total_assignment_count)} "
            f"current~{assignment_text} "
            f"nodes={nodes} ({rate:,.0f}/s) "
            f"length_pruned={self.stats.get('length_pruned_nodes')} "
            f"angle_pruned={self.stats.get('angle_pruned_nodes')} "
            f"outer_arc_pruned={self.stats.get('exterior_arc_repetition_pruned_nodes')} "
            f"placements={self.stats.get('surviving_placements')} "
            f"preword_pruned={self.stats.get('preword_rejections')} "
            f"word_systems={self.stats.get('solver_cases')} "
            f"families={self.stats.get('word_families')}"
            f"[finite={self.stats.get('word_family_finite')},"
            f"power={self.stats.get('word_family_power')},"
            f"nested={self.stats.get('word_family_nested_power')}] "
            f"specializations={self.stats.get('family_specializations')} "
            f"unexpanded={self.stats.get('families_not_specialized')} "
            f"joint_angle_rejections={self.stats.get('decoration_rejection_joint_angular_feasibility')} "
            f"profile_rejections={rejected_profiles} "
            f"profiles={self.stats.get('profiles_emitted')}"
        )
        print(message, file=sys.stderr, flush=True)

    def _checkpoint_state_payload(self) -> Dict[str, Any]:
        state = dict(self._search_state)
        if self._current_weak_orders is not None:
            state["weak_order"] = self._current_weak_orders.checkpoint_state()
        return state

    def _save_checkpoint(self, *, force: bool = False, completed: bool = False) -> None:
        saved = self.checkpoint_store.save(
            self._safe_search_state,
            self._safe_stats_payload,
            completed=completed,
            force=force,
        )
        if saved:
            print(
                f"[CHECKPOINT] Saved at progress~{self._progress_percentage():.1f}% "
                f"to {self.checkpoint_store.path}",
                file=sys.stderr,
                flush=True,
            )

    def _weak_checkpoint(self, weak_state: Mapping[str, object]) -> None:
        self._search_state["weak_order"] = dict(weak_state)
        self._safe_search_state = deepcopy(self._search_state)
        self._safe_stats_payload = self.stats.checkpoint_payload()
        self._save_checkpoint(force=False, completed=False)

    def _mark_top_level_safe(self) -> None:
        self._safe_search_state = deepcopy(self._search_state)
        self._safe_stats_payload = self.stats.checkpoint_payload()

    def _build_map_contexts(self) -> Tuple[MapContext, ...]:
        contexts = []
        total_mass = 0
        total_assignments = 0
        enumeration_config = self.config["enumeration"]
        track_exact_domain_size = bool(
            enumeration_config.get("track_exact_domain_size", True)
        )
        symmetry_mode = str(enumeration_config["symmetry_mode"])
        equivariance_config = enumeration_config.get("cyclic_equivariance", {})
        equivariance_enabled = bool(equivariance_config.get("enabled", False))
        enforce_equivariant_weak_orders = bool(
            equivariance_config.get("enforce_weak_orders", True)
        )
        required_equivariance = (
            str(equivariance_config.get("automorphism", "rotation_1"))
            if equivariance_enabled
            else None
        )
        for planar_map in iterate_maps(tuple(self.config["maps"])):
            assignment_enumerator = AssignmentEnumerator(
                planar_map,
                allow_reflections=bool(enumeration_config["allow_reflections"]),
                symmetry_mode=symmetry_mode,
                required_equivariance=required_equivariance,
                required_equivariance_on_weak_orders=(
                    enforce_equivariant_weak_orders
                ),
            )
            if symmetry_mode != "off":
                self.stats.increment(
                    "intrinsic_symmetry_group_elements",
                    len(assignment_enumerator.mapping_symmetry.group),
                )
                self.stats.increment(
                    "admissible_symmetry_group_elements",
                    len(assignment_enumerator.mapping_symmetry.quotient_group),
                )
                self.stats.increment(
                    "effective_mapping_symmetry_actions",
                    len(assignment_enumerator.mapping_symmetry.mapping_actions),
                )

            # Always keep the assignment domain lazy. Checkpoints store the raw
            # mixed-radix slot; non-canonical slots are rejected by inexpensive
            # integer permutations without materializing the canonical domain.
            assignment_count = assignment_enumerator.raw_assignment_count()
            first_assignment = (
                assignment_enumerator.assignment_at(0)
                if assignment_count
                else None
            )

            if first_assignment is not None and track_exact_domain_size:
                if (
                    required_equivariance is not None
                    and bool(equivariance_config.get("enforce_weak_orders", True))
                ):
                    orbits = assignment_enumerator.equivariance_piece_orbits
                    lengths = tuple(
                        len(first_assignment.sequences[orbit[0]]) for orbit in orbits
                    )
                    reference_piece_index = first_assignment.piece_names.index(
                        planar_map.reference_piece
                    )
                    reference_index = next(
                        index
                        for index, orbit in enumerate(orbits)
                        if reference_piece_index in orbit
                    )
                else:
                    lengths = tuple(
                        len(sequence) for sequence in first_assignment.sequences
                    )
                    reference_index = first_assignment.piece_names.index(
                        planar_map.reference_piece
                    )
                mass_per_assignment = count_weak_orders_for_lengths(
                    lengths, reference_index
                )
            else:
                mass_per_assignment = 0
            contexts.append(
                MapContext(
                    planar_map=planar_map,
                    assignment_enumerator=assignment_enumerator,
                    assignment_count=assignment_count,
                    mass_per_assignment=mass_per_assignment,
                )
            )
            total_mass += assignment_count * mass_per_assignment
            total_assignments += assignment_count
        self._total_leaf_mass = total_mass
        self._total_assignment_count = total_assignments
        return tuple(contexts)

    @staticmethod
    def _make_writer(
        enabled: bool,
        path: Path,
        flush_every: int,
        max_records: int | None,
        append: bool,
    ) -> JsonlWriter | NullJsonlWriter:
        if not enabled:
            return NullJsonlWriter()
        return JsonlWriter(
            path,
            flush_every,
            append=append,
            max_records=max_records,
        )

    def _record_unexpected_error(
        self,
        writer: JsonlWriter | NullJsonlWriter,
        *,
        stage: str,
        error: Exception,
        context: Mapping[str, Any],
    ) -> None:
        """Record a non-blocking implementation error and taint the campaign."""
        self.stats.increment("unexpected_errors")
        self.stats.increment(f"unexpected_error_{stage}")
        writer.write(
            {
                "stage": stage,
                **dict(context),
                "error_type": type(error).__name__,
                "error": repr(error),
                "traceback": traceback.format_exc(),
            }
        )

    def _unexpected_errors_by_stage(self) -> Dict[str, int]:
        prefix = "unexpected_error_"
        return {
            name[len(prefix) :]: int(value)
            for name, value in sorted(self.stats.counters.items())
            if name.startswith(prefix) and name != "unexpected_errors" and int(value) > 0
        }

    def _report_tainted_campaign(self, error_path: Path) -> None:
        count = self.stats.get("unexpected_errors")
        if count <= 0:
            return
        stages = ", ".join(
            f"{stage}={amount}"
            for stage, amount in self._unexpected_errors_by_stage().items()
        )
        destination = (
            str(error_path)
            if bool(self.config["output"].get("write_errors", True))
            else "error logging disabled; see run_summary.json"
        )
        print(
            f"[TAINTED] Campaign continued after {count} unexpected "
            f"implementation error(s) ({stages}). Details: {destination}",
            file=sys.stderr,
            flush=True,
        )

    def run(self) -> Dict[str, object]:
        output_config = self.config["output"]
        candidate_path = self.output_directory / output_config["candidates_file"]
        family_path = self.output_directory / output_config["families_file"]
        unsupported_path = self.output_directory / output_config["unsupported_file"]
        word_case_audit_path = self.output_directory / output_config["word_cases_file"]
        placement_path = self.output_directory / output_config["placements_file"]
        error_path = self.output_directory / "errors.jsonl"
        flush_every = int(output_config.get("flush_every", 1))

        contexts = self._build_map_contexts()
        if self.stats.get("raw_assignments_in_domain") == 0:
            self.stats.increment(
                "raw_assignments_in_domain",
                sum(
                    context.assignment_enumerator.raw_assignment_count()
                    for context in contexts
                ),
            )
            unrestricted = sum(
                context.assignment_enumerator.unrestricted_raw_assignment_count()
                for context in contexts
            )
            self.stats.increment(
                "unrestricted_raw_assignments_in_domain", unrestricted
            )
            if unrestricted != self.stats.get("raw_assignments_in_domain"):
                self.stats.increment(
                    "cyclic_equivariance_assignment_reduction",
                    unrestricted - self.stats.get("raw_assignments_in_domain"),
                )
        self.stats.counters["assignment_slots_in_domain"] = self._total_assignment_count
        self.stats.counters.pop("canonical_assignments_in_domain", None)
        if bool(self.config["enumeration"].get("track_exact_domain_size", True)):
            self.stats.counters["estimated_raw_weak_orders_in_domain"] = self._total_leaf_mass
        else:
            self.stats.counters.pop("estimated_raw_weak_orders_in_domain", None)
            self.stats.counters["exact_weak_order_domain_count_disabled"] = 1

        if self._checkpoint_completed:
            survivor_count = self.checkpoint_store.export_survivors_jsonl(candidate_path)
            self.stats.stop_reason = "already_completed"
            print(
                f"[COMPLETE] Search checkpoint is already complete. "
                f"Exported {survivor_count} survivor(s) to {candidate_path}. "
                "Use --restart to start again.",
                file=sys.stderr,
                flush=True,
            )
            summary = self._final_summary(
                candidate_path, family_path, unsupported_path,
                word_case_audit_path, placement_path, error_path
            )
            atomic_write_json(self.output_directory / "run_summary.json", summary)
            self._report_tainted_campaign(error_path)
            self.checkpoint_store.close()
            return summary

        if not self._resumed:
            # A new search owns these output files. Disabled high-volume streams are
            # removed so stale files from an older configuration cannot be mistaken
            # for current output.
            for enabled_key, path in (
                ("write_families", family_path),
                ("write_unsupported", unsupported_path),
                ("write_word_cases", word_case_audit_path),
                ("write_placements", placement_path),
                ("write_errors", error_path),
            ):
                if not bool(output_config.get(enabled_key, False)) and path.exists():
                    path.unlink()

        # When adopting an output directory created before SQLite checkpoints,
        # preserve any existing survivors unless the user explicitly requested
        # --restart. SQLite then becomes authoritative.
        if (
            not self._resumed
            and not bool(self.config.get("checkpoint", {}).get("restart", False))
            and bool(output_config.get("write_candidates", True))
        ):
            imported = self.checkpoint_store.import_survivors_jsonl(candidate_path)
            if imported:
                print(
                    f"[CHECKPOINT] Imported {imported} existing survivor(s) into SQLite.",
                    file=sys.stderr,
                    flush=True,
                )

        # SQLite is authoritative for survivors. Rebuild JSONL before appending so
        # an interruption between database commit and JSONL write cannot lose data.
        if bool(output_config.get("write_candidates", True)):
            self.checkpoint_store.export_survivors_jsonl(candidate_path)
        candidate_writer = self._make_writer(
            bool(output_config.get("write_candidates", True)),
            candidate_path,
            1,
            None,
            append=self._resumed or self.checkpoint_store.enabled,
        )
        family_writer = self._make_writer(
            bool(output_config.get("write_families", False)),
            family_path,
            flush_every,
            output_config.get("max_family_records"),
            append=self._resumed,
        )
        unsupported_writer = self._make_writer(
            bool(output_config.get("write_unsupported", False)),
            unsupported_path,
            flush_every,
            output_config.get("max_unsupported_records"),
            append=self._resumed,
        )
        word_case_audit_writer = self._make_writer(
            bool(output_config.get("write_word_cases", False)),
            word_case_audit_path,
            flush_every,
            output_config.get("max_word_case_records"),
            append=self._resumed,
        )
        placement_writer = self._make_writer(
            bool(output_config.get("write_placements", False)),
            placement_path,
            flush_every,
            output_config.get("max_placement_records"),
            append=self._resumed,
        )
        error_writer = self._make_writer(
            bool(output_config.get("write_errors", True)),
            error_path,
            1,
            output_config.get("max_error_records", 1000),
            append=self._resumed,
        )

        solver_config = self.config["solver"]
        if str(solver_config.get("mode", "exact_partial")) != "exact_partial":
            raise ValueError("Only solver.mode=exact_partial is supported in version 0.3")
        expansion_config = solver_config["family_expansion"]
        expansion_policy = FamilyExpansionPolicy(
            kind=str(expansion_config["policy"]),
            maximum_exponent=int(expansion_config.get("maximum_exponent", 1)),
            max_specializations=(
                None
                if expansion_config.get("max_specializations_per_family") is None
                else int(expansion_config["max_specializations_per_family"])
            ),
        )
        solver_limits = SolverLimits(
            max_graph_nodes=(
                None
                if solver_config.get("max_graph_nodes_per_placement") is None
                else int(solver_config["max_graph_nodes_per_placement"])
            ),
            max_graph_edges=(
                None
                if solver_config.get("max_graph_edges_per_placement") is None
                else int(solver_config["max_graph_edges_per_placement"])
            ),
            max_families=(
                None
                if solver_config.get("max_families_per_placement") is None
                else int(solver_config["max_families_per_placement"])
            ),
            max_expression_nodes=(
                None
                if solver_config.get("max_expression_nodes") is None
                else int(solver_config["max_expression_nodes"])
            ),
            validation_exponent=int(solver_config.get("validation_exponent", 2)),
        )
        tolerance = float(self.config["enumeration"]["lp_tolerance"])
        exhausted = True

        try:
            start_map_index = int(self._search_state.get("map_index", 0))
            for map_index in range(start_map_index, len(contexts)):
                context = contexts[map_index]
                planar_map = context.planar_map
                assignment_enumerator = context.assignment_enumerator
                mass_per_assignment = context.mass_per_assignment
                self._current_map_name = planar_map.name
                self._search_state["map_index"] = map_index
                if not bool(self._search_state.get("map_started", False)):
                    self.stats.increment("maps_processed")
                    self._search_state["map_started"] = True

                start_assignment_id = int(self._search_state.get("assignment_id", 0))
                for assignment_id in range(
                    start_assignment_id, context.assignment_count
                ):
                    self._search_state["assignment_id"] = assignment_id
                    if self._should_stop():
                        exhausted = False
                        break
                    assignment = context.assignment_at(assignment_id)
                    if assignment is None:
                        self.stats.increment("symmetry_pruned_assignments")
                        self._search_state["completed_leaf_mass"] = int(
                            self._search_state.get("completed_leaf_mass", 0)
                        ) + mass_per_assignment
                        self._search_state["assignment_id"] = assignment_id + 1
                        self._search_state["assignment_started"] = False
                        self._search_state["weak_order"] = {}
                        self._mark_top_level_safe()
                        self._save_checkpoint(force=False, completed=False)
                        continue
                    max_assignments = self.config["limits"].get("max_assignments")
                    if (
                        max_assignments is not None
                        and not bool(self._search_state.get("assignment_started", False))
                        and self.stats.get("assignments_processed") >= int(max_assignments)
                    ):
                        self.stats.stop_reason = "max_assignments"
                        self._stop_requested = True
                        exhausted = False
                        break
                    if not bool(self._search_state.get("assignment_started", False)):
                        self.stats.increment("assignments_processed")
                        self.stats.increment("canonical_assignments_processed")
                        self._search_state["assignment_started"] = True
                        self._search_state["weak_order"] = {}

                    resume_weak = self._search_state.get("weak_order", {})
                    weak_orders = WeakOrderEnumerator(
                        planar_map=planar_map,
                        assignment=assignment,
                        occurrence_names=assignment_enumerator.occurrence_names,
                        length_oracle=self.length_oracle,
                        angle_oracle=self.angle_oracle,
                        symmetry_mode=str(self.config["enumeration"]["symmetry_mode"]),
                        enable_length_filter=bool(
                            self.config["enumeration"]["enable_length_filter"]
                        ),
                        enable_angle_filter=bool(
                            self.config["enumeration"]["enable_angle_filter"]
                        ),
                        enable_exterior_arc_repetition_filter=bool(
                            self.config["enumeration"]
                            .get("exterior_arc_repetition", {})
                            .get("enabled", True)
                        ),
                        event_sink=self._event,
                        stop_predicate=self._should_stop,
                        resume_state=resume_weak if isinstance(resume_weak, Mapping) else None,
                        checkpoint_sink=self._weak_checkpoint,
                        track_exact_leaf_mass=bool(
                            self.config["enumeration"].get(
                                "track_exact_domain_size", True
                            )
                        ),
                        required_equivariance_transform=(
                            assignment_enumerator.required_transform(assignment)
                            if assignment.required_equivariance is not None
                            and bool(
                                self.config["enumeration"]
                                .get("cyclic_equivariance", {})
                                .get("enforce_weak_orders", True)
                            )
                            else None
                        ),
                        equivariance_piece_orbits=(
                            assignment_enumerator.equivariance_piece_orbits
                            if assignment.required_equivariance is not None
                            and bool(
                                self.config["enumeration"]
                                .get("cyclic_equivariance", {})
                                .get("enforce_weak_orders", True)
                            )
                            else ()
                        ),
                        mapping_symmetry=(
                            assignment_enumerator.mapping_symmetry
                            if str(self.config["enumeration"]["symmetry_mode"]) != "off"
                            else None
                        ),
                    )
                    self._current_weak_orders = weak_orders
                    placement_started = time.perf_counter()

                    for placement in weak_orders.enumerate():
                        self.stats.add_time(
                            "placement_enumeration",
                            time.perf_counter() - placement_started,
                        )
                        if bool(output_config.get("write_placements", False)):
                            placement_writer.write(
                                {
                                    "map": planar_map.name,
                                    "assignment": assignment.to_dict(
                                        assignment_enumerator.occurrence_names
                                    ),
                                    "placement": placement.to_dict(
                                        assignment_enumerator.occurrence_names
                                    ),
                                }
                            )

                        started = time.perf_counter()
                        try:
                            compiled = compile_word_case(planar_map, placement)
                            self.stats.increment("word_cases_compiled")
                        except Exception as error:
                            self.stats.increment("compile_errors")
                            self._record_unexpected_error(
                                error_writer,
                                stage="compile_word_case",
                                error=error,
                                context={
                                    "map": planar_map.name,
                                    "assignment_id": assignment.assignment_id,
                                    "placement_id": placement.placement_id,
                                },
                            )
                            placement_started = time.perf_counter()
                            continue
                        finally:
                            self.stats.add_time(
                                "word_compilation", time.perf_counter() - started
                            )

                        preword_result = None
                        preword_config = self.config["filters"].get(
                            "preword_pruning", {}
                        )
                        if bool(preword_config.get("enabled", True)):
                            preword_started = time.perf_counter()
                            self.stats.increment("preword_checks")
                            try:
                                preword_result = self.preword_pruning.analyze(
                                    planar_map,
                                    placement,
                                    compiled,
                                )
                            except Exception as error:
                                # Pre-word pruning is an optimization. Unexpected
                                # construction errors must never remove a formal case.
                                self.stats.increment("preword_errors")
                                self._record_unexpected_error(
                                    error_writer,
                                    stage="preword_pruning",
                                    error=error,
                                    context={
                                        "map": planar_map.name,
                                        "assignment_id": assignment.assignment_id,
                                        "placement_id": placement.placement_id,
                                        "word_case": compiled.to_dict(),
                                    },
                                )
                            finally:
                                self.stats.add_time(
                                    "preword_pruning",
                                    time.perf_counter() - preword_started,
                                )
                            if preword_result is not None:
                                topology = preword_result.topology
                                linear = preword_result.linear_invariants
                                self.stats.increment(
                                    "preword_unresolved_arc_images",
                                    topology.unresolved_images,
                                )
                                self.stats.increment(
                                    "preword_endpoint_checks",
                                    topology.endpoint_crossing_checks,
                                )
                                self.stats.increment(
                                    "preword_overlap_checks",
                                    topology.forced_overlap_checks,
                                )
                                if topology.propagation_truncated:
                                    self.stats.increment("preword_topology_truncations")
                                if linear is not None:
                                    self.stats.increment("preword_linear_checks")
                                    if linear.metric_exact_certificate_used:
                                        self.stats.increment("preword_metric_exact_certificates")
                                    if linear.point_angle_exact_certificate_used:
                                        self.stats.increment("preword_point_exact_certificates")
                                    if linear.signed_radius_balance_derived:
                                        self.stats.increment("preword_radius_balance_derived")
                                    if linear.smooth_turn_balance_derived:
                                        self.stats.increment("preword_smooth_turn_balance_derived")
                                    if linear.point_turn_balance_derived:
                                        self.stats.increment("preword_point_turn_balance_derived")
                            if preword_result is not None and not preword_result.feasible:
                                self.stats.increment("preword_rejections")
                                if preword_result.linear_invariants is None:
                                    self.stats.increment("preword_topology_rejections")
                                else:
                                    self.stats.increment("preword_linear_rejections")
                                reason_key = (
                                    preword_result.reason.lower()
                                    .replace("same-radius ", "")
                                    .replace("preword ", "")
                                    .replace(" ", "_")
                                    .replace("/", "_")
                                    .replace("-", "_")
                                )
                                self.stats.increment(f"preword_rejection_{reason_key}")
                                placement_started = time.perf_counter()
                                if self._placement_limit_reached():
                                    exhausted = False
                                    break
                                continue

                        if not bool(solver_config["enabled"]):
                            placement_started = time.perf_counter()
                            if self._placement_limit_reached():
                                exhausted = False
                                break
                            continue

                        solver = ExactPartialWordSolver(
                            compiled.effective_solver_equations, compiled.solver_variables
                        )
                        self.stats.increment("solver_cases")
                        families_before = self.stats.get("word_families")
                        try:
                            family_iterator = iter(
                                solver.solve(
                                    solver_limits,
                                    stop_predicate=self._should_stop,
                                )
                            )
                            while True:
                                solver_started = time.perf_counter()
                                try:
                                    family = next(family_iterator)
                                except StopIteration:
                                    self.stats.add_time(
                                        "exact_partial_word_solver",
                                        time.perf_counter() - solver_started,
                                    )
                                    break
                                except Exception:
                                    self.stats.add_time(
                                        "exact_partial_word_solver",
                                        time.perf_counter() - solver_started,
                                    )
                                    raise
                                else:
                                    self.stats.add_time(
                                        "exact_partial_word_solver",
                                        time.perf_counter() - solver_started,
                                    )
                                self.stats.increment("word_families")
                                self.stats.increment(f"word_family_{family.kind}")
                                if bool(output_config.get("write_families", False)):
                                    family_writer.write(
                                        {
                                            "schema_version": "formal-contour-word-family-v3",
                                            "map": planar_map.to_dict(),
                                            "assignment": assignment.to_dict(
                                                assignment_enumerator.occurrence_names
                                            ),
                                            "placement": placement.to_dict(
                                                assignment_enumerator.occurrence_names
                                            ),
                                            "word_case": compiled.to_dict(),
                                            "family": family.to_dict(),
                                        }
                                    )

                                specialization_count = 0
                                for specialization in expand_family(family, expansion_policy):
                                    specialization_count += 1
                                    self.stats.increment("family_specializations")
                                    profile_started = time.perf_counter()
                                    try:
                                        profile = build_formal_profile(
                                            planar_map,
                                            assignment_enumerator.occurrence_names,
                                            placement,
                                            compiled,
                                            family,
                                            specialization,
                                            tolerance=tolerance,
                                        )
                                    except DecorationInfeasible as error:
                                        self.stats.increment("decoration_rejections")
                                        self.stats.increment(
                                            f"decoration_rejection_{error.stage}"
                                        )
                                        continue
                                    except Exception as error:
                                        self.stats.increment("profile_build_errors")
                                        self._record_unexpected_error(
                                            error_writer,
                                            stage="profile_build",
                                            error=error,
                                            context={
                                                "map": planar_map.name,
                                                "assignment_id": assignment.assignment_id,
                                                "placement_id": placement.placement_id,
                                                "family": family.to_dict(),
                                                "specialization": specialization.to_dict(),
                                            },
                                        )
                                        continue
                                    finally:
                                        self.stats.add_time(
                                            "profile_decoration",
                                            time.perf_counter() - profile_started,
                                        )

                                    filter_started = time.perf_counter()
                                    filtered_profile, statuses = self.filter_pipeline.apply(profile)
                                    self.stats.add_time(
                                        "profile_filters",
                                        time.perf_counter() - filter_started,
                                    )
                                    if filtered_profile is None:
                                        self.stats.increment("profile_filter_rejections")
                                        if statuses:
                                            self.stats.increment(
                                                f"profile_filter_rejection_{statuses[-1][0]}"
                                            )
                                        continue

                                    key = conservative_profile_key(
                                        planar_map.name,
                                        assignment.canonical_key,
                                        placement.blocks,
                                        specialization.environment_map(),
                                    )
                                    if bool(
                                        self.config["filters"]["deduplicate_exact_profiles"]
                                    ) and key in self._seen_profile_keys:
                                        self.stats.increment("duplicate_profiles")
                                        continue

                                    formal_profile_id = "fp-" + key[:32]
                                    record = {
                                        "schema_version": "formal-contour-survivor-v7",
                                        "formal_profile_id": formal_profile_id,
                                        "map": planar_map.to_dict(),
                                        "assignment": assignment.to_dict(
                                            assignment_enumerator.occurrence_names
                                        ),
                                        "placement": placement.to_dict(
                                            assignment_enumerator.occurrence_names
                                        ),
                                        "word_case": compiled.to_dict(),
                                        "word_family": family.to_dict(),
                                        "specialization": specialization.to_dict(),
                                        "profile": filtered_profile.to_dict(),
                                    }
                                    is_new = self.checkpoint_store.store_survivor(key, record)
                                    if not is_new:
                                        self.stats.increment("duplicate_profiles")
                                        self._seen_profile_keys.add(key)
                                        continue
                                    self._seen_profile_keys.add(key)
                                    candidate_writer.write(record)
                                    self.stats.increment("profiles_emitted")
                                    print(
                                        "[SURVIVOR] "
                                        f"map={planar_map.name} assignment={assignment.assignment_id} "
                                        f"placement={placement.placement_id} family={family.family_id} "
                                        f"kind={family.kind} exponents={dict(specialization.exponent_assignment)} "
                                        f"file={candidate_path}",
                                        file=sys.stderr,
                                        flush=True,
                                    )
                                    print(
                                        "[DECORATED CONTOUR] "
                                        + filtered_profile.decorated_terminal_contour()["text"],
                                        file=sys.stderr,
                                        flush=True,
                                    )
                                    if bool(
                                        self.config["limits"]["stop_on_first_profile"]
                                    ):
                                        self.stats.stop_reason = "first_profile"
                                        self._stop_requested = True
                                        exhausted = False
                                        break
                                    if self._should_stop():
                                        exhausted = False
                                        break
                                if specialization_count == 0:
                                    self.stats.increment("families_not_specialized")
                                if self._should_stop():
                                    exhausted = False
                                    break
                        except Exception as error:
                            self.stats.increment("solver_errors")
                            self._record_unexpected_error(
                                error_writer,
                                stage="exact_partial_word_solver",
                                error=error,
                                context={
                                    "map": planar_map.name,
                                    "assignment_id": assignment.assignment_id,
                                    "placement_id": placement.placement_id,
                                    "word_case": compiled.to_dict(),
                                },
                            )

                        summary = solver.last_summary
                        self.stats.increment("residual_graph_nodes", summary.visited_states)
                        self.stats.increment("residual_graph_edges", summary.graph_edges)
                        self.stats.increment(
                            "unsupported_complex_components",
                            summary.unsupported_complex_components,
                        )
                        if summary.exact_unsat:
                            self.stats.increment("exact_unsat_word_cases")
                        if summary.status == "exact_unsupported_family_language":
                            self.stats.increment("unsupported_language_word_cases")
                        if summary.status == "unresolved_graph_limit":
                            self.stats.increment("graph_limited_word_cases")
                        if summary.status == "unresolved_family_limit":
                            self.stats.increment("family_limited_word_cases")
                        if summary.status == "interrupted_external_stop":
                            self.stats.increment("externally_stopped_word_cases")
                        if self.stats.get("word_families") == families_before:
                            self.stats.increment("word_cases_without_supported_family")

                        if bool(output_config.get("write_word_cases", False)):
                            word_case_audit_writer.write(
                                {
                                    "schema_version": "formal-contour-word-case-audit-v3",
                                    "map_name": planar_map.name,
                                    "assignment_id": assignment.assignment_id,
                                    "placement_id": placement.placement_id,
                                    "word_case": compiled.to_dict(),
                                    "preword_pruning": (
                                        preword_result.to_dict()
                                        if preword_result is not None
                                        else None
                                    ),
                                    "solver_summary": summary.to_dict(),
                                    "family_count": summary.emitted_families,
                                    "unsupported_component_count": len(
                                        solver.unsupported_components
                                    ),
                                }
                            )

                        if bool(output_config.get("write_unsupported", False)):
                            for component in solver.unsupported_components:
                                unsupported_writer.write(
                                    {
                                        "schema_version": "formal-contour-unsupported-word-component-v3",
                                        "map": planar_map.to_dict(),
                                        "assignment": assignment.to_dict(
                                            assignment_enumerator.occurrence_names
                                        ),
                                        "placement": placement.to_dict(
                                            assignment_enumerator.occurrence_names
                                        ),
                                        "word_case": compiled.to_dict(),
                                        "solver_summary": summary.to_dict(),
                                        "unsupported_component": component.to_dict(),
                                    }
                                )

                        if self._placement_limit_reached():
                            exhausted = False
                            break
                        placement_started = time.perf_counter()

                    self._search_state["weak_order"] = weak_orders.checkpoint_state()
                    self._current_weak_orders = None
                    if self._should_stop():
                        exhausted = False
                        break

                    # The assignment iterator exhausted naturally. Its raw weak-order
                    # mass is fully accounted for, even though most leaves were pruned
                    # as whole subtrees.
                    self._search_state["completed_leaf_mass"] = int(
                        self._search_state.get("completed_leaf_mass", 0)
                    ) + mass_per_assignment
                    self._search_state["assignment_id"] = assignment_id + 1
                    self._search_state["assignment_started"] = False
                    self._search_state["weak_order"] = {}
                    self._mark_top_level_safe()
                    self._save_checkpoint(force=True, completed=False)

                if self._should_stop():
                    exhausted = False
                    break
                self._search_state["map_index"] = map_index + 1
                self._search_state["assignment_id"] = 0
                self._search_state["map_started"] = False
                self._search_state["assignment_started"] = False
                self._search_state["weak_order"] = {}
                self._mark_top_level_safe()
                self._save_checkpoint(force=True, completed=False)

        except KeyboardInterrupt:
            self.stats.stop_reason = "keyboard_interrupt"
            self._stop_requested = True
            exhausted = False
            print(
                "Interrupted by user; saving a compact checkpoint before exit.",
                file=sys.stderr,
                flush=True,
            )
        finally:
            if exhausted and not self._stop_requested:
                self._mark_top_level_safe()
            self._save_checkpoint(force=True, completed=exhausted and not self._stop_requested)
            candidate_writer.close()
            family_writer.close()
            unsupported_writer.close()
            word_case_audit_writer.close()
            placement_writer.close()
            error_writer.close()
            if bool(output_config.get("write_candidates", True)):
                self.checkpoint_store.export_survivors_jsonl(candidate_path)
            self._maybe_progress(force=True)
            self.checkpoint_store.close()

        if exhausted and not self._stop_requested:
            self.stats.stop_reason = "completed"
        self._record_dropped_outputs(
            family_writer,
            unsupported_writer,
            word_case_audit_writer,
            placement_writer,
            error_writer,
        )
        summary = self._final_summary(
            candidate_path,
            family_path,
            unsupported_path,
            word_case_audit_path,
            placement_path,
            error_path,
        )
        atomic_write_json(self.output_directory / "run_summary.json", summary)
        self._report_tainted_campaign(error_path)
        return summary

    def _placement_limit_reached(self) -> bool:
        max_placements = self.config["limits"].get("max_placements")
        if (
            max_placements is not None
            and self.stats.get("surviving_placements") >= int(max_placements)
        ):
            self.stats.stop_reason = "max_placements"
            self._stop_requested = True
            return True
        return False

    def _record_dropped_outputs(self, *writers: object) -> None:
        names = (
            "families",
            "unsupported_components",
            "word_cases",
            "placements",
            "errors",
        )
        for name, writer in zip(names, writers):
            dropped = int(getattr(writer, "dropped", 0))
            if dropped:
                self.stats.increment(f"output_{name}_records_dropped", dropped)

    def _final_summary(
        self,
        candidate_path: Path,
        family_path: Path,
        unsupported_path: Path,
        word_case_audit_path: Path,
        placement_path: Path,
        error_path: Path,
    ) -> Dict[str, object]:
        assignment_mass, assignment_total, assignment_percent = self._current_assignment_progress()
        unexpected_error_count = self.stats.get("unexpected_errors")
        return {
            "tainted": unexpected_error_count > 0,
            "unexpected_error_count": unexpected_error_count,
            "unexpected_errors_by_stage": self._unexpected_errors_by_stage(),
            "configuration": self.config,
            "statistics": self.stats.to_dict(),
            "progress": {
                "estimate_semantics": (
                    "Fraction of raw anchored weak cyclic orders accounted for by "
                    "completed or pruned DFS subtrees across canonical assignments."
                ),
                "estimated_percent": self._progress_percentage(),
                "raw_weak_orders_accounted": self._current_processed_leaf_mass(),
                "raw_weak_orders_total": self._total_leaf_mass,
                "canonical_assignments_total": self._total_assignment_count,
                "current_assignment_raw_orders_accounted": assignment_mass,
                "current_assignment_raw_orders_total": assignment_total,
                "current_assignment_estimated_percent": assignment_percent,
                "map_index": int(self._search_state.get("map_index", 0)),
                "assignment_id": int(self._search_state.get("assignment_id", 0)),
            },
            "checkpoint": {
                "enabled": self.checkpoint_store.enabled,
                "path": str(self.checkpoint_store.path),
                "resumed": self._resumed,
                "automatic_resume": bool(self.config.get("checkpoint", {}).get("resume", True)),
                "interval_seconds": float(
                    self.config.get("checkpoint", {}).get("interval_seconds", 60.0)
                ),
                "stores_rejected_cases": False,
                "stores_solver_states": False,
                "stores_survivors": True,
            },
            "oracles": {
                "length": {
                    "calls": self.length_oracle.calls,
                    "cache_hits": self.length_oracle.cache_hits,
                    "cache_misses": self.length_oracle.calls - self.length_oracle.cache_hits,
                    "elapsed_seconds": self.length_oracle.elapsed_seconds,
                    "lp_seconds": self.length_oracle.lp_seconds,
                    "pruned_nodes": self.stats.get("length_pruned_nodes"),
                },
                "angle": {
                    "calls": self.angle_oracle.calls,
                    "cache_hits": self.angle_oracle.cache_hits,
                    "cache_misses": self.angle_oracle.calls - self.angle_oracle.cache_hits,
                    "elapsed_seconds": self.angle_oracle.elapsed_seconds,
                    "lp_seconds": self.angle_oracle.lp_seconds,
                    "pruned_nodes": self.stats.get("angle_pruned_nodes"),
                    "semantics": (
                        "positive solid-angle sums at map vertices, represented through "
                        "prototype signed point turns"
                    ),
                },
                "preword_topology_strict_length": {
                    "calls": self.preword_pruning.topology_filter.strict_oracle.calls,
                    "cache_hits": self.preword_pruning.topology_filter.strict_oracle.cache_hits,
                    "elapsed_seconds": self.preword_pruning.topology_filter.strict_oracle.elapsed_seconds,
                    "lp_seconds": self.preword_pruning.topology_filter.strict_oracle.lp_seconds,
                    "exact_certificate_calls": self.preword_pruning.topology_filter.exact_strict_oracle.calls,
                    "exact_certificate_cache_hits": self.preword_pruning.topology_filter.exact_strict_oracle.cache_hits,
                    "exact_certificate_elapsed_seconds": self.preword_pruning.topology_filter.exact_strict_oracle.elapsed_seconds,
                    "rejections": self.stats.get("preword_topology_rejections"),
                },
                "preword_metric_invariants": {
                    "calls": self.preword_pruning.linear_filter.metric_oracle.calls,
                    "cache_hits": self.preword_pruning.linear_filter.metric_oracle.cache_hits,
                    "exact_certificate_calls": self.preword_pruning.linear_filter.metric_oracle.exact_calls,
                    "elapsed_seconds": self.preword_pruning.linear_filter.metric_oracle.elapsed_seconds,
                    "float_seconds": self.preword_pruning.linear_filter.metric_oracle.float_seconds,
                    "exact_seconds": self.preword_pruning.linear_filter.metric_oracle.exact_seconds,
                },
                "preword_point_turns": {
                    "calls": self.preword_pruning.linear_filter.point_oracle.calls,
                    "cache_hits": self.preword_pruning.linear_filter.point_oracle.cache_hits,
                    "exact_certificate_calls": self.preword_pruning.linear_filter.point_oracle.exact_calls,
                    "elapsed_seconds": self.preword_pruning.linear_filter.point_oracle.elapsed_seconds,
                    "float_seconds": self.preword_pruning.linear_filter.point_oracle.float_seconds,
                    "exact_seconds": self.preword_pruning.linear_filter.point_oracle.exact_seconds,
                },
            },
            "files": {
                "candidates": str(candidate_path),
                "checkpoint": str(self.checkpoint_store.path),
                "word_families": (
                    str(family_path)
                    if bool(self.config["output"].get("write_families", False))
                    else None
                ),
                "unsupported_word_components": (
                    str(unsupported_path)
                    if bool(self.config["output"].get("write_unsupported", False))
                    else None
                ),
                "word_case_audit": (
                    str(word_case_audit_path)
                    if bool(self.config["output"].get("write_word_cases", False))
                    else None
                ),
                "placements": (
                    str(placement_path)
                    if bool(self.config["output"].get("write_placements", False))
                    else None
                ),
                "errors": (
                    str(error_path)
                    if bool(self.config["output"].get("write_errors", True))
                    else None
                ),
            },
        }
