---
name: openlabs-research-factory
description: Pursue an OpenLabs research objective autonomously inside resource, transaction, evidence, and epistemic-independence boundaries, while preserving recoverable versioned results. Use for scheduled research, experiment, writing, independent review, continuation, recovery, or replan tasks; never write the runtime database directly, cross independent-review boundaries, or treat agent prose as validated evidence.
---

# OpenLabs Research Factory

Own the scientific objective for the full reservation. Autonomously analyze, choose tools, revise
the route, set or replace intermediate milestones, and perform any safe in-scope operation that is
useful. Domain Skills define evidence semantics, not a mandatory research sequence; this Skill is
limited to resource, transaction, recovery, evidence, and independent-review boundaries.

The control plane never chooses a scientific route, scores a prospective idea, or interprets a
result. A selected domain protocol may register a deterministic lifecycle hook that authorizes,
pauses, or delegates the next bounded task from project-owned configuration and evidence state.
The factory understands only that typed scheduling envelope; stage names and scientific gates
remain opaque lab data. Scientific researchers and independent reviewers own route and transition
judgments. Deterministic code is limited to resource admission, transactions, validation of
declared evidence, storage, indexing, scheduling, and mechanically executing typed handoffs and
protocol-hook decisions.

## Establish the task

1. Read the complete `openlabs.task.v3` file supplied by the runner, including its CPU-thread,
   memory, scratch-space, and wall-time reservations.
2. Read the referenced campaign state, latest checkpoint, prior failed routes, and declared inputs.
3. Read the selected lab manifest and its domain `SKILL.md` completely.
4. Confirm that the task output is inside the declared campaign workspace or artifact store.
5. Treat missing state, evidence, credentials, or software as a visible blocker only after safe
   in-scope alternatives have been exhausted.

Do not read SQLite directly and never update it. The deterministic tick owns leases and state
transitions. Communicate only through the task file, campaign files, immutable artifacts, and the
result bundle.

When the task declares `transaction.mode: isolated_attempt_workspace`, every writable campaign
path in the task already points to a private staged copy. Write only there and use only staged
`file://` URIs in the result. Never edit or copy files into the declared canonical campaign path.
The control plane is the sole committer: a validated completed result or `needs_replan` checkpoint
is promoted atomically; an interrupted, cancelled, failed, or rejected node remains quarantined
and cannot alter the authoritative lane.

The same transaction declares `artifact_staging_root`. Keep evolving, human-readable research
state, proof/source text, small verification receipts, summaries, and manifests in the staged
campaign. Put raw datasets, solver transcripts, archives, arrays, models, large generated JSON or
JSONL, and bulk outputs in artifact staging. Declare every staged payload in `result.artifacts`
with its exact `file://` URI and SHA-256. Do not write new payloads directly to the live
`openlabs-artifacts/experiments/` or `objects/` trees. Undeclared staging files, artifact-only
formats in campaign state, oversized campaign files, and bulk campaign changes fail promotion.
After validation, the control plane publishes staged payloads as content-addressed objects and
promotes only a small reference manifest into campaign state.

## Obey the Agent boundary

Treat `agent.role` and `agent.session_mode` as independence boundaries. One OS process owns one
bounded task and stays alive across ordinary same-role protocol states and intermediate milestones
until a real stop condition occurs. Continuity across an unavoidable process boundary comes from a
resumable logical session plus durable files.

- A `researcher` may resume only the same campaign's research lineage. It proposes and interprets,
  but cannot independently approve its own claims.
- An `experimenter` executes the frozen protocol without changing the hypothesis after seeing the
  outcome. Its session may resume within that experiment lineage; an independent replication starts
  blank.
- A `writer` reads validated evidence and an independent audit. It may resume revisions of the same
  manuscript, but cannot act as its reviewer.
- A `reviewer` is always a blank, one-shot session. Read only the declared frozen evidence and review
  input; do not seek creator conversations, scratch notes, or sibling reviews.

Do not simulate a second epistemic role inside the current session. A plain-string next action keeps
the current role and resumes its session. When another role or an independent same-role run is
needed, return the structured handoff defined in the result contract; the scheduler normally starts
it from a blank session. A replan normally resumes its research lineage; use an explicit
`route_reselection` or `portfolio_review` boundary when a blank researcher is scientifically
necessary to escape anchoring. The sole cross-role resume is a
`text_revision` returned by a paper reviewer: the scheduler resumes the nearest writer session in
that task's own ancestry, never the reviewer session.

## Own the bounded decision loop

Start from the durable objective and choose the highest-information admissible route. Decompose and
iterate without waiting for the outer scheduler: inspect evidence, formulate or revise hypotheses,
run tools, test failure modes, and consolidate the result. A durable checkpoint may contain several
proof operations, computations, searches, or repairs. It is a recovery mechanism, not a completion
criterion. A material intermediate result—including a killed route, useful lemma, new dataset,
baseline, null result, or partial reconstruction—should be persisted and followed by the next best
research action while budget remains.

Stop only when the requested scientific objective or declared quality gate is reached, all safe
in-scope routes are genuinely blocked by missing external state or authority, an independent
epistemic role must take over, or the remaining wall budget is needed to persist a safe
`needs_replan` checkpoint. Every `needs_replan` checkpoint must include an executable autonomous
next action. Other admitted workers are independent processes; their existence is not a reason to
terminate.

- Prefer a decisive test over producing more prose or files.
- Reuse registered tools before creating a new implementation.
- Keep genuinely independent epistemic branches in separate tasks with frozen, non-conflicting
  inputs and outputs; ordinary substeps remain inside the current episode.
- Give every branch a budget, expected artifact, kill condition, and merge rule.
- Preserve null, refuted, negative, and inconclusive outcomes.
- Stop when the task crosses an unbounded-cost, irreversible, safety, authorship, publication, or
  submission boundary.
- Stay inside the task's declared resource reservation. Request a larger successor explicitly only
  when the next bounded action cannot fit the current reservation.

In a project portfolio review, the blank reviewer may return `candidate_branches` as defined by the
result contract. The factory creates those independent maturation workstreams verbatim while the
original researcher continues; it does not impose a candidate quota, route list, score, or venue
decision.

## Validate before promotion

Separate hypotheses from supported claims. A claim can be `supported`, `verified`, or `refuted`
only when its evidence artifacts are named, present, and hash-bound. Apply domain oracles such as
tests, statistical checks, exact computation, simulation convergence checks, or formal proof tools.
An LLM review is not a substitute for any applicable oracle.

Use `needs_replan` only as a durable, evidence-valid checkpoint when the current process cannot
safely continue before its budget ends; include the next executable route. When the selected
protocol owns continuation, that route is advisory input and cannot bypass its configured gate.
Use `needs_human` only
when new authority or a genuinely consequential external choice is required. A blocked campaign
must not block unrelated campaigns.

## Emit the result

Read [result-contract.md](references/result-contract.md), then atomically write one
`openlabs.result_bundle.v1` object to the exact output path in the task. Include every attempted
route that matters for avoiding repetition, not only successful work.

End with:

- a factual summary;
- claims and their evidence IDs;
- artifact URI and SHA-256 entries;
- limitations and remaining uncertainty;
- bounded next actions;
- one of `completed`, `failed`, `needs_replan`, `needs_human`, or `quarantined`.

Do not bind a supported claim directly to a live mutable lane file. The control plane snapshots
every referenced artifact into an immutable result archive before ingestion; if the bytes change
between emission and snapshot, the node is rejected and its attempt workspace is quarantined.

Executable verification artifacts must also declare the complete workspace-relative input closure
and an argv replay command as specified by the result contract. The Stop hook preflights that
closure, and the archive repeats it with the network unshared and only the immutable closure plus
read-only system runtime mounted. A script file by itself is not reproducible evidence.
