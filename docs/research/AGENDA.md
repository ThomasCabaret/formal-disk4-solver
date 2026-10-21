# Live research agenda

Updated 2026-10-21. This is the live question tree, not a promise to implement
every branch. Selection follows [METHODOLOGY.md](METHODOLOGY.md).

## Current selection

- Active iteration: none running. [CPLX-002](studies/CPLX-002-contour-word-structure.md)
  completed the first structural diagnostic: bare constant-free existence is
  positive linear feasibility; the costly family search serves additional
  decorated/geometric requirements. A signed interval-cover reduction handles
  prescribed integer word lengths, not unknown geometry.
- Selected path: `R0 -> CPLX-001 -> CPLX-003`; cross-beneficiary:
  `R0 -> APP-SEARCH -> APP-CONTOUR`. Owner priorities are contour tractability
  first and genuinely alternative formulations second.
- Next bounded action: formulate fixed-length signed interval constraints with
  arc type/sign and corner information. Determine which checks and useful
  alternatives admit a compact representation before implementing a new kernel.
  Preserve the distinction between fixed graph and fixed incidence, and between
  integer word lengths and physical arclengths. No large rewrite or long run.
- Second priority: `ALG-001`, compare genuinely different unknown-tile discovery
  formulations, not a known-shape assembly engine. It need not wait for a full
  general complexity classification, but no second study is running now.
- Parked continuation: `MATH-004` orientation-preserving three-orbit branch.
  Its results and pending reviews are preserved; resume if the owner restores
  its priority or it supplies a needed structural reduction for the selected
  algorithmic question. No draft theorem is promoted or enabled in code.
- Latest completed iteration: [CPLX-002](studies/CPLX-002-contour-word-structure.md),
  [mathematical note](../contour_word_structure.tex) and an isolated reproducible
  probe. 164 small signed-cover controls matched brute force; four actual
  compiler cases had bare witnesses, and two disk witnesses failed decoration
  while the ordinary families passed. No geometry search or end-to-end speedup
  was established; no production filter changed.
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
|   +-- MATH-003  Test the minimal two-orbit Stein architecture (restricted case)
|   `-- MATH-004  Generalize circular-boundary constraints to multiple orbits
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
|   +-- MATH-002 Area-free outer-trace bridge for rotational Stein candidates
|   `-- APPLIED-001 Promote one audited high-leverage result into a tested reduction
|
+-- VALID-001 Withdrawn known-shape/placement replay proposal (historical)
|
+-- CPLX-001  Structural tractability and complexity of contour formulations
|   +-- CPLX-002  Actual fixed-incidence word class and representation explosion
|   `-- CPLX-003  Compact signed intervals with disk/corner constraints
|
`-- INTEG-001 Reassess the research portfolio from the preceding evidence
```

## Nodes

| ID | Status | Parent | Question and deliverable | Dependencies / resumption trigger |
| --- | --- | --- | --- | --- |
| `R0` | active | — | Find or understand nontrivial monohedral disk tilings; permit mathematical, constructive and computational outcomes. | Root objective. |
| `APP-IMP` | parked | `R0` | Approach: impossibility or classification for an explicitly stated unresolved tiling class. Existing orbit drafts are preserved. | Owner prioritized contour tractability and alternative formulations; resume on an explicit priority change or a needed reduction. No unrestricted nonexistence claim. |
| `APP-EXIST` | proposed | `R0` | Alternative approach: prove existence in an unresolved class without necessarily constructing a tile. | Independent of failure or completion of `APP-IMP`; hypotheses and novelty must be specified when selecting a study. |
| `APP-CONSTRUCT` | proposed | `R0` | Alternative approach: construct and prove a new admissible tiling or family. | Not constrained by the current software representation. Known examples alone are not new discoveries. |
| `APP-SEARCH` | proposed | `R0` | Alternative approach: obtain discoveries or structural evidence through justified computational search. | Compare representations, scope and scaling; do not assume the formal-contour implementation must be retained. |
| `APP-CONTOUR` | proposed | `APP-SEARCH` | Candidate approach: search formal contours and constraints, then realize geometry. Existing code is an asset, not a validated complete method. | New concrete children require a named bottleneck or mathematical question and parent benefit. Alternative representations can be opened alongside it. |
| `SPEC-001` | supported-in-scope | `R0` | [Working specification](PROBLEM_SPEC.md) and [study](studies/SPEC-001-problem-domain.md): broad Jordan-region target, center predicates, F1/F2/F3 and result semantics. | Delivered as a research contract; independent mathematical review remains pending. Revise if a later target needs different hypotheses. |
| `VALID-001` | superseded | `R0` | Known-shape/known-placement acceptance exercise withdrawn: no useful dependency on the actual contour pipeline was established. No study or run started. | A future validation task must name a concrete interface/property of the actual solver and the research conclusion it enables. |
| `MATH-001` | supported-in-scope | `R0` | First [literature pass](LITERATURE_FRONTIER.md) and [study](studies/MATH-001-literature-frontier.md) completed: four primary sources and explicit search limitations. | Proof audits and a comprehensive literature frontier remain open; no complete classification asserted. |
| `MATH-002` | supported-in-scope | `MATH-001` | [Replacement-proof draft](studies/MATH-002-outer-trace-audit.md): interior circumcenters imply connected outer traces; rotational Stein candidates have that property. The other two transport facts are locally derived too. | Independent review pending. The general published Jordan-boundary area question is not settled; code premise detectors are unaudited. Updated `EXT-MATH-002` ready, not submitted. |
| `MATH-003` | supported-in-scope | `APP-IMP` | [Integrated proof draft](studies/MATH-003-two-orbit-stein.md): proposed exclusion of exactly two moving tile orbits for every `m>=2`, with candidate `N>=3m+1`; no additional outer-trace assumptions after `MATH-002`. | Independent review and novelty check pending; no production rejection. [EXT-MATH-002](contracts/EXT-MATH-002-two-orbit-obstruction.md) is ready. Do not automatically extend to three orbits or assume general Stein nonexistence. |
| `MATH-004` | supported-in-scope | `APP-IMP` | [Multiple-orbit study](studies/MATH-004-multiple-orbit-boundary.md): weighted repetitions and mirror-capacity drafts delivered. | Acceptance status unchanged; proposed three-orbit continuation is parked behind `CPLX-002` and `ALG-001`, not automatically resumed. |
| `APPLIED-001` | proposed | `MATH-001` | For one audited result, implement or evaluate the premise detector and measure sound selectivity/cost. | Requires an audited theorem and a trusted positive-control pack. |
| `ALG-001` | selected | `APP-SEARCH` | Second-priority comparison of contour search with genuinely alternative formulations for an unknown tile, including disk-specific constraints. Deliver state, coverage, expected bottleneck and a small discriminator before implementation. | Owner-approved alongside contour-complexity research; not running in parallel. No known-shape assembly detour or presumption that another formulation is easier. |
| `ALG-002` | proposed | `ALG-001` | Implement the smallest discriminator for the most promising alternative and compare it on identical controls. | Requires `ALG-001` selection and controls of the actual compared algorithms. |
| `CPLX-001` | active | `R0` | Approach: characterize practical and theoretical tractability of the contour formulation, first at fixed graph, separating general word equations from geometrically induced subclasses. | Upper bounds are not hardness; hardness requires a reduction into the actual class and does not preclude practical or parameterized gains. |
| `CPLX-002` | supported-in-scope | `CPLX-001` | [Study](studies/CPLX-002-contour-word-structure.md): constant-free bare feasibility reduces to LP; prescribed integer lengths reduce to a signed double-cover orbit test. Actual compiler controls distinguish these from valid decorated families. | All new proofs are drafts; no general decorated/tiling complexity classification, production rewrite or speedup claim. |
| `CPLX-003` | selected | `CPLX-001` | Determine what circular-arc type/sign and corner consistency can be represented or checked on compact fixed-length interval identifications, retaining useful geometric alternatives. | First write the exact constraint contract and small discriminator. Unknown lengths and geometry remain separate; do not implement a large AHT engine on the strength of an orbit-count theorem alone. |
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
