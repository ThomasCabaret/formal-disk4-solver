# Live research agenda

Updated 2026-10-21. This is the live question tree, not a promise to implement
every branch. Selection follows [METHODOLOGY.md](METHODOLOGY.md).

## Current selection

- Active study: none.
- Default next node: none selected; discuss the next target with the owner.
- Reason: the owner requests a plain-language explanation of a target's value
  before starting it and emphasizes original mathematical research. The
  proposed 12-tile acceptance control is withdrawn. Use the mathematical
  priorities and parent-decision requirements in [ROADMAP.md](ROADMAP.md).
- Latest completed iteration: [MATH-001](studies/MATH-001-literature-frontier.md),
  yielding [the literature map](LITERATURE_FRONTIER.md).
- Optional external audit: [EXT-MATH-001](contracts/EXT-MATH-001-stein-boundary-orbits.md)
  for `MATH-002`, ready for the owner to submit. No answer is assumed or required
  before continuing independent research.
- Override condition: a newly identified soundness failure in a direct-use
  theorem or positive control takes priority.

## Question tree

```text
R0  Nontrivial monohedral tilings of the disk
|
+-- SPEC-001  Define the mathematical target and finite computational variants
|
+-- VALID-001 Withdrawn known-shape/placement replay proposal
|
+-- MATH-001  Survey and audit disk-specific structural mathematics
|   +-- MATH-002 Audit rotational Stein boundary-orbit necessity (RSS-ORB)
|   `-- APPLIED-001 Promote one audited high-leverage result into a tested reduction
|
+-- MATH-003  Original mathematics: test the minimal two-orbit Stein architecture
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
| `SPEC-001` | supported-in-scope | `R0` | [Working specification](PROBLEM_SPEC.md) and [study](studies/SPEC-001-problem-domain.md): broad Jordan-region target, center predicates, F1/F2/F3 and result semantics. | Delivered as a research contract; independent mathematical review remains pending. Revise if a later target needs different hypotheses. |
| `VALID-001` | superseded | `R0` | Known-shape/known-placement acceptance exercise withdrawn: no useful dependency on the actual contour pipeline was established. No study or run started. | A future validation task must name a concrete interface/property of the actual solver and the research conclusion it enables. |
| `MATH-001` | supported-in-scope | `R0` | First [literature pass](LITERATURE_FRONTIER.md) and [study](studies/MATH-001-literature-frontier.md) completed: four primary sources and explicit search limitations. | Proof audits and a comprehensive literature frontier remain open; no complete classification asserted. |
| `MATH-002` | proposed | `MATH-001` | Audit `RSS-OVERLAP`/`RSS-ORB`: do the precise Jordan/rotation hypotheses force two boundary-reaching orbits and centered matching? | [EXT-MATH-001](contracts/EXT-MATH-001-stein-boundary-orbits.md) is ready for optional external review; can also be pursued locally. Only conclusions relying on this theorem await its validation; independent work continues. |
| `MATH-003` | proposed | `R0` | Original-mathematics candidate: can a rotational Stein tiling have exactly two moving tile orbits (`N=2m+1`, `m>=2`), or can a new obstruction exclude all or some of them? | Natural unresolved target in `rotational_stein_structural_note.tex`. Any argument using its orbit/dihedral reductions must audit those premises; no new proof or novelty certification is claimed. Discuss scope/value before starting. |
| `APPLIED-001` | proposed | `MATH-001` | For one audited result, implement or evaluate the premise detector and measure sound selectivity/cost. | Requires an audited theorem and a trusted positive-control pack. |
| `ALG-001` | proposed | `R0` | Clean-room comparison of formal-contour, incremental obligation, placement-first and constructive/constraint formulations. Deliver state, coverage and certificate analysis, not a large implementation. | Follows the mathematical question, established reductions and remaining freedoms; empirical bottleneck claims need relevant evidence. No blanket witness-replay prerequisite. |
| `ALG-002` | proposed | `ALG-001` | Implement the smallest discriminator for the most promising alternative and compare it on identical controls. | Requires `ALG-001` selection and controls of the actual compared algorithms. |
| `CPLX-001` | proposed | `R0` | Define decision inputs and investigate decidability/upper/lower bounds for bounded formal or algebraic variants. | Requires `SPEC-001`; literature conclusions must cite primary sources. |
| `INTEG-001` | blocked | `R0` | Decide whether to scale, redesign, restrict the target, emphasize constructive mathematics, or park computational discovery. | Needs discriminating evidence about the selected mathematical question or algorithm. Validate software evidence when used; pure mathematics does not depend on completing an implementation checklist. |

## Selection notes

- Learning remains parked. Resume it only if a stable decision process, adequate
  signal and a comparison showing plausible leverage are established.
- Tetrads and free-boundary patches may be controls for a precisely identified
  kernel question; they are not separate programme objectives.
- The existing Contact V2 and placement-first documents are candidates inside
  `ALG-001`; neither is selected as the baseline in advance.
- `FPR-PER` and `FPR-PERIOD` are possible children of `MATH-001`, but proof audit
  precedes implementation.
- External contract status records preparation, transmission, response and
  acceptance separately. Creating a file does not start an external run or
  certify its answer; independent research continues normally.

When a node is selected, create a study from
[`studies/TEMPLATE.md`](studies/TEMPLATE.md), add its link here, and replace the
default target only with an explicit rationale.
