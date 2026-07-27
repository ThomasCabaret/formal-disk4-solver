# Patch 0.6.0 - Exact point and curve-turn feasibility

This differential patch applies over version 0.5.0.

## Conceptual separation

Contact mappings remain the sole source used to place congruent copies relative to one another. A mapping specifies the paired subcontours, their traversal direction and direct/reflected parity; the visualization layer derives the corresponding Euclidean isometry.

The curve-transform information used by this patch has a different purpose: it propagates the sign of the **total tangent turn internal to a curve template**. It does not create a competing placement mechanism.

## New exact terminal variables

For every terminal point:

```text
tau_Bi = 1 - alpha_Bi
-1 < tau_Bi < 1
```

where `alpha_Bi` is the interior angle in units of pi.

For every curve-template component:

```text
K_Ci in R
```

where `K_Ci*pi` is the signed total tangent rotation accumulated while traversing the representative curve. These variables are deliberately unbounded because a generic curve may spiral.

Every component also retains its positive normalized length `L_Ci`.

## Exact equations

The terminal filter combines:

- all existing point-angle class and physical-vertex equations;
- all exact terminal length equations;
- sign propagation of curve turn through reverse/reflected template relations;
- `K_Ci = 0` for straight or self-turn-reversing components;
- exterior-circle equations `signed K_Ci = 2*L_Ci` under `C_disk=1`;
- the prototype winding equation

```text
sum(signed curve occurrence turns) + sum(1-alpha_Bi) = 2.
```

The equality system is reduced by exact rational Gaussian elimination. A new exact two-phase simplex, implemented with `fractions.Fraction`, maximizes a common strict margin for all point-angle bounds and positive component lengths. Zero-margin and inconsistent profiles are rejected before persistence and before numerical geometry.

## Output changes

Every curve segment now exports:

- `curve_turn_parameter`;
- exact affine `curve_turn_pi`;
- `curve_turn_pi_witness`;
- readable turn text in the decorated contour.

Every profile exports `exact_joint_angular_feasibility`, including equations, source labels, affine solution, free parameters, exact margin and witness.

The progress line reports `joint_angle_rejections`.

## Numerical geometry

The single-piece geometry solver now enforces the formal total turn of every generic curve component. Previously, only circular sweeps were fixed and a generic curve could numerically acquire an incompatible total turn.

## Compatibility

The survivor schema is now `formal-contour-survivor-v6`; the nested profile schema is `formal-contour-profile-v5`.

Search semantics changed. Existing 0.5.0 checkpoints and previously emitted candidates have not passed the new exact filter. Start a new search with `--restart` or use a new output directory.

## Validation

The test suite includes:

- rejection of a one-segment straight contour whose total turn cannot reach one full winding;
- preservation of genuinely free unbounded curve-turn parameters;
- exact pizza-sector resolution with a free radial-curve turn that cancels and a disk arc fixed to `2/3*pi`;
- end-to-end geometry compatibility.
