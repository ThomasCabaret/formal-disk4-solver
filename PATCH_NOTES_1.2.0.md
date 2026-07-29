# Patch 1.2.0 - Required cyclic equivariance for double-cycle searches

Apply this differential patch over version 1.1.0.

## Search semantics

The double-cycle family now imposes the map automorphism `rotation_1` by
default.  This is a search restriction, not merely a quotient of duplicate
solutions: the search only keeps assignments and weak cyclic orders fixed by

```text
E_i -> E_(i+1)
I_i -> I_(i+1)
```

The global default remains disabled, so `c3`, `c4` and all K4 Stein cases are
unchanged.

## Assignment reduction

A required automorphism decomposes the copies into piece orbits.  One
phase/parity sequence is chosen for each orbit representative and transported
to every other copy in that orbit.

For `double-cycle-6` this gives two orbits, exterior and interior:

```text
6,115,295,232 unrestricted assignments
24 cyclic-equivariant assignments
```

The implementation is generic over the configured map automorphism and works
for every `double-cycle-N` generated from the family template.

## Weak-order reduction

The same equivariance is enforced in the weak-order DFS.  Every coincidence
block advances a union of complete piece orbits.  Advancing only some rotated
copies would map one prototype point to a different prototype point and break
the imposed symmetry.

The twelve-copy order problem therefore reduces to two contour orbits of
lengths `(4,3)`:

```text
66 weak orders per assignment
1,584 weak orders over the 24 assignments
```

Exact progress percentages are enabled again for the default symmetric mode.

## Configuration and override

The double-cycle search and profile configurations contain:

```json
"cyclic_equivariance": {
  "enabled": true,
  "automorphism": "rotation_1",
  "enforce_weak_orders": true
}
```

Disable the restriction with:

```bat
run_case.bat double-cycle-6 search --restart --no-cyclic-equivariance
run_double_cycle_6_pipeline.bat --restart --no-cyclic-equivariance
```

The unrestricted mode automatically disables exact weak-order domain counting,
because the twelve-copy state lattice is prohibitively large.  Symmetric and
unrestricted checkpoints have different search fingerprints; use `--restart`
or separate output directories when switching modes.

Inspect the reduced domain with:

```bat
.venv\Scripts\python.exe -m formal_disk4 counts --map double-cycle-6 --symmetry off --cyclic-equivariance rotation_1
```

## Checkpointing

Required equivariance is included in the search fingerprint.  The SQLite cursor
continues to store an assignment index plus the compact weak-order DFS path.
Resume was tested across two bounded runs in the symmetric domain.

## Validation

- 69 unit tests pass.
- `double-cycle-6` reports 24 assignments and 1,584 exact weak orders.
- A default formal search reached a survivor in the second assignment during
  validation; this is only a formal survivor, not a certified geometric tiling.
- The unrestricted override restores the 6,115,295,232-assignment domain and
  starts without materializing it.
