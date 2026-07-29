# Benchmark interpretation for version 0.3

The progress line now separates symbolic families from concrete profile work. Example:

```text
[ 123.77s] map=k4 overall~0.0% assignment=1/256 current~0.0% nodes=662 (5/s) length_pruned=522 angle_pruned=1 placements=2 word_systems=2 families=5[finite=3,power=2,nested=0] specializations=3 profile_rejections=3 profiles=0
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

## Version 0.7 short stage profile

`run_case.bat k4 profile` runs the normal `k4` pipeline for approximately 20 seconds with no checkpoint and no candidate output. The exact-partial solver now receives the run stop predicate, so a time limit also interrupts a large residual-graph exploration instead of waiting for the current word system to finish.

A representative 20-second run in the development environment produced:

```text
placement nodes                 661
length checks                   572
length-pruned nodes             522
angle checks                     50
angle-pruned nodes                1
surviving placements              2
word systems                      2
finite families                   5
```

Measured non-overlapping stage times were approximately:

```text
exact-partial word solver       19.27 s   96.2%
weak-order enumeration           0.35 s    1.7%
terminal profile decoration      0.01 s    0.05%
word compilation                 0.001 s   negligible
```

The length oracle made 574 calls, of which 487 were cache hits; 87 actual cache misses consumed about 0.24 seconds and pruned 522 nodes. The angle oracle made 52 calls, of which 33 were cache hits; 19 misses consumed about 0.05 seconds and pruned one node.

Therefore the current order, length before angle, is appropriate. Reversing it would make the weak angle filter run on many branches that the stronger length filter already removes. The immediate optimization target is the exact-partial word solver, not the early LP ordering.

A `cProfile` sample of the same workload identified the largest internal costs as residual-state canonicalization, word substitution and expression-environment substitution/serialization. These are the first areas to optimize before adding heavier pre-geometric filters.

## Version 0.8 circular pre-word profile

The same 20-second K4 profile with the circular pre-word layer enabled produced in the development environment:

```text
placement nodes                         34,339
complete placements                     1,920
pre-word circular rejections             1,919
word systems sent to Nielsen-Levi            1
```

The rejection breakdown was approximately:

```text
exterior seed already crosses hard endpoint       1,856
mapped circular image crosses hard endpoint          18
forced overlap with opposite circular sign           45
```

Stage times were approximately:

```text
weak-order enumeration                  18.58 s
circular pre-word layer                  1.07 s
word solver                              0.002 s
word compilation                         0.13 s
```

The strict-order LP screen made 356 calls and the exact rational rejection certifier made 126 calls. A comparison run with the pre-word layer disabled spent about 9.68 of 10 seconds in the word solver and visited only 661 placement nodes. This workload is not a proof of the eventual global rejection ratio, but it confirms that the filter is cheap relative to Nielsen-Levi and should remain before it.

## Version 0.9 refactored pre-word profile

A final 10-second `k4` run of the refactored layer produced:

```text
placement nodes                         16,084
complete placements                        924
pre-word topology rejections                923
pre-word linear-invariant rejections          1
word systems sent to Nielsen--Levi            0
```

The non-overlapping stage times were approximately:

```text
weak-order enumeration                   8.83 s
pre-word pruning                         0.82 s
word compilation                         0.08 s
```

The single topology survivor was rejected by the exact joint metric system. The floating screen reported zero strict margin and the rational simplex confirmed it. This particular early sample therefore spent no time in Nielsen--Levi.

The result is not an estimate of the global K4 rejection rate: it covers only the beginning of the first canonical assignment. It does confirm that the refactored metric system is cheap enough to remain before word solving and that the Stein-only concavity constraint is active without breaking the pizza validation maps.

## 0.9.1 transported exterior-arc repetition

A 10-second differential run from assignment 1 compared the guarded weak-order filter with the same build using `--no-exterior-arc-repetition`.

| mode | visited nodes | exterior-arc pruned prefixes | raw weak orders accounted | current assignment |
|---|---:|---:|---:|---:|
| enabled | 35,805 | 18,098 | 1,586,428 | 0.5950% |
| disabled | 24,185 | 0 | 21,884 | 0.0082% |

The filter leaves all 256 canonical phase/parity assignments in the domain. Its gain comes from counting large impossible weak-order subtrees as completed immediately after corresponding exterior endpoints split.
