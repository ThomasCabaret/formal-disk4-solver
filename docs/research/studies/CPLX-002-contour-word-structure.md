# CPLX-002 — What word systems does the contour formulation actually produce?

## Identity

- Node / parent: `CPLX-002` / `CPLX-001`.
- Path: `R0 -> CPLX-001 -> CPLX-002`; supporting mathematical/algorithmic study.
- Cross-benefit: `R0 -> APP-SEARCH -> APP-CONTOUR` and comparison `ALG-001`.
- Track: `COMPLEXITY` / `MATH` / `ALG`; status: supported-in-scope for this
  bounded structural diagnostic, not a full decorated-system classification.
- Investigator/date: repository agent (LLM), 2026-10-21.
- Root benefit: determine whether the contour route can avoid its current
  combinatorial explosion before investing in a larger implementation or search.

## Question and hypotheses

- Question: does the class of word systems induced by a fixed finite embedded
  contact structure have exploitable restrictions absent from general word
  equations, and does the current family enumeration obscure them?
- Working hypothesis: at least part of the explosion comes from representation
  or from asking to enumerate all refinements rather than propagating an
  equivalent compact constraint. This is not a promise of polynomial solving.
- Domain: finite embedded contact systems for congruent connected Jordan tiles;
  reflections allowed; no imposed symmetry by default. Compare free boundary
  and exact circular exterior explicitly. Fixing a graph does not fix copy
  charts, incidence order, refinement size or geometry.
- Separate tasks: formal existence, a formal witness, a representation of all
  formal solutions, and a geometrically realizable disk witness. A solution of
  the first is not a solution of the last.
- No claim about arbitrary Jordan contours, NP/PSPACE completeness of tiling,
  or mathematical impossibility from an unsuccessful solver.

## Decision context

- Owner selected these priorities after challenging the lower-leverage orbit
  continuation: first actual contour tractability, second alternative discovery
  formulations. `MATH-004` continuation is parked, sources retained.
- Parent decision: keep/reformulate the word layer, exploit a restricted class,
  identify a hardness boundary, or prioritize a different representation.
- Alternatives: another orbit obstruction, a general literature survey, or an
  immediate solver rewrite. None discriminates this representation question as
  directly as extracting the actual equations and one precise structural result.
- Support: prove a useful equivalent compressed formulation or tractable
  fragment, with exact limitations and geometry compatibility obligations.
- Refutation: exhibit an actual produced family contradicting the proposed
  structural restriction; that does not automatically prove general hardness.
- Inconclusive: preserve the exact missing reduction/representation theorem and
  return to the parent rather than start an unbounded implementation.

## Evidence plan

1. Trace constructors, variable semantics, involution, point symbols and metric
   coupling in both classic and Contact V2 paths. Give file/line references.
2. Compare the extracted family with relevant primary word-equation results;
   do not import their complexity unless the encoding and hypotheses match.
3. Attempt one bounded structural derivation, with a small reproducible control
   if useful. Prefer removing a search dimension to timing another large tree.
4. Stop with a scoped mathematical draft/diagnostic and the next decision. No
   production rewrite, learning, long campaign or checkpoint changes.

## Reproduction

- Starting revision: `2aab3abf60e622fbc5a65d9e1a4ac93ec27b8d6d`; clean tree.
- Sources: `docs/research/PROBLEM_SPEC.md`, `docs/six_structural_results.tex`,
  word constructors/solvers and `search/contact_words.py`.
- No independent review completed; all new mathematical deductions remain
  drafts. Any small script is diagnostic, not a tiling oracle.

## Results

Proof/diagnostic source: [contour_word_structure.tex](../../contour_word_structure.tex).
Reproducible small probe:
[probe_contour_words.py](../../../scripts/research/probe_contour_words.py).
All newly derived mathematical statements remain proof drafts; independent
acceptance and literature novelty are not claimed. The elementary constant-free
construction is not presented as a new word-theory theorem.

### 1. Extracted equation class and implementation trace

| Location at the starting revision | Observation | What this does not establish |
| --- | --- | --- |
| `words/algebra.py:8`, `:35` | Literals are signed variables. Inverse reverses the sequence and flips signs; no adjacent inverse cancellation is performed. | This is not the freely reduced group-word problem. |
| `words/compile.py:186` | Atomic variables form one cyclic prototype order. An interface uses oriented proper factors of that order; each atomic interval appears at most once on one initial equation side. | No globally quadratic occurrence bound across the system or after substitution. |
| `words/compile.py:223`–`:260` | Effective equations contain only variables, inverses and separate mirror-sheet variables, with mirror closure when reflected contacts occur. | Physical mirror constraints and their later common refinement are not all encoded by independent sheet variables alone. |
| `words/compile.py:262`, `:273` | Circular outer and free factors are stored as metadata, not prescribed constant strings in the effective word equations. | Circle semantics are not ignored: preword checks and later decorations use them; changing the boundary can change upstream survivors. |
| `words/compile.py:289` | Intrinsic rotation adds a variable sector power equation, still with no constant letters. | Matching that word period is not sufficient for a geometric rotation. |
| `search/contact_words.py:81`, `:114` | Contact V2 already adds corners and exact metric comparisons in incremental propagation. | The full propagated state is not merely the bare constant-free system below. |
| `words/exact_partial.py:830`, `words/families.py:333` | The existing leaf machinery enumerates supported exact families and specializes their exponent parameters. | It is doing more than deciding whether one bare word solution exists. |
| `pipeline/runner.py:1911`, `profiles/decorations.py:1200` | Each specialization is rebuilt and checked for angular/curve conditions, including circular turn. | One formal word witness cannot replace all geometry-relevant families. |

The raw compiler controls have repeated equations. Their maximum occurrence
counts are **not** used as a counterexample to a quadratic condition after
deduplication. No claim that arbitrary word equations reduce to valid planar
contact systems has been established.

### 2. Bare existence reduces to a positive linear system

Let `A` count the occurrences of each variable on the left minus the right
of every equation, ignoring inverse signs. For a **constant-free** system of
non-erasing words with reversal-complement involution, existence is equivalent
to a positive null vector `A*x=0`, `x>0`.

Proof draft `CWS-BARE` / `prop:bare`:

1. Any word solution gives positive integer word lengths satisfying those rows.
2. A positive real null vector can be scaled into `x>=1`; rational linear
   feasibility supplies a rational point, then denominator clearing gives
   positive integers `n_i`.
3. Choose one opposite letter pair `a,bar(a)` and the nonempty block
   `w=a*bar(a)`, fixed by the anti-involution. Assign `X_i=w^n_i`.
   Every signed variable is a power of this same block, so all equations hold.

The bare decision problem is consequently polynomial-time solvable by rational
LP. This does **not** give our simplex a polynomial pivot guarantee, solve
prescribed exact odd word lengths, include constant letters, or decide the
decorated/geometric problem. Word lengths and physical arclengths are distinct.
Homogeneous mirror-length equalities can be included, but all physical mirror
semantics are not thereby discharged.

A Fibonacci recurrence gives an explicit family of small systems whose minimum
expanded words have exponential length. The equations even have sides that are
proper factors of one common cyclic variable order. Binary powers give short
witness descriptions. This is an **output-expansion** example, not NP-hardness;
its realization as valid embedded tile data has not been proved.

### 3. Why that cheap witness loses essential information

The universal periodic witness identifies far more pieces of word than a
general solution. For any additive observable `chi` satisfying
`chi(inverse(U))=-chi(U)`, it forces every variable and compiled factor to have
zero `chi`. It cannot meet a positive such requirement on an outer arc.
This is draft `CWS-CHARGE` / `prop:charge`, not a license to reject all periodic
contours; intrinsically symmetric valid shapes can have periodic contours.

Commutation illustrates the other direction: `XY=YX` forces common-root powers,
so positive metric lengths `ell` and an additive observable `chi` obey
`chi(X)*ell(Y)=chi(Y)*ell(X)`. Separate additive rows do not express that
consequence. This is a standard algebraic example re-derived in the note,
not an identified compiled disk family or a new literature theorem.

Thus neither a generic word-equation hardness citation nor replacing the word
engine by its easiest LP witness answers the real question. The remaining task
is selecting/preserving identifications that can satisfy the decorated geometry.

### 4. A compact fixed-length consistency reduction

For prescribed positive integer **word lengths** `L_i` (binary encoded), store
all variable positions in blocks of an integer interval of size `N=sum(L_i)`.
Comparing equation factors creates only a linear number of signed interval
pairings in the explicit syntax size: merge factor endpoints without expanding
the individual positions. First check the total lengths of both sides.

Ignore the signs and count positional orbits `c`. Duplicate the interval into
two sheets and lift each pairing of sign `epsilon` to
`(p,b) ~ (q,b xor epsilon)`; let the lifted orbit count be `c_cover`.

Draft `CWS-COVER` / `prop:cover` proves:

```text
fixed-length bare word system is satisfiable iff c_cover == 2*c.
```

An unsigned component lifts to two components unless it has an odd-sign loop,
which would equate a letter to its opposite. When no such loop exists, choosing
opposite letters on the paired components constructs a solution. The input
relations are integer interval isometries, so the published AHT orbit-counting
algorithm makes this a polynomial test in syntax size and `log(N)`.

This is a reduction for **fixed** lengths and **bare** consistency, not a
polynomial method to choose unknown lengths, solve angular/circular conditions
or recover all useful curve degrees of freedom. Orbit counts alone cannot feed
the geometry stage. AHT is not implemented by the diagnostic script, and no
practical polynomial bound or speedup for the whole search is asserted.

### 5. Small controls actually run

Command from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts\research\probe_contour_words.py `
  --output output\CPLX-002\word-probe-v1.json
```

If using another Python with project dependencies, set `PYTHONPATH` to `src`
and run the same script. The local venv has Python 3.12.5, NumPy 2.5.1,
SciPy 1.18.0. It lacks NetworkX, which this probe does not need. The bundled
Python lacks SciPy; no package was installed or environment changed.

- Fixed seed `27021`: 160 generated tiny signed systems plus four edge controls.
  The explicit signed-cover criterion matched exhaustive enumeration over one
  opposite letter pair in **164/164** cases. This validates the small control
  mechanism, not the compact AHT implementation (there is none).
- For the same finite systems, exact positive-length LP constructed **30**
  periodic witnesses, checked by substitution in the original equations;
  **134** LPs were infeasible. These are separate unknown-length and fixed-length
  tasks: their YES counts are not compared as if they had the same domain.
- Compiler controls: the first surviving direct-chart placements of `c3` and
  `c4`, with the ordinary disk boundary and with an isolated free-exterior
  projection, give **4/4** exact word witnesses by LP and direct substitution.
  These controls do not sample reflected compiler charts or large maps; the
  proof statement includes signed variables, and the algebra controls do too.
- On both disk controls, that witness is rejected in
  `joint_angular_feasibility` with
  `inconsistent angular equation from terminal-contour`. For the **same
  placements**, the existing solver's first ordinary family passes the profile
  filters (**2/2** controls). This demonstrates the extra identifications imposed
  by the universal witness; it does not diagnose a solver bug.
- Both free-exterior universal witnesses build formal profiles. No geometry or
  overlap/coverage check was requested or performed; these are not patch solutions.
- LP plus witness construction in those four tiny cases took approximately
  `0.08–0.10 ms` each in this run; the measured probe body took `0.145 s`,
  excluding interpreter/module startup. Different tasks and tiny samples:
  **no speedup claim** over family enumeration or disk discovery follows.
- Existing targeted tests passed: `test_words.py` (2), `test_exact_partial.py`
  (10), `test_mirror_refinement.py` (3). Not a full regression or geometry audit.

Artifact `output/CPLX-002/word-probe-v1.json` is generated evidence, uncommitted.
It is 3,115 bytes in this run and covered by the existing output ignore rule.
The starting revision plus the new probe/source/study files and agenda changes
identify this iteration; no production solver code was edited. No long search,
training process or existing checkpoint was touched.

Documentation checks passed: 157 local research Markdown links resolve; all 19
agenda nodes reach `R0` without cycles; the new TeX environments nest correctly
and its three labels/references resolve; the probe parses as Python;
`git diff --check` passes. No PDF compilation or independent proof review was
performed. These checks do not validate the mathematical deductions themselves.

### 6. Primary-source boundary

Consulted on 2026-10-21:

- [Jeż, *Word equations in linear space*, v2](https://arxiv.org/abs/1702.00736):
  general word equations with constants; complexity statement not transferred
  to our constant-free/decorated subclass.
- [Diekert–Jeż–Plandowski, *Finding All Solutions…*, v2](https://arxiv.org/abs/1405.5133):
  finite graph descriptions of solution sets with involution/rational constraints;
  these do not imply that enumerating our supported powers is necessary or complete.
- [Agol–Hass–Thurston, v2, Section 4, Theorem 12](https://arxiv.org/html/math/0205057v2):
  interval pairing orbit counts in polynomial time in `k*log(N)`. Only this
  theorem is invoked, not the paper's unrelated knot-genus hardness theorem.
  Its published statement and surrounding algorithm were read, not independently
  audited end to end; the signed lift is a local derivation.

This was a targeted source check, not an exhaustive contemporary literature
review. No novelty claim for the algebraic constructions or a complexity
classification of monohedral tilings is made.

## Interpretation and return to parent

- Result: the bare constant-free word existence problem has an elementary LP
  route, whereas our expensive layer is used to produce geometry-relevant
  factor-identification families. The distinction changes the research target:
  general word satisfiability hardness is not the explanation established here.
- Parent `CPLX-001` remains open for decorated systems, unknown metric choices,
  incidence search and actual realizability. Neither universal polynomial
  solvability nor intrinsic hardness of those tasks has been shown.
- Open next sibling `CPLX-003`: fixed-length signed interval constraints with
  circular-arc type/sign propagation and corner data. Determine exactly what
  can be checked or represented compactly without enumerating complete families.
  It must preserve useful geometric alternatives, not just return the collapsed
  universal witness. Start with a precise contract and a discriminating small
  control, not a replacement production solver or a large AHT implementation.
- `ALG-001` remains the second-priority alternative-formulation comparison;
  it need not await a general complexity theorem. Orbit continuation and learning
  remain parked. Return upward if the compact route merely relocates the same
  unknown-length explosion without a useful restriction.
- Agenda/backbone/registry/state and history decision `D-015` record this return.
