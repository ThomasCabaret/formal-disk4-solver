from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import signal
import sqlite3
import subprocess
import sys
import threading
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, TextIO

from formal_disk4.orchestration.catalog import CaseCatalog, CaseDefinition, SUPPORTED_STAGES
from formal_disk4.pipeline.checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    search_fingerprint,
)


PIPELINE_SCHEMA = "formal-disk4-pipeline-v1"
PIPELINE_STATE_SCHEMA = "formal-disk4-pipeline-state-v2"
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


def _resolve_project_path(root: Path, raw: str | Path) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else root / path


def _file_fingerprint(path: Path) -> str:
    stat = path.stat()
    payload = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _search_checkpoint_completed(root: Path, config: Mapping[str, Any]) -> bool:
    output = _resolve_project_path(root, str(config["output"]["directory"]))
    checkpoint = config.get("checkpoint", {})
    path = output / str(checkpoint.get("file", "checkpoint.sqlite3"))
    if not path.exists():
        return False
    try:
        connection = sqlite3.connect(str(path), timeout=1.0)
        try:
            row = connection.execute(
                "SELECT schema_version, config_fingerprint, completed "
                "FROM search_checkpoint WHERE singleton = 1"
            ).fetchone()
            survivor_row = connection.execute("SELECT COUNT(*) FROM survivors").fetchone()
        finally:
            connection.close()
    except (sqlite3.Error, OSError):
        return False
    if row is None:
        return False
    schema_version, fingerprint, completed = row
    if not (
        int(schema_version) == CHECKPOINT_SCHEMA_VERSION
        and str(fingerprint) == search_fingerprint(config)
        and bool(completed)
    ):
        return False
    candidates_path = output / str(
        config.get("output", {}).get("candidates_file", "candidates.jsonl")
    )
    if not candidates_path.exists():
        return False
    expected = int(survivor_row[0]) if survivor_row is not None else 0
    try:
        return _count_jsonl(candidates_path) == expected
    except OSError:
        return False


def _geometry_checkpoint_completed(root: Path, config: Mapping[str, Any]) -> bool:
    output = _resolve_project_path(root, str(config["output"]["directory"]))
    checkpoint = config.get("checkpoint", {})
    path = output / str(
        config.get("output", {}).get(
            "checkpoint_file", checkpoint.get("file", "geometry_checkpoint.json")
        )
    )
    if not path.exists():
        return False
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(state, dict) or not bool(state.get("completed", False)):
        return False
    solutions_path = output / str(
        config.get("output", {}).get("solutions_file", "geometric_solutions.jsonl")
    )
    if not solutions_path.exists():
        return False
    input_path = _resolve_project_path(
        root, str(config.get("input", {}).get("candidates_file", ""))
    )
    if not input_path.exists():
        return False
    if str(state.get("input_path", "")) != str(input_path.resolve()):
        return False
    try:
        return str(state.get("input_fingerprint", "")) == _file_fingerprint(input_path)
    except OSError:
        return False


def _process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            process_query_limited_information = 0x1000
            still_active = 259
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel32.OpenProcess(
                process_query_limited_information, False, int(pid)
            )
            if not handle:
                return False
            try:
                exit_code = wintypes.DWORD()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return int(exit_code.value) == still_active
            finally:
                kernel32.CloseHandle(handle)
        except (AttributeError, OSError):
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass
class _TaskLease:
    path: Path
    token: str
    task: PipelineTask

    @classmethod
    def acquire(cls, root: Path, materialized: "MaterializedTask") -> "_TaskLease":
        config = json.loads(materialized.config_path.read_text(encoding="utf-8"))
        output = _resolve_project_path(root, str(config["output"]["directory"]))
        output.mkdir(parents=True, exist_ok=True)
        path = output / f".active-{materialized.task.stage}-pipeline-task.json"
        token = secrets.token_hex(12)
        payload = {
            "schema_version": "formal-disk4-active-task-v1",
            "token": token,
            "owner_pid": os.getpid(),
            "child_pid": None,
            "case_id": materialized.task.case_id,
            "stage": materialized.task.stage,
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }
        for _attempt in range(3):
            try:
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    existing = {}
                active_pid = int(
                    existing.get("child_pid") or existing.get("owner_pid") or 0
                )
                if _process_is_alive(active_pid):
                    raise RuntimeError(
                        f"Another {materialized.task.stage} process is still active for "
                        f"{materialized.task.case_id} (pid={active_pid}). Stop that "
                        "process before resuming or restarting this case."
                    )
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                continue
            else:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, indent=2)
                    handle.write("\n")
                return cls(path, token, materialized.task)
        raise RuntimeError(f"Cannot acquire active-task lease: {path}")

    def attach_child(self, pid: int) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if data.get("token") != self.token:
            return
        data["child_pid"] = int(pid)
        _atomic_write_json(self.path, data)

    def release(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError):
            data = {}
        if data.get("token") == self.token:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


def task_checkpoint_completed(root: Path, materialized: "MaterializedTask") -> bool:
    """Return true only when the stage's own compatible checkpoint is complete.

    Pipeline state is deliberately not authoritative: it can survive a restarted
    task or a GUI crash. Search and geometry checkpoints are the source of truth.
    """

    if materialized.task.stage == "visualize":
        return False
    # CLI arguments may change search semantics or the geometry budget. Let the
    # stage runner interpret them instead of pre-emptively skipping the task.
    if materialized.task.arguments:
        return False
    try:
        config = json.loads(materialized.config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(config, dict):
        return False
    if materialized.task.stage == "search":
        return _search_checkpoint_completed(root, config)
    if materialized.task.stage == "geometry":
        return _geometry_checkpoint_completed(root, config)
    return False


def materialize_task(
    root: Path,
    case: CaseDefinition,
    task: PipelineTask,
    generated_config_directory: Path,
    task_index: int,
    *,
    restart_checkpoint: bool = False,
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
    effective_arguments = list(task.arguments)
    if (
        restart_checkpoint
        and task.stage in {"search", "geometry"}
        and "--restart" not in effective_arguments
    ):
        effective_arguments.append("--restart")
    command = (
        *_python_command(root),
        "-m",
        "formal_disk4",
        subcommand,
        "--config",
        str(config_path),
        *effective_arguments,
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
        self.interrupt_current = threading.Event()
        self.current_process: subprocess.Popen[str] | None = None
        self.detached_visualizers: set[subprocess.Popen[str]] = set()
        self._detached_lock = threading.Lock()
        self._process_lock = threading.Lock()

    def request_stop_after_current(self) -> None:
        self.stop_after_current.set()

    def request_interrupt_current(self) -> None:
        """Interrupt the active solver so it can save its own checkpoint."""

        self.interrupt_current.set()
        with self._process_lock:
            process = self.current_process
        if process is None or process.poll() is not None:
            return
        try:
            if os.name == "nt" and hasattr(signal, "CTRL_BREAK_EVENT"):
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                process.send_signal(signal.SIGINT)
        except (OSError, ValueError):
            try:
                process.terminate()
            except OSError:
                return

        def escalate() -> None:
            try:
                process.wait(timeout=30.0)
            except subprocess.TimeoutExpired:
                try:
                    process.terminate()
                    process.wait(timeout=5.0)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        process.kill()
                    except OSError:
                        pass

        threading.Thread(target=escalate, daemon=True).start()

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
        # Pipeline state is useful for diagnostics, but it is not authoritative.
        # A restarted task or an interrupted GUI can make its completed list stale.
        completed: set[int] = set()
        if not resume and state_path.exists():
            state_path.unlink()
        log_path = run_root / (
            "pipeline_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".log"
        )
        self.stop_after_current.clear()
        self.interrupt_current.clear()

        with log_path.open("a", encoding="utf-8", buffering=1) as log:
            callbacks.on_log(f"[PIPELINE] {plan.name} ({len(plan.tasks)} tasks)")
            callbacks.on_log(f"[LOG] {log_path}")
            if resume:
                callbacks.on_log(
                    "[RESUME MODE] Search and geometry checkpoints are authoritative; "
                    "stale pipeline completion flags are ignored."
                )
            else:
                callbacks.on_log(
                    "[FRESH RUN] Pipeline state is cleared and search/geometry "
                    "checkpoints will be restarted."
                )
            for index, task in enumerate(plan.tasks):
                if self.interrupt_current.is_set():
                    callbacks.on_log(
                        "[PIPELINE PAUSED] Stop requested before the next task."
                    )
                    _save_state(state_path, plan, completed, index)
                    return 0

                case = self.catalog.get(task.case_id)
                callbacks.on_task_start(index, task, case)
                materialized = materialize_task(
                    self.root,
                    case,
                    task,
                    generated,
                    index,
                    restart_checkpoint=not resume,
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

                if resume and task_checkpoint_completed(self.root, materialized):
                    callbacks.on_log(
                        f"[SKIP CHECKPOINT COMPLETE] {index + 1}/{len(plan.tasks)} "
                        f"{task.stage} {task.case_id}"
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

                if self.interrupt_current.is_set():
                    callbacks.on_log(
                        "[PIPELINE PAUSED] Current task was interrupted; its solver "
                        "checkpoint remains resumable."
                    )
                    _save_state(state_path, plan, completed, index)
                    return 0
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
        lease = _TaskLease.acquire(self.root, materialized)
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
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
            lease.attach_child(process.pid)
            with self._process_lock:
                self.current_process = process
            # The close request can arrive during Popen. Deliver it once the child is known.
            if self.interrupt_current.is_set() and process.poll() is None:
                self.request_interrupt_current()
            tracker = TaskProgress(self.root, materialized.task, materialized.case)
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.rstrip("\r\n")
                print(line, file=log)
                progress = tracker.feed(line)
                if progress is not None:
                    callbacks.on_task_progress(task_index, progress)
                    callbacks.on_pipeline_progress(
                        (task_index + progress) / max(1, task_count)
                    )
                callbacks.on_log(line)
            return int(process.wait())
        finally:
            if process is not None:
                with self._process_lock:
                    if self.current_process is process:
                        self.current_process = None
            lease.release()


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
