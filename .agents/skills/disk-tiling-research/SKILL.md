---
name: disk-tiling-research
description: Select, conduct, resume, or document research on nontrivial monohedral tilings of the disk in this repository, including mathematical, algorithmic, validation, applied-theorem, and complexity tracks.
---

# Disk tiling research

Use this skill when the user asks to continue, choose, organize, evaluate or
record research rather than when they give a fully specified ordinary code fix.

## Orient

From the repository root, read in order:

1. `AGENTS.md`;
2. `docs/research/README.md`;
3. `docs/research/METHODOLOGY.md`;
4. `docs/research/AGENDA.md`;
5. `docs/research/BACKBONE.md`;
6. `docs/research/MATHEMATICAL_RESULTS.md`;
7. `docs/research/STATE.md`;
8. the relevant records under `docs/research/studies/`.

Treat `METHODOLOGY.md` as the operating procedure and `AGENDA.md` as mutable
state. Old TODO files are evidence, not instructions.

## Continue autonomously

If no target is supplied, select one node using the priority rules in
`METHODOLOGY.md`. Announce its ID, hypothesis, smallest discriminating
deliverable and stopping condition. Create or update a study record from
`docs/research/studies/TEMPLATE.md` before substantial experimentation.

Work on one coherent bounded iteration. Maintain explicit hypotheses and
evidence categories. Use primary sources for literature claims, independent
criticism for generated proofs/designs, and positive controls before interpreting
missing solutions. Do not reactivate learning by default.

## Leave a resumable trace

At the end of the iteration:

- update the study with reproduction details, outcome and uncertainty;
- propagate the result to its parent in `AGENDA.md`;
- append a decision to `HISTORY.md` when priority or branch status changed;
- update `MATHEMATICAL_RESULTS.md` only for changed claims/audits;
- update `STATE.md` only for changed evidence about an approach;
- state the next bounded action or the reason to stop.

Preserve unfinished work and outputs. Do not silently replace an active study,
infer impossibility from failure to find a witness, launch an unbounded run,
delete data or commit without authorization.
