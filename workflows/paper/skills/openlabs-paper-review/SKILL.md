---
name: openlabs-paper-review
description: "Run the sole OpenLabs journal self-review: deterministic preflight, independent target-editor screen with actual rejection history, configured scientific referee, bibliography and core-mathematics verification, then a bound decision."
---

# OpenLabs unified paper review

Use `review unified-run` under the resource guard; this is the only route to
`writing_release: ready`. Models and the active referee panel come from
`registry/settings.yaml`. Claude remains disabled under the actual user instruction;
only the configured Codex referee B runs. A gate never authorizes journal submission.

```bash
bin/openlabs-resource-guard --task-type cpu -- env PYTHONPATH=workflows/paper python -m paper_writing \
  review unified-run --paper-id PID --root DATA_ROOT --response RESPONSE.md
```

Omit `--response` only for a first review. Do not manually construct decisions or
edit manuscript/registry/evidence during review. Preserve actual outputs and model
receipts, including failures. Revised prose remains neutral scientific writing;
keep internal review negotiation and claims about editor approval outside the paper.

## Current sequence (user instruction, 2026-10-12)

1. Deterministic preflight: clean build, source/style/declarations, support package,
   verified journal scope/ranking/fees/format. File integrity is preparation work.
2. Independent target-journal editor: contribution, closest prior work, readership,
   strongest desk-reject reason and actual available historical refusal letters.
3. Independent scientific referee: complete manuscript and supplementary arguments,
   novelty, significance for the target, correctness, experimental credibility,
   actual previous objections and required changes. Do not defer this judgment
   until a paragraph/quote audit passes.
The referee records actual unsupported main claims in `scientific_blockers` and
local prose/index repairs as typed changes. Its pre-verification diagnostic is
preserved; a diagnostic observation is not automatically a scientific defect.

4. If the scientific decision can advance, independent **bibliography and core
   mathematics** verification. Every printed reference is checked against authoritative
   database/catalog metadata; no original document is required. Mathematical scope
   covers named statements/proofs, displayed formulas and inline derivations,
   excluding isolated variable names and ordinary prose. The complete source remains
   context. Real formula/theorem errors, missing essential proof steps and unknown
   reference identities block the gate. Read [formal-checks.md](references/formal-checks.md).
5. Conservative merge and editor decision letter. A scientific rejection skips
   unnecessary verification calls. A reference/core-mathematics failure cannot set ready.

Formal verification does **not** audit every empirical row, historical execution,
protocol timestamp, author agreement, funding/conflict statement, human inspection,
classifier implementation or archive member. The ordinary scientific referee and
preflight/release checks handle those responsibilities. Citation quotes, original
PDFs, OCR and precise original theorem/page numbers are not compulsory substitutes
for checking the actual mathematics. Bibliographic evidence uses real source IDs
and metadata locations; literal quotation is optional and, if supplied, must be true.

The deterministic scope and full-document hashes are bound with source bytes,
actual outputs/receipts and the current policy. There is no per-paper disable switch.
Coverage/JSON/ID errors are technical failures, not mathematical counterexamples;
pure technical failures do not consume scientific rounds. Old decisions and counts
are never rewritten. A changed policy requires a fresh unified review, not a fake
conversion of an old failure into a pass. This is not a Lean machine-proof certificate.

Once an identified authoritative metadata record covers a reference, do not automatically
download its optional printed full-text links. Preserve those links and actual retrieval failures;
references without identified metadata still need an official catalog record. Each reference's
evidence IDs must belong to sources bound to that reference key, with honest gaps still allowed.

`ready` requires `send_to_review`, a merged `accept` or `minor_revision`, no scientific blocker,
no unresolved previous item, and only `text` changes remaining. Scores are recorded for
calibration only. At most `review.max_rounds_per_target` rounds (10) per target journal; after
that the paper is `blocked` and the user decides (retarget, more research, or stop).
The user's 2026-10-10 instruction sets the active limit to 15 rounds per target in
`registry/settings.yaml`; the configured limit takes precedence over the older 10-round default.
The global limit remains 15. The Biology paper
`20261005-biology-genetics-reference-orientation-depth` alone has a user-authorized limit of
30 for `Computational Biology and Chemistry` under the user's 2026-10-13 actual
instruction, registered in the top-level paper field
`review_round_limit_override`. Its exact paper ID, target and integer limit must match a
SHA256-bound actual user instruction receipt (`authorization.path`, `sha256`, `json_pointer`
and exact `summary`). Missing, changed or mismatched authorization stops the review and
release validation. Papers without an override retain their configured round limit; the
mandatory formal-check upgrade changes every paper's review policy digest. At the effective
limit the user still decides how to proceed; this override
adds no referee role and changes no editorial or referee decision standard.

Records: `reviews/unified/<paper_id>/<run_id>/` (`decision.json`, per-role prompts, outputs and
receipts with the runtime-reported model). The registry `writing_release` binds the decision
record hash and the exact manuscript, registry and support fingerprints; the handoff rechecks
them.

## Revising after a decision

Fix what the letter asks. Answer a "claim too strong" point by changing the claim or the
structure, never by adding a disclaimer ("we do not claim ..."): referees are instructed to
treat such patches as unresolved. Never put process narration (scripts, versions, review rounds,
verification history) in the paper. Then run `paper start-revision` before editing if not already
open, rebuild, and run the review again with `--response`.

## Return one factory decision

Inside an OpenLabs `paper_review` task, write the `openlabs.result_bundle.v1` from the command's
output without editing the manuscript:

- `outcome: ready` -> `paper_candidate: true`, no `next_actions`.
- `next_action: text_revision` (presentation, claim narrowing, text changes, or a
  `revise_before_submission` screen) -> one action to the `writer`, `session_mode: resume`,
  `handoff_kind: text_revision`, carrying the decision letter.
- `next_action: evidence_remediation` (scientific blocker, evidence change, `reject`, or a desk
  rejection for significance, novelty or incrementality) -> one action to a fresh `researcher`
  (or `experimenter` for an already frozen protocol).
- `next_action: retarget_required` or `blocked` -> no automatic action; report to the user.
- `preflight_failed` -> one `text_revision` action listing the preflight blockers.

Report the editor decision and its strongest desk-reject reason, the active referee recommendations
and actual models, the merged decision, and the run directory.
Label all of these as **internal simulated self-review**, including `send_to_review` and
`minor_revision`. They are not an actual journal submission, external editor decision or
external referee report. Keep actual journal correspondence and submission events separate;
never imply external review from an internal role's journal-style vocabulary.

## Legacy paths

The earlier full-review panel, editorial delta, metadata reuse, minor/targeted/editorial
closeouts and the separate editorial screen are disabled for new work while
`review_process: unified_v1` is configured (they raise an error). Their historical records stay
readable and unchanged. The previous instructions are kept at
`references/legacy-SKILL-before-20261006.md` for reading old records only.

## Temporary configuration and rejection clearance (2026-10-09)

The editor must use a fresh Codex process. Original letters are also supplied to the
active referee, without the current editor verdict, so newly recovered evidence can
resolve an earlier missing-letter request. Claude referee A is temporarily inactive;
`review.referee_roles: [referee_b]` and the recorded user authorization select one Codex
referee. This lacks the normal second-model cross-check and must be reported honestly.
For every distinct historical rejection, supply a verbatim letter with its source and
SHA-256 (registry `journal_rejection_letters`). An internal summary is not a letter.
The editor must identify each decision ID and judge it `resolved` or `compatible` with
located evidence before refereeing can start. Missing, omitted, unresolved or contradictory
letters stop advancement. The decision binds the active review policy as well as the
manuscript; old gates cannot be reused after a policy change.

### Scoped user instruction (2026-10-11)

The user explicitly authorized standard editor/referee evaluation without making missing
original rejection letters alone blocking for four identified papers. A paper can enable
`missing_rejection_letter_policy.mode: available_originals_only` only with its exact paper ID,
missing decision IDs and a hash-bound actual-user receipt whose JSON pointer explicitly
authorizes that paper and decision scope. Every other paper keeps the strict default.
For listed originals that are genuinely unavailable, the fresh editor records
`not_assessable`, `answered: false`, and the unknown-source boundary; it must not invent a
letter or call it resolved/compatible. All available authentic letters and expert reports
reach both editor and active referee, with the scoped instruction. Actual unaddressed
objections, scientific gaps, invalid bindings and changed file hashes remain blocking.
Fresh referees can independently close an earlier request solely for the authorized
missing original as no longer required; old review records are never rewritten. Do not
ask for authorization again when the valid actual-user receipt already supplies it.
This policy is included in the opted-in paper's current review binding only; strict-paper
fingerprints remain unchanged. It does not waive target, manuscript, support, author,
scientific or other release requirements and does not authorize journal submission.
