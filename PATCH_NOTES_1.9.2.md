# formal_disk4_solver 1.9.2

## Critical correction of `k4-rotation-2`

The 1.9.1 catalog entry was wrong: it reused the four-piece K4 map (one central
piece plus three peripheral pieces), which neither matches the requested
five-piece topology nor declares `rotation_2`.

Version 1.9.2 replaces that entry with the correct map:

- four outer pieces `P0,...,P3` forming a contact 4-cycle;
- one fully internal central piece `C` touching all four outer pieces;
- four outer boundary arcs;
- the complete dihedral `D4` automorphism group;
- a certified half-turn named `rotation_2` with `P0 <-> P2`, `P1 <-> P3`,
  and a half-turn action on the central contour.

The GUI case id remains `k4-rotation-2` for compatibility, but the actual map
name is now `wheel-4` (contact graph W5).

## Cyclic-shift equivariance

A fixed central piece cannot use the old pointwise weak-order equivariance:
that mechanism would require opposite central vertices to occupy the same
prototype point.  The new `cyclic_shift_equivariance` mode constructs one
fundamental half of the prototype contour and obtains the second half by the
certified `rotation_2` occurrence permutation.

This gives an exact half-turn-invariant weak order rather than a late heuristic
filter.  The mode currently supports orientation-preserving order-two actions
without fixed contour occurrences, which is exactly the new wheel case.

## Checkpoints

- Existing checkpoints for every pre-existing case remain valid: no default
  configuration key or checkpoint schema was changed.
- The failed 1.9.1 `k4-rotation-2` run used a different map and configuration.
  Its output/checkpoint directory must be restarted or replaced.
- A GUI "Fresh run" already passes `--restart` and is sufficient.

## Validation

- 141 tests passed.
- The new map has 5 pieces, 8 vertices, 8 internal interfaces, 4 outer
  interfaces and 20 contour occurrences.
- All 8 declared D4 automorphisms are certified on contours, incidences and
  interfaces.
- A real bounded CLI smoke run started `k4-rotation-2` and traversed 500 search
  nodes without error.
