# Patch 1.2.1 - Fixed-geometry fast rejection and streaming CLI overrides

Apply this differential patch over version 1.2.0.

## Zero-dimensional geometry

The geometry solver now checks the dimension of its numerical parameter vector
before calling SciPy.  When the vector is empty, the current curve-template
model defines exactly one contour.  Repeating random restarts cannot modify that
contour, so the solver evaluates it once and never calls `least_squares`.

Closure is checked before sampled self-intersection validation.  A fixed contour
that does not return to its initial point or tangent is rejected immediately:

```text
fixed geometry failed closure precheck: closed_contour
```

The first `double-cycle-6` survivor has no formal or template-shape parameters.
Its deterministic closure error is approximately `8.238466e-2`, so it is now
rejected in a few milliseconds with:

```text
attempts=0
optimizer_attempts=0
fixed_candidates_evaluated=1
```

If a zero-dimensional contour passes closure, the normal complete geometry
validation still runs once.  A valid fixed contour is recorded with optimization
method `deterministic_fixed_geometry`.

## Continue formal search after survivors

The formal CLI accepts:

```text
--continue-after-profile
```

It overrides `limits.stop_on_first_profile` without changing other cases.  The
`double-cycle-6` search configuration now has no numerical profile cap, while
still stopping on the first profile by default.  Therefore this command runs
continuously until interrupted or another explicit limit is reached:

```bat
run_case.bat double-cycle-6 search --restart --continue-after-profile
```

Resume the same formal checkpoint later with:

```bat
run_case.bat double-cycle-6 search --continue-after-profile
```

## Geometry over the current candidates file

The geometry CLI accepts:

```text
--continue-after-solution
```

This processes every candidate currently available instead of stopping on the
first geometric solution.  Run it in another terminal with:

```bat
run_case.bat double-cycle-6 geometry --restart --continue-after-solution
```

The geometry reader exits when it reaches the current end of `candidates.jsonl`.
If the formal search appends more candidates later, rerun without `--restart`:

```bat
run_case.bat double-cycle-6 geometry --continue-after-solution
```

Its line checkpoint resumes at the first newly appended candidate.

## Scope

This patch does not yet solve closure feasibility when free parameters exist.
That future pre-geometry stage would need to solve the two positional closure
equations over the remaining parameters before testing self-intersection.

## Validation

- 73 unit tests pass.
- The known fixed `double-cycle-6` survivor is rejected with zero optimizer
  attempts and a closure-only precheck.
- `--continue-after-profile` emitted multiple profiles in a bounded test run.
- Geometry checkpoint resume continues to accept an input file that grows by
  appended formal candidates.
