# Patch 1.3.0 - Mirror-aware word equations

Apply this differential patch directly over version 1.2.1. Versions 1.2.2 and
1.2.3 were diagnostic-only experiments and are neither required nor included.

## Reflected contacts remain distinct in the word solver

The old compiler reduced every contact to an ordinary free-word equality and
attached reflection metadata only after Nielsen-Levi solving. This was too late:
a curve and its mirror image had already been identified as the same terminal
literal. A reflected circular component could therefore acquire a false
self-mirror relation and be forced to be straight.

The compiler now gives every atomic contour variable two sheets:

```text
X_i       direct image
M_X_i     mirror image
```

Direct contacts use ordinary reversal. Reflected contacts use the mirror sheet,
and the mirror image of each physical equation is compiled as well. The formal
profile builder then reconstructs an explicit mirror involution between terminal
curve templates before curve types and signed turns are inferred.

The legacy plain equations and public contact-mapping representation are kept for
preword filters and compatibility. No map-specific Figure 2b branch is present
in production code.

## Safe point-turn pruning for double cycles

The global point-turn balance at the atomic weak-order stage is not sound when
the word solver can later subdivide an atomic interval and introduce a genuine
corner at the new boundary. Figure 2b uses exactly such a subdivision, with a
`-pi/2` point turn.

A new granular option controls only that premature global equation:

```json
"enforce_global_point_turn_balance": false
```

It is disabled in both `double-cycle-6/search.json` and
`double-cycle-6/profile.json`. Local physical-vertex angle checks remain enabled.
All other cases retain the default value `true`.

The final decorated contour still has to satisfy the complete exact point-angle
system and total-turn identity, so this change removes only an unsafe early
pruning step.

## Figure 2b formal regression

A production-independent regression test hard-codes the supplied contour and
mappings:

```text
contour: A, C, C, A^-1, C^-1, A^-1
outer:   0-1   <-> 4-3
inner:   0-5-4 <-> 0-1-2
radial:  4-5-0 <-> 2-3-4
```

The test runs the complete formal path through preword pruning, mirror-aware word
compilation, exact-partial solving, specialization, decoration and final profile
filters. It verifies:

- point turns `120, 90, 0, 90, 120, -90` degrees;
- straight/circular pattern `A,C,C,A,C,A`;
- circular signs `+,+,-`;
- all three requested contact mappings;
- survival through every formal filter.

The numerical geometry solver is deliberately outside this regression.

## Checkpoints

The word semantics changed, so the search fingerprint is bumped. Start existing
case directories with `--restart`; a 1.2.1 checkpoint cannot be resumed under
1.3.0.

## Validation

- 74 tests pass.
- The exact Figure 2b mapping survives every formal stage.
- Existing direct-contact cases retain their stable `T0,T1,...` terminal naming.
