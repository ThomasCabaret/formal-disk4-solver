# Research decision history

This is an append-only compact log of decisions that alter the research tree.
Detailed evidence belongs in study records and generated artifacts. Corrections
should be added as later entries rather than silently rewriting past rationale.

## 2026-10-21 — Research reset and repository orientation

**Decision `D-001`: treat the project as a research programme, not as the
continued optimization of one solver.**

- Evidence: the owner reports recovery of known symmetric 12-tile examples, but
  broad enumeration, learned ordering and relaxed controls did not establish a
  scalable or completely validated search.
- Consequence: mathematics, constructive work, algorithm design, complexity and
  validation are separate interacting tracks under root objective `R0`.
- Artifacts: `README.md`, `BACKBONE.md`, `MATHEMATICAL_RESULTS.md`, `STATE.md`.

**Decision `D-002`: preserve the formal-contour pipeline as one candidate, not
the mandatory architecture.**

- Alternatives retained: incremental obligation search, placement-first
  formulations, constructive families and purely mathematical progress.
- No approach was validated or globally rejected by this documentation pass.

**Decision `D-003`: park learning as a research priority.**

- Rationale: no convincing practical improvement is established, while the
  underlying decisions and representations are still changing.
- Resumption trigger: stable decision points, adequate training signal and a
  controlled comparison indicating material leverage.

**Decision `D-004`: select problem specification as the default next node.**

- Alternatives considered: immediate proof search, another solver refactor, or
  a new long discovery run.
- Rationale: without separating the unrestricted mathematical question from
  finite encoded decision problems, completeness, complexity and algorithm
  comparisons are ill-defined.
- Next node: `SPEC-001` in `AGENDA.md`.

## 2026-10-21 — Recovery of the pre-reset implementation snapshot

**Decision `D-005`: preserve the dirty implementation as one explicitly
historical experimental snapshot instead of deleting or partially restoring it.**

- Audit: the modified and untracked files form one dependency-connected tranche:
  tile-frontier/contact traversal, word and metric propagation, retained length
  sectors, completed-word caching, Euclidean placement diagnostics, progressive
  numerical geometry, fixed-graph campaigns, dashboards and their tests.
- Alternatives rejected: splitting it into apparently independent commits would
  create misleading intermediate states; restoring selected files would discard
  provenance and potentially useful negative/diagnostic work.
- Validation: with `PYTHONPATH=src` and a workspace-local temporary directory,
  the complete suite reported 374 passed, one skipped and 217 parameterized
  subtests passed in 142.85 seconds.
- Interpretation: this establishes internal regression coherence only. It does
  not establish completeness, soundness of every mathematical gate, a search
  speedup, or scientific validation of Contact V2 or the frontier strategy.
- Consequence: the code remains available as a tested research artifact while
  `SPEC-001` and the research methodology, not old engineering checklists,
  continue to determine future work.

## 2026-10-21 — First research iteration: problem specification

**Decision `D-006`: adopt SPEC-001's working domain contract and select a
bounded literature-frontier investigation under MATH-001.**

- Artifact: [PROBLEM_SPEC.md](PROBLEM_SPEC.md), with
  [study record](studies/SPEC-001-problem-domain.md).
- Result: separated `NT_center` (some tile omits the center) from `STEIN`
  (the center is interior to one tile), and bounded formal feasibility, exact
  semialgebraic templates and numerical realization. Known positive existence
  for the first predicate is not itself the remaining discovery question.
- Read-only audit: the present simple planar 3-connected graph generator and
  finite regular boundary representation are explicit restrictions, with no
  general completeness theorem supplied by this iteration.
- Alternatives: immediately extend Contact V2, rerun searches, or audit an
  isolated lemma. First identify the present published frontier and choose
  which proof/constructive question would actually advance `R0`.
- Next: `MATH-001`, with a primary-source claim/hypothesis table as the bounded
  first deliverable. `VALID-001` remains the preemption path if a concrete
  soundness blocker is discovered. No solver change or research run was made.

## 2026-10-21 — Literature map and optional external mathematical audits

**Decision `D-007`: export precise natural subproblems as optional external
LLM contracts, while continuing independent local work.**

- Owner preference: another available LLM can address bounded proofs,
  counterexamples or calculations without consuming the current agent quota.
- Method: write self-contained contracts with parent, hypotheses, requested
  result and acceptance checks. Preparation is distinct from submission and
  validation; returned model output remains a candidate until checked.
- First contract: `EXT-MATH-001`, the rotational Stein boundary-orbit argument
  already used to constrain graph generation. No external transmission occurred.

**Decision `D-008`: close the first MATH-001 literature pass and select
known-witness validation as the independent local continuation.**

- Artifact: [literature map](LITERATURE_FRONTIER.md) and
  [study](studies/MATH-001-literature-frontier.md). Four primary papers supplied
  constructions and restricted classifications; no full contemporary frontier
  or independent proof audit was claimed.
- `MATH-002` records the consequential `RSS-ORB` audit for external or local
  work. Its dependencies matter because the generator excludes whole domains.
- `VALID-001` is selected next: reconstruct one known 12-tile disk witness and
  trace complete assembly checks. This can proceed without the optional audit
  answer and provides ground truth before another algorithm comparison.
- No solver changes, discovery runs, new filters or learning work occurred.

## 2026-10-21 — Original mathematics and explicit target discussion

**Decision `D-009`: make original mathematical creation an explicit expected
outcome, and revisit the proposed validation priority before starting it.**

- Owner clarification: literature and audits support creating new mathematics;
  the programme must attempt new theorems, constructions and reductions.
- Every proposed study must explain in plain French its actual operations,
  output and benefit to the disk objective. The owner requests discussion of
  the next target before work begins.
- `VALID-001` returns to proposed: its intended work was acceptance testing of
  a known shape with known placements, not discovering an arrangement or
  improving search. No such study or run was started.
- `MATH-003` records a proposed original question on the minimal two-orbit
  Stein architecture already isolated in the local note. It is not selected,
  proved, or certified new in the literature. No new research study begins in
  this documentation/discussion turn.

## 2026-10-21 — Withdraw the misplaced validation task and plan from the root

**Decision `D-010`: withdraw VALID-001 as described, and require a mathematical
roadmap before selecting further implementation work.**

- The owner pointed out that the existing algorithm searches formal contours
  and their constraints, realizes a prototype, and derives placements from the
  formal correspondences. The proposed known-shape/known-placement exercise
  had no demonstrated place in that research path. It is withdrawn, not simply
  postponed. No exercise or new placement engine was implemented.
- [ROADMAP.md](ROADMAP.md) now gives the intended priorities: seek
  impossibility/classification arguments, then existence arguments, extract
  necessary conditions, and select algorithms in response to the remaining
  freedoms. A failed proof attempt does not settle existence either way.
- Every child must identify its parent question and explain how each possible
  outcome changes a parent decision. Generic validation/housekeeping cannot
  substitute for that connection.
- Known nontrivial examples prevent an indiscriminate impossibility target.
  Stein and classification beyond precisely defined known constructions are
  distinct candidate parent questions; neither has been silently selected.
- This turn corrects the roadmap and records the rejection. No new mathematical
  proof study, solver development, search run or theorem result is claimed.

## 2026-10-21 — Make progressive refinement the mandatory research procedure

**Decision `D-011`: replace D-010's sequential priority wording with a visible,
revisable approach tree and a mandatory relevance/return-to-parent protocol.**

- Owner clarification: begin macroscopically, then refine. Impossibility,
  nonconstructive existence, constructions and algorithms may coexist as
  alternatives; new approaches can arise at any depth. A mathematical pruning
  subgoal can belong to an algorithmic approach, and its result must be returned
  there. No fixed discipline order is imposed.
- `AGENDA.md` is the sole live hierarchy. `APP-*` entries organize approaches,
  not new active studies. The contour pipeline is one candidate under search,
  not the inevitable destination of all research. `BACKBONE.md` remains a
  dependency/area map, not a second competing agenda.
- Mandatory preflight: register the root-to-node path and parent relation;
  explain the actual parent decision, success/negative/inconclusive consequences,
  sibling alternatives, scope and stopping point before substantive work.
  Merely labeling a task "useful validation" or attaching it to `R0` fails this
  gate. This is the specific safeguard against repeating `VALID-001`.
- On completion or interruption, propagate only warranted consequences, return
  to the parent and explicitly choose continuation, another approach or
  suspension. A failed child does not automatically close its parent or siblings.
  Preserve old branches and record any changed parent links and rationale.
- Reparenting: `MATH-003`, formerly directly under `R0`, is a restricted-case
  candidate under `APP-IMP`; `ALG-001`, formerly under `R0`, supports approach
  selection under `APP-SEARCH`. Their scientific statuses are unchanged.
- The study template and agent entry instructions now carry these requirements.
  Routine steps within one study need no extra node. No new proof, experiment,
  solver change or research target selection occurred in this governance turn.

## 2026-10-21 — First two-orbit Stein obstruction attempt

**Decision `D-012`: pursue the owner-approved MATH-003 proof question, retain
its proposed exclusion as a reviewable draft, and return to APP-IMP before
extending the claim or implementing a filter.**

- Path: `R0 -> APP-IMP -> MATH-003`. The alternative was another broad survey
  or algorithm redesign; the two-orbit class offered a specific geometric proof
  target independent of the present search engine.
- Local deductions of the needed rotational normal form were re-derived
  conditional on KLV's outer-trace facts. The primary statements and their
  general tiling scope were checked; their full proofs were not independently
  certified, nor were code premise detectors audited.
- New artifact: [two_orbit_stein_obstruction.tex](../two_orbit_stein_obstruction.tex).
  The draft excludes `m>=3` using intrinsic rotation of a sector-confined tile,
  then treats `m=2` with an upper lens-area bound and measure subadditivity.
  This avoids assuming zero-area Jordan boundaries. Its proposed consequence
  is `N=1+km`, `k>=3`, not general Stein nonexistence.
- Auxiliary checks of two identities for orders 2–200 found no transcription
  error. They are not proof certificates or performance evidence. The detailed
  [study](studies/MATH-003-two-orbit-stein.md) also records assumption controls
  and the limits of a bounded prior-art search; novelty is not certified.
- A late critical check identified a specific area-equality question in the
  external proof of outer-trace connectedness for unrestricted Jordan boundaries.
  It is recorded for audit, not as a refutation of the published lemma. The
  tiling theorem is explicitly conditional on the outer-trace premises; the
  new elementary sector/lens arguments are separate. A zero-mean orbit proof
  removes that dependency from strict containment of the central tile itself.
- `RSS-SECTOR` and `RSS-2ORB-EXCL` are indexed as proof drafts. The original
  rotational source is preserved with a status pointer, not silently rewritten
  as if its earlier reflection-case gap had never existed.
- [EXT-MATH-002](contracts/EXT-MATH-002-two-orbit-obstruction.md) is ready for
  independent review, not submitted. No independent acceptance has been recorded.
  Next: review this exact argument; if it fails, return to the affected step.
  Other root approaches remain open. No solver/filter, learned policy, run data
  or checkpoint changed; no discovery computation was launched.

## 2026-10-21 — Replace the area-dependent trace premise in the Stein class

**Decision `D-013`: close the bounded MATH-002 iteration with an area-free
replacement proof, return it to MATH-003, and retain independent review as
the next check rather than extend the orbit count or change code.**

- Owning path: `R0 -> MATH-001 -> MATH-002`; the served dependency is
  `R0 -> APP-IMP -> MATH-003`. The owner approved this targeted investigation
  rather than a new solver run or an automatic three-orbit study.
- The journal/preprint area equalities were located, but their justification
  for completely general positive-area Jordan boundaries was not settled.
  No counterexample to the published connected-trace lemma is asserted.
- A narrower sufficient condition was identified and proved in draft: if a
  congruent Jordan prototile's circumcenter is interior, its outer trace in a
  disk tiling is connected. A crosscut traps another tile in the same minimal
  enclosing disk; congruence and uniqueness then force an interior overlap.
  No area equality or boundary smoothness is used.
- Actual rotational Stein tiles satisfy this circumcenter condition by an
  orbit-average squared-distance identity. The condition is deduced, not
  imposed as an extra symmetry or graph restriction. The two trace-transport
  facts were also proved locally for that class.
- `RSS-TRACE-IC` and the integrated TeX now remove the former outer-trace
  assumptions from the proposed `N>=3m+1` obstruction. This supersedes D-012's
  conditional status in this class, not its pending independent acceptance
  or novelty checks. Code premise detectors remain unaudited and unchanged.
- [Study](studies/MATH-002-outer-trace-audit.md) records proof, scope and
  critical checks. `EXT-MATH-002` was updated while still unsent to include the
  complete replacement argument. Next: independent review of the integrated
  proof, especially trapping of the connected interior and sector geometry.
  Other root approaches remain available; no discovery computation was launched.

## 2026-10-21 — Generalize before independent review, at the owner's request

**Decision `D-014`: defer independent review without promoting the existing
proofs; investigate MATH-004 and retain the resulting many-orbit constraints
as explicitly scoped drafts. Next study the surviving direct-match branch.**

- Path: `R0 -> APP-IMP -> MATH-004`, sibling of `MATH-003` and conditional
  user of `MATH-002`. The owner overrode D-013's review-first continuation.
  No independent acceptance or external answer is inferred from that choice.
- [New source](../stein_boundary_multiplicity.tex) and
  [study](studies/MATH-004-multiple-orbit-boundary.md) derive a weighted
  repetition inequality for arbitrary orbit counts. Connected outer traces
  are an explicit premise; the previous draft proposes to discharge it but
  was not independently checked this iteration.
- A separate local deduction does not need connected traces: a centered
  mirror pair between different moving orbits confines a tile between the
  rotated reflection axes. Its intrinsic regular polygon and disk containment
  bound its circumradius by `1/sqrt(F_m)` and force `N>=F_m`.
- Combining the bounds conditionally forces one matching class and at least
  `ceil(sqrt(F_m))` outer orbits. For `m=5`, three moving orbits therefore
  cannot admit such a mirror pair; direct matches remain an open alternative.
  No universal Stein nonexistence, independent proof review or certified
  literature novelty is claimed.
- A further conditional deduction excludes the case in which all noncentral
  tiles are outer and centered rotations of one tile. Additional interior
  tiles destroy the unique-central-remainder argument: shell symmetry fixes
  their union, not necessarily their partition. This is the precise missing
  implication, not an assumed global symmetry.
- Next bounded action: investigate the three-moving-orbit orientation-preserving
  branch, separating inner-orbit and multiple-outer-class possibilities. If no
  geometric constraint beyond counting is found, reassess at `APP-IMP` rather
  than extend arithmetic indefinitely. Other root approaches remain open.
- The methodology now explicitly asks every research report to finish with
  the next bounded action and its parent benefit, as requested by the owner.
  No solver code, runs, histories or checkpoints changed; no push.

## 2026-10-21 — Prioritize contour tractability and alternative formulations

**Decision `D-015`: park the orbit-proof continuation; prioritize CPLX-001,
complete the first CPLX-002 structural diagnostic, and select CPLX-003's
compact decorated-interval contract. ALG-001 is the second strategic priority.**

- The owner challenged continued local orbit pruning and explicitly authorized
  this reprioritization and first investigation. Path:
  `R0 -> CPLX-001 -> CPLX-002`; result returned to `CPLX-001`. The next sibling
  is `CPLX-003`. No active solver run was stopped or replaced.
- Code tracing found constant-free signed cyclic-factor equations at fixed
  incidence, with separate circle/free metadata and later decorated constraints.
  Contact V2 already includes corners and metric propagation; its full state is
  not misclassified as a plain word equation. Fixed graph is not fixed incidence.
- [Proof note](../contour_word_structure.tex) derives bare existence from
  positive linear feasibility via a common involution-fixed block. This simple
  construction is not claimed novel. It does not replace the supported-family
  solver: its extra identifications can make the circle/angle constraints fail.
- A signed positional double cover reduces prescribed-integer-word-length
  consistency to two unsigned interval-orbit counts; the published AHT theorem
  supplies a polynomial bound for that subtask. Unknown physical lengths,
  decorated constraints and recovery of geometry-relevant families remain open.
  No AHT implementation, general tiling hardness or practical speedup is claimed.
- [Probe](../../scripts/research/probe_contour_words.py): 164 small fixed-length
  systems matched exhaustive binary-involution search. Thirty exact LP-derived
  unknown-length witnesses were checked by substitution; 134 LPs were infeasible.
  On four actual small compiler cases all bare witnesses passed; the two disk
  witnesses failed decoration while ordinary families on the same placements
  passed profile filters. The two free cases built profiles only, not geometry.
- Fifteen targeted existing tests passed. No full regression/geometry audit or
  discovery run was performed. The generated JSON is under `output/CPLX-002/`
  and excluded from commits. No production solver code, environment, learned
  policy, existing history or checkpoint changed.
- Next: make the fixed-length interval/type/corner contract precise and find
  a small discriminator before any kernel rewrite. Alternative discovery
  formulations remain selected second; the orbit drafts and their unaccepted
  status are preserved with a resumption trigger. The research agenda, not an
  old implementation checklist or a generic hardness citation, selects work.
