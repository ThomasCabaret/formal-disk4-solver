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
