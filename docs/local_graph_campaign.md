# Exhaustive local-contact-graph campaign

This standalone campaign is a validation tool for the formal solver. It does
not use Graph Lab learning and it imposes no structural symmetry. It currently
retains the deprecated complete-mapping-first traversal so its resumable
exhaustion certificates remain comparable with older campaigns. It must not be
used as a performance reference for the maintained Graph Lab tile-frontier
strategy.

## Exact native graph domain

The native source uses NetworkX's complete, isomorph-free graph atlas. A dual
graph has one distinguished `OUTSIDE` vertex in addition to its tile vertices.
Every inequivalent choice of that root is retained. Candidates are required to
be simple, planar, and 3-connected; consequently every tile has degree at least
three when `OUTSIDE` is counted, and the spherical embedding is unique up to
reflection.

The atlas contains all graphs through seven vertices, so native graph coverage
is exact only for three through six tiles. The program refuses a larger native
range rather than silently sampling it. A future `plantri`/nauty source can
extend the same campaign interface to larger sizes.

The exact rooted counts in this domain are:

| Tiles | Graphs |
|---:|---:|
| 3 | 1 |
| 4 | 4 |
| 5 | 17 |
| 6 | 155 |

## Running

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH = "$PWD\src"
py.exe -m formal_disk4.graph_lab.exhaustive_local `
  --min-tiles 3 `
  --max-tiles 6 `
  --word-seconds 2 `
  --graph-seconds 30 `
  --output-directory output\local_graph_campaign\atlas-3-6
```

The command resumes automatically. Add `--restart` only to discard that
campaign directory and start it again. To inspect the graph domain without
running the solver, add `--catalog-only`.

The example is a bounded survey: each word case gets two seconds and each graph
gets a 30-second slice. An incomplete graph does not block later graphs.
Re-running the same command resumes its checkpoints and grants another slice.
Any cutoff is recorded as a proof gap and can never produce a negative
certificate. Omit the two time options for an unbounded run, but the configured
terminal-contour and residual-graph guardrails still deliberately leave very
large symbolic/nested systems unresolved rather than trying to solve them.
Use the same `--word-seconds` value when resuming a campaign because that option
is part of its checkpoint fingerprint; `--graph-seconds` may be changed.

To print the current list of graphs, statuses, elapsed times, profile counts,
proof gaps, and compact edge lists without doing more work:

```powershell
py.exe -m formal_disk4.graph_lab.exhaustive_local `
  --min-tiles 3 `
  --max-tiles 6 `
  --output-directory output\local_graph_campaign\atlas-3-6 `
  --report-only
```

## Center-plus-ring reference family

The same validation pipeline can target one graph per size consisting of one
central tile and a cycle of surrounding tiles. Every surrounding tile touches
the center, its two cyclic neighbours, and the free exterior. No symmetry is
imposed on the mapping or on the prototype.

```powershell
py.exe -m formal_disk4.graph_lab.exhaustive_local `
  --graph-family center-ring `
  --min-tiles 4 `
  --max-tiles 10 `
  --word-seconds 2 `
  --graph-seconds 30 `
  --output-directory output\local_graph_campaign\center-ring-4-10
```

## Outputs and certificate semantics

- `graph_manifest.json` is the exact requested rooted graph catalog.
- `status.json` identifies the current graph.
- `results.json` is the authoritative per-graph result table.
- `timings.csv` gives formal, geometry, and wall times by graph and size.
- The console/report table also shows placement nodes, word cases, residual
  graph nodes, deferred word cases, and the word solver's share of elapsed
  formal time. These numbers make the first combinatorial explosion visible.
- Every graph directory contains its graph, formal checkpoint, geometry state,
  and an SVG when an assembled geometric solution is found.
- `formal_unsat_certificate.json` is written only when the full discrete search
  completed with no formal profile and with no deferred, unsupported, capped,
  externally stopped, or errored word case.

That certificate is an auditable exhaustion record for the implemented formal
model. It is not an independently checked mathematical proof. Conversely, a
numerical geometry failure is always reported as open and is never treated as
evidence of impossibility.

The production solver writes a console heartbeat and
`formal/diagnostics/heartbeat_latest.json` while a graph is active. This makes
long word-solver branches distinguishable from a dead process.
