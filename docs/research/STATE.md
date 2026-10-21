# Research and implementation state

Inventory dated 2026-10-21, based on repository sources/notes and the project
owner's account. No experiments or test suite were rerun for this inventory.
“Present” and “previously tested” do not mean currently validated end to end.

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
| Contact V2: `search/`, sector bridge and completed-word cache | Partial redesign, not a finished baseline | Exact metric/word propagation and optional retained sectors; missing shared derived state across direct insertions, no demonstrated decisive speedup. See `docs/CONTACT_SEARCH_V2.md`. |
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

The working tree contains substantial modified and untracked code/tests from
earlier work. This documentation change does not validate, commit, revert or
remove them. A repository download at HEAD may therefore omit local V2 work:
before publishing a reproducible baseline, explicitly choose and test the code
to include, and attach a revision/patch identity to each reported result.

The older root `REFACTOR_STATUS.md`, `docs/NEXT_STEPS.md` and versioned patch
notes remain engineering history. Their “stable”, “maintained” or “next” labels
are not a current scientific endorsement or a newly approved development plan.
