from __future__ import annotations

import json
import sys
from copy import deepcopy
import time
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
from formal_disk4.words.compile import compile_word_case
from formal_disk4.words.exact_partial import ExactPartialWordSolver, SolverLimits
from formal_disk4.words.families import FamilyExpansionPolicy, expand_family

from .checkpoint import CheckpointStore, search_fingerprint
from .output import JsonlWriter, NullJsonlWriter, atomic_write_json
from .stats import RunStats


MapContext = Tuple[PlanarMap, AssignmentEnumerator, Tuple[ContourAssignment, ...], int]


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
        assignment_position = int(self._search_state.get("assignment_id", 0)) + 1
        rejected_profiles = (
            self.stats.get("decoration_rejections")
            + self.stats.get("profile_filter_rejections")
        )
        message = (
            f"[{elapsed:9.2f}s] map={self._current_map_name} "
            f"overall~{percent:5.1f}% "
            f"assignment={assignment_position}/{max(1, self._total_assignment_count)} "
            f"current~{assignment_percent:5.1f}% "
            f"nodes={nodes} ({rate:,.0f}/s) "
            f"length_pruned={self.stats.get('length_pruned_nodes')} "
            f"angle_pruned={self.stats.get('angle_pruned_nodes')} "
            f"placements={self.stats.get('surviving_placements')} "
            f"word_systems={self.stats.get('solver_cases')} "
            f"families={self.stats.get('word_families')}"
            f"[finite={self.stats.get('word_family_finite')},"
            f"power={self.stats.get('word_family_power')},"
            f"nested={self.stats.get('word_family_nested_power')}] "
            f"specializations={self.stats.get('family_specializations')} "
            f"unexpanded={self.stats.get('families_not_specialized')} "
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
        for planar_map in iterate_maps(tuple(self.config["maps"])):
            assignment_enumerator = AssignmentEnumerator(
                planar_map,
                allow_reflections=bool(
                    self.config["enumeration"]["allow_reflections"]
                ),
                symmetry_mode=str(self.config["enumeration"]["symmetry_mode"]),
            )
            assignments = tuple(assignment_enumerator.enumerate())
            if assignments:
                lengths = tuple(len(sequence) for sequence in assignments[0].sequences)
                reference_index = assignments[0].piece_names.index(planar_map.reference_piece)
                mass_per_assignment = count_weak_orders_for_lengths(lengths, reference_index)
            else:
                mass_per_assignment = 0
            contexts.append((planar_map, assignment_enumerator, assignments, mass_per_assignment))
            total_mass += len(assignments) * mass_per_assignment
            total_assignments += len(assignments)
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
                sum(context[1].raw_assignment_count() for context in contexts),
            )
        self.stats.counters["canonical_assignments_in_domain"] = self._total_assignment_count
        self.stats.counters["estimated_raw_weak_orders_in_domain"] = self._total_leaf_mass

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
                planar_map, assignment_enumerator, assignments, mass_per_assignment = contexts[map_index]
                self._current_map_name = planar_map.name
                self._search_state["map_index"] = map_index
                if not bool(self._search_state.get("map_started", False)):
                    self.stats.increment("maps_processed")
                    self._search_state["map_started"] = True

                start_assignment_id = int(self._search_state.get("assignment_id", 0))
                for assignment_id in range(start_assignment_id, len(assignments)):
                    assignment = assignments[assignment_id]
                    self._search_state["assignment_id"] = assignment_id
                    if self._should_stop():
                        exhausted = False
                        break
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
                        event_sink=self._event,
                        stop_predicate=self._should_stop,
                        resume_state=resume_weak if isinstance(resume_weak, Mapping) else None,
                        checkpoint_sink=self._weak_checkpoint,
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
                            error_writer.write(
                                {
                                    "stage": "compile_word_case",
                                    "map": planar_map.name,
                                    "assignment_id": assignment.assignment_id,
                                    "placement_id": placement.placement_id,
                                    "error": repr(error),
                                }
                            )
                            placement_started = time.perf_counter()
                            continue
                        finally:
                            self.stats.add_time(
                                "word_compilation", time.perf_counter() - started
                            )

                        if not bool(solver_config["enabled"]):
                            placement_started = time.perf_counter()
                            if self._placement_limit_reached():
                                exhausted = False
                                break
                            continue

                        solver = ExactPartialWordSolver(
                            compiled.equations, compiled.atomic_variables
                        )
                        self.stats.increment("solver_cases")
                        families_before = self.stats.get("word_families")
                        started = time.perf_counter()
                        try:
                            for family in solver.solve(solver_limits):
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
                                        error_writer.write(
                                            {
                                                "stage": "profile_build",
                                                "map": planar_map.name,
                                                "assignment_id": assignment.assignment_id,
                                                "placement_id": placement.placement_id,
                                                "family": family.to_dict(),
                                                "specialization": specialization.to_dict(),
                                                "error": repr(error),
                                            }
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
                                        "schema_version": "formal-contour-survivor-v5",
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
                            error_writer.write(
                                {
                                    "stage": "exact_partial_word_solver",
                                    "map": planar_map.name,
                                    "assignment_id": assignment.assignment_id,
                                    "placement_id": placement.placement_id,
                                    "error": repr(error),
                                    "word_case": compiled.to_dict(),
                                }
                            )
                        finally:
                            self.stats.add_time(
                                "exact_partial_word_solver",
                                time.perf_counter() - started,
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
        return {
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
                },
                "angle": {
                    "calls": self.angle_oracle.calls,
                    "cache_hits": self.angle_oracle.cache_hits,
                    "semantics": (
                        "signed turn classes; reversed contour gives complementary "
                        "interior angle"
                    ),
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
