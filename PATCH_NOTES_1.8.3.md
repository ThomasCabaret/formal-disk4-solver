# Patch 1.8.3 — Compact word-search core and terminal-contour cutoff

This patch replaces the production exact-partial word solver's hot residual
representation with packed integer tokens and adds an optional physical cutoff
on the minimum forced terminal contour length.

Apply it over version 1.8.2 with all solver processes stopped.

## Compact residual representation

The hot Nielsen graph no longer represents each residual occurrence as a
`Literal(variable="V12", inverse=...)` object backed by a string. A literal is
now one integer token:

```text
token = (dense_variable_id << 1) | inverse_bit
variable_id = token >> 1
inverse(token) = token ^ 1
```

Residual words, equations, substitutions, transitions, cycle signatures, and
expression-arena atoms therefore use tuples of integers throughout the search.
Text-labelled public objects are reconstructed only at rare boundaries such as
family emission, validation, and diagnostics.

The mathematical search graph and canonical ordering are preserved. On the
first real word system captured from `three-ring-parallel-3`, old and new
implementations visited exactly the same graph edges and emitted the same
finite family:

| Node limit | 1.8.2 | 1.8.3 | Speedup |
|---:|---:|---:|---:|
| 1,000 | 2.77 s | 0.91 s | 3.03x |
| 1,500 | 6.81 s | 2.06 s | 3.31x |
| 2,000 | 13.12 s | 3.52 s | 3.72x |

These figures measure one real system and are not a promise that every word
system will obtain the same full-run speedup.

## Configurable terminal-contour cutoff

The pipeline now defaults to:

```json
"solver": {
  "max_terminal_contour_segments": 100
}
```

Set the value to another non-negative integer to change the limit, or to
`null` to disable the cutoff.

The measured quantity is **not** the temporary residual literal count. It is a
lower bound on the total terminal-word length already forced for the original
physical contour variables `X_i`. Mirror variables are excluded. Because every
remaining residual variable is non-erasing, a branch is discarded only when
its current substitutions already imply:

```text
minimum forced direct-contour segments > configured limit
```

This is a deliberate restriction of the searched physical domain. A run that
uses the cutoff must not be interpreted as an exhaustive proof about contours
longer than the configured limit. If any branch is discarded for this reason,
the word case is reported as `restricted_terminal_contour_limit`, never as
`exact_unsat`.

## Heartbeat and statistics

During a word-system search, the heartbeat now includes fields such as:

```text
residual=4eq/19836lit terminal_min=73/100 terminal_pruned=412
```

- `terminal_min`: current lower bound for the direct physical contour;
- denominator: configured limit, or `None` when disabled;
- `terminal_pruned`: branches discarded by this limit in the current word
  system.

Campaign statistics also include:

```text
terminal_contour_pruned_branches
terminal_contour_limited_word_cases
```

## Checkpoint compatibility

The default search domain changed because the new cutoff defaults to 100.
Search-semantics version is therefore bumped from v13 to v14. Formal-search
checkpoints created by 1.8.2 are intentionally not resumable in 1.8.3; restart
those tasks. Set the cutoff to `null` when the unrestricted former domain is
required.

## Validation

- 132 tests pass.
- Python bytecode compilation passes for `src` and `tests`.
- Targeted equivalence checks preserve graph-node/edge counts and emitted
  families on the captured real `three-ring-parallel-3` system.
