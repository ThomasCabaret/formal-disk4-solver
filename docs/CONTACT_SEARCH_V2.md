# Incremental contact search: first executable layer

This is a **partial implementation** of `contact_type_enumerator_design.tex`,
not the complete contact/word unification algorithm described there.

## Implemented

The fixed embedded graph supplies one positive arclength variable per physical
interface. The two views of an internal interface share that variable. Every
tile has the same perimeter (normalized to one), starting at the root, including
tiles not yet assigned a contour chart.

For each additional tile, choose its direct/reflected orientation and its first
marked corner after the prototype cut. Corner coordinates are an offset plus
sums of interface lengths. Insert corners one at a time, either coincident with
an existing prototype corner or strictly inside an interval. Local chart order
removes impossible insertions without a solver call. An affine feasibility
check follows every remaining decision. Coincidences additionally merge angle
variables and check the physical junction constraints.

Negative LP decisions require an exact rational result; numerical failure alone
does not prune. A feasible numerical result merely permits continued search.
Free boundary angles use the map's own strict upper bounds, not disk-specific
global invariants. The reference chart fixes only the common cyclic origin and
orientation. Other tile reflections are still explored.

## Module boundaries

- `search/contact_model.py`: shared physical variables and local charts.
- `search/linear.py`: immutable affine constraints, bounded feasibility caches.
- `search/angles.py`: necessary junction constraints.
- `search/contact_turns.py`: partial integrated-turn constraints.
- `search/word_propagation.py`: deterministic cancellation and forced Levi splits.
- `search/contact_words.py`: partial interface compilation and angle consequences.
- `search/word_refinement.py`: existential three-case Levi lookahead.
- `search/contact_types.py`: streaming DFS over charts and corner incidences.
- `search/placement_adapter.py`: conversion to the existing formal kernel.

The graph source is outside this search. A consequence-only partial validator
can be added without replacing traversal. Word solving, decoration and geometry
still use the existing kernel and run on each completed contact arrangement.

## Explicit remaining work

This first layer still constructs the **direct marked-point arrangement**.
It propagates forced word equalities during partial construction, but does not
yet persist derived word cuts between direct-incidence DFS nodes, implement conflict learning or canonical
augmentation, or generate the graph inside DFS. In particular it does not prove
finite closure of arbitrary word refinements. Imposed automorphisms and intrinsic
prototype rotation are explicitly unsupported by this engine for now, rather
than silently routed through the old engine.

Residual word-system guardrails remain proof gaps. Exhausting the direct search
with such gaps is not a negative certificate for all geometric realizations.
This version has not demonstrated a large end-to-end speedup on the tetrad.

## Launch a free-boundary tetrad, without learning

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH="$PWD\src"
py.exe -m formal_disk4.graph_lab.backtracking_lab `
  --engine contact-types `
  --contact-word-refinement-depth 2 --contact-word-sectors `
  --graph-family center-ring --min-tiles 4 --max-tiles 4 `
  --output-directory output\backtracking_lab\tetrad-contact-v6 `
  --port 8771
```

The web dashboard opens automatically. It shows current local branch choices,
early rejections, elapsed time, emitted profiles and geometric solutions. Local
choice fractions are **not** a percentage of the whole tree. There is no global
time/node/leaf ceiling in this command. The graph stops at a geometric solution
or traversal exhaustion, retaining the kernel's explicit word proof gaps.

Use a new output directory for a fresh experiment. Reusing the same directory
skips completed graphs but **does not resume a DFS stack** inside an interrupted
graph: that graph is searched again. Mixing engines in one directory is refused.
The legacy comparison engine is `--engine tile-frontier`.

## Incremental contact turning (2026-09-07)

Enabled by default in `contact-types`. `search/contact_turns.py` adds necessary
signed-turn equations at each partial node: total prototype turn is 2*pi and
the two CCW views of each completed contact have opposite interior turns.
Endpoint turns are excluded from a contact equation. Marked corners obey the
existing junction angle constraints. Crucially, each open interval carries an
**unrestricted** integrated turn, including future unmarked corners: it is not
assumed straight or smooth. No disk radius or convexity is imposed. Both direct
and reflected charts obey the same physical CCW cancellation.

This propagates a necessary consequence of interface matching, not the entire
word problem or its derived cuts. All negative decisions use the exact affine
oracle; an unknown numerical outcome cannot close a branch.

In the earlier `tetrad-contact-v3` comparison, the
short benchmark compared contact search with and without this propagation,
under identical explicit one-second word-case guards. In the 30-second trial,
four subtrees were cut, including one at 9 assigned incidences out of 15 (before
all tiles were placed); propagation cost about 0.28 seconds. Neither variant
produced a profile. This establishes early selectivity at low cost, not a total
speedup factor or a successful tetrad solution.

## Validation and short comparison

### Partial word propagation deliverable (2026-09-07)

Enabled by default in `contact-types`. At partial nodes, completed interfaces
provide equations between arbitrary nonempty factors and marked corner turns.
The propagator cancels matching ends, identifies equal-length factors with their
orientation, and splits the longer factor when the current affine constraints
**force** a strict length comparison. New split points are not assumed smooth.
The induced signed corner equalities are checked immediately against junction
angle constraints. Contradictions prune the current subtree, not just leaves.

Length comparisons use equality reduction or exact infeasibility of the negated
comparison, never a chosen numerical witness. Ambiguous comparisons and atomic
self-involutions remain for the original leaf solver. Optional propagation has
small per-node work bounds (8 comparison queries, 96 normalization steps, 2048
expanded tokens); reaching them does **not** reject the branch. The dashboard
reports rejections, refinements, corner relations, residual/limited states and
propagation time. Original equations still reach the existing formal kernel.

In a 30-second-per-variant diagnostic with identical one-second word-case
guards, propagation rejected 59 subtrees, including 6 at 9 of 15 assigned
incidences. It consumed about 5.6 seconds and emitted 2 formal profiles, versus
0 without propagation. These are geometry-ready profiles, **not verified
geometric solutions**, and this is not an end-to-end speedup factor. A separate
repeat saved the profiles for inspection.

Next deliverables, rather than claiming the redesign finished:

1. Done: shared metric variables, junction/turn checks, forced partial word
   correspondences and immediate angular contradictions.
2. Partial: persistent derived-cut snapshots and ambiguous refinement decisions
   inside local word lookahead, plus retained metric sectors through direct
   insertions and terminal profiles (see below). Still pending: a shared derived
   word DAG across direct-incidence insertions and reuse of terminal word work.
3. Later: canonical augmentation/duplicate reduction and conflict reuse.
4. Separate extension: imposed symmetry and graph construction within DFS.

`tests/test_word_propagation.py` exercises both involutions, signed corner
transport, forced splits, nonempty cancellation, unresolved cases and bounds.

### Three-case Levi lookahead (2026-09-08)

When partial word propagation encounters an undecided factor-length comparison,
the search now tests equality, shorter and longer cases. Each feasible child
resumes an immutable snapshot of residual equations, substitutions, derived
factors and point relations; siblings cannot mutate one another. Forced
consequences and junction angles are propagated again under that child's affine
constraints. If all three cases are contradictory, the direct-incidence node
is rejected before its descendants are generated.

This is **existential lookahead**, not yet a wholesale replacement of the main
DFS: the first open case keeps the unrestricted parent. Its constraints are NOT
silently committed and NOT lost at the adapter. The unchanged terminal kernel
still searches the original equations, including all other sectors. Therefore
this step neither duplicates a terminal arrangement per Levi sector nor excludes
solutions in unexplored sectors. Derived snapshots are retained between local
Levi decisions, but rebuilt when the direct marked-point partition changes.

Lookahead is opt-in: `--contact-word-refinement-depth 2` enables two ambiguous
decisions (`contact_word_refinement_depth` in evaluator configuration, default
zero disables lookahead). This is a bound on optional
anticipation, **not a bound on the main tree**: unproved cases, normalization
limits and depth limits always keep the branch. Progress reports expose decisions,
cases tested, all-case closures, affine rejections and deferred lookaheads.

Compare this change alone, keeping deterministic word propagation enabled in
both variants:

```powershell
py.exe scripts\benchmark_contact_search.py --seconds 30 `
  --comparison refinement --output output\contact-levi-refinement-benchmark.json
```

The next architectural step remains coupling retained word sectors with future
direct insertions and terminal solving. The current adapter cannot carry those
additional strict inequalities; this deliverable deliberately avoids pretending
otherwise.

Measured 30-second comparison: both variants emitted two profiles. Lookahead
tested 298 local cases and closed 13 local word nodes; total word propagation
time increased from 3.75 to 8.73 seconds. Direct search visited 209 versus 191
nodes, over different pruned trees. This does not demonstrate acceleration and
is why lookahead is not enabled by default. The 13 closures are local word-tree
nodes, not necessarily 13 distinct direct-incidence subtrees.

### Retained metric sectors (next deliverable, 2026-09-08)

The above adapter limitation is now addressed by opt-in `--contact-word-sectors`.
Instead of existential lookahead, each feasible equality/shorter/longer case
becomes a real DFS child. Its affine constraints survive future chart and direct
incidence decisions. Residual word snapshots resume between sector decisions;
on a changed direct partition they are rebuilt under the retained metric rows.
`--contact-word-refinement-depth 2` in this mode limits the number of retained
sector decisions per root-to-leaf path, not the size or duration of the main
tree. Beyond that depth the residual system is left to the existing kernel;
no undecided case is removed.

At a complete contact arrangement, `PlacementAdapter.project_sector` translates
interface lengths and tile offsets into prototype interval-length rows. Search
normalizes the prototype perimeter to one; its affine constant therefore becomes
the sum of prototype gaps, NOT the constant one in disk-circumference units.
Both orientations are supported, and equalities may hold modulo the existing
contact-length equations rather than as identical coefficient vectors.

`Placement.length_sector` carries these homogeneous rational rows. Terminal
decoration substitutes the resolved words and adds equalities directly; strict
rows become positive slack variables. Those variables participate in exact
length and joint-angle feasibility. Their positive expressions are serialized
with the formal profile, loaded by geometry, included in optimization residuals,
and checked before a geometric result is accepted. Existing numerical geometry
tolerances still apply. Profile deduplication includes sector rows: distinct
metric domains cannot silently erase one another.

This is not yet a sector-aware word-equation solver: algebraic word families may
still be recomputed across sectors; metric specialization subsequently respects
the chosen sector. In a 30-second comparison the retained-sector variant tested
89 sector cases, emitted zero profiles versus two without sectors, and had no
reported build error. Total word propagation took 4.57 versus 3.42 seconds.
This is a structural deliverable, not evidence of improved end-to-end speed.
It remains opt-in. The next useful optimization is avoiding repeated terminal
word solving across metric sectors and transporting more word structure itself.

### Completed word-language reuse (2026-09-11)

The retained-sector path now reuses fully resolved algebraic word languages
within one runner. The key contains the complete compiled case, solver limits
and family expansion policy; sector length rows deliberately do not enter it.
Each sector still runs its own specialization, decoration and geometry checks.
Only `exact_supported` and `exact_unsat` results without any resource cutoff or
unsupported component are stored, and only after full iterator consumption.
Interrupted or partial results are recalculated, never frozen as exhaustion.

The cache keeps no solver/residual graph, no profiles and no disk files. It is
bounded to 32 entries and 50,000 structural weight units (expression nodes plus
trace character/validation counts, not a byte guarantee). Oversized languages
are streamed normally without being retained. Eviction changes performance only.
`word_cache_hits`, `word_cache_misses`, `word_cache_stored` and
`word_cache_not_stored` are reported; replay does not recount residual graph
nodes or edges as new work. A dashboard card and console counter show hits.

No new launch flag is needed: the existing `--contact-word-sectors` command
activates reuse. This is intentionally limited to completed languages; sharing
unfinished residual graphs is not part of this stabilization step.

`tests/test_length_sectors.py` checks exact homogeneous projection including
reflections, equality and strict specialization, rejection after terminal
identification, sector-sensitive IDs, preserved DFS constraints, profile JSON
roundtrip and geometric sector validation.

```powershell
py.exe scripts\benchmark_contact_search.py --seconds 30 `
  --comparison sectors --output output\contact-sector-benchmark.json
```

`tests/test_contact_search.py` compares all outputs for a two-triangle patch with
the legacy enumeration followed by exact length/angle checks, including
reflections, coincident corners and the formal adapter's constraint rows. It also
checks strict inequalities, interrupted search and a positive formal-profile
control through the existing kernel.

```powershell
py.exe scripts\benchmark_contact_search.py --seconds 30
```

This separate diagnostic now compares the contact engine with and without word
propagation, with an explicit one-second word-case guard and a 30-second budget
per variant. It writes `output/contact-v2-benchmark.json` and sibling profile
JSONL files. `--variant before` or `--variant after` runs just one variant.
Different engines traverse different prefixes, so their leaf rates are not a
speedup measurement. Inspect early rejection depth, late length rejections,
word/decorating outcomes and time spent in affine checks.

Historical snapshot on 2026-09-06, before the above propagation work,
30 seconds per engine (one-second word-case guard):

| Measure | Legacy tile frontier | Contact V2 |
| --- | ---: | ---: |
| Complete arrangements passed to kernel | 319 | 42 |
| Late positive-length rejections | 261 | 0 |
| Word cases attempted | 58 | 42 |
| Word families produced | 340 | 565 |
| Formal profiles emitted | 0 | 0 |

V2 spent about 1.08 seconds in its affine checks and rejected 140 candidate
decisions there. The remainder is predominantly downstream work; these counts
do not demonstrate an end-to-end speedup. In particular, a word family is not a
geometric solution: the observed families were rejected during decoration.
This is the reason not to label the first metric layer as the completed redesign.
