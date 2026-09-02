# Production plan and lane contract

## Production plan

`production_plan.json` is administrator-owned policy. Required fields:

- `schema_version`: `openlabs.math_production_plan.v1`;
- `plan_id`, `status`, `objective`;
- `autonomy`, `scheduler`, `portfolio`, `selection_gate`, `paper_shadow_gate`;
- `lanes`: lane identifiers and paths relative to the plan;
- `observation_policy`: evidence-triggered recalibration rules.

Agents may read the plan but must not silently change its score floors, WIP limits, external-action
policy, or resource ceilings.

For a `radar_scored` plan, `selection_gate.minimum_target_cards_per_cycle` is mapped to the lane's
canonical `minimum_target_cards`, and
`selection_gate.minimum_distinct_research_fronts_per_cycle` is mapped to
`minimum_distinct_research_fronts`. Plan minima are authoritative: a lane may strengthen them but
cannot weaken them. The effective snapshot always requires at least four cards and one named
research front. A selected target also freezes the SHA-256 of the exact production-plan bytes.

`status: active` is a control-plane continuity contract. Each lane whose `startup` is `active` is
bound to a renewable production epoch. The factory retains lifetime tasks, evidence, and Agent-time
accounting, but renews the bounded task/time safety window when an idle lane exhausts the current
epoch. Plan activation and retirement are administrator-owned state; an Agent must not change
them.

### Optional flagship program

A long-horizon plan may include a `program` object with:

- `north_star`: exact statement, authoritative source, and current public status;
- `research_fronts`: admissible families of intermediate targets;
- `invalid_progress`: routes that cannot count as progress;
- `summary_policy`: paths and events for structured and human-readable summaries;
- `seed_maturation`: the trigger, expansion requirements, and promotion contract for a standalone
  intermediate result;
- `north_star_claim_gate`: additional reconstruction and dependency checks for a claimed solution.
- `theorem_target_policy`: hard budgets for nodes without theorem progress, total research nodes per
  target, and consecutive frozen branches without promotion.

In a score-selected plan, the north star directs radar but is not automatically the AMRA target.
Every intermediate target must name a verifiable bridge to it. The configured `program_summary` and
`paper_seed_registry` are durable scientific records: update them atomically after every node and
preserve negative and null outcomes.

For `program.execution_mode: operator_locked_parallel_routes`, the administrator has already
chosen established routes and their public frontiers. Each lane uses
`selection_mode: operator_locked_route`, begins directly in `research`, and contains a score-free
`selected_target` initialized with `scripts/production_lane.py lock-route`. Target records preserve
`source_original_statement`, `frozen_target_statement`, and `target_relation`; only an `exact`
statement match can represent source-problem closure. Candidate radar and
prospective publication scoring are forbidden in this mode. Publication assessment occurs only
after a mathematical result has survived reconstruction.

A `radar_scored` lane may enter research through `select` only when `target_relation` is `exact`
and the source-original and frozen target statements match. Non-exact theorems belong to an
explicitly scoped operator route or `branch-route`, never to open-problem selection. During
research, lane validation requires all three target fields and checks them, together with `source`,
against the nested AMRA `closure_contract.json`; changing only one record fails closed.
The `selection.json` receipt uses `openlabs.math_target_selection.v1`. It freezes a primary-source
artifact and exact locator, public open status, the plan-required number of candidate cards and
distinct research fronts, score vector, selection-gate snapshot, closest-result/duplicate-search
evidence, and a cleared blocking-novelty risk. Every counted card must use `target_relation: exact`,
have matching normalized source-original and frozen statements, identify `open_problem` or
`open_conjecture` status, clear blocking novelty risk, and carry a complete bounded score vector
whose total is correct. The receipt and selected lane record bind the selected `research_front`,
effective canonical gate, and production-plan SHA-256; the nested AMRA campaign copies the
source-authority bundle inside its own evidence boundary.

## Production lane

`production_lane.json` is mutable lane state:

```json
{
  "schema_version": "openlabs.math_production_lane.v1",
  "plan_id": "math-q1-adaptive-r1",
  "lane_id": "math-q1-r1-example",
  "selection_mode": "radar_scored",
  "stage": "radar",
  "cycle": 1,
  "theme": {"name": "...", "include": [], "exclude": []},
  "plan_path": "../production/.../production_plan.json",
  "selection_gate": {
    "minimum_total": 75,
    "minimum_novelty": 18,
    "minimum_significance": 18,
    "minimum_closure": 12,
    "minimum_target_cards": 4,
    "minimum_distinct_research_fronts": 1
  },
  "node_policy": {
    "consecutive_no_progress_limit": 3,
    "max_radar_nodes_per_cycle": 3,
    "max_nodes_without_theorem_delta": 8,
    "max_research_nodes_per_target": 12,
    "max_frozen_branches_without_promotion": 2
  },
  "selected_target": null,
  "archived_targets": [],
  "nodes": [],
  "history": []
}
```

Allowed stages are `radar`, `research`, and `terminal`. A selected target contains its exact
statement, source, score vector, frozen selection-gate snapshot, first kill test, and safe relative
nested AMRA campaign path. The path must equal `research/cycle-NNN/<slugged-target-id>` inside the
lane workspace, and nested campaign id, problem id, and title must match. Archived targets are
revalidated rather than trusted as inert history.

An operator-locked lane also contains a durable `route` object and uses
`selection_basis: operator_locked_route` instead of a score vector. After a target freezes or
promotes, `branch-route` may initialize the next evidence-driven subproblem in that same route with
`selection_basis: post_result_route_branch`; it never returns to candidate radar. A frozen target's
successor must retain the source-original statement and problem id, change the scoped target, and
record both `branch_amendment` and
`defect_addressed`. The default permits one such repair: after two consecutive frozen targets
without promotion, the route cannot branch again.

## Score contract

Use integer scores with these maxima:

- novelty 25;
- significance 25;
- closure 20;
- auditability 15;
- generality 10;
- venue fit 5.

The default selection gate requires total 75, novelty 18, significance 18, closure 12, and no
blocking novelty risk. Scoring is a triage decision, not mathematical evidence. It applies only to
`radar_scored` lanes and must not gate an operator-selected route.

## Evidence-adaptive timing

Wall time is a fail-safe, not a schedule. The initial node ceiling is normally one hour and the
factory hard ceiling is four hours. Recalibrate only after the configured number of completed
nodes, a promotion, a freeze, a repeated blocker, or a material resource observation.

The plan may name a hash-bound `current_calibration` record. Use its stage-specific
`effective_wall_seconds` in the structured successor action's optional `wall_seconds` field. A
calibrated ceiling is capped by the factory hard ceiling. Stages without three comparable samples
remain explicitly uncalibrated and retain their prior ceiling.

Classify a node at two levels:

- `progress`: one named epistemic blocker became strictly smaller;
- `no_progress`: activity occurred but no promotion-relevant uncertainty decreased;
- `promotion`: the frozen AMRA success condition passed independent audit;
- `freeze`: the target was terminated with its negative evidence preserved.

Then classify progress as:

- `search`: a blocker shrank, mechanism died, survivor strengthened, or a promotion gate moved;
- `theorem`: an exact standalone theorem/no-go statement was obtained, a hypothesis was removed, or
  a published frontier was strictly improved;
- `promotion`: a theorem delta survived fresh independent reconstruction.

Search progress preserves valuable negative information but does not reset the theorem-stall
counter. Eight research nodes without theorem progress, three consecutive `no_progress` nodes, or
twelve research nodes on one target normally force AMRA freeze. A theorem delta must include its
exact statement, scope, and non-cosmetic consequence, and immediately requires fresh independent
audit. An already obtained theorem may still be recorded at the budget boundary; it opens audit,
not further author-side search.
Direct refutation of a named public statement is also a freeze of that positive target, but its
counterexample may enter a fresh, separately audited negative-result track. It is not promoted from
the authoring session and does not inherit novelty approval from the original question.

An unselected radar pass is always `no_progress`. A source-family change, bibliographic collision,
or provenance improvement cannot reset this count. Reaching `max_radar_nodes_per_cycle` without a
selection makes the lane terminal; the control plane then pauses it instead of reseeding it.

For a `progress` node, `record-node` requires a semantic delta kind. Search kinds are
`blocker_reduced`, `mechanism_killed`, `survivor_strengthened`, and
`promotion_gate_advanced`. Theorem kinds are `theorem_statement_strengthened`,
`hypothesis_removed`, `public_frontier_improved`, and `standalone_no_go_closed`.
Literature-only and artifact-only activity do not satisfy this contract.

## Result and continuation contract

Each active-lane result must leave enough durable state for a blank process to continue:

- the updated lane and nested AMRA paths;
- the exact evidence delta and node classification;
- local `file://` artifact URIs plus SHA-256 for evidence-bearing objects;
- exactly one structured bounded next action, unless the task is the explicitly terminal adopted
  campaign described by the supervisor skill.

Literature URLs remain provenance only. A repairable missing/local-binding error is
`needs_replan`, not a reason to stop the production lane or redo the underlying science.
