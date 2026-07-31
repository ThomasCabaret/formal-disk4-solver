# Formal Disk4 Solver 1.7.4

This differential release adds live formal/geometry result summaries to the pipeline GUI.

## Pipeline table

Each pipeline row now displays:

- the real stage state (`not started`, `running`, `paused`, `complete`, etc.);
- the number of formal candidates currently persisted by the search checkpoint;
- the number of distinct formal candidates classified by geometry;
- `Certain reject`: a candidate with a unique fixed geometry that failed closure or validation;
- `Solution`: a valid geometric solution was found;
- `No solution`: the numerical search did not find a solution, without proving rejection.

The table refreshes automatically while the pipeline is running and while the GUI remains open.

## Exact geometry status registry

Geometry now maintains `geometry/geometry_status.sqlite3`. It stores only the latest status for each `formal_profile_id`, so retries do not inflate the GUI counts. A later successful retry replaces an earlier `No solution` status.

`--restart` removes this registry together with the other geometry outputs.

Existing geometry output created before 1.7.4 remains readable. When only cumulative legacy counters are available, the GUI prefixes geometry counts with `~` to indicate that retries may make them approximate. New or retried candidates progressively receive exact statuses.

## Scope

The formal solver, word solver, pruning rules, mapping quotient, search checkpoint schema and geometry checkpoint schema are unchanged.
