# Output schema 1.0.0

## Default persistent files

### `checkpoint.sqlite3`

SQLite is authoritative for resumable search state and survivors. The checkpoint contains one compact cursor, cumulative counters/timings and a completion flag. It does not contain rejected placements, compiled word systems or residual solver graphs.

The search-semantics version is part of the checkpoint metadata. Version 1.0.0 uses canonical case identifiers and case-specific output directories. Older checkpoints remain separate historical files and are not selected by the new case runner.

### `candidates.jsonl`

A human-readable export of the SQLite survivor table. Each self-contained record contains:

- the complete selected planar map;
- copy sequences, orientations and cyclic offsets;
- weak cyclic coincidence blocks and early LP witnesses;
- one compiled equation and explicit mapping per internal interface;
- every exterior word;
- symbolic family and concrete specialization;
- terminal contour and environment;
- an alternating `decorated_terminal_contour` with the point before every segment;
- exact rational point-angle equations, solved values and free parameters;
- signed point-turn expressions and their strict domain `(-pi,pi)`;
- one unbounded signed total-turn variable for every curve-template component;
- mapping-induced curve-turn signs and zero-turn consequences;
- exact joint point/curve-turn/length equations, affine solution and rational strict witness;
- curve-template components classified as `generic_curve`, `straight_segment` or `circular_arc`;
- exact disk-circumference-normalized component and exterior-arc lengths;
- exact circular sweep parameters in units of pi and full turns;
- common-circle constraints;
- map-dependent expected mapping/outer-arc counts;
- local filter statuses.

The number of mappings is determined by the map: three for `c3`, four for `c4`, six for `k4`, and five for each `k4-minus-*` case.

The current top-level survivor schema is `formal-contour-survivor-v7`; the nested profile schema is `formal-contour-profile-v6`.

### `run_summary.json`

Contains cumulative counters, timings, rates, checkpoint status and combinatorial progress. The `preword_*` counters separate topology and linear-invariant checks before Nielsen--Levi. The oracle section reports topology strict-length screens, exact interval certificates, joint metric invariants and point-turn systems. `decoration_rejection_joint_angular_feasibility` counts terminal profiles rejected by the exact terminal system.

### `errors.jsonl`

Unexpected implementation errors only, globally capped across resumed sessions.

## Optional bounded audit streams

Disabled by default and globally capped when enabled:

- `word_case_audit.jsonl`;
- `word_families.jsonl`;
- `unsupported_word_components.jsonl`;
- `placements.jsonl`.

## Exact values versus search witnesses

Early placement margins and SciPy LP angle/length values are numerical pruning witnesses. They must not be interpreted as uniquely determined geometry.

The authoritative terminal formal data are stored under:

- `exact_angle_solution`;
- `exact_disk_normalized_length_solution`;
- `exact_joint_angular_feasibility`;
- each point's `interior_angle_pi` and `signed_point_turn_pi`;
- each component's `disk_normalized_length` and `curve_turn_pi`;
- each outer arc's `disk_normalized_length` and `turn_pi`.

`exact_joint_angular_feasibility` contains:

- `point_angle_variables`: `alpha_Bi`;
- `curve_turn_variables`: `K_Ci`;
- `length_variables`: `L_Ci`;
- the complete exact equation list and source labels;
- the affine rational solution and free parameters;
- an exact positive strict margin;
- one exact rational witness.

Every exact scalar is represented by numerator, denominator, text and a convenience floating value. Underdetermined values are affine expressions in explicit free parameters.

For backward compatibility, segment records retain `disk_normalized_turn_pi` as an alias of `curve_turn_pi`; new consumers should use `curve_turn_pi`.

## Decorated contour segment record

Every segment in `profile.decorated_terminal_contour.cycle` includes:

```text
literal
template_orientation
curve_component
curve_type
circle_class
length_parameter
disk_normalized_length
curve_turn_parameter
curve_turn_pi
curve_turn_pi_witness
forced_straight
self_symmetries
```

`curve_turn_pi` is the total signed tangent rotation of the representative template in units of pi. It is not a point angle and is not bounded. The sign contributed by a particular occurrence is obtained from its literal orientation and mapping-induced template transform.

## Geometry-stage files 0.6.0

### `geometry/geometric_solutions.jsonl`

One record per validated numerical realization. Each record contains:

- `formal_profile_id` and a stable `geometric_solution_id`;
- source candidates file and line number;
- optionally the complete formal candidate, enabled by default;
- solved values of all free formal angle, length and curve-turn parameters;
- local curve-template control points;
- analytic circular centers, radii and signed sweeps;
- every placed curve occurrence with start/end points and tangents;
- every decorated contour point with target and reconstructed angle;
- closure, tangent, component-turn, length, area and self-intersection validation metrics.

Dense circular validation samples are not stored. The analytic arc descriptor is sufficient for the renderer.

### `geometry/geometry_checkpoint.json`

A compact line cursor and aggregate counts. It does not contain optimizer states, failed iterates or sampled curves.

### `geometry/geometry_summary.json`

Configuration, counters, stop reason and the explicit numerical-validation caveat.

## Geometric assembly reconstruction

The visualization stage normally writes no bulk output. Its in-memory `geometric-assembly-v1` record contains:

- `assembly_id`;
- `geometric_solution_id` and `formal_profile_id`;
- map and reference-piece identifiers;
- one orthogonal matrix and translation per piece;
- one sampled solid-fill polygon per piece;
- maximum and RMS residuals for every mapped interface;
- direct/reflected determinant checks.

Use `formal_disk4 visualize ... --validate-only` to print a compact JSON summary without opening the GUI.
