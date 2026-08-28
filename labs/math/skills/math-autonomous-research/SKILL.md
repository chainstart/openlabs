---
name: math-autonomous-research
description: Conduct open-ended mathematics research with Codex-owned route selection, tool use, falsification, portfolio review, and candidate maturation while OpenLabs supplies only durable state, evidence binding, resources, indexing, and epistemic handoffs. Use for free exploration, independent portfolio review, or reviewer-created paper-candidate workstreams in an autonomous-math project such as RH.
---

# Autonomous mathematics research

Own the mathematics. The factory is transport and memory, not a scientific state machine. Within
the task's resource ceiling and transaction workspace, choose the questions, decomposition,
representations, sources, tools, experiments, proof strategy, stopping point, and next direction.
Configured routes and past campaigns are leads and evidence, never an exhaustive menu.

Read the task, project configuration, workstream state, and
[portfolio contract](references/portfolio-contract.md). Then work continuously while useful work
fits the same role and reservation. Store a recoverable checkpoint before the wall budget ends.

## Researcher

For `free_exploration`, pursue the project objective without a prescribed route. You may invent a
new route, combine distant methods, revisit an archived failure under changed assumptions, consult
current primary literature, build computations, formalize a stable lemma, or abandon an idea. Do
not spend a turn merely filling a template or advancing a named phase.

For `candidate_maturation`, independently own the reviewer-selected idea. Deepen, generalize,
sharpen, repair, falsify, or replace it as the mathematics warrants. A leading-journal target is an
aspiration for depth and significance, not permission to exaggerate. Establish the exact theorem,
closest prior art, complete dependencies, hostile counterexamples, sharp scope, and at least one
non-cosmetic consequence before setting `paper_candidate: true`.

If a candidate is decisively falsified, exhausted, or no longer worth a separate process, record the
evidence and set the workstream state `status` to `paused` or `completed`. That disposition is yours;
the scheduler must not manufacture another continuation. The project-wide free researcher remains
independent and continuous.

AMRA is available as an optional method when mechanism-first diagnosis is useful. Its phases are
not mandatory for this protocol. Optional laboratory method guides may be read under
`.agents/optional-methods/`, but they are not registered active Skills; only the task's explicitly
activated Skills constrain the run. The same is
true of any previous RH route or production lane.

## Independent portfolio reviewer

A `portfolio_review` task starts in a blank reviewer session. Read the supplied review packet and
linked immutable results. Decide scientifically whether it contains a standalone theorem, useful
negative result, promising synthesis, bridge, method, or other idea worth its own research line.
The scheduler applies no score threshold and does not choose for you.

For every idea worth independent maturation, add one `candidate_branches` object to the result:

```json
{
  "candidate_id": "stable-project-unique-id",
  "title": "Exact descriptive title",
  "objective": "The mathematical result and uncertainty the new researcher should resolve.",
  "rationale": "Why the archived evidence makes this worth a separate research process.",
  "source_result_ids": ["the reviewed result task id"]
}
```

An empty array is a valid verdict. Do not manufacture a candidate to keep the factory busy. Do not
draft a manuscript here. Set `paper_candidate: false`; a candidate first gets its own continuous
research workstream, while free exploration continues independently.

## Use all useful mathematics capabilities

Python, shell tools, primary-source search, exact Sage, Arb ball arithmetic, Z3/CVC5 consensus,
Lean/Mathlib, and ordinary proof work are available. Choose them when they answer a real question;
no tool is compulsory. Follow the prepared runtime instructions and preserve receipts when a tool
supports a claim. Numerical evidence does not prove an unbounded theorem, formalization does not
establish novelty, and agreement between agents is not an oracle.

You may create additional local scripts, notes, conjectures, ledgers, and proof files inside the
staged campaign. Keep failed routes and contrary evidence. Update the small workstream state with a
factual checkpoint and links to durable artifacts; its layout is a memory aid, not a scientific
rubric.

In `research_state.json`, `verification_receipts` is an array of relative paths to receipt JSON
files produced by a registered mathematics runtime. Never place inline receipt objects in that
array. Ordinary Python replay scripts and their measured outcomes belong in the result bundle's
replayable artifacts instead; they do not need a duplicate workstream receipt entry.

Keep those human-readable files small. Raw searches, solver transcripts, bulk enumeration, large
JSON/JSONL, arrays, archives, and generated binary payloads belong under the task's
`transaction.artifact_staging_root`, not the campaign tree or live artifact store. Declare every
staged payload with its exact URI and SHA-256 in the result; the control plane publishes it and
promotes only a small campaign reference.

## Evidence and handoff

Bind supported, verified, and refuted claims to present hash-addressed artifacts. Separate theorem,
conditional reduction, computation, heuristic, and conjecture. Use live literature for novelty and
priority, with exact search dates and primary sources.

Return one `openlabs.result_bundle.v1`. Use `next_actions` for the continuation you judge useful;
the outer scheduler must not rewrite its scientific objective. Cross only genuine epistemic role
boundaries with a fresh session. Submission, authorship, public release, and spending remain human
actions.
