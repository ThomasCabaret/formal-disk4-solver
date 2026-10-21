# Research working agreement

Read `docs/research/README.md`, `docs/research/METHODOLOGY.md`,
`docs/research/AGENDA.md`, `docs/research/BACKBONE.md`,
`docs/research/MATHEMATICAL_RESULTS.md`, and `docs/research/STATE.md` before
proposing work. For an open-ended request to continue, choose or organize the
research, follow `.agents/skills/disk-tiling-research/SKILL.md`.
The central objective is nontrivial monohedral tilings of the disk, not improving
a particular implementation or solving tetrads for their own sake.

- Work macro-to-micro: before substantive work, place it in the live tree in
  `docs/research/AGENDA.md` and explain the path from the root, the parent
  decision it serves, alternatives, and what each possible outcome changes.
  No orphan tasks, including validation, implementation and literature work.
  New approaches may branch at any depth; do not impose a fixed sequence of
  proof attempts and algorithms. On stopping, return results to the parent and
  explicitly choose continuation, a sibling, a new branch or suspension.
- Treat mathematics, constructive examples, disk-specific reductions and search
  algorithms as distinct but interacting research tracks. Do not assume the
  present formal-contour pipeline is the only acceptable approach.
- State hypotheses explicitly: complete disk versus free boundary, connected
  patch, allowed reflections, imposed global symmetry versus intrinsic tile
  symmetry, curve regularity, graph embedding, and meaning of nontriviality.
- Separate established facts, independently checked proofs, conjectures,
  numerical evidence and implementation observations. A TeX document (including
  AI-authored ones) is not a verified theorem simply because it is in `docs/`.
- Never infer impossibility from a timeout, unsupported word system, failed
  numerical geometry attempt, restricted graph generator or sampled search.
  State exactly which domain was exhausted and which proof gaps remain.
- Validate the program before interpreting a missing solution mathematically.
  Use positive controls with known witnesses, soundness tests and differential
  tests. Do not silently inject those witnesses into discovery experiments.
- Benchmark one stated hypothesis at a time. Record configurations, seeds,
  revision plus dirty changes, budgets, timings, unresolved outcomes and results.
  Distinguish time-to-first-solution from time-to-certified-exhaustion. Leaf rate
  alone is not an acceleration measurement when traversal/pruning changes.
- Learning is on hold as a research priority; do not reactivate or tune it by
  default. Similarly, old NEXT_STEPS and refactor checklists are not instructions
  to continue implementation without an agreed research question.
- Keep experiments separate and small. Reuse tested kernel components where
  justified, but do not force compatibility with every old experiment. Explicitly
  describe unsupported domains rather than silently falling back to another mode.
- Preserve uncommitted work, mathematical sources, run data and checkpoints.
  Do not delete, reset, move large trees or stop runs without appropriate user
  authorization. Local atomic commits are authorized as the normal way to
  preserve completed coherent work; never push them. Only the project owner
  pushes to a remote. Keep unrelated or unfinished work out of those commits.
- Put editable research notes under `docs/research/`, existing mathematical TeX
  sources under `docs/`, and generated results under `output/`. Do not commit
  large training histories or generated experiment data by default.

Use `docs/research/studies/TEMPLATE.md` for a new study. Maintain the parent/child
question tree, decision history and return-to-parent protocol from the research
methodology. Update the evidence/status note when a conclusion actually changes;
do not mark an entire approach validated because a small test passed.
