---
name: openlabs-paper-writing
description: Shared OpenLabs manuscript workflow for every domain, from verified evidence through drafting, deterministic checks, supporting-material preparation and hand-off to the independent unified review. The domain entry skills (openlabs-ai-paper, -biology-, -materials-, -math-, -physics-, -quant-paper) point here and add a short domain section.
---

# OpenLabs paper writing

The repository owns state and evidence; this skill is the shared procedure. Principles are in
the code repository's `AGENTS.md`; user decisions (venue eligibility, review panel, round
limit, author defaults, cadence) are in the main data repository's `registry/settings.yaml`. Mechanical
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

Create a new paper with `paper-writing paper create` (also inside a campaign workspace or a
private review root). The record keeps `workspace: papers/<paper_id>` and every manuscript,
PDF and evidence path under `papers/<paper_id>/`; never `workspace: .` or a root-level
`manuscript/`. New records in other layouts are refused (existing ones only warn until
`program adopt` relocates them), and only this layout is delivered
from the data repository unchanged. The data and code availability statement names where
the material is: the archived support record's DOI, a URL, or the journal's supplementary
material (a delivery-exit check).

Identifiers and public file names: `../references/paper-identifiers.md`. Keep unpublished
material local unless external processing is authorized and compatible with the venue.

Load at most the three vendored components that `../profiles.yaml` declares for the domain,
from `workflows/paper/skills/vendor/`: the primary writing skill always, the domain component
(statistical-analysis or sympy) only when the paper needs it, and peer-review only in an
assigned reviewer role. Repository rules override vendored instructions; in particular the
`scientific-writing` sentence that it "does not generate images or schematics" is replaced by
`../openlabs-paper-figures/SKILL.md`: OpenLabs writers draw their schematics.

## Write

Select the article type and class from the [journal proof catalog](../../templates/journal-proofs/README.md). Compile the matching short sample, carry its measured column widths into the figure plan, and use the publisher’s current submission options for the actual manuscript. The Nature layout is a preview. Floats follow the figure skill: in a single-column layout use `figure[!htbp]` after the first citing paragraph, never `figure*` or `[t]` alone.

Use the owner's two to four takeaways and the claim–evidence map to draft one page in
`writing/storyline.md`: intended reader, question, decisive comparison, quantitative answer,
meaning, the limitation that changes interpretation and what belongs outside the main text.
Run `paper-writing story-review --paper-id <id>` once and use the editor’s reading before drafting. Draw the decisive figures first. Figure 1
orients the reader and each subsequent figure answers one question. Write Results from these
comparisons, with headings that state findings. Consult the readability and figure skills.

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
   toolchain, not to AI output. Never weaken a truthful disclosure. When you register or first
   draft the paper, also record the drafting model the runtime reports as `writer_model` (exact
   identifier, e.g. `gpt-6.2-sol`) and `writer_provider` (`openai-codex` or `anthropic`) in the
   paper record: the unified review needs a referee from another model family than this one.
7. Authors, CRediT roles, competing interests and funding use the standing defaults in
   `settings.yaml#defaults` (user instruction 2026-11-09) unless the paper record says otherwise;
   do not ask for routine reconfirmation, and do not treat the defaults as attestation of human
   review or code verification. Submission-facing files contain no pending-confirmation text;
   an unavoidable later portal action goes only in `production/human_action_checklist.md`.

## Choose the venue

Eligibility, routine versus escalation tiers, the ranking system and fees are defined in
`settings.yaml#journal_target_policy` and `#submission_cadence`; do not restate them from
memory. A fee-free route means no mandatory author fee of any kind: check and source page
charges, colour charges and submission fees as well as the APC (2026-11-12: a journal's
open-access page said "no APC" on the subscription route while its costs page levied a page
charge per typeset page). Before any shortlist or retarget run `paper-writing journal-history sync` and
`journal-history check --journal <title>` for every candidate. Record an evidence-backed
`target_journal_fit` (scope, core readership, contribution scale, two recent adjacent articles
from that venue, same-target history), the dated ranking source, the fee-free route and the
official format, and convert the canonical `manuscript/` itself to that format. Missing ranking
metadata is a lookup task; record `unverified` only after a genuine search fails or conflicts.
Look a journal up in the local registry of verified journals first
(`paper-writing venue lookup --journal <title>`; verified, eligible ones:
`paper-writing venue alternatives [--zone N] [--category <CAS major category>]`); go online only
for what it lacks. A publisher page that refuses you (HTTP 403/406, a challenge page) is not a
reason to stop for a human: record it with `paper-writing venue mark-pending --journal <title>
--url <url> --http-status <code> --reason <what> --by <model>` and continue with the journal
pending verification or switch to a verified alternative.
Handling a rejection: `docs/JOURNAL_HISTORY.md#handling-a-rejection`.

## Check, prepare support, hand off

1. Compile the real manuscript; run repository validation, `paper-writing style-check` and the
   declaration checks under the resource guard. The review only reports most of these findings
   as preparation advisories, but delivery requires them clean, so fix them while drafting.
2. Use reader-check or narrative-check when an outside reading would help.
3. Unless the record is `not_required` with a reason, prepare the Zenodo draft
   (`paper-writing zenodo prepare`, code-first per `docs/ZENODO_GUIDE.md`), cite its Version DOI
   in the bibliography, first substantive support mention and availability statement with
   wording that stays true after publication, then run `zenodo verify-draft` and
   `support-check`. Use the configured default licence without asking; surface a real licence
   conflict instead of changing files or licence silently.
4. Editorial rewriting is available on request.
5. In a factory `writer` task, stop at the frozen `paper_candidate`; never run or impersonate a
   reviewer. The scheduler starts a fresh `$openlabs-paper-review` task. On `paper_revision`,
   apply only the declared request; new evidence goes through `evidence_remediation` first.
   Requested qualifications, checks and explanations go to the appendix and the response letter
   where scientifically relevant. File checks and rerun logs go in the archive. Aim for zero net growth
   unless a referee placed the request in the main text (readability skill, section 5).
6. After a passing gate, run `paper-writing zenodo release` under the standing authorization,
   commit the DOI/receipt, then `paper-writing handoff release` (research-program papers are
   delivered by the orchestrator when `[program] auto_handoff` is on). None of this submits the
   paper, creates a journal event, or authorizes spending; those stay with a human.

## Finish

Report changed files, evidence gaps, checks and builds actually run, and remaining scientific
risks. If the paper is not ready, state the next bounded step instead of calling it
submission-ready.

## Field-bound topics

When the task activates a field skill, read it before drafting. The campaign
provides the field and line short name. In `paper create`, supply `--slug` with
scientific keywords in place of `--paper-id`. Keep the host domain and subject
subdomain in their existing CLI options. Reuse the registered ID for all
subsequent commands. Panel and independence rules come from the main data
repository's `registry/settings.yaml`.

示意图要承载数值与对比，不画纯方框流程。注明单位、样本或时间分辨率、对比基准和证据出处。教学参数须在图中标明，不能作为稿件结果。

Divide the figure work by what each tool does best: data result figures in matplotlib; principle, mechanism and system schematics first as SVG/HTML composed from the shared element library (`paper-writing figures assets`, templates `schematic-flow` and the field examples), with sized connectors and small data insets; TikZ for formula-dense theory diagrams. Schematics carry few formulas and little running text: show the mechanism with real objects, colour and line weight, label key quantities with units, and include the credit line the asset checker prints in the caption or acknowledgments.
