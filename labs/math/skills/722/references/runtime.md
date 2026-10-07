# Runtime and durable research record

From the OpenLabs code root run Python commands under `bin/openlabs-resource-guard --` (or the
math resource guard when the active workspace requires it). The code-root-relative helper is
`labs/math/skills/722/scripts/discovery.py`.

Create an isolated, inactive project specification from a JSON statement card:

```bash
bin/openlabs-resource-guard -- python3 labs/math/skills/722/scripts/discovery.py init \
  --root /absolute/isolated/project --project-id discovery-trial --statement /absolute/card.json
```

The card is an object with nonempty strings `source`, `source_statement`, `target_statement`,
`target_relation` (one of `exact`, `specialization`, `strengthening`), `known_frontier`,
`remaining_gap`, `success_criterion`, and `boundary_tests` (a nonempty string array).
An exact target must have the identical source and target statement. Check sources at intake;
the helper freezes the supplied text but does not judge mathematics or web status.

The generated project uses protocol `math-discovery` and profile `math-discovery-v1`. It must be
explicitly admitted by the existing project controller before scheduling. The helper neither writes
the database nor enables a timer. Configure effective model/effort through the controller's runner
profile, not through invented state-machine task fields. No global Codex configuration is changed.

The existing state-machine CLI controls `observe`, `transition`, `pause`, `resume`, and `status`:

```bash
bin/openlabs-resource-guard -- python3 labs/math/protocols/research_state_machine.py status \
  --project /absolute/project/project.json \
  --workstream /absolute/project/workstreams/discovery/research_state.json
```

Read the returned stage and bound policy. Create evidence before observing it; use the scheduler's
real task ID and role. `statement_checked` unlocks representation exploration without a proved
bridge. `progress_established` must describe an actual new mechanism, proved fact, refuted lemma,
or eliminated parameter loss. `candidate_ready` requires a frozen ordinary-language proof.
The reviewer boundary requires `reconstruction_passed` from a fresh reviewer before a terminal
result. A failed audit freezes this allocation; repair can be a new, explicitly allocated workstream
that refers to its preserved ledger. Never rewrite a failed audit or silently enlarge a budget.

Append one checkpoint from JSON:

```bash
bin/openlabs-resource-guard -- python3 labs/math/skills/722/scripts/discovery.py checkpoint \
  --ledger /absolute/project/workstreams/discovery/discovery-ledger.json --entry /absolute/entry.json
```

An entry contains `id`, `source_task_id`, `mechanism`, `new_evidence`, `remaining_gap`,
`next_test`, `losses` (string array), `evidence` (nonempty workstream-relative path array),
`disposition` (`continue`, `blocked`, `candidate`, `refuted`), and `usage`:

```json
{"model":"effective-model-id", "reasoning_effort":"max", "mode":"unknown",
 "agent_seconds":1200, "input_tokens":null, "output_tokens":null,
 "reasoning_tokens":null, "cost":null, "measurement_source":"scheduler receipt"}
```

Usage is per-checkpoint interval, not a cumulative value. Provide measured token/cost values only
when available; zeros mean measured zero, null means unknown. Aggregates remain unknown if any
interval is missing that metric. Reasoning tokens may be a subset of output tokens: do not add them
again. Usage recording is provenance, not a substitute for controller-authenticated allocation.
The scheduler enforces stage Agent-time and task ceilings; raw token or currency ceilings are not
enforced by this experimental ledger. No compute is labeled Pro-equivalent.

Every entry stores evidence hashes and a previous-entry hash. The protocol checks the frozen card,
chain and artifacts; at commit it also requires the canonical ledger to remain a prefix and binds
new checkpoints to the real task. This detects rewrites of previous attempts, not mathematical
invalidity. Keep artifact bulk outside the ledger, using declared artifact references as usual.

Validate and inspect:

```bash
bin/openlabs-resource-guard -- python3 labs/math/skills/722/scripts/discovery.py status \
  --ledger /absolute/project/workstreams/discovery/discovery-ledger.json
bin/openlabs-resource-guard -- python3 labs/math/protocols/discovery_math_protocol.py validate \
  --project /absolute/project/project.json \
  --workstream /absolute/project/workstreams/discovery/research_state.json --mode commit
```

Default allocations are 30-minute intake, up to two 2-hour representation attempts, up to three
4-hour mechanism attempts, and up to two 2-hour fresh-review attempts. Exhaustion defers for a
controller decision; it does not fabricate a theorem, a refutation or permanent abandonment.
The caller may select administrator-owned overrides before initialization. The allocated times
are scheduling windows, not the unpublished OpenAI model's three-hour compute estimate.
