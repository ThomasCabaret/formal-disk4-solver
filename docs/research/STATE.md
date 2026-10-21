# Research and implementation state

Inventory dated 2026-10-21, based on repository sources/notes and the project
owner's account. The recovered experimental code snapshot was regression-tested
after this inventory (374 tests passed, one skipped, plus 217 parameterized
subtests); no research experiment or performance benchmark was rerun.
“Present”, “previously tested” and a passing regression suite do not mean an
approach is scientifically or end-to-end validated.

## Research restart progress

`SPEC-001` delivered [a working problem specification](PROBLEM_SPEC.md): the
broad Jordan-region disk target, separate center predicates and three finite
computational variants. Read-only code inspection traced the current graph,
regularity and engine restrictions; it did not reveal a new demonstrated solver
bug or establish complete validation.
See [the study](studies/SPEC-001-problem-domain.md) for scope and remaining review.

The first `MATH-001` pass produced [a literature map](LITERATURE_FRONTIER.md).
It identified constructive control families and restricted classifications,
but did not settle the current general Stein question or audit the local
stronger theorems. The owner subsequently selected `MATH-003`;
`VALID-001` was withdrawn without starting it: its usefulness to the actual
formal-contour pipeline had not been established. [ROADMAP.md](ROADMAP.md)
describes competing approaches, not compulsory sequential phases. The live
agenda now exposes impossibility/classification, nonconstructive existence,
constructions and computational discovery, with the formal-contour route as one
algorithmic candidate. The methodology requires a root-to-node path, alternatives
and outcome-to-parent consequences before substantive work, then an explicit
return to the parent. This changes research governance, not scientific evidence.
Original mathematical creation
is an explicit objective. The optional
[external RSS-ORB audit](contracts/EXT-MATH-001-stein-boundary-orbits.md) is ready
for submission by the owner; it has no returned answer and does not determine
the next independent study. No solver or search-performance evidence changed.

### First original-mathematics attempt: MATH-003

[The study](studies/MATH-003-two-orbit-stein.md) now contains a complete
[proposed proof](../two_orbit_stein_obstruction.tex) excluding two moving orbits
in a rotational Stein disk tiling for every order `m>=2`. It combines a new
intrinsic-rotation/sector obstruction for `m>=3` with a five-lens area bound for
`m=2`. If accepted together with the needed orbit reduction, this strengthens
the count bound to `N=1+km`, `k>=3` (`N>=3m+1`).

The first draft was conditional on KLV's published outer-trace premises.
[MATH-002](studies/MATH-002-outer-trace-audit.md) now supplies an area-free local
replacement: a prototile whose smallest enclosing disk has its center strictly
inside the tile has connected outer traces. Rotational Stein tiles satisfy
that condition by a zero-mean orbit argument. The two transport facts are also
locally proved, so the integrated draft has no additional outer-trace premise.

The published proof's general Jordan-boundary area question was not settled;
the replacement suffices for this narrower application rather than refuting
the general lemma. Independent acceptance and novelty remain pending. Earlier
finite numerical identity checks are algebra sanity checks, not proof
certificates; no numerical test is claimed to validate the new topology proof.
[EXT-MATH-002](contracts/EXT-MATH-002-two-orbit-obstruction.md) is ready for
optional independent review, not submitted. No new rejection was enabled in code;
no discovery run or performance benchmark was launched. That iteration did not
address the larger-orbit or asymmetric Stein questions.

### Many-orbit generalization: MATH-004

At the owner's request, independent review is deferred, not silently considered
complete. [MATH-004](studies/MATH-004-multiple-orbit-boundary.md) delivers
[proposed weighted boundary and mirror-capacity constraints](../stein_boundary_multiplicity.tex).
Boundary repetitions explicitly assume connected traces from the earlier
unaccepted draft. A separate local argument needs no such premise: a centered
reflection between different moving orbits confines a tile to a narrow wedge,
bounding its circumradius and forcing a quadratic necessary tile count as
symmetry order grows. Combined conditionally with the boundary count, it forces
at least `ceil(sqrt(F_m))` outer orbits. This generalizes a constraint, not the
full nonexistence theorem.

The exact obstruction to copying the old global argument is now explicit:
an outer-shell symmetry may preserve the remaining region without preserving
its inner tile partition. The orientation-preserving centered-match branch
survives, particularly with three moving orbits. That continuation is now parked
after the owner's formulation-complexity recadrage. No production code, discovery run, checkpoint or performance evidence
changed; all statements remain proof drafts, and novelty is not certified.

### Current priority: contour tractability, CPLX-002

The owner prioritized the actual complexity of contour solving and a second
track comparing alternative discovery formulations. The first
[CPLX-002 study](studies/CPLX-002-contour-word-structure.md) traces the bare
compiler input as constant-free signed word equations. It proposes an elementary
positive-LP existence reduction and a fixed-integer-length signed interval-cover
test. These are precise subproblems, not classifications of the full decorated
or geometric problem. New mathematical deductions remain proof drafts.

The positive-length projection is already implemented in several engines; see
the [capability index](BACKBONE.md#existing-constraint-engines). CPLX-002's bare
existence interpretation is not a new solver capability or a demonstrated gain.

The isolated probe matched its explicit signed-cover test with exhaustive
one-opposite-pair word search on 164 small systems. All four actual small compiler
controls had direct periodic word witnesses; both disk ones failed angular
decoration, while ordinary families on those same placements passed profile
filters. The two free-exterior probes built formal profiles only. No geometry
was run. Fifteen targeted existing tests passed; there was no full regression
run or claim that the historical solver is now validated.

This changes the explanation being investigated: large family enumeration is
not necessary just to answer bare word satisfiability; preserving identifications
that may satisfy circle/corner geometry is the actual unresolved task.
`CPLX-003` will define that compact-constraint task before any new kernel. No
production solver code, learned policy, active search, checkpoint or environment
was changed. The small generated JSON under `output/CPLX-002/` is uncommitted.
No end-to-end speedup or impossibility/hardness theorem was obtained.

## What the history supports

- The owner reports rediscovery of known nontrivial 12-tile disk tilings under
  imposed symmetry. The exact run artifacts and witnesses should be identified
  before using these as a reproducible current baseline.
- Broad enumeration and later learned ordering did not deliver the desired
  practical exploration. This is the motivation for reassessment, not a proof
  that every formal-contour or learning approach must fail.
- Relaxed patches and tetrads exposed performance problems and prompted fixes
  and redesigns. Their failures must not be read as disk impossibility results.
- September notes report passing targeted tests but no demonstrated end-to-end
  speedup for the latest V2 additions. Tests and timings are dated evidence only.

## Approach inventory

| Area and location | Current research status | What it offers / limitations |
| --- | --- | --- |
| Formal kernel: `src/formal_disk4/{constraints,preword,words,profiles,pipeline}` | Reusable implementation, validation remains scoped | Formal equations, pruning and decoration; word solver deliberately leaves some languages unsupported. Not a complete decision procedure for the original problem. |
| Numerical geometry and assembly: `geometry/`, `visualization/` | Existing validation tools | Realization and display; distinguish a single contour from an assembled disk. Numerical failure is not an infeasibility certificate. |
| Catalogue / classic enumeration: `maps/`, `enumeration/`, `config/cases/`, old Tk GUI | Historical baseline / compatibility | Useful reference cases and regression controls; exhaustive Cartesian-style search is not the current research priority. Catalogue is not an enumeration of all admissible graphs. |
| Web Graph Lab: `graph_lab/app.py` and related modules | Most developed interactive workbench | Prior-driven graph proposal, reporting, geometry queue; good interface does not establish search completeness or efficiency. |
| Learned policies / Mapping Lab: `mapping_lab/`, learning modules in `graph_lab/` | Parked as a research priority, code retained | No convincing practical benefit established in this project history. Do not tune or reactivate by default. |
| Tile-frontier / fixed-graph campaigns | Diagnostic experimental baseline | Incremental placement and live progress; inspect budgets and unsupported cases before interpreting exhaustion. See `docs/backtracking_lab.md`. |
| Contact V2: `search/`, sector bridge and completed-word cache | Preserved tested experiment, not a finished baseline | Exact metric/word propagation and optional retained sectors; missing shared derived state across direct insertions, no demonstrated decisive speedup. See `docs/CONTACT_SEARCH_V2.md`. |
| Stein symmetry, crowns, free boundaries, intrinsic prototype symmetry | Restricted domains / diagnostic tools | Useful experiments with distinct hypotheses; not interchangeable with the general disk problem, nor supported by every engine. |
| Mathematical/design sources: `docs/*.tex` | Sources to review individually | Structural results, candidate reductions and algorithm proposals. Presence in the repository is not proof-review certification. |
| `docs/legacy/`, `legacy_reference/`, root patch notes/manifests | Historical record | Preserve context; not current instructions or promises of compatibility. |

The inverse-shape heuristic and earlier global-filter proposal were set aside
in the conversation after unsatisfactory assessment/experiments. This inventory
does not revive them or claim a general mathematical refutation of those ideas.

## Reading map

1. [Research charter](README.md): goals, tracks, methodology and outcome meanings.
2. [Operating method](METHODOLOGY.md) and [live agenda](AGENDA.md): how work is
   selected, traced, interrupted, resumed and reintegrated.
3. [Decision history](HISTORY.md): compact chronological rationale for changed
   priorities and closed/parked branches.
4. [Research backbone](BACKBONE.md): dependency tree, representation-independent
   pipeline, traversal strategies and result-to-code map.
5. [Mathematical-results registry](MATHEMATICAL_RESULTS.md): stable result IDs,
   hypotheses, source labels, implementation references and proof-review status.
6. [Architecture](../ARCHITECTURE.md), [solver API](../solver_api.md): existing
   implementation boundaries; architectural vocabulary may predate V2.
7. [Contact V2 status](../CONTACT_SEARCH_V2.md): actual partial deliverables,
   limitations and historical timings; not an instruction to keep extending it.
8. [Backtracking Lab](../backtracking_lab.md),
   [local campaigns](../local_graph_campaign.md): diagnostic entry points.
9. `../six_structural_results.tex`, `../rotational_stein_structural_note.tex`,
   `../cyclic_hub_obstruction.tex`: mathematical sources for later scoped review.
10. `../contact_type_enumerator_design.tex`, `../stein_search_algorithm.tex`:
   design proposals, distinct from verified implemented behavior.

## Repository boundaries and preservation

Keep one editable documentation tree (`docs/`), with the new research direction
in `docs/research/`. Existing `src/`, `tests/`, `config/` and `scripts/` remain in
place. `output/`, `logs/`, `diagnostics/` and `tmp/` may contain generated or local
artifacts; none is declared disposable wholesale by this inventory. Determine
owners, provenance and active-run status before any cleanup.

The formerly modified and untracked implementation files were audited as one
interdependent historical snapshot and preserved rather than selectively
discarded. They include Contact V2, tile-frontier backtracking, fixed-graph
campaigns, Euclidean placement diagnostics, progressive numerical geometry,
length-sector propagation and word-result caching. The full regression suite
passed at preservation time, but no speedup or research conclusion was inferred
from that fact. See decision `D-005` in `HISTORY.md`.

The older root `REFACTOR_STATUS.md`, `docs/NEXT_STEPS.md` and versioned patch
notes remain engineering history. Their “stable”, “maintained” or “next” labels
are not a current scientific endorsement or a newly approved development plan.
