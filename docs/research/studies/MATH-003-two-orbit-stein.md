# MATH-003 — Can two moving orbits form a rotational Stein tiling?

Update after the first iteration: [MATH-002](MATH-002-outer-trace-audit.md)
supplied an area-free outer-trace proof for the interior-circumcenter class,
which contains all rotational Stein candidates here. The integrated TeX no
longer assumes P1–P3; the conditional statements below preserve the first
iteration's rationale and are superseded in that respect. Independent proof
review and novelty remain pending. No program filter was changed.

## Identity

- Node / parent: `MATH-003` / `APP-IMP`.
- Path: `R0 -> APP-IMP -> MATH-003`; restricted-case mathematical investigation.
- Track: `MATH`; status: supported-in-scope for the proof-draft deliverable,
  first bounded iteration completed 2026-10-21. Independent acceptance pending.
- Investigator: repository agent (LLM); independent review not yet performed.
- Root benefit: exclude an entire rotational Stein architecture, or identify
  exactly why the proposed obstruction cannot exclude it, before more search.

## Question and hypotheses

Can a disk tiled by `2m+1` congruent compact Jordan regions, `m>=2`, have one
tile containing the disk center in its interior and an actual rotational
symmetry of order `m` with exactly two noncentral tile orbits?

The boundary is the complete circle, not a free patch. Reflections are allowed.
No graph, embedding, connected pairwise interfaces or boundary smoothness is
assumed. Intrinsic symmetry of the tile is to be deduced from the central tile,
not added as an unrelated restriction. This is a Stein subcase, not all known
nontrivial disk tilings. A negative result here cannot exclude larger orbit
counts or tilings without rotational symmetry.

## Decision context

- Selected by the owner following the explained proposal. The local rotational
  Stein note claims a strong two-orbit sector reduction and explicitly leaves
  its exclusion unresolved.
- Parent decision: can this class be removed mathematically, and which
  geometric freedoms survive if it cannot?
- Alternatives: broad existence/classification arguments or another search
  representation. This small class offers a precise disk-specific proof target
  without relying on the present enumerator or introducing another engine.
- Success: a scoped obstruction, with proof dependencies and review status.
- Counterexample to a reduction: withdraw only that reduction and reconsider
  the obstruction; a diagram/abstract graph is not a tiling counterexample.
- Inconclusive: record the exact surviving configuration or missing inequality,
  return to `APP-IMP` and reassess rather than extend the attempt indefinitely.

## Evidence plan

1. Check the external statements and local steps of `RSS-OVERLAP`, `RSS-ORB`
   and `RSS-2ORB` needed for this specific argument.
2. Attempt a geometric contradiction using the intrinsic tile symmetry,
   congruence, circular outer trace and sector confinement.
3. Challenge endpoints, reflected congruences, order two, and any use of
   smoothness or connected internal interfaces. Seek a simpler independent
   formulation of each proposed new implication.

One bounded analytical iteration; stop with a proof draft, a defective premise,
or an explicit unresolved step. No solver experiment, implementation change or
unbounded computation is authorized by this study. Return to the parent before
starting another research direction.

## Reproduction

- Starting revision: `b4bab9012ca2d2bcee1d64c92366c67ccf09c3bf`; working tree
  clean before creating this record.
- Source: `docs/rotational_stein_structural_note.tex`, especially `lem:overlap`,
  `thm:main`, `thm:twoorbit` and its open-target section.
- Shared dependency: `MATH-002`; optional `EXT-MATH-001` is prepared, not sent.
- Published premise checks: [KLV primary preprint, v1](https://arxiv.org/html/1910.03836),
  Lemma 2.6 and Remarks 2.7–2.8, read with the general-`n` scope preceding them;
  no independent end-to-end proof audit of that paper was performed.
- Proof artifact: [two_orbit_stein_obstruction.tex](../../two_orbit_stein_obstruction.tex).
  Local normal-form deductions are restated there so the dependency chain is
  inspectable rather than assumed from the earlier note's word "audited".
- Independent check: [EXT-MATH-002](../contracts/EXT-MATH-002-two-orbit-obstruction.md)
  is ready, not submitted. No outside reviewer or second agent accepted this proof.
- No numerical tiling search, hardware-dependent benchmark or random seed.
  Auxiliary double-precision identity checks, not proof certificates, ran using
  bundled Python 3.12.14 and only its standard library.
  The system `py.exe` launcher found no installed Python; SymPy was unavailable.
  No dependency was installed. The built-in TeX compilation request did not
  return a diagnostic before cancellation; no successful PDF build is claimed.

## Results

### 1. Dependency review

Rechecked the local chain conditional on the cited KLV facts: uniqueness and
rotation invariance of the center tile; full noncentral orbits by Brouwer;
strict convex-hull perimeter bound; coincidence of transported outer arcs;
equivariant transports preventing within-orbit coincidence; centered matching;
equal alternating outer traces for two orbits; reflective rather than rotational
matching; confinement between reflection axes. No gap in these local deductions
was found in this iteration. This is a local re-derivation, not independent
certification of KLV, `MATH-002`, or their implementation premise detectors.

One dependency can be removed outright: strict containment of the central tile
does not need outer-trace connectedness. If `|u|=1` for `u in C`, rotation
invariance gives zero mean for `R^j u`; for a congruence `f(x)=Qx+t` into
another disk-contained tile, the average squared norm of `f(R^j u)` is
`1+|t|^2<=1`. Thus `f(O)=0`, contradicting central-tile uniqueness. This
finite-orbit argument is included in the proof artifact and review contract.

**Specific unresolved external-premise risk:** the [journal proof of KLV
Lemma 2.6](https://link.springer.com/article/10.1007/s00009-020-01595-3)
and its primary preprint use area-equality steps. For the unrestricted Jordan
domain, disjoint interiors alone do not establish zero-area shared boundaries.
Whether the proof's additional geometric conclusions justify those equalities
was not resolved here. This is not a counterexample to the published lemma.
Record the two-orbit theorem as conditional on P1–P3 pending this audit; the new
sector lemma and the five-lens coverage bound do not have this dependency.

### 2. New obstruction draft

Let `beta=pi/(2m)`, `c=cos(beta)`, `s=sin(beta)`. Normalize an outer tile to
the sector `W={x>=0, |y|<=x*tan(beta)}`. It contains `u+=(c,s)`, `u-=(c,-s)`
and omits `O`. Congruence with the central tile gives intrinsic order-`m`
rotation about an interior point `P`. This symmetry is deduced, not assumed
independently of the tiling.

- Even `m`: the half-turn and the two vertical extrema force `P=(c,0)`.
- Odd `m`: the two sector-support normals are related by a power of the
  intrinsic rotation. Equal centered support values force `P=(p,0)`, `p>0`.
- In both cases, rotating `u+` clockwise through `2pi/m` gives a point `v` with

  `|v|^2-1 = 2p*(1-cos(4beta))*(p-1/(2c))`.

  Disk containment implies `p<=1/(2c)`.
- For even `m>=4`, `p=c` contradicts that inequality.
- For odd `m>=3`, the intrinsic rotation through `(m-1)*pi/m` sends `u+` to
  `(2pc-1)*(c,-s)`. Sector containment implies `p>=1/(2c)`, hence this point
  equals `O`, contradicting the Stein hypothesis for the outer tile.
- For `m=2`, the tile is in a unit-disk lens of area at most `pi/2-1`. Five
  congruent copies have union area at most `5*(pi/2-1)<pi`, so cannot cover `D`.
  This is measure subadditivity: **no zero-area boundary assumption or equality
  of tile area with `pi/5` is used**.

Thus the draft excludes two moving orbits for every integer `m>=2` and,
conditional on the reviewed orbit reduction, would strengthen `k>=2` to `k>=3`,
or `N>=3m+1`. Registry IDs: `RSS-SECTOR` and `RSS-2ORB-EXCL`. These are proof
drafts awaiting independent review, not newly certified production filters.

### 3. Attempts to break the argument

- Reflected congruences reverse the intrinsic rotation angle but preserve its
  cyclic subgroup. Both rotation signs used in the proof remain available.
- Order two is not smuggled into the `m>=3` rejection: its actual lens fits
  the quarter-disk and is centrally symmetric; the separate area bound matters.
- For `m=3`, the equilateral triangle `conv{O,u+,u-}` is a countercontrol if
  `O not in T` is omitted. The lemma therefore cannot reject a tile merely
  because the center is not in its interior; center-on-boundary cases differ.
- The argument needs the endpoint contacts and sector angle derived from the
  complete two-orbit disk. It has not been generalized to free boundaries,
  wider sectors, smaller outer arcs, or arbitrary graph automorphisms.
- Neither finite internal contacts nor differentiability is used. Convex hulls
  are used for support/perimeter facts, not to assume the tiles themselves convex.

### 4. Auxiliary checks and bounded prior-art search

For integers `m=2,...,200`, four choices of `p` per order gave the first
identity with maximum absolute discrepancy `6.67e-16`. The 396 applicable odd
checks of the rotated-ray identity had maximum discrepancy `3.35e-16`.
The 99 even orders `4,...,200` all sent the tested endpoint outside the disk.
These finite floating-point checks guard against algebraic transcription
errors; the analytic proof, not these samples, quantifies over every `m`.

The rational check `5 - (3/2)*(22/7) = 2/7 > 0`, with the classical strict
bound `pi<22/7`, confirms the direction of the five-lens area contradiction.

Representative prior-art queries (2026-10-21):

```text
"Stein" "tiling" "rotational" "two orbits"
"monohedral" "disk" "2m+1"
"Stein" "tiling" "dihedral"
site:arxiv.org "monohedral" "Stein" "rotational symmetry"
site:arxiv.org "disk" "tilings" "centrally symmetric" Stein
```

No matching primary result was identified by this bounded search. This does
not establish novelty or a complete contemporary literature frontier. The
search returned unrelated uses of "Stein" and later three-tile classification
papers; those were not treated as support for this proposed theorem.

### Reproduce the auxiliary checks

Run the following with Python 3 (standard library only). It is not a geometric
solver or an independent proof verifier:

```python
import cmath
import math
from fractions import Fraction

disk_error = ray_error = 0.0
for m in range(2, 201):
    beta = math.pi / (2 * m)
    c, s = math.cos(beta), math.sin(beta)
    u = complex(c, s)
    q = 1 / (2 * c)
    for p in (q * 0.8, q, q * 1.2, c):
        v = p + (u - p) * cmath.exp(-2j * math.pi / m)
        rhs = 2 * p * (1 - math.cos(4 * beta)) * (p - q)
        disk_error = max(disk_error, abs(abs(v) ** 2 - 1 - rhs))
        if m % 2:
            z = p + (u - p) * cmath.exp(1j * (math.pi - 2 * beta))
            ray_error = max(ray_error, abs(z - (2 * p * c - 1) * complex(c, -s)))
    if m % 2 == 0 and m >= 4:
        assert abs(c + (u - c) * cmath.exp(-2j * math.pi / m)) > 1
assert max(disk_error, ray_error) < 1e-12
assert 5 - Fraction(3, 2) * Fraction(22, 7) == Fraction(2, 7)
print(disk_error, ray_error)
```

## Interpretation and return to parent

- The bounded task delivered a complete proposed proof, not an algorithm or
  another search run. It is new work in the repository; independent validity
  and literature novelty remain separate pending questions.
- `APP-IMP` gains a candidate exclusion of one entire class, not general Stein
  nonexistence. Without rotation or with three or more moving orbits, nothing
  is settled by this proof. No known weaker nontrivial family is excluded.
- Next bounded decision: review this proof, especially external premise scope,
  odd-order support normals and order-two measure arguments, before any extension
  or code change. The self-contained `EXT-MATH-002` contract supports optional
  owner-mediated independent review; preparing it does not send it or block
  other justified research.
- Keep the other root approaches open. Do not automatically start `k=3`, change
  a graph generator, or resume learning. A failed review returns to the exact
  affected lemma and parent decision, not to an unqualified impossibility claim.
- `AGENDA.md`, `HISTORY.md`, `STATE.md` and the result registry record the draft
  and review boundary. Original mathematical sources and run data are preserved.
