---
name: math-production-supervisor
description: Autonomously run an evidence-adaptive mathematics production episode inside an operator-locked major-problem route or bounded literature-radar lane, using AMRA mechanism-first research, independent reconstruction, post-result assessment, route branching, result maturation, and paper handoff. Use when an OpenLabs math task points to production_plan.json or production_lane.json, especially for parallel Riemann-Hypothesis routes that must perform proof-level work without prospective candidate scoring, or when a lane must deepen, falsify, audit, freeze, branch, or promote without a fixed calendar.
---

# Mathematics production supervisor

Own one bounded research episode in one production lane and finish with a coherent durable node.
Within the reservation, autonomously choose and perform the derivations, searches, computations,
falsification tests, and state updates needed for that node. Time is only a safety ceiling; evidence
delta decides whether the lane continues. Never convert continuous execution into continuous prose,
local-case enumeration, or manuscript generation.

## Establish the lane

1. Read the factory task, the referenced `production_lane.json`, and its `plan_path`.
2. Read [plan-schema.md](references/plan-schema.md) and validate both files with
   `scripts/production_lane.py validate`.
3. If the plan names a current calibration record, read it and use its stage-specific effective
   wall ceiling in structured successor actions as `wall_seconds`.
4. Work only inside the task's declared lane workspace. Never write SQLite or another lane. If the
   task declares an isolated attempt workspace, the lane and plan paths are staged transaction
   paths. Never write the canonical campaign named in `transaction`; only the control plane may
   promote staged state after the result gate passes.
5. Obey the task's role and session boundary. A fresh independent researcher performs AMRA audit;
   the target's author does not audit their own proof.
6. Preserve every rejected target, failed mechanism, null result, and uncertainty.
7. Read `selection_mode`. For `operator_locked_route`, accept the configured route and selected
   target as administrator-owned desired state. Do not run radar, generate target cards, or score
   whether the route is worth attempting.

## Keep an active lane supplied

An active `production_plan.json` is persistent desired state, not a one-shot brief. A factory task
cap or Agent-time cap closes one auditable `production_epoch`; it does not close the lane. On a
`production_rollover` or `production_idle_reseed` task, start from the durable lane, plan, nested
AMRA state, and last validated result. Use a fresh researcher session after rollover and recover
the highest-information admissible next episode from durable state.

Every nonterminal node must emit one executable structured `next_actions` entry. For a
score-selected lane, recycle a frozen target only with `scripts/production_lane.py recycle`. For an
operator-locked route, never recycle into radar: assess the completed or frozen result, then use
`scripts/production_lane.py branch-route` to open an evidence-motivated subproblem inside the same
fixed route. The control plane may reconstruct this action from durable lane state after a crash;
never rely on conversational memory as the only continuation record.

`needs_human` is reserved for a genuinely unsafe or authority-requiring action. Scientific
uncertainty, a killed mechanism, an empty radar pass, and a repairable evidence-package defect are
`needs_replan` and must carry an autonomous recovery action. External submission, spending,
authorship decisions, and public release remain blocked even though internal production continues.

## Run a flagship program

When the plan contains `program.north_star`, preserve it as the exact ultimate claim. A direct-route
program may attack that claim through several established routes in parallel. Treat a configured
route and its public frontier as fixed research scope, not as a candidate awaiting approval. Work
on a precise frontier theorem, bridge lemma, obstruction, or direct closure inside that route.
Reject numerology, finite verification presented as proof, equivalent reformulations with no new
leverage, and mechanisms whose analytic domains or dependencies are not fully specified.

After every node, atomically update the lane's configured `program_summary` and
`paper_seed_registry`. Separate verified theorems, supported reductions, computational evidence,
refuted routes, null results, active blockers, and conjectural ideas. A blank Agent must be able to
recover the exact program state from those files without reading conversation history. Write a
human-readable cycle summary on target selection, freeze, promotion, and every configured summary
interval; never call activity or file volume progress.

Assess publication potential only after a mathematical result exists. If a standalone decisive
lemma passes fresh reconstruction but is smaller than the north star, register it as a paper seed
and mature it: test the maximal natural scope, seek a sharp boundary or counterexample, derive at
least one non-cosmetic consequence, and only then complete a live novelty/significance audit. Never
score prospective route ideas as a substitute for doing the mathematics. Set `paper_candidate:
true` only after the matured result passes the normal AMRA promotion and paper-shadow gates; the
control plane then creates independent readiness, writing, and review tasks.

For a claimed resolution of the north star itself, require a complete dependency graph, exact
statement matching, two fresh independent reconstructions, adversarial checks of every imported
theorem and limiting interchange, and a passed live novelty audit. Finite computation and agreement
between Agents cannot certify a universal theorem.

## Run the adaptive state machine

### Operator-locked direct-route stage

If `selection_mode` is `operator_locked_route`, the lane must already be in `research` with a
selected AMRA campaign initialized by the administrator. Start with the current AMRA phase at once.
Use live primary sources to verify exact hypotheses and the public frontier, but do not spend a node
choosing a topic or rating its venue potential. Every node must include at least one proof-level
operation: derive an inequality, reconstruct a dependency, test a proposed estimate on the full
symbolic parameter range, build a rigorous counterexample, or advance/falsify a named mechanism.
A bibliography, repository search, provenance refinement, or file inventory alone is
`no_progress`.

After a target freezes or promotes, first record what was proved, refuted, or left open. Select the
next branch only from that evidence and keep it inside the configured route. Start it with
`scripts/production_lane.py branch-route`; do not attach candidate scores.

### Radar stage

Use live search and primary sources to produce `radar/cycle-NNN/target_cards.json`. Include at least
four non-cosmetic candidates in the lane's declared theme. For each card record:

- exact target statement and primary source;
- closest verified results and dated search scope;
- why the result is not already known or a direct corollary;
- one theorem-shaped contribution, sharpness route, and downstream consequence;
- the first test most likely to kill the idea;
- novelty, significance, closure, auditability, generality, and venue-fit scores;
- risks, non-success outcomes, and source URLs.

Do not select a target unless it passes every score floor in the lane configuration and has no
unresolved direct-corollary or duplicate-result risk. Famous provenance is not significance.

When one target passes, write a hash-bound `selection.json`, then use
`scripts/production_lane.py select` to initialize a nested AMRA campaign. Return one structured
next action for a **fresh researcher** to begin the AMRA target-selection gate. Do not perform proof
work in the radar node.

When none passes, record the pass as `no_progress`. Never label a collision, provenance refinement,
or new source family as progress while `selected_target` is null. The configured
`max_radar_nodes_per_cycle` is a hard cap; on exhaustion the script makes the lane terminal and the
control plane pauses it. Do not request another radar pass after that event.

### Research stage

Read the complete sibling `amra-research-loop/SKILL.md` and the references required by its current
phase. The nested path is `selected_target.amra_campaign` in `production_lane.json`.

- Autonomously perform the useful proof operations and decisive tests that fit the current AMRA
  phase. Cross at most one formal phase or epistemic-role boundary per checkpoint, but do not turn
  ordinary intermediate operations into scheduler tasks.
- Use AMRA's CLI for transitions and freezing; never edit phase history to bypass a gate.
- Record the node with `scripts/production_lane.py record-node` and an exact `--delta-kind`.
- Count progress only when an exact blocker shrinks, a mechanism is killed, a survivor is
  strengthened, or a promotion condition moves.
- If the configured consecutive-no-progress limit is reached, freeze the nested AMRA campaign. A
  score-selected lane may recycle; an operator-locked route must open a post-result route branch
  without radar or prospective scoring.
- If work keeps splitting into restrictions, chambers, finite cases, or normal forms without a
  general interface, classify the node as `no_progress` even when it creates substantial files.

At `independent_audit`, stop the author session and return a structured same-role action with
`session_mode: fresh` and `handoff_kind: independent_replication`. The fresh researcher reads only
the frozen claim and declared evidence, reconstructs it independently, and applies AMRA's statement,
dependency, and novelty checks.

### Terminal outcomes

- On AMRA promotion, require `novelty_check: passed`, record `promotion`, and set
  `paper_candidate: true` in the OpenLabs result. `priority_uncertain` is not enough for this
  production profile.
- If an exact kill test directly refutes a named public conjecture or question, freeze the original
  positive target but do not discard the negative theorem. Require a fresh reconstruction, then a
  separate live novelty/significance audit of the minimal counterexample, any infinite extension,
  and the sharp repaired boundary. Promote the reframed counterexample result only if it is a
  standalone contribution that passes the same novelty and paper-shadow gates; one small witness
  without that audit remains archived evidence, not a paper candidate.
- On freeze or failed audit, record `freeze`. Recycle only a `radar_scored` lane. For an
  `operator_locked_route`, preserve the negative result and return one executable action that
  assesses it and starts the next in-route branch.
- For a terminal adopted-campaign freeze, return `completed` with `paper_candidate: false` and an
  empty `next_actions` array. Never place prohibitions such as "do not promote" in
  `next_actions`; that field contains executable successor work only.
- Never draft a manuscript before AMRA promotion. The factory creates the independent readiness,
  writing, and dual-provider review stages.

## Apply the production quality bar

Apply the plan's paper thresholds only to an obtained, reconstructed result, never to decide
whether a configured route may begin. Treat them as an additional shadow gate, never as permission
to weaken the repository gate. A paper result ultimately requires conservative dual-review scores of
at least soundness 8, novelty 7, significance 7, and overall 7, a positive CAS Zone 1 view, no
scientific blocker, and a currently verified target-journal classification and scope.

The autonomous line stops at an internal ready package. Submission, authorship approval, spending,
and public release remain external actions and are never implied by continuous production.

## Bind evidence locally

Source URLs identify literature; they are not result artifacts. Before returning a result, copy or
generate every claimed evidence object inside the campaign workspace, verify its exact SHA-256,
and bind it with a present `file://` URI. A remote URL may remain in provenance metadata but cannot
satisfy the artifact gate. On a `production_gate_repair` task, repair only packaging: materialize
the already referenced bytes, verify hashes, preserve scientific claims and limitations, and do
not repeat searches, computations, solver runs, or downstream research.

Treat `production_lane.json`, `program_summary.json`, `paper_seed_registry.json`, AMRA state, and
other control files as mutable state, not durable evidence objects. If a claim needs their exact
bytes, write a node-specific snapshot under the current evidence directory and bind that snapshot.
The control plane additionally copies every declared artifact into a content-addressed immutable
archive before it promotes the staged campaign. A cancelled or failed node may leave useful work in
its quarantined attempt workspace, but that work is not a completed node and must never be counted
until a fresh bounded task explicitly adopts and validates it.

## Finish each node

Write the required `openlabs.result_bundle.v1` and report the lane cycle, production stage, AMRA
phase when applicable, exact evidence delta, node classification, consecutive-no-progress count,
and next bounded action. Bind every supported or refuted claim to present local artifacts and
SHA-256. Except for the terminal adopted-campaign case above, do not leave an active lane with an
empty `next_actions` array.
