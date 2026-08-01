# formal_disk4_solver 1.9.1

## Added case: `k4-rotation-2`

This patch adds a new catalog case for the map with:

- four outer tiles forming a 4-cycle,
- one central tile touching all four outer tiles,
- imposed `rotation_2` equivariance on the formal search.

The new case is exposed in the GUI/pipeline catalog as:

- `k4-rotation-2`

It reuses the existing K4 search/geometry/visualizer configs and writes to:

- `output/cases/k4-rotation-2`

## Checkpoints

No existing case semantics are changed.

- Existing checkpoints for older cases remain valid.
- `k4-rotation-2` is a new case with its own output directory, so it starts with fresh checkpoints.
- There is no checkpoint-format change in this patch.
