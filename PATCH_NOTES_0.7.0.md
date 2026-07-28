# Patch 0.7.0

This differential update applies on top of version 0.6.1.

## Four-piece pizza validation map

A new registered map, `k4-pizza`, describes four congruent sectors meeting at one interior vertex. The internal piece-contact graph is the cycle `P0-P1-P2-P3-P0`; every piece owns one outer circular arc.

The map uses the same generic pipeline as `k3-pizza` and `k4-central`. It defines:

- 4 pieces;
- 5 geometric vertices;
- 4 internal interfaces;
- 4 outer interfaces;
- 12 prototype occurrences;
- the 8-element dihedral automorphism group of the four-cycle.

The first canonical placement gives the expected quarter-sector profile:

```text
T0^-1 T1 T0
```

with central angle `pi/2`, exterior arc length `1/4*C_disk`, exterior-arc turn `pi/2`, and two complementary free outer angles.

## Windows launchers

Added:

- `run_pizza4.bat`;
- `run_pizza4_geometry.bat`;
- `run_pizza4_visualizer.bat`;
- `run_pizza4_pipeline.bat`;
- `scripts/run_pizza4_pipeline.ps1`.

The complete validation command is:

```bat
run_pizza4_pipeline.bat --restart
```

## Short K4 profiler

Added `run_profile_k4.bat` and `config/profile_k4.json`. The profile uses the normal K4 solver limits, performs no checkpointing or high-volume output, and stops after approximately 20 seconds.

The exact-partial solver now accepts an external stop predicate. Time limits can therefore stop inside a large residual graph. `run_summary.json` now reports stage shares and LP oracle time/cache data.

The development profile showed that the exact-partial word solver consumes about 96% of the elapsed time. Length pruning remains highly effective and should stay before the weak early angle filter.

## Validation

The formal four-piece pizza survivor, numerical piece realization and mapping-driven four-copy assembly were validated. The reconstructed interface error was approximately `1.7e-16`.
