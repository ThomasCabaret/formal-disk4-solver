# Architecture 0.3

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

Each prototype point also carries a signed turn `t` in units of pi. A copy with orientation sign `s` sees interior angle `alpha = 1-s*t`. Vertex equations use the incidence and prescribed angle sum supplied by the map.

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

Mappings induce signed endpoint classes and curve-template transformations. A signed union-find resolves equal, complementary and forced-zero turn classes. A second angle LP checks the terminal subdivisions introduced by the word solver.

Curve variables are grouped under identity, reverse, mirror and mirror+reverse. Exterior words mark complete curve components as arcs of the common disk circle.

The exported circle constraints are generic over the number of exterior arcs:

```text
sum(O_i) = C_disk
sum(theta_i) = 2
theta_i * C_disk = 2 * O_i
```

## 9. Local filters

Current exact local checks include nonempty contour, positive terminal component lengths, signed-angle bounds, complete map-dependent mapping coverage, curve-template compatibility and complete outer-circle decorations.

The old cyclic `A A^-1` rejection is disabled by default because equal variables denote congruent templates, not identical geometric occurrences. The three-sector contour `A^-1 B A` is a direct counterexample.

## 10. Streaming and checkpointing

Every placement is compiled, solved and filtered immediately. Only survivors are persisted by default. SQLite stores one compact DFS cursor and cumulative statistics, not the explored tree or rejected systems.

The progress percentage credits the full raw descendant mass whenever a subtree is completed or rejected. It estimates combinatorial coverage, not remaining wall-clock time.


## Exact terminal decoration layer

After a finite family is specialized, the decoration layer builds two exact rational linear systems:

1. terminal interior-angle equations, combining mapping-induced equalities/full-turn complements with physical map-vertex sums;
2. terminal curve-length equations, obtained by substituting terminal component counts into the placement length rows and normalizing the disk circumference to one.

Exact row reduction produces solved rational values or affine expressions in named free parameters. A separate floating LP is used only to certify the existence of a strictly positive/interior witness. The two roles are deliberately separated in the output schema.

## 11. Numerical single-piece contour stage

The `geometry` command is intentionally downstream and independent of map
assembly. It reads complete formal survivor records and solves only one piece
boundary.

A generic curve component is a shared local polyline template with a configurable
number of intermediate points. The default is one intermediate point. Variable
relations and literal inversion are applied as identity, reverse, mirror or
mirror+reverse transformations of that local template.

A circular component is represented analytically by local start point, start
tangent, signed sweep, radius and center. Its sampled points are temporary and
used only by the numerical simplicity validator.

Starting from a fixed origin and initial tangent removes global Euclidean motion.
Each curve occurrence determines the next point and incoming tangent. The resolved
interior angle determines the outgoing tangent. The optimizer chooses formal free
parameters and generic-template shapes so the final point and tangent close.

The emitted geometry remains linked to its formal input through
`formal_profile_id`. Assembly and rendering are deliberately deferred.

## Visualization and assembly layer

`formal_disk4.visualization` is downstream of the numerical single-piece geometry stage. It never changes the realized prototype contour.

`assembly.py` treats every copy placement as an orthogonal matrix plus translation. The reference piece receives the identity transform. Each internal contact mapping gives a relation between directed terminal-segment samples on two copies and a determinant sign. The unknown copy transform is derived deterministically, propagated over the contact graph and checked on every graph cycle.

`viewer.py` is deliberately thin. It indexes JSONL byte offsets, assembles the selected record on demand, and converts transformed piece polygons to Tk canvas coordinates. GUI imports are lazy so the solver and tests remain usable in headless environments.
