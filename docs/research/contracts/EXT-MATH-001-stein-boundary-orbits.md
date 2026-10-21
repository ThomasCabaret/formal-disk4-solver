# EXT-MATH-001 — Audit a boundary-orbit theorem for rotational Stein tilings

- Status: ready for external review; not submitted by this agent.
- Parent: `MATH-002`, under `MATH-001` and the disk-tiling objective `R0`.
- Requested output: a rigorous conditional proof, a counterexample, or a precise
  unresolved gap. Please challenge the argument rather than assume it is true.
- Everything essential is stated below; repository access is not required.

## Problem

Let `D={x in R^2: |x|<=1}` with center `O=0`, and let a finite family of `N>1`
congruent compact Jordan regions tile `D`: their interiors are pairwise disjoint
and their union is `D`. Reflected congruent copies are allowed. Assume
`O in int(C)` for one tile `C`. No smoothness, rectifiability, connected internal
interfaces or normality is assumed.

Let `R` be the rotation about `O` by `2pi/m`, where integer `m>=2`, and assume
`R` permutes the actual geometric tiles. Its order is exactly `m`; it need not
be the maximal rotational order of the tiling. This is a geometric symmetry,
not merely a permutation of an abstract graph.

An outer tile has `S_T = T intersect boundary(D)` containing a circular arc of
positive length. An outer orbit is an `R`-orbit of such tiles. Point-only
contacts and empty outer traces must not be counted as outer orbits.

Audit the claim that:

1. `C` is fixed by `R` and every other tile has orbit size `m`.
2. At least two distinct noncentral orbits are outer. In particular,
   `N=1+km` for an integer `k>=2`.
3. Two tiles `A,B` in distinct outer orbits admit an isometry `h` with
   `h(A)=B` and `h(O)=O`.

Do not replace this by a proof for polygons, normal tilings or finite contact
complexes. If such an extra hypothesis is necessary, identify exactly where.

## Permitted external premises

For the conditional audit, take the following as explicit premises, including
their validity for arbitrary tile congruences:

- P1: Every nonempty `S_T` is a connected circular arc (a point is allowed).
- P2: Transporting `S_T` to a congruent tile `U` places it on `boundary(conv(U))`.
- P3: Two positive-length outer traces transported to the same tile are equal,
  or their relative interiors are disjoint and they intersect only at endpoints.

The source references for these premises are Kurusa–Lángi–Vígh,
[Tiling a Circular Disc with Congruent Pieces (2020)](https://link.springer.com/article/10.1007/s00009-020-01595-3),
Lemma 2.6 and Remarks 2.7–2.8. These premises are not the theorem requested
above. A complete unconditional audit should additionally verify their scope;
clearly separate that task from checking the implication P1–P3 -> claims 1–3.
Brouwer's fixed-point theorem and elementary convex-perimeter facts may be used
if their applications are justified.

## Proposed argument to inspect

This is a proposed proof from an AI-authored working note, not an established
result you must accept.

The central tile is unique. Every other Jordan tile omits `O`, since a boundary
point is a limit of interior points. Thus `R(C)=C`. If a noncentral tile has
orbit size `d<m`, it is fixed by a nonidentity `R^d`. Brouwer applied to that
tile forces a fixed point, necessarily `O`, a contradiction. This proves 1.

By P1, `C intersect boundary(D)`, if nonempty, is a connected circular arc
invariant under `R`. It must be the whole circle. A Jordan region inside `D`
containing that circle must equal `D`, which is impossible with other tiles.
Consequently `C` is compactly inside `D`. Its convex hull lies in some concentric
disk of radius `r<1`, so `perimeter(conv(C))<=2pi*r<2pi`.

The positive-length exterior traces cover the circle except for finitely many
endpoints and have disjoint relative interiors, giving total length `2pi`.
After arbitrary congruences to `C`, P2–P3 imply a coincidence between two of
these transported traces: otherwise their total length would force
`perimeter(conv(C))>=2pi`. Empty and point traces are excluded from this sum.

Choose the transports equivariantly within each outer orbit. Given representative
`T`, take an isometry `f:C->T` and set

```
T_j = R^j T
f_j = R^j f R^(-j) : C -> T_j
Gamma = f^(-1)(S_T)
f_j^(-1)(S_(T_j)) = R^j Gamma.
```

The supporting unit circle of `Gamma` has center `q=f^(-1)(O)`. If
`R^j Gamma=R^l Gamma`
for distinct indices modulo `m`, equality of their supporting circles implies
`R^(j-l)q=q`, hence `q=O`. Then `f(O)=O` puts `O` in `int(T)`, impossible.
Therefore the forced coincidence is between two different orbits, proving 2.

If transports `phi_A:A->C` and `phi_B:B->C` give the same positive-length
trace, let `h=phi_B^(-1) phi_A`. It maps `A` to `B` and a nondegenerate arc
of `boundary(D)` onto another such arc. A circle is determined by three points,
so `h` fixes its center `O`, proving 3.

## Output and acceptance criteria

- Check every implication, especially the Jordan/topological steps, perimeter
  comparison, point-only traces, arbitrary reflected transports and the
  equivariant formula. Distinguish a proof gap from an actual counterexample.
- State whether the three conclusions follow conditionally on P1–P3. If a
  premise fails, identify the precise weakening and the conclusions it affects.
- If claiming an actual counterexample, provide a verifiable geometric tiling
  or exact construction with congruence and coverage checks. A graph or a
  numerical failed search is insufficient. An unresolved proof step is also
  a useful answer; there is no requirement to force a yes/no conclusion.
- Do not assume the existence or nonexistence of a Stein tiling. Do not use
  the unproved stronger bound `k>=3` or the separate two-orbit dihedral theorem.

## Integration after an answer

The owner can paste the answer back into the project. Preserve it verbatim or
with a precise source reference, then review it before changing theorem status
or code. A valid proof supports the graph-domain premise; it still does not
audit how code recognizes it. A gap/counterexample calls for a scoped local
audit of `RSS-OVERLAP`/`RSS-ORB` and their premise detectors. No response leaves
the audit available locally; it does not block independent witness validation.
