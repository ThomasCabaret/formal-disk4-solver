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

Its supervised target is the stable 26-component vector exposed by
`formal_disk4.pipeline.filter_report.LEARNING_FILTER_IDS`. Each component is a
conditional pass rate among descendants that actually reached and decided the
corresponding filter. Deferred, inapplicable, unvisited, and implementation
error outcomes are not mislabeled as failures.

The uniform mappings selected from the same proposal pool are retained as a
control population. This makes learned enrichment distinguishable from an
easier generation or a change in the graph distribution.

The weak-order level also keeps uniform control rollouts. Every decision stores
its state, chosen action, pool size, selection probability, entropy, and the
terminal 26-filter target. Training/validation is split by complete graph, so
validation tests transfer rather than memorization of another branch of the
same graph. The deterministic GUI/CLI search passes no policy and retains its
exhaustive DFS.

When the legal weak-order action set is larger than the configured pool, the
pool is sampled uniformly without replacement. No full-mask or singleton shape
is inserted obligatorily; consequently every legal action has equal admission
probability in the control policy and nonzero probability under the learned
epsilon mixture.

## Run

From PowerShell in the project root:

```powershell
$env:PYTHONPATH="$PWD\src"
py.exe -m formal_disk4.graph_lab --config config\graph_lab\up-to-13.json --restart --generations 1000 --batch-size 8
```

The new configuration and checkpoint schema are incompatible with the former
graph-only run, so the first run must use `--restart`. Later runs omit it and
resume from `state.json`.

## Live mapping dashboard

```powershell
$env:PYTHONPATH="$PWD\src"
py.exe -m formal_disk4.graph_lab.dashboard --input output\graph_lab\up-to-13\mapping_training_metrics.jsonl
```

Use `training_metrics.jsonl` instead to inspect the coarser graph ranker.

To inspect the learned weak-order policy itself:

```powershell
$env:PYTHONPATH="$PWD\src"
py.exe -m formal_disk4.graph_lab.dashboard --input output\graph_lab\up-to-13\weak_order_training_metrics.jsonl
```

Important durable outputs are:

- `mapping_observations.jsonl`: every fixed mapping, target vector, counters,
  selection metadata, and rollout count;
- `mapping_training_metrics.jsonl`: per-filter learned-versus-uniform rates and
  validation metrics;
- `mapping_model.pt`: resumable mapping model and optimizer state;
- `deep_mapping_candidates.jsonl`: mappings that reached the word-level gates;
- `weak_order_rollouts.jsonl`: one complete stochastic trajectory with all
  state/action decisions and its terminal filter vector;
- `weak_order_training_metrics.jsonl`: per-filter learned-versus-uniform
  rollout rates and graph-held-out validation metrics;
- `weak_order_model.pt`: resumable state/action ranker and optimizer;
- `deep_weak_order_candidates.jsonl`: complete trajectories that reached the
  configured deep-filter threshold;
- `geometry_candidates.jsonl`: every emitted formal profile, ready for the
  separate geometry solver.

All files live under the ignored `output/` tree and remain subject to the
configured 8 GiB aggregate training-output limit.
