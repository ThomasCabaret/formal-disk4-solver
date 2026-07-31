# Formal Disk4 Solver 1.8.0

This differential release implements two isofunctional search-performance improvements.

## Incremental radius-arc topology pruning

The two expensive complete-placement topology rejections are now also available during the weak-order DFS:

- a mapped circular arc is forced to cross a hard outer endpoint;
- a mapped circular arc is forced to overlap an interval with the opposite circular sign.

The prefix filter uses only paths and boundaries that are already stable under every descendant of the current DFS node. Unresolved paths are omitted. A negative result therefore removes a complete subtree; an inconclusive result keeps it.

The existing complete preword topology filter remains in place as the final check. The new prefix implementation is isolated in `src/formal_disk4/preword/prefix_topology.py`.

New run counters include:

- `prefix_topology_checks`;
- `prefix_topology_cache_hits`;
- `prefix_topology_pruned_nodes`;
- reason-specific `prefix_topology_rejection_*` counters;
- `prefix_topology_errors` (errors are conservative and keep the subtree).

## Exact equality elimination before rational simplex

`HybridMarginOracle` now performs exact rational Gaussian elimination on all equalities before calling the exact simplex. Pivot variables are substituted into the remaining inequalities and non-negativity domains, leaving the simplex only the actual free dimensions.

This does not alter the LP, its exact optimum, or the pruning rule. It is a smaller exact representation of the same feasible set.

## Validation and measurements

- 123 tests passed, plus 16 symmetry-certification subtests.
- 80 deterministic random exact LP systems matched the former simplex exactly in feasibility, status and rational optimum.
- 97 LP systems reached during `double-cycle-4-rotation-2` matched the former implementation exactly; exact-solver time fell from 7.51 s to 0.59 s (12.69x).
- A complete `inner-cycle-boundary-points-3` search produced the same 9 formal profile IDs before and after the patch. DFS nodes fell from 1,338 to 1,250.
- On a 30-second `double-cycle-4-rotation-2` sample, accounted weak-order mass increased from 3,798 to 10,198 (2.68x). The prefix filter rejected 2,312 DFS nodes before complete-placement processing.

## Compatibility

No checkpoint schema or search fingerprint changes. Existing 1.7.4 formal checkpoints can be resumed; the new pruning is applied only to the remaining search.
