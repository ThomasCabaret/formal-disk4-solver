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

For `RSS-OVERLAP`/`RSS-ORB`, the cited KLV labels were matched to primary-source
statements. The additional local inference is still pending audit under
`MATH-002`; [EXT-MATH-001](contracts/EXT-MATH-001-stein-boundary-orbits.md)
is ready for optional external review. No reply or independent acceptance has
been recorded, and the statuses below are unchanged.

## Priority 1: claims with direct implementation dependencies

| ID | Claim recorded by the source | Exact scope to preserve | Source and label | Implementation evidence | Review status |
| --- | --- | --- | --- | --- | --- |
| `SSR-REP` | Two transported outer traces coincide; oriented endpoint order depends on reflection parity. | Monohedral tiling of a Euclidean disk by congruent Jordan regions, more than one tile; degenerate traces allowed in the base theorem. | [`six_structural_results.tex`](../six_structural_results.tex), `thm:repetition` and `cor:peripheral` | [`enumeration/exterior_arc_repetition.py`](../../src/formal_disk4/enumeration/exterior_arc_repetition.py), weak-order pruning, related tests. The implementation also cites `RSS-OVERLAP`/`RSS-ORB`. | Source proof present; external KLV facts are used elsewhere; not re-audited here. |
| `SSR-CONC` | A Stein center tile forces a positive-length prototype arc of radius equal to the disk radius, concave relative to the tile. | Complete disk, congruent Jordan regions, center in the interior of one tile; the existence claim does not require regularity of the rest of the contour. | [`six_structural_results.tex`](../six_structural_results.tex), `thm:concavity` (compiled as Theorem 1.3 in code comments) | [`preword/linear_invariants.py`](../../src/formal_disk4/preword/linear_invariants.py) adds the strict concavity inequality only for the corresponding hypotheses. | Source proof present; not re-audited here. |
| `SSR-NL` | The local non-erasing Nielsen–Levi prefix split is sound, disjoint at semantic level and complete, including equality and both strict-prefix branches. | Free-monoid word equations with every active variable non-erasing; canonical transformations must be bijective and mirror-equivariant. | [`six_structural_results.tex`](../six_structural_results.tex), `thm:nielsen` | [`words/compact.py`](../../src/formal_disk4/words/compact.py), [`words/exact_partial.py`](../../src/formal_disk4/words/exact_partial.py). | Source proof present; implementation referenced and tests may cover it, not rerun. |
| `SSR-PAL` | Under a fixed-point-free reversal-complement involution, every nonempty fixed word has the unique form `r mu(r)`. | Fixed-point-free alphabet involution; non-erasing variable; equivariant signed renaming. | same source, `thm:palindrome` | palindrome branch in [`words/compact.py`](../../src/formal_disk4/words/compact.py). | Source proof present; the fixed-point-free premise is essential. |
| `SSR-LOOP` | A certified fixed-context unary loop iterates as `p^n V s^n`; simple/properly nested cycle conditions license the represented family. | Invariant contexts, preserved parameters, exits retained, canonical renamings undone; not arbitrary repeated residual states. | same source, `thm:loops` and `cor:safe-scc` | loop classifier and compilation in [`words/compact.py`](../../src/formal_disk4/words/compact.py) / [`words/exact_partial.py`](../../src/formal_disk4/words/exact_partial.py). | Source proof present; coverage outside this restricted class is explicitly not claimed. |
| `SSR-CONCUR` | Concurrent noncommuting Nielsen cycles already occur for `XY=YX`; unary/nested powers alone are not complete. | General non-erasing word-equation residual graph; also survives compatible mirror equations. | same source, `thm:concurrent` | unsupported-SCC path in [`words/exact_partial.py`](../../src/formal_disk4/words/exact_partial.py); this result prevents false UNSAT. | Source proof/counterexample present; not re-audited here. |
| `RSS-OVERLAP` | Outer traces transported to the center tile cannot all be distinct. | Rotational Stein tiling; nondegenerate outer traces; KLV connectedness/convex-hull/no-partial-overlap facts. | [`rotational_stein_structural_note.tex`](../rotational_stein_structural_note.tex), `lem:overlap` | premise for exterior-arc repetition and Stein-domain checks. | Source labels itself audited; depends on KLV; not independently re-audited in this restart. |
| `RSS-ORB` | The center tile is fixed, every other orbit has full order `m`, at least two noncentral orbits reach the boundary, and two are related by a center-fixing isometry; hence `n=1+km`, `k>=2`. | Actual geometric rotation of exact order `m>=2`, complete disk, Stein center tile, congruent Jordan regions. An abstract graph automorphism is insufficient. | same source, `thm:main` and `cor:k2` | [`graph_lab/space.py`](../../src/formal_disk4/graph_lab/space.py), [`enumeration/exterior_arc_repetition.py`](../../src/formal_disk4/enumeration/exterior_arc_repetition.py), weak-order comments and tests. | Earlier internal audit claim; external Brouwer/KLV dependencies; not re-audited here. |
| `RSS-2ORB` | If exactly two noncentral orbits remain, outer traces alternate, centered matching is reflective, the tiling is dihedral and tiles are sector-confined. | All `RSS-ORB` hypotheses plus exactly two noncentral orbits. | same source, `thm:twoorbit` | two-orbit reflection/domain code in [`graph_lab/space.py`](../../src/formal_disk4/graph_lab/space.py) and associated tests. | Earlier internal audit claim; not re-audited here. The stronger `k>=3` claim is explicitly not established. |

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
  +--> RSS-OVERLAP --> RSS-ORB --> RSS-2ORB
  `--> FPR-REP+ / FPR-ROT (overlapping later derivations)

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
