# Mapping learning lab

The Mapping Lab is an experimental campaign runner for one fixed catalog case.
It stays outside the production search pipeline: it generates complete mappings,
asks the production formal filters how far each mapping gets, and uses that
bounded feedback to improve the next proposal pool.

The retained configuration targets `wheel-6-half-turn-fertile-abc`. The normal
catalog remains responsible for the graph, fertile subdomain, half-turn action,
and cyclic split.

## Architecture

The lab is intentionally split into four small layers:

- `core.py` adapts catalog cases, complete mappings, and production filters;
- `sampling.py` generates uniform controls and a bounded proposal pool;
- `backend.py` defines the model-independent learning contract;
- `neural.py` implements the retained neural stage-curriculum backend;
- `runner.py` handles timeouts, persistence, archives, and campaign metrics.

The runner only sends a backend complete-mapping feature vectors and terminal
filter stages. A future model can therefore replace the neural backend without
changing the evaluator or proposal generator. Likewise, a different feature
representation can be introduced at the `MappingSpace.mapping_feature_vector`
boundary.

## Retained learning mode

The current backend is a small fully connected network with two shared ReLU
layers. Its lossless input describes the complete weak order: normalized ranks,
the before/tied/after relation of every occurrence pair, and block count.

The output is a curriculum of conditional binary heads. Head `k` predicts
whether a mapping that reached stage `k-1` will reach stage `k`. Heads activate
only after both positive and negative examples exist. Class-balanced binary
cross entropy protects rare deeper examples.

Training can start with an empty output directory. Every evaluated mapping is
added to a stable 80/20 training/validation split. Storage is bounded and
stratified by terminal stage, so rare deep examples are retained without an
unbounded JSON history dependency.

For each batch, 20 percent of mappings are independent uniform controls. The
remaining slots come from a bounded pool of random mappings plus local or broad
mutations of the deepest saved seeds. The backend ranks this complete pool by
expected filter depth; a small fraction of selected proposals remains random.

Timeouts and evaluator errors are recorded but are not training examples.
Mappings that reach stage 8 or deeper are archived immediately, including their
full masks, blocks, rejection witness, and any word-solver result.

## Run and resume

From the project root:

```powershell
py.exe -m formal_disk4.mapping_lab --config config\mapping_lab\wheel-6.json --restart --generations 10000 --batch-size 64
```

For a quick smoke test:

```powershell
py.exe -m formal_disk4.mapping_lab --config config\mapping_lab\wheel-6.json --restart --generations 2 --batch-size 8
```

Without `--restart`, the same command resumes from `state.json` and avoids
mappings already present in `evaluations.jsonl`. `--generations` is the total
target generation count, not an additional count.

Generated data lives in `output/mapping_lab/wheel-6/` and is ignored by Git:

- `evaluations.jsonl`: one complete production-filter result per mapping;
- `generations.jsonl`: per-generation signal, comparisons, and model metrics;
- `state.json`: resumable campaign cursor and case fingerprint;
- `model.npz`: network weights and Adam state;
- `dataset.npz`: bounded stage-stratified train/validation corpus;
- `deep_seeds.json`: bounded mutation seed memory;
- `promising_mappings.jsonl`: every stage-8-or-deeper mapping;
- `champions.jsonl`: new campaign depth records;
- `timeout_mappings.jsonl`: mappings stopped by the hard timeout;
- `summary.json`: first/last and model-versus-control summary.

## Dashboard

Double-click `mapping-lab-dashboard.bat`, or run:

```powershell
py.exe -m formal_disk4.mapping_lab.dashboard --input output\mapping_lab\wheel-6\generations.jsonl
```

The page rereads the JSONL every five seconds. The primary evidence of useful
learning is a sustained learned-proposal depth above the independent uniform
control. The transition table shows where signal exists; validation AUC above
0.5 indicates predictive separation, while effectives and conditional pass
rates show whether a deeper transition has enough examples to learn from.
