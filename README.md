# Formal Contour Solver 0.6.1

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
5. Adds one physical solid-angle equation at every geometric map vertex: incident angles sum to `2*pi` inside the disk and to `pi` on the disk boundary.
6. Compiles every surviving placement into one word equation per internal interface and one exterior word per outer arc.
7. Runs the exact-partial Nielsen-Levi solver:
   - finite/pure families are emitted;
   - fixed-context cycles are compiled as powers;
   - successive supported cycles may produce nested powers;
   - more general iterative components are cut and classified as unsupported, not as impossible.
8. Uses expansion policy `none` by default. Finite families still have one concrete specialization; power families remain symbolic and do not enter the concrete profile pipeline.
9. Reconstructs the terminal contour and every explicit segment mapping.
10. Resolves signed-turn classes only at points strictly internal to mapped interfaces; interface endpoints are governed solely by the physical vertex equations.
11. Builds curve-template components under identity, reverse, mirror and mirror+reverse.
12. Assigns one unbounded signed total-turn variable `K_Ci` to every curve component.
13. Solves one exact rational joint system containing point-angle classes, curve turns, positive lengths, straight/self-reversing zero-turn constraints, circular-arc turn constraints and the total-turn equation of the prototype contour.
14. Propagates the common `disk_boundary` circular decoration through all exterior words.
15. Applies modular local filters and commits every survivor immediately to SQLite and `candidates.jsonl`.
16. In the separate geometry stage, reads formal survivors and numerically realizes one closed simple piece contour without assembling copies.
17. In the visualization stage, reconstructs every congruent copy solely from the oriented contact mappings and direct/reflected parities, validates all mapped interfaces, then displays the complete assembly.

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

- Early placement length/angle pruning still uses SciPy HiGHS. After a terminal formal contour is obtained, the complete joint point/curve-turn and positive-length feasibility test is exact over rational numbers, including its strict-margin certificate.
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
T0^-1{generic_curve,L=(L_C0)*C_disk,turn=(K_C0)*pi}
((1 - alpha_B2)*pi)
T1{circular_arc:disk_boundary,L=1/3*C_disk,turn=2/3*pi[1/3 turn]}
((alpha_B2)*pi)
T0{generic_curve,L=(L_C0)*C_disk,turn=(K_C0)*pi}
```

Here `T0` is one free curve template used in opposite orientations on the two radial sides. Its length and representative signed total turn `K_C0*pi` remain free; the two contour occurrences contribute opposite curve turns and therefore cancel in the prototype total-turn equation. `T1` is exactly a circular arc of the disk boundary with length `1/3*C_disk` and sweep `2/3*pi`, i.e. one third of a full turn.

The two outer point angles are not individually fixed. The exact relations are:

```text
alpha_B1 + alpha_B2 = 1
3*alpha_B0 = 2
0 < alpha_B1 < 1
0 < alpha_B2 < 1
```

Thus `alpha_B2=t` and `alpha_B1=1-t`; `pi/2,pi/2` is only one possible witness. All coefficients are stored as rational numerators and denominators. Floating-point LP values are retained only as feasibility witnesses and are labeled as such.



## Physical map-vertex angle rule

Every `PlanarMap` vertex is classified as `interior` or `outer`. If the incident solid polygonal angles are `alpha_1,...,alpha_n`, the solver adds exactly one equation:

```text
interior vertex: alpha_1 + ... + alpha_n = 2
outer vertex:    alpha_1 + ... + alpha_n = 1
```

All values are in units of `pi`. Reflection of a congruent copy preserves its positive solid interior angle, so copy-orientation signs do not appear in these equations. With signed point turn `tau_i=1-alpha_i`, the equivalent equations used by the early oracle are `sum(tau_i)=n-2` and `sum(tau_i)=n-1`.

A contact mapping transports signed turns only at subdivision points strictly inside the mapped interval. Its two endpoints are deliberately excluded because the shared arc supplies only one of the two incident tangent directions and cannot determine the complete corner angle.

## Exact joint point/curve-turn filter

For every terminal profile, point corners and curve interiors are solved together. In units of `pi`:

```text
tau_Bi = 1 - alpha_Bi
-1 < tau_Bi < 1
K_Ci in R
sum(occurrence curve turns) + sum(tau_Bi) = 2
```

`K_Ci` is the signed tangent rotation accumulated while traversing the representative curve template. Reversing the template or applying an orientation-reversing isometry changes its sign. A straight component, or a component identified with itself through a sign-reversing transform, has `K_Ci = 0`.

With disk circumference normalized to one, every positively traversed exterior-circle occurrence additionally satisfies:

```text
physical_signed_turn_pi = 2 * component_length
```

The point equations, length equations, curve-turn equations and total winding are first reduced by exact rational Gaussian elimination. A small exact rational simplex then maximizes a common strict margin for all point-angle bounds and positive component lengths. Infeasible profiles are rejected before they are written to `candidates.jsonl` or sent to numerical geometry.

The mappings still determine relative copy placement. The curve-turn variables do not introduce an alternative assembly mechanism; they describe only the tangent rotation internal to the prototype curve templates.

## Numerical single-piece geometry

The geometry command consumes `candidates.jsonl`; it does not rerun the formal search and it does not place the other congruent copies.

```bat
.venv\Scripts\python.exe -m formal_disk4 geometry --config config\pizza3_geometry.json --restart
```

For every generic curve template, `intermediate_points_per_generic_curve=1` creates two line segments sharing one optimized intermediate point. Repeated direct, inverse or mirrored occurrences use the same template. Straight components remain exact segments. Circular components remain analytic arcs with solved radius and sweep.

A solution is saved only after closure, tangent closure, decorated angles, decorated lengths, positive area and sampled non-self-intersection all pass. The output is `output\pizza3\geometry\geometric_solutions.jsonl`; each record includes the complete formal candidate and the stable `formal_profile_id` needed by the later assembly renderer.

For the canonical pizza candidate, the disk arc radius is fixed to `1/(2*pi)` and its sweep to `2*pi/3` under the normalization `C_disk=1`. The radial-template length `L_C0`, its total turn and the complementary outer-angle parameter remain free; the numerical solver may therefore return a symmetric sector or an asymmetric but formally valid one.


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
