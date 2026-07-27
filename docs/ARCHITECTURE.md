# Architecture 0.6

## 1. Map-driven core

`PlanarMap` stores arbitrary pieces, oriented combinatorial contours, geometric vertices, internal interfaces, exterior arcs, automorphisms and a reference copy used only to anchor the prototype orientation.

Registered maps:

- `k4-central`: contour lengths `(3,4,4,4)`, six internal interfaces and three exterior arcs;
- `k3-pizza`: contour lengths `(3,3,3)`, three internal interfaces and three exterior arcs.

No downstream layer assumes four copies or six mappings. Expected mapping and exterior-arc counts are carried into each profile from its map.

## 2. Copy assignments and symmetry

A `ContourAssignment` gives one cyclic sequence per copy. `cyclic_offsets` records which occurrence appears first after the prototype cut. Non-reference copies may be direct or reflected; fixing the reference orientation removes global contour reversal.

Automorphisms can move the reference piece. Consequently, the reversal needed to restore the reference contour orientation is computed for each transformed assignment, rather than being stored as a map-level constant.

Symmetry modes are independently switchable:

- `off`: no quotient;
- `assignment`: quotient assignments only;
- `incremental`: assignment quotient plus stabilizer checks on prefixes and leaves.

For `k3-pizza`, the raw reflected domain has 108 assignments and the map quotient emits 22 representatives.

## 3. Weak cyclic orders

A search node is a nonempty sequence of coincidence blocks. Each block consumes the next occurrence of any nonempty subset of copies and contains at most one occurrence per copy. Thus all allowed degeneracies between different copies are represented.

`placement_nodes` counts these partial prefixes, not word systems. A complete prefix that survives early constraints becomes a `Placement`.

## 4. Early linear constraints

For atomic lengths `x`:

```text
maximize epsilon
A x = 0
sum(x) = 1
x_i >= epsilon
```

Every resolved internal interface contributes one integral equality row.

Each prototype point also carries a signed point turn `tau` in units of pi. A copy with orientation sign `s` sees interior angle `alpha = 1-s*tau`. Vertex equations use the incidence and prescribed angle sum supplied by the map. These early placement oracles currently use SciPy HiGHS and serve only to prune partial weak orders.

## 5. Word compilation

Each atomic interval becomes `X0`, `X1`, and so on. Every internal interface produces:

```text
left_positive_word = inverse(right_positive_word)
```

The compiler records direct/reflected parity and every exterior word.

A directed mapping reference records traversal of the expanded contour segment. Literal inversion separately records orientation relative to the curve template. These two notions must not be conflated.

## 6. Exact-partial word solver

Residual systems are canonicalized and explored as a Nielsen-Levi graph.

A repeated residual state is compiled only when its cycle has fixed contexts. Supported cycles produce power expressions and successive supported cycles may produce nested powers. More general iterative components are recorded and cut.

The statuses distinguish supported solutions, exact unsatisfiability, unsupported family language and configured graph limits.

## 7. Family specialization

The default expansion policy is `none`:

- finite families produce one concrete specialization;
- power and nested-power families remain symbolic;
- only concrete specializations enter decorations and local profile filters.

## 8. Terminal decorations

After a finite family is specialized, the terminal contour alternates decorated points and decorated curve occurrences.

### Point decorations

Every terminal point has an interior-angle variable `alpha_Bi` in units of pi and a signed point turn

```text
tau_Bi = 1 - alpha_Bi
```

with the strict geometric domain

```text
-1 < tau_Bi < 1
```

or equivalently `0 < alpha_Bi < 2`. Mappings and physical map vertices induce exact rational equalities and complement relations between these point variables.

### Curve decorations

Mappings group terminal variables into curve-template components. Every component receives:

- a positive normalized length variable `L_Ci`;
- an unbounded signed total tangent-turn variable `K_Ci`, in units of pi;
- a geometric type: generic curve, forced straight segment or arc of a named common circle.

The sign with which a contour occurrence contributes `K_Ci` is determined by literal traversal and the mapping-induced template transform. Reversal or reflection reverses signed curve turn. A straight component, or a component identified with itself through a turn-sign-reversing transform, satisfies `K_Ci = 0`.

These internal curve transforms do **not** place copies. Relative copy placement remains determined only by the complete oriented contact mappings and their direct/reflected parity.

### Exterior circle

Exterior words mark complete curve components as arcs of `disk_boundary`. With disk circumference normalized to one, a positively traversed exterior occurrence satisfies

```text
K_Ci = 2 * L_Ci
```

in pi units. The generic outer constraints are

```text
sum(O_i) = C_disk
sum(theta_i) = 2
theta_i * C_disk = 2 * O_i
```

where `C_disk=1` in normalized expressions.

## 9. Exact joint angular feasibility

Before a profile is persisted, one exact rational system simultaneously contains:

- all point-angle equations;
- all terminal component-length equations;
- all mapping-induced curve-turn sign equations;
- zero-turn equations for straight or self-turn-reversing components;
- exterior-circle length/turn equations;
- the total-turn equation of the prototype contour:

```text
sum(signed curve occurrence turns) + sum(tau_Bi) = 2
```

The curve-turn variables are unbounded: a generic curve may spiral through any finite signed total turn. Only point turns have the strict `(-1,1)` bound.

Exact Gaussian elimination first expresses all variables as affine rational functions of a minimal set of free parameters. A small two-phase simplex using `fractions.Fraction` then maximizes one common strict margin for:

- `0 < alpha_Bi < 2`;
- `L_Ci > 0`.

If the exact optimum is zero or the equality system is inconsistent, the profile is rejected before SQLite, `candidates.jsonl` and numerical geometry. The exact affine solution and a rational strict witness are exported with every survivor.

## 10. Local filters

Current local checks include:

- nonempty terminal contour;
- positive terminal component lengths;
- signed point-angle bounds;
- exact joint point/curve-turn feasibility and total winding;
- complete map-dependent mapping coverage;
- curve-template compatibility;
- complete outer-circle decorations.

The old cyclic `A A^-1` rejection is disabled by default because equal variables denote congruent templates, not identical geometric occurrences. The three-sector contour `A^-1 B A` is a direct counterexample.

## 11. Streaming and checkpointing

Every placement is compiled, solved and filtered immediately. Only survivors are persisted by default. SQLite stores one compact DFS cursor and cumulative statistics, not the explored tree or rejected systems.

The progress percentage credits the full raw descendant mass whenever a subtree is completed or rejected. It estimates combinatorial coverage, not remaining wall-clock time.

## 12. Numerical single-piece contour stage

The `geometry` command is downstream and independent of map assembly. It reads complete formal survivor records and solves only one piece boundary.

A generic curve component is a shared local polyline template with a configurable number of intermediate points. The default is one intermediate point. Variable relations and literal inversion are applied as identity, reverse, mirror or mirror+reverse transformations of that local template.

A circular component is represented analytically by local start point, start tangent, signed sweep, radius and center. Its sampled points are temporary and used only by the numerical simplicity validator.

Starting from a fixed origin and initial tangent removes global Euclidean motion. Each curve occurrence determines the next point and incoming tangent. The resolved interior angle determines the outgoing tangent. The optimizer chooses formal free parameters and generic-template shapes so the final point and tangent close. It now also enforces every exact formal component turn `K_Ci*pi`; generic-curve turn is no longer left unconstrained numerically.

The emitted geometry remains linked to its formal input through `formal_profile_id`.

## 13. Visualization and assembly layer

`formal_disk4.visualization` is downstream of the numerical single-piece geometry stage. It never changes the realized prototype contour.

`assembly.py` treats every copy placement as an orthogonal matrix plus translation. The reference piece receives the identity transform. Each internal contact mapping gives a relation between directed terminal-segment samples on two copies and a determinant sign. The unknown copy transform is derived deterministically, propagated over the contact graph and checked on every graph cycle.

`viewer.py` indexes JSONL byte offsets, assembles the selected record on demand, and converts transformed piece polygons to Tk canvas coordinates. GUI imports are lazy so the solver and tests remain usable in headless environments.
