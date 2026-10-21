# MATH-004 — Boundary constraints with more than two moving orbits

## Identity

- Node / parent: `MATH-004` / `APP-IMP`.
- Path: `R0 -> APP-IMP -> MATH-004`; restricted-case mathematical study,
  sibling generalization of `MATH-003`, with shared dependency `MATH-002`.
- Track: `MATH`; status: supported-in-scope for a conditional necessary-condition
  draft, not general nonexistence or independent acceptance. Opened and bounded
  iteration completed 2026-10-21 by repository agent (LLM).
- Root benefit: replace a small-orbit obstruction by a general necessary
  condition, or delimit why that obstruction cannot generalize.

## Question and hypotheses

Can outer circular arcs and intrinsic tile rotation constrain arbitrary numbers
of moving orbits, rather than only the two-orbit architecture?

Complete unit disk; finitely many congruent compact Jordan tiles with disjoint
interiors; one tile contains the disk center strictly inside; an actual geometric
rotation of order `m>=2` permutes the tiles. Reflections are allowed. No chosen
graph, connected pairwise contacts, boundary smoothness or maximality of `m`.
Intrinsic order-`m` tile symmetry is deduced from the center tile, not separately
imposed. Free patches and asymmetric Stein tilings are outside scope.

The owner explicitly asks to defer independent proof validation. Existing
`MATH-002`/`MATH-003` arguments remain unaccepted drafts. Any use of their trace
or sector conclusions must be conditional and visible; this study will not
silently promote them or use the two-orbit exclusion as a certified premise.

## Decision context

- Parent decision: is there a general disk-specific obstruction worth pursuing,
  rather than counting one small orbit architecture at a time?
- Selected by owner over the previously proposed independent proof review.
- Alternatives: immediately enumerate three-orbit graphs; implement the draft
  filter; or change research approach. A general geometric constraint has more
  potential leverage and does not require code or a new enumeration engine.
- Support: a necessary condition valid for arbitrary orbit counts supplies a
  new mathematical tool and possibly a later representation-level reduction.
- Failure: identify the specific global symmetry/sector implication lost when
  extra orbits are present, and return to the parent without extrapolating.
- Inconclusive: retain an explicit subproblem, not a nonexistence conclusion.

## Evidence plan

- Read the existing proof drafts and distinguish local tile geometry from
  facts depending on the complete two-orbit partition.
- Investigate supporting-circle multiplicities, intrinsic rotations, and
  disk-containment inequalities for the outer arcs.
- Stop after one bounded analytical iteration with a derivation or explicit
  remaining obstruction. No solver/training run or implementation change.
- Basic algebra/finite examples may check transcription, not certify a tiling.

## Reproduction

- Starting revision: `47338241bceae92573e683e4ca557fb28f2c9eb2`, clean tree.
- Sources: `docs/two_orbit_stein_obstruction.tex`,
  `docs/rotational_stein_structural_note.tex`, and the two linked study records.
- No independent reviewer or accepted external contract. No random seed or
  performance benchmark planned.

## Results

Artifact: [stein_boundary_multiplicity.tex](../../stein_boundary_multiplicity.tex).
All numbered statements there are proposed proof drafts. The stronger boundary
consequences explicitly assume connected outer traces, denoted `(CT)`. The
previous `MATH-002` argument proposes to derive `(CT)` in this domain, but this
iteration does not independently review it. The `MATH-003` two-orbit exclusion
is **not** used as a premise.

### 1. Weighted repetition replaces a single coincidence

Let `r<1` be the common circumradius, normalized to outer disk radius one.
For each outer rotational orbit choose an equivariant congruence from the
central tile. Group the transported supporting-circle centers modulo the
intrinsic order-`m` rotation of that tile. Write `s_a` for the number of outer
orbits in one group and `alpha_a` for their common outer-arc length.

Conditional on `(CT)`, circle coverage and convex perimeter give

```text
m * sum(s_a * alpha_a) = 2*pi
m * sum(alpha_a) <= perimeter(conv(C)) <= 2*pi*r.
```

Thus the arc-length-weighted mean repetition multiplicity is at least `1/r`.
Some single matching group contains at least `ceil(1/r)` outer orbits, and
the total number `b` of outer orbits is at least that large. This holds for
arbitrary `k`, not only two moving orbits. It is non-strict at integer
thresholds; for example `r<1/2`, not merely `r<=1/2`, forces at least three.

Each such group consists of genuinely center-fixing congruent tiles. The
chart-based grouping need not find all possible equivalences if the prototile
has additional symmetries; the inequality holds for the stated grouping
without claiming it is a complete geometric classifier.

### 2. Mirror capacity applies even with additional interior orbits

Suppose reflection `s` in a line through the big disk center maps one
noncentral tile `A` to a tile `B` in a **different** rotational orbit.
This need not be a symmetry of the rest of the tiling, and the pair need
not even be outer.

The reflections `R^j s` map `A` to distinct tiles, so their axes cannot cross
its interior. Hence `A` is confined to a wedge of angle `pi/m`. This inference
does not require the two-orbit reduction or `(CT)`.

For `m>=3`, put

```text
c = cos(pi/m)
lambda = c / sin(pi/(2*m))
F_m = 1 + lambda^2 + 2*lambda*c.
```

The convex hull of a farthest-point intrinsic rotation orbit contains the
disk of radius `r*c` around the tile circumcenter `P`. Wedge containment
therefore forces `d=|P| >= lambda*r`. One of those farthest-point directions
is within `pi/m` of the direction of `P`; containment in the outer unit disk
then gives `1 >= d^2+r^2+2*d*r*c >= F_m*r^2`.

Consequently **`r<=1/sqrt(F_m)` and `N>=F_m`**. The latter follows from
`pi <= N*pi*r^2` by measure subadditivity, not an assumption of equal area
shares or zero-area Jordan boundaries. These bounds need no connected-trace
premise. The full derivation is `prop:mirror` in the TeX source.

### 3. Combining the two gives a general orbit-count dichotomy

Conditional on `(CT)`, the reflected-pair hypothesis forces

```text
some matching group size s_a >= ceil(sqrt(F_m))
b >= ceil(sqrt(F_m))
k >= ceil(sqrt(F_m)).
```

Illustrations (floating-point values are not certified numerical intervals):

| m | F_m, approximately | Upper circumradius | Minimum outer orbits from formula | Minimum N=1+km from this consequence |
| --- | --- | --- | --- | --- |
| 3 | 3.000000 | 0.577351 | 2 | 7 |
| 4 | 7.027339 | 0.377229 | 3 | 13 |
| 5 | 12.090170 | 0.287597 | 4 | 21 |
| 6 | 17.991707 | 0.235757 | 5 | 31 |
| 8 | 32.176724 | 0.176291 | 6 | 49 |
| 12 | 70.059805 | 0.119472 | 9 | 109 |

The order-three row alone does not exclude the two-orbit case and is weaker
there than the earlier sector/lens draft; it is not a regression or a use of
that unaccepted exclusion. The general improvement concerns larger orders.

For order five the non-rounding argument is exact:
`F_5=(13+5*sqrt(5))/2>9`, so a mirror pair requires at least four outer
orbits. Therefore any hypothetical three-moving-orbit order-five Stein tiling
must avoid **all** center-fixing mirror pairs between different moving orbits.
It is not excluded entirely: center-fixing rotation matches remain possible.

Asymptotically `sqrt(F_m)/m -> 2/pi` and `F_m/m^2 -> 4/pi^2`. Thus this
mirror branch needs a number of outer orbits growing at least linearly with
symmetry order, and a total tile count growing at least quadratically. These
are necessary-count statements within the named hypotheses, not complexity
results or an existence theorem.

### 4. Exact obstruction to extending the old argument

If **every** noncentral tile is outer and all are rotations about the big disk
center of one fixed tile, their equal arcs form a regular circle subdivision.
The rotation taking each arc to its successor then permutes all noncentral
tiles and preserves the unique remaining central tile. It would give a
one-moving-orbit tiling for a larger rotation, contrary to the conditional
multiplicity bound. This excludes that architecture for arbitrary `k`.

But with additional interior tiles the outer-shell rotation preserves only
the **union** of the remaining region. It does not automatically preserve the
individual inner tiles or the center tile. This is the precise implication
that cannot be copied from the old two-orbit proof. We have not shown it is
false for actual Stein tilings, and we have not proved that it must hold.

### Scope controls and checks actually performed

- Reflections between the **same** rotational orbit are excluded from the
  mirror-capacity premise: an axis could then preserve a tile, and the wedge
  argument would not follow. No graph automorphism is substituted for an
  actual Euclidean reflection.
- Convex hulls are used only to derive necessary containment/area bounds;
  no convexity of the original tiles is assumed.
- At `m=2`, the inradius factor is zero. No nontrivial capacity is claimed;
  this argument does not use the older separate lens proof.
- For `m=3`, an equilateral triangle in the wedge with one vertex at the big
  disk center attains the local bound `r=1/sqrt(3)`. It is not a valid Stein
  peripheral tile, because it contains that center. This checks the geometric
  constants but supplies no tiling witness.
- The other root research approaches remain open. No existing solver was
  changed or run, and no rejection filter was enabled. Geometric quantities
  such as `r` and the reflection pairing are not generally known from a bare
  contact graph, so no immediate runtime improvement is asserted.
- No independent reviewer accepted these proofs. The owner-directed deferral
  of independent review does not promote either old or new drafts to facts.

### Reproduce the small arithmetic check

Python 3, standard library only; no generated dataset is needed:

```python
import math

for m in (3, 4, 5, 6, 8, 12):
    c = math.cos(math.pi / m)
    lam = c / math.sin(math.pi / (2 * m))
    f = 1 + lam * lam + 2 * lam * c
    b = math.ceil(math.sqrt(f))
    print(m, f, 1 / math.sqrt(f), b, 1 + m * b)

c = math.cos(math.pi / 5)
lam = c / math.sin(math.pi / 10)
assert abs(1 + lam * lam + 2 * lam * c - (13 + 5 * math.sqrt(5)) / 2) < 1e-12
```

Executed with the bundled Python 3.12.14 at
`C:/Users/thoma/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`.
The radical/formula discrepancy was `1.78e-15`. This is a transcription check,
not independent mathematical validation or a numerical discovery experiment.

Additional checks in this iteration: 146 local research Markdown links resolve;
all 17 agenda-node paths reach `R0` without a cycle; the new TeX's four labels
and references resolve and its environments nest correctly; `git diff --check`
passes. For `m=3,...,200` and 33 equally spaced phases per order, sampled
regular-polygon supports satisfied `max_j cos(theta+2*pi*j/m)>=cos(pi/m)`
(minimum floating-point slack zero). These checks do not replace the analytic
argument or independently accept any proof. The TeX was not compiled to PDF
in this iteration. No generated run data or additional dependency was created.

Bounded prior-art queries on 2026-10-21 were
`"Stein" "tiling" "circumradius"` and
`"disk" "monohedral" "reflection" "orbits"`.
They returned the already indexed
[KLV journal source](https://link.springer.com/article/10.1007/s00009-020-01595-3)
and unrelated material, not an identified matching theorem. This does not
establish novelty; no additional literature fact is used as a premise.

## Interpretation and return to parent

- The generalization attempt delivered a weighted boundary condition and a
  local mirror-capacity bound, rather than universal Stein nonexistence.
- `APP-IMP` gains a conditional many-orbit dichotomy: sufficiently few orbits
  force the centered-match route to be orientation-preserving. A new branch
  of the proof is therefore explicit instead of silently assuming every
  centered match produces reflection axes or a global symmetry.
- `RSS-MULT`, `RSS-MIRROR-CAP`, `RSS-MIRROR-ORB` and `RSS-ROT-SHELL` are indexed
  as proof drafts with separate trace dependencies. No code consequence yet.
- Continuation decision: continue the mathematical branch, not implementation
  or a postponed independent audit. Next bounded question: classify the
  orientation-preserving centered-match cases with three moving orbits,
  especially two outer plus one interior orbit, or three outer in more than
  one direct matching class. Seek a concrete contradiction or identify the
  extra geometry permitting them; do not assume shell symmetry extends inward.
- If only arc-count arithmetic remains and no new geometric constraint is
  obtained, return to `APP-IMP` to reconsider another obstruction or approach.
- Agenda, registry, backbone, state and decision `D-014` record the scoped
  return; independent review remains deferred, not claimed complete.
