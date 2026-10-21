# EXT-MATH-002 — Challenge the two-orbit Stein obstruction

- Status: ready for external review; not submitted; no external answer received.
- Parent: `MATH-003`, path `R0 -> APP-IMP -> MATH-003`.
- Purpose: independently check a proposed new obstruction, not endorse it.
- Requested result: a rigorous audit, counterexample or exact proof gap. Treat
  all assertions below as candidates. Literature novelty is a separate issue.

## 1. Tiling question

Let `D={x in R^2: |x|<=1}`, `O=0`. A finite family of congruent compact Jordan
regions with pairwise disjoint interiors covers `D`. Reflections are allowed;
no smoothness, rectifiability, zero-area boundary, connected internal contact
or finite embedded graph is assumed. One tile `C` contains `O` in its interior.
Rotation `R` through `2pi/m`, integer `m>=2`, permutes the actual geometric
tiles; it need not generate their maximal rotation group.

The proposed theorem excludes exactly two noncentral `R`-orbits, hence excludes
`N=2m+1`. Combined with the separate at-least-two-orbits reduction, it would
give `N=1+km`, `k>=3`, not general Stein nonexistence.

## 2. External premises and claimed reductions

For a conditional audit take these published premises as explicit assumptions:

- P1: each nonempty `S_T = T intersect boundary(D)` is a connected circular arc,
  possibly a point.
- P2: any congruence transporting an outer trace to a tile `U` puts it on
  `boundary(conv(U))`.
- P3: positive-length outer traces transported to the same tile either
  coincide or intersect only at endpoints.

The source is Kurusa–Lángi–Vígh, *Tiling a Circular Disc with Congruent Pieces*,
DOI [10.1007/s00009-020-01595-3](https://doi.org/10.1007/s00009-020-01595-3),
[primary preprint](https://arxiv.org/html/1910.03836), Lemma 2.6 and Remarks
2.7–2.8. Check applicability separately from the conditional deductions.

Specific premise-audit question: the preprint and journal proof of Lemma 2.6
use area equalities for congruent tiles. Their validity for arbitrary Jordan
boundaries of positive planar measure needs justification in that proof's exact
configuration. Disjoint interiors alone do not justify equal area shares.
This is not asserted to refute the lemma. Please identify whether its geometry
already supplies the missing justification, the argument can be repaired, or
an additional regularity assumption is needed. Keep this separate from the
elementary sector lemma, which does not use P1–P3 or any area equality.

The proposed reduction is:

1. Every noncentral Jordan tile omits `O`, even on its boundary, since its
   interior would otherwise accumulate inside `int(C)`. Thus `R(C)=C`.
   Brouwer applied to any noncentral tile fixed by a nonidentity power of `R`
   would force `O` into it. Every noncentral orbit therefore has size `m`.
2. P1 and rotation invariance force the central outer trace to be empty; the
   alternative is the whole circle, which would force `C=D` by Jordan
   separation. Thus `C` is in a concentric radius-`r` disk, `r<1`, and its
   convex hull has perimeter `<2pi`. Positive outer traces partition the outer
   circle up to finitely many endpoints and have total length `2pi`.
3. P2–P3 force a coincidence after transport to `C`. For each outer orbit use
   `f_j=R^j f R^(-j):C->R^j T`, with `f:C->T`. Transported traces are
   `R^j Gamma`, `Gamma=f^(-1)(S_T)`. Their unit-circle centers are `R^j q`,
   `q=f^(-1)(O) != O`. Distinct traces in one orbit cannot coincide. A forced
   coincidence is therefore between different orbits; composing its two
   transports gives an isometry between two tiles fixing `O`.
4. With exactly two noncentral orbits, both are outer. The centered matching
   forces equal trace lengths, hence every trace has length `pi/m`. The two
   orbits alternate on the circle.
5. A matching between adjacent traces is a rotation `rho` of angle `pi/m` or
   reflection `s` in their common endpoint radius. If it is `rho`, then
   `rho^2=R`, so `rho` swaps the two orbits and preserves their union and the
   remaining central tile. This contradicts step 3 for the larger rotation
   group, under which all noncentral tiles form one orbit. Thus matching is
   reflective; `R,s` preserve the tiling. The central tile is the closure of
   the complement in `D` of the other tiles, so preservation of those tiles
   does indeed preserve it.
6. Every reflection `R^j s` sends a tile of the first outer orbit to a distinct
   tile of the second. Its fixed axis cannot meet that tile's interior.
   Connectedness of the Jordan interior therefore confines the outer tile to
   one sector between the axes, of angle `pi/m`. Its outer trace is the full
   outer arc of that sector, since the angles agree.
7. Each outer tile `T=f(C)` inherits intrinsic rotation through `+/-2pi/m`
   about `P=f(O) in int(T)`. Both signs generate the same cyclic subgroup.

Alternative for the central-containment part of step 2, avoiding P1: if
`u in C` has `|u|=1`, then the orbit `R^j u` has zero mean. For any other
tile `f(C) subset D`, `f(x)=Qx+t` gives
`1 >= (1/m)*sum_j |Q R^j u+t|^2 = 1+|t|^2`. Hence `t=f(O)=O`, which would
put `O` inside both tiles. Thus `C` is strictly inside `D` independently of
the outer-trace connectedness claim. The remaining uses of P1 still need audit.

Please check that no hidden maximal-order, normality or connected-contact
assumption enters these steps.

## 3. Proposed elementary sector lemma (the new core)

Set `beta=pi/(2m)`, `c=cos(beta)`, `s=sin(beta)` and

```text
W = {(x,y): x>=0, |y|<=x*tan(beta)}
u+ = (c,s), u- = (c,-s).
```

Claim: for `m>=3`, no compact set `T subset D intersect W` can contain `u+`
and `u-`, omit `O`, and be invariant under rotation of order `m` about
`P in int(T)`.

Candidate proof:

- For even `m`, the half-turn is intrinsic. The extrema of the vertical
  coordinate of `T` are `-s,s`, so `P_y=0`. The half-turn image of `u+` is at
  height `-s`; the only point of `D intersect W` there is `u-`. Thus `P=(c,0)`.
- For odd `m`, put `K=conv(T)`, `n+=(-s,c)`, `n-=(-s,-c)`. Its support
  function satisfies `h_K(n+)=h_K(n-)=0`. Rotation by
  `theta=(m-1)*pi/m`, a power of the intrinsic rotation, sends `n+` to `n-`.
  Hence `h_(K-P)(n+)=h_(K-P)(n-)`, so `P dot (n+-n-)=0` and `P_y=0`.
- Write `P=(p,0)` in both cases, with `p>0`. Rotate `u+` clockwise through
  `2pi/m=4beta` about `P`, giving `v in T subset D`. Expansion gives

  `|v|^2 - 1 = 2p*(1-cos(4beta))*(p - 1/(2c))`.

  Therefore `p<=1/(2c)`.
- For even `m>=4`, `p=c` and `c^2>1/2` contradict this bound.
- For odd `m>=3`, rotating `u+` counterclockwise through `theta` gives

  `z=(2pc-1)*(c,-s) in T`.

  Since `z in W`, `2pc-1>=0`. Hence `p=1/(2c)` and `z=O`, contradicting
  `O not in T`.

Challenge every sign, equality case, support-function step and implication.
The core uses endpoints only; it must not silently require convexity of `T`.

## 4. Exceptional order two

For `m=2`, the even-case argument still gives `P=(1/sqrt(2),0)`. The sector
lemma itself is not an obstruction: the centrally symmetric lens
`D intersect (2P-D)` fits this quarter-sector and contains both endpoints.
Instead `T subset D intersect (2P-D)` bounds its area by `pi/2-1`.

There are five congruent tiles. Measure subadditivity gives

`pi = area(D) <= sum area(T_i) <= 5*(pi/2-1) < pi`.

The strict inequality follows from `pi<10/3`. This does **not** assume tile
areas equal `pi/5`; Jordan boundaries can have positive area. Check the lens
bound and that the coverage argument does not need boundary measure zero.

## 5. Acceptance and integration

Separate: (A) the new elementary lemmas, (B) deductions from P1–P3, and (C)
the external premises' applicability to the broad Jordan domain. A proof only
for smooth boundaries or connected contacts does not establish the stated
theorem. Give explicit counterexamples to any overstrong intermediate claim,
or identify exact missing steps without inventing a negative/positive answer.

Also check whether this obstruction is already known; no novelty claim is made
from a bounded web search. A returned audit remains a candidate until checked
here. Do not suggest enabling a rejection filter before that review and a
separate code-premise audit. The contract's preparation does not submit it to
any external service or block independent research.
