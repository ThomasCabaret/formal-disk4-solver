# Formal Disk4 Solver 1.7.0 - Case catalog and pipeline GUI

## Scope

This release adds a lightweight orchestration layer. It does not modify the formal solver, the geometric solver, the word solver, pruning rules, map builders, or their checkpoint formats.

## Launch

From the project root on Windows:

```bat
run_pipeline_gui.bat
```

The GUI discovers cases dynamically, lets the user select cases, add ordered `search`, `geometry`, and `visualize` tasks, save/load a pipeline JSON file, and run or resume the pipeline.

## Case catalog

The GUI contains no hardcoded case list.

- Static cases are discovered from `config/cases/*/case.json`.
- Parameterized families are discovered from `config/case_families/*.json`.
- The new `cyclic-two-ring.json` descriptor expands the current cyclic families into concrete cases.

A family descriptor can set map templates, parameter values, output paths, base configurations, and nested stage-specific configuration overrides. This allows a future `rotation_2` campaign to be added as data with a distinct case id and output directory instead of adding another launcher script.

## Pipeline execution

Each task is materialized into a generated JSON configuration under:

```text
output/pipelines/<pipeline-id>/generated_configs/
```

The existing commands are then run in subprocesses:

```text
formal_disk4 run
formal_disk4 geometry
formal_disk4 visualize
```

The orchestration layer therefore reuses the existing solver behavior and checkpoints.

A separate pipeline state records completed tasks. If the current task is interrupted, it is not marked complete and its solver-level checkpoint remains responsible for resumption. The GUI can either resume the pipeline state or rerun all tasks.

## Progress and logs

- Formal search progress is parsed from the existing `overall~...%` metric.
- Geometry progress is estimated from remaining formal candidates and candidate-start messages.
- Visualization uses an indeterminate task progress bar.
- Full subprocess output is written to a timestamped pipeline log.
- The GUI keeps a bounded recent console view.

The `Stop after task` action does not terminate the current solver process. It finishes the current task and pauses before the next one, avoiding unsafe checkpoint interruption.

## Files

New orchestration code is isolated under:

```text
src/formal_disk4/orchestration/
```

The only existing runtime files changed are the package version and `pyproject.toml` entry points.

## Validation

- 109 unit tests pass.
- Catalog discovery, family expansion, unique ids, static visualizer aliases, generated search/geometry configurations, pipeline serialization, and progress parsing are covered.
- The GUI was instantiated successfully under a virtual display.
- A bounded end-to-end formal task was launched through `PipelineExecutor`, completed, logged, and checkpointed at the pipeline level.
