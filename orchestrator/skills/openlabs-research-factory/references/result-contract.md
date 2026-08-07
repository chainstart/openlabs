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
  "session_mode": "fresh"
}
```

Role changes and every `reviewer` handoff are forced to `fresh`. Initial writing is created only by
the paper-readiness gate; a result cannot hand itself directly to a new writer.
