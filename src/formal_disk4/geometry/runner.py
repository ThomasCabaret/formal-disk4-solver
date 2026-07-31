from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Mapping

from formal_disk4.pipeline.output import JsonlWriter, NullJsonlWriter, atomic_write_json

from .model import parse_formal_geometry_problem
from .solver import GeometrySolverConfig, NumericalContourSolver


GEOMETRY_CHECKPOINT_VERSION = 2


def _file_fingerprint(path: Path) -> str:
    stat = path.stat()
    payload = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


class GeometryRunner:
    """Stream formal candidates into the single-piece numerical contour solver."""

    def __init__(self, config: Mapping[str, Any]) -> None:
        self.config = dict(config)
        self.input_path = Path(self.config["input"]["candidates_file"]).resolve()
        self.output_directory = Path(self.config["output"]["directory"]).resolve()
        self.output_directory.mkdir(parents=True, exist_ok=True)
        output = self.config["output"]
        self.solutions_path = self.output_directory / str(
            output.get("solutions_file", "geometric_solutions.jsonl")
        )
        self.summary_path = self.output_directory / str(
            output.get("summary_file", "geometry_summary.json")
        )
        self.checkpoint_path = self.output_directory / str(
            output.get("checkpoint_file", "geometry_checkpoint.json")
        )
        self.failures_path = self.output_directory / str(
            output.get("failures_file", "geometry_failures.jsonl")
        )
        self.solver = NumericalContourSolver(
            GeometrySolverConfig.from_mapping(self.config["geometry"])
        )

    def _initial_state(self) -> Dict[str, Any]:
        return {
            "version": GEOMETRY_CHECKPOINT_VERSION,
            "input_path": str(self.input_path),
            "input_fingerprint": _file_fingerprint(self.input_path),
            "scan_passes": 0,
            "candidates_seen": 0,
            "candidates_skipped_solved": 0,
            "candidates_solved": 0,
            "candidates_failed": 0,
            "optimizer_attempts": 0,
            "fixed_candidates_evaluated": 0,
            "elapsed_seconds": 0.0,
            "completed": False,
        }

    def _load_state(self) -> Dict[str, Any]:
        checkpoint = self.config.get("checkpoint", {})
        restart = bool(checkpoint.get("restart", False))
        resume = bool(checkpoint.get("resume", True))
        if restart:
            for path in (
                self.solutions_path,
                self.summary_path,
                self.checkpoint_path,
                self.failures_path,
            ):
                if path.exists():
                    path.unlink()
            return self._initial_state()
        if not resume or not self.checkpoint_path.exists():
            return self._initial_state()
        state = _read_json(self.checkpoint_path)
        version = int(state.get("version", -1))
        if version not in (1, GEOMETRY_CHECKPOINT_VERSION):
            raise RuntimeError(
                "Geometry checkpoint version is incompatible. Use --restart."
            )
        if str(state.get("input_path")) != str(self.input_path):
            raise RuntimeError(
                "Geometry checkpoint refers to a different candidates file. Use --restart "
                "or choose another geometry output directory."
            )
        if version == 1:
            # Version 1 stored a permanent line cursor. Migrate conservatively by
            # discarding that cursor and rescanning every unresolved candidate.
            state.pop("next_line", None)
            state["version"] = GEOMETRY_CHECKPOINT_VERSION
            state.setdefault("scan_passes", 0)
            state.setdefault("candidates_skipped_solved", 0)
            state["completed"] = False
        current_fingerprint = _file_fingerprint(self.input_path)
        if str(state.get("input_fingerprint", "")) != current_fingerprint:
            state["completed"] = False
        state["input_fingerprint"] = current_fingerprint
        return state

    def _save_state(self, state: Mapping[str, Any]) -> None:
        if not bool(self.config.get("checkpoint", {}).get("enabled", True)):
            return
        atomic_write_json(self.checkpoint_path, state)

    def _load_solved_profile_ids(self) -> set[str]:
        """Read persisted solutions so resume never depends on a line cursor."""
        solved: set[str] = set()
        if not self.solutions_path.exists():
            return solved
        with self.solutions_path.open(
            "r", encoding="utf-8", errors="replace"
        ) as handle:
            for line_number, line in enumerate(handle, 1):
                text = line.strip()
                if not text:
                    continue
                try:
                    record = json.loads(text)
                except json.JSONDecodeError as error:
                    # A malformed old record must never cause a formal candidate to
                    # be skipped. It may only lead to a harmless duplicate solution.
                    print(
                        "[GEOMETRY CHECKPOINT WARNING] "
                        f"Ignoring malformed solution record at line {line_number}: {error}",
                        file=sys.stderr,
                        flush=True,
                    )
                    continue
                profile_id = record.get("formal_profile_id")
                if isinstance(profile_id, str) and profile_id:
                    solved.add(profile_id)
        return solved

    def run(self) -> Dict[str, Any]:
        if not self.input_path.exists():
            raise FileNotFoundError(
                f"Formal candidate file not found: {self.input_path}. "
                "Run the formal search first."
            )
        state = self._load_state()
        solved_profile_ids = self._load_solved_profile_ids()
        # The persisted solution file is authoritative. A stale checkpoint must
        # never claim that a missing solution record is already resolved.
        state["candidates_solved"] = len(solved_profile_ids)
        state["scan_passes"] = int(state.get("scan_passes", 0)) + 1
        state["completed"] = False
        started = time.perf_counter()
        output = self.config["output"]
        solution_writer = JsonlWriter(
            self.solutions_path,
            flush_every=1,
            append=self.solutions_path.exists(),
        )
        failure_writer = (
            JsonlWriter(
                self.failures_path,
                flush_every=1,
                append=self.failures_path.exists(),
                max_records=int(output.get("max_failure_records", 1000)),
            )
            if bool(output.get("write_failures", False))
            else NullJsonlWriter()
        )
        limits = self.config["limits"]
        max_candidates = limits.get("max_candidates")
        max_solutions = limits.get("max_solutions")
        stop_on_first = bool(limits.get("stop_on_first_solution", False))
        include_formal = bool(output.get("include_formal_candidate", True))
        stop_reason = "completed"
        session_candidates_attempted = 0

        try:
            with self.input_path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, 1):
                    text = line.strip()
                    if not text:
                        continue
                    candidate = json.loads(text)
                    problem = parse_formal_geometry_problem(
                        candidate,
                        source_path=self.input_path,
                        source_line=line_number,
                    )
                    if problem.formal_profile_id in solved_profile_ids:
                        state["candidates_skipped_solved"] = int(
                            state.get("candidates_skipped_solved", 0)
                        ) + 1
                        continue
                    if (
                        max_candidates is not None
                        and session_candidates_attempted >= int(max_candidates)
                    ):
                        stop_reason = "max_candidates"
                        break
                    if (
                        max_solutions is not None
                        and int(state["candidates_solved"]) >= int(max_solutions)
                    ):
                        stop_reason = "max_solutions"
                        break
                    session_candidates_attempted += 1
                    print(
                        "[GEOMETRY] "
                        f"candidate={problem.formal_profile_id} map={problem.map_name} "
                        f"line={line_number} generic_points="
                        f"{self.solver.config.intermediate_points_per_generic_curve}",
                        file=sys.stderr,
                        flush=True,
                    )
                    result = self.solver.solve(problem)
                    state["candidates_seen"] = int(state["candidates_seen"]) + 1
                    state["optimizer_attempts"] = int(state["optimizer_attempts"]) + result.attempts
                    if result.attempts == 0:
                        state["fixed_candidates_evaluated"] = int(
                            state.get("fixed_candidates_evaluated", 0)
                        ) + 1
                    if result.solution is not None:
                        state["candidates_solved"] = int(state["candidates_solved"]) + 1
                        record: Dict[str, Any] = {
                            "schema_version": "geometric-contour-result-v1",
                            "formal_profile_id": problem.formal_profile_id,
                            "source": {
                                "candidates_file": str(self.input_path),
                                "line_number": line_number,
                                "map": problem.map_name,
                            },
                            "geometric_solution": result.solution.to_dict(),
                        }
                        if include_formal:
                            record["formal_candidate"] = candidate
                        solution_writer.write(record)
                        solved_profile_ids.add(problem.formal_profile_id)
                        validation = result.solution.validation
                        print(
                            "[GEOMETRIC SOLUTION] "
                            f"id={result.solution.solution_id} formal={problem.formal_profile_id} "
                            f"attempts={result.attempts} closure={validation.closure_error:.3e} "
                            f"area={validation.signed_area:.9g} "
                            f"file={self.solutions_path}",
                            file=sys.stderr,
                            flush=True,
                        )
                    else:
                        state["candidates_failed"] = int(state["candidates_failed"]) + 1
                        failure_writer.write(
                            {
                                "formal_profile_id": problem.formal_profile_id,
                                "source_line": line_number,
                                "reason": result.reason,
                                "attempts": result.attempts,
                                "best_cost": result.best_cost,
                                "best_validation": result.best_validation,
                            }
                        )
                        print(
                            "[GEOMETRY NOT FOUND] "
                            f"formal={problem.formal_profile_id} attempts={result.attempts} "
                            f"reason={result.reason}",
                            file=sys.stderr,
                            flush=True,
                        )
                    state["elapsed_seconds"] = float(state.get("elapsed_seconds", 0.0)) + (
                        time.perf_counter() - started
                    )
                    started = time.perf_counter()
                    state["completed"] = False
                    self._save_state(state)

                    if stop_on_first and result.solution is not None:
                        stop_reason = "first_solution"
                        break
                    if max_solutions is not None and int(state["candidates_solved"]) >= int(max_solutions):
                        stop_reason = "max_solutions"
                        break
                else:
                    state["completed"] = True
                    stop_reason = "completed"
        except KeyboardInterrupt:
            stop_reason = "keyboard_interrupt"
            print(
                "[GEOMETRY] Interrupted by user; saving the conservative checkpoint.",
                file=sys.stderr,
                flush=True,
            )
        finally:
            state["elapsed_seconds"] = float(state.get("elapsed_seconds", 0.0)) + (
                time.perf_counter() - started
            )
            state["input_fingerprint"] = _file_fingerprint(self.input_path)
            self._save_state(state)
            solution_writer.close()
            failure_writer.close()

        summary = {
            "schema_version": "geometry-run-summary-v1",
            "input": str(self.input_path),
            "output_directory": str(self.output_directory),
            "solutions_file": str(self.solutions_path),
            "checkpoint_file": str(self.checkpoint_path),
            "stop_reason": stop_reason,
            "state": state,
            "geometry_config": self.config["geometry"],
            "scope": "single_piece_contour_only",
            "validation_note": (
                "The staged solver first optimizes analytic contour closure without "
                "collision sampling. Full angle, length, area and self-intersection "
                "validation runs only on closed candidates. Circular arcs are sampled "
                "only for final numerical validation; this is not a formal proof."
            ),
        }
        atomic_write_json(self.summary_path, summary)
        return summary
