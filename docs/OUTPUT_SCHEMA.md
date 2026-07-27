# Output schema 0.3.1

## Default persistent files

### `checkpoint.sqlite3`

SQLite is authoritative for resumable search state and survivors. The checkpoint contains one compact cursor, cumulative counters/timings and a completion flag. It does not contain rejected placements, compiled word systems or residual solver graphs.

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
- signed angle classes and physical-vertex complement relations;
- curve-template components classified as `generic_curve`, `straight_segment` or `circular_arc`;
- exact disk-circumference-normalized component and exterior-arc lengths;
- exact circular sweep parameters in units of pi and full turns;
- common-circle constraints;
- map-dependent expected mapping/outer-arc counts;
- local filter statuses.

The number of mappings is determined by the map: three for `k3-pizza`, six for `k4-central`.

### `run_summary.json`

Contains cumulative counters, timings, rates, checkpoint status and combinatorial progress.

### `errors.jsonl`

Unexpected implementation errors only, globally capped across resumed sessions.

## Optional bounded audit streams

Disabled by default and globally capped when enabled:

- `word_case_audit.jsonl`;
- `word_families.jsonl`;
- `unsupported_word_components.jsonl`;
- `placements.jsonl`.


## Exact versus witness values

`search_witness_normalized_length`, placement margins and LP angle values are numerical feasibility witnesses. They must not be interpreted as uniquely determined geometry.

The authoritative formal values are stored under:

- `exact_angle_solution`;
- `exact_disk_normalized_length_solution`;
- each point's `prototype_angle_pi`;
- each component's `disk_normalized_length`;
- each circular component's `disk_normalized_turn_pi`;
- each outer arc's `disk_normalized_length` and `turn_pi`.

Every exact scalar is represented by numerator, denominator, text and a convenience floating value. Underdetermined values are affine expressions in explicit free parameters.

## Geometry-stage files 0.4.0

### `geometry/geometric_solutions.jsonl`

One record per validated numerical realization. Each record contains:

- `formal_profile_id` and a stable `geometric_solution_id`;
- source candidates file and line number;
- optionally the complete formal candidate (enabled by default);
- solved values of all free formal angle/length parameters;
- local curve-template control points;
- analytic circular centers, radii and signed sweeps;
- every placed curve occurrence with start/end points and tangents;
- every decorated contour point with target and reconstructed angle;
- closure, tangent, length, area and self-intersection validation metrics.

Dense circular validation samples are not stored. The analytic arc descriptor is
sufficient for the later renderer.

### `geometry/geometry_checkpoint.json`

A compact line cursor and aggregate counts. It does not contain optimizer states,
failed iterates or sampled curves.

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
