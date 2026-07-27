# Benchmark interpretation for version 0.3

The progress line now separates symbolic families from concrete profile work. Example:

```text
[ 123.77s] map=k4-central overall~0.0% assignment=1/256 current~0.0% nodes=662 (5/s) length_pruned=522 angle_pruned=1 placements=2 word_systems=2 families=5[finite=3,power=2,nested=0] specializations=3 profile_rejections=3 profiles=0
```

- `nodes`: partial weak-order prefixes visited. This includes prefixes rejected early and complete leaves. It is not a count of equations or placements.
- `length_pruned`, `angle_pruned`: prefixes whose whole descendant subtrees were rejected by the corresponding early LP.
- `placements`: complete weak orders surviving early filters.
- `word_systems`: placements actually sent to the exact-partial word solver.
- `families`: supported symbolic families found across those systems.
- `finite`, `power`, `nested`: family-kind breakdown.
- `specializations`: concrete family instances sent to terminal decoration. Under default policy `none`, only finite families contribute.
- `profile_rejections`: decoration failures plus local profile-filter failures.
- `profiles`: survivors committed to SQLite and exported to `candidates.jsonl`.

Thus `word_systems=2, families=5, profiles=0` means that two systems produced five supported symbolic families in total. It does not prove that all five were filtered: power families may not have been specialized at all. Consult `family_specializations`, `families_not_specialized`, `decoration_rejection_*` and `profile_filter_rejection_*` in `run_summary.json`.

The displayed node rate is cumulative wall-clock throughput and includes time spent inside word solving and profile processing. It is not a pure weak-order enumeration microbenchmark.

Important exact-partial counters include:

- `residual_graph_nodes`, `residual_graph_edges`;
- `unsupported_complex_components`;
- `exact_unsat_word_cases`;
- `graph_limited_word_cases`;
- `word_family_finite`, `word_family_power`, `word_family_nested_power`;
- `family_specializations`, `families_not_specialized`;
- `decoration_rejection_*`, `profile_filter_rejection_*`.

The percentage is the fraction of raw anchored weak orders accounted for by completed or pruned DFS subtrees across canonical assignments. It is monotone but not an ETA.
