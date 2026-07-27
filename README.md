# Formal Contour Solver 0.5.0

This repository is a streaming formal-contour solver for congruent topological-disk pieces tiling a disk. The search engine is map-driven: piece count, contour incidences, contact interfaces, exterior arcs, vertex-angle sums and map automorphisms come from a registered `PlanarMap`.

Two maps are currently registered:

- `k4-central`: one central piece and three peripheral pieces, with piece-contact graph K4;
- `k3-pizza`: three congruent sectors meeting at one interior vertex, each pair sharing one radial interface and each piece touching the disk boundary.

The three-piece map is a pipeline validation case. With the supplied configuration, its first canonical placement gives the finite contour `T0^-1 T1 T0` and survives all currently active formal filters.

## Implemented pipeline

For every selected map, the program:

1. Enumerates cyclic offsets and direct/reflected copy orientations. A cyclic offset only identifies the first occurrence after the chosen cut of the prototype contour.
2. Quotients explicit automorphisms of the selected map. Automorphisms may move the reference copy; prototype reversal is normalized per assignment.
3. Builds all weak cyclic interleavings incrementally, including coincidence blocks between different copies.
4. Adds interface-length equations as soon as their endpoints are known and rejects branches with no strictly positive atomic lengths.
5. Adds signed-turn equations at every geometric map vertex.
6. Compiles every surviving placement into one word equation per internal interface and one exterior word per outer arc.
7. Runs the exact-partial Nielsen-Levi solver:
   - finite/pure families are emitted;
   - fixed-context cycles are compiled as powers;
   - successive supported cycles may produce nested powers;
   - more general iterative components are cut and classified as unsupported, not as impossible.
8. Uses expansion policy `none` by default. Finite families still have one concrete specialization; power families remain symbolic and do not enter the concrete profile pipeline.
9. Reconstructs the terminal contour and every explicit segment mapping.
10. Resolves signed angle equality/complement classes induced by the mappings.
11. Builds curve-template components under identity, reverse, mirror and mirror+reverse.
12. Propagates the common `disk_boundary` circular decoration through all exterior words.
13. Applies modular local filters and commits every survivor immediately to SQLite and `candidates.jsonl`.
14. In the separate geometry stage, reads formal survivors and numerically realizes one closed simple piece contour without assembling copies.
15. In the visualization stage, reconstructs every congruent copy solely from the oriented contact mappings and direct/reflected parities, validates all mapped interfaces, then displays the complete assembly.

The program never materializes all cyclic orders in advance.

## Windows quick start

Install or update the environment:

```bat
setup.bat
run_tests.bat
```

Run the three-piece validation case and stop at its first formal survivor:

```bat
run_pizza3.bat
```

Then realize that single piece contour geometrically:

```bat
run_pizza3_geometry.bat --restart
```

Display the complete three-piece assembly reconstructed from the mappings:

```bat
run_pizza3_visualizer.bat
```

Run all three stages and open the viewer:

```bat
run_pizza3_pipeline.bat --restart
```

Restart that validation search from the beginning:

```bat
run_pizza3.bat --restart
```

Run the unbounded K4 search:

```bat
run_full_k4.bat
```

Other launchers:

```bat
run_debug.bat
run_benchmark.bat
run_enumeration_only.bat
```

Every `.bat` launcher prints its steps, writes a transcript under `logs\`, reports its exit code and pauses before closing.

The map can also be overridden directly:

```bat
run_debug.bat --map k3-pizza --output output\pizza_debug --restart
```

## Reading the progress line

A line such as:

```text
nodes=662 placements=2 word_systems=2 families=5 specializations=3 profile_rejections=3 profiles=0
```

means:

- `nodes`: partial weak-order prefixes visited, including complete leaves;
- `placements`: complete weak orders surviving the early length and angle filters;
- `word_systems`: placements sent to the word solver;
- `families`: supported symbolic families emitted by that solver;
- `specializations`: concrete finite instances sent to decoration;
- `profile_rejections`: concrete profiles rejected during decoration or local filtering;
- `profiles`: fully filtered survivors persisted to disk.

With expansion policy `none`, power and nested-power families increase `families` but not `specializations`. Therefore `families=5, profiles=0` does not by itself mean that all five families failed geometric filters.

## Persistent output

Normal full runs persist only:

- `checkpoint.sqlite3`: compact cursor, cumulative counters and survivors;
- `candidates.jsonl`: complete self-contained survivor records, including an explicit alternating decorated terminal contour;
- `run_summary.json`: counters, timings and progress;
- `effective_config.json`;
- bounded `errors.jsonl`.

Potentially massive per-placement and per-system audit streams are disabled by default and capped when explicitly enabled.

A survivor record contains the full planar map, assignment, cyclic placement, equations, symbolic family, specialization, terminal contour, contact mappings, angle classes, curve-template components, exterior-circle constraints, LP witnesses and filter statuses.

## Solver configuration

```json
{
  "solver": {
    "mode": "exact_partial",
    "max_graph_nodes_per_placement": 3000,
    "max_graph_edges_per_placement": 12000,
    "max_families_per_placement": 8,
    "max_expression_nodes": 2000,
    "validation_exponent": 2,
    "family_expansion": {
      "policy": "none",
      "maximum_exponent": 1,
      "max_specializations_per_family": 64
    }
  }
}
```

Expansion policies are `none`, `minimum`, `fixed` and `range`.

## Current proof-status limitations

- Equality systems for terminal angles and disk-normalized lengths are reduced exactly over rational numbers. Strict inequalities still use SciPy HiGHS witnesses; a rational exact backend is still required for positivity certificates.
- Common-circle length-turn relations are resolved exactly after disk-circumference normalization and are consumed by the numerical single-piece contour stage.
- Numerical realization uses piecewise-linear generic templates and analytic circular arcs. Simplicity is verified on exact polyline edges and a dense arc sampling; it is not yet a formal continuous-curve proof.
- Cross-profile decorated subsumption, signed-area certification and Z3 geometry remain later stages. Mapping-derived assembly isometries and interactive solid-fill rendering are implemented, but overlap/coverage certification of the complete assembly is not yet formal.
- The K4 statement that the combinatorially central piece contains the disk center remains a realization-stage condition.

See `docs/ARCHITECTURE.md`, `docs/BENCHMARK_NOTES.md` and `docs/OUTPUT_SCHEMA.md`.

## Decorated terminal contours

Every surviving profile now contains `profile.decorated_terminal_contour`, an alternating cyclic sequence of point and curve decorations. The console prints the same compact sentence immediately after `[SURVIVOR]`.

For the canonical `k3-pizza` sector, the resolved sentence is:

```text
(2/3*pi[1/3 turn])
T0^-1{generic_curve,L=(L_C0)*C_disk}
(1/2*pi[1/4 turn])
T1{circular_arc:disk_boundary,L=1/3*C_disk,turn=2/3*pi[1/3 turn]}
(1/2*pi[1/4 turn])
T0{generic_curve,L=(L_C0)*C_disk}
```

Here `T0` is one free curve template used in opposite orientations on the two radial sides. Its length remains a free positive parameter relative to the disk circumference. `T1` is exactly a circular arc of the disk boundary with length `1/3*C_disk` and sweep `2/3*pi`, i.e. one third of a full turn.

The JSON also records the exact angle relations that imply this result:

```text
alpha_B1 = alpha_B2
alpha_B1 + alpha_B2 = 1
3*alpha_B0 = 2
```

All coefficients are stored as rational numerators and denominators. Floating-point LP values are retained only as feasibility witnesses and are labeled as such.


## Numerical single-piece geometry

The geometry command consumes `candidates.jsonl`; it does not rerun the formal search and it does not place the other congruent copies.

```bat
.venv\Scripts\python.exe -m formal_disk4 geometry --config config\pizza3_geometry.json --restart
```

For every generic curve template, `intermediate_points_per_generic_curve=1` creates two line segments sharing one optimized intermediate point. Repeated direct, inverse or mirrored occurrences use the same template. Straight components remain exact segments. Circular components remain analytic arcs with solved radius and sweep.

A solution is saved only after closure, tangent closure, decorated angles, decorated lengths, positive area and sampled non-self-intersection all pass. The output is `output\pizza3\geometry\geometric_solutions.jsonl`; each record includes the complete formal candidate and the stable `formal_profile_id` needed by the later assembly renderer.

For the canonical pizza candidate the solver obtains `L_C0 = 1/(2*pi)`, the disk arc radius `1/(2*pi)` and sweep `2*pi/3` under the normalization `C_disk=1`.


## Mapping-driven assembly visualization

The visualizer consumes `geometric_solutions.jsonl`. It fixes the map's reference piece, then propagates one Euclidean isometry per copy through the internal-contact graph. For every interface, the formal profile already specifies:

- the left and right pieces;
- the paired terminal contour segments;
- the traversal direction on each segment;
- whether the relative isometry is direct or reflected.

No placement optimizer is used. An oriented interface chord and the required parity determine the relative isometry; dense samples of the mapped curves are then used only to verify that the complete interface coincides. Cycles in the contact graph are checked for consistency.

The desktop viewer uses Tkinter from the standard Python distribution. It renders each piece as a solid filled polygon with no outline or vertex markers on a medium-gray background. Piece checkboxes are generated from the map, so a three-piece pizza and a future four-piece K4 realization use the same interface. Previous/Next buttons and keyboard arrows navigate through multiple geometric solutions.

Direct command:

```bat
.venv\Scripts\python.exe -m formal_disk4 visualize --config config\pizza3_visualizer.json
```

Headless mapping validation:

```bat
.venv\Scripts\python.exe -m formal_disk4 visualize --config config\pizza3_visualizer.json --validate-only
```
