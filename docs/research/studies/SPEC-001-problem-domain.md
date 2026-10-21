# Study SPEC-001 — Mathematical target and finite search domains

## Identity

- Node / parent: `SPEC-001` / `R0`.
- Track: specification supporting `MATH`, `VALID`, `ALG` and `COMPLEXITY`.
- Status: supported-in-scope (specification delivered; independent review pending).
- Owner / opened / updated: Codex / 2026-10-21 / 2026-10-21.
- Relevance: define what a disk discovery, a restricted failure and an
  algorithm comparison actually mean before selecting the next investigation.

## Question and hypotheses

Can we separate the unrestricted Jordan-tile existence question from bounded
formal and geometric problems, with explicit success and negative-certificate
semantics? Hypothesis: the existing sources and interfaces suffice to specify
those domains and expose their coverage obligations without another refactor.

The base target is a complete unit disk, congruent Jordan regions, reflections
allowed, no imposed symmetry or contact-normality assumption. Restricted
regularity, Stein and free-boundary variants must be named separately.

## Decision context and evidence plan

The agenda selected this node before the session. Alternatives are an immediate
proof survey, kernel validation or Contact V2 development. Specification has
priority because each alternative depends on which domain it claims to cover.

Deliver one inspectable specification, an implementation-to-domain comparison,
and a next bounded research target. Stop once the broad target, three bounded
variants and outcome semantics are explicit; no discovery run or solver edit.

Read the research backbone/registry and relevant map/request/search interfaces.
Consult primary sources for terminology. Treat local AI-authored TeX as source
claims. Check edge cases: point-only boundary contacts, reflected copies,
abstract versus geometric symmetry and formal versus geometric feasibility.

## Reproduction

- Starting revision: `3b196e30483b024cbc0d5dc8d6ce4f3de763c356`.
- Working tree: clean at start; this iteration edits research documentation.
- Method: source inspection and mathematical specification; no random seed,
  experiment runtime or hardware-sensitive performance claim.
- Sources: KLV, arXiv:1910.03836v1, introduction; Basu, arXiv:1409.1534,
  quantifier elimination survey. Exact links will be listed in the deliverable.
- Independent review: pending; this session cannot certify its own new claims
  as independently audited mathematics.

## Results

Deliverable: [PROBLEM_SPEC.md](../PROBLEM_SPEC.md), version 1.

- Defined a common Jordan-region disk problem and separated `NT_center` from
  the stronger `STEIN` predicate. The former has published positive examples;
  it is not a globally unresolved existence question.
- Specified F1 bounded formal feasibility, F2 exact semialgebraic template
  placement/synthesis, and F3 numerical realization with separate assembly
  outcomes. Finite description, finite discrete enumeration and a finite
  computational budget now have distinct meanings.
- Traced representation restrictions in `maps/base.py`,
  `graph_lab/space.py`, `graph_lab/search_request.py`, Contact V2 and geometry.
  In particular, simple planar 3-connected graphs are the generator's domain,
  not an established necessary condition for all target tilings.
- Edge-case check: two half-disks are a valid complete disk tiling but their
  augmented simple graph fails 3-connectivity. This refutes necessity for all
  disk tilings only; it does not exhibit a missing nontrivial witness.
- Source checks: KLV introduction/Theorem 1.1 (arXiv:1910.03836v1);
  Basu survey sections 1.2/2.1 (author-hosted 2014 manuscript). Sources and
  formula dependencies are linked in the specification. No claim about the
  current open-problem frontier has been made from these older papers.
- No solver changes, search runs, timing experiments or new unit tests.
  Documentation was checked for whitespace and local-link integrity.

## Interpretation

The hypothesis is supported as a documentation/analysis result: existing assets
were sufficient to define the domains and expose coverage obligations without
a refactor. This is not evidence that the current implementation decides F1,
implements F2, or has complete geometric validation. The semialgebraic
formulation is a proposed contract with a template-topology premise; it is not
a new implemented algorithm. Its mathematical review remains pending.

The chosen default nontriviality predicate is a working programme convention,
not a claim that every all-center tiling is geometrically uninteresting.
An explicit different user objective can revise it without changing the
underlying tiling equations.

## Return to parent

- Effect on `R0`: separates discovery, stronger Stein existence, validation and
  representation coverage so that the next study can select a precise target.
- Next selected node: `MATH-001`. First deliverable: a current primary-source
  map of constructions and obstructions for the two predicates, with exact
  hypotheses, followed by selection of one high-consequence proof audit.
- Alternative next step: `VALID-001` can reconstruct a known 12-tile disk
  witness if validation becomes the immediate blocker. No positive witness
  was injected into discovery during this study.
- `AGENDA.md`, `HISTORY.md`, `STATE.md` and the backbone were updated. No existing
  theorem's proof-review status was promoted in `MATHEMATICAL_RESULTS.md`.

Subsequent correction (`D-010`): the known-shape/placement validation proposal
mentioned above was withdrawn. Read [ROADMAP.md](../ROADMAP.md) and the current
agenda for priorities; this historical return-to-parent section does not select
a new implementation task.
