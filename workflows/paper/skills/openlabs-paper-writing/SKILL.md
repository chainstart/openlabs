---
name: openlabs-paper-writing
description: Shared OpenLabs manuscript workflow for every domain, from verified evidence through drafting, deterministic checks, supporting-material preparation and hand-off to the independent unified review. The domain entry skills (openlabs-ai-paper, -biology-, -materials-, -math-, -physics-, -quant-paper) point here and add a short domain section.
---

# OpenLabs paper writing

The repository owns state and evidence; this skill is the shared procedure. Principles are in
the code repository's `AGENTS.md`; user decisions (venue eligibility, review panel, round
limit, author defaults, cadence) are in `<paper_root>/registry/settings.yaml`. Mechanical
details of the checks and registry fields are in `../overlays/quality-gate.md`
(`workflows/paper/skills/overlays/quality-gate.md`).

## Inputs and canonical places

Resolve `paper_root` from `OPENLABS_DATA` or `$OPENLABS_WORKSPACE/openlabs-data` (the private
data repository). Read the paper record `registry/papers/<paper_id>.yaml` and its evidence
bundles; missing or contradictory evidence is a blocker, not an invitation to write plausible
prose. Use only the canonical artifacts, never a parallel state file:

- claims and provenance: `papers/<paper_id>/evidence/claim_evidence_map.md`;
- manuscript: `papers/<paper_id>/manuscript/`; revision notes: `papers/<paper_id>/revisions/`;
- internal reviews: `reviews/`; release status: the record's `writing_release`.

Identifiers and public file names: `../references/paper-identifiers.md`. Keep unpublished
material local unless external processing is authorized and compatible with the venue.

Load at most the three vendored components that `../profiles.yaml` declares for the domain,
from `workflows/paper/skills/vendor/`: the primary writing skill always, the domain component
(statistical-analysis or sympy) only when the paper needs it, and peer-review only in an
assigned reviewer role. Repository rules override vendored instructions.

## Write

1. Build or update the claim–evidence map before strengthening any claim or adding numbers.
2. Fix one main conclusion and its contribution boundary against the closest published work,
   then revise the canonical LaTeX. Apply `../openlabs-paper-readability/SKILL.md`.
3. Keep negative, mixed, null and incomplete results. Do not choose an analysis after seeing
   which result is favorable; record design, exclusions, uncertainty, seeds and versions.
4. Verify each citation's metadata and its support for the specific sentence; a search hit or
   another paper's bibliography is discovery, not verification.
5. Write neutral scholarly prose. Prompts, agents, review or gate mechanics, audit narration,
   internal paths and repository state stay out of the manuscript and bibliography notes;
   `style-check` enforces the mechanical part.
6. Exactly one final AI-use declaration, using the short template selected in
   `registry/paper-declarations/templates.yaml` unless the venue requires another form. Name the
   tools and model identifiers that runtime records show (registered under
   `declarations.ai_use.model_usage` with hash-bound evidence) and their actual purposes, such as
   code development or Lean preparation; formal verification is credited to the pinned Lean
   toolchain, not to AI output. Never weaken a truthful disclosure.
7. Authors, CRediT roles, competing interests and funding use the standing defaults in
   `settings.yaml#defaults` (user instruction 2026-11-09) unless the paper record says otherwise;
   do not ask for routine reconfirmation, and do not treat the defaults as attestation of human
   review or code verification. Submission-facing files contain no pending-confirmation text;
   an unavoidable later portal action goes only in `production/human_action_checklist.md`.

## Choose the venue

Eligibility, routine versus escalation tiers, the ranking system and fees are defined in
`settings.yaml#journal_target_policy` and `#submission_cadence`; do not restate them from
memory. Before any shortlist or retarget run `paper-writing journal-history sync` and
`journal-history check --journal <title>` for every candidate. Record an evidence-backed
`target_journal_fit` (scope, core readership, contribution scale, two recent adjacent articles
from that venue, same-target history), the dated ranking source, the fee-free route and the
official format, and convert the canonical `manuscript/` itself to that format. Missing ranking
metadata is a lookup task; record `unverified` only after a genuine search fails or conflicts.
Handling a rejection: `docs/JOURNAL_HISTORY.md#handling-a-rejection`.

## Check, prepare support, hand off

1. Compile the real manuscript; run repository validation, `paper-writing style-check` and the
   declaration checks under the resource guard. A failure blocks review.
2. Unless the record is `not_required` with a reason, prepare the Zenodo draft
   (`paper-writing zenodo prepare`, code-first per `docs/ZENODO_GUIDE.md`), cite its Version DOI
   in the bibliography, first substantive support mention and availability statement with
   wording that stays true after publication, then run `zenodo verify-draft` and
   `support-check`. Use the configured default licence without asking; surface a real licence
   conflict instead of changing files or licence silently.
3. For targets checked from 2026-11-08, run `paper-writing rewrite run <paper_id>` (editor-facing
   rewrite pass, `settings.yaml#quality_gate.editorial_rewrite`) before review.
4. In a factory `writer` task, stop at the frozen `paper_candidate`; never run or impersonate a
   reviewer. The scheduler starts a fresh `$openlabs-paper-review` task. On `paper_revision`,
   apply only the declared request; new evidence goes through `evidence_remediation` first.
5. After a passing gate, run `paper-writing zenodo release` under the standing authorization,
   commit the DOI/receipt, then `paper-writing handoff release`. None of this submits the paper,
   creates a journal event, or authorizes spending; those stay with a human.

## Finish

Report changed files, evidence gaps, checks and builds actually run, and remaining scientific
risks. If the paper is not ready, state the next bounded step instead of calling it
submission-ready.
