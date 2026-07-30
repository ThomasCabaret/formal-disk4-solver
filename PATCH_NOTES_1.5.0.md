# Patch 1.5.0 - Staged geometry solver

Apply this differential archive directly over 1.4.0.

## Compatible entry points

All existing commands remain valid:

```bat
run_case.bat <case> geometry [options]
run_cycle_case.bat <family> <N> geometry [options]
run_cycle_suite.bat <suite> geometry [options]
```

The formal search, case maps, campaign orchestration, candidate JSONL schema and
geometric solution schema are unchanged. Geometry checkpoints may be restarted
independently with `--restart` or `--restart-all`.

## Staged solving

The numerical solver no longer performs sampled self-intersection and area
checks inside every least-squares residual evaluation.

1. **Closure stage:** propagate analytic endpoints and tangents, then solve only
   position/tangent closure plus cheap positivity and formal-turn guards.
2. **Validation stage:** build the requested final arc sampling and run all
   existing length, angle, area and self-intersection acceptance checks only on
   a closed candidate.
3. **Clearance fallback:** if a closed candidate is crossed or has negligible
   area, run a bounded coarse collision refinement, then repeat the unchanged
   final validation.

Fixed zero-dimensional candidates are still evaluated exactly once and valid
fixed candidates are accepted.

## Resource bounds

A real per-candidate wall-clock bound is added:

```json
"candidate_timeout_seconds": 20.0
```

A value of `0` disables the timeout. The existing keys now bound closure work:

```json
"max_restarts": 32,
"max_function_evaluations": 1000
```

`max_function_evaluations: 1` is now honored as one instead of being silently
raised to 100. New CLI overrides are available:

```bat
--candidate-timeout SECONDS
--max-function-evaluations COUNT
```

## Performance

On the previously supplied two-parameter `d693` record with eight arc samples,
the same accepted geometry is recovered in about 0.06 seconds locally instead
of the recorded 2.33 seconds. With 64 samples, the expensive sampling is paid
only once during final validation rather than at every optimizer evaluation.

## Validation

- fixed valid and fixed invalid geometry behavior is unchanged;
- the c3 pizza profile is still found and validates without intersections;
- final acceptance checks are unchanged;
- candidate timeout, one-evaluation limits and staged validation frequency have
  dedicated regression tests;
- 89 unit tests pass.
