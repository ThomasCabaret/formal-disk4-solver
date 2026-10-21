# Research backbone

Updated 2026-10-21. This is the navigation spine for the project. It describes
how the research questions, mathematical claims, search stages and software
artifacts depend on one another. It is not a claim that one current pipeline is
complete or preferable.

Read the [research charter](README.md) for evidence standards, the
[operating method](METHODOLOGY.md) and [live agenda](AGENDA.md) for continuation,
and the [mathematical-results registry](MATHEMATICAL_RESULTS.md) before treating
a filter as a theorem. The [state inventory](STATE.md) records which
implementations currently exist.

The current mathematical and computational domains are defined in
[PROBLEM_SPEC.md](PROBLEM_SPEC.md), from `SPEC-001`. Its default `NT_center`
predicate and stronger `STEIN` target must not be inferred from graph or UI
categories.

Published constructions and classifications are indexed in
[LITERATURE_FRONTIER.md](LITERATURE_FRONTIER.md). Optional, self-contained
external audit tasks live under `contracts/`; their status is tracked through
the parent study and agenda, separately from validated mathematical results.

[MATH-003](studies/MATH-003-two-orbit-stein.md) supplies a proposed exclusion
of two moving orbits, with count bound `N>=3m+1`.
[MATH-002](studies/MATH-002-outer-trace-audit.md) supplies the area-free
interior-circumcenter trace lemma `RSS-TRACE-IC`, removing the earlier KLV trace
premise from that draft. Independent review is pending; this is not an active
code filter or a claim about all Stein tilings.

The owner deferred independent review and selected generalization in
[MATH-004](studies/MATH-004-multiple-orbit-boundary.md). Its
[new draft](../stein_boundary_multiplicity.tex) gives weighted arc repetitions,
a local mirror-capacity constraint and a pure-rotational-shell exclusion.
The capacity bound does not use the connected-trace draft; the stronger
boundary consequences explicitly do. No unconditional general Stein exclusion
or automatic symmetry extension to inner tiles is asserted.

Current owner priority has moved back to formulation tractability:
[CPLX-002](studies/CPLX-002-contour-word-structure.md) traces the actual
constant-free word input and gives [scoped reductions](../contour_word_structure.tex).
Bare existence has a positive-LP construction; prescribed integer word lengths
have a signed interval-cover consistency test using published orbit counting.
Neither supplies the decorated families needed for geometric discovery. Next
is `CPLX-003`, a precise compact interval/type/corner contract. Orbit continuation
is parked; genuinely alternative discovery formulations remain second priority.

## Stable map of research areas (not the live question tree)

The authoritative root-to-approach-to-study hierarchy is in
[AGENDA.md](AGENDA.md). The sketch below is a map of interacting subject areas,
not a second agenda, a mandatory order, or a separation that forbids mathematical
children of algorithmic questions. New approaches may branch at any depth under
the [refinement protocol](METHODOLOGY.md#mandatory-macro-to-micro-refinement).

```text
Nontrivial monohedral tilings of a Euclidean disk
|
+-- A. Pure mathematics
|   +-- impossibility / classification under explicit hypotheses
|   +-- nonconstructive existence
|   +-- constructive families
|   `-- disk-specific structural reductions
|
+-- B. Computational discovery
|   +-- candidate topology and symmetry actions
|   +-- contour incidences, parity and offsets
|   +-- exact length / angle / word constraints
|   +-- numerical realization
|   `-- independent assembly and disk validation
|
+-- C. Algorithmic research
|   +-- Cartesian enumeration (historical baseline)
|   +-- incremental obligation search / backtracking
|   +-- alternative placement-first relaxations
|   `-- symmetry quotients, canonicalization and certificates
|
`-- D. Validation
    +-- known disk witnesses, kept out of discovery priors
    +-- free-boundary patches and tetrads as kernel controls
    `-- differential, soundness and coverage tests
```

The branches interact but do not imply one another. A failed numerical search
in B is not a theorem in A. A theorem in A is useful to B only after its
hypotheses can be recognized soundly from the current search state. A faster
tetrad search in D does not by itself establish a faster disk algorithm.

## Hypothesis envelope

Every study must state, rather than inherit, at least these choices:

- complete disk or free boundary; connected whole patch or selected fragment;
- Jordan-region tiles and any stronger boundary regularity;
- direct isometries only or reflections allowed;
- point contacts versus positive-length interfaces;
- fixed planar embedding versus abstract graph only;
- imposed global symmetry, intrinsic tile symmetry, or neither;
- center-tile/Stein assumption; and
- the operational definition of “nontrivial”.

The registry gives each mathematical claim its own envelope. A program gate may
cite a result only when the request supplies all of that result's hypotheses.

## Representation-independent computational backbone

This is the common sequence of obligations, not a mandate to enumerate each
row in a separate outer loop. A good search may solve several rows jointly or
propagate them incrementally.

| Stage | Question / emitted object | Exact information available | Main current implementation | Mathematical dependencies |
| --- | --- | --- | --- | --- |
| 0. Study specification | What domain is being searched and what counts as success? | Hypothesis envelope and budgets | request/config objects; lab CLIs | none; this is a declared domain restriction |
| 1. Topology | Which embedded contact structures are admissible? | Plane map, exterior incidences, contact type, optional action | `maps/`, `graph_lab/space.py`, `search/contact_types.py` | candidate early reductions `FPR-PER`, `RSS-ORB`, `CHO-HUB` when their premises are explicit |
| 2. Symmetry and copy parity | Which tile copies share an orbit, and are their prototype charts direct or reflected? | Group action, orbit/stabilizer data, parity equations | assignment enumerators; Graph Lab symmetry code; Contact V2 parity state | `RSS-ORB`, `RSS-2ORB`; quotienting itself needs a bijection proof |
| 3. Boundary incidence | Which prototype intervals/endpoints realize each physical interface? | Cyclic offsets, endpoint equalities/order facts, interface maps | legacy mapping + weak-order DFS; tile-frontier search; `search/` Contact V2 | `SSR-REP`; local interface-isometry obligations |
| 4. Incremental metric constraints | Can positive lengths and angle/turn equalities coexist? | Exact linear rows and strict positivity | `constraints/`, `preword/`, Contact V2 metric state | `SSR-CONC`; local length/angle arguments; candidate `FPR-PERIOD` |
| 5. Formal contour words | Are the two sides of every interface compatible as non-erasing words? | Word equations, signed reversal, residual SCCs | `words/`, `search/contact_words.py` | `SSR-NL`, `SSR-PAL`, `SSR-LOOP`, `SSR-CONCUR` |
| 6. Formal profiles | Which supported word families and decorations remain? | Complete formal contour candidates within the supported language | `profiles/`, pipeline specialization | local profile filters; unsupported word systems remain unresolved |
| 7. Numerical realization | Does a formal profile admit coordinates/curves within a stated parameterization? | Numerical contour and residuals | `geometry/` | numerical failure is not an exact rejection |
| 8. Assembly validation | Do congruent copies realize every contact and exactly fill the disk? | Placed copies, overlaps/gaps, boundary and cycle checks | geometry/visualization assembly paths | a validated witness supports existence in the stated class |
| 9. Evidence record | What was proved, exhausted, left unsupported or merely not found? | certificates, provenance, timings and artifacts | reports under `output/`; study notes under `docs/research/` | research charter semantics |

Two design rules follow. First, the traversal policy (Cartesian, backtracking,
SMT, placement-first) should be separable from the exact theory engines in
stages 1–6. Second, no stage may translate `unsupported`, a resource limit, or
numerical failure into `unsatisfiable`.

## Existing constraint engines

Capability index checked at `a80a11c` (2026-10-21), not an independent correctness
audit. Consult this before proposing another length reduction or joint solver.
Use **file plus symbol**, not line numbers alone, and inspect the callers for
the selected mode. These engines coexist; they are not all stages of every run.
The broader stage table above and [STATE.md](STATE.md) remain the project map.

| Existing capability | Definition / call path | Boundary to preserve |
| --- | --- | --- |
| Interface length projection and positivity | [`weak_orders.py`](../../src/formal_disk4/enumeration/weak_orders.py), `_resolved_length_rows`; [`length_lp.py`](../../src/formal_disk4/constraints/length_lp.py), `LengthFeasibilityOracle`; used by the weak-order enumerator. | Already forms homogeneous equal-length rows. This oracle directly rejects exact same-sign contradictions; numerical LP failure remains unknown. Length feasibility is not full word or geometry feasibility. |
| Joint cyclic weak-order / length guidance | [`joint_weak_length.py`](../../src/formal_disk4/enumeration/joint_weak_length.py), `CyclicJointWeakLengthOracle`; `WeakOrderEnumerator._joint_cyclic_oracle` in `weak_orders.py`. | Solves coordinate/order and interface-length constraints under the supported direct cyclic action, not all topology or arbitrary symmetry constraints. |
| Preword metric and turning relaxations | [`linear_invariants.py`](../../src/formal_disk4/preword/linear_invariants.py), `PrewordLinearInvariantFilter._analyze_metric` and `_analyze_point_turns`; configured in [`pipeline/runner.py`](../../src/formal_disk4/pipeline/runner.py). | Already combines lengths, positive/negative radius-R arc measures, curve turns and point constraints. Global disk identities have free-boundary and regularity guards; these are necessary constraints, not complete word solving. |
| Incremental metric/word propagation (Contact V2) | [`contact_words.py`](../../src/formal_disk4/search/contact_words.py), `ContactWordTheory.check`, `ForcedLengthComparison`; called by [`contact_types.py`](../../src/formal_disk4/search/contact_types.py), with [`linear.py`](../../src/formal_disk4/search/linear.py), `LinearTheory`. | Uses affine lengths to force Levi comparisons, propagates factors/corners and optionally explores residual comparisons. Already more than a final length filter; not a complete compact solution of the decorated problem. |
| Mirror-compatible terminal refinement | [`words/compile.py`](../../src/formal_disk4/words/compile.py), `refine_mirror_compatible_terminal_environment`; invoked by `pipeline/runner.py`. | For a concrete family specialization, exact positive rational weights are scaled to integer subdivisions. This already constructs common refinements, not merely tests unit-atom lengths. |
| Terminal metric and joint angular solving | [`profiles/decorations.py`](../../src/formal_disk4/profiles/decorations.py), `_terminal_lengths`, `_build_joint_angular_feasibility`, called by `build_decorations`. | Carries word identifications and length-sector constraints into lengths, angles and curve turns, with circular turn/length coupling. Does not itself establish numerical realization or disk coverage. |

Related controls (presence only, not rerun by this index update):
[`test_joint_weak_length.py`](../../tests/test_joint_weak_length.py),
[`test_preword_linear.py`](../../tests/test_preword_linear.py),
[`test_contact_search.py`](../../tests/test_contact_search.py),
[`test_mirror_refinement.py`](../../tests/test_mirror_refinement.py),
[`test_joint_angular.py`](../../tests/test_joint_angular.py).
Detailed Contact V2 limitations remain in [its status note](../CONTACT_SEARCH_V2.md).

In particular, `CWS-BARE` in CPLX-002 is a scoped theoretical interpretation of
bare constant-free existence, **not** the introduction of linear length solving
to this project or a measured speedup. Any proposed compact decorated solver
must identify what the engines above cannot already propagate or represent.

## Existing traversal strategies

| Strategy | Where it branches | Reused kernel | Present status |
| --- | --- | --- | --- |
| Classic map pipeline | complete assignment, then weak cyclic orders, then words | stages 3–8 | Historical executable baseline; large Cartesian products are the known weakness. |
| Graph Lab | graph proposal/ranking followed by existing formal evaluation and geometry queue | much of stages 1–8 | Interactive workbench; neither proposal coverage nor learning benefit is established. |
| Tile-frontier / fixed-graph search | adds a tile/frontier decision and checks partial constraints | legacy exact filters plus diagnostic geometry | Useful diagnostic baseline; bounded runs are not exhaustive unless explicitly reported so. |
| Contact V2 | introduces contact obligations lazily and co-propagates parity, order, metric and word facts | new `search/` state plus adapters to existing word machinery | Partial implementation of the design in `contact_type_enumerator_design.tex`; no decisive end-to-end gain established. |
| Placement-first Stein proposal | placement boxes, relaxations, boundary synthesis, exactification | largely alternative continuous route | Design proposal in `stein_search_algorithm.tex`, not the current production pipeline. |
| Learned ranking | ranks graph/mapping/order pools | legacy/Graph Lab evaluators | Parked. It must not be reactivated by default while the underlying decisions remain unsettled. |

The editable historical pipeline diagram is documented in
[SOLVER_PIPELINE.md](../SOLVER_PIPELINE.md). It is a snapshot of the classic
pipeline, not the unique research architecture. The proposed monotone filter
ladder in `filter_pipeline_roadmap.tex` is likewise a proposal: each new result
must pass the registry's proof and implementation audits before becoming a
production rejection.

## Result-to-code dependency map

The identifiers below resolve in
[MATHEMATICAL_RESULTS.md](MATHEMATICAL_RESULTS.md).

```text
SSR-REP ------------------> boundary-incidence / weak-order pruning
RSS-ORB ----+-------------> Stein graph/symmetry-domain validation
RSS-2ORB ---+
SSR-CONC -----------------> preword strict radius-R concavity inequality

SSR-NL -------------------> complete local Nielsen--Levi branches
SSR-PAL ------------------> mirror-fixed word factorization
SSR-LOOP -----------------> supported unary fixed-context loop compression
SSR-CONCUR ---------------> non-simple residual SCC => unsupported, not UNSAT

RSS-TRACE-IC + intrinsic rotation of the Stein center tile
    +--> RSS-OVERLAP --> RSS-ORB --> RSS-2ORB

RSS-ORB + RSS-2ORB + intrinsic tile rotation
    +--> RSS-SECTOR ------> RSS-2ORB-EXCL (new proof draft; no code gate)

Connected-trace premise (MATH-002 draft) + intrinsic tile rotation
    +--> RSS-MULT (weighted repetitions for arbitrary orbit counts)
    `--> RSS-ROT-SHELL (pure rotational shell needs extra interior tiles)
Centered mirror pair + intrinsic rotation + disk containment
    +--> RSS-MIRROR-CAP (no connected-trace premise)
RSS-MULT + RSS-MIRROR-CAP
    +--> RSS-MIRROR-ORB (conditional many-orbit lower bound)

CHO-HUB / CHO-WORD -------> candidate early cyclic-hub rejection
FPR-PER ------------------> proposed graph-only perimeter filter
FPR-PERIOD ---------------> proposed row-space period-interface rejection
```

The first two groups have identifiable code references. The last group remains
candidate work unless the registry says otherwise. “Implemented” means that a
code path exists; it does not certify the source proof or the correctness of the
hypothesis detector.

## How a result becomes an active filter

1. Give the claim a stable registry ID and preserve its full editable source.
2. Audit the proof and every external dependency; record the reviewer and scope.
3. Define a machine-checkable premise detector. Test near-miss cases where one
   hypothesis is absent.
4. Implement a certificate-producing rejection or a clearly identified
   quotient. Keep heuristics as ordering signals only.
5. Run soundness controls, known positives and differential tests with the
   filter disabled/enabled.
6. Measure conditional rejection, cost and descendants avoided. Promote the
   filter only if it is both sound in scope and useful.
7. Cite the registry ID and source label in the code comment. Update this map if
   the stage or logical status changes.

## Research branches presently worth keeping visible

- **Proof audit and disk structure:** audit the direct-use results first, then
  investigate genuinely disk-specific reductions rather than generic shape
  heuristics without a regularity hypothesis.
- **Incremental exact enumeration:** determine whether Contact V2's obligation
  representation preserves coverage and reduces the tested search tree on
  small controlled instances.
- **Word-equation boundary:** characterize the residual systems actually
  produced; unsupported SCCs are a research target, not negative instances.
- **Geometry validation:** keep realization and complete assembly distinct, and
  build positive controls for both.
- **Alternative formulations:** placement-first, constructive, or purely
  mathematical approaches remain legitimate even if they bypass the current
  formal-contour pipeline.

These are branches, not an automatically authorized implementation backlog.
Each next step starts with one study record and one falsifiable question.

## Formulation-complexity boundary from CPLX-002

```text
Fixed graph
  -> still choose charts, parity, endpoint incidence and weak order
Fixed incidence -> constant-free signed word equations
  +-> bare non-erasing existence -> CWS-BARE (positive LP, proof draft)
  +-> prescribed integer word lengths -> CWS-COVER (signed interval orbits)
  `-> geometry-relevant identifications + corner/circle/metric constraints
       -> actual unresolved tractability target, CPLX-003
```

The easy existential witness can identify too many factors and fail disk
decoration. It is not a complete family description and must not replace the
word engine silently. Conversely an explicit word or family expansion may be
huge even when a compressed representation is small. Fixed-length orbit counts
alone do not reconstruct all geometry-relevant curve classes. No result here
decides the unknown-length decorated problem or the unrestricted tiling problem.
