# Result contract

Write one JSON object with this minimum shape:

```json
{
  "schema_version": "openlabs.result_bundle.v1",
  "task_id": "task-id",
  "campaign_id": "campaign-id",
  "lab_id": "math",
  "domain": "math",
  "status": "completed",
  "summary": "Factual result without promotion language unsupported by the evidence.",
  "artifacts": [
    {
      "artifact_id": "decisive-test",
      "uri": "file:///absolute/runtime/path/result.json",
      "sha256": "64-lowercase-hex-characters",
      "kind": "test_result"
    }
  ],
  "claims": [
    {
      "claim_id": "bounded-claim",
      "text": "The exact bounded claim.",
      "status": "supported",
      "evidence": ["decisive-test"],
      "limitations": ["What the evidence does not establish."]
    }
  ],
  "next_actions": ["One bounded next action."],
  "paper_candidate": false
}
```

Every artifact whose `kind` is `verification_script`, `reproduction_script`,
`validator_script`, or another value ending in `_script` must add a replay declaration:

```json
{
  "artifact_id": "decisive-validator",
  "uri": "file:///attempt/campaign/evidence/node-007/verify.py",
  "sha256": "64-lowercase-hex-characters",
  "kind": "verification_script",
  "reproduction": {
    "command": ["python3", "{artifact}"],
    "inputs": [
      {
        "path": "evidence/node-007/frozen-input.json",
        "sha256": "64-lowercase-hex-characters"
      }
    ],
    "timeout_seconds": 120
  }
}
```

`inputs[].path` is relative to the staged campaign root, not to the script. List every non-system
file the command reads, including source extracts, state snapshots, data, helper modules, and
configuration. Use `{artifact}` for the archived workspace-relative script path and `{workspace}`
when an absolute closure root argument is required. The command is an argv array, never a shell
pipeline. The hook and immutable archiver each rebuild only this declared closure and replay it in
a network-unshared sandbox. Missing inputs, hash drift, undeclared live-state reads, timeouts, and
nonzero exits make the artifact non-reproducible and block promotion. All executable-artifact
timeouts in one result must total at most 300 seconds; `.py` and `.sh` artifacts are treated as
executable even when their `kind` was mislabeled.

Allowed claim statuses are `hypothesis`, `unsupported`, `supported`, `verified`, and `refuted`.
Use `verified` only for an applicable independent deterministic or formal check, not because an
agent agreed. Every promoted or refuted claim requires at least one evidence artifact with a
SHA-256 digest.

A plain string continues the current role and resumes its logical session. To cross an epistemic
role boundary, or to start an independent run of the same role, use one structured action:

```json
{
  "objective": "Execute the frozen falsification protocol without changing the hypothesis.",
  "agent_role": "experimenter",
  "session_mode": "fresh",
  "handoff_kind": "role_handoff"
}
```

Allowed `handoff_kind` values are `role_handoff`, `independent_replication`, `text_revision`, and
`evidence_remediation`. An action may also include a complete `resources` object with positive
`cpu_threads`, `memory_mib`, and `scratch_mib` values.

Role changes and every `reviewer` handoff are normally forced to `fresh`. Initial writing is created
only by the paper-readiness gate; a research result cannot hand itself directly to a new writer.
A `paper_review` reviewer has two safe failure routes:

```json
{
  "objective": "Correct the stated limitation without changing the supported claim.",
  "agent_role": "writer",
  "session_mode": "resume",
  "handoff_kind": "text_revision"
}
```

This resumes only the closest writer session in the current task ancestry. If new scientific
evidence is required, return `evidence_remediation` to a fresh `researcher` or `experimenter`.
After that bounded evidence task completes, the scheduler returns to the ancestral writer; if no
writer exists yet, it repeats the independent paper-readiness audit.
