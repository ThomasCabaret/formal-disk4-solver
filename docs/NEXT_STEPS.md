# Recommended next steps after 0.6.0

## Proof-grade preprocessing

1. Replace the remaining **early placement** SciPy strict-feasibility LP calls with an exact rational backend while retaining the oracle interfaces and cache keys. Terminal joint point/curve-turn/length feasibility is already exact.
2. Export compact infeasibility certificates for the exact terminal system.
3. Run bounded differential tests with symmetry on and off, then compare canonicalized placements and word systems.

## Exact-partial word language

1. Add proof objects for every residual transition and compiled power loop.
2. Recognize additional sound cycle normal forms without unfolding them.
3. Canonicalize redundant nested-power parameterizations and merge equivalent families.
4. Add shared residual-graph caches for identical canonical word systems.
5. Distinguish global interruption from per-system graph, expression and family limits.

## Formal profile pruning

1. Add inexpensive symbolic chord closure and forced-point-coincidence filters.
2. Construct the assembled exterior contour formally and check its tangent/translation holonomy.
3. Generalize decorated-path subsumption to arbitrary contact-mapping lists and distinguished point roles.
4. Canonicalize complete decorated mappings under contour rotation/inversion, signed variable renaming, map automorphisms and global reflection.
5. Consider an online partitioned antichain only after measuring duplicate/subsumption rates on real K4 output.

## Geometry

1. Use a two-stage optimizer: solve formal metric/angular closure first, then enable collision barriers only for near-valid self-intersecting candidates.
2. Add multi-resolution generic templates, beginning with zero intermediate points and increasing only after failure.
3. Supply a sparse analytic or structured finite-difference Jacobian.
4. Add process-level parallelism over independent formal candidates with a single result collector.
5. Add signed area and disk-center tests after single-piece realization.

## Polynomial layer

1. Add chord variables and vector closure.
2. Add global copy-isometry consistency and exterior-circle center constraints.
3. Add signed curve areas and `outer_area = piece_count * tile_area`.
4. Use rational relaxations before nonlinear Z3.

## More planar maps

Implement a planar-map generator for admissible contact multigraphs and plane embeddings. Each output should compile to `PlanarMap`, leaving all lower layers unchanged.
