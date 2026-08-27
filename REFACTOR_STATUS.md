# Refactor status

This file records the current stabilization boundary so later work can resume
without reconstructing it from the Git history.

## Maintained baseline

- The web Graph Lab is the maintained interactive entry point.
- `FormalSolverAPI` is the shared formal-solver boundary. Legacy clients may
  keep using it without depending on Graph Lab internals.
- A `GraphLabSearchRequest` describes the mathematical search domain and its
  constraints independently from the traversal strategy.
- Graph ordering uses the stochastic prior by default. Learned ordering is an
  explicit experimental policy.
- Complete enumeration and joint cyclic backtracking are selectable search
  strategies; changing strategy does not change the mathematical request.
- Run persistence is isolated in `GraphLabRunStore` so future strategies can
  reuse checkpoints and dashboard data.
- Documentation sources live under `docs/`; generated local PDFs belong under
  `output/docs/`.

## Completed stabilization steps

1. Consolidated the documentation layout.
2. Generalized the formal solver for partial regions, free boundaries, and
   intrinsic prototype rotation constraints.
3. Moved mirror self-identification refinement into the formal word/profile
   construction rather than geometry-side repair.
4. Added bounded joint backtracking for contour mappings and weak cyclic
   orders.
5. Separated graph policy, search request, shared CLI arguments, and run-state
   persistence from the main Graph Lab loop.
6. Extracted diversity archiving and stochastic graph-pool construction behind
   the `GraphProposalSource` protocol.
7. Isolated bounded replay-journal loading for experimental learned policies in
   `GraphLabReplayStore`.
8. Moved generation metrics, final reports, and geometry-queue exports into
   `GraphLabReporter`.
9. Isolated the optional mapping, weak-order, and specialization policies in
   `HierarchicalPolicyRuntime`.

## Remaining work

1. Split the remaining generation loop orchestration out of `GraphLabRunner` if
   a second caller actually needs it. Proposal, hierarchical policies,
   persistence, and reporting are now independent; avoid adding an interface
   merely to reduce the remaining line count.
2. Define a common proposal protocol before adding incremental graph or
   weak-order backtracking. New strategies should produce the same request and
   observation types as current strategies.
3. Move generally useful crown/free-boundary graph transformations out of the
   Graph Lab package once their contracts have stabilized.
4. Add web-side start/stop/resume controls only after orchestration is detached
   from the dashboard server.
5. Keep Mapping Lab and learned policies experimental until deterministic and
   stochastic baselines are stable enough to evaluate learning honestly.

## Regression checks

Run from the repository root:

```powershell
$env:PYTHONPATH = "$PWD\src"
py.exe -m pytest -q
```

The stabilization baseline at the time this note was written passed 318 tests,
with one skipped test and 217 parameterized subtests.
