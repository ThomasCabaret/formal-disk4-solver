# Patch 1.4.0 - Cyclic two-ring campaign families

Apply this differential archive directly over 1.3.1.

## New mathematical families

The existing `double-cycle-N` builder remains DC1. Three additional planar map
families are available dynamically for every `N >= 3`:

- `double-cycle-offset-N` (DC2), with cross offsets `{0,1}`;
- `inner-cycle-boundary-points-N` (DC4), with no positive outer-cycle edges;
- `outer-cycle-center-points-N` (DC5), with no positive inner-cycle edges.

All three expose the cyclic automorphisms `rotation_0` through
`rotation_(N-1)`, so the existing assignment and weak-order equivariance is
active in the campaign configuration.

DC3 (`double-cycle-wide-N`) is retained in campaign lists as an exact structural
obstruction. It requests `5N` edges in the annular positive-interface graph,
above the planar maximum `4N`, and therefore completes with zero candidates.

## External campaign orchestration

Two launchers are added:

```bat
run_cycle_case.bat <family> <N> <mode> [options]
run_cycle_suite.bat <suite> <mode> [options]
```

No per-case batch files are generated. Suite membership is defined only by JSON
files under `config/suites/`.

Each concrete case writes exclusively under `output/cases/<case-id>/` and keeps
independent formal and geometry checkpoints.

For a fresh suite use `--restart-all`. For resume, omit every restart flag.
The suite walks its list from the beginning; completed cases return immediately
and the interrupted case resumes from its own checkpoint.

## Counting and visualization

`count` prints per-case and total counts for formal candidates, geometry inputs,
accepted solutions and failures, and writes CSV/JSON reports under
`output/suites/<suite-id>/`.

Suite visualization concatenates the current per-case geometric-solution JSONL
files into a disposable suite JSONL and opens one viewer over the combined set.

## Validation

- all DC2/DC4/DC5 maps validate for N=3,4,5;
- cyclic equivariance starts successfully for every supported family;
- the 15-case fresh suite and resume pass were exercised;
- 78 unit tests pass.
