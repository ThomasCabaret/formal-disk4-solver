# Patch 0.3.1 - exact decorated terminal contour

This differential patch applies over version 0.3.0. Extract it into the project root and allow overwriting.

## Why the patch was needed

Version 0.3.0 already propagated point and curve decorations, but its survivor JSON did not present them as one resolved cyclic contour. It also exposed an LP witness as `normalized_length`, which could be mistaken for a mathematically forced length.

For `k3-pizza`, the max-margin LP happened to choose all three atomic lengths equal to `1/3`. Only the exterior arc is actually forced to be one third of the disk circumference; the radial curve length is free. Version 0.3.1 separates these notions.

## Exact rational angle resolution

The terminal decoration stage now builds exact equations directly in the interior-angle variables `alpha_B0`, `alpha_B1`, ... . It combines:

- angle equality or full-turn complement relations induced by every mapped segment endpoint;
- the sum of incident piece angles at each interior or exterior map vertex;
- strict geometric bounds checked by the existing LP.

The equations are row-reduced over `fractions.Fraction`. Each point receives either an exact rational angle or an affine expression in explicit free parameters.

For the canonical pizza sector, the stored equations include:

```text
alpha_B1 - alpha_B2 = 0
alpha_B1 + alpha_B2 = 1
3*alpha_B0 = 2
```

and therefore:

```text
alpha_B0 = 2/3*pi = 1/3 full turn
alpha_B1 = alpha_B2 = 1/2*pi = 1/4 full turn
```

The exterior endpoint angles are both equal by congruence and complementary to `pi` at the physical disk-boundary vertex.

## Exact disk-normalized curve lengths

Terminal component lengths are no longer fixed to one arbitrary placement witness. The program now:

1. substitutes terminal component counts into the placement length equations;
2. adds the normalization `disk circumference = 1`;
3. solves the equality system exactly;
4. separately maximizes a strict positivity margin.

For `k3-pizza` this gives:

```text
L(T1) = 1/3*C_disk
turn(T1) = 2/3*pi = 1/3 full turn
L(T0) = free positive parameter * C_disk
```

`T1` is classified as `circular_arc` on `disk_boundary`. `T0` remains a `generic_curve` used once directly and once inversely; it is not incorrectly forced straight.

## Explicit decorated contour

Every survivor now contains:

```text
profile.decorated_terminal_contour
```

with:

- an alternating point/segment cycle;
- incoming and outgoing literals at every point;
- exact point-angle expressions;
- segment curve type, orientation, component and length expression;
- circular arc length and sweep;
- all mapping and physical-vertex angle relations;
- complete exact angle and length solutions.

The console prints the compact sentence immediately after a survivor:

```text
[DECORATED CONTOUR] (2/3*pi[1/3 turn]) T0^-1{generic_curve,L=(L_C0)*C_disk} (1/2*pi[1/4 turn]) T1{circular_arc:disk_boundary,L=1/3*C_disk,turn=2/3*pi[1/3 turn]} (1/2*pi[1/4 turn]) T0{generic_curve,L=(L_C0)*C_disk}
```

## Schema and checkpoint compatibility

- package version: `0.3.1`;
- profile schema: `formal-contour-profile-v4`;
- survivor schema: `formal-contour-survivor-v4`.

Search semantics changed because the terminal length feasibility system is now constructed correctly. Existing 0.3.0 checkpoints are intentionally rejected. Use `--restart` or a new output directory.

## Missing legacy source

The initial archive references `angle_constraints.py`, but that source file was not included. This patch implements the required angle-class behavior directly from map incidences and contact mappings, with exact rational tests for the pizza sector. If the original file is supplied later, its additional conventions can be compared against this implementation.

## Validation

- 30 unit and integration tests pass;
- the pizza integration test emits the exact decorated contour above;
- exact linear tests cover unique rational solutions, free parameters and contradictions.
