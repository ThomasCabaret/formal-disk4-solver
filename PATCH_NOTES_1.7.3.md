# Formal Disk4 Solver 1.7.3

This patch fixes pipeline checkpoint ownership and adds the size-4 half-turn campaigns.

## Pipeline resume and restart

- Pipeline-state completion flags are no longer trusted as proof that a solver task is complete.
- In resume mode, a search task is skipped only when its own SQLite checkpoint:
  - uses the current checkpoint schema;
  - has the same search-semantics fingerprint;
  - is explicitly marked complete.
- Geometry is skipped only when its own checkpoint is complete and still matches the current candidates file.
- Incomplete or absent stage checkpoints are always executed, even when an older pipeline state marked the task complete.
- Fresh mode still passes `--restart` to every search and geometry task and clears the pipeline state.
- Pipeline-state schema is bumped to v2 so stale 1.7.0-1.7.2 completion records are ignored.

## GUI process ownership

- Closing the pipeline GUI while a search or geometry task is running now asks to stop it.
- On confirmation, the GUI sends an interrupt to the child process and remains open until the solver has handled the interrupt and saved its checkpoint.
- The interrupted task is left resumable and is not marked complete by the pipeline.
- This prevents solver processes from continuing invisibly after the GUI closes and later overwriting a resumed or restarted checkpoint.
- Search and geometry tasks now hold a per-output active-process lease. A second GUI cannot start the same stage against the same output while the first child process is still alive. Stale lease files are removed automatically.

## New size-4 rotation_2 cases

The catalog now exposes four independent half-turn-equivariant cases:

- `double-cycle-4-rotation-2`
- `double-cycle-offset-4-rotation-2`
- `inner-cycle-boundary-points-4-rotation-2`
- `outer-cycle-center-points-4-rotation-2`

They use the existing size-4 maps, impose `rotation_2` on assignments and weak orders, and write to separate output directories. No profiling limit, node limit, placement limit, profile limit, or time limit is added.

## Validation

- 119 tests passed.
- 16 symmetry/campaign subtests passed.
- End-to-end checkpoint test:
  - fresh start;
  - interrupt after a real SQLite checkpoint;
  - resume from the saved counters;
  - fresh restart resetting the counters.
- All four `rotation_2` cases were started with a one-node bounded smoke test and accepted `rotation_2` on their maps.
