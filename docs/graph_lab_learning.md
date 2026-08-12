# Graph Lab learning pipeline

The Graph Lab now has three learned selection levels:

1. A shared graph GNN ranks complete dual-graph candidates.
2. For each selected graph, the Lab samples a cheap pool of complete contour
   mappings (one orientation and cyclic phase per tile). A second shared GNN,
   conditioned on both the graph and the mapping, ranks that pool.
3. Each selected mapping is held fixed while several weak-order rollouts choose
   one legal next block at a time. A third graph-and-mapping-conditioned ranker
   scores the legal state/action pairs, then a temperature/epsilon policy draws
   one branch. The production filters and exact word solver remain unchanged.

Graph visits are not deduplicated globally. Seeing a graph once only evaluates
a small stochastic sample of its mappings and weak orders, so later visits are
allowed and provide new descendant rollouts. Deduplication is limited to one
proposal pool, and the diversity archive keeps at most the best visit for a
given graph in each cell.

The unlearned graph prior is a mixture of rings, general polyhedral graphs, and
stochastic draws in the neighbourhood of configured catalog templates. A
template draw carries no positive label and injects no mapping or placement:
all downstream decisions and the success signal still have to be rediscovered.

The mapping GNN uses shared node/message weights, periodic phase features, and
directed edge-port attributes. Each interface message therefore knows the
cyclic position and direction of the port on both adjacent tiles; the network
does not lose the planar embedding by seeing only an unlabelled adjacency
matrix. It has no graph-specific embedding table, so examples from one graph
can train the ranking policy used on another graph or another tile count.

Every ranker retains the stable 26-component vector exposed by
`formal_disk4.pipeline.filter_report.LEARNING_FILTER_IDS`. Each component is a
conditional pass rate among descendants that actually reached and decided the
corresponding filter. Deferred, inapplicable, unvisited, and implementation
error outcomes are not mislabeled as failures. These heads are auxiliary: the
policy no longer multiplies them as though they were one independent linear
chain.

Policy ordering instead uses three direct value heads: probability of emitting
a formal profile, probability that the asynchronous geometry worker finds a
solution, and probability that it finds a solution on a non-ring graph. The
last two labels are joined by exact formal-profile identifier. Old graph-level
records may use the persistent graph/profile catalog, but a graph's solution is
never copied onto every mapping or weak-order rollout of that graph. Unknown
geometry outcomes stay unlabeled rather than becoming failures.

Sparse direct and micro-filter labels use bounded class balancing. A pairwise
loss additionally compares candidates in the same decision domain: equal tile
count for graph proposals, the same graph for mappings, and the exact same
mapping plus partial state for weak-order actions. Thus the model learns the
ordering needed by the policy as well as calibrated absolute targets.

The uniform mappings selected from the same proposal pool are retained as a
control population. This makes learned enrichment distinguishable from an
easier generation or a change in the graph distribution.

The weak-order level also keeps uniform control rollouts. Every decision stores
its state, chosen action, pool size, selection probability, entropy, and the
terminal 26-filter target. Its state encoder includes the ordered coincidence
blocks already fixed by the prefix. This is not provenance: those blocks are
part of the current mathematical state and are not recoverable from aggregate
counters alone. They are omitted from each repeated on-disk state to avoid
quadratic output, then reconstructed from the preceding decisions on resume.
Training/validation is split by complete graph, so validation tests transfer
rather than memorization of another branch of the same graph. The deterministic
GUI/CLI search passes no policy and retains its exhaustive DFS.

When the legal weak-order action set is larger than the configured pool, the
pool is sampled uniformly without replacement. No full-mask or singleton shape
is inserted obligatorily; consequently every legal action has equal admission
probability in the control policy and nonzero probability under the learned
epsilon mixture.

## Run

The normal entry point starts the learned search in the current console, opens
the unified dashboard in the browser, and consumes geometry-ready profiles with
the numerical geometry solver in a background queue:

```powershell
$env:PYTHONPATH="$PWD\src"
py.exe -m formal_disk4.graph_lab.app --config config\graph_lab\up-to-13.json --geometry-config config\graph_lab\geometry.json --generations 1000 --batch-size 8
```

`--generations` is the total target generation, not an additional count. A run
whose `state.json` contains `next_generation: 1000` therefore continues with
`--generations 2000`. Use `--restart` only for an intentionally fresh
experiment: it clears both the learned-search output and its geometry queue.
Model checkpoints are architecture-exact: after changing a ranker architecture,
start a fresh experiment instead of partially loading coincidentally compatible
tensors from an older model.
After the requested generation target is reached, the console keeps the web
dashboard and geometry queue alive until Ctrl+C. Add `--exit-when-complete` for
a non-interactive run.

## Unified live dashboard

The single page compares recent uniform controls with learned rollouts at the
graph, mapping, and weak-order levels. Mapping statistics compare learned and
uniform choices only inside the same graph and generation; weak-order
statistics use the same mapping and generation. Historical rows written before
these matched cohorts were introduced are deliberately not presented as a
policy-versus-random comparison. The learned policy itself is not modified by
this reporting rule: only the random control rows outside its action domain are
excluded from the comparison.

Each level also displays the three direct policy objectives, including observed
rate, mean prediction, held-out AUC, and pairwise ranking accuracy. The
26-filter table remains available as the fine-grained diagnostic signal.

Each level includes a nested-area filter funnel: the area of every inner
rectangle is the product of its displayed conditional passage rates. The line
below it separately reports the actual fraction that reached the level's final
outcome, so the visual index is not confused with an observed end-to-end rate.

The geometry tab indexes exact formal profiles, shows both their distinct count
and the total number of emissions, and embeds an SVG assembly for each solved
profile. Repeated emissions update the profile's last source line and move its
card to the top without discarding its occurrence count. Structure and solver
status checkboxes filter the gallery without changing the catalog.

The structures tab shows the 50 or 100 most recent graph rollouts, newest
first. Unlike the geometry catalog, it deliberately keeps repeated visits: it
is a view of the search trajectory rather than a deduplicated result set. Each
card uses the catalog browser's schematic contact renderer and states the exact
imposed permutation, its order, the selection mode, and the deepest reached
stage. The dashboard tails `observations.jsonl` incrementally, so refreshing
this view does not rebuild all historical schematics.

Pizza classification is intentionally conservative. A profile is a ring only
when its graph is exactly an outside star plus one connected, simple cycle over
all tiles (exactly `2n` edges in total). Ring cards then distinguish uniform and
mixed copy orientations when assignment data is available. The imposed
symmetry order is never used as evidence that a profile is a pizza; uncertain
cases stay in the non-ring category.

The dashboard may also be opened on an existing output directory without
starting a search or a geometry worker:

```powershell
$env:PYTHONPATH="$PWD\src"
py.exe -m formal_disk4.graph_lab.dashboard --output output\graph_lab\up-to-13
```

The first opening of a large historical run incrementally builds a persistent
SQLite index for `geometry_candidates.jsonl`; subsequent openings resume from
its byte offset instead of rescanning the file.

## Rollout coverage audit

The compact coverage journal distinguishes the proposal pool from the selected
rollouts at the graph and mapping levels. For weak orders it records the funnel
from enumerated masks, through the bounded uniform pool and prefix filters, to
the single policy choice. It retains selected identifiers only, which is enough
to compare historical and recent concentration without duplicating the large
observation files.

```powershell
$env:PYTHONPATH="$PWD\src"
py.exe -m formal_disk4.graph_lab.rollout_audit --input output\graph_lab\up-to-13\rollout_coverage_metrics.jsonl --window-generations 50
```

The report prints unique trajectories, historical revisits, top-choice share,
effective number of visited identifiers, proposal/rollout structure bins and
the weak-order decision funnel. `locally-not-selected` always means eligible to
be sampled again. Graphs, mappings, and weak-order trajectories have no global
closed set; `permanently-closed` must remain zero at all three levels.

Important durable outputs are:

- `mapping_observations.jsonl`: every fixed mapping, target vector, counters,
  selection metadata, and rollout count;
- `mapping_training_metrics.jsonl`: per-filter learned-versus-uniform rates and
  validation metrics;
- `mapping_model.pt`: resumable mapping model and optimizer state;
- `deep_mapping_candidates.jsonl`: compact identifiers of mappings that
  reached the word-level gates; full records stay in `mapping_observations.jsonl`;
- `weak_order_rollouts.jsonl`: one complete stochastic trajectory with all
  state/action decisions and its terminal filter vector;
- `weak_order_training_metrics.jsonl`: per-filter learned-versus-uniform
  rollout rates and graph-held-out validation metrics;
- `rollout_coverage_metrics.jsonl`: compact historical/recent coverage,
  concentration, revisit, and local-nonselection telemetry for all three
  policy levels;
- `weak_order_model.pt`: resumable state/action ranker and optimizer;
- `deep_weak_order_candidates.jsonl`: compact identifiers of trajectories that
  reached the configured deep-filter threshold; full records stay in
  `weak_order_rollouts.jsonl`;
- `geometry_candidates.jsonl`: every emitted formal profile, ready for the
  background geometry queue;
- `geometry/geometry_candidate_catalog.sqlite3`: resumable occurrence and
  pagination index, deduplicated by exact formal-profile identifier;
- `geometry/geometry_worker_state.json`: current background worker phase and
  profile;
- `geometry/geometric_solutions.jsonl`: solved contours used by the dashboard's
  SVG previews.

All files live under the ignored `output/` tree and remain subject to the
configured 8 GiB recursive output limit. Metrics evaluate a bounded recent
sample instead of re-running neural inference over the complete history after
every generation; the full durable examples remain available for replay.
