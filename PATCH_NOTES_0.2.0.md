# Patch 0.2.0

Apply this archive over version 0.1.1 and allow existing files to be overwritten.

## Main changes

- Replaces the runner's depth-bounded word solver with an exact-partial residual-graph solver.
- Emits finite, fixed-context power and nested-power families.
- Cuts and records more complex iterative components without declaring them impossible.
- Adds configurable exponent specialization, defaulting to all values through 2.
- Replaces early unsigned angle variables with signed turn classes, including complementary angles under reversed copies.
- Resolves terminal point-angle equivalence/complement classes from the six mappings.
- Adds terminal curve-template components under identity/reverse/mirror/mirror+reverse.
- Forces self-mirror components straight.
- Adds strictly positive terminal component-length feasibility.
- Adds common-circle decorations and formal constraints for the three exterior arcs.
- Adds `word_case_audit.jsonl`, `word_families.jsonl`, and `unsupported_word_components.jsonl`.
- Prints `[SURVIVOR]` immediately for every profile written to `candidates.jsonl`.
- Adds per-stage benchmark timings and detailed family/decorations counters.
- Renames the user-facing assignment field `phases` to `cyclic_offsets`.
- Updates the project version to 0.2.0 and expands the test suite.

## Deliberately deferred

- rational exact LP certificates;
- cross-profile decorated subsumption;
- chord/closure/isometry/area constraints;
- polynomial Z3 solving and numerical realization;
- geometric disk-center containment.
