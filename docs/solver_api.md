# Formal solver API

`formal_disk4.pipeline.FormalSolverAPI` is the public boundary between the
production formal solver and experimental search policies.  It delegates to
the same `SolverRunner` as the CLI; it does not contain a second implementation
of any mathematical filter.

## Inputs

The API accepts the normal search configuration, optional dynamic planar maps,
and optional `AssignmentSelection` values.  An assignment selection contains
raw mixed-radix contour-assignment ids: orientation and cyclic offset choices
before the intrinsic-symmetry quotient.  Selecting a non-canonical id therefore
produces a quotient rejection rather than silently substituting another id.

```python
from formal_disk4.config import load_config
from formal_disk4.pipeline import (
    AssignmentSelection,
    FormalSolverAPI,
    SolverAPIRequest,
)

config = load_config("config/search.json")
result = FormalSolverAPI.evaluate(
    SolverAPIRequest(
        config=config,
        assignments=(AssignmentSelection("wheel-6", (12, 48, 91)),),
    )
)
```

Limits, checkpointing and output paths remain explicit in the supplied config.
The assignment selection is included in the checkpoint fingerprint.

## Outputs

`SolverAPIResult.filters` is an aggregate `FilterReport` for the whole request.
`SolverAPIResult.assignments` contains one report per mapping that was actually
started.  Each report provides the following counts for every stable filter id:

- `entered`: candidates that reached the gate;
- `passed` and `rejected`: decided outcomes;
- `deferred`: resource-limited or mathematically unsupported outcomes;
- `errors`: implementation failures, kept separate from learning evidence;
- `unaccounted`: future/unknown outcomes not represented by the current schema;
- `conditional_pass_rate`: `passed / (passed + rejected)`.

The ordered `target_vector` is suitable as a multi-head supervision target.
Clients must use `target_order` rather than assuming that internal counter names
or dictionary order are stable.  Rejection witnesses are deliberately excluded
from reason totals because several witnesses can describe one rejection.

With `SolverAPIRequest.collect_profiles=True`, emitted formal profiles are
returned directly in `SolverAPIResult.profiles` and the request's candidate
JSONL stream is disabled. This lets experimental callers consume the exact
production records without serializing and immediately reparsing a temporary
file; normal CLI output behavior is unchanged.

## Current boundary

The API can target graphs and complete contour mappings, return labels for all
currently executed weak-order, pre-word and exact-word gates, and optionally
accept a `WeakOrderBranchPolicy` and a `FamilySpecializationPolicy`. The latter
receives the complete family-specialization pool for one solved word case, must
return unique legal indices for that bounded API rollout, and observes each exact
decoration/profile-filter outcome. Unselected candidates are local non-selections,
not solver contradictions or persistent exclusions. The normal CLI passes no policy and retains deterministic
production DFS and historical family order; Graph Lab can drive bounded
stochastic sub-rollouts while continuing to use the same authoritative filters.
