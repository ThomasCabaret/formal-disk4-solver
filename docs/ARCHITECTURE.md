# Architecture 0.9

## 1. Map-driven core

`PlanarMap` stores arbitrary pieces, oriented combinatorial contours, geometric vertices, internal interfaces, exterior arcs, automorphisms and a reference copy used only to anchor the prototype orientation.

Registered maps:

- `k4-central`: contour lengths `(3,4,4,4)`, six internal interfaces and three exterior arcs;
- `k3-pizza`: contour lengths `(3,3,3)`, three internal interfaces and three exterior arcs;
- `k4-pizza`: contour lengths `(3,3,3,3)`, four internal interfaces and four exterior arcs.

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

Each prototype point also carries a signed point turn `tau=1-alpha` in units of pi. Every physical map vertex contributes one sum of positive solid interior angles: `2*pi` at an interior vertex and `pi` at an outer vertex. Copy reflection does not change the positive solid angle. These early placement oracles currently use SciPy HiGHS and serve only to prune partial weak orders.

## 5. Word compilation

Each atomic interval becomes `X0`, `X1`, and so on. Every internal interface produces:

```text
left_positive_word = inverse(right_positive_word)
```

The compiler records direct/reflected parity and every exterior word.

A directed mapping reference records traversal of the expanded contour segment. Literal inversion separately records orientation relative to the curve template. These two notions must not be conflated.

## 5.1 Early exterior-arc repetition in the weak-order DFS

For the supported four-piece Stein map shape, a transported-exterior-arc theorem forces at least two peripheral outer edges to represent the same prototype interval. The filter is guarded by explicit structural checks and is otherwise inactive.

Each candidate repeated pair stores the two ordered endpoint occurrences. During weak-order construction a pair remains possible only while corresponding endpoints are both unplaced or already occupy the same block. If all candidate pairs become impossible, the whole remaining subtree is counted as processed and pruned before any length LP, angle LP, word compilation or Nielsen--Levi work.

The phase/parity assignment layer only determines whether an outer edge crosses the chosen global cut. For `k4-central`, all 256 canonical assignments retain one or three possible pairs, so the material reduction begins in the weak-order iterator rather than in the assignment count.

## 6. Refactored pre-word pruning layer

The layer runs after word compilation and before residual-state construction. It is composed of independent necessary-condition modules.

### 6.1 Radius-arc topology

Exterior words seed convex arcs of the disk circle. Boundary-aligned images are propagated through internal interfaces with opposite convexity. The module rejects:

- a smooth radius-R arc forced across a hard outer corner;
- a positive-length atom forced both convex and concave;
- a mapped image forced to overlap an existing opposite-sign interval.

It never guesses a Nielsen--Levi subdivision. Non-aligned symbolic images are reported as unresolved. LP-dependent interval rejections are confirmed by the exact strict-length oracle.

### 6.2 Joint metric invariants

For every atomic interval `i`, the module introduces:

```text
l_i > 0                    atomic length
r_i+ >= 0, r_i- >= 0       radius-R convex/concave measures
r_i+ + r_i- <= l_i
H_i in R                   disk-circumference-scaled smooth turn
```

The scaling `H_i = C_disk * K_i/pi` makes the circle rule linear: a forced convex or concave radius-R atom satisfies `H_i = +/-2*l_i`. Interface equations preserve length, exchange `r+` and `r-`, and cancel physical smooth turn.

The same system contains the general congruent-disk identities:

```text
tile_count * (L_plus - L_minus) = C_disk
tile_count * smooth_turn = 2*pi
```

It also contains a linear isoperimetric necessary condition. For non-square tile counts, a certified rational upper bound on `sqrt(tile_count)` is used, producing a slightly weaker but sound inequality.

The Stein-only condition `L_minus > 0` is enabled through `ProblemHypotheses.center_strictly_inside_one_tile`; pizza validation maps do not enable it.

### 6.3 Point turns

Point turns use a separate exact LP because their variables do not occur in the metric system. Local map-vertex equations are combined with:

```text
sum(point turns on one tile) = 2 - 2/tile_count
```

### 6.4 Soundness policy

HiGHS is only a fast feasibility screen. A placement is rejected by the linear modules only after the rational simplex proves that the best strict margin is non-positive. Unexpected construction errors are logged and conservatively passed to Nielsen--Levi.

## 7. Exact-partial word solver

Residual systems are canonicalized and explored as a Nielsen-Levi graph.

A repeated residual state is compiled only when its cycle has fixed contexts. Supported cycles produce power expressions and successive supported cycles may produce nested powers. More general iterative components are recorded and cut.

The statuses distinguish supported solutions, exact unsatisfiability, unsupported family language and configured graph limits.

## 8. Family specialization

The default expansion policy is `none`:

- finite families produce one concrete specialization;
- power and nested-power families remain symbolic;
- only concrete specializations enter decorations and local profile filters.

## 9. Terminal decorations

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

## 10. Exact terminal angular feasibility

After word solving, the same mathematical model is rebuilt on terminal curve components. It contains:

- point-angle class equations;
- terminal component-length equations;
- mapping-induced curve-turn sign equations;
- zero-turn equations for straight or self-turn-reversing components;
- exterior-circle length/turn equations.

For piecewise-C2 maps, the two global contributions are constrained separately:

```text
sum(signed smooth curve turns) = 2/tile_count
sum(point turns) = 2 - 2/tile_count
```

Their sum is the usual full winding `2`. The curve-turn variables remain unbounded; only point turns have the strict `(-1,1)` domain.

Exact Gaussian elimination expresses all variables as affine rational functions of a minimal free set. A small rational simplex then maximizes a common strict margin for point-angle bounds and positive component lengths. Infeasible profiles are rejected before persistence and numerical geometry.

## 11. Local filters

Current local checks include:

- nonempty terminal contour;
- positive terminal component lengths;
- signed point-angle bounds;
- exact joint point/curve-turn feasibility and total winding;
- complete map-dependent mapping coverage;
- curve-template compatibility;
- complete outer-circle decorations.

The old cyclic `A A^-1` rejection is disabled by default because equal variables denote congruent templates, not identical geometric occurrences. The three-sector contour `A^-1 B A` is a direct counterexample.

## 12. Streaming and checkpointing

Every placement is compiled, solved and filtered immediately. Only survivors are persisted by default. SQLite stores one compact DFS cursor and cumulative statistics, not the explored tree or rejected systems.

The progress percentage credits the full raw descendant mass whenever a subtree is completed or rejected. It estimates combinatorial coverage, not remaining wall-clock time.

## 13. Numerical single-piece contour stage

The `geometry` command is downstream and independent of map assembly. It reads complete formal survivor records and solves only one piece boundary.

A generic curve component is a shared local polyline template with a configurable number of intermediate points. The default is one intermediate point. Variable relations and literal inversion are applied as identity, reverse, mirror or mirror+reverse transformations of that local template.

A circular component is represented analytically by local start point, start tangent, signed sweep, radius and center. Its sampled points are temporary and used only by the numerical simplicity validator.

Starting from a fixed origin and initial tangent removes global Euclidean motion. Each curve occurrence determines the next point and incoming tangent. The resolved interior angle determines the outgoing tangent. The optimizer chooses formal free parameters and generic-template shapes so the final point and tangent close. It now also enforces every exact formal component turn `K_Ci*pi`; generic-curve turn is no longer left unconstrained numerically.

The emitted geometry remains linked to its formal input through `formal_profile_id`.

## 13. Visualization and assembly layer

`formal_disk4.visualization` is downstream of the numerical single-piece geometry stage. It never changes the realized prototype contour.

`assembly.py` treats every copy placement as an orthogonal matrix plus translation. The reference piece receives the identity transform. Each internal contact mapping gives a relation between directed terminal-segment samples on two copies and a determinant sign. The unknown copy transform is derived deterministically, propagated over the contact graph and checked on every graph cycle.

`viewer.py` indexes JSONL byte offsets, assembles the selected record on demand, and converts transformed piece polygons to Tk canvas coordinates. GUI imports are lazy so the solver and tests remain usable in headless environments.
