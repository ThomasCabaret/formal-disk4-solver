# Formal Disk4 Solver 1.7.1

This differential patch targets version 1.7.0 and is limited to case-catalog cleanup and pipeline visualization behavior.

## Changes

- `double-cycle-6` is now expanded from the parameterized `double-cycle-N` family alongside sizes 3, 4 and 5.
- The legacy static `config/cases/double-cycle-6` manifest is disabled in the catalog so the patch works immediately after extraction. The optional cleanup script removes the obsolete directory from Git.
- Structurally impossible `double-cycle-wide-N` cases are removed from the declarative family catalog, predefined suites and legacy cyclic campaign interface.
- Pipeline `visualize` tasks launch independent GUI processes and no longer block later tasks.
- Multiple visualization tasks can remain open concurrently.
- Missing or empty geometric solution files are treated as a valid empty result.
- An empty viewer opens normally and displays `No geometric solution` rather than failing the pipeline.
- Each detached viewer writes its console output to `output/pipelines/<pipeline-id>/visualizer_logs/`.
- `cleanup_deprecated_1.7.1.bat` lists and stages conservative `git rm` operations for obsolete per-case wrappers and duplicate pizza configurations.

## Compatibility

- No formal-search, word-solver, geometry-solver or checkpoint format changes.
- Existing search and geometry checkpoints remain compatible.
- Existing pipeline JSON files remain compatible.
- Visualization tasks are considered complete by the pipeline once their GUI process has been launched.

## Validation

- 112 tests passed, plus 12 symmetry-certification subtests.
- Empty/missing solution source validation passed.
- Empty viewer initialization passed under a virtual display.
- Full test suite passed again after simulating every deletion performed by `cleanup_deprecated_1.7.1.bat`.
- Post-cleanup catalog contains 21 selectable cases, no structurally impossible cases, and resolves `double-cycle-6` from the parameterized family.
