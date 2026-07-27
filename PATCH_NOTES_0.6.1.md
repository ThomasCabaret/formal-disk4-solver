# Patch 0.6.1 - Correct physical vertex angles

This differential patch applies over version 0.6.0.

## Corrected rule

A geometric map vertex now contributes exactly one equation in positive polygonal interior angles, measured in units of pi:

- interior vertex: the incident piece angles sum to `2`;
- outer disk-boundary vertex: the incident piece angles sum to `1`.

The rule works for any number of incident pieces. Copy reflection preserves a solid interior angle and therefore does not change its sign or replace it by `2-alpha`.

The early weak-order filter uses the equivalent signed-turn equations with `tau=1-alpha`:

- interior degree `n`: `sum(tau)=n-2`;
- outer degree `n`: `sum(tau)=n-1`.

## Mapping endpoint correction

Mappings now generate signed-turn relations only at points strictly inside a mapped subarc. Both endpoints are excluded. At an endpoint the interface determines only the tangent of the shared side, not the other side of the corner, so it cannot imply equality or complementarity of the complete point angles.

This restores the correct pizza family:

```text
alpha_center = 2/3
alpha_outer_left + alpha_outer_right = 1
```

The two outer angles remain a free complementary pair. `1/2,1/2` is only a possible numerical witness.

## Serialization and compatibility

Occurrence-angle fields now always store the positive solid angle, independently of direct/reflected copy orientation. The survivor schema is `formal-contour-survivor-v7`, the nested profile schema is `formal-contour-profile-v6`, and the search-semantics version is `formal-contour-search-v6`. Existing 0.6.0 checkpoints are intentionally rejected.

## Geometry test reliability

The numerical geometry residual gives contour closure a larger weight. This does not relax validation tolerances; it makes the pizza realization reach the existing `1e-8` closure requirement more reliably after the outer angles became free.

## Validation

Tests cover:

- arbitrary-degree interior and outer vertex sums;
- invariance of solid point angles under copy reflection;
- rejection of inconsistent declared map-vertex sums;
- exclusion of interface endpoints from mapping angle classes;
- the pizza exact family `2/3, t, 1-t`;
- formal search, numerical geometry and mapping-driven visualization.
