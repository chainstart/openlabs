---
name: openlabs-paper-review
description: Run OpenLabs' unified journal review for a manuscript in the data repository - deterministic preflight, a target-journal editor screen, mandatory evidence-bound reference and prerequisite verification, the configured blind referee panel, and a conservative decision. This is the only route to writing_release ready. Use for every paper_review task and every request to review, re-review or gate a manuscript.
---

# OpenLabs unified paper review

The review simulates the target journal: first its handling editor, then its referees. Its job is
to catch, before submission, what the journal would catch - above all a desk rejection. The
process is configured in `registry/settings.yaml` (`quality_gate.review_process: unified_v1` and
the `review` block with the active role models and referee_roles) and implemented in
`workflows/paper/paper_writing/review_flow.py`. Design and rationale:
`workflows/paper/docs/UNIFIED_REVIEW_DESIGN.zh.md`.

## Run it

Under the repository resource guard, from the code repository:

```bash
bin/openlabs-resource-guard -- env PYTHONPATH=workflows/paper python3 -m paper_writing \
  review unified-run --paper-id <paper_id> --root <data-root>
```

For a re-review after the authors revised the paper, add `--response <response-letter.md>`.
The response letter answers every item of the previous decision letter with what was changed and
where. Without it a re-review is refused.

The command does everything; do not reproduce its stages by hand, do not write review records
yourself, and do not edit the manuscript, evidence or registry while it runs.

1. **Preflight** (no model): clean build; no source file in `manuscript/` that the build does
   not read; `style-check`; `support-check`; a verified target journal with an approved fit
   record. Any failure stops the run with `preflight_failed`.
2. **Editor screen** - a fresh read-only Codex process (`review.roles.editor`) receives the title,
   abstract, introduction, main statements and reference list, plus the target journal's
   official page and recent related articles, and every prior editorial decision on the paper.
   It restates the contribution in two sentences, names the closest prior work, gives the
   strongest desk-reject reason, says whether each previous rejection is actually answered, and
   decides `send_to_review`, `revise_before_submission` or `desk_reject`.
3. **Reference/prerequisite verification** - after editor and rejection-history clearance,
   fresh Codex batches verify complete coverage, authoritative bibliographic data and mathematical correctness as described below.
   An incomplete or failed verification stops advancement with `formal_check_blocked`.
   Raw coverage and negative entries are preserved. Author-facing root causes
   distinguish scientific findings, protocol/service errors, source routing and
   deterministic artifact preparation; a parent/nested duplicate is one cause.
4. **Referees** - only after `send_to_review` and passing mandatory verification. The configured active referees in fresh processes (normally two different models;
   temporarily only Codex `referee_b` under the 2026-10-09 user instruction) review the complete expanded source, bibliography and
   supporting-material description, blind to each other, and recommend in the journal's
   vocabulary with typed required changes (`text`, `claim_narrowing`, `evidence`).
5. **Decision** - deterministic merge: the more cautious recommendation wins; blockers are the
   union; an unresolved item from the previous round blocks. The editor model then writes the
   decision letter without changing the decision.

After editor clearance and before the ordinary referees, **mandatory reference and
prerequisite verification** runs in fresh Codex processes using the configured editor
model. This is a verification stage, not an additional journal referee or a return of
Claude. Read [references/formal-checks.md](references/formal-checks.md) when preparing
sources or resolving a failure. Code checks exact coverage of every printed reference,
every citation occurrence, every detected formula and all main/supplement source
passages; independent verifiers check authoritative bibliographic data and theorem applications.
Errors, gaps, unchecked items, omitted/duplicate/invented IDs, unsupported quotations,
or unresolved bibliographic identity block advancement. Under the user's 2026-10-12
instruction, acquiring original documents is not required: correct authoritative
metadata suffices for references, and paywalls or failed full-text/OCR retrievals
alone do not block. Mathematical statements, hypotheses, derivations and appropriate
attribution remain independently checked. Referees
must also assess omitted/misclassified prerequisites. The rule cannot be disabled by
paper metadata. A standalone `formal-check` does not set `writing_release: ready`.

The decision and release bind the complete formal report, retrieved evidence bytes,
role outputs/receipts and source plan. Changed/missing evidence, a changed verifier
policy or an old decision lacking this stage requires a fresh unified review.
Historical decisions and website submission events remain unchanged. This provides
evidence-backed coverage, not a universal mathematical correctness certificate or
an automatic Lean proof of all prose; any machine proof claim needs an actual checked
certificate with a statement/assumption correspondence.

Under the user's 2026-10-12 proportionality instruction, quoted evidence and
internal proof excerpts allow pure whitespace folding while original evidence
bytes remain hash-bound; symbols, case and hyphenation remain exact. Configured
PDF/ZIP presence, format and hashes are deterministic preparation checks, not
scientific premises. Reproducibility and numerical claims still need actual
evidence. New decisions with only technical, routing or preparation failures
block clearance without consuming a scientific round; mixed scientific gaps
still count. Historical records and their counts are never rewritten. Any policy
change requires a fresh unified review, preserving editor → complete formal
checks → active referee order and independent contexts.

`ready` requires `send_to_review`, a merged `accept` or `minor_revision`, no scientific blocker,
no unresolved previous item, and only `text` changes remaining. Scores are recorded for
calibration only. At most `review.max_rounds_per_target` rounds (10) per target journal; after
that the paper is `blocked` and the user decides (retarget, more research, or stop).
The user's 2026-10-10 instruction sets the active limit to 15 rounds per target in
`registry/settings.yaml`; the configured limit takes precedence over the older 10-round default.
The global limit remains 15. The Biology paper
`20261005-biology-genetics-reference-orientation-depth` alone has a user-authorized limit of
22 for `Computational Biology and Chemistry` under the current actual user
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
