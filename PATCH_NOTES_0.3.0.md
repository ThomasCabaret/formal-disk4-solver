# Patch 0.3.0 - generic map selection and three-piece pizza validation

This differential patch applies over version 0.2.1. Extract it into the project root and allow overwriting.

## New map

Adds `k3-pizza`, the planar map of three congruent sectors meeting at one interior point. It contains:

- three pieces;
- three internal interfaces;
- three exterior circle arcs;
- four geometric vertices;
- nine contour occurrences;
- the six automorphisms of the triangular arrangement.

The same assignment, weak-order, length, angle, word, decoration, filtering, output and checkpoint pipeline is used for both `k3-pizza` and `k4-central`.

## New launcher

`run_pizza3.bat` runs `config\pizza3.json`. It enables reflections and incremental symmetry reduction, uses no power expansion, resumes from `output\pizza3\checkpoint.sqlite3`, and stops after the first fully filtered finite survivor.

A clean run finds the canonical sector solution immediately:

```text
terminal contour: T0^-1 T1 T0
internal mappings: 3
exterior arcs: 3
```

The survivor is written to `output\pizza3\candidates.jsonl` with complete map, placement, equation, mapping, decoration and filter context.

## Genericity changes

- `formal_disk4 run --map NAME` overrides the configured map.
- `formal_disk4 counts --map NAME` reports generic assignment and weak-order counts.
- Mapping coverage and exterior-arc filters use counts supplied by the current map instead of hard-coded values 6 and 3.
- Output schema labels are generalized to `formal-contour-...-v3`.
- Vertex roles use `VertexSpec.kind`, not name prefixes.

## Symmetry correction

Version 0.2.1 assumed that the reversal parity of a map automorphism was independent of the copy assignment. That was valid for K4 because every automorphism fixes the central reference piece, but invalid for a transitive map such as `k3-pizza`.

Version 0.3 computes the required prototype reversal for each transformed assignment. Tests verify:

- 108 raw reflected pizza assignments;
- 22 canonical representatives under the six map automorphisms.

## Mapping-orientation correction

Expanded contour references now distinguish:

- traversal direction of a segment occurrence;
- direct or inverse use of its curve template.

The previous code conflated these notions and could pair a center endpoint with an outer endpoint, producing false decorated-angle contradictions.

## Removal of an unsound default rejection

The cyclic `A A^-1` check is disabled by default. Equal variables denote congruent curve templates, not the same geometric occurrence. A sector contour `A^-1 B A` is a direct counterexample to the old rejection rule.

The old check remains available only as the explicit debugging heuristic:

```json
"enable_cyclic_no_backtracking_heuristic": true
```

## Clearer progress output

Progress lines now show:

- current map;
- finite, power and nested-power family counts;
- number of concrete specializations;
- number of decoration/profile rejections.

This distinguishes symbolic families retained under expansion policy `none` from concrete profiles actually filtered.

## Validation

- Editable installation reports version `0.3.0`.
- 27 unit and integration tests pass.
- The dedicated pizza integration test finds and persists one survivor.
