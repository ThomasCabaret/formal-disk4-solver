# Fixed-graph Backtracking Lab

This standalone lab measures the maintained tile-frontier arrangement search
without the bounded-survey semantics of `exhaustive_local`. For every fixed
graph, it chooses one whole tile at a time, including its direct/reflected
contour mapping and weak-order merge. Every complete leaf is evaluated
immediately by the production pre-word, word, decoration, and profile kernel.

The lab sets the arrangement wall-clock, node, assignment, placement, and
profile limits to `null`. A graph is labelled `tree_exhausted` only when the
enumerator returns after visiting its complete finite tree. It stops earlier
only after a formal profile has produced an actual geometric solution. Formal
word-system guardrails remain enabled: a deferred or unsupported word case is
reported as a proof gap and prevents a clean negative conclusion, but it does
not stop traversal of the surrounding arrangement tree.

## Center-plus-ring scaling run

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH = "$PWD\src"
py.exe -m formal_disk4.graph_lab.backtracking_lab `
  --graph-family center-ring `
  --min-tiles 4 `
  --max-tiles 10 `
  --output-directory output\backtracking_lab\center-ring-4-10 `
  --restart
```

To measure the first, non-pruning Euclidean placement prototype on the first
64 complete leaves, add:

```powershell
  --euclidean-audit-samples 64
```

The dashboard reports `Audit euclidien faisable` as numerical witnesses over
successful audits.  The complementary leaves are *unresolved*, not certified
impossible.  This experiment never changes the arrangement tree or its
exhaustion status.  `--euclidean-audit-restarts` and
`--euclidean-audit-max-nfev` control its bounded numerical effort.  The
free-outer-boundary campaign automatically omits all unit-circle and disk
containment residuals.

To run the same Euclidean model as an actual early backtracking gate, add:

```powershell
  --euclidean-partial-pruning `
  --euclidean-pruning-restarts 1 `
  --euclidean-pruning-max-nfev 60
```

The gate runs when a newly inserted tile closes at least two interfaces to
already placed tiles. A bounded numerical failure cuts that descendant tree,
but is not an exact impossibility certificate. Consequently the dashboard
reports the number of cut subtrees and a fully traversed run is labelled
`tree_exhausted_tainted`, never `tree_exhausted`. This mode is intended to
measure search acceleration and candidate discovery; it cannot support a
negative mathematical conclusion.

The dashboard opens at `http://127.0.0.1:8770/`. It shows the active graph,
elapsed time, arrangement nodes, complete leaves sent to the formal kernel,
leaf rate, rejection/defer counters, formal profiles, geometry attempts, and
the completed per-graph timing table. A geometric solution is rendered in the
same page. Once a graph obtains one such solution, the campaign records it and
moves to the next graph.

Omit `--restart` to keep completed graphs. An interrupted current graph starts
its deterministic tree again from the root; resumable in-tree cursors have not
been added. Add `--no-browser` to keep the web server without opening a browser,
or `--no-dashboard` for console-only operation. By default, the server remains
open after the campaign completes so the final page stays available; add
`--exit-when-complete` to exit instead.

## Exact small rooted graph atlas

The same front-end can traverse every admissible rooted graph from the native
NetworkX atlas:

```powershell
py.exe -m formal_disk4.graph_lab.backtracking_lab `
  --graph-family atlas `
  --min-tiles 3 `
  --max-tiles 6 `
  --output-directory output\backtracking_lab\atlas-3-6 `
  --restart
```

This graph source is isomorph-free and exhaustive only through six tiles
(seven vertices including `OUTSIDE`); the program refuses larger atlas ranges.

## Output semantics

- `manifest.json` records the ordered graph domain and unbounded traversal
  settings.
- `status.json` is the live dashboard/console state.
- `results.json` records timestamps, total wall time, nodes, leaves, profiles,
  geometry attempts, stop reason, and proof gaps for completed graphs.
- Each graph directory contains `graph.svg`, streamed formal candidates,
  persistent geometry statuses and failures, and `solution.svg` when found.

`tree_exhausted_with_proof_gaps` means that the mapping/weak-order tree was
fully traversed but at least one downstream formal case was deliberately left
inconclusive. It must not be interpreted as a mathematical impossibility.
