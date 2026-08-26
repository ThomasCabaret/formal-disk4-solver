# Graph Lab learning pipeline

> Experimental subsystem. The maintained Graph Lab defaults to the structural
> prior and does not instantiate or train these models. Select this subsystem
> explicitly with `--policy learned`; it changes traversal order, never formal
> acceptance.

The Graph Lab now has four learned selection levels:

1. A shared graph GNN ranks complete dual-graph candidates.
2. For each selected graph, the Lab samples a cheap pool of complete contour
   mappings (one orientation and cyclic phase per tile). A second shared GNN,
   conditioned on both the graph and the mapping, ranks that pool.
3. Each selected mapping is held fixed while several weak-order rollouts choose
   one legal next block at a time. A third graph-and-mapping-conditioned ranker
   scores the legal state/action pairs, then a temperature/epsilon policy draws
   one branch.
4. For every completed word case, the exact solver's finite families and their
   configured specializations form one decision pool. A fourth ranker orders
   all `(family, specialization)` pairs together, so the search can reach a
   profile-valid family before spending its bounded rollout on invalid sibling
   families. The production filters and exact word solver remain unchanged.

Graph visits are not deduplicated globally. Seeing a graph once only evaluates
a small stochastic sample of its mappings and weak orders, so later visits are
allowed and provide new descendant rollouts. Deduplication is limited to one
proposal pool, and the diversity archive keeps at most the best visit for a
given graph in each cell.

The unlearned graph prior has no catalog input and no known-solution injection.
Its general branch constructs arbitrary polyhedral graphs. Its symmetric branch
first chooses an abstract cyclic action on the requested number of tiles, with
strictly positive probability for every feasible order and increasing weight
for larger orders. Since the outside vertex is fixed, an orientation-preserving
finite rotation permits full tile orbits and at most one additional fixed tile.

For the full-support part of that branch, all possible edges are partitioned
into orbits under the chosen permutation and each complete edge orbit is sampled
with probability strictly between zero and one. Every invariant labelled graph
is such a union, so no symmetric topology is excluded by the generator. Invalid,
non-planar, non-3-connected, or orientation-reversing results are rejected only
after sampling. A faster constructive part builds generic cyclic shells solely
from the orbit decomposition, then adds or deletes complete edge orbits. It is
an efficiency bias, not the support guarantee. Known catalog solutions are used
only after sampling by the optional coverage benchmark, where they act as
oracles measuring genuine rediscovery.

Tile-count sampling uses a tempered combinatorial-growth prior rather than a
uniform-size prior. With `size_growth_factor = 1.4`, every additional tile
multiplies the proposal weight by 1.4. This compensates partially for the rapid
growth in the number of graph classes: even uniform sampling by tile count
would strongly over-sample each small topology. The same weight is used when
choosing mutation parents, so the mutation branch cannot silently restore the
old small-graph bias. Every allowed tile count retains strictly positive
probability; the factor is deliberately much milder than the true combinatorial
growth and therefore does not collapse the search onto the maximum size.

The mapping GNN uses shared node/message weights, periodic phase features, and
directed edge-port attributes. Each interface message therefore knows the
cyclic position and direction of the port on both adjacent tiles; the network
does not lose the planar embedding by seeing only an unlabelled adjacency
matrix. It has no graph-specific embedding table, so examples from one graph
can train the ranking policy used on another graph or another tile count.

The mapping and weak-order rankers retain two stable 26-component vectors
indexed by
`formal_disk4.pipeline.filter_report.LEARNING_FILTER_IDS`. Each component is a
conditional pass rate among descendants that actually reached and decided the
corresponding filter. Deferred, inapplicable, unvisited, and implementation
error outcomes are not mislabeled as failures. These heads are auxiliary: the
second vector directly supervises the probability that a rollout invokes that
filter at all. The policy never multiplies different micro-filter probabilities
as though they formed one independent linear chain.

Policy ordering follows a curriculum. It first emphasises the earliest
well-supported reach head whose empirical rate is below the configured mastery
threshold, keeps small additive signals for shallower/deeper heads, and retains
small terminal bonuses. Probability of emitting a formal profile, probability
that the asynchronous geometry worker finds a solution, and probability that
it finds a solution on a non-ring graph remain direct value heads. The last two
labels are joined by exact formal-profile identifier. A graph's solution is
never copied onto every mapping or weak-order rollout of that graph, and unknown
geometry outcomes stay unlabeled rather than becoming failures.

Sparse direct and micro-filter labels use bounded class balancing. A pairwise
loss additionally compares candidates in the same decision domain: equal tile
count for graph proposals, the same graph for mappings, and the exact same
mapping plus partial state for weak-order actions. Thus the model learns the
ordering needed by the policy as well as calibrated absolute targets. Mapping
and weak-order rankers also receive a pairwise loss on the current reach
frontier.

The specialization ranker has two explicit heads. Its primary target is
`specialization.profile_valid`: decoration and the final formal-profile filters
accepted the specialization. Exact duplicates remain positive for this target,
because mathematical validity must not depend on what a previous rollout wrote
to disk. `specialization.profile_emitted` is a secondary operational target.
The training loss also compares positive and negative siblings inside the same
word-case pool, which directly optimizes the required ordering rather than only
calibrating a global rare-event probability.

Its input is conditioned on the same graph and complete mapping as the earlier
rankers, the actual weak-order placement blocks, and the full canonical symbolic
shape of every specialized word environment. Shared graph-message weights and
canonical occurrence/literal integers permit transfer between graph sizes;
there is no table keyed by a catalog map, graph id, family id, or solution.
Numeric family complexity summaries alone would make distinct word families
indistinguishable, so they are only auxiliary features.

The Lab policy visits a bounded, unique subset of the legal specialization pool
(`visits_per_pool`, four in the standard experiment). This is a local rollout
budget, not a mathematical pruning result: uniform controls and epsilon give
every sibling strictly positive probability on later revisits, and no persistent
closed set is stored. The budget is what converts the learned ordering into a
real reduction of specialization work on negative rollouts. The deterministic
GUI/CLI path passes no specialization policy and retains the exhaustive
historical streaming family order.

The uniform mappings selected from the same proposal pool are retained as a
control population. This makes learned enrichment distinguishable from an
easier generation or a change in the graph distribution.

The weak-order level also keeps uniform control rollouts. Every decision stores
its state, chosen action, pool size, selection probability, entropy, and the
terminal 27-filter target. Its state encoder includes the ordered coincidence
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

The default tile-count domain is 3 through 13. Use `--tile-counts` with a
comma-separated union of integers and inclusive ranges to explore a
discontinuous domain. For example, this keeps the usual domain and adds only
18 and 19 tiles:

```powershell
py.exe -m formal_disk4.graph_lab.app --config config\graph_lab\up-to-13.json --geometry-config config\graph_lab\geometry.json --tile-counts "3-13,18-19" --generations 10000 --batch-size 8
```

Sizes 14 through 17 are then absent from both direct prior proposals and
mutations. The size prior uses the actual numerical gap, so its configured
growth factor still gives larger requested sizes the extra sampling mass they
need. The option is checkpoint-compatible: stopping an existing 3--13 run and
resuming it with this option retains all model checkpoints and replay examples.
The shared variable-size encoders do not acquire a new tensor shape; existing
3--13 knowledge therefore transfers to the newly admitted sizes. Use
`--restart` only when a deliberately independent training experiment is
wanted.

Resume reads JSONL journals as streams and retains only the replay windows the
large descendant models actually train on (50,000 mapping and weak-order
examples by default and 20,000 specialization pools). Cumulative checkpoint
counters and historical coverage identifiers still include the complete
journals. At the weak-order
policy level, a large legal subset domain remains implicit: the policy samples
its uniform pool of 64 actions by indexed access instead of first allocating
all `2^n` masks. This optimization is confined to bounded Lab policies; the
production solver with no policy keeps its exhaustive deterministic ordering.

Add `--exclude-rings` to remove every outside-star plus simple tile-cycle
structure before graph ranking. The filter applies equally to random priors,
symmetry-preserving mutations, ordinary mutations, and learned selections. The option is
written into the effective configuration and current state, but is deliberately
excluded from checkpoint compatibility. A run can therefore learn first from
rings, resume with `--exclude-rings` to transfer that knowledge to the non-ring
domain, and later resume without the option. Historical replay and model weights
are retained; only future graph proposals change.

The background geometry configuration is intentionally more generous than a
quick interactive check: 128 closure starts, 1,500 evaluations per start, 320
clearance-refinement evaluations, 80 samples per arc, and a 45-second hard
candidate timeout. Most positive contours still finish in a fraction of a
second; the extra budget is spent only on difficult or negative candidates.

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
graph, mapping, weak-order, and family-specialization levels. Mapping statistics compare learned and
uniform choices only inside the same graph and generation; weak-order
statistics use the same mapping and generation. Historical rows written before
these matched cohorts were introduced are deliberately not presented as a
policy-versus-random comparison. The learned policy itself is not modified by
this reporting rule: only the random control rows outside its action domain are
excluded from the comparison.

The fourth panel compares randomly assigned control candidates and learned
candidates from the exact same word-case pools. It reports support, held-out
AUC, Brier calibration, and within-pool pairwise accuracy for profile validity,
plus the secondary actual-emission rate. Until both positive and negative
support exist, all candidates are deliberately treated as exploration.

Each level also displays the three direct policy objectives, including observed
rate, mean prediction, held-out AUC, and pairwise ranking accuracy. The
27-filter table remains available as the fine-grained diagnostic signal. It
includes `assignment.cyclic_shift_compatible`, so an imposed rotation that
cannot act on a contour mapping is visible as its own gate rather than as an
unexplained gap before the first weak-order filter.

At graph level the nested-area funnel is a true product of sequential
conditional transitions. At mapping and weak-order levels, each rectangle uses
the directly observed fraction of rollouts that reached that micro-filter;
unrelated filters are never multiplied. The model report includes AUC, Brier
score, pairwise accuracy at the current frontier, the active frontier name, and
an alert when validation AUC drops by more than 0.05 below its historical best.

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
The specialization panel reports its analogous `legal_candidates`,
`visited_candidates`, `locally_not_selected`, and `permanently_closed` counts;
the last value is likewise always zero by construction.

Important durable outputs are:

- `mapping_observations.jsonl`: every fixed mapping, conditional target vector,
  direct reach vector, counters, selection metadata, and rollout count;
- `mapping_training_metrics.jsonl`: per-filter learned-versus-uniform rates and
  validation metrics;
- `mapping_model.pt`: resumable mapping model and optimizer state;
- `deep_mapping_candidates.jsonl`: compact identifiers of mappings that
  reached the word-level gates; full records stay in `mapping_observations.jsonl`;
- `weak_order_rollouts.jsonl`: one complete stochastic trajectory with all
  state/action decisions, its conditional filter vector, and direct reach
  vector;
- `weak_order_training_metrics.jsonl`: per-filter learned-versus-uniform
  rollout rates and graph-held-out validation metrics;
- `rollout_coverage_metrics.jsonl`: compact historical/recent coverage,
  concentration, revisit, and local-nonselection telemetry for all three
  pre-word policy levels; specialization coverage is stored beside its own
  generation metrics;
- `weak_order_model.pt`: resumable state/action ranker and optimizer;
- `deep_weak_order_candidates.jsonl`: compact identifiers of trajectories that
  reached the configured deep-filter threshold; full records stay in
  `weak_order_rollouts.jsonl`;
- `specialization_pools.jsonl`: each exact word-case pool, its complete mapping,
  weak placement, symbolic family actions, stochastic policy metadata, and
  observed decoration/profile-filter outcome;
- `specialization_training_metrics.jsonl`: learned-versus-control rates and
  validation/ranking diagnostics for profile-valid family selection;
- `specialization_model.pt`: resumable graph/mapping/placement/family ranker and
  optimizer state;
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

## Rotational Stein subdomain

`--stein-symmetric` restricts the structural proposal distribution to the
audited consequences of
`docs/rotational_stein_structural_note.tex`.  A candidate has one distinguished
central tile fixed by a rotation of order `m >= 2`; every other tile belongs to
a full `m`-orbit, at least two such orbits exist and at least two distinct
orbits meet the outer boundary.  Consequently only sizes `n = 1 + k*m` with
`k >= 2` remain in the effective tile-count domain.  The unproved stronger
claim `k >= 3` is not used.

For the proved boundary case `k = 2`, the generator also enforces the graph
content of Theorem 4: every non-central tile is outer and the contact graph
admits an orientation-reversing involution that exchanges the two moving
orbits and conjugates the imposed rotation to its inverse.  Sector confinement
and the centered geometric reflection are not guessed from the graph; the
mapping/geometry layers retain responsibility for those data.

The sampler chooses a requested admissible tile count and then a compatible
rotation order.  Its default order mass decreases with `m`, while every
compatible configured order retains positive probability.  It samples and
mutates complete edge orbits, so the prior contains no catalog graph or known
solution.  The graph-only domain cannot encode the theorem's centered matching
between two outer tile orbits; that necessary condition is enforced later by
the outer-arc mapping/weak-order filter.  During cyclic weak-order sampling the
filter is applied incrementally to every proposed prefix, before policy
ranking.  This is the same exact necessary condition used at a completed leaf:
it prevents a bounded rollout from having to guess the required endpoint
coincidences blindly, without excluding any leaf that the complete test would
accept.  The exact radius-arc topology test is likewise evaluated on cyclic
prefixes.  An incomplete fundamental domain has one open insertion frontier
per rotated copy; only propagated paths avoiding every frontier are used.
Consequently hard-endpoint and opposite-sign contradictions are removed before
policy ranking while every potentially repairable path remains deferred.

The cyclic subgroup, rather than an arbitrary named generator, is the imposed
structure.  Before mapping sampling, the dynamic map therefore normalizes among
the equivalent generators and selects the one that advances the central contour
by one positive fundamental domain.  In particular, choosing `R` or `R^-1`
cannot make an otherwise identical mapping domain spuriously empty.

Use a separate output directory so a Stein experiment cannot mix with a
general Graph Lab checkpoint:

```powershell
$env:PYTHONPATH="$PWD\src"
py.exe -m formal_disk4.graph_lab.app `
  --config config\graph_lab\up-to-13.json `
  --geometry-config config\graph_lab\geometry.json `
  --output-directory output\graph_lab\stein-symmetric `
  --stein-symmetric `
  --tile-counts "3-19" `
  --symmetry-orders "2-8" `
  --restart `
  --generations 10000 `
  --batch-size 8
```

For this example the effective sizes are reported at startup; incompatible
requested sizes are absent rather than sampled and rejected downstream.  Omit
`--symmetry-orders` to retain every order compatible with the tile-count
domain.  Resume by running the same command without `--restart`.
