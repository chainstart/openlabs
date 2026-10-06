---
name: openlabs-paper-review
description: Run OpenLabs' unified journal review for a manuscript in the data repository - a deterministic preflight, an editor screen at the named target journal (to catch desk rejections), two blind referees on different models, and a conservative editor decision. This is the only route to writing_release ready. Use for every paper_review task and every request to review, re-review or gate a manuscript.
---

# OpenLabs unified paper review

The review simulates the target journal: first its handling editor, then its referees. Its job is
to catch, before submission, what the journal would catch - above all a desk rejection. The
process is configured in `registry/settings.yaml` (`quality_gate.review_process: unified_v1` and
the `review` block with the three role models) and implemented in
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
2. **Editor screen** - a fresh, tool-less process (`review.roles.editor`) reads only the title,
   abstract, introduction, main statements and reference list, plus the target journal's
   official page and recent related articles, and every prior editorial decision on the paper.
   It restates the contribution in two sentences, names the closest prior work, gives the
   strongest desk-reject reason, says whether each previous rejection is actually answered, and
   decides `send_to_review`, `revise_before_submission` or `desk_reject`.
3. **Referees** - only after `send_to_review`. Two fresh, tool-less processes on different
   models (`referee_a`, `referee_b`) review the complete expanded source, bibliography and
   supporting-material description, blind to each other, and recommend in the journal's
   vocabulary with typed required changes (`text`, `claim_narrowing`, `evidence`).
4. **Decision** - deterministic merge: the more cautious recommendation wins; blockers are the
   union; an unresolved item from the previous round blocks. The editor model then writes the
   decision letter without changing the decision.

`ready` requires `send_to_review`, a merged `accept` or `minor_revision`, no scientific blocker,
no unresolved previous item, and only `text` changes remaining. Scores are recorded for
calibration only. At most `review.max_rounds_per_target` rounds (3) per target journal; after
that the paper is `blocked` and the user decides (retarget, more research, or stop).

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

Report the editor decision and its strongest desk-reject reason, both referee recommendations
and models, the merged decision, and the run directory.

## Legacy paths

The earlier full-review panel, editorial delta, metadata reuse, minor/targeted/editorial
closeouts and the separate editorial screen are disabled for new work while
`review_process: unified_v1` is configured (they raise an error). Their historical records stay
readable and unchanged. The previous instructions are kept at
`references/legacy-SKILL-before-20261006.md` for reading old records only.
