from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TextIO

from formal_disk4.orchestration.catalog import CaseCatalog, CaseDefinition, SUPPORTED_STAGES


PIPELINE_SCHEMA = "formal-disk4-pipeline-v1"
PIPELINE_STATE_SCHEMA = "formal-disk4-pipeline-state-v1"
_PROGRESS_RE = re.compile(r"overall~\s*(\d+(?:\.\d+)?)%")
_GEOMETRY_START_RE = re.compile(r"^\[GEOMETRY\]\s+candidate=")


def _deep_merge(target: dict[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
    for key, value in source.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = deepcopy(value)
    return target


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _safe_identifier(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return cleaned or "pipeline"


@dataclass(frozen=True)
class PipelineTask:
    case_id: str
    stage: str
    arguments: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.stage not in SUPPORTED_STAGES:
            raise ValueError(f"Unsupported pipeline stage: {self.stage}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "stage": self.stage,
            "arguments": list(self.arguments),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PipelineTask":
        return cls(
            case_id=str(data["case_id"]),
            stage=str(data["stage"]),
            arguments=tuple(str(value) for value in data.get("arguments", ())),
        )


@dataclass(frozen=True)
class PipelinePlan:
    pipeline_id: str
    name: str
    tasks: tuple[PipelineTask, ...]
    source: Path | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if not self.tasks:
            raise ValueError("A pipeline must contain at least one task.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PIPELINE_SCHEMA,
            "pipeline_id": self.pipeline_id,
            "name": self.name,
            "tasks": [task.to_dict() for task in self.tasks],
        }

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def save(self, path: Path) -> None:
        _atomic_write_json(path, self.to_dict())

    @classmethod
    def load(cls, path: Path) -> "PipelinePlan":
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != PIPELINE_SCHEMA:
            raise ValueError(f"Unsupported pipeline schema in {path}.")
        tasks = tuple(PipelineTask.from_dict(item) for item in data.get("tasks", ()))
        return cls(
            pipeline_id=str(data.get("pipeline_id") or path.stem),
            name=str(data.get("name") or path.stem),
            tasks=tasks,
            source=path,
        )


@dataclass(frozen=True)
class MaterializedTask:
    task: PipelineTask
    case: CaseDefinition
    config_path: Path
    command: tuple[str, ...]
    skipped_reason: str | None = None


class TaskProgress:
    def __init__(self, root: Path, task: PipelineTask, case: CaseDefinition):
        self.stage = task.stage
        self.case = case
        self.geometry_started = 0
        self.geometry_total = 0
        if self.stage == "geometry":
            total = _count_jsonl(root / case.output_directory / "candidates.jsonl")
            solved = _count_jsonl(
                root
                / case.output_directory
                / "geometry"
                / "geometric_solutions.jsonl"
            )
            self.geometry_total = max(0, total - solved)

    def feed(self, line: str) -> float | None:
        if self.stage == "search":
            match = _PROGRESS_RE.search(line)
            if match:
                return min(1.0, max(0.0, float(match.group(1)) / 100.0))
            return None
        if self.stage == "geometry" and _GEOMETRY_START_RE.search(line):
            self.geometry_started += 1
            if self.geometry_total > 0:
                return min(1.0, self.geometry_started / self.geometry_total)
        return None


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _python_command(root: Path) -> tuple[str, ...]:
    windows_python = root / ".venv" / "Scripts" / "python.exe"
    if windows_python.exists():
        return (str(windows_python),)
    posix_python = root / ".venv" / "bin" / "python"
    if posix_python.exists():
        return (str(posix_python),)
    return (sys.executable,)


def materialize_task(
    root: Path,
    case: CaseDefinition,
    task: PipelineTask,
    generated_config_directory: Path,
    task_index: int,
) -> MaterializedTask:
    config_path = generated_config_directory / (
        f"{task_index + 1:03d}_{_safe_identifier(task.case_id)}_{task.stage}.json"
    )
    if case.structurally_impossible:
        return MaterializedTask(
            task=task,
            case=case,
            config_path=config_path,
            command=(),
            skipped_reason="case is marked structurally impossible",
        )

    base_path = case.config_for(task.stage)
    config = json.loads(base_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError(f"Expected a JSON object in {base_path}.")
    _deep_merge(config, case.overrides_for(task.stage))

    output = case.output_directory.as_posix()
    if task.stage == "search":
        config["maps"] = [case.map_name]
        config.setdefault("output", {})["directory"] = output
        subcommand = "run"
    elif task.stage == "geometry":
        config.setdefault("input", {})["candidates_file"] = (
            case.output_directory / "candidates.jsonl"
        ).as_posix()
        config.setdefault("output", {})["directory"] = (
            case.output_directory / "geometry"
        ).as_posix()
        subcommand = "geometry"
    elif task.stage == "visualize":
        config.setdefault("input", {})["solutions_file"] = (
            case.output_directory / "geometry" / "geometric_solutions.jsonl"
        ).as_posix()
        viewer = config.setdefault("viewer", {})
        viewer["title"] = f"{case.label} - geometric solutions"
        viewer["empty_message"] = f"No geometric solution for {case.label}."
        subcommand = "visualize"
    else:
        raise ValueError(f"Unsupported task stage: {task.stage}")

    _atomic_write_json(config_path, config)
    command = (
        *_python_command(root),
        "-m",
        "formal_disk4",
        subcommand,
        "--config",
        str(config_path),
        *task.arguments,
    )
    return MaterializedTask(task, case, config_path, tuple(command))


@dataclass
class PipelineCallbacks:
    on_log: Callable[[str], None] = lambda _line: None
    on_task_start: Callable[[int, PipelineTask, CaseDefinition], None] = (
        lambda _index, _task, _case: None
    )
    on_task_progress: Callable[[int, float | None], None] = (
        lambda _index, _progress: None
    )
    on_task_end: Callable[[int, PipelineTask, int], None] = (
        lambda _index, _task, _returncode: None
    )
    on_pipeline_progress: Callable[[float], None] = lambda _progress: None


class PipelineExecutor:
    """Run search/geometry sequentially and launch viewers independently."""

    def __init__(self, root: Path | str, catalog: CaseCatalog | None = None):
        self.root = Path(root).resolve()
        self.catalog = catalog or CaseCatalog.load(self.root)
        self.stop_after_current = threading.Event()
        self.current_process: subprocess.Popen[str] | None = None
        self.detached_visualizers: set[subprocess.Popen[str]] = set()
        self._detached_lock = threading.Lock()

    def request_stop_after_current(self) -> None:
        self.stop_after_current.set()

    def run(
        self,
        plan: PipelinePlan,
        callbacks: PipelineCallbacks | None = None,
        *,
        resume: bool = True,
    ) -> int:
        callbacks = callbacks or PipelineCallbacks()
        run_root = self.root / "output" / "pipelines" / _safe_identifier(plan.pipeline_id)
        generated = run_root / "generated_configs"
        generated.mkdir(parents=True, exist_ok=True)
        state_path = run_root / "pipeline_state.json"
        completed = _load_completed_tasks(state_path, plan) if resume else set()
        if not resume and state_path.exists():
            state_path.unlink()
        log_path = run_root / (
            "pipeline_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".log"
        )
        self.stop_after_current.clear()

        with log_path.open("a", encoding="utf-8", buffering=1) as log:
            callbacks.on_log(f"[PIPELINE] {plan.name} ({len(plan.tasks)} tasks)")
            callbacks.on_log(f"[LOG] {log_path}")
            for index, task in enumerate(plan.tasks):
                if index in completed:
                    callbacks.on_log(
                        f"[SKIP COMPLETED] {index + 1}/{len(plan.tasks)} "
                        f"{task.stage} {task.case_id}"
                    )
                    callbacks.on_pipeline_progress((index + 1) / len(plan.tasks))
                    continue
                case = self.catalog.get(task.case_id)
                callbacks.on_task_start(index, task, case)
                materialized = materialize_task(
                    self.root, case, task, generated, index
                )
                if materialized.skipped_reason:
                    callbacks.on_log(
                        f"[SKIP] {task.case_id}: {materialized.skipped_reason}."
                    )
                    completed.add(index)
                    _save_state(state_path, plan, completed, None)
                    callbacks.on_task_end(index, task, 0)
                    callbacks.on_pipeline_progress((index + 1) / len(plan.tasks))
                    continue

                command_text = subprocess.list2cmdline(list(materialized.command))
                callbacks.on_log(
                    f"[TASK {index + 1}/{len(plan.tasks)}] {task.stage} {task.case_id}"
                )
                callbacks.on_log(f"[COMMAND] {command_text}")
                print(f"[TASK] {task.stage} {task.case_id}", file=log)
                print(f"[COMMAND] {command_text}", file=log)
                _save_state(state_path, plan, completed, index)
                if task.stage == "visualize":
                    returncode = self._launch_visualizer(
                        materialized,
                        index,
                        callbacks,
                        run_root / "visualizer_logs",
                    )
                else:
                    returncode = self._run_process(
                        materialized,
                        index,
                        len(plan.tasks),
                        callbacks,
                        log,
                    )
                callbacks.on_task_end(index, task, returncode)
                if returncode != 0:
                    callbacks.on_log(
                        f"[PIPELINE STOPPED] Task returned exit code {returncode}."
                    )
                    _save_state(state_path, plan, completed, index)
                    return returncode
                completed.add(index)
                _save_state(state_path, plan, completed, None)
                callbacks.on_pipeline_progress((index + 1) / len(plan.tasks))
                if self.stop_after_current.is_set():
                    callbacks.on_log("[PIPELINE PAUSED] Stop requested after current task.")
                    return 0

        callbacks.on_log("[PIPELINE COMPLETE]")
        return 0

    def _launch_visualizer(
        self,
        materialized: MaterializedTask,
        task_index: int,
        callbacks: PipelineCallbacks,
        log_directory: Path,
    ) -> int:
        """Launch a viewer independently so later pipeline tasks are not blocked."""

        environment = self._subprocess_environment()
        log_directory.mkdir(parents=True, exist_ok=True)
        log_path = log_directory / (
            f"{task_index + 1:03d}_{_safe_identifier(materialized.task.case_id)}.log"
        )
        log_handle = log_path.open("a", encoding="utf-8", buffering=1)
        creationflags = 0
        start_new_session = os.name != "nt"
        if os.name == "nt":
            if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
                creationflags |= subprocess.CREATE_NEW_PROCESS_GROUP
            if hasattr(subprocess, "DETACHED_PROCESS"):
                creationflags |= subprocess.DETACHED_PROCESS
        try:
            process = subprocess.Popen(
                list(materialized.command),
                cwd=self.root,
                env=environment,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
                start_new_session=start_new_session,
            )
        except Exception:
            log_handle.close()
            raise

        with self._detached_lock:
            self.detached_visualizers.add(process)
        callbacks.on_log(
            f"[VISUALIZER LAUNCHED] {materialized.task.case_id} "
            f"pid={process.pid} log={log_path}"
        )

        def reap() -> None:
            returncode = int(process.wait())
            log_handle.close()
            with self._detached_lock:
                self.detached_visualizers.discard(process)
            callbacks.on_log(
                f"[VISUALIZER CLOSED] {materialized.task.case_id} "
                f"exit_code={returncode}"
            )

        threading.Thread(target=reap, daemon=True).start()
        return 0

    def _subprocess_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        source = str(self.root / "src")
        environment["PYTHONPATH"] = (
            source
            if not environment.get("PYTHONPATH")
            else source + os.pathsep + environment["PYTHONPATH"]
        )
        environment["PYTHONUTF8"] = "1"
        environment["PYTHONUNBUFFERED"] = "1"
        return environment

    def _run_process(
        self,
        materialized: MaterializedTask,
        task_index: int,
        task_count: int,
        callbacks: PipelineCallbacks,
        log: TextIO,
    ) -> int:
        environment = self._subprocess_environment()
        creationflags = 0
        if os.name == "nt" and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        self.current_process = subprocess.Popen(
            list(materialized.command),
            cwd=self.root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
        tracker = TaskProgress(self.root, materialized.task, materialized.case)
        assert self.current_process.stdout is not None
        try:
            for raw_line in self.current_process.stdout:
                line = raw_line.rstrip("\r\n")
                print(line, file=log)
                progress = tracker.feed(line)
                if progress is not None:
                    callbacks.on_task_progress(task_index, progress)
                    callbacks.on_pipeline_progress(
                        (task_index + progress) / max(1, task_count)
                    )
                callbacks.on_log(line)
            return int(self.current_process.wait())
        finally:
            self.current_process = None


def _load_completed_tasks(path: Path, plan: PipelinePlan) -> set[int]:
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if data.get("schema_version") != PIPELINE_STATE_SCHEMA:
        return set()
    if data.get("pipeline_fingerprint") != plan.fingerprint:
        return set()
    return {int(value) for value in data.get("completed_tasks", ())}


def _save_state(
    path: Path,
    plan: PipelinePlan,
    completed: set[int],
    current_task: int | None,
) -> None:
    _atomic_write_json(
        path,
        {
            "schema_version": PIPELINE_STATE_SCHEMA,
            "pipeline_id": plan.pipeline_id,
            "pipeline_fingerprint": plan.fingerprint,
            "completed_tasks": sorted(completed),
            "current_task": current_task,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        },
    )
