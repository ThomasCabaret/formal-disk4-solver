# Mathematical results registry

Updated 2026-10-21. This file is the central index for mathematical claims used
or proposed by the project. Full statements and proofs remain in their editable
TeX sources; this registry does not duplicate them or silently rewrite them.

The project owner identifies these sources as largely AI-generated mathematical
work. During the 2026-10 restart, none of the proofs below was independently
rechecked end to end. A source calling itself “audited” records an earlier
internal audit claim, not a new independent certification.

## Status vocabulary

- **Source proof present:** the TeX contains an argument, but this registry has
  not validated it.
- **Externally dependent:** the proof invokes a published result that must be
  checked against its original statement and hypotheses.
- **Implemented reference:** code explicitly cites or embodies the claim.
- **Tests present, not rerun:** relevant tests exist in the working tree; this
  inventory did not execute them.
- **Candidate:** proposed mathematics or algorithmic reading; not an active
  sound rejection merely because it appears in a document.
- **Open / conjectural:** no complete proof is claimed in the source.

Proof status and implementation status are independent. A correct theorem can
be misdetected in code; passing tests cannot establish a theorem.

## Published landmarks identified by MATH-001

These are statement-level source checks, not independent proof certifications.
Precise hypotheses and versions are in [the literature map](LITERATURE_FRONTIER.md).

| ID | Source and recorded role | Status |
| --- | --- | --- |
| `HW-CONSTR` | Haddley–Worsley, sections 3–6: constructive disk families; their full-classification conjectures remain separate. | Source constructions located; witnesses not yet replayed here. |
| `KLV-3` | Kurusa–Lángi–Vígh, Theorem 1.1: classification with at most three Jordan tiles in the circular disk. | Published statement checked; proof not independently audited here. |
| `NV-3` | Nagy–Vígh, Theorem 1.2: normal three-tile classification with explicit target and tile regularity. | Hypotheses checked; no promotion to an unrestricted theorem. |
| `BL-3` | Basit–Lángi, Theorem 1: two/three-tile classifications of regular polygons. | Statement checked; different target boundary. |

For `RSS-OVERLAP`/`RSS-ORB`, the initial restart matched KLV labels to primary
statements and re-derived the local deductions conditionally. The subsequent
[MATH-002 iteration](studies/MATH-002-outer-trace-audit.md) supplied an area-free
replacement in the interior-circumcenter class, which contains rotational Stein
tilings. The integrated local proof no longer assumes KLV's outer-trace facts.
Independent acceptance and implementation premise-detector audits remain
pending. No external contract has been submitted or accepted by this agent.

## New proof drafts from MATH-003 and MATH-002 — independent review pending

Source: [two_orbit_stein_obstruction.tex](../two_orbit_stein_obstruction.tex).
The [study](studies/MATH-003-two-orbit-stein.md) records scope, attempted
falsification and auxiliary checks. These are new proof drafts in this project,
not certified literature novelty, production filters, or independent audits.

The initial tiling draft was conditional on KLV outer-trace premises. The
replacement below removes that dependency for the stated rotational Stein
class without imposing smoothness. The general area-equality question in the
published proof remains unresolved in this audit; no counterexample is claimed.
Removing a premise reservation is not independent proof certification.

| ID | Proposed result | Exact domain and dependencies | Proof/review status and code use |
| --- | --- | --- | --- |
| `RSS-TRACE-IC` | In a monohedral tiling of the circular disk by at least two compact Jordan regions, an interior circumcenter of the prototile forces every nonempty outer trace to be a closed connected arc. | The circumcenter means the unique center of its smallest enclosing disk, not a centroid or arbitrary intrinsic-symmetry point. Congruence, Jordan interiors and complete circle boundary are used; no area equality, smoothness or connected internal contacts. Rotational Stein tiles satisfy the extra condition by a zero-mean orbit argument. | Full area-free draft, `lem:circumtrace`, in the same TeX; `MATH-002` records the crosscut/containment review. Independent acceptance and novelty pending. No code use. |
| `RSS-SECTOR` | For `m>=3`, an intrinsically order-`m` rotational compact set inside a unit-disk sector of angle `pi/m`, containing both outer endpoints and omitting the disk center, is impossible when its rotation center is interior to the set. For `m=2`, central symmetry confines it to a lens of area at most `pi/2-1`. | Actual intrinsic Euclidean rotation, exact sector/endpoints and disk containment. No convexity of the set, boundary smoothness, connected contacts or graph restriction. | Full local proof draft, `lem:sector` and `lem:lens`; identities sanity-checked for `m=2,...,200`, not proof-certified by sampling. No code use. |
| `RSS-2ORB-EXCL` | A rotational Stein disk tiling cannot have exactly two moving tile orbits; combined with `RSS-ORB`, the candidate bound is `N=1+km`, `k>=3`. | Complete disk, congruent compact Jordan tiles, reflections allowed, actual rotation order `m>=2`, center interior to one tile. Uses local `RSS-TRACE-IC`, orbit/sector deductions and `RSS-SECTOR`; no additional KLV premises after `MATH-002`. Order two uses subadditivity, not zero-area boundaries. | Integrated draft, `thm:exclusion`. [EXT-MATH-002](contracts/EXT-MATH-002-two-orbit-obstruction.md) updated, ready, not submitted; independent acceptance and novelty pending. No generator/filter change. |

The exclusion does not address three or more moving orbits, asymmetric Stein
tilings, free-boundary patches, or general weaker nontrivial disk tilings.

## MATH-004 — many-orbit generalization, all proof drafts

The owner explicitly deferred independent review of MATH-002/003 and selected
generalization. [The study](studies/MATH-004-multiple-orbit-boundary.md) and
[standalone source](../stein_boundary_multiplicity.tex) distinguish the explicit
connected-outer-trace premise `(CT)` from local geometry that does not need it.
No previous draft or new deduction is promoted to independent acceptance.
None is used in code; novelty has not been certified.

Let `m>=2` be the actual global rotation order, `N=1+km`, `b<=k` the number
of positive-outer-trace orbits, and `r<1` the common circumradius in a unit disk.
For `m>=3`, set `c=cos(pi/m)`, `lambda=c/sin(pi/(2m))`,
`F_m=1+lambda^2+2*lambda*c`.

| ID | Proposed result | Domain and dependencies | Proof status / label |
| --- | --- | --- | --- |
| `RSS-MULT` | An arc-length-weighted mean matching multiplicity is at least `1/r`; one class contains at least `ceil(1/r)` outer orbits. | Rotational Stein setting plus explicit `(CT)`. Supporting centers are grouped modulo intrinsic `C_m` after equivariant charts; this is sufficient matching, not a complete classifier of all centered congruences. | Conditional proof draft, `prop:multiplicity`; no two-orbit exclusion is used. |
| `RSS-MIRROR-CAP` | A center-fixing mirror match between tiles in different moving orbits implies `r<=1/sqrt(F_m)` and `N>=F_m`. | `m>=3`; congruent Jordan tiles; actual rotation and reflection. Pair need not be outer. Local axis confinement, regular-polygon inradius and disk containment; **no `(CT)` or two-orbit exclusion**. | Local proof draft, `prop:mirror`. Area conclusion uses subadditivity, not equal tile-area shares. |
| `RSS-MIRROR-ORB` | Such a mirror pair forces a matching class and at least `ceil(sqrt(F_m))` outer orbits; asymptotically at least `(2/pi+o(1))*m`. | `RSS-MIRROR-CAP` plus `RSS-MULT`, hence conditional on `(CT)`. The large matching class need not contain the original mirror pair. | Conditional proof draft, `cor:amplification`. At `m=5`, `F_m=(13+5*sqrt(5))/2>9` excludes mirror matching when `k=3`, not the whole three-orbit class. |
| `RSS-ROT-SHELL` | All noncentral tiles cannot simultaneously be outer and rotations about the big disk center of one fixed tile. | Rotational Stein setting plus `(CT)`. Equal arcs create a larger rotation preserving the unique central remainder; that gives one moving orbit and contradicts `RSS-MULT`. | Conditional proof draft, `prop:shell`. Additional interior tiles invalidate the unique-remainder step; no extension to them is claimed. |

The mirror capacity gives a quadratic necessary total-tile count on its branch,
not a general computational complexity bound. The direct-match alternatives
with multiple arc classes or an inner tile partition remain open. Independent
review is deferred by the owner, not completed or required before conditional
mathematical exploration; no production rejection may assume acceptance.

## Priority 1: claims with direct implementation dependencies

| ID | Claim recorded by the source | Exact scope to preserve | Source and label | Implementation evidence | Review status |
| --- | --- | --- | --- | --- | --- |
| `SSR-REP` | Two transported outer traces coincide; oriented endpoint order depends on reflection parity. | Monohedral tiling of a Euclidean disk by congruent Jordan regions, more than one tile; degenerate traces allowed in the base theorem. | [`six_structural_results.tex`](../six_structural_results.tex), `thm:repetition` and `cor:peripheral` | [`enumeration/exterior_arc_repetition.py`](../../src/formal_disk4/enumeration/exterior_arc_repetition.py), weak-order pruning, related tests. The implementation also cites `RSS-OVERLAP`/`RSS-ORB`. | Source proof present; external KLV facts are used elsewhere; not re-audited here. |
| `SSR-CONC` | A Stein center tile forces a positive-length prototype arc of radius equal to the disk radius, concave relative to the tile. | Complete disk, congruent Jordan regions, center in the interior of one tile; the existence claim does not require regularity of the rest of the contour. | [`six_structural_results.tex`](../six_structural_results.tex), `thm:concavity` (compiled as Theorem 1.3 in code comments) | [`preword/linear_invariants.py`](../../src/formal_disk4/preword/linear_invariants.py) adds the strict concavity inequality only for the corresponding hypotheses. | Source proof present; not re-audited here. |
| `SSR-NL` | The local non-erasing Nielsen–Levi prefix split is sound, disjoint at semantic level and complete, including equality and both strict-prefix branches. | Free-monoid word equations with every active variable non-erasing; canonical transformations must be bijective and mirror-equivariant. | [`six_structural_results.tex`](../six_structural_results.tex), `thm:nielsen` | [`words/compact.py`](../../src/formal_disk4/words/compact.py), [`words/exact_partial.py`](../../src/formal_disk4/words/exact_partial.py). | Source proof present; implementation referenced and tests may cover it, not rerun. |
| `SSR-PAL` | Under a fixed-point-free reversal-complement involution, every nonempty fixed word has the unique form `r mu(r)`. | Fixed-point-free alphabet involution; non-erasing variable; equivariant signed renaming. | same source, `thm:palindrome` | palindrome branch in [`words/compact.py`](../../src/formal_disk4/words/compact.py). | Source proof present; the fixed-point-free premise is essential. |
| `SSR-LOOP` | A certified fixed-context unary loop iterates as `p^n V s^n`; simple/properly nested cycle conditions license the represented family. | Invariant contexts, preserved parameters, exits retained, canonical renamings undone; not arbitrary repeated residual states. | same source, `thm:loops` and `cor:safe-scc` | loop classifier and compilation in [`words/compact.py`](../../src/formal_disk4/words/compact.py) / [`words/exact_partial.py`](../../src/formal_disk4/words/exact_partial.py). | Source proof present; coverage outside this restricted class is explicitly not claimed. |
| `SSR-CONCUR` | Concurrent noncommuting Nielsen cycles already occur for `XY=YX`; unary/nested powers alone are not complete. | General non-erasing word-equation residual graph; also survives compatible mirror equations. | same source, `thm:concurrent` | unsupported-SCC path in [`words/exact_partial.py`](../../src/formal_disk4/words/exact_partial.py); this result prevents false UNSAT. | Source proof/counterexample present; not re-audited here. |
| `RSS-OVERLAP` | Outer traces transported to the center tile cannot all be distinct. | Rotational Stein tiling; nondegenerate outer traces; convex perimeter and transport facts. | [`rotational_stein_structural_note.tex`](../rotational_stein_structural_note.tex), `lem:overlap`; updated local route in the integrated MATH-002/003 TeX | premise for exterior-arc repetition and Stein-domain checks. | Area-free trace replacement now supplied by `RSS-TRACE-IC`; independent mathematical/code audit pending. |
| `RSS-ORB` | The center tile is fixed, every other orbit has full order `m`, at least two noncentral orbits reach the boundary, and two are related by a center-fixing isometry; hence `n=1+km`, `k>=2`. | Actual geometric rotation of exact order `m>=2`, complete disk, Stein center tile, congruent Jordan regions. An abstract graph automorphism is insufficient. | same original source, `thm:main` and `cor:k2`; integrated local replacement in the new TeX | [`graph_lab/space.py`](../../src/formal_disk4/graph_lab/space.py), [`enumeration/exterior_arc_repetition.py`](../../src/formal_disk4/enumeration/exterior_arc_repetition.py), weak-order comments and tests. | Local route uses `RSS-TRACE-IC`, elementary geometry and Brouwer, no extra KLV trace premise. Independent mathematical/code audit pending. |
| `RSS-2ORB` | If exactly two noncentral orbits remain, outer traces alternate, centered matching is reflective, the tiling is dihedral and tiles are sector-confined. | All `RSS-ORB` hypotheses plus exactly two noncentral orbits. | same original source, `thm:twoorbit`; updated integrated draft | two-orbit reflection/domain code in [`graph_lab/space.py`](../../src/formal_disk4/graph_lab/space.py) and associated tests. | Local route updated with the area-free replacement; independent acceptance pending. Stronger exclusion remains separately indexed as draft `RSS-2ORB-EXCL`. |

Before trusting any of these gates mathematically, audit both the proof and the
premise detector. The current code citations are useful traceability, not proof
certificates.

## Priority 2: proved-in-source claims not yet traced to active production gates

| ID | Claim recorded by the source | Scope | Source | Current relation to code | Review status |
| --- | --- | --- | --- | --- | --- |
| `CHO-HUB` | A rotation-fixed central tile whose whole boundary is one orbit of connected contacts with one neighboring orbit is impossible; outer rings do not repair it. | Complete disk; actual rotation; piecewise-`C^2` Jordan boundaries; hypotheses H1–H3, including connected interfaces covering the hub boundary. | [`cyclic_hub_obstruction.tex`](../cyclic_hub_obstruction.tex), `thm:one-ring`, `thm:many-rings` | No direct source-code citation found in the 2026-10 inventory. | Source proof present; not re-audited. Do not apply to multiple neighbor orbits, disconnected contacts, abstract symmetry or irregular boundaries. |
| `CHO-WORD` | A torsion-free additive charge gives a small contradiction when a hub period is paired with an opposite equal-length cyclic factor. | The exact power-word and charge hypotheses in the proposition. | same source, `prop:word` | Proposed early formal certificate; no direct implementation citation found. | Source proof present; not re-audited. |
| `FPR-PER` | A loop-augmented contact support is positively perimeter-regularizable exactly when it has total support / every support edge lies in an allowed spanning cycle forest; Hall-type deficits give cheap obstructions. | Graph encodes every positive-length tile contact and exterior contact correctly; positive perimeter contribution is the target relaxation. | [`filter_pipeline_roadmap.tex`](../filter_pipeline_roadmap.tex), `thm:perimeter-regularizability`, `cor:cycle-forest`, `prop:hall` | Proposed Stage A graph-only filter; no matching implementation found by name. | Candidate pending independent proof audit and a precise graph-construction audit. |
| `FPR-REP+` | Exterior-arc repetition can be required on a nondegenerate class rather than satisfied only by degenerate traces. | Exact hypotheses in the source, including the disk/exterior structure. | same source, `thm:nondeg-repeat` | Proposed exterior-first enumeration; overlaps `SSR-REP`. | Candidate pending comparison with `SSR-REP` and proof audit. |
| `FPR-ROT` | In a rotational Stein tiling each outer arc has angle `<2pi/q`, so one peripheral orbit cannot cover the circle and `n>=1+2q`. | Actual geometric order-`q` rotation, complete disk, nontrivial Stein tiling. | same source, `thm:rot-outer-bound`, `cor:two-orbits` | Substantially overlaps/superseded for indexing purposes by `RSS-ORB`; current code cites the rotational Stein note. | Candidate duplicate until the two proofs/statements are reconciled. |
| `FPR-PERIOD` | A connected center interface whose length is an integral number of rotational contour periods is impossible. | Complete disk; actual rotation; fixed tile; piecewise-`C^2` boundaries; connected positive-length interface; exact row-space implication of the period length. | same source, `thm:period-interface` | Proposed exact row-space filter; no direct implementation citation found. | Candidate pending proof audit, particularly curvature regularity and the transported-interval step. |

The “research status” language inside `filter_pipeline_roadmap.tex` is the
source author's assessment. This registry deliberately downgrades its new
claims to **candidate** until the project records an independent audit.

## Local mathematical certificates presently documented in code

Several rejections use short local arguments rather than a named TeX theorem.
They still require audit, but giving each one a separate theorem document would
add noise. Their standardized comments are the primary source for now.

| Family | Intended certificate | Principal location | Important scope guard |
| --- | --- | --- | --- |
| `LOC-LENGTH` | Interface length preservation and exact strict-positive linear infeasibility. | `constraints/length_lp.py`, weak-order length oracle | Only exact/certified infeasibility rejects. |
| `LOC-ANGLE` | Exact angle equalities and nonnegative/strict turn constraints. | `constraints/angle_lp.py`, weak-order angle oracle | Must match the selected point/curve regularity model. |
| `LOC-ARC` | The two views of one interface have opposite circular sign; incompatible radius-arc endpoints/topology reject. | `preword/arc_topology.py` | Unstable/unrepresented paths must remain unresolved, not rejected. |
| `LOC-RADIUS-SUM` | Summing signed radius measures cancels internal interfaces and leaves the disk boundary. | `preword/linear_invariants.py` | Complete disk only; disabled for free boundaries. |
| `LOC-TURN-SUM` | Signed regular turn cancels on internal interfaces and leaves one full outer turn. | same file | Complete disk and the configured piecewise-`C^2` hypothesis. |
| `LOC-ISOPER` | Disk perimeter sharing plus planar isoperimetry yields a necessary upper bound, implemented with a safe rational ceiling. | same file | Complete disk; the ceiling must weaken, never strengthen, the exact bound. |
| `LOC-PROFILE` | Non-erasure, Jordan angle range, point/turn identities, and straight-versus-circular incompatibility. | `profiles/filters.py` | Applies only to the represented formal profile semantics. |

These comments should cite a named registry result if a future proof grows
beyond a few local lines. Conversely, a purely local identity need not be
promoted to a grand theorem.

## Design documents: not theorem registries

| Document | Role | Claims not to overread |
| --- | --- | --- |
| [`contact_type_enumerator_design.tex`](../contact_type_enumerator_design.tex) | Constraint-driven, lazy incidence/word/length enumeration design; conditional soundness/completeness schemas. | The schemas say what an implementation would need to prove. They do not establish that Contact V2 satisfies the obligations or terminates without a refinement bound. |
| [`stein_search_algorithm.tex`](../stein_search_algorithm.tex) | Alternative placement-first hierarchy using interval contraction, relaxations, synthesis and exactification. | Completeness is relative to its representation hierarchy; the document is not evidence that these modules exist or outperform the formal pipeline. |
| [`symmetry_first_graph_sampling.tex`](../symmetry_first_graph_sampling.tex) | Symmetry-action-first graph generation and fair scheduling proposal. | A support/coverage argument for an ideal sampler is not evidence that the current Graph Lab samples every graph or has the claimed distribution. |
| [`joint_solver_filter_flowchart.tex`](../joint_solver_filter_flowchart.tex) and [`solver_pipeline_diagram.json`](../solver_pipeline_diagram.json) | Editable diagrams of historical/current-at-the-time control flow. | They are architecture snapshots, not mathematical proofs and not guaranteed to match every dirty working-tree path. |

## Dependency graph between mathematical claims

```text
Published external facts (especially KLV 2020)
  |
  +--> SSR-REP
  `--> FPR-REP+ / FPR-ROT (overlapping later derivations)

RSS-TRACE-IC + intrinsic rotation of the Stein center tile
  `--> RSS-OVERLAP --> RSS-ORB --> RSS-2ORB --> RSS-2ORB-EXCL
         (local draft route; independent acceptance pending)

Basic Jordan/curvature cancellation facts
  +--> SSR-CONC
  +--> CHO-HUB --> CHO-WORD (formal analogue, with extra charge hypotheses)
  `--> FPR-PERIOD (claimed generalization of the hub obstruction)

Levi prefix lemma / free-monoid facts
  +--> SSR-NL --> exact local word branching
  +--> SSR-PAL --> involutive fixed-word branch
  +--> SSR-LOOP --> restricted loop compression
  `--> SSR-CONCUR --> boundary of that compression / unsupported status
```

Arrows mean “uses or motivates”, not “has been independently verified from”.
The bibliography inside each TeX remains the source list; an audit must consult
the cited original, not only the paraphrase in the local note.

## Audit queue

Audit in consequence order, not document order:

1. `SSR-NL`, `SSR-PAL`, `SSR-LOOP`, `SSR-CONCUR`, because they control whether
   the word solver is complete, unsupported, or allowed to reject.
2. `SSR-REP`, `SSR-CONC`, `RSS-ORB`, `RSS-2ORB`, because code currently narrows
   search domains or prunes with them.
3. The local certificate families, especially their free-boundary and
   regularity guards.
4. `FPR-PER` and `FPR-PERIOD` only before considering implementation.
5. Alternative design claims only when a concrete comparative study is chosen.

For each audit, create a study note from the charter template and record: exact
statement, proof dependencies, checked counterexamples/edge cases, conclusion,
reviewer/date, and any code premise detector affected.
