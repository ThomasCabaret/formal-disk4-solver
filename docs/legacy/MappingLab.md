# Mapping Lab (legacy experiment)

> Historical design note. The fixed-graph Mapping Lab is retained as an
> experimental reference and is not the maintained search baseline.

The Mapping Lab is an experimental package around the production formal
filters. It does not change what the production solver accepts or rejects.
Generated datasets, models, reports, and checkpoints all live below `output/`,
which is ignored by Git.

## Maintained entry points

There are three deliberately separate workflows:

1. `formal_disk4.mapping_lab` is the ordinary online learner for a catalog case
   with a declared mapping subdomain. Its default configuration is
   `config/mapping_lab/wheel-6.json`.
2. `formal_disk4.mapping_lab.deep_experiment` is the retained wheel-6 research
   study. It compares uniform sampling, topology-preserving local edits, and
   LP-guided length repair. Its configuration is
   `config/mapping_lab/wheel-6-repair.json`.
3. `formal_disk4.mapping_lab.positive_control` is a known-solvable control. It
   runs the production search for `double-cycle-offset-6`, records exact audit
   boundaries, and tests both offline learnability and online acquisition.

The older `uniform/ranker/frontier/witness` method race was removed. It was
superseded by the exact curriculum and local-repair study and should not be
used as a second implementation of the same experiment.

## Known-solvable positive control

The control first performs the normal `double-cycle-offset-6` search with
three extra audit streams enabled. It labels every surviving weak-order
placement with the deepest exact stage reached:

1. enumerated placement (length and angle LPs passed);
2. pre-word pruning passed;
3. at least one exact word family was emitted;
4. at least one formal profile was emitted.

Labels are attached to `(assignment, placement)` pairs, not to individual word
families or emitted profiles. Thus several formal profiles (including repeated
symmetry-related outcomes) arising from one placement count as one discovered
positive and cannot artificially inflate learning metrics.

The features contain the complete weak-order positions, contour orientation
and cyclic phase for every piece, block count, and the already-computed length
and angle margins. They are therefore available before the expensive word
solver is entered.

Assignments 2 and 7 are held out in full. This is stricter than a random row
split and prevents exact rows from the same contour assignment appearing in
both train and validation data. The report contains:

- conditional validation AUC and log loss for every transition;
- unconditional ranking AUC and top-5/10/25-percent enrichment;
- an online replay against uniform sampling at identical evaluation budgets;
- a compact verdict separating offline signal from online acquisition.

Run the complete control from the project root in PowerShell. The production
collection is expected to take roughly the same time as the standard case
(historically around 15 minutes on the development machine):

```powershell
$env:PYTHONPATH="$PWD\src"
py.exe -m formal_disk4.mapping_lab.positive_control --config config\mapping_lab\double-cycle-offset-6-positive-control.json --restart
```

If collection is interrupted, resume it without `--restart`:

```powershell
$env:PYTHONPATH="$PWD\src"
py.exe -m formal_disk4.mapping_lab.positive_control --config config\mapping_lab\double-cycle-offset-6-positive-control.json
```

After the exact dataset exists, change model settings in the JSON and rerun
only training and reporting:

```powershell
$env:PYTHONPATH="$PWD\src"
py.exe -m formal_disk4.mapping_lab.positive_control --config config\mapping_lab\double-cycle-offset-6-positive-control.json --retrain-only
```

The compact and full reports are written to
`output/mapping_lab/positive-control/double-cycle-offset-6/benchmark/`.
`--max-placements` exists only for developer diagnostics; a capped dataset is
not the scientific positive control and must subsequently be replaced with a
full `--restart` run.

Success on this control means the model and acquisition loop can extract a
known signal. It does not imply transfer to wheel-6, whose distribution and
rarity remain different.

## Wheel-6 local-repair study

The retained deep curriculum splits the former coarse pre-word metric filter
into nested exact stages. The local study compares:

- `uniform`: an unranked control;
- `local_topology`: one-boundary edits ranked by exact topology retention;
- `length_repair`: the same edits with an LP relaxation used only as a proposal
  score. Exact feasibility remains the acceptance rule.

Start a clean study:

```powershell
$env:PYTHONPATH="$PWD\src"
py.exe -m formal_disk4.mapping_lab.deep_experiment --config config\mapping_lab\wheel-6-repair.json --restart --generations 1000 --batch-size 64
```

Resume it by removing `--restart`. Regenerate its report while stopped with:

```powershell
$env:PYTHONPATH="$PWD\src"
py.exe -m formal_disk4.mapping_lab.deep_report --input output\mapping_lab\studies\wheel-6-repair --arms uniform,local_topology,length_repair
```

The clean configuration has no dependency on historical output directories.
On a fresh clone the models and archives start empty; local arms use their
documented uniform fallback until they discover a deep frontier of their own.
Consequently the study is reproducible rather than silently bootstrapping from
a developer's previous method race.
