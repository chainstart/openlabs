---
name: openlabs-ai-paper
description: Run OpenLabs' evidence-bound AI/ML manuscript workflow from verified results through drafting, statistical checks, skeptical review, and the local quality gate. Invoke explicitly for AI or machine-learning papers in the OpenLabs data repository; use pinned components and never publish or submit as an implicit consequence of a passing gate.
---

# OpenLabs AI/ML paper profile

Use this as a thin coordinator. The repository owns state and evidence; vendored skills supply
writing, statistical, and review expertise.

## Establish the boundary

1. Resolve `paper_root` from `OPENLABS_DATA`, or from `$OPENLABS_WORKSPACE/openlabs-data`. It is the
   private data repository, not the code repository.
2. Read the code-owned `workflows/paper/skills/profiles.yaml` and
   `workflows/paper/skills/overlays/quality-gate.md`, then read
   `<paper_root>/registry/settings.yaml` and `<paper_root>/registry/papers/<paper_id>.yaml`.
3. Confirm that the user is authorized to process any unpublished or confidential material.
   Keep manuscript text local unless external processing is explicitly authorized and compatible
   with the target venue's current policy.
4. Validate every registered evidence bundle before drafting. Missing or contradictory evidence
   is a blocker, never an invitation to complete plausible prose.

Repository rules and the local overlay override every vendored instruction. Do not create
`paper_state.json`, `plan/progress.md`, `claims.csv`, a second source manifest, or a parallel
submission state. Translate useful upstream checks into the canonical OpenLabs artifacts:

- claims and provenance: `papers/<paper_id>/evidence/claim_evidence_map.md`;
- manuscript: `papers/<paper_id>/manuscript/`;
- revision notes: `papers/<paper_id>/revisions/`;
- internal reviews: `reviews/`;
- release status: `registry/papers/<paper_id>.yaml#writing_release`.

## Load only the needed components

Read component instructions from their installed paths before using them:

- Always load `workflows/paper/skills/vendor/ai-research-writing-skill/SKILL.md` for story, drafting, citation,
  figure/table, and build guidance.
- Load `workflows/paper/skills/vendor/statistical-analysis/SKILL.md` only for quantitative claims, test
  selection, assumption checks, effect sizes, power, or statistical reporting.
- Load `workflows/paper/skills/vendor/peer-review/SKILL.md` only when the assigned role is
  `reviewer`; a factory `writer` leaves review to the later `paper_review` task.

Never activate more than the three components declared by this profile. Do not install optional
statistics dependencies merely because the skill lists them; first establish that the paper needs
the analysis and that the existing environment cannot perform it.

Two vendored AI-writing scripts can access the network: `fetch_template.py` and
`verify_citations.py`. Use them only when the task requires that operation, never include
confidential manuscript text in a request, and record the source and access date. Image generation
is opt-in and illustrative only; it cannot supply experimental evidence.

## Work the paper

1. Inventory the verified evidence, current manuscript, venue constraints, and unresolved gaps.
2. Build or update the claim–evidence map before strengthening claims or adding numbers.
3. Establish the thesis, contribution boundary, and claims to avoid, then revise the canonical
   LaTeX directly. Preserve negative, mixed, incomplete, and null results.
4. For quantitative work, record the design, analysis population, assumptions, exclusions,
   multiplicity handling, uncertainty, effect sizes, code, data provenance, seeds, and versions.
   Do not choose an analysis after seeing which result is favorable.
5. Verify each citation's metadata and sentence-level support. A search result or related paper's
   bibliography is discovery material, not verification.
6. Compile the real manuscript and run repository validation plus all relevant local checks.
7. If public support materials are needed, prepare their local deterministic package and record
   missing metadata as a blocker. Creating even a reversible remote draft requires a separate,
   explicit administrator action with OpenLabs external writes enabled.
8. In a factory `writer` task, stop after freezing the compiled snapshot and emit it as a
   `paper_candidate`; do not run or impersonate either reviewer. The scheduler creates a fresh
   `paper_review` task using `$openlabs-paper-review`, whose Codex and Packy Claude Opus 5 reviewers
   apply the `cs_top_tier` standard and the mandatory local quality gate.
9. On a `paper_revision` task, apply only the declared review request. If new scientific evidence
   is needed, do not invent it; the reviewer must route an `evidence_remediation` task first. Freeze
   the revised snapshot as a new `paper_candidate` so both reviewers assess it again.

Only a `writing_release.status` of `ready` permits consideration for handoff. It does not mean the
paper has been submitted or accepted, and it never replaces human scientific judgment.

A passing gate authorizes only an internal state transition to `ready`. It never authorizes a
Zenodo release, remote handoff, submission, journal event, spending decision, or publication fact.
Those actions require a new explicit administrator instruction and the deterministic external-write
guard.

## Finish

Report the files changed, evidence gaps, checks and build commands run, and remaining scientific
risks. A reviewer additionally reports the review record and quality-gate result. If the gate is
not ready, state the next bounded revision rather than presenting the paper as submission-ready.
