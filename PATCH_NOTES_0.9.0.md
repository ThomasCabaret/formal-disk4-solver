# Patch 0.9.0 — Refactored pre-Nielsen--Levi pruning

This patch applies on top of version 0.8.0. It replaces the old closed circular-sign balance by a modular pre-word constraint layer and keeps every rejection conservative and auditable.

## Main changes

### 1. Structural radius-arc topology

`formal_disk4.preword.arc_topology` now owns only the inexpensive interval logic:

- exterior words seed convex arcs of the disk circle;
- boundary-aligned images propagate through internal interfaces with opposite convexity;
- a smooth radius-R arc cannot cross a hard exterior corner;
- a positive-length atom cannot be forced both convex and concave;
- a mapped image cannot be forced to overlap an opposite-sign known interval;
- ambiguous non-aligned images are recorded and left to Nielsen--Levi.

The old `preword.circular_arcs` import remains as a compatibility wrapper.

### 2. Joint metric/radius/turn system

`formal_disk4.preword.linear_invariants` introduces, for every atomic interval:

```text
l_i > 0                    atomic length
r_i+ >= 0, r_i- >= 0       convex/concave radius-R measures
r_i+ + r_i- <= l_i
H_i in R                   disk-circumference-scaled smooth turn
```

The system combines:

- all compiled interface-length equations;
- convex/concave measure exchange across internal interfaces;
- forced whole-atom radius-R decorations from structural propagation;
- physical smooth-turn cancellation across internal interfaces;
- `tile_count * (L_plus - L_minus) = C_disk`;
- `tile_count * smooth_turn = 2*pi`;
- the isoperimetric necessary condition;
- strict positive radius-R concavity only for maps declaring a Stein configuration.

The scaled variable `H_i = C_disk * K_i/pi` keeps the radius-R relation linear:

```text
H_i = +2*l_i   convex radius-R arc
H_i = -2*l_i   concave radius-R arc
```

### 3. Separate point-turn system

Point turns do not share variables with lengths, so they remain in a smaller exact LP. It contains:

- the local interior/outer map-vertex equations;
- strict point-turn bounds;
- `sum(point turns on one tile) = 2 - 2/tile_count`.

### 4. Exact rejection policy

HiGHS is used only as a fast screen. A pre-word linear case is rejected only after the rational simplex proves that the maximum strict margin is non-positive. Floating-point errors can therefore only miss pruning opportunities, not remove a valid case.

The topology module follows the same policy for every LP-dependent interval rejection. Unexpected pre-word exceptions are logged and the word system is conservatively allowed through.

### 5. General problem hypotheses

`PlanarMap` now carries `ProblemHypotheses`:

```text
piecewise_c2_boundary
center_strictly_inside_one_tile
```

`k4-central` enables the Stein hypothesis and therefore requires a strictly positive concave radius-R measure. `k3-pizza` and `k4-pizza` do not enable it, so their convex sector solutions remain valid.

### 6. Terminal model aligned with the same invariants

For piecewise-C2 maps, the terminal exact angular system now uses the stronger split equations:

```text
sum(signed smooth curve turns) = 2/tile_count
sum(point turns) = 2 - 2/tile_count
```

The older single total-winding equation remains only as a fallback for maps that do not declare piecewise-C2 boundary regularity.

### 7. Configuration and statistics

The new configuration key is:

```json
{
  "filters": {
    "preword_pruning": {
      "enabled": true,
      "topology": {
        "enabled": true,
        "enable_endpoint_crossing": true,
        "max_intervals": 1024
      },
      "linear_invariants": {
        "enabled": true,
        "enable_radius_measures": true,
        "enable_smooth_turns": true,
        "enable_point_turns": true,
        "enable_isoperimetric": true,
        "sqrt_upper_bound_denominator": 1000
      }
    }
  }
}
```

Version 0.8 `preword_circular_arcs` settings are migrated automatically. The obsolete standalone `enable_signed_balance` switch is intentionally ignored because the general radius-measure system replaces it.

Progress now reports `preword_pruned`. `run_summary.json` separates:

- topology and linear rejections;
- unresolved circular images;
- endpoint and overlap checks;
- exact metric and point-turn certificates;
- whether global radius, smooth-turn and point-turn balances were already derived from local equalities.

Disable the whole layer for differential debugging with:

```bat
run_profile_k4.bat --no-preword-pruning
```

The old `--no-preword-circular` flag remains a hidden compatibility alias.

## Checkpoint compatibility

Search semantics changed. Version 0.8.0 K4 checkpoints must not be resumed.

```bat
run_full_k4.bat --restart
```

Subsequent 0.9.0 sessions resume normally with:

```bat
run_full_k4.bat
```

## Validation

- 56 unit/integration tests pass.
- Pizza3 and pizza4 still pass formal search, exact decoration, numerical geometry and mapping-derived visualization.
- A final 10-second K4 profile visited 16,084 placement nodes and compiled 924 complete placements. The topology layer rejected 923 and the exact joint metric system rejected the remaining one before Nielsen--Levi.

This short profile covers only the beginning of the first canonical assignment; it validates cost and integration, not the eventual global rejection rate.
