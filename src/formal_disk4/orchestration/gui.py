from __future__ import annotations

import os
import queue
import shlex
import threading
import time
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from formal_disk4.orchestration.catalog import CaseCatalog, CaseDefinition
from formal_disk4.orchestration.pipeline import (
    PipelineCallbacks,
    PipelineExecutor,
    PipelinePlan,
    PipelineTask,
)
from formal_disk4.orchestration.status import PipelineStatusReader


class PipelineApp:
    def __init__(self, root: tk.Tk, project_root: Path):
        self.root = root
        self.project_root = project_root.resolve()
        self.catalog = CaseCatalog.load(self.project_root)
        self.executor = PipelineExecutor(self.project_root, self.catalog)
        self.status_reader = PipelineStatusReader(self.project_root)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.pipeline_tasks: list[PipelineTask] = []
        self.selected_cases: set[str] = set()
        self.running = False
        self.current_plan_path: Path | None = None
        self.log_line_count = 0
        self.closing = False
        self.last_status_refresh = 0.0

        self.root.title("Formal Disk4 Pipeline Builder")
        self.root.geometry("1480x900")
        self.root.minsize(1120, 720)
        self._build_ui()
        self._populate_catalog()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._poll_events)

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        main = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        main.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        left = ttk.Frame(main, padding=6)
        right = ttk.Frame(main, padding=6)
        main.add(left, weight=1)
        main.add(right, weight=2)

        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)
        ttk.Label(left, text="Available cases", font=("TkDefaultFont", 11, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.filter_var = tk.StringVar()
        filter_row = ttk.Frame(left)
        filter_row.grid(row=1, column=0, sticky="ew", pady=(6, 6))
        filter_row.columnconfigure(0, weight=1)
        filter_entry = ttk.Entry(filter_row, textvariable=self.filter_var)
        filter_entry.grid(row=0, column=0, sticky="ew")
        filter_entry.bind("<KeyRelease>", lambda _event: self._populate_catalog())
        ttk.Button(filter_row, text="Select all", command=self._select_all_visible).grid(
            row=0, column=1, padx=(6, 0)
        )
        ttk.Button(filter_row, text="Clear", command=self._clear_selection).grid(
            row=0, column=2, padx=(6, 0)
        )

        self.case_tree = ttk.Treeview(
            left,
            columns=("mark", "map", "description"),
            show="tree headings",
            selectmode="browse",
        )
        self.case_tree.heading("#0", text="Case")
        self.case_tree.heading("mark", text="Use")
        self.case_tree.heading("map", text="Map")
        self.case_tree.heading("description", text="Description")
        self.case_tree.column("#0", width=230, stretch=False)
        self.case_tree.column("mark", width=48, anchor="center", stretch=False)
        self.case_tree.column("map", width=210, stretch=False)
        self.case_tree.column("description", width=360, stretch=True)
        case_scroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.case_tree.yview)
        self.case_tree.configure(yscrollcommand=case_scroll.set)
        self.case_tree.grid(row=2, column=0, sticky="nsew")
        case_scroll.grid(row=2, column=1, sticky="ns")
        self.case_tree.bind("<Button-1>", self._toggle_tree_item)
        self.case_tree.bind("<space>", lambda _event: self._toggle_focused_item())

        add_box = ttk.LabelFrame(left, text="Add tasks", padding=8)
        add_box.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        add_box.columnconfigure(1, weight=1)
        ttk.Label(add_box, text="Stage").grid(row=0, column=0, sticky="w")
        self.stage_var = tk.StringVar(value="search")
        stage_combo = ttk.Combobox(
            add_box,
            textvariable=self.stage_var,
            values=("search", "geometry", "visualize"),
            state="readonly",
            width=14,
        )
        stage_combo.grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(add_box, text="Extra arguments").grid(
            row=1, column=0, sticky="w", pady=(6, 0)
        )
        self.arguments_var = tk.StringVar()
        ttk.Entry(add_box, textvariable=self.arguments_var).grid(
            row=1, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=(6, 0)
        )
        ttk.Button(add_box, text="Add selected", command=self._add_selected_stage).grid(
            row=2, column=0, pady=(8, 0), sticky="ew"
        )
        ttk.Button(
            add_box,
            text="Add search + geometry",
            command=self._add_selected_search_geometry,
        ).grid(row=2, column=1, padx=(8, 0), pady=(8, 0), sticky="ew")

        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        ttk.Label(right, text="Pipeline", font=("TkDefaultFont", 11, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.pipeline_tree = ttk.Treeview(
            right,
            columns=(
                "order",
                "stage",
                "case",
                "state",
                "formal",
                "geometry",
                "certain",
                "solved",
                "no_solution",
                "arguments",
            ),
            show="headings",
            selectmode="extended",
        )
        for column, title, width in (
            ("order", "#", 38),
            ("stage", "Stage", 76),
            ("case", "Case", 225),
            ("state", "State", 105),
            ("formal", "Formal", 64),
            ("geometry", "Geometry", 70),
            ("certain", "Certain reject", 92),
            ("solved", "Solution", 66),
            ("no_solution", "No solution", 82),
            ("arguments", "Arguments", 160),
        ):
            self.pipeline_tree.heading(column, text=title)
            self.pipeline_tree.column(
                column,
                width=width,
                anchor=("e" if column in {"formal", "geometry", "certain", "solved", "no_solution"} else "w"),
                stretch=(column in {"case", "arguments"}),
            )
        pipe_scroll = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.pipeline_tree.yview)
        pipe_scroll_x = ttk.Scrollbar(right, orient=tk.HORIZONTAL, command=self.pipeline_tree.xview)
        self.pipeline_tree.configure(
            yscrollcommand=pipe_scroll.set, xscrollcommand=pipe_scroll_x.set
        )
        self.pipeline_tree.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        pipe_scroll.grid(row=1, column=1, sticky="ns", pady=(6, 0))
        pipe_scroll_x.grid(row=2, column=0, sticky="ew")

        controls = ttk.Frame(right)
        controls.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        for index in range(8):
            controls.columnconfigure(index, weight=1)
        ttk.Button(controls, text="Up", command=lambda: self._move_tasks(-1)).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Button(controls, text="Down", command=lambda: self._move_tasks(1)).grid(
            row=0, column=1, padx=(4, 0), sticky="ew"
        )
        ttk.Button(controls, text="Remove", command=self._remove_tasks).grid(
            row=0, column=2, padx=(4, 0), sticky="ew"
        )
        ttk.Button(controls, text="Clear", command=self._clear_pipeline).grid(
            row=0, column=3, padx=(4, 0), sticky="ew"
        )
        ttk.Button(controls, text="Load", command=self._load_pipeline).grid(
            row=0, column=4, padx=(12, 0), sticky="ew"
        )
        ttk.Button(controls, text="Save", command=self._save_pipeline).grid(
            row=0, column=5, padx=(4, 0), sticky="ew"
        )
        self.run_button = ttk.Button(controls, text="Run", command=self._run_pipeline)
        self.run_button.grid(row=0, column=6, padx=(12, 0), sticky="ew")
        self.stop_button = ttk.Button(
            controls,
            text="Stop after task",
            command=self._stop_after_task,
            state=tk.DISABLED,
        )
        self.stop_button.grid(row=0, column=7, padx=(4, 0), sticky="ew")
        ttk.Button(
            controls,
            text="Rejection statistics...",
            command=self._show_rejection_statistics,
        ).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        self.resume_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            controls,
            text="Resume existing work/checkpoints",
            variable=self.resume_var,
        ).grid(row=1, column=4, columnspan=4, sticky="e", pady=(6, 0))

        progress_box = ttk.LabelFrame(right, text="Progress", padding=8)
        progress_box.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        progress_box.columnconfigure(1, weight=1)
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(progress_box, textvariable=self.status_var).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(progress_box, text="Current task").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.task_progress = ttk.Progressbar(progress_box, mode="determinate", maximum=100)
        self.task_progress.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))
        ttk.Label(progress_box, text="Pipeline").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.pipeline_progress = ttk.Progressbar(progress_box, mode="determinate", maximum=100)
        self.pipeline_progress.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))

        console_box = ttk.LabelFrame(right, text="Console", padding=6)
        ttk.Label(
            right,
            text="Geometry counts are distinct formal candidates; ~ marks legacy approximate counters.",
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(5, 0))

        console_box.grid(row=6, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        right.rowconfigure(6, weight=1)
        console_box.columnconfigure(0, weight=1)
        console_box.rowconfigure(0, weight=1)
        self.console = tk.Text(console_box, height=13, wrap="none", state=tk.DISABLED)
        console_scroll_y = ttk.Scrollbar(console_box, orient=tk.VERTICAL, command=self.console.yview)
        console_scroll_x = ttk.Scrollbar(console_box, orient=tk.HORIZONTAL, command=self.console.xview)
        self.console.configure(
            yscrollcommand=console_scroll_y.set, xscrollcommand=console_scroll_x.set
        )
        self.console.grid(row=0, column=0, sticky="nsew")
        console_scroll_y.grid(row=0, column=1, sticky="ns")
        console_scroll_x.grid(row=1, column=0, sticky="ew")

    def _populate_catalog(self) -> None:
        query = self.filter_var.get().strip().casefold() if hasattr(self, "filter_var") else ""
        open_groups = {
            self.case_tree.item(item, "text")
            for item in self.case_tree.get_children("")
            if self.case_tree.item(item, "open")
        }
        self.case_tree.delete(*self.case_tree.get_children(""))
        for group in self.catalog.groups():
            cases = [
                case
                for case in self.catalog.cases_in_group(group)
                if not query
                or query in case.case_id.casefold()
                or query in case.label.casefold()
                or query in case.description.casefold()
                or query in case.map_name.casefold()
            ]
            if not cases:
                continue
            group_id = self.case_tree.insert(
                "", "end", text=group, values=("", "", ""), open=(not query or group in open_groups)
            )
            for case in cases:
                mark = "[x]" if case.case_id in self.selected_cases else "[ ]"
                if case.structurally_impossible:
                    mark = "[-]"
                self.case_tree.insert(
                    group_id,
                    "end",
                    iid="case:" + case.case_id,
                    text=case.label,
                    values=(mark, case.map_name, case.description),
                )

    def _toggle_tree_item(self, event: tk.Event) -> None:
        item = self.case_tree.identify_row(event.y)
        if not item:
            return
        self.root.after_idle(lambda: self._toggle_item(item))

    def _toggle_focused_item(self) -> None:
        item = self.case_tree.focus()
        if item:
            self._toggle_item(item)

    def _toggle_item(self, item: str) -> None:
        if item.startswith("case:"):
            case_id = item[5:]
            case = self.catalog.get(case_id)
            if case.structurally_impossible:
                return
            if case_id in self.selected_cases:
                self.selected_cases.remove(case_id)
            else:
                self.selected_cases.add(case_id)
        else:
            child_ids = [child[5:] for child in self.case_tree.get_children(item)]
            selectable = [
                case_id
                for case_id in child_ids
                if not self.catalog.get(case_id).structurally_impossible
            ]
            if selectable and all(case_id in self.selected_cases for case_id in selectable):
                self.selected_cases.difference_update(selectable)
            else:
                self.selected_cases.update(selectable)
        self._populate_catalog()

    def _select_all_visible(self) -> None:
        for group in self.case_tree.get_children(""):
            for item in self.case_tree.get_children(group):
                case_id = item[5:]
                if not self.catalog.get(case_id).structurally_impossible:
                    self.selected_cases.add(case_id)
        self._populate_catalog()

    def _clear_selection(self) -> None:
        self.selected_cases.clear()
        self._populate_catalog()

    def _parse_arguments(self) -> tuple[str, ...]:
        text = self.arguments_var.get().strip()
        if not text:
            return ()
        return tuple(shlex.split(text, posix=(os.name != "nt")))

    def _ordered_selected_cases(self) -> list[CaseDefinition]:
        return [case for case in self.catalog.cases if case.case_id in self.selected_cases]

    def _add_selected_stage(self) -> None:
        try:
            arguments = self._parse_arguments()
        except ValueError as exc:
            messagebox.showerror("Invalid arguments", str(exc), parent=self.root)
            return
        stage = self.stage_var.get()
        cases = self._ordered_selected_cases()
        if not cases:
            messagebox.showinfo("No cases", "Select at least one case.", parent=self.root)
            return
        self.pipeline_tasks.extend(PipelineTask(case.case_id, stage, arguments) for case in cases)
        self._refresh_pipeline_tree()

    def _add_selected_search_geometry(self) -> None:
        try:
            arguments = self._parse_arguments()
        except ValueError as exc:
            messagebox.showerror("Invalid arguments", str(exc), parent=self.root)
            return
        cases = self._ordered_selected_cases()
        if not cases:
            messagebox.showinfo("No cases", "Select at least one case.", parent=self.root)
            return
        for case in cases:
            self.pipeline_tasks.append(PipelineTask(case.case_id, "search", arguments))
        geometry_args = tuple(
            argument for argument in arguments if argument in {"--restart", "--no-resume"}
        )
        for case in cases:
            self.pipeline_tasks.append(PipelineTask(case.case_id, "geometry", geometry_args))
        self._refresh_pipeline_tree()

    def _refresh_pipeline_tree(self) -> None:
        selected = tuple(self.pipeline_tree.selection())
        self.pipeline_tree.delete(*self.pipeline_tree.get_children(""))
        for index, task in enumerate(self.pipeline_tasks):
            self.pipeline_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    index + 1,
                    task.stage,
                    task.case_id,
                    "reading",
                    "0",
                    "0",
                    "0",
                    "0",
                    "0",
                    " ".join(task.arguments),
                ),
            )
        valid = [item for item in selected if self.pipeline_tree.exists(item)]
        if valid:
            self.pipeline_tree.selection_set(*valid)
        self._refresh_pipeline_statuses(force=True)

    def _refresh_pipeline_statuses(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self.last_status_refresh < 1.0:
            return
        self.last_status_refresh = now
        by_case = {}
        for index, task in enumerate(self.pipeline_tasks):
            item = str(index)
            if not self.pipeline_tree.exists(item):
                continue
            try:
                status = by_case.setdefault(
                    task.case_id, self.status_reader.read(self.catalog.get(task.case_id))
                )
                stage_state = (
                    status.search_state
                    if task.stage == "search"
                    else status.geometry_state
                    if task.stage == "geometry"
                    else ("ready" if status.solutions_found else "no solution")
                )
                prefix = "" if status.exact_geometry_counts else "~"
                values = (
                    index + 1,
                    task.stage,
                    task.case_id,
                    stage_state,
                    status.formal_candidates,
                    f"{prefix}{status.geometry_considered}",
                    f"{prefix}{status.rejected_certain}",
                    f"{prefix}{status.solutions_found}",
                    f"{prefix}{status.no_solution_found}",
                    " ".join(task.arguments),
                )
            except Exception:
                values = (
                    index + 1,
                    task.stage,
                    task.case_id,
                    "status error",
                    "?",
                    "?",
                    "?",
                    "?",
                    "?",
                    " ".join(task.arguments),
                )
            self.pipeline_tree.item(item, values=values)

    def _selected_pipeline_indices(self) -> list[int]:
        return sorted(int(item) for item in self.pipeline_tree.selection())

    def _show_rejection_statistics(self) -> None:
        selected = self._selected_pipeline_indices()
        if not selected:
            messagebox.showinfo(
                "No pipeline task",
                "Select a pipeline row whose search statistics should be shown.",
                parent=self.root,
            )
            return
        case = self.catalog.get(self.pipeline_tasks[selected[0]].case_id)

        window = tk.Toplevel(self.root)
        window.title(f"Search rejection statistics - {case.label}")
        window.geometry("1180x680")
        window.minsize(850, 480)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(2, weight=1)

        header_var = tk.StringVar()
        ttk.Label(
            window,
            textvariable=header_var,
            font=("TkDefaultFont", 10, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 2))
        ttk.Label(
            window,
            text=(
                "DFS pruning rows count rejected nodes/subtrees, not rejected leaf "
                "candidates; rows without a denominator intentionally have no rate."
            ),
            wraplength=1120,
        ).grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))

        notebook = ttk.Notebook(window)
        notebook.grid(row=2, column=0, sticky="nsew", padx=10)

        stage_frame = ttk.Frame(notebook)
        raw_frame = ttk.Frame(notebook)
        timing_frame = ttk.Frame(notebook)
        notebook.add(stage_frame, text="By rejection stage")
        notebook.add(raw_frame, text="Raw counters")
        notebook.add(timing_frame, text="Timings")

        def make_tree(
            frame: ttk.Frame,
            columns: tuple[tuple[str, str, int], ...],
        ) -> ttk.Treeview:
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(0, weight=1)
            tree = ttk.Treeview(
                frame,
                columns=tuple(name for name, _title, _width in columns),
                show="headings",
            )
            numeric = {"examined", "result", "rate", "value", "seconds", "share"}
            for name, title, width in columns:
                tree.heading(name, text=title)
                tree.column(
                    name,
                    width=width,
                    anchor="e" if name in numeric else "w",
                    stretch=name in {"stage", "details", "counter", "timing"},
                )
            scroll_y = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
            scroll_x = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=tree.xview)
            tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
            tree.grid(row=0, column=0, sticky="nsew")
            scroll_y.grid(row=0, column=1, sticky="ns")
            scroll_x.grid(row=1, column=0, sticky="ew")
            return tree

        stage_tree = make_tree(
            stage_frame,
            (
                ("stage", "Stage / filter", 300),
                ("examined", "Examined", 100),
                ("result", "Rejected / result", 120),
                ("rate", "Rate", 80),
                ("details", "Fine reasons and related counts", 480),
            ),
        )
        raw_tree = make_tree(
            raw_frame,
            (("counter", "Counter", 620), ("value", "Value", 180)),
        )
        timing_tree = make_tree(
            timing_frame,
            (
                ("timing", "Timed section", 560),
                ("seconds", "Seconds", 160),
                ("share", "Share of elapsed", 160),
            ),
        )

        def pretty(name: str) -> str:
            return name.replace("_", " ")

        def integer(value: int | None) -> str:
            return "-" if value is None else f"{value:,}"

        def refresh() -> None:
            diagnostics = self.status_reader.read_search_diagnostics(case)
            for tree in (stage_tree, raw_tree, timing_tree):
                tree.delete(*tree.get_children(""))
            if diagnostics is None:
                header_var.set(f"{case.label}: no saved search statistics yet")
                return
            state = "complete" if diagnostics.completed else "running or paused"
            updated = diagnostics.updated_utc or "unknown time"
            header_var.set(
                f"{case.label} - {state} - {diagnostics.source}, updated {updated} - "
                f"elapsed {diagnostics.elapsed_seconds:,.1f} s"
            )
            for stage in diagnostics.stages:
                detail_text = "; ".join(
                    f"{pretty(name)}={amount:,}" for name, amount in stage.details
                )
                stage_tree.insert(
                    "",
                    "end",
                    values=(
                        stage.label,
                        integer(stage.examined),
                        integer(stage.rejected_or_result),
                        (
                            "-"
                            if stage.rate_percent is None
                            else f"{stage.rate_percent:.2f}%"
                        ),
                        detail_text,
                    ),
                )
            for name, amount in diagnostics.counters:
                raw_tree.insert("", "end", values=(pretty(name), integer(amount)))
            elapsed = diagnostics.elapsed_seconds
            for name, seconds in diagnostics.timings:
                share = 100.0 * seconds / elapsed if elapsed else 0.0
                timing_tree.insert(
                    "",
                    "end",
                    values=(pretty(name), f"{seconds:,.3f}", f"{share:.2f}%"),
                )

        footer = ttk.Frame(window)
        footer.grid(row=3, column=0, sticky="ew", padx=10, pady=10)
        ttk.Button(footer, text="Refresh now", command=refresh).pack(side=tk.LEFT)
        ttk.Label(
            footer,
            text="Automatically refreshed every 5 s; active checkpoint data may lag by about 60 s.",
        ).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(footer, text="Close", command=window.destroy).pack(side=tk.RIGHT)

        def auto_refresh() -> None:
            if not window.winfo_exists():
                return
            refresh()
            window.after(5000, auto_refresh)

        refresh()
        window.after(5000, auto_refresh)

    def _move_tasks(self, direction: int) -> None:
        selected = self._selected_pipeline_indices()
        if not selected:
            return
        if direction < 0:
            for index in selected:
                if index > 0 and index - 1 not in selected:
                    self.pipeline_tasks[index - 1], self.pipeline_tasks[index] = (
                        self.pipeline_tasks[index],
                        self.pipeline_tasks[index - 1],
                    )
            new_selected = [max(0, index - 1) for index in selected]
        else:
            for index in reversed(selected):
                if index < len(self.pipeline_tasks) - 1 and index + 1 not in selected:
                    self.pipeline_tasks[index + 1], self.pipeline_tasks[index] = (
                        self.pipeline_tasks[index],
                        self.pipeline_tasks[index + 1],
                    )
            new_selected = [min(len(self.pipeline_tasks) - 1, index + 1) for index in selected]
        self._refresh_pipeline_tree()
        self.pipeline_tree.selection_set(*(str(index) for index in new_selected))

    def _remove_tasks(self) -> None:
        for index in reversed(self._selected_pipeline_indices()):
            del self.pipeline_tasks[index]
        self._refresh_pipeline_tree()

    def _clear_pipeline(self) -> None:
        self.pipeline_tasks.clear()
        self.current_plan_path = None
        self._refresh_pipeline_tree()

    def _make_plan(self) -> PipelinePlan:
        if not self.pipeline_tasks:
            raise ValueError("The pipeline is empty.")
        if self.current_plan_path is not None:
            pipeline_id = self.current_plan_path.stem
            name = self.current_plan_path.stem
        else:
            digest_source = "\n".join(
                f"{task.stage}:{task.case_id}:{' '.join(task.arguments)}"
                for task in self.pipeline_tasks
            )
            import hashlib

            pipeline_id = "gui-" + hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:12]
            name = "GUI pipeline"
        return PipelinePlan(pipeline_id, name, tuple(self.pipeline_tasks), self.current_plan_path)

    def _save_pipeline(self) -> None:
        try:
            plan = self._make_plan()
        except ValueError as exc:
            messagebox.showinfo("Empty pipeline", str(exc), parent=self.root)
            return
        initial = self.project_root / "config" / "pipelines"
        initial.mkdir(parents=True, exist_ok=True)
        path = filedialog.asksaveasfilename(
            parent=self.root,
            initialdir=initial,
            defaultextension=".json",
            filetypes=(("Pipeline JSON", "*.json"), ("All files", "*.*")),
        )
        if not path:
            return
        target = Path(path)
        plan = PipelinePlan(target.stem, target.stem, plan.tasks, target)
        plan.save(target)
        self.current_plan_path = target
        self.status_var.set(f"Saved {target.name}")

    def _load_pipeline(self) -> None:
        initial = self.project_root / "config" / "pipelines"
        initial.mkdir(parents=True, exist_ok=True)
        path = filedialog.askopenfilename(
            parent=self.root,
            initialdir=initial,
            filetypes=(("Pipeline JSON", "*.json"), ("All files", "*.*")),
        )
        if not path:
            return
        try:
            plan = PipelinePlan.load(Path(path))
            for task in plan.tasks:
                self.catalog.get(task.case_id)
        except Exception as exc:
            messagebox.showerror("Cannot load pipeline", str(exc), parent=self.root)
            return
        self.pipeline_tasks = list(plan.tasks)
        self.current_plan_path = Path(path)
        self._refresh_pipeline_tree()
        self.status_var.set(f"Loaded {Path(path).name}")

    def _run_pipeline(self) -> None:
        if self.running:
            return
        try:
            plan = self._make_plan()
        except ValueError as exc:
            messagebox.showinfo("Empty pipeline", str(exc), parent=self.root)
            return
        self.running = True
        self.run_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        self.task_progress.configure(value=0, mode="determinate")
        self.pipeline_progress.configure(value=0)
        self.status_var.set("Starting pipeline")
        self._append_console("")
        thread = threading.Thread(
            target=self._run_worker,
            args=(plan, bool(self.resume_var.get())),
            daemon=True,
        )
        thread.start()

    def _run_worker(self, plan: PipelinePlan, resume: bool) -> None:
        callbacks = PipelineCallbacks(
            on_log=lambda line: self.events.put(("log", line)),
            on_task_start=lambda index, task, case: self.events.put(
                ("task_start", (index, task, case))
            ),
            on_task_progress=lambda index, progress: self.events.put(
                ("task_progress", (index, progress))
            ),
            on_task_end=lambda index, task, returncode: self.events.put(
                ("task_end", (index, task, returncode))
            ),
            on_pipeline_progress=lambda progress: self.events.put(
                ("pipeline_progress", progress)
            ),
        )
        try:
            returncode = self.executor.run(plan, callbacks, resume=resume)
            self.events.put(("finished", returncode))
        except Exception:
            self.events.put(("error", traceback.format_exc()))

    def _stop_after_task(self) -> None:
        if self.running:
            self.executor.request_stop_after_current()
            self.status_var.set("Stop requested after current task")
            self.stop_button.configure(state=tk.DISABLED)

    def _on_close(self) -> None:
        if not self.running:
            self.root.destroy()
            return
        if self.closing:
            return
        should_stop = messagebox.askyesno(
            "Stop running task",
            "A search or geometry task is still running. Stop it now, save its "
            "checkpoint, then close the pipeline GUI?",
            parent=self.root,
        )
        if not should_stop:
            return
        self.closing = True
        self.run_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.DISABLED)
        self.status_var.set("Stopping current task and saving its checkpoint")
        self._append_console(
            "[GUI CLOSE] Interrupting the current solver and waiting for its "
            "checkpoint save."
        )
        self.executor.request_interrupt_current()

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "log":
                    line = str(payload)
                    self._append_console(line)
                    if line.startswith("[WORD CASE DEFERRED]"):
                        self.status_var.set(
                            "Pathological word case deferred; search continues"
                        )
                elif event == "task_start":
                    index, task, case = payload  # type: ignore[misc]
                    self.status_var.set(
                        f"Task {index + 1}/{len(self.pipeline_tasks)}: {task.stage} - {case.label}"
                    )
                    if task.stage == "visualize":
                        self.task_progress.configure(mode="indeterminate")
                        self.task_progress.start(12)
                    else:
                        self.task_progress.stop()
                        self.task_progress.configure(mode="determinate", value=0)
                elif event == "task_progress":
                    _index, progress = payload  # type: ignore[misc]
                    if progress is not None:
                        self.task_progress.stop()
                        self.task_progress.configure(mode="determinate", value=100 * float(progress))
                elif event == "task_end":
                    _index, _task, returncode = payload  # type: ignore[misc]
                    self.task_progress.stop()
                    if int(returncode) == 0:
                        self.task_progress.configure(mode="determinate", value=100)
                elif event == "pipeline_progress":
                    self.pipeline_progress.configure(value=100 * float(payload))
                elif event == "finished":
                    self._finish_run(int(payload))
                elif event == "error":
                    self._append_console(str(payload))
                    self._finish_run(8)
                    messagebox.showerror("Pipeline error", str(payload).splitlines()[-1], parent=self.root)
        except queue.Empty:
            pass
        self._refresh_pipeline_statuses()
        self.root.after(100, self._poll_events)

    def _finish_run(self, returncode: int) -> None:
        self.running = False
        self.run_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)
        self.task_progress.stop()
        if self.closing:
            self.root.after_idle(self.root.destroy)
            return
        if returncode == 0:
            self.status_var.set("Pipeline complete or paused cleanly")
        else:
            self.status_var.set(f"Pipeline stopped with exit code {returncode}")

    def _append_console(self, line: str) -> None:
        self.console.configure(state=tk.NORMAL)
        self.console.insert(tk.END, line + "\n")
        self.log_line_count += 1
        if self.log_line_count > 2500:
            self.console.delete("1.0", "501.0")
            self.log_line_count -= 500
        self.console.see(tk.END)
        self.console.configure(state=tk.DISABLED)


def project_root_from_cwd() -> Path:
    root = Path.cwd().resolve()
    if not (root / "config").exists() or not (root / "src" / "formal_disk4").exists():
        raise RuntimeError("Run the pipeline GUI from the formal_disk4_solver project root.")
    return root


def main() -> int:
    try:
        project_root = project_root_from_cwd()
    except Exception as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Formal Disk4", str(exc), parent=root)
        root.destroy()
        return 8
    root = tk.Tk()
    PipelineApp(root, project_root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
