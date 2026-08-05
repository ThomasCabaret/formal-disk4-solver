# Solver pipeline diagram

The editable semantic source is `docs/solver_pipeline_diagram.json`. It is
rendered by `scripts/render_solver_pipeline.py` into a ten-page presentation PDF.

The diagram distinguishes:

- intrinsic symmetry quotients;
- deliberately imposed search domains;
- mathematical necessary-condition rejections;
- resource cutoffs and unsupported cases;
- numerical failures that are not proofs;
- integrity and implementation errors.

This distinction is essential when interpreting an exhaustive run. A timeout,
an unsupported word-family language, an unexpanded symbolic family, or a
failed numerical optimization must not be counted as a formal impossibility.

## Build

From the project root:

```powershell
py.exe -m pip install reportlab
py.exe scripts\render_solver_pipeline.py
```

The output is written to:

```text
output/pdf/formal_disk4_solver_pipeline.pdf
```

The documentation commit also contains the versioned snapshot generated on
2026-08-05 at 13:03:08 (Europe/Paris):

```text
docs/formal_disk4_solver_pipeline_2026-08-05_130308.pdf
```

The JSON is the content source. Edit its pages, groups, lanes, cards, audit
questions, or implementation map, then rerun the renderer. The renderer owns
only presentation rules and contains no solver-specific pipeline text.

## Scope

The main diagram follows the production pipeline implemented by
`formal_disk4.pipeline.runner.SolverRunner`, followed by the independent
single-prototile geometry and visualization stages. The Mapping Lab is shown as
an experimental sidecar because it samples complete mappings and evaluates them
through a production-filter adapter; it does not alter production filter
semantics.

## Filter-comment vocabulary

Production pruning sites use a short standardized prefix so that their logical
status can be audited without reconstructing the whole pipeline:

- `FILTER JUSTIFICATION (local)` records a direct necessary-condition argument;
- `FILTER JUSTIFICATION (theorem)` cites the numbered result that licenses the
  rejection, currently in `docs/six_structural_results.tex`;
- `QUOTIENT JUSTIFICATION` identifies a bijective equivalence reduction;
- `SEARCH-DOMAIN RESTRICTION` identifies an imposed, non-exhaustive shard;
- `CONSERVATIVE FALLBACK` means uncertainty is accepted rather than rejected;
- `RESOURCE LIMIT, NOT REJECTION` and `UNSUPPORTED, NOT UNSAT` prevent an
  incomplete computation from being reported as a mathematical impossibility.

The theorem document also fixes the current word-solver boundary: unary
fixed-context cycles are justified by Theorem 1.6, while Theorem 1.7 and
Corollary 8.2 require any reachable non-simple residual SCC to remain
unsupported unless a separate completeness proof is supplied.
