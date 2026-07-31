# formal-disk4 solver 1.8.1

This release adds a first declarative family of nine-tile, three-ring cyclic maps.
It does not change the search, pruning, word, geometry, visualization, or checkpoint semantics of existing cases.

## New pipeline cases

All cases impose `rotation_1` equivariance on three tile orbits of size 3:

- `three-ring-parallel-3`
- `three-ring-boundary-points-3`
- `three-ring-outer-offset-3`
- `three-ring-inner-offset-3`
- `three-ring-offset-same-3`
- `three-ring-offset-opposite-3`

The first five contact patterns cover parallel and antiprism-style offset couplings between adjacent layers. The last offset pair distinguishes equal and opposite chirality. The boundary-point variant opens the outer tile cycle: middle tiles reach the disk boundary at the junction between two outer arcs, while the middle and inner layers remain cycles.

The cases are discovered dynamically from:

`config/case_families/cyclic-three-ring.json`

No additional launcher script is required; search, geometry, and visualization tasks are available directly in the pipeline GUI.

## Map implementation

The maps are localized in:

`src/formal_disk4/maps/three_ring_families.py`

The generic builder supports sizes greater than or equal to 3, although this release exposes only size 3 because it is the nine-tile family relevant below the known twelve-tile construction.

Only certified cyclic rotations are declared. No reflection quotient is assumed for these new maps.

## Validation

- 130 tests passed.
- 34 subtests passed.
- Each new map satisfies the disk Euler invariant `V - E + F = 1`.
- Each declared `rotation_1` action is certified against the full combinatorial map.
- All six search configurations started successfully in bounded end-to-end smoke runs.
