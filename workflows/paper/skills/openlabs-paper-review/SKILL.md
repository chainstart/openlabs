---
name: openlabs-paper-review
description: Run OpenLabs' independent dual-provider paper gate for AI, computer-science, software-engineering, mathematics, or materials-science manuscripts. Use when one fresh Codex reviewer and one blind Packy Claude Code Opus 5 reviewer must score the same frozen manuscript, or when validating their conservative panel result.
---

# OpenLabs paper review

Use exactly two score-bearing reviewers:

- `reviewer-1`: a fresh Codex reviewer with `provider: openai-codex`;
- `reviewer-2`: a fresh Claude Code process using Packy and exactly `claude-opus-5`.

The reviewers must be independent. Freeze reviewer-1 before Claude starts, never send its content
to Claude, and never revise it after Claude returns. Deterministic code may validate provenance and
combine completed judgments; it must never originate or improve a score.

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
4. Confirm that sending unpublished inputs to Packy is authorized and compatible with venue
   policy. Installing this integration does not authorize external processing of every future
   paper; confidentiality and venue constraints still apply per manuscript.
5. Finish deterministic manuscript checks, then freeze and hash one canonical manuscript
   snapshot. Neither reviewer may edit the manuscript, evidence, registry, or sibling output.

If a reviewer sees a prior evaluative projection or the snapshot changes, discard that reviewer
record and rerun the complete two-review gate on a clean snapshot.

## Run the two independent reviewers

### Reviewer 1: Codex

Start a blank reviewer session. Read the complete frozen paper, relevant evidence, and the selected
rubric. Write `reviewer-1.json` using `ara.paper_writing.review.v2`, including:

```json
{
  "provider": "openai-codex",
  "model": "<actual Codex model>",
  "panel_reviewer_id": "reviewer-1",
  "independent_context": true,
  "prior_reviews_hidden": true
}
```

These keys belong inside `review_metadata`. Validate and freeze the file before starting Claude.
Do not edit it afterward.

### Reviewer 2: Claude Code Opus 5 through Packy

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

When Lean evidence is in scope, run one snapshot-bound objective audit before either reviewer:

```bash
python "$OPENLABS_WORKSPACE/openlabs/workflows/paper/skills/openlabs-paper-review/scripts/run_lean_audit.py" \
  --paper-id <paper_id> \
  --project <repo-relative-lean-project> \
  --audit-file <project-relative-axiom-audit.lean> \
  --manuscript-snapshot <sha256> \
  --support-sha256 <sha256> \
  --output reviews/objective-audits/<paper_id>/<snapshot>/lean.json
```

This checker is not a third reviewer and does not score. Give the same immutable receipt to both
reviewers. Do not run `lake update`, rebuild Lean, or repeat the formal validation in a reviewer
context. Preserve the existing resource ceilings: at most four threads, 24 GiB aggregate RSS,
32 GiB virtual address space per process, 24 processes, and 60 minutes, while reserving at least
8 GiB or one quarter of host memory. If a central claim needs the audit and no valid PASS receipt
exists, retain an evidence blocker.

## Select the rubric

Read `references/rubrics.md` completely and route from the registry's literal domain:

- `ai`, `cs`, `se`: `cs_top_tier`, with independent `top_conference` and
  `cas_zone_1_journal` recommendations;
- `math`: `math`, judged against *Annals of Mathematics*, *Inventiones Mathematicae*, *Journal of
  the American Mathematical Society*, and *Acta Mathematica*, with `four_top_math_journals` and
  `cas_zone_1_journal` recommendations and no conference view;
- `materials`: `materials`, with `leading_materials_journals` and
  `cas_zone_1_journal` recommendations;
- any other domain: stop; do not silently substitute a rubric.

Use `cas_zone_1_basis.mode: generic_standard` unless a named target's current major-category
classification has been verified from an identified source.

## Review the frozen work

Reviewer-1 inspects the compiled PDF, all canonical source inputs, and registered evidence.
Reviewer-2 receives the same scientific content as explicit UTF-8 source/evidence inputs; include
all transitive TeX, bibliography, figure/table descriptions, and machine-readable evidence needed
to assess central claims.

Both reviewers independently check claim-evidence correspondence, proof dependencies, statistical
design, physical validity, citations, build freshness, unresolved markers, reproducibility, and
support-package claims as applicable. Run `python -m paper_writing support-check --paper-id
<paper_id>` before scoring. Missing or contradictory evidence, invalid inference, proof gaps, and
unsupported central claims are blockers; do not repair them during review.

## Score independently

Read `references/review-schema.md` before writing either record.

- Score `clarity`, `soundness`, `significance`, `novelty`, and holistic `overall` as integers 1--10.
- When between integers, choose the lower one and explain the uncertainty.
- Do not tune a result to cross the repository threshold or infer the other reviewer's judgment.
- Produce exactly the two domain-specific simulated recommendation views.
- `minor_revision` is allowed only when no new central proof, experiment, data, analysis, or claim
  is required. A scientific blocker prevents an accept recommendation.

## Aggregate conservatively

Only after both immutable source files exist may the coordinator read reviewer-2.

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

Omit `--objective-audit` when it is not in scope. The aggregator validates provider/model identity,
the hidden frozen-peer hash, common snapshot, source hashes, and exact conservative aggregation.

## Validate and apply

Validate both source files and the panel:

```bash
python "$OPENLABS_WORKSPACE/openlabs/workflows/paper/skills/openlabs-paper-review/scripts/validate_review.py" \
  --paper-id <paper_id> \
  --review reviews/<review_run_id>/<paper_id>/reviewer-1.json

python "$OPENLABS_WORKSPACE/openlabs/workflows/paper/skills/openlabs-paper-review/scripts/validate_review.py" \
  --paper-id <paper_id> \
  --review reviews/<review_run_id>/<paper_id>/reviewer-2.json

python "$OPENLABS_WORKSPACE/openlabs/workflows/paper/skills/openlabs-paper-review/scripts/validate_review.py" \
  --paper-id <paper_id> \
  --review reviews/<review_run_id>/<paper_id>/review.json
```

Fix validation-only transcription errors in place. A substantive judgment change requires a new
reviewer context; any score-bearing manuscript change invalidates both reviews.

Apply the validated panel with:

```bash
python -m paper_writing review apply \
  --paper-id <paper_id> \
  --review reviews/<review_run_id>/<paper_id>/review.json \
  --venue-type <conference-or-journal>
```

The CAS Zone 1 decision remains the internal gate decision. Any unresolved blocker keeps the gate
out of `ready`. A ready gate does not authorize release, submission, publication, or any external
action.

Report both score vectors, the five conservative scores, both strictest simulated decisions,
retained blockers, validation and gate results, actual provider/model identities, and confirmation
that both reviewers used the same unchanged manuscript snapshot.
