# Patch 0.9.1 — Early transported exterior-arc repetition

This differential patch applies on top of version 0.9.0.

## Purpose

For the supported four-piece Stein map shape, a theorem on exterior arcs transported to one prototile implies that at least two peripheral copies use exactly the same prototype boundary arc. The new filter enforces this necessary condition while the weak cyclic order is still being built, before length LPs, angle LPs, word compilation and Nielsen--Levi.

## Important assignment-count result

The 256 canonical K4 phase/parity assignments are not geometric rotations. They only choose contour orientation and the position of the common cyclic cut. Consequently the theorem does **not** reduce `256`:

```text
1536 raw assignments
256 canonical assignments
256 assignments still admitting at least one repeated exterior-arc pair
```

Among those 256 assignments:

```text
108 admit three cut-compatible candidate pairs
148 admit one cut-compatible candidate pair
```

The real pruning starts inside the weak-order DFS.

## Incremental rule

For each candidate pair, the two exterior edges are expressed in the common prototype direction. The pair remains possible only when:

- both corresponding start endpoints are still unplaced, or already occupy the same weak-order block;
- both corresponding end endpoints are still unplaced, or already occupy the same weak-order block.

A completed block can never receive a later occurrence. Therefore, once every candidate pair has separated at least one corresponding endpoint, no descendant can satisfy the theorem and the complete subtree is safely discarded.

## Guarded applicability

The filter activates only when the map data explicitly establish all current assumptions:

- exactly four pieces;
- `center_strictly_inside_one_tile = true`;
- the reference piece does not touch the outer boundary;
- exactly three outer interfaces;
- those interfaces belong to the three distinct peripheral pieces;
- each outer interface is one full piece edge.

It is therefore inactive for `k3-pizza`, `k4-pizza`, and any future map that does not expose this precise structure. The implementation does not test a map name.

## Configuration

```json
{
  "enumeration": {
    "exterior_arc_repetition": {
      "enabled": true
    }
  }
}
```

Disable only this theorem for differential profiling:

```bat
run_profile_k4.bat --no-exterior-arc-repetition
```

## Diagnostics

The progress line adds:

```text
outer_arc_pruned=...
```

The `counts` command reports assignment-level applicability and the number of cut-compatible candidate pairs:

```bat
.venv\Scripts\python.exe -m formal_disk4 counts --map k4-central --symmetry incremental
```

## Short differential benchmark

Two 10-second runs from the beginning of the first canonical K4 assignment gave:

```text
filter enabled:
  35,805 visited nodes
  18,098 exterior-arc prefix rejections
  1,586,428 raw weak orders accounted for
  0.5950% of assignment 1

filter disabled:
  24,185 visited nodes
  0 exterior-arc prefix rejections
  21,884 raw weak orders accounted for
  0.0082% of assignment 1
```

The processed-mass comparison is more meaningful than the raw node count: one early rejection can account for a very large untouched subtree.

## Checkpoint compatibility

The weak-order search semantics changed. Restart K4 searches created by 0.9.0:

```bat
run_full_k4.bat --restart
```

Subsequent 0.9.1 sessions can resume normally.

## Validation

- 59 unit and integration tests pass.
- Pizza3 and pizza4 remain unaffected because the filter is structurally inapplicable.
- `k4-central` reports 256/256 assignment-level compatibility, confirming that no unjustified phase assignment was removed.
