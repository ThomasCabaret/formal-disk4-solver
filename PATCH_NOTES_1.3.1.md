# Patch 1.3.1 - Smooth subdivisions of disk-boundary arcs

Apply this differential patch over version 1.3.0.

## Fixed false geometric survivors

A solved word may refine one declared outer interface into several terminal
curve occurrences. Those occurrences are subdivisions of one arc of the disk
circle, not independent arcs joined by corners.

The decorator now locates every terminal boundary strictly inside each expanded
outer interface and imposes the exact equation

```text
alpha_B = 1*pi
```

at each such boundary. Equivalently, the signed point turn is zero. The two
endpoints of the outer interface are unchanged and retain their normal map
vertex angles.

The equations are added after word specialization, when all solver-introduced
subdivisions are known. They are not an early weak-order approximation.

## Regression coverage

The geometric survivor `geo-d693c8601dd9b3e5e26e04cd18634b90` is reconstructed
from its exact assignment, placement and finite word environment. Its outer
interface expands into four circular occurrences with three non-smooth internal
corners, and it is now rejected during exact angle decoration.

The existing Figure 2b regression still passes. Its subdivided exterior arc has
zero point turn at the internal subdivision and remains formally accepted.

## Checkpoints

Search semantics are bumped to `formal-contour-search-v12`. Restart an existing
search so previously emitted false survivors are removed and all placements are
redecorated under the new constraint.

## Validation

- 76 tests pass.
- The `d693` false survivor is rejected before numerical geometry.
- The Figure 2b formal witness still passes every formal stage.
