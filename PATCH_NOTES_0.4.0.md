# Patch 0.4.0 - single-piece numerical contour realization

This differential update adds the first numerical geometry stage. It consumes
formal survivors from `candidates.jsonl` and realizes only the boundary of one
piece. It deliberately does not assemble congruent copies and does not render an
image yet.

## New geometry command

```bat
run_pizza3_geometry.bat --restart
```

Equivalent direct command:

```bat
.venv\Scripts\python.exe -m formal_disk4 geometry --config config\pizza3_geometry.json --restart
```

The pizza formal candidate must exist first:

```bat
run_pizza3.bat --restart
```

## Geometry model

- A generic curve template is represented by a polyline.
- The default is one intermediate point, hence two straight subsegments.
- Repeated direct/inverse/mirrored occurrences use the same local template.
- A forced straight component remains one exact straight segment.
- A circular component remains an analytic circular arc. Sampling is used only
  for numerical simplicity validation.
- Formal point-angle expressions and formal component-length expressions are
  evaluated from shared free parameters.
- The contour is propagated from one fixed point and one fixed initial tangent;
  closure and tangent-cycle closure are solved numerically.

## Validation

A result is emitted only when all configured checks pass:

- positional closure;
- tangent-cycle closure;
- all decorated point angles;
- all decorated component lengths;
- positive nondegenerate sampled edges;
- nonzero enclosed area;
- no self-intersection of exact polyline edges or densely sampled circular arcs.

This is a strong numerical validation, not a formal proof of simplicity for the
continuous curve between samples.

## Output

`output\pizza3\geometry\geometric_solutions.jsonl` contains:

- a stable geometric solution identifier;
- the formal profile identifier;
- the complete source formal candidate;
- solved formal free parameters;
- local curve-template control points;
- exact circular centers, radii and sweeps;
- every placed contour occurrence;
- every contour point and tangent;
- detailed validation residuals and pass/fail checks.

Dense arc samples are not persisted, avoiding unnecessary output growth.

A compact `geometry_checkpoint.json` stores only the next input line and aggregate
counts. Failed optimizer attempts are not stored by default.

## Pizza regression

The canonical pizza profile is solved without a pizza-specific geometric rule.
With disk circumference normalized to one, the numerical stage obtains:

```text
L_C0 = 1 / (2*pi)
radius(T1) = 1 / (2*pi)
sweep(T1) = 2*pi/3
```

The default generic template has one intermediate point; the optimizer places it
collinearly, yielding the expected radial side. The resulting contour closes to
floating error and passes the sampled simplicity test.
