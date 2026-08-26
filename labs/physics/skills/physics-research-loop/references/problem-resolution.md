# Physics problem-resolution decisions

OpenLabs uses two independent status layers:

- `latest_round.task_status` records what happened to one bounded Codex task.
- `problem_verdict` records whether the scoped scientific question is resolved.

A task may be `succeeded` and its round `completed` while `problem_verdict` remains `open`. This is the
expected outcome for a reproducibility blocker, a literature boundary audit, a benchmark reproduction,
an inconclusive computation or a useful classification that lacks a physical derivation.

The durable `resolution_decision.json` uses schema
`openlabs.physics_problem_resolution.v1`. Each resolution route states the verdict that follows if the
route is complete and lists atomic criteria with `met`, `not_met`, `inconclusive` or `blocked` status.
Every `met` criterion must cite a preserved evidence path or identifier. The deterministic validator
derives `open` unless every criterion in at least one route is `met`; prose confidence, solver success,
plots and task completion cannot override that derivation.

Use `solved_positive` for a constructive derivation or certified result, and `solved_negative` for the
explicit counterexample or no-go route already admitted by the frozen question. Use `superseded` only
when dated primary prior art fully answers the same scoped question, not merely a broader historical
prompt. Use `not_well_posed` only when a completed route demonstrates that no unique, falsifiable
question exists under the declared information and conventions.

Before closing a round:

1. update only criteria whose cited evidence was actually produced or independently checked;
2. apply the declared `all` or `any` round completion rule;
3. run `tools/problem_verdict.py resolution_decision.json`;
4. preserve an explicit rationale for why round completion does or does not change the problem verdict.
