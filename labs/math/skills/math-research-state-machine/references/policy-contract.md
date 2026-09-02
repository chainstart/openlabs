# Policy and state contract

The project points `domain_config.path` to an
`openlabs.math_research_policy_binding.v1` object. A binding selects either an installed profile or
an inline policy and may recursively override configured fields. Arrays are replaced, while objects
are merged. The workstream's `policy_digest` binds it to the exact resolved policy; changing a
profile or override requires an explicit state migration rather than silent reinterpretation.

For a compatible administrator edit that keeps the same `policy_id` and existing stage
graph/history valid, run `rebind-policy` outside a research attempt with the exact old digest and a
reason. The command validates the entire state against the newly resolved policy before atomically
recording the digest change. A research agent must not modify its staged binding or self-authorize
more allocation; the commit gate rejects changed project inputs. A different policy id or
incompatible graph requires a separately reviewed migration; never replace the digest by hand.

Installed profiles live under `labs/math/policies/`. They are optional configurations, not global
math-lab rules. `open-problem-closure-v1` selectively unlocks deep resources for original-problem
closure. `publishable-intermediates-v1` demonstrates a different broad-exploration objective.

Locate the CLI from the repository root:

```bash
python3 labs/math/protocols/research_state_machine.py status \
  --project "$PROJECT_CONFIG" --workstream "$WORKSTREAM_STATE"

python3 labs/math/protocols/research_state_machine.py validate \
  --project "$PROJECT_CONFIG" --workstream "$WORKSTREAM_STATE" --mode commit
```

Record one evidence-bound observation:

```bash
python3 labs/math/protocols/research_state_machine.py observe \
  --project "$PROJECT_CONFIG" --workstream "$WORKSTREAM_STATE" \
  --observation-id stable-id --kind configured-kind --verdict accepted \
  --actor-role researcher --source-task-id <task-id-from-task-file> \
  --summary "Exact factual finding" \
  --evidence evidence/proof.md
```

Request a configured transition using only the observations that should discharge its gate:

```bash
python3 labs/math/protocols/research_state_machine.py transition \
  --project "$PROJECT_CONFIG" --workstream "$WORKSTREAM_STATE" \
  --to configured-next-stage --reason "Why this allocation is now justified" \
  --observation stable-id
```

Repeat `--evidence` and `--observation` for multiple entries. Evidence paths are relative to the
workstream and must exist before the command runs. A condition may require a particular actor role,
which is normally paired with a fresh-session task envelope by the policy. At attempt commit, the
validator compares the staged state with the canonical prefix and binds every newly appended
observation to the scheduler-authenticated task id, role, and session boundary. Re-labeling the
current task as an independent reviewer, rewriting history, or crossing a configured fresh boundary
inside one task is rejected.

The reserved `original_problem_closed` and `counterexample_closed` observations have an additional
hard gate. They cannot cite an ordinary proof note alone. Supply a workstream-relative AMRA v2
campaign already at a fully validated exact-statement promotion and a new receipt path:

```bash
python3 labs/math/protocols/research_state_machine.py observe \
  ... --kind original_problem_closed \
  --amra-campaign amra/exact-source-campaign \
  --closure-receipt evidence/exact-source-closure.json
```

The command creates the structured receipt and registers it in `verification_receipts`. Every later
state validation reruns the complete AMRA promotion gate and checks the receipt, frozen statement
identity, core campaign artifacts, cited evidence hashes, and receipt SHA-256. A non-exact AMRA
target, an incomplete audit, a changed proof file, or a hand-written evidence text fails closed.
The reviewer result must be a successful, fresh control-plane review bound to the frozen AMRA
review-manifest hash. The AMRA decision and reviewer result must also agree on resolution polarity:
`proof` for `original_problem_closed`, or `counterexample` for `counterexample_closed`; one cannot
be relabeled as the other.

If the current route or target no longer warrants automatic allocation, stop it explicitly:

```bash
python3 labs/math/protocols/research_state_machine.py pause \
  --project "$PROJECT_CONFIG" --workstream "$WORKSTREAM_STATE" \
  --reason "Evidence-based stopping decision"
```

A paused nonterminal workstream may be resumed only through the matching `resume` command with a
durable reason, normally after an explicit project decision, changed policy allocation, or material
new evidence. Terminal stages require a reviewed migration rather than `resume`.

The scheduler counts actual task attempts and Agent-time by the opaque routing key returned by the
math hook. It also supplies active workstream summaries so a policy can cap concurrent tasks at a
stage. A capacity wait returns `defer` and does not alter mathematical state. The scheduler clamps
every requested task to factory-wide safety limits. Reaching a configured stage budget defers,
pauses, or delegates to the default scheduler exactly as the selected policy states; the supplied
profiles use `defer` so reauthorization is possible without fabricating a mathematical verdict.
