# Patch 1.8.2 — Search heartbeat and reproducible slow-state diagnostics

This patch adds a low-volume heartbeat to the formal search. It does not change
search semantics, pruning rules, enumeration order, checkpoints, or solver
limits.

## Runtime behavior

- While normal progress events are flowing, the existing progress line remains
  unchanged.
- At least once every 60 seconds, a separate daemon thread emits:
  1. the usual global progress line;
  2. a compact state line identifying the active stage, its elapsed time, the
     current assignment/placement/work identifier, and the most relevant
     module-specific counters.
- The heartbeat samples the Python stack of the main search thread. The state
  line therefore includes the active source file, line, and function even when
  the main thread is inside a long blocking call.

The default interval is 60 seconds. It can be shortened with:

```json
"progress": {
  "heartbeat_interval_seconds": 15
}
```

Values above 60 seconds are clamped to 60 seconds. The heartbeat can be disabled
explicitly with `"heartbeat_enabled": false`.

## Reproduction data

The latest full snapshot is atomically overwritten at:

```text
output/cases/<case>/diagnostics/heartbeat_latest.json
```

It contains, when available:

- map and active pipeline stage;
- assignment and placement identifiers;
- a deterministic word-system identifier;
- the current weak-order DFS path and counters;
- the complete current assignment, placement, and compiled word case;
- word-solver phase, residual size, graph nodes/edges, and trace tail;
- a short sampled stack of the main search thread.

A compact one-line history is appended once per heartbeat to:

```text
output/cases/<case>/diagnostics/heartbeat_history.jsonl
```

This history deliberately omits the full reproducer payload to remain small.

## Instrumented stages

- weak-order DFS and its incremental filters;
- word compilation;
- preword topology and linear-invariant phases;
- exact-partial word-solver initialization and internal phases;
- family processing and profile decoration;
- finalization.

## Validation

- 131 tests and 34 symmetry certification subtests pass.
- A live K4 smoke run confirmed heartbeats during a long LP call, including the
  exact SciPy/HiGHS stack location and the current weak-order path.
- A fixed-node K4 benchmark showed no measurable throughput regression with the
  heartbeat disabled.
