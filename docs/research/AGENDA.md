# Live research agenda

Updated 2026-10-21. This is the live question tree, not a promise to implement
every branch. Selection follows [METHODOLOGY.md](METHODOLOGY.md).

## Current selection

- Active study: none.
- Default next node: `SPEC-001`.
- Reason: a finite computational problem and a broad mathematical existence
  question are still conflated in parts of the historical project. This blocks
  meaningful complexity claims, coverage arguments and fair algorithm designs.
- Override condition: a newly identified soundness failure in a direct-use
  theorem or positive control takes priority.

## Question tree

```text
R0  Nontrivial monohedral tilings of the disk
|
+-- SPEC-001  Define the mathematical target and finite computational variants
|
+-- VALID-001 Reconstruct a trustworthy positive-control and soundness pack
|
+-- MATH-001  Survey and audit disk-specific structural mathematics
|   `-- APPLIED-001 Promote one audited high-leverage result into a tested reduction
|
+-- ALG-001   Compare fundamentally different search representations
|   `-- ALG-002 Test one minimal alternative against the trusted control pack
|
+-- CPLX-001  Classify the bounded decision problems and likely scaling barriers
|
`-- INTEG-001 Reassess the research portfolio from the preceding evidence
```

## Nodes

| ID | Status | Parent | Question and deliverable | Dependencies / resumption trigger |
| --- | --- | --- | --- | --- |
| `R0` | active | — | Find or understand nontrivial monohedral disk tilings; permit mathematical, constructive and computational outcomes. | Root objective. |
| `SPEC-001` | selected | `R0` | State the unrestricted mathematical problem and two or three finite encodings, including nontriviality, reflections, regularity, contacts, embedding and certificate semantics. | None. Needed before rigorous complexity or coverage claims. |
| `VALID-001` | proposed | `R0` | Identify reproducible known witnesses without injecting them into discovery; test representation, formal acceptance, geometry and assembly separately. | Can begin after the hypothesis envelope from `SPEC-001` is stable enough. Preempts other work if a soundness bug appears. |
| `MATH-001` | proposed | `R0` | Primary-source survey plus independent audit of the highest-consequence existing claims; identify genuinely disk-specific reductions and constructive families. | Scope supplied by `SPEC-001`; direct-use proof audit can start earlier if validation exposes it as a blocker. |
| `APPLIED-001` | proposed | `MATH-001` | For one audited result, implement or evaluate the premise detector and measure sound selectivity/cost. | Requires an audited theorem and a trusted positive-control pack. |
| `ALG-001` | proposed | `R0` | Clean-room comparison of formal-contour, incremental obligation, placement-first and constructive/constraint formulations. Deliver state, coverage and certificate analysis, not a large implementation. | Requires finite variants from `SPEC-001`; should use bottlenecks established by `VALID-001`. |
| `ALG-002` | proposed | `ALG-001` | Implement the smallest discriminator for the most promising alternative and compare it on identical controls. | Requires `ALG-001` selection and `VALID-001`. |
| `CPLX-001` | proposed | `R0` | Define decision inputs and investigate decidability/upper/lower bounds for bounded formal or algebraic variants. | Requires `SPEC-001`; literature conclusions must cite primary sources. |
| `INTEG-001` | blocked | `R0` | Decide whether to scale, redesign, restrict the target, emphasize constructive mathematics, or park computational discovery. | Unblocks after at least `SPEC-001`, `VALID-001`, and one of `MATH-001`/`ALG-001`/`CPLX-001` yield discriminating evidence. |

## Selection notes

- Learning remains parked. Resume it only if a stable decision process, adequate
  signal and a comparison showing plausible leverage are established.
- Tetrads and free-boundary patches are controls under `VALID-001`, not separate
  programme objectives.
- The existing Contact V2 and placement-first documents are candidates inside
  `ALG-001`; neither is selected as the baseline in advance.
- `FPR-PER` and `FPR-PERIOD` are possible children of `MATH-001`, but proof audit
  precedes implementation.

When a node is selected, create a study from
[`studies/TEMPLATE.md`](studies/TEMPLATE.md), add its link here, and replace the
default target only with an explicit rationale.
