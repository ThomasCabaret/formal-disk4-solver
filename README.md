# Formal Contour Solver

Version 1.0.0 reorganizes the project around explicit **case identifiers**.  A
case owns its planar map, search configuration, geometry configuration,
visualizer configuration, output directory and checkpoints.

## Registered cases

| ID | Topology |
|---|---|
| `c3` | Three congruent sectors; contact graph `C3`. Validation case. |
| `c4` | Four congruent sectors; contact graph `C4`. Validation case. |
| `k4` | The former `k4-central`: `T0` is internal and every pair of tiles shares a positive-length interface. |
| `k4-minus-point` | `K4` minus the `T1-T3` interface. `T0` reaches the outer circle only at the common point `A` of `T0,T1,T3`. |
| `k4-minus-arc` | `K4` minus the `T1-T3` interface. `T0` owns one outer arc between `T3` and `T1`; the outer cyclic order is `T0,T1,T2,T3`. |

Legacy names `k3-pizza`, `k4-pizza` and `k4-central` are accepted as input
aliases, but all new records use the canonical names above.

## Installation

```bat
setup.bat
run_tests.bat
```

## One case runner

Run without arguments to select both a case and an action from menus:

```bat
run_case.bat
```

Non-interactive examples:

```bat
run_case.bat c3 pipeline --restart
run_case.bat k4 search
run_case.bat k4-minus-point profile
run_case.bat k4-minus-arc info
run_case.bat c4 visualize --validate-only
```

Available actions are:

- `search`: formal enumeration and word solving;
- `pipeline`: search, single-piece geometry, then assembly viewer;
- `profile`: disposable 20-second run without checkpoint or survivor output;
- `geometry`: realize candidates already written by the formal search;
- `visualize`: reconstruct copies solely from formal mappings;
- `info`: print the registered planar map.

The full-pipeline action accepts `--restart` and `--no-resume`.  Search,
profile, geometry and visualization modes pass their remaining arguments to the
corresponding Python command.

## Direct full-pipeline launchers

```bat
run_c3_pipeline.bat --restart
run_c4_pipeline.bat --restart
run_k4_pipeline.bat
run_k4_minus_point_pipeline.bat
run_k4_minus_arc_pipeline.bat
```

The two validation cases normally stop on their first formal and geometric
solution.  The three Stein searches are unbounded unless command-line limits
are supplied.

## Independent outputs and checkpoints

Every case writes below its own directory:

```text
output/cases/c3/
output/cases/c4/
output/cases/k4/
output/cases/k4-minus-point/
output/cases/k4-minus-arc/
```

Each formal directory contains its own `checkpoint.sqlite3`.  Geometry
checkpoints are stored under the corresponding `geometry/` directory.  Running
another case cannot overwrite or advance the checkpoint of a previous case.

Disposable profiles use separate directories:

```text
output/profiles/<case-id>/
```

## Case configuration layout

Each case is self-contained under:

```text
config/cases/<case-id>/
    case.json
    search.json
    profile.json
    geometry.json
    visualizer.json
```

`case.json` supplies the display label, map identifier and filenames used by
the generic runner.  The other files contain normal solver configurations.

Adding a case intentionally remains simple:

1. add one `PlanarMap` builder under `src/formal_disk4/maps/`;
2. add one `MapRegistration` entry in `maps/registry.py`;
3. add one `config/cases/<id>/` directory using the five-file layout;
4. add map and checkpoint-isolation tests.

No case-specific branch should be added to the solver pipeline.  Optional
mathematical filters must inspect explicit map structure and hypotheses before
they activate.

## The two new K4-minus cases

### `k4-minus-point`

The encoded assumptions are:

- `T0` contains the disk centre and meets the outer circle only at `A`;
- `A` is incident to `T0,T1,T3`;
- `T1` and `T3` share only `A`, not a positive-length interface;
- `X` is incident to `T0,T1,T2`;
- `Y` is incident to `T0,T2,T3`;
- positive-length interfaces are `T0-T1`, `T0-T2`, `T0-T3`, `T1-T2`, `T2-T3`;
- outer arcs belong to `T1,T2,T3`.

### `k4-minus-arc`

The encoded assumptions are:

- `T0` contains the disk centre and owns one non-degenerate outer arc;
- the outer cyclic order is `T0,T1,T2,T3`;
- `T1` and `T3` are disjoint;
- the same five positive-length internal interfaces as above are present;
- `X=(T0,T1,T2)` and `Y=(T0,T2,T3)` are the two internal triple vertices.

These statements remove the two ambiguities that otherwise remain in a verbal
contact-graph description: whether the point contact in the first case is a
three-tile point, and whether `T1,T3` share an endpoint in the second case.

## Exterior-contact metadata

A piece now declares one of three contact kinds:

```text
none
point
arc
```

This matters because a point contact has no positive-length outer interface.
The map validator checks that the declaration agrees with the outer vertices
and outer interfaces.

The peripheral exterior-arc repetition pruning is still isolated and
configurable.  It activates structurally only for a four-tile Stein map whose
three peripheral pieces each own one full outer edge.  The central tile may
have no outer contact, a point contact, or its own outer arc; its arc is not
included among the three peripheral candidates.

Disable it for a differential run with:

```bat
run_case.bat k4 profile --no-exterior-arc-repetition
```

## Pipeline summary

For each registered map, the formal search:

1. enumerates phase and reflection assignments modulo map automorphisms;
2. enumerates weak cyclic orders, including coincidence blocks;
3. applies incremental positive-length and point-angle feasibility;
4. compiles interface word equations and mappings;
5. applies preword topology and joint linear invariants;
6. runs the exact-partial Nielsen-Levi solver;
7. decorates terminal contour families and applies exact profile filters;
8. writes compact survivors and an SQLite checkpoint.

The geometry stage realizes one prototype contour.  The visualizer then places
all copies only from the formal interface mappings; it does not search for a
preferred assembly.

## Useful direct Python commands

```bat
.venv\Scripts\python.exe -m formal_disk4 map-info --map k4-minus-point
.venv\Scripts\python.exe -m formal_disk4 counts --map k4-minus-arc --symmetry incremental
.venv\Scripts\python.exe -m formal_disk4 assignments --map k4 --limit 5
.venv\Scripts\python.exe -m formal_disk4 run --config config\cases\k4\search.json
```

## Checkpoint compatibility

Canonical map names and case output paths changed in 1.0.0.  Existing 0.9.1
checkpoints are not reused automatically.  Keep them as historical data or
start the corresponding canonical case with `--restart`.
