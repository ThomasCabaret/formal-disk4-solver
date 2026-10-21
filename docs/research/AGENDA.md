# Live research agenda

Updated 2026-10-21. This is the live question tree, not a promise to implement
every branch. Selection follows [METHODOLOGY.md](METHODOLOGY.md).

## Current selection

- Active iteration: none running. [MATH-003](studies/MATH-003-two-orbit-stein.md)
  completed its first bounded iteration with a proposed two-orbit exclusion
  for all `m>=2`; independent proof review remains pending.
- Current path: `R0 -> APP-IMP -> MATH-003`.
- Next bounded action: critically review the new sector/lens argument and its
  external premises before treating `k>=3` as established or changing code.
  In particular, audit the external outer-trace proof's area-equality steps for
  arbitrary Jordan boundaries; the tiling conclusion remains conditional.
  [EXT-MATH-002](contracts/EXT-MATH-002-two-orbit-obstruction.md) is ready for
  optional owner-mediated review, not submitted. Other approaches remain open.
- Latest completed iteration: [MATH-003](studies/MATH-003-two-orbit-stein.md),
  yielding [a proof draft](../two_orbit_stein_obstruction.tex), not a new filter.
- Optional external audit: [EXT-MATH-001](contracts/EXT-MATH-001-stein-boundary-orbits.md)
  for `MATH-002`, ready for the owner to submit. No answer is assumed or required
  before continuing independent research.
- Override condition: a newly identified soundness failure in a theorem or
  control needed by the selected question takes priority over interpreting that
  evidence; it does not block independent mathematics.

## Question tree

This is the canonical live hierarchy. Approach nodes organize possible routes,
not commitments to run all of them. Their status is separate from that of their
children; the root being active does not mean a study is running. Supporting
studies can inform several branches through the cross-dependencies below.

```text
R0  Nontrivial monohedral tilings of the disk
|
+-- APP-IMP  Impossibility / classification under explicit hypotheses
|   `-- MATH-003  Test the minimal two-orbit Stein architecture (restricted case)
|
+-- APP-EXIST  Nonconstructive existence
|
+-- APP-CONSTRUCT  Explicit constructions / new families
|
+-- APP-SEARCH  Computational discovery: compare approaches, not just modules
|   +-- APP-CONTOUR  Formal-contour route (existing experimental asset)
|   `-- ALG-001  Compare this route with genuinely different representations
|       `-- ALG-002  Smallest justified discriminator between candidates
|
+-- SPEC-001  Shared support: define the target and finite variants
|
+-- MATH-001  Shared support: survey and audit structural mathematics
|   +-- MATH-002 Audit rotational Stein boundary-orbit necessity (RSS-ORB)
|   `-- APPLIED-001 Promote one audited high-leverage result into a tested reduction
|
+-- VALID-001 Withdrawn known-shape/placement replay proposal (historical)
|
+-- CPLX-001  Classify the bounded decision problems and likely scaling barriers
|
`-- INTEG-001 Reassess the research portfolio from the preceding evidence
```

## Nodes

| ID | Status | Parent | Question and deliverable | Dependencies / resumption trigger |
| --- | --- | --- | --- | --- |
| `R0` | active | — | Find or understand nontrivial monohedral disk tilings; permit mathematical, constructive and computational outcomes. | Root objective. |
| `APP-IMP` | active | `R0` | Approach: impossibility or classification for an explicitly stated unresolved tiling class. | No unrestricted nonexistence claim: known nontrivial examples exist. A restricted result must state what it changes for the broader question. |
| `APP-EXIST` | proposed | `R0` | Alternative approach: prove existence in an unresolved class without necessarily constructing a tile. | Independent of failure or completion of `APP-IMP`; hypotheses and novelty must be specified when selecting a study. |
| `APP-CONSTRUCT` | proposed | `R0` | Alternative approach: construct and prove a new admissible tiling or family. | Not constrained by the current software representation. Known examples alone are not new discoveries. |
| `APP-SEARCH` | proposed | `R0` | Alternative approach: obtain discoveries or structural evidence through justified computational search. | Compare representations, scope and scaling; do not assume the formal-contour implementation must be retained. |
| `APP-CONTOUR` | proposed | `APP-SEARCH` | Candidate approach: search formal contours and constraints, then realize geometry. Existing code is an asset, not a validated complete method. | New concrete children require a named bottleneck or mathematical question and parent benefit. Alternative representations can be opened alongside it. |
| `SPEC-001` | supported-in-scope | `R0` | [Working specification](PROBLEM_SPEC.md) and [study](studies/SPEC-001-problem-domain.md): broad Jordan-region target, center predicates, F1/F2/F3 and result semantics. | Delivered as a research contract; independent mathematical review remains pending. Revise if a later target needs different hypotheses. |
| `VALID-001` | superseded | `R0` | Known-shape/known-placement acceptance exercise withdrawn: no useful dependency on the actual contour pipeline was established. No study or run started. | A future validation task must name a concrete interface/property of the actual solver and the research conclusion it enables. |
| `MATH-001` | supported-in-scope | `R0` | First [literature pass](LITERATURE_FRONTIER.md) and [study](studies/MATH-001-literature-frontier.md) completed: four primary sources and explicit search limitations. | Proof audits and a comprehensive literature frontier remain open; no complete classification asserted. |
| `MATH-002` | proposed | `MATH-001` | Independently audit `RSS-OVERLAP`/`RSS-ORB`: do the precise Jordan/rotation hypotheses force two boundary-reaching orbits and centered matching? | Local deductions conditional on KLV were re-derived in `MATH-003`; full independent acceptance and code-premise audit are still pending. [EXT-MATH-001](contracts/EXT-MATH-001-stein-boundary-orbits.md) remains ready, not submitted. |
| `MATH-003` | supported-in-scope | `APP-IMP` | [First proof-draft deliverable](studies/MATH-003-two-orbit-stein.md): proposed exclusion of exactly two moving tile orbits for every `m>=2`, yielding candidate `N>=3m+1`. | Independent review and novelty check pending; no production rejection. [EXT-MATH-002](contracts/EXT-MATH-002-two-orbit-obstruction.md) is ready. Do not automatically extend to three orbits or assume general Stein nonexistence. |
| `APPLIED-001` | proposed | `MATH-001` | For one audited result, implement or evaluate the premise detector and measure sound selectivity/cost. | Requires an audited theorem and a trusted positive-control pack. |
| `ALG-001` | proposed | `APP-SEARCH` | Supporting comparison: formal-contour, incremental obligation, placement-first and constructive/constraint formulations. Deliver state, coverage and certificate analysis, not a large implementation. | Informs selection or creation of sibling approaches under `APP-SEARCH`. Empirical bottleneck claims need relevant evidence; no blanket witness-replay prerequisite. |
| `ALG-002` | proposed | `ALG-001` | Implement the smallest discriminator for the most promising alternative and compare it on identical controls. | Requires `ALG-001` selection and controls of the actual compared algorithms. |
| `CPLX-001` | proposed | `R0` | Define decision inputs and investigate decidability/upper/lower bounds for bounded formal or algebraic variants. | Requires `SPEC-001`; literature conclusions must cite primary sources. |
| `INTEG-001` | blocked | `R0` | Decide whether to scale, redesign, restrict the target, emphasize constructive mathematics, or park computational discovery. | Needs discriminating evidence about the selected mathematical question or algorithm. Validate software evidence when used; pure mathematics does not depend on completing an implementation checklist. |

## Selection notes

- The `APP-*` nodes expose alternatives, not five new studies. Their common
  hypothesis envelope comes from `R0`/`PROBLEM_SPEC.md`; any selected child must
  make its own restrictions explicit. They close no domain and assert no result.
- `SPEC-001`, `MATH-001` and `CPLX-001` are shared supporting questions, not
  compulsory phases. `MATH-002` can support `APP-IMP` and graph constraints;
  `APPLIED-001` can support `APP-SEARCH` only when a proved result applies.
- A new sibling or subgoal must be inserted here with its parent, relation and
  selection rationale before substantial work. Use the study template for the
  outcome-to-parent decision. On return, update the parent and choose the next
  branch explicitly; do not automatically continue the deepest open task.
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
