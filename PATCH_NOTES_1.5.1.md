# Patch 1.5.1 - Conservative failure handling and geometry resume

Apply this differential archive directly over 1.5.0 by extracting it into the
project root and overwriting existing files.

## Non-blocking implementation errors are visible

Unexpected errors already handled by the formal pipeline remain non-blocking.
They no longer look like an entirely clean campaign:

- `run_summary.json` now contains `tainted`, `unexpected_error_count`, and
  `unexpected_errors_by_stage`;
- the existing stage-specific counters remain available;
- `errors.jsonl` records the exception type and traceback when error logging is
  enabled;
- a final `[TAINTED]` warning is printed to stderr.

The meaning of `stop_reason: completed` is unchanged.

## Geometry checkpoints never permanently skip an unresolved candidate

Geometry checkpoint schema version 2 no longer resumes from a permanent line
cursor. Every invocation rescans the formal candidate file and skips only
`formal_profile_id` values already present in `geometric_solutions.jsonl`.
Candidates for which no solution was found are retried on the next invocation.

This deliberately prefers harmless recomputation over a possible missed
solution. Existing version-1 geometry checkpoints are migrated automatically:
the old `next_line` cursor is discarded and unresolved candidates are rescanned.
Persisted solutions remain idempotent across crashes and reordered/rebuilt input
files.

`max_candidates` now limits solver attempts in the current invocation, so a
resumed invocation can retry previous failures.

## Conservative floating-point LP pruning

The weak length and angle LP oracles now prune only on an exact contradiction
implemented by the oracle:

- the existing same-sign length contradiction remains certified;
- inconsistent angle equalities are checked over rational arithmetic;
- LP backend exceptions, unsuccessful/ambiguous statuses, zero strict margins,
  and unverified floating witnesses return an inconclusive result that keeps the
  branch.

This may admit additional false positives for later exact/formal stages, but a
floating-point LP failure cannot remove a solution.

## Validation

Regression tests cover:

- non-blocking campaign taint reporting and traceback output;
- retry of an unresolved candidate after resume;
- automatic migration of a version-1 geometry checkpoint with a stale
  `next_line` cursor;
- conservative handling of LP backend exceptions and negative statuses;
- exact angle-equality contradictions remaining prunable.

All 95 unit tests pass.
