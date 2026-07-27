# Recommended next steps after 0.3.1

## Proof-grade preprocessing

1. Replace the remaining SciPy strict-feasibility LP calls with an exact rational backend while retaining the oracle interfaces and cache keys. Terminal equality reduction is already exact over rational numbers.
2. Export positive witnesses and infeasibility certificates.
3. Run bounded differential tests with symmetry on and off, then compare canonicalized placements and word systems.

## Exact-partial word language

1. Add proof objects for every residual transition and compiled power loop.
2. Recognize additional sound cycle normal forms without unfolding them.
3. Canonicalize redundant nested-power parameterizations and merge equivalent families.
4. Add shared residual-graph caches for identical canonical six-equation systems.
5. Distinguish global time interruption from per-system graph, expression and family limits.

## Formal profile reduction

1. Generalize decorated-path subsumption to arbitrary contact-mapping lists and distinguished point roles.
2. Canonicalize complete decorated mappings under contour rotation/inversion, signed variable renaming, map automorphisms and global reflection.
3. Maintain an online antichain of primitive profiles rather than exact duplicate removal only.

## Geometry

1. Send the exported common-circle equations to a polynomial backend.
2. Add chord variables, vector closure and global copy-isometry consistency.
3. Add signed curve areas and `outer_area = 4 * tile_area`.
4. Add rational relaxations before nonlinear Z3.
5. Add numerical realization and a validated disk-center-in-central-piece test.

## More planar maps

Implement a planar-map generator for admissible contact multigraphs and plane embeddings. Each output should compile to `PlanarMap`, leaving all lower layers unchanged.

## Performance

1. Profile residual-graph canonicalization separately from branch generation.
2. Store compact bit-packed length rows and signed-angle equations.
3. Add process-level parallelism over canonical copy assignments.
4. Persist checkpoints at assignment boundaries.
5. Add configurable rejection logging and histogram summaries without slowing release benchmarks.
