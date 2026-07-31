# Formal Disk4 Solver 1.6.0 — intrinsic mapping symmetry quotient

This differential patch applies over version 1.5.1. Extract it directly at the
project root and allow existing files to be overwritten.

## Scope

Version 1.6.0 adds a canonical quotient of the combinatorial mappings that are
constructed before the incremental LP checks, the preword LP, and the exact word
equation solver.

The feature is localized in `formal_disk4.enumeration.symmetry` and connected to
the assignment and weak-order enumerators through small integration points.

## Search semantics and checkpoints

The formal search semantics version changes from `formal-contour-search-v12` to
`formal-contour-search-v13` because the enumerated domain and its order change.

Existing 1.5.1 formal-search checkpoints are intentionally incompatible with
1.6.0. Start the formal campaign in a new output directory or use the relevant
`--restart` / `--restart-all` option. The patch itself does not delete campaign
outputs.

Geometry checkpoints retain the 1.5.1 format and behavior.

## Quotient implemented

The mapping being quotiented is the complete pair:

- contour phase/orientation assignment;
- weak cyclic order of occurrences, hence the complete offset mapping.

The implementation:

1. certifies the declared combinatorial automorphisms of the map;
2. computes their finite group closure;
3. when an equivariance is imposed, keeps only intrinsic automorphisms commuting
   with it, a conservative subgroup preserving the restricted search domain;
4. removes the subgroup already imposed on every admissible mapping;
5. fixes the global cyclic cut through the reference occurrence when safe;
6. quotients assignments lazily under the anchor-preserving subgroup;
7. quotients weak-order prefixes under the assignment stabilizer before the
   incremental LP checks;
8. quotients complete mappings before `compile_word_case`, the preword LP, and
   the exact word solver.

If imposed equivariance is not enforced on weak orders, cyclic reanchoring is
disabled conservatively. This may retain duplicates but cannot remove a class of
solutions.

## Checkpoint design

Assignment enumeration remains random-access over raw mixed-radix slots. A
checkpoint stores the raw slot index, not a materialized canonical list. On
resume, noncanonical slots are skipped cheaply. This avoids building the whole
canonical assignment domain in memory and keeps restart behavior deterministic.

## Configuration

Intrinsic symmetry quotienting is enabled with `symmetry_mode: "incremental"`
in:

- `config/cycle_campaign/search.json`;
- `config/cases/double-cycle-6/search.json`;
- `config/cases/double-cycle-6/profile.json`.

## Validation

The test suite contains exhaustive small-domain checks that:

- partition all 1,584 raw mappings of `inner-cycle-boundary-points-3` into exactly
  528 symmetry orbits;
- produce exactly one quotient representative per orbit, with no missing orbit;
- verify that all members of each orbit compile to the same canonical word
  residual;
- verify conservative interaction with an imposed rotation;
- verify that assignment-only equivariance disables unsafe cyclic reanchoring;
- certify declared automorphisms on the 12 cyclic campaign maps of sizes 3–5;
- exercise the lazy raw-slot enumeration and campaign configuration.

Validation result: 101 tests passed, plus 12 subtests.

## Expected reduction of expensive calls

Exhaustive mapping counts with the standard cyclic imposed rotation and weak-order
equivariance, before LP and word solving:

| Family | Raw mappings | Quotiented mappings | Reduction |
|---|---:|---:|---:|
| `double-cycle-N` | 1,584 | 528 | 3.00x |
| `double-cycle-offset-N` | 14,400 | 3,600 | 4.00x |
| `inner-cycle-boundary-points-N` | 1,584 | 528 | 3.00x |
| `outer-cycle-center-points-N` | 5,256 | 1,752 | 3.00x |

These counts are the same for N = 3, 4, and 5 under the current imposed cyclic
search assumptions. Across the active size-3/4/5 suite, the total domain changes
from 68,472 to 19,224 mappings, an expected divisor of approximately 3.56 for
calls made after mapping construction.

This is a reduction in calls to the expensive stages, not a measured wall-clock
speedup. Fixed overhead, early pruning, and different costs per mapping will make
the total elapsed-time ratio differ.

## New counters

Search summaries now expose:

- `symmetry_pruned_assignments`;
- `symmetry_pruned_nodes`;
- `symmetry_pruned_leaves`;
- `canonical_assignments_processed`;
- `assignment_slots_in_domain`;
- `intrinsic_symmetry_group_elements`;
- `admissible_symmetry_group_elements`;
- `effective_mapping_symmetry_actions`.
