# MATH-002 — Outer-trace connectedness and the area-equality question

## Identity

- Node / parent: `MATH-002` / `MATH-001`; supporting mathematical audit.
- Owning path: `R0 -> MATH-001 -> MATH-002`.
- Cross-dependency served: `R0 -> APP-IMP -> MATH-003`, whose two-orbit
  obstruction currently assumes the outer-trace premises.
- Track: `MATH`; status: supported-in-scope for a replacement-proof draft,
  bounded iteration opened and completed 2026-10-21; independent review pending.
- Investigator: repository agent (LLM); no independent acceptance implied.

## Question and hypotheses

Does the proof of connected outer traces in KLV Lemma 2.6 justify its area
equalities for congruent compact Jordan tiles with disjoint interiors, or can
that step be replaced for the rotational Stein class actually needed here?

Complete circular disk, finite congruent compact Jordan regions, reflections
allowed; no smoothness, zero-area boundary, connected pairwise interfaces or
prescribed graph. The general source lemma and the narrower rotational Stein
application must be distinguished. Intrinsic rotation is deduced only when
using the latter class. A free patch is outside this study.

## Decision context

The owner approved this dependency investigation after the first `MATH-003`
draft. It has priority over studying three orbits or changing a generator:
success could remove a named premise reservation; a gap would delimit the
obstruction's actual scope. This is not a new broad literature survey.

- Success: a justified source step or a self-contained replacement with its
  exact scope, propagated back to `MATH-003`.
- Failure of the source argument: identify a precise missing implication,
  not assert that the published lemma is false without a counterexample.
- Inconclusive: retain the conditional theorem and record the exact remaining
  subproblem or sufficient additional hypothesis.

## Evidence plan

Read the primary journal/preprint proof in context. Separate topological,
isometric and measure-theoretic dependencies. Attempt a replacement using
geometry/containment or the intrinsic symmetry already available in the Stein
subcase. Challenge positive-area boundaries and degenerate circle contacts.
Stop this analytical iteration with a repair, a scoped substitute or a precise
gap; do not launch solver experiments or expand into unrelated classification.

## Reproduction

- Starting revision: `a1e85b6367322318d70402becdf3b7d956c94fcd`; initial working
  tree clean.
- Primary source: KLV, DOI `10.1007/s00009-020-01595-3`, Lemmas 2.4–2.6 and
  Remarks 2.7–2.8; exact versions/URLs and consulted passages recorded below.
- Dependent draft: `docs/two_orbit_stein_obstruction.tex` and
  `docs/research/studies/MATH-003-two-orbit-stein.md`.
- No random seed, numerical discovery run or performance benchmark planned.
- External contracts remain prepared, not submitted by the agent.

## Results

### Source audit: the general area question was not settled

Consulted [the journal version](https://link.springer.com/article/10.1007/s00009-020-01595-3),
Lemma 2.6 from the gap/circumdisk argument through its final area equation,
and [the primary preprint v1](https://arxiv.org/html/1910.03836), same lemma.
Both use equality of tile area with an equal share of the disk/lens. Such
equalities are not a consequence of congruence and disjoint interiors alone
when Jordan boundaries can have positive planar measure. This iteration did
not determine whether all intermediate geometry of that source proof supplies
the needed additional justification. No counterexample to its lemma is claimed.

The useful outcome is instead a replacement in a class known to contain our
rotational Stein candidates. No general theorem was silently weakened and then
applied as if unrestricted.

### Replacement lemma: an interior circumcenter suffices

Proposed result `RSS-TRACE-IC`: in a finite monohedral tiling of the closed unit
disk by at least two compact Jordan regions, if the center of the prototile's
smallest enclosing disk is in its interior, every nonempty outer trace is a
closed connected circular arc (a point is allowed).

The full proof is now in [the mathematical source](../../two_orbit_stein_obstruction.tex),
`lem:circumtrace`. It uses no area equality or boundary-measure regularity:

1. Congruence gives every tile the same minimal enclosing radius `r<=1` and
   an interior circumcenter. If `r=1`, the unit disk is minimal for every tile;
   uniqueness would place all circumcenters, and hence all interiors, at the
   disk center. Thus `r<1`.
2. For a tile `A`, its circumdisk `B(a,r)` intersects the outer unit circle
   in at most one arc of angle less than `pi`. Indeed, for `|u|=1` membership
   requires `u dot (a/|a|) >= (1+|a|^2-r^2)/(2|a|)>0`; if `a=0` it is empty.
3. If `A` skips an outer subarc between two points `p,q` of its trace, join
   those points by a simple crosscut with all other points in `int(A)`.
   Together with the intervening circle arc it bounds a Jordan region `F`.
   Both curves lie in `B(a,r)`, so convexity gives `F subset B(a,r)`.
4. Another tile `U` contains a skipped circle point. Near that point, the
   bounded side of the loop is the disk side. Interior points of `U` accumulate
   there. Its connected interior cannot cross the loop: the circle part lies
   on the outer disk boundary; the crosscut lies in the other tile's interior.
   Hence `U subset F subset B(a,r)`.
5. The latter disk has radius `r`, which is also the minimal radius of `U`.
   Uniqueness makes it the circumdisk of both tiles. Its center would be in
   both interiors, contradicting disjointness.

Uniqueness of a minimal enclosing disk is elementary: the intersection of two
radius-`r` disks with distinct centers `a,b` is inside the disk centered at
`(a+b)/2` with smaller radius `sqrt(r^2-|a-b|^2/4)`.

### Why the extra hypothesis is available, not imposed, in MATH-003

The unique Stein center tile `C` is invariant under actual order-`m` rotation
about `O`. Put `r=max{|x|:x in C}` and take a point at that distance. Its
rotation orbit has mean zero. Any disk of center `a` and radius `t` containing
that orbit satisfies `t^2>=r^2+|a|^2`; thus `C`'s unique minimal enclosing
disk is centered at `O`, which is interior to `C`. Every congruent copy has
the same interior-circumcenter property, including reflected copies.

Consequently the replacement applies to all the rotational Stein tilings
considered in `MATH-003`, not merely to a smooth subclass or one graph.

### The other two trace facts can also be discharged locally

For a congruence `phi_i:T_i->U`, let `B_i=phi_i(D)`. A transported trace is
exactly `A_i=U intersect boundary(B_i)`, and `U subset B_i` puts it on
`boundary(conv(U))`. For two such traces, equal circles give equal complete
traces. Distinct equal-radius circles can meet arcs only at endpoints: an
interior transverse intersection would force one arc outside the other disk;
external tangency would reduce the disk intersection to a point, inconsistent
with `int(U)` nonempty. This proves the two transport facts without importing
KLV as a hypothesis for this class.

### Critical checks and limits

- The crosscut exists by a homeomorphism from a closed disk onto the Jordan
  tile: the image of a chord has precisely the required interior points.
- The trapped tile's **connected interior**, not its boundary, is the set to
  which Jordan separation is applied. Taking its closure gives the whole tile.
- Near a skipped circle point the crosscut stays away, since it is contained
  in the compact tile not containing that point. The loop is locally just a
  circular subarc, with its bounded region on the disk side.
- Containment of `F` in its boundary's convex hull, then in the circumdisk,
  does not assume the tiles themselves are convex.
- Empty and singleton traces cause no disconnected-trace argument. The
  disk-intersection formula treats these degenerate cases explicitly.
- Congruence is needed for the equality of minimal enclosing radii. An
  interior circumcenter is needed for the final interior-overlap contradiction.
  Neither can be dropped from this proof.
- No area measure is used in the replacement lemma. Positive-area boundaries
  therefore do not affect its argument. The separate order-two lens step in
  `MATH-003` still uses only measure subadditivity.
- No numerical test is claimed to certify this topological proof. No tiling
  search or software soundness audit was performed. The same agent derived
  and critically checked the argument; independent mathematical review remains
  pending, and literature novelty is not established.

## Interpretation and return to parent

- The bounded task found a scoped replacement rather than settling the
  published general area-equality question. That wider question remains open
  in this audit, but no longer blocks the stated rotational Stein argument.
- `MATH-003` now has a self-contained proof draft of `N=1+km`, `k>=3`, without
  extra outer-trace assumptions. The original geometric hypotheses and the
  independent-review reservation remain; this is not a certified impossibility
  theorem for all Stein tilings.
- `RSS-TRACE-IC` is indexed, and the earlier conditional statuses of the local
  orbit/sector deductions are updated to identify this replacement proof.
  Production code and its premise detectors are not changed or certified.
- Next bounded action: independent critical review of the integrated draft,
  especially crosscut trapping and the odd-order sector lemma. The updated
  `EXT-MATH-002` is ready for owner-mediated review, not submitted. Do not start
  the three-orbit case automatically or wait idly for an external answer.
- Parent/agenda, evidence snapshot and decision `D-013` record this return.
