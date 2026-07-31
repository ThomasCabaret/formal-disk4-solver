# Patch 1.7.2 - Pipeline resume semantics

This patch fixes the pipeline GUI resume control.

## Behavior

The checkbox is now labelled `Resume existing work/checkpoints`.

- Checked: pipeline-level completed tasks are skipped and existing search or geometry checkpoints are resumed.
- Unchecked: pipeline state is cleared and `--restart` is automatically passed to every search and geometry task.
- Visualization tasks are unchanged.

This means an incompatible formal checkpoint or an already-completed search can be restarted directly from the GUI by unchecking the option. Manual deletion of SQLite files is no longer required.

## Scope

The patch changes only the orchestration GUI, task materialization, documentation, tests and version metadata. Solver implementations, pruning, maps and checkpoint formats are unchanged.

## Validation

- 114 tests passed.
- 12 symmetry certification subtests passed.
- Tests verify automatic restart for search and geometry, no restart for visualization, and no duplicate `--restart` argument.
