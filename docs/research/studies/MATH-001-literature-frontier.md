# Study MATH-001 — Published disk-tiling frontier

## Identity

- Node / parent: `MATH-001` / `R0`.
- Track: `MATH`, first literature iteration.
- Status: supported-in-scope (first literature pass complete, proof audits pending).
- Owner / opened / updated: Codex / 2026-10-21 / 2026-10-21.
- Relevance: identify which existence, construction and obstruction questions
  can advance the disk objective before choosing a proof audit or another search.

## Question and hypotheses

What do accessible primary sources establish about `NT_center` and `STEIN`,
and which assumptions separate their results? The working hypothesis is that
known constructions and restricted classifications provide a useful, sharply
scoped next target; the broad status must be checked rather than inferred from
an older paper's open-question list.

Domain: complete circular disk, congruent compact Jordan regions, reflections
allowed unless stated, no imposed symmetry in the broad question. Record
normality, regularity and geometric symmetry per claim. Free patches are controls.

## Decision context and evidence plan

`SPEC-001` selected this node. Alternatives are reconstructing a current known
witness (`VALID-001`) and extending Contact V2. A literature map can discriminate
between these directions without implementing another speculative search.

Bound this iteration to the main constructive disk source, the KLV small-tile
classification, relevant later classifications, and targeted searches for later
Stein/minimum-cardinality results. Stop with a source/hypothesis/result table,
explicit search limitations and one next bounded audit. Do not equate a missing
search result with proof that a question remains open.

## Reproduction

- Starting revision: `1674efd` (clean working tree).
- Sources: primary papers, author/institutional repositories and publisher pages;
  exact URLs/version dates and queries to be recorded in the resulting note.
- No computational discovery, randomized benchmark or kernel change planned.
- Independent proof review: not part of this literature pass; source statements
  will not be promoted to independently verified theorems.

## Results

Deliverable: [LITERATURE_FRONTIER.md](../LITERATURE_FRONTIER.md).

- Four primary papers were inspected at the statement level, with constructions,
  restricted classifications and conjectures separated by hypotheses.
- The constructive families provide an analytical route to control instances.
  The local catalogue's historical witnesses have not yet been identified with
  those source constructions.
- No later primary resolution of general Stein existence, or improvement to
  the reported general minimum-count bounds, was found in this bounded search.
  This is a search outcome, not a certified contemporary open-problem status.
- References to KLV Lemma 2.6 and Remarks 2.7–2.8 in the local rotational note
  were matched to the published statements. The local stronger theorem and
  its implementation have not been independently audited by doing that.
- No code, solver settings, run data or learned policies changed. No numerical
  search or performance comparison was run.

Primary reading:

1. Haddley–Worsley, `arXiv:1512.03794v2`, sections 3–6; revised 2016-04-28.
2. Kurusa–Lángi–Vígh, journal DOI `10.1007/s00009-020-01595-3` (2020),
   introduction, Theorem 1.1/Corollary 1.2 and Lemma 2.6/Remarks 2.7–2.8.
3. Nagy–Vígh, `arXiv:2110.11800v1`, Theorems 1.1, 1.2, 5.1 and Conjecture 6.1;
   journal DOI `10.1016/j.disc.2022.113140`, issue 2023.
4. Basit–Lángi, DOI `10.1007/s00010-023-00973-y`, Theorem 1;
   online 2023, issue 2024.

All exact links are in the deliverable. An author-maintained citation list was
also inspected for follow-up leads. Search engines' dates and HTML internal
dates were not used to infer new publications or resolved conjectures.

Search queries (2026-10-21):

```text
"monohedral" "disc" "Stein" tiling 2025 2026
Haddley Worsley dissecting a disc into congruent pieces 2016 12 18
"circular disc" "congruent" "four" tiles
"Stein" "disk" "tiling" center interior
"Stein" "monohedral" "2024"
"Stein" "monohedral" "2025"
"Monohedral Tilings of a Convex Disc with a Smooth Boundary" Nagy Vigh arxiv
"monohedral" "disk" "2026"
"Stein" "monohedral tilings" solved
"circular disc" "tiling" "four" "2025"
"monohedral disk" "2024" "2025"
"monohedral" "center" "interior" "2026"
```

## Interpretation

Existing constructive and obstruction results are enough to select two
consequential bounded tasks. They do not establish a complete classification,
validate the historical solver, or justify a new search restriction. This pass
is intentionally limited by accessible sources; no author confirmation or
comprehensive citation-index review was performed.

## Return to parent

- `MATH-002` is proposed as the scoped audit of `RSS-OVERLAP`/`RSS-ORB`.
  [EXT-MATH-001](../contracts/EXT-MATH-001-stein-boundary-orbits.md) exports its
  mathematical core for optional independent review. Status: ready, not sent;
  no external response or validated theorem is implied.
- This audit was chosen over extending another candidate filter because it
  controls the generator's accepted domain. Word-solver audits remain on the
  registry queue; they were not resolved by this pass.
- Independent local next step: `VALID-001`, reconstruct a known 12-tile disk
  witness from explicit geometry/source data, then trace prototype, congruence,
  contact and full-disk checks. No wait for the external contract is needed.
- `AGENDA.md`, `HISTORY.md`, `STATE.md` and the mathematical registry were
  updated with this evidence and the outstanding review boundary.

Subsequent correction (`D-010`): the proposed `VALID-001` continuation above was
withdrawn before work began. Its connection to the actual contour pipeline was
not established. The source observations stand; the next-task recommendation
is superseded by [ROADMAP.md](../ROADMAP.md) and the current agenda.
