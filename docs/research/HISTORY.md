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
