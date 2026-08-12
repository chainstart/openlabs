---
name: openlabs-research-factory
description: Coordinate a bounded, recoverable OpenLabs research episode by reading durable task and campaign state, autonomously decomposing the objective with the matching domain Skill, obeying epistemic-role and transaction boundaries, and emitting a versioned evidence-bound checkpoint. Use for scheduled research, experiment, writing, independent review, continuation, recovery, or replan tasks; never write the runtime database directly, cross role boundaries, or treat agent prose as validated evidence.
---

# OpenLabs Research Factory

Own one useful, checkpointed research episode. Autonomously analyze, choose tools, revise the route,
and perform as many intermediate operations as are useful within the reservation. Let the domain
Skill govern scientific method; keep this Skill focused on boundaries, recovery, and handoff.

## Establish the task

1. Read the complete `openlabs.task.v3` file supplied by the runner, including its CPU-thread,
   memory, scratch-space, and wall-time reservations.
2. Read the referenced campaign state, latest checkpoint, prior failed routes, and declared inputs.
3. Read the selected lab manifest and its domain `SKILL.md` completely.
4. Confirm that the task output is inside the declared campaign workspace or artifact store.
5. Treat missing state, evidence, credentials, software, or authority as a visible blocker.

Do not read SQLite directly and never update it. The deterministic tick owns leases and state
transitions. Communicate only through the task file, campaign files, immutable artifacts, and the
result bundle.

When the task declares `transaction.mode: isolated_attempt_workspace`, every writable campaign
path in the task already points to a private staged copy. Write only there and use only staged
`file://` URIs in the result. Never edit or copy files into the declared canonical campaign path.
The control plane is the sole committer: a validated completed node is promoted atomically; an
interrupted, cancelled, failed, or rejected node remains a quarantined checkpoint and cannot alter
the authoritative lane.

## Obey the Agent boundary

Treat `agent.role` and `agent.session_mode` as authority, not suggestions. One OS process performs
one bounded task and exits; continuity comes from a resumable logical session plus durable files.

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
it from a blank session. A replan also starts a blank researcher session, using the frozen failure
artifacts without inheriting the failed conversation's anchoring. The sole cross-role resume is a
`text_revision` returned by a paper reviewer: the scheduler resumes the nearest writer session in
that task's own ancestry, never the reviewer session.

## Own the bounded decision loop

Start from the durable objective and choose the highest-information admissible route. Decompose and
iterate without waiting for the outer scheduler: inspect evidence, formulate or revise hypotheses,
run tools, test failure modes, and consolidate the result. A checkpoint may contain several proof
operations, computations, searches, or repairs when they form one coherent evidence advance.

Stop the episode when it has produced a material evidence delta, decisively killed a route, reached
a genuine blocker, encountered a role/authority boundary, or needs to reserve time to persist a
recoverable checkpoint. Do not stop merely because one administrative substep or one file edit is
complete.

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

## Validate before promotion

Separate hypotheses from supported claims. A claim can be `supported`, `verified`, or `refuted`
only when its evidence artifacts are named, present, and hash-bound. Apply domain oracles such as
tests, statistical checks, exact computation, simulation convergence checks, or formal proof tools.
An LLM review is not a substitute for any applicable oracle.

Use `needs_replan` when a route failed but an autonomous alternative is available. Use
`needs_human` only when new authority or a genuinely consequential choice is required. A blocked
campaign must not block unrelated campaigns.

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
