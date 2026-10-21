# Research roadmap — from the root question to competing approaches

Updated 2026-10-21. This roadmap explains the approach portfolio;
[AGENDA.md](AGENDA.md) is the authoritative live tree and selection record.
The [method](METHODOLOGY.md#mandatory-macro-to-micro-refinement) governs how to
refine it, open alternatives and return results to a parent.

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

## Approaches, not mandatory successive phases

| Approach | Actual research work | Useful outcome and next decision |
| --- | --- | --- |
| Impossibility / classification | Start from an explicitly scoped unresolved claim. Combine circle-boundary structure, congruences and necessary invariants; attempt a contradiction or a theorem forcing a known form. No graph or symmetry restriction may enter unnoticed. | A proof closes exactly its stated class. A failed attempt identifies the missing implication or surviving class; it does not establish existence. |
| Nonconstructive existence | Seek an existence argument without requiring explicit tile coordinates or an algorithm that finds them. State why the objects guaranteed by the argument meet the tiling hypotheses. | A proof settles existence in scope even if no explicit example follows. An incomplete argument leaves a precise gap, not a positive result. |
| Constructive mathematics | Derive an admissible tile or family with congruent copies filling the disk. This is not restricted to constructions representable by the existing program. | A verified construction establishes existence and supplies examples; its scope and novelty remain explicit. |
| Computational discovery / algorithms | Compare representations and search methods for the chosen tiling question. The formal-contour pipeline is one candidate alongside justified alternatives. | Coverage analysis or a controlled comparison changes the algorithm choice. Implement only the smallest discriminator needed, then reassess. |

These approaches can coexist and branch at any depth. The table is not a ranking
or a waterfall: there is no requirement to fail at impossibility before trying
existence, or to finish mathematics before considering algorithms. Conversely,
an available implementation does not make algorithm development the default.
Choose the next bounded investigation by its expected contribution to the
parent question, evidence, dependencies and cost; record that choice.

Structural reductions, complexity analysis and targeted validation can serve
any relevant branch. For example, a formal-contour search can spawn a question
about a new pruning theorem; a proved theorem can motivate a different search
representation instead of one more filter. Validation must test a property of
the actual evidence or program being relied on, not become a separate generic
assembly project. Literature review supports precise questions and original
research rather than replacing them.

When a child is answered or a bounded attempt ends, return to its parent and
reconsider the alternatives. A blocked or costly contour approach can justify
opening another algorithmic approach; a promising existence argument can
redirect higher-level priorities. Neither switch establishes that the earlier
approach is impossible. Preserve the old branch, evidence and resumption trigger.

## Entry condition for every subproblem

Before starting, explain in plain French:

1. Where is the task in the live root-to-approach-to-question tree, and which
   parent decision is still unresolved?
2. What concrete claim, proof attempt or algorithm is proposed?
3. What will actually be done, with what hypotheses and stopping point?
4. What changes for the parent if it succeeds, fails, or remains unresolved?
5. Why is this a better next investment than the available sibling approaches,
   and when will its result be brought back to the parent?

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

`MATH-003` (two moving orbits in a rotational Stein tiling) was subsequently
selected by the owner and delivered a [proof draft](studies/MATH-003-two-orbit-stein.md),
not an accepted theorem or production gate. The owner subsequently deferred
independent review and selected a many-orbit generalization (`MATH-004`), then
parked that continuation to prioritize formulation tractability. These changes
do not promote any proof to independent acceptance.
`EXT-MATH-001` can review an existing lemma and `EXT-MATH-002` the new argument;
both are ready, not submitted, and do not determine other research priorities.

## Current strategic priorities

1. **Contour tractability (`CPLX-001`).** At fixed graph, separate incidence
   choices, bare signed words, decorated families and geometric realization.
   Seek exploitable structural restrictions or an appropriately scoped hardness
   reduction, with practical consequences. General word-equation complexity is
   not automatically the complexity of this subclass.
2. **Alternative unknown-tile discovery formulations (`ALG-001`).** Compare
   representations that do not require explicit contour-family enumeration.
   Do not assume they are easier, require known prototype shapes, or implement
   a large replacement engine before a meaningful small discriminator.

[CPLX-002](studies/CPLX-002-contour-word-structure.md) supplied the first
diagnostic: bare constant-free existence admits a positive-LP construction,
but that collapsed witness can fail disk decoration; a signed interval-cover
test addresses prescribed integer word lengths without listing all positions.
`CPLX-003` next asks what useful circle/corner constraints admit a compact
representation. Unknown metric choices and realizability remain unresolved.
No complexity theorem has condemned the whole programme or established a
practical scalable solver. A worst-case hardness result would still leave
parameterized, restricted-class and large practical improvements possible.
