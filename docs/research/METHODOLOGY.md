# Research operating method

Updated 2026-10-21. This document defines how research is selected, conducted,
recorded, interrupted and reintegrated into the project. It complements the
[charter](README.md): the charter defines standards, while this file defines the
operating loop.

The method must remain lightweight. It exists to preserve scientific context,
not to create an orchestration project alongside the tiling project.

## Research model

The root objective is `R0`: understand and find nontrivial monohedral tilings of
a Euclidean disk. Work proceeds through interacting tracks:

- `MATH`: existence, impossibility, structural and constructive mathematics;
- `ALG`: representations, propagation, enumeration and search algorithms;
- `APPLIED`: translation of proved mathematics into sound computational tests;
- `VALID`: program validation, positive controls and differential tests;
- `COMPLEXITY`: finite encodings, upper/lower bounds and scaling limits.

These tracks may run conceptually in parallel. They need not advance in a fixed
cycle. A mathematical result may preempt an algorithm study; a validation bug
may suspend mathematical interpretation; a complexity result may redirect the
entire computational programme.

## Repository record

The maintained research memory is split by purpose:

| File | Role |
| --- | --- |
| [`README.md`](README.md) | Objective, evidence standards and research charter. |
| [`BACKBONE.md`](BACKBONE.md) | Stable dependency map between questions, stages, mathematics and implementations. |
| [`MATHEMATICAL_RESULTS.md`](MATHEMATICAL_RESULTS.md) | Registry of claims, hypotheses, proof-review status and code dependencies. |
| [`STATE.md`](STATE.md) | Evidence-based snapshot of implementations and approaches. |
| [`AGENDA.md`](AGENDA.md) | Live question tree, dependencies, priorities and current/default target. |
| [`HISTORY.md`](HISTORY.md) | Append-only decisions and completed/parked branches. |
| [`studies/`](studies/) | One reproducible record per concrete investigation. |
| `output/<study-id>/` | Generated data, logs, figures and bulky artifacts. |

Do not use an old implementation checklist as the live agenda. Do not put bulk
outputs into a study note. Do not make `STATE.md` a chronological log.

## Version-control policy

Use local Git commits as atomic research checkpoints. Commit a coherent change
once its scope, evidence and limitations have been recorded; separate unrelated
work and do not disguise an experimental snapshot as a validated baseline.
Generated run histories and bulky outputs remain uncommitted by default.

Never push from an agent session. Do not invoke `git push`, alter a remote, or
publish a branch or tag. The project owner alone decides when local commits are
ready to be pushed. This standing policy authorizes well-scoped local commits;
it does not authorize deleting, resetting, overwriting or absorbing unrelated
unfinished work.

## Research-node schema

Every agenda node has a stable identifier such as `MATH-003` or `ALG-002` and:

- one parent question, except `R0`;
- a precise question and relevance to `R0`;
- explicit hypotheses/domain;
- dependencies and downstream questions;
- a status;
- a stop, falsification or completion condition;
- links to its study records and outputs.

Allowed statuses are:

- `proposed`: useful question, not selected;
- `selected`: next intended study, not yet running;
- `active`: work or an external run is in progress;
- `blocked`: cannot proceed without a named dependency or decision;
- `supported-in-scope`: evidence supports the stated hypothesis only;
- `rejected-in-scope`: the stated hypothesis was falsified only in its domain;
- `inconclusive`: completed work did not discriminate;
- `parked`: deliberately deprioritized, with a resumption trigger;
- `superseded`: replaced by a better-formulated node.

“Failed approach” is not a global status unless the stated domain was actually
covered. A timeout normally produces `inconclusive`, not `rejected-in-scope`.

## Choosing the next target autonomously

When asked to “continue the research” without a more specific target:

1. Read the six maintained files listed above and inspect active study records.
2. Resume an `active` or `selected` node if its assumptions remain valid and a
   bounded next step exists. Otherwise choose among `proposed` nodes.
3. Prefer, in order:
   - a validity blocker whose failure would invalidate downstream conclusions;
   - a high-leverage result that removes or changes a whole search dimension;
   - a small study with high information value between competing approaches;
   - work directly retaining disk-specific structure;
   - local performance work only after correctness and relevance are secure.
4. Penalize vague scope, unavailable ground truth, high cost without an early
   discriminator, and work whose only benefit is polishing a parked approach.
5. State the selected node, hypothesis, smallest discriminating deliverable and
   stopping condition before substantial work.
6. Create or update its study record. Perform one coherent bounded iteration,
   not an open-ended collection of improvements.

Selection is qualitative; a fabricated numerical score is not required. The
decision rationale must mention the alternatives considered and why this node
has higher present information value.

## Study lifecycle

### 1. Orient

Identify the parent question, current evidence and exact hypothesis envelope.
Search the repository before inventing a duplicate note, theorem or experiment.

### 2. Design

Define one falsifiable claim, controls, method, budget and possible outcomes.
For algorithms, specify coverage and certificate semantics. For mathematics,
list proof dependencies and edge cases. For literature work, require primary
sources and separate reported theorems from new deductions.

### 3. Execute

Use the smallest test or proof audit that can change a decision. Record commands,
revision plus dirty patch, seeds, budgets and hardware when they affect results.
Long or expensive runs require an agreed budget; autonomous work defaults to a
short discriminating experiment.

### 4. Evaluate

Classify the outcome with the charter's evidence vocabulary. Record unresolved
cases and alternative explanations. A model that proposed a proof or algorithm
must not be its only substantive reviewer.

### 5. Close or suspend

Update the study status and add a concise entry to `HISTORY.md`. Update
`MATHEMATICAL_RESULTS.md` only when a claim or audit status changed, and
`STATE.md` only when the evidence about an approach changed.

### 6. Return to the parent

Every closed child must say how it changes its parent:

- answers the parent completely;
- removes one branch;
- supplies a new premise or algorithmic tool;
- exposes a new child question;
- or changes nothing and should not be pursued further.

Update `AGENDA.md` accordingly. Do not leave a solved subquestion detached from
the general question that motivated it.

## Branching, preemption and resumption

Open a child node only when its answer can change the parent decision. Record the
parent ID in the study note. Do not expand every interesting aside into a branch.

Preempt active work when:

- a premise is disproved or shown not to apply;
- validation exposes a representation or soundness bug;
- a theorem removes the explored domain;
- a cheaper discriminating study becomes available;
- the user changes the research priority.

On preemption, preserve artifacts, record the exact stopping point, mark the
node `parked` or `blocked`, and state its resumption trigger. Never silently
replace an active question.

## Interaction between the tracks

### Mathematics to algorithm

A result may become a rejection filter, quotient, representation change or
ordering heuristic. Follow the promotion procedure in `BACKBONE.md`: proof
audit, premise detector, soundness controls, differential tests, then measured
selectivity/cost. A promising formula is not immediately a production filter.

### Algorithm to mathematics

Repeated exact conflicts may suggest a lemma. Minimize the conflict, state a
mathematical conjecture independently of code and seek a proof. Empirical
frequency is motivation, not proof.

### Validation to all tracks

A failed positive control preempts performance interpretation. First determine
whether the witness is representable, generated, formally accepted, numerically
realized and fully assembled. Only then interpret search statistics.

### Complexity to algorithm

Complexity claims require a finite encoding and decision problem. Distinguish
the unrestricted Jordan-region question from bounded formal or algebraic
representations. Hardness does not imply that structured disk instances are
practically hopeless; lack of a complexity result does not imply scalability.

## Using language models responsibly

Use models in separated roles when useful:

- **scout:** find candidate primary sources, constructions or representations;
- **designer:** propose an algorithm without being anchored to the current one;
- **critic:** search for missing hypotheses, counterexamples and coverage gaps;
- **integrator:** map audited findings back to the agenda and backbone.

Keep public, reproducible rationale: premises, sources, alternatives considered,
tests performed, outcomes and the decision made. Do not record unverifiable
claims as established facts, and do not treat agreement between models as proof.

### Optional external LLM contracts

The owner can submit well-defined subproblems to another LLM without consuming
this project's agent quota. Use this option when a natural research dependency
has a precise, self-contained statement; do not manufacture extra subgoals just
to delegate work. Mathematical proof audits, counterexample searches and finite
calculations are suitable when their assumptions and checks can be specified.

Write a compact Markdown contract under `docs/research/contracts/` with a stable
ID and parent study/node. Include the complete problem, definitions, assumptions,
source references, requested output (proof, counterexample or explicit gap),
verification/acceptance criteria, and its effect on the parent decision. Supply
all essential content in the contract so the recipient need not read the repo.
Mark it `ready for external review`; do not claim it was sent or accepted merely
because the file exists. Mention its path and purpose in the user-facing report.
The owner handles transmission; creating a contract does not authorize sending
repository contents or messages to an external service.

An external answer is a candidate result until its arguments/calculations have
been checked here. Preserve the returned answer or an exact reference, record
gaps and the validation outcome in the parent study, then update the agenda and
registry only as warranted. Failure or no reply leaves the question open and
available to resume locally. Continue independent useful work while a contract
is outstanding; external review is never an automatic blocker or proof oracle.

## Completion standard for one research turn

A research turn is complete when it leaves:

1. a clear question and scope;
2. an inspectable artifact, proof audit or reproducible experiment;
3. an evidence-qualified conclusion;
4. the resulting agenda/parent update;
5. an explicit next decision or stopping condition.

If the work is incomplete, leave the study resumable: exact stopping point,
remaining uncertainty and next bounded action. Make local commits according to
the version-control policy above. Deleting historical data or launching an
unbounded run still requires the user's authorization.
