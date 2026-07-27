# Patch 0.2.1 - compact persistence and resumable search

This patch is differential against version 0.2.0. Extract it into the existing project root and allow overwriting.

## Corrections

### No power expansion by default

The default family expansion policy is now:

```json
{
  "policy": "none",
  "maximum_exponent": 1
}
```

Finite/pure families still produce one concrete specialization. Power and nested-power families remain symbolic, are counted, and do not enter the decorated-profile pipeline unless expansion is explicitly enabled with `minimum`, `fixed`, or `range`.

### No unbounded low-level output

The following streams are disabled in the default, benchmark, full and enumeration-only configurations:

- `word_case_audit.jsonl`;
- `word_families.jsonl`;
- `unsupported_word_components.jsonl`;
- `placements.jsonl`.

They remain available for debugging through independent `write_*` flags. Every optional stream has a global record cap that remains effective after resumed sessions. `errors.jsonl` is capped at 1000 records by default.

### SQLite checkpoint and automatic resume

Every normal run now creates `checkpoint.sqlite3` in its output directory. It stores:

- one search checkpoint row;
- the current map and assignment cursor;
- a compact weak-order DFS cursor of at most fifteen subset masks;
- cumulative counters and timings;
- only fully surviving profile payloads.

It does not store rejected placements, word systems, residual solver states or explored nodes.

The checkpoint is updated approximately once per minute, immediately at the first safe point, at assignment boundaries, and on clean interruption or exit. Running the same command again resumes automatically. Runtime limits may be changed between sessions.

Use:

```bat
run_full_k4.bat --restart
```

to discard the checkpoint and survivor database for that output directory.

### Survivor durability

SQLite is authoritative for survivors. A survivor is committed once under a unique profile key before it is appended to `candidates.jsonl`. On resume, `candidates.jsonl` is rebuilt from SQLite, preventing both loss and duplicate records at interruption boundaries.

Existing `candidates.jsonl` files from pre-checkpoint runs are imported rather than silently erased, unless `--restart` is used.

### Progress estimate

The progress line now reports:

- overall percentage across canonical assignments;
- current assignment percentage;
- assignment index;
- usual pruning and solver counters.

The percentage uses the exact number of raw weak-order leaves below every completed or pruned DFS subtree. It is monotone but is not a wall-clock ETA.

### Cumulative benchmark sessions

`elapsed_seconds`, counters and timings resume cumulatively. `session_elapsed_seconds` reports only the current invocation. A configured time limit applies to the current invocation, so repeated benchmark runs continue the same search rather than stopping immediately.

## Validation

- 23 unit and integration tests pass.
- A two-session run resumed the same weak-order cursor without replaying completed placements.
- Default output contained only `checkpoint.sqlite3`, `candidates.jsonl`, `errors.jsonl`, `effective_config.json`, and `run_summary.json`.
- The checkpoint database remained approximately 16 KiB without survivors.
