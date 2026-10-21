# Research charter and method

Updated 2026-10-21. This is the current direction, not a claim that the software
already achieves it. Continue with the [operating method](METHODOLOGY.md), the
[live agenda](AGENDA.md), [research backbone](BACKBONE.md), the
[mathematical-results registry](MATHEMATICAL_RESULTS.md), and then
[STATE.md](STATE.md) for the implementation landscape.

The [working problem specification](PROBLEM_SPEC.md) defines the default
nontriviality predicate, the separate Stein target and bounded computational
variants. It was produced by [SPEC-001](studies/SPEC-001-problem-domain.md).
The [research roadmap](ROADMAP.md) connects mathematical goals, competing proof
and algorithmic approaches, and structural reductions. The [live tree](AGENDA.md)
is the single reference for their hierarchy. Before substantive work, follow
the [macro-to-micro gate](METHODOLOGY.md#mandatory-macro-to-micro-refinement):
locate the task, explain its parent benefit and alternatives, bound the work,
then return its result to the parent. Do not start an orphan implementation task.

## Objective and scope

Find and understand nontrivial monohedral tilings of the Euclidean disk: copies
of one tile, congruent under the allowed isometries, filling the disk without
interior overlaps or gaps. Known nontrivial examples are controls, not the final
discovery target. Rediscovering them is useful for validation but is not itself
a new mathematical result. Sector/pizza tilings are elementary controls.

Producing original mathematics is a central project objective and an expected
part of an agent's work: formulate and attempt to prove new theorems, develop
new constructions and derive new obstructions or algorithmic reductions.
Literature review supplies context and a novelty check; absence of a published
answer is a reason to investigate, not to stop at a bibliography. Preserve
LLM-generated arguments with their assumptions, gaps and review status.

The exact meaning of **nontrivial** must be specified for each investigation.
Do not identify it solely with a contact-graph shape or a dashboard category.
Likewise record tile connectedness, boundary regularity, permitted reflections,
point versus positive-length contacts, global symmetries, intrinsic tile
symmetries and any centre-tile assumption. A theorem about a restricted class
does not automatically extend to all disk tilings.

The formal-contour and word-equation pipeline is a substantial existing asset,
but remains a hypothesis about how best to search. The project may advance by
mathematics without code, or by another computational representation.

## Research tracks

| Track | Questions | Useful deliverable |
| --- | --- | --- |
| Existence / impossibility | Under which explicit hypotheses must or cannot a tiling exist? Can existence be proved nonconstructively? | A proof with scope and independently checked steps; or a precisely stated conjecture. |
| Constructive mathematics | Can a family of tiles and placements be constructed directly? | Parameterized construction, admissibility conditions and verification of disk coverage and congruence. |
| Mathematical reductions | What necessary conditions eliminate entire classes before enumeration? What does the circular boundary imply beyond local curvature constraints? | A proved reduction, its assumptions, a computable test and measured selectivity/cost. |
| Algorithm design | Which decisions should be joint, incremental or deferred? Which state and equivalences avoid redundant enumeration? | A small implementation, correctness/coverage argument and controlled comparison. |
| Validation and subcases | Where does the current implementation fail, stall, or omit possibilities? | Reproducible known-positive tests, minimized failures and stage-level diagnostics. |

These tracks interact: a theorem may change the representation rather than add
another filter; a computational obstruction may suggest a lemma but is not its
proof. A useful advance need not produce a new geometric tiling immediately.

## Disk first; relaxed cases as instruments

Free-boundary patches, tetrads and crown fragments help isolate defects and
measure combinatorics. They must not silently replace the disk objective.
Relaxing the boundary enlarges feasibility, but can also remove structure an
algorithm could exploit. There is no established implication that an algorithm
slow on tetrads must be slow on a disk-specific formulation, or that a fast
tetrad algorithm will scale to disk tilings with many tiles.

Study both when relevant: (a) controls isolating a kernel operation, (b) disk
instances retaining the hypotheses of the proposed reduction. Any claim about
lower complexity needs a defined input representation, parameter and argument;
neither a new constraint nor a faster sample establishes such a claim alone.

## Minimal research loop

1. Write one question and a falsifiable hypothesis. Name the track and the link
   to the disk objective. Read relevant existing notes before adding machinery.
2. Specify the domain and outcome that would support or refute the hypothesis.
   Identify a baseline and positive controls; do not hardcode known answers into
   an allegedly agnostic sampler.
3. For a mathematical claim, inspect every assumption and proof step. For code,
   first test representation, soundness and known positives. Missing solutions
   are initially diagnostic evidence, not evidence of a theorem.
4. Run the smallest discriminating experiment or proof check. Agree on long-run
   budgets before launching them. Keep the search order and other settings fixed
   when comparing one change, or explain why that cannot be done.
5. Record the result, limitations and next decision: retain, revise, park or
   abandon the hypothesis. Preserve failed experiments if they explain a choice.

## Outcomes and evidence

Keep separate: formal candidate; numerically realized single tile; assembled
patch with required contacts; validated disk tiling; exact construction/proof.
A picture of a closed tile is not validation of an assembly. For numerical
solutions record tolerances and which geometric properties were actually tested.

For negative outcomes distinguish certified infeasibility of a specified
subsystem, exhaustion of a supported finite domain, unsupported word cases,
resource interruption, and failure to find a numerical witness. A global
impossibility claim needs justified coverage and sound rejection throughout;
neither a solver status string nor excluding unsupported systems supplies that.

Measure time-to-first-validated-result, cumulative results, unresolved counts,
and time-to-exhaustion where meaningful. Also record time by stage, decisions
and rejection depth, duplicate work and memory/disk usage. State denominators
for pass rates and count distinct structures separately from profiles/attempts.
For stochastic comparisons use several seeds before claiming robust improvement.
Do not extrapolate hours on four tiles into a quantitative runtime for 28 tiles
without an explicit scaling model. Historical small tests are not current audits.

## Record for a study

Create `docs/research/studies/<id>-<slug>.md` from
[`studies/TEMPLATE.md`](studies/TEMPLATE.md) when there is an actual study. The
template records its parent question and return path as well as reproducibility.

No new lab framework is required. Use existing tests/scripts when appropriate.
Store generated artifacts in a dedicated `output/<study>/` directory, and keep
enough provenance to distinguish runs. Do not assume checkpoint compatibility
or full graph-generator coverage without verifying the specific mode.

## Current continuation

The initial inventory is complete; research continues through the live agenda.
`SPEC-001` supplied the working problem contract; `MATH-001` supplied a first
[literature map](LITERATURE_FRONTIER.md). The next study is currently under
discussion with the owner; no new research run or proof study is active.
The known-shape/placement replay proposal is withdrawn. Original-mathematics
targets remain proposed in the agenda, with an existing-lemma audit available
as an optional external contract.
Historical TODO lists do not select that work.
Proof audits, search experiments and algorithm choices must each satisfy the
method above; completing the inventory did not validate the stored mathematics
or select a winning search method.
