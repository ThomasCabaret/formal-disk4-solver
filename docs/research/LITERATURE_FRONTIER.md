# Disk-tiling literature map — MATH-001, first pass

Checked 2026-10-21. Scope follows [PROBLEM_SPEC.md](PROBLEM_SPEC.md).
This is a bounded primary-source survey, with statements read but proofs not
independently audited. Full provenance is in the
[study record](studies/MATH-001-literature-frontier.md).

## Sources and usable statements

| Source / version | Stated result and precise scope | Consequence for this project |
| --- | --- | --- |
| [Haddley–Worsley, arXiv:1512.03794v2](https://arxiv.org/html/1512.03794), revised 28 April 2016; sections 3–6 | Constructive wedge/subdivision families, including `D_n^t` with `4n` tiles and `C_{n,k}^t`, `C-tilde_{n,k}^{t*}` with `2nk` tiles, for odd `n>=3` and admissible parameters. Some placements omit the center; others do not. | A constructive control family is available without graph search. The paper's general classification is conjectural (6.1–6.3). |
| [Kurusa–Lángi–Vígh, Mediterranean Journal of Mathematics 17:156 (2020)](https://link.springer.com/article/10.1007/s00009-020-01595-3), Theorem 1.1 / Corollary 1.2 | Every circular-disk monohedral tiling with at most three Jordan tiles is rotationally generated. Its minimum-count question for `NT_center` has the reported interval `4<=N_min<=12`. | A small exact disk obstruction and known positives; this is not a classification for four or more tiles. |
| [Nagy–Vígh, Discrete Mathematics 346(1):113140 (2023)](https://doi.org/10.1016/j.disc.2022.113140); [readable preprint](https://arxiv.org/html/2110.11800), Theorems 1.1, 1.2, 5.1 | Two-piece classification for smooth strictly convex regions; three-piece conclusions require normality, C1 target boundary and piecewise differentiable tile boundaries. Section 5 treats a restricted non-normal case. | Record regularity and normality before reusing these conclusions. Theorem 5.1 gives necessary structure, not existence. |
| [Basit–Lángi, Aequationes Mathematicae 98 (2024), 535–555](https://link.springer.com/article/10.1007/s00010-023-00973-y), online 9 July 2023, Theorem 1 | For a regular `r`-gon, `r>=5`, and `k=2` or `3` Jordan tiles: either `k=2` with odd `r` and an axial bisection, or `k` divides `r` and the tiling is rotationally generated. | A comparison showing how target-boundary structure can control the whole tiling. It is not a free-boundary patch theorem. |

In Nagy–Vígh, **normal** means that each intersection of two tiles is connected
or empty. This is additional geometry, not a synonym for a simple contact graph.
Their Conjecture 6.1 asks for extension beyond normal tilings. We found no
justification to silently remove its normality hypothesis in a new filter.

Haddley–Worsley's construction parameters explain why 18 tiles are a natural
control: `n=3, k=3` gives `2nk=18`; `n=3, k=2` gives 12. This arithmetic and
source-family membership do not identify our historical catalogue mappings
with those constructions. That identification requires an explicit witness.
The freedom in their allowed groove paths also means these are more than a
finite list of pictured shapes.

## What is known versus what this search did not settle

- `NT_center` existence has constructive positive examples. New discoveries
  must be compared against known families; a new graph/profile ID alone does
  not establish geometric novelty.
- Stein is explicitly posed as a question in the sources checked. The targeted
  searches below did not locate a later primary-source resolution. Treat its
  present status as **no resolution found in this bounded search**, not a
  certified statement that the entire literature contains none.
- Likewise, no improved general bound beyond the reported minimum-count
  interval was located. Do not present that interval as a newly certified
  optimal contemporary bound.
- Neither the general classification conjecture nor the three-tile theorems
  justify enumerating only symmetric graphs or only the known constructive
  families for unrestricted discovery.
- The local AI-authored rotational Stein note supplies stronger claims than
  the published small-count classifications. Matching its cited dependencies
  to primary-source labels is useful provenance, but does not complete a
  proof audit of its extra conclusions.

## Selected proof question and an independent local continuation

The next natural audit is `RSS-ORB`: does a geometric rotation of order `m`
in a Stein tiling force two boundary-reaching tile orbits, and hence
`N=1+km` with `k>=2`? The local note also asserts a centered matching between
two such orbits. This directly controls which graphs the Stein generator
discards in [`graph_lab/space.py`](../../src/formal_disk4/graph_lab/space.py).
It is consequential enough to audit before adding more restrictions.

The [self-contained external contract EXT-MATH-001](contracts/EXT-MATH-001-stein-boundary-orbits.md)
states this question and provides its proposed argument. It is ready for the
owner to submit to another LLM; no external answer has been received and no
proof status has been promoted. Code is unchanged.

The initial proposal to continue with known-shape/placement replay under
`VALID-001` was subsequently withdrawn: no useful dependency on the actual
contour pipeline was identified. See [ROADMAP.md](ROADMAP.md) and decision
`D-010` in [HISTORY.md](HISTORY.md). The literature pass does not select an
implementation project; the next step must follow the chosen mathematical
question and its remaining uncertainty.

## Search boundary and chronology

The search covered the four papers above, their relevant references and an
[author-maintained citation list](https://www.math.u-szeged.hu/~zlangi/citations.html).
Queries combined monohedral disk/disc tilings with Stein, interior center,
four tiles, minimum cardinality and the years 2024–2026. Only primary research
sources and author/institutional metadata support the recorded results.
Search-result publication/crawl dates were not used as theorem dates.

In particular, the Nagy–Vígh preprint was submitted in 2021 and the journal
issue is 2023. A later internal date in generated HTML or a reuploaded PDF
does not make its classifications new 2025/2026 results. A full citation-index
survey, unpublished work and author confirmation remain outside this pass.
