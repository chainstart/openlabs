---
name: openlabs-paper-review
description: "Run the sole OpenLabs journal self-review: deterministic preflight, independent target-editor screen with actual rejection history, the configured cross-model referees, bibliography and core-mathematics verification, then a bound decision."
---

# OpenLabs unified paper review

Use `review unified-run` under the resource guard; this is the only route to
`writing_release: ready`. The editor, the referees, their models and the round limit come
from `registry/settings.yaml#review`; do not restate them here. The panel must include a
referee from a model family other than the drafting model (`review.cross_model`). A gate never
authorizes journal submission.

```bash
bin/openlabs-resource-guard --task-type cpu -- env PYTHONPATH=workflows/paper python -m paper_writing \
  review unified-run --paper-id PID --root DATA_ROOT --response RESPONSE.md
```

Omit `--response` only for a first review. Do not manually construct decisions or
edit manuscript/registry/evidence during review. Preserve actual outputs and model
receipts, including failures. Revised prose remains neutral scientific writing;
keep internal review negotiation and claims about editor approval outside the paper.

## Sequence

1. Deterministic preflight. It stops the review only when a review would be meaningless: the
   manuscript does not build, the registration or an evidence/data hash binding is broken, the
   target violates the venue policy, a declared source points at a missing bibliography key, or
   the editor-facing rewrite pass has not run once for this target. Style, AI-declaration,
   abstract-format, unused-source, support-record and unpackaged claim-evidence-map
   (no Zenodo draft of the current version yet) findings are recorded as
   `preparation_advisories`; they are enforced at the delivery exit (handoff and Zenodo
   release), not here, so a formal slip never costs a scientific round.
2. Independent target-venue editor: contribution, closest prior work, readership, strongest
   desk-reject reason and every available historical refusal letter.
3. Independent scientific referees, each in a fresh process: complete manuscript and
   supplement, novelty, significance for the target, correctness, experimental credibility,
   previous objections. Unsupported main claims go in `scientific_blockers`; requested changes
   are typed `evidence`, `claim_narrowing` (with `main_claim`) or `text`.
4. If the scientific decision can advance, independent bibliography and core-mathematics
   verification, run by `review.roles.formal_verifier` when configured (otherwise the editor's
   model). Every printed reference is checked against authoritative metadata; named
   statements, proofs, displayed formulas and inline derivations are checked as mathematics.
   Real formula or theorem errors, missing essential proof steps and wrong or unknown reference
   identities block. A reference whose authoritative record could not be fetched for access
   reasons is listed as `unverifiable_source_access`, not as a defect. Details:
   [formal-checks.md](references/formal-checks.md).
5. Deterministic merge and editor decision letter.

Technical failures (coverage, JSON, IDs) are not scientific findings and do not consume a
round. Decisions bind the manuscript snapshot, source hashes, model receipts and the current
review policy; old decisions and counts are never rewritten, and a policy change needs a
fresh review.

## What decides readiness

Only scientific substance blocks. `ready` requires `send_to_review`, no scientific blocker, no
`evidence` change, no main-claim narrowing, no unresolved previous scientific or evidence item,
and an `accept` or `minor_revision` recommendation. When referees disagree the more favourable
recommendation stands unless the stricter one is backed by such an item. `text` changes and
the editor's presentation notes are advisory: they reach the letter and `advisory_changes`, but
are not tracked into the next round. Under the escalation track every referee must also reach
the configured escalation score without low confidence. Scores are otherwise kept for
calibration.

Outcomes that are not a revision: a desk reject for significance or incrementality, or a
`reject` from every referee of a two-referee panel, returns `direction_decision` with a
`direction_context`; a scope or readership desk reject returns `retarget_required`. Both set
the paper `blocked`. `stalled` marks a round with no evidence request whose mean significance
and novelty scores have not risen over the last two transitions.

After a ready review, a later text- or figure-only change is rechecked as a delta: when the
title, abstract, introduction, statements, tables, conclusion-bearing sections and numbers are
unchanged and few lines changed, the earlier judgment is reused, the formal verification
reruns, and no round is consumed. Anything more gets a full review.

The round limit per target is `review.max_rounds_per_target`; a paper may carry a
`review_round_limit_override` only with a matching SHA-256-bound user receipt. At the limit the
paper is `blocked` and the orchestrator takes a direction decision (retarget, more research, or
freeze).

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
- `next_action: evidence_remediation` (scientific blocker, evidence change, a `reject` that is
  not unanimous, a failed formal verification, uncleared rejection history, or a
  `novelty_unclear` desk rejection) -> one action to a fresh `researcher` (or `experimenter` for
  an already frozen protocol).
- `next_action: retarget_required`, `direction_decision`, `review_stalled: true` or
  `status: blocked` (rounds used up) -> no action; the `review_outcome` below lets the
  orchestrator schedule a direction decision. Do not choose a new venue or stop the topic here.
- `preflight_failed` -> one `text_revision` action listing the preflight blockers.

In every case also copy the paper's `registry/papers/<paper_id>.yaml#writing_release` unchanged
into the result field `review_outcome`: `next_action`, `status`, `review_stalled` (false when
absent), `rounds_for_target`, `max_rounds_per_target`, `direction_context` (null when absent),
`decision_record`, `decision_record_sha256`, plus `paper_id`. The orchestrator checks it and
decides the next step from it (for example no writer revision after a stalled review, even with a
`text_revision` action).

Report the editor decision and its strongest desk-reject reason, the active referee recommendations
and actual models, the merged decision, and the run directory.
Label all of these as **internal simulated self-review**, including `send_to_review` and
`minor_revision`. They are not an actual journal submission, external editor decision or
external referee report. Keep actual journal correspondence and submission events separate;
never imply external review from an internal role's journal-style vocabulary.

## Legacy paths

The pre-unified routes (scored panel, delta and closeout commands, metadata reuse, separate
editorial screen) are removed or refuse to run under `review_process: unified_v1`. Their
records stay readable; the old instructions are in
`references/archive/legacy-SKILL-before-20261006.md` for reading those records only.

## Rejection clearance

The editor uses a fresh process. Original letters are also supplied to the referees, without
the current editor verdict, so newly recovered evidence can resolve an earlier missing-letter
request. Decisions started under an earlier panel stay bound to the matching
`review.previous_panels` entry. For every distinct historical rejection, supply a verbatim
letter with its source and SHA-256 (registry `journal_rejection_letters`). An internal summary is not a letter.
The editor must identify each decision ID and judge it `resolved` or `compatible` with
located evidence before refereeing can start. Missing, omitted, unresolved or contradictory
letters stop advancement. The decision binds the active review policy as well as the
manuscript; old gates cannot be reused after a policy change.

### Missing original letters (user instruction 2026-10-11)

A paper may set `missing_rejection_letter_policy.mode: available_originals_only` only with its
exact paper ID, missing decision IDs and a hash-bound user receipt covering that scope. The
editor then records a genuinely unavailable original as `not_assessable`, never invents or "resolves" it, and all available letters still reach the
editor and referees. Every other requirement stays blocking; do not ask again when a valid
receipt exists. Details:
`workflows/paper/docs/REJECTION_HISTORY_POLICY.zh.md`.
