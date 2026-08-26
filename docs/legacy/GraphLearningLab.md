# Variable-graph learning lab (legacy experiment)

> Historical design note. Learning is no longer the stable default Graph Lab
> policy; use `--policy learned` only for explicit experiments.

This lab explores the structure itself instead of training one model per catalog
map. It is isolated from the production acceptance rules: generated structures
are proposed and ranked by learning, but every recorded stage and every formal
candidate comes from the unchanged production solver.

## Structural representation

A candidate is a simple three-connected planar dual graph. Tile vertices are
joined when the corresponding tiles share a nonzero interface. A distinguished
`outside` vertex represents the complement of the disk; its incident edges are
outer boundary arcs. Faces of the embedded dual graph reconstruct the map
vertices and the cyclic contour of every tile.

Three-connectivity is intentional in this first implementation. It guarantees
at least three contour vertices per tile and a unique cellular embedding up to
reflection. It covers the known ring, double-ring, offset double-ring, and
inner-boundary-point controls through thirteen tiles. Multigraphs and degenerate
two-connected cell complexes are not yet in the generated domain.

The constructive prior starts from `K4`, inserts tile vertices into faces,
performs planar diagonal flips, and deletes admissible edges. Local mutations
add/delete contacts, flip diagonals, and add/delete tiles. All mutations are
validated for simplicity, planarity, and three-connectivity before evaluation.

Nontrivial orientation-preserving automorphisms are detected exactly. The
initial distribution favors imposing one of them, but both the prior and local
mutations retain nonzero probability for asymmetric graphs and symmetry
breaking. Tile counts 3 through 13 all retain nonzero prior probability, with a
deliberate bias toward smaller structures.

## Learning and exploration

A shared PyTorch message-passing GNN accepts every graph size. Conditional
heads predict whether a bounded production evaluation reaches:

1. a contour assignment;
2. a weak-order placement;
3. the word solver after pre-word pruning;
4. an exact word family;
5. a formal profile ready for geometry.

A sixth head predicts elapsed evaluation cost. The generator uses a sequential
Monte Carlo/evolutionary loop: a pool mixes fresh prior samples and mutations
of diverse archived candidates, the GNN ranks exploitation proposals, and a
fixed fraction is selected uniformly for exploration. This is simpler and more
diagnosable than a first GFlowNet while preserving the important variable-graph
transfer-learning contract.

The diversity archive is stratified by tile count, imposed symmetry, edge
density, and pipeline depth. Exact graph isomorphism, including conjugacy of the
imposed symmetry, prevents a relabelled copy from appearing to be a new family.
A Weisfeiler--Lehman hash is used only as a lookup bucket; it never rejects a
candidate without an exact isomorphism test.

## Known controls

The configuration injects sixteen catalog controls: `c4`, four double cycles,
four offset double cycles, four inner-boundary-point cycles, and the three
simple centered size-six structures containing thirteen tiles. They are still
evaluated by the bounded production pipeline; their labels are not hard-coded.
Two not-yet-seen controls occupy explicit batch slots per generation. Their
observed production-solver result then enters the shared archive and training
set, which biases later mutations and ranking. Thus injection means supervised
initial examples, not merely a vague prior preference, while a control that
fails under the configured budget is not falsely labelled positive. Here a
known solution means a formal profile accepted for geometry, not a completed
numerical geometric realization.

## Running

Install the optional learning dependency if PyTorch is not already available:

```powershell
py.exe -m pip install -e ".[graph-lab]"
```

Start a fresh long run from the project root:

```powershell
$env:PYTHONPATH="$PWD\src"
py.exe -m formal_disk4.graph_lab --config config\graph_lab\up-to-13.json --restart
```

Resume it with the same command without `--restart`. For an initial diagnostic,
override the total generations and batch size:

```powershell
$env:PYTHONPATH="$PWD\src"
py.exe -m formal_disk4.graph_lab --config config\graph_lab\up-to-13.json --restart --generations 20 --batch-size 4
```

Each graph evaluation is limited to 30 seconds, each word case to 2 seconds,
and completed observations are appended immediately. Interrupting the process
therefore loses at most the currently evaluated graph.

To measure the constructive prior alone--with no known-seed injection, learned
ranking, archive mutation, or formal solving--against every representable
catalog graph/symmetry class:

```powershell
$env:PYTHONPATH="$PWD\src"
py.exe -m formal_disk4.graph_lab.coverage `
  --config config\graph_lab\up-to-13.json `
  --samples 1000000 `
  --require-complete
```

The command stops early if every class is found and writes
`output/graph_lab/prior-coverage.json`. Cases outside the current simple,
three-connected, at-most-thirteen-tile domain are reported separately rather than
counted as random misses. This diagnostic is CPU-intensive and should not be
run concurrently with a performance-sensitive learning run.

## Outputs

All generated data is under `output/graph_lab/up-to-13/` and is ignored by Git.
The training-owned files have a hard 8 GiB budget; the run stops cleanly with
`max_training_output_bytes` before they exceed that budget. Numerical
geometry output lives in a subdirectory and is not charged to that training
budget:

- `observations.jsonl`: every evaluated graph, deepest stage, cost, counters,
  model prediction, and lineage;
- `training_metrics.jsonl`: compact per-generation conditional transition
  counts used by the live dashboard;
- `geometry_candidates.jsonl`: every formal profile that reached the geometry
  handoff, with its complete graph and imposed symmetry attached;
- `geometry_graphs.jsonl`: one compact structural record per geometry-ready
  graph;
- `model.pt`: resumable shared GNN;
- `report.md` and `report.json`: stage counts, known-control rediscovery,
  diversity and model metrics.

Double-click `graph-lab-dashboard.bat` while training is running, or run:

```powershell
$env:PYTHONPATH="$PWD\src"
py.exe -m formal_disk4.graph_lab.dashboard --input output\graph_lab\up-to-13\training_metrics.jsonl
```

The dashboard compares the first random-pool control window, the recent random
control window, and recent GNN-ranked candidates for every conditional pipeline
transition. The recent random control is important: it reveals distribution
shift or exhaustion caused by the no-duplicate memory separately from learned
enrichment. It reads only the compact metrics file and does not scan the large
candidate journals.

The dedicated geometry configuration consumes the geometry-ready file directly:

```powershell
py.exe -m formal_disk4 geometry --config config\graph_lab\geometry.json
py.exe -m formal_disk4 visualize --config config\graph_lab\visualizer.json
```

The lab does not claim a geometric solution merely because a formal profile was
emitted. The geometry runner processes the candidates present when it reaches
the end of the file and then exits; rerun it later to include profiles appended
by a still-running Graph Lab search.
