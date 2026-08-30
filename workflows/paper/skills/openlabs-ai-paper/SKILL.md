---
name: openlabs-ai-paper
description: Run OpenLabs' evidence-bound AI/ML manuscript workflow from verified results through drafting, statistical checks, skeptical review, the local quality gate, and controlled supporting-material release. Invoke explicitly for AI or machine-learning papers in the OpenLabs data repository; use pinned components and repository release commands without creating parallel state.
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
   When creating a workspace or naming a reader-facing file, also read
   [paper-identifiers.md](../references/paper-identifiers.md).
   If support publication is required, also read `docs/ZENODO_GUIDE.md` in the code repository.
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
   Use neutral scholarly prose and keep prompts, agents, model orchestration, review/gate mechanics,
   private claim routing, source-audit narration (including `audit`, `auditable`, and
   `auditability`), internal audit/campaign filenames or paths, workflow notes in bibliography
   metadata, repository state, and `reader-facing` labels out of the scientific manuscript. Exact
   implementation names that remain in an immutable support archive belong in its replay
   documentation, not in reader prose. Preserve registered institutional names.
4. For quantitative work, record the design, analysis population, assumptions, exclusions,
   multiplicity handling, uncertainty, effect sizes, code, data provenance, seeds, and versions.
   Do not choose an analysis after seeing which result is favorable.
5. Verify each citation's metadata and sentence-level support. A search result or related paper's
   bibliography is discovery material, not verification.
6. Require exactly one final venue-compatible AI-use declaration and consolidate truthful AI use
   there. Identify OpenAI GPT-5.6 through Codex and its actual purposes, including source-code
   development and computational verification when applicable; state the human checks performed.
   If Codex assisted Lean work, disclose preparation/checking of Lean code and attribute formal
   checking to the pinned Lean toolchain rather than to AI output. Do not weaken a truthful
   disclosure to conceal AI use.
7. Compile the real manuscript and run repository validation plus all relevant local checks,
   including `python -m paper_writing style-check --paper-id <paper_id>`. A failure blocks review.
8. If the support DOI belongs in the paper, resolve the public files and license from the registry's
   `support.publication`, then use `paper-writing zenodo prepare` to create only a reversible draft.
   Add the reserved Version DOI with publication-state-neutral wording, run
   `paper-writing zenodo verify-draft`, and rebuild before final review. Never choose a license
   yourself or add confidential files to the public set; treat either gap as a blocker.
9. In a factory `writer` task, stop after freezing the compiled snapshot and emit it as a
   `paper_candidate`; do not run or impersonate either reviewer. The scheduler creates a fresh
   `paper_review` task using `$openlabs-paper-review`, whose Codex and Packy Claude Opus 5 reviewers
   apply the `cs_top_tier` standard and the mandatory local quality gate.
10. On a `paper_revision` task, apply only the declared review request. If new scientific evidence
   is needed, do not invent it; the reviewer must route an `evidence_remediation` task first. Freeze
   the revised snapshot as a new `paper_candidate` so both reviewers assess it again.

Only a `writing_release.status` of `ready` permits consideration for handoff. It does not mean the
paper has been submitted or accepted, and it never replaces human scientific judgment.

After a basic manuscript is complete, select a target journal verified as Tier 1 or Tier 2 in an
allowed domain-specific 2026 XinRui system, with a publication route carrying no mandatory author
fee. Record ranking, fee, and official formatting sources and check dates. Convert the canonical
`manuscript/` itself to the current venue format; a separate candidate does not satisfy this rule.

After a passing gate, run `paper-writing zenodo release` for the prepared production draft without
asking the user again; the gate is the authorization. Skip it only when venue policy forbids public
support materials. Commit its DOI/receipt update before `paper-writing handoff release`. A passing
score still never authorizes a submission, journal event, or publication fact.

## Finish

Report the files changed, evidence gaps, checks and build commands run, and remaining scientific
risks. A reviewer additionally reports the review record and quality-gate result. If the gate is
not ready, state the next bounded revision rather than presenting the paper as submission-ready.
