---
name: openlabs-paper-review
description: Run OpenLabs' configured fresh-context paper gate for AI, computer-science, software-engineering, mathematics, materials-science, physics, or quantitative-finance manuscripts. Uses one independent Codex reviewer by default and adds a blind Packy Claude reviewer only when the registry explicitly enables the two-reviewer contract.
---

# OpenLabs paper review

Read `registry/settings.yaml` before selecting the panel contract. The default contract uses exactly
one score-bearing reviewer: a fresh Codex `reviewer-1` with `provider: openai-codex`. Do not launch
Claude under this contract. Form the validated one-member panel with `aggregate_panel.py`, which
selects `openlabs.paper_writing.review.single.v1`, `coordinatewise_median`, and `ordinal_median`
from the configured panel size.

Claude is optional. Only when `registry/settings.yaml#quality_gate` explicitly sets
`review_panel_size: 2`, `score_aggregation: coordinatewise_minimum`, and
`decision_aggregation: strictest_decision` add `reviewer-2`, a fresh Claude Code process using
Packy and exactly `claude-opus-5`. Freeze reviewer-1 before Claude starts, never send its content
to Claude, and never revise it after Claude returns. Deterministic code may validate provenance and
combine completed judgments; it must never originate or improve a score.

The default one-reviewer contract does not weaken snapshot, input-hygiene, provenance, rubric, or
quality-gate checks.
The sole reviewer must run in a new ephemeral process with no author-session state. A same-context
self-review, a resumed author session, or a score supplied directly to `quality-gate` is invalid and
must never advance `writing_release` to `ready`.

Do not launch any reviewer for a revision that was opened from a current passing gate and changes
only author identity/contact/affiliation commands or release-envelope metadata. Run
`paper-writing review reuse-metadata --paper-id <paper_id>` instead. That deterministic command is
the sole classifier for this exception: it compares the captured scientific/textual, registry, and
support-source fingerprints and reruns non-LLM checks. If it reports any difference or lacks a
verified baseline, proceed with the normal fresh review below. Never decide metadata-only status by
eyeballing a diff, and never edit an old review record to fit a new full snapshot.

## Establish the review boundary

1. Resolve the private data root from `OPENLABS_DATA` or the configured workspace. Read
   `registry/settings.yaml`, `workflows/paper/skills/profiles.yaml`, and the selected paper record.
   Derive reviewer metadata with `paper_writing.review.review_safe_registry`; do not expose
   `ara_llm_self_review`, `writing_release`, `review_file`, or
   `support.publication.release_binding`.
2. Build an explicit input list from canonical transitive TeX inputs, bibliography, claim-evidence
   maps, registered evidence, and any objective audit receipt. Do not recursively expose the paper
   tree. Never include a prior review, preflight verdict, score, decision, editor verdict, venue
   readiness assessment, or Git history.
3. Run `scripts/check_input_hygiene.py` on every registered ZIP and the current support ZIP. A
   nonzero result blocks review. Directly inspect the explicit text inputs as well; the archive
   checker is not a substitute for that inspection.
4. If and only if the configured two-reviewer contract enables Packy, confirm that sending
   unpublished inputs to Packy is authorized and compatible with venue policy. Installing this
   integration does not authorize external processing of every future paper; confidentiality and
   venue constraints still apply per manuscript.
5. Finish deterministic manuscript checks, then freeze and hash one canonical manuscript
   snapshot. No configured reviewer may edit the manuscript, evidence, registry, or sibling output.

If a reviewer sees a prior evaluative projection or the snapshot changes, discard that reviewer
record and rerun the complete configured panel on a clean snapshot.

## Run the configured reviewers

### Reviewer 1: Codex

Start a blank reviewer session. Read the complete frozen paper, relevant evidence, and the selected
rubric. Write `reviewer-1.json` using `ara.paper_writing.review.v2`, including:

```json
{
  "provider": "openai-codex",
  "model": "<actual Codex model>",
  "panel_reviewer_id": "reviewer-1",
  "independent_context": true,
  "isolated_process": true,
  "prior_reviews_hidden": true
}
```

These keys belong inside `review_metadata`. The isolated-process flag is valid only when the
review was produced by a newly launched, non-resumed, ephemeral reviewer process with no author
conversation state. Validate and freeze the file. Under the default contract, proceed directly to
single-reviewer aggregation. Under the optional two-reviewer contract, freeze it before starting
Claude and do not edit it afterward.

### Reviewer 2: Claude Code Opus 5 through Packy

Skip this subsection entirely unless the explicitly configured two-reviewer contract enables it.

Use the local Claude settings file containing `ANTHROPIC_BASE_URL` for Packy and either
`ANTHROPIC_AUTH_TOKEN` or `ANTHROPIC_API_KEY`. Never copy the key into this repository, an
environment example, a prompt, a log, or a review artifact.

Run the bounded adapter after reviewer-1 is frozen:

```bash
python "$OPENLABS_WORKSPACE/openlabs/workflows/paper/skills/openlabs-paper-review/scripts/run_claude_reviewer.py" \
  --paper-id <paper_id> \
  --peer-review reviews/<review_run_id>/<paper_id>/reviewer-1.json \
  --input <transitive-tex-or-bib> \
  --input <review-safe-evidence-or-objective-receipt>
```

The adapter automatically includes canonical `main.tex`, redacted registry metadata, and the
rubric. It accepts only explicit UTF-8 files inside the data repository; prior review paths are
rejected except objective-audit receipts. It invokes a new non-persistent Claude Code process with
all tools disabled, structured output enabled, and model fixed to `claude-opus-5`. It verifies the
Packy endpoint and presence of a local credential without printing the credential. It hashes but
does not read reviewer-1 into the prompt, checks reviewer-1 and the manuscript remained unchanged,
and writes `reviewer-2.json` beside reviewer-1.

## Run objective formal checks once

When Lean evidence is in scope, run one snapshot-bound objective audit before the configured review:

```bash
python "$OPENLABS_WORKSPACE/openlabs/workflows/paper/skills/openlabs-paper-review/scripts/run_lean_audit.py" \
  --paper-id <paper_id> \
  --project <repo-relative-lean-project> \
  --audit-file <project-relative-axiom-audit.lean> \
  --manuscript-snapshot <sha256> \
  --support-sha256 <sha256> \
  --output reviews/objective-audits/<paper_id>/<snapshot>/lean.json
```

This checker is not a reviewer and does not score. Give the same immutable receipt to every
configured reviewer. Do not run `lake update`, rebuild Lean, or repeat the formal validation in a reviewer
context. Preserve the existing resource ceilings: at most four threads, 24 GiB aggregate RSS,
32 GiB virtual address space per process, 24 processes, and 60 minutes, while reserving at least
8 GiB or one quarter of host memory. If a central claim needs the audit and no valid PASS receipt
exists, retain an evidence blocker.

Select validation from the Lean-input delta. If Lean sources, `lean-toolchain`, Lake configuration,
and dependency-lock hashes are unchanged, use `--reuse-pass-receipt` (or
`--reuse-build-report` for a verified legacy full-build report) to create a zero-execution receipt
bound to the current manuscript/support snapshot. A support-package or manuscript-only change does
not invalidate Lean evidence. For a local source change with stable toolchain, dependency lock,
configuration, and foundational interfaces, use `--build-mode incremental`; reserve
`--build-mode full` for toolchain, dependency, configuration, or broad interface changes. State in
the review packet whether Lean validation was reused, incremental, or full.

## Select the rubric

Read `references/rubrics.md` completely and route from the registry's literal domain. For
physics, also read `references/physics-highest-tier-venues.md` completely:

- `ai`, `cs`, `se`: `cs_top_tier`, with independent `top_conference` and
  `cas_zone_1_journal` recommendations;
- `math`: `math`, judged against *Annals of Mathematics*, *Inventiones Mathematicae*, *Journal of
  the American Mathematical Society*, and *Acta Mathematica*, with `four_top_math_journals` and
  `cas_zone_1_journal` recommendations and no conference view;
- `materials`: `materials`, with `leading_materials_journals` and
  `cas_zone_1_journal` recommendations;
- `physics`: `physics`, with separate scored simulations for *Physical Review Letters*,
  *Physical Review X*, and *Nature Physics* inside `leading_physics_journals`, plus an independent
  `cas_zone_1_journal` recommendation;
- `quant`: `quant_finance`, with `leading_quant_finance_journals` and
  `cas_zone_1_journal` recommendations;
- any other domain: stop; do not silently substitute a rubric.

Use `cas_zone_1_basis.mode: generic_standard` unless a named target's current major-category
classification has been verified from an identified source.

## Review the frozen work

Reviewer-1 inspects the compiled PDF, all canonical source inputs, and registered evidence. When
the optional second reviewer is enabled, reviewer-2 receives the same scientific content as
explicit UTF-8 source/evidence inputs; include all transitive TeX, bibliography, figure/table
descriptions, and machine-readable evidence needed to assess central claims.

Every configured reviewer independently checks claim-evidence correspondence, proof dependencies, statistical
design, physical validity, citations, build freshness, unresolved markers, reproducibility, and
support-package claims as applicable. Run `python -m paper_writing support-check --paper-id
<paper_id>` before scoring. Missing or contradictory evidence, invalid inference, proof gaps, and
unsupported central claims are blockers; do not repair them during review.

The repository treats registered author metadata and final declarations as confirmed defaults.
The reviewed manuscript, cover letter, and current journal package must contain no TODO, pending
author confirmation, draft-for-approval, internal upload gate, or similar production narration.
Put genuinely unavoidable later human portal actions only in
`production/human_action_checklist.md`, outside `journal-submissions/`. Such a checklist cannot
hide or waive a scientific, evidence, ethics, authorship, or license blocker. A passing review
targets a package requiring no further author editing before upload.

## Score independently

Read `references/review-schema.md` before writing any configured record.

- Score `clarity`, `soundness`, `significance`, `novelty`, and holistic `overall` as integers 1--10.
- When between integers, choose the lower one and explain the uncertainty.
- Do not tune a result to cross the repository threshold or infer the other reviewer's judgment.
- Produce exactly the two domain-specific simulated recommendation views.
- `minor_revision` is allowed only when no new central proof, experiment, data, analysis, or claim
  is required. A scientific blocker prevents an accept recommendation.

## Aggregate the configured panel

Under the default one-reviewer contract, freeze `reviewer-1.json`, preserve its scores, decisions,
findings, and blockers exactly, and run the command below. The resulting
`openlabs.paper_writing.review.single.v1` record uses one-member coordinatewise and ordinal medians.
There is no reviewer-2 validation step.

Under the optional two-reviewer contract, only after both immutable source files exist may the
coordinator read reviewer-2. Then:

1. For each score, take the lower of the two integers (`coordinatewise_minimum`).
2. For each recommendation vocabulary ordered most favorable to least favorable in the rubric,
   take the less favorable decision (`strictest_decision`).
3. Retain the union of weaknesses, required changes, change requests, and unresolved blockers.
   `text_ready` and `scientific_ready` are true only if both reviewers say true and no blocker
   remains. No vote, average, or coordinator prose may erase a blocker.
4. Write schema `openlabs.paper_writing.review.v1`. Historical
   `ara.paper_writing.review.v3` three-review panels remain readable but must not be generated for
   new work.

Use the mechanical aggregator:

```bash
python "$OPENLABS_WORKSPACE/openlabs/workflows/paper/skills/openlabs-paper-review/scripts/aggregate_panel.py" \
  --paper-id <paper_id> \
  --review-dir reviews/<review_run_id>/<paper_id> \
  --objective-audit reviews/objective-audits/<paper_id>/<snapshot>/lean.json
```

Omit `--objective-audit` when it is not in scope. The aggregator reads the active contract and
validates provider/model identity, the common snapshot, source hashes, and exact configured
aggregation. In two-reviewer mode it additionally validates the hidden frozen-peer hash and
conservative aggregation.

## Validate and apply

Validate reviewer-1 and the panel. Run the reviewer-2 validation command only when the optional
two-reviewer contract is enabled:

```bash
python "$OPENLABS_WORKSPACE/openlabs/workflows/paper/skills/openlabs-paper-review/scripts/validate_review.py" \
  --paper-id <paper_id> \
  --review reviews/<review_run_id>/<paper_id>/reviewer-1.json

# Optional two-reviewer contract only:
python "$OPENLABS_WORKSPACE/openlabs/workflows/paper/skills/openlabs-paper-review/scripts/validate_review.py" \
  --paper-id <paper_id> \
  --review reviews/<review_run_id>/<paper_id>/reviewer-2.json

python "$OPENLABS_WORKSPACE/openlabs/workflows/paper/skills/openlabs-paper-review/scripts/validate_review.py" \
  --paper-id <paper_id> \
  --review reviews/<review_run_id>/<paper_id>/review.json
```

Fix validation-only transcription errors in place. A substantive judgment change requires a new
reviewer context; any score-bearing manuscript change invalidates every configured review. A changed full PDF
hash caused solely by the deterministic metadata-only path above is recorded as review reuse, not a
new review.

Apply the validated panel with:

```bash
python -m paper_writing review apply \
  --paper-id <paper_id> \
  --review reviews/<review_run_id>/<paper_id>/review.json \
  --venue-type <conference-or-journal>
```

The CAS Zone 1 decision remains the internal gate decision. Any unresolved blocker keeps the gate
out of `ready`. A ready gate activates the repository's standing authorization to publish the
exact prepared Zenodo support record in a separate fail-closed release step. It does not itself
perform a network write or record a journal submission, publication, or editorial event.

## Return one factory decision

When this Skill runs inside an OpenLabs `paper_review` task, write the required
`openlabs.result_bundle.v1` without editing the manuscript:

- If the validated conservative panel passes, set `paper_candidate: true` and leave
  `next_actions` empty. This is the terminal internal review state.
- If the evidence is sufficient and only prose, organization, citation presentation, or claim
  narrowing must change, set `paper_candidate: false` and return exactly one structured action with
  `agent_role: writer`, `session_mode: resume`, and `handoff_kind: text_revision`. The scheduler
  resumes the ancestral writer session; it never passes this reviewer session to the writer.
- If a new proof, experiment, analysis, literature determination, or other scientific evidence is
  required, return exactly one `evidence_remediation` action to a fresh `researcher` or
  `experimenter`. Choose `experimenter` only for execution of an already frozen protocol. Include a
  `resources` object only when the bounded remediation genuinely needs a reservation different
  from the default.

Do not combine text revision and evidence remediation in one action, ask the writer to manufacture
missing evidence, or request another reviewer. After either repair path, the scheduler freezes a
new manuscript candidate and starts a new panel under the same configured contract.

Report every source score vector, the five aggregate scores, both simulated decisions, retained
blockers, validation and gate results, actual provider/model identities, and confirmation that all
configured reviewers used the same unchanged manuscript snapshot.
