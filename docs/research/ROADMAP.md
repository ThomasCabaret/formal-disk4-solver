# Research roadmap — mathematical questions before implementation tasks

Updated 2026-10-21 after the owner's correction of the proposed next step.
This roadmap governs selection; [AGENDA.md](AGENDA.md) records current work.

## Root question and the remaining uncertainty

The objective is new understanding and new monohedral tilings of the circular
disk. Known nontrivial examples already answer unrestricted `NT_center`
existence positively. Two important questions remain distinct:

- **Beyond the known constructions:** can a disk tiling exist outside the
  precisely defined families already available, or can a classification theorem
  exclude that possibility? "Outside" must specify a mathematical family,
  rather than mean absent from our catalogue or not yet found by our program.
- **Stein:** can a congruent Jordan-tile tiling put the center strictly inside
  one tile? This is a stronger hypothesis than omitting the center from some
  tiles. Global rotational symmetry is a further optional restriction.

Neither question is silently substituted for the other. Choosing the root
claim and its hypotheses precedes choosing a small case, proof contractor,
algorithm or experiment. The broad tiling equations and working variants are
in [PROBLEM_SPEC.md](PROBLEM_SPEC.md).

## Direction of work

| Priority | Actual research work | Useful outcome and next decision |
| --- | --- | --- |
| 1. Impossibility / classification | Start from the chosen full mathematical question. Combine circle-boundary structure, congruences and necessary invariants; attempt a contradiction or a theorem forcing a known form. No graph or symmetry restriction may enter unnoticed. | A proof closes exactly its stated class. A failed attempt identifies the missing implication or surviving class; it does not establish existence. |
| 2. Existence | If the obstruction programme does not settle the question, attempt an existence proof, including nonconstructive arguments or an explicit family. Record why the proposed family is genuinely admissible. | A proof establishes existence in scope; an explicit construction also gives geometric examples. Failure leaves the question unresolved. |
| 3. Structural reductions | Extract independently useful necessary conditions encountered during either proof attempt. Determine which assumptions are recognizable before expensive enumeration. | A theorem eliminates a whole class or a decision dimension. An ordering heuristic remains distinct from a sound rejection. |
| 4. Algorithms | Choose a search representation and algorithm in response to the remaining mathematical degrees of freedom and the reductions actually established. Reuse the formal-contour kernel where appropriate. | Compare approaches on the same specified domain. Build the smallest implementation whose result can change the algorithm choice. |
| 5. Targeted implementation checks | Test a specific correctness or performance claim needed by the chosen computational study, using its real inputs and entry points. | Diagnose a named issue or establish a scoped control. Stop once that dependency is addressed; no independent assembly project is implied. |

These are priorities with feedback, not a demand to exhaust all conceivable
proofs before considering another branch. Bound each proof attempt by one
stated line of argument and record exactly where it stops. A promising
existence argument or a major usable reduction can change the order, provided
the decision and its effect on the root question are explicit.

## Entry condition for every subproblem

Before starting, explain in plain French:

1. Which parent mathematical question is still unresolved?
2. What concrete claim, proof attempt or algorithm is proposed?
3. What will actually be done, with what hypotheses and stopping point?
4. What changes for the parent if it succeeds, fails, or remains unresolved?
5. Why is this a better next investment than the available alternatives?

If these links cannot be supplied, do not start the task. Availability of code,
a known example or an old TODO is not a reason to select it. Documentation and
literature work must themselves enable a named decision; repeatedly organizing
the project does not replace conducting research.

## Present implementation boundary and withdrawn proposal

The current contour route determines formal interface correspondences, solves
and decorates contours, realizes a prototype geometrically, then derives copy
placements from those correspondences. The intended contract is that a conforming
realization respects the formal gluing obligations. A concrete violation would
call for a targeted audit of that chain.

The proposal to feed a known tile and known placements into an independent
acceptance/assembly exercise (`VALID-001` as most recently described) is
withdrawn: its relevance to that chain was not established. No such work was
started. Any future validation must name the actual stage and property tested;
it cannot introduce a new placement solver as an unstated prerequisite.

`MATH-003` (two moving orbits in a rotational Stein tiling) remains a possible
restricted proof question. It should be chosen only after explaining how its
answer changes the selected broader question. The ready external audit
`EXT-MATH-001` can review an existing lemma; it does not set research priority
and need not delay original mathematics.

No new proof study or implementation is selected in this planning turn.
