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

In a score-selected plan, the north star directs radar but is not automatically the AMRA target.
Every intermediate target must name a verifiable bridge to it. The configured `program_summary` and
`paper_seed_registry` are durable scientific records: update them atomically after every node and
preserve negative and null outcomes.

For `program.execution_mode: operator_locked_parallel_routes`, the administrator has already
chosen established routes and their public frontiers. Each lane uses
`selection_mode: operator_locked_route`, begins directly in `research`, and contains a score-free
`selected_target` initialized with `scripts/production_lane.py lock-route`. Candidate radar and
prospective publication scoring are forbidden in this mode. Publication assessment occurs only
after a mathematical result has survived reconstruction.

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
  "selection_gate": {},
  "node_policy": {
    "consecutive_no_progress_limit": 3,
    "max_radar_nodes_per_cycle": 3
  },
  "selected_target": null,
  "archived_targets": [],
  "nodes": [],
  "history": []
}
```

Allowed stages are `radar`, `research`, and `terminal`. A selected target contains its exact
statement, source, score vector, first kill test, and relative nested AMRA campaign path.

An operator-locked lane also contains a durable `route` object and uses
`selection_basis: operator_locked_route` instead of a score vector. After a target freezes or
promotes, `branch-route` may initialize the next evidence-driven subproblem in that same route with
`selection_basis: post_result_route_branch`; it never returns to candidate radar.

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

Classify a node as:

- `progress`: one named epistemic blocker became strictly smaller;
- `no_progress`: activity occurred but no promotion-relevant uncertainty decreased;
- `promotion`: the frozen AMRA success condition passed independent audit;
- `freeze`: the target was terminated with its negative evidence preserved.

Three consecutive `no_progress` nodes normally force AMRA freeze and lane recycling.
Direct refutation of a named public statement is also a freeze of that positive target, but its
counterexample may enter a fresh, separately audited negative-result track. It is not promoted from
the authoring session and does not inherit novelty approval from the original question.

An unselected radar pass is always `no_progress`. A source-family change, bibliographic collision,
or provenance improvement cannot reset this count. Reaching `max_radar_nodes_per_cycle` without a
selection makes the lane terminal; the control plane then pauses it instead of reseeding it.

For a `progress` node, `record-node` requires a semantic delta kind: `blocker_reduced`,
`mechanism_killed`, `survivor_strengthened`, or `promotion_gate_advanced`. Literature-only and
artifact-only activity do not satisfy this contract.

## Result and continuation contract

Each active-lane result must leave enough durable state for a blank process to continue:

- the updated lane and nested AMRA paths;
- the exact evidence delta and node classification;
- local `file://` artifact URIs plus SHA-256 for evidence-bearing objects;
- exactly one structured bounded next action, unless the task is the explicitly terminal adopted
  campaign described by the supervisor skill.

Literature URLs remain provenance only. A repairable missing/local-binding error is
`needs_replan`, not a reason to stop the production lane or redo the underlying science.
