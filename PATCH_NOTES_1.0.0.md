# Patch 1.0.0 — case catalogue and launcher reorganization

This differential patch applies to version 0.9.1.

## Canonical case identifiers

- `k3-pizza` becomes `c3`;
- `k4-pizza` becomes `c4`;
- `k4-central` becomes `k4`;
- new `k4-minus-point` map;
- new `k4-minus-arc` map.

Legacy map strings remain accepted as aliases.  Emitted records and new
configurations use canonical identifiers.

## New K4-minus topologies

`k4-minus-point` encodes a central tile that reaches the disk boundary at one
three-tile point shared with `T1,T3`.  `T1,T3` otherwise do not share an
interface.

`k4-minus-arc` encodes an outer arc of `T0` between `T3,T1`, with outer cyclic
order `T0,T1,T2,T3`; `T1,T3` are disjoint.

Both maps have positive-length contact graph `K4` minus the edge `T1-T3` and a
reflection automorphism exchanging `T1,T3`.

## Boundary-contact metadata

`PieceSpec` distinguishes `none`, `point`, and `arc` outer contact.  Validation
checks that point contacts own no outer edge and that arc contacts own at least
one outer edge.

The exterior-arc repetition pruning was generalized structurally: it uses the
three peripheral outer arcs even when the central tile has a point contact or
its own outer arc.

## Unified launch system

`run_case.bat` discovers case manifests below `config/cases/`, asks for a case
and action when needed, and supports non-interactive invocation.

Specialized full-pipeline wrappers are supplied for all five cases.  Every case
has isolated formal, geometry and profile output directories, so SQLite
checkpoints remain independent across interleaved runs.

## Tests

The suite adds topology, alias, filter-applicability and checkpoint-isolation
tests for the case catalogue.
