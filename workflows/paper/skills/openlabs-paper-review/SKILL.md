---
name: openlabs-paper-review
description: Perform OpenLabs' three-agent, parallel, fresh-context review panel for AI, computer-science, software-engineering, mathematics, or materials-science manuscripts. Use when scoring one frozen manuscript, producing three independent immutable reviews and their median panel result, or rerunning the internal quality gate after score-bearing changes; keep scripts limited to routing, provenance, and exact median validation.
---

# OpenLabs paper review

Make scientific judgments only inside the three reviewer contexts. Use deterministic helpers to
verify inputs, immutable provenance, output structure, and exact medians; never let a script
originate, round, raise, or lower an individual score.

## Establish the review boundary

1. Resolve the private paper root from `OPENLABS_DATA` (or `$OPENLABS_WORKSPACE/openlabs-data`) and read
   `registry/settings.yaml`. From the code repository read `workflows/paper/skills/profiles.yaml`
   and `workflows/paper/skills/overlays/quality-gate.md`. The coordinating context reads the
   selected paper registry in full. Before launching reviewers it must derive a review-safe view of
   that same current registry with the top-level `ara_llm_self_review`, `writing_release`, and
   `review_file` fields removed, and with the nested
   `support.publication.release_binding` mapping removed in full. Do not retain its snapshot, score,
   target, decision, or package-binding fields. Each reviewer reads only that review-safe view; it
   must never open, search, or use Git history to recover the unredacted registry. This preserves
   authors, evidence, and current support metadata without leaking a prior score, decision,
   blocker, or review path.
   Generate the view in memory or print it directly with
   `paper_writing.review.review_safe_registry`; do not create a parallel registry artifact and do
   not hand-maintain a second redaction rule in reviewer prompts.
   Historical preflight/review artifacts may also exist inside `papers/<paper_id>/manuscript/`.
   Reviewers must not list-and-open or recursively search the whole paper/manuscript tree. Build the
   review source list from the canonical main file's transitive TeX inputs plus its bibliography,
   and restrict unresolved-marker searches to that explicit list. Never open a filename containing
   `review`, `preflight`, `score`, or `decision`; open validation/README metadata only when the
   coordinator has first confirmed that it contains no prior-review projection.
   Before launching the panel, the coordinator must also scan every text-readable artifact in the
   registered review input and current public-support archive for embedded prior judgments. Remove
   reviewer/editor verdicts, venue or publishability assessments, novelty/gate outcomes, and
   internal campaign status from the reader-facing package, rebuild the draft, and freeze the new
   package hash before review. Treat prose such as “potentially publishable,” “suitable for
   publication,” “publication assessment,” “passed the audit,” venue-tier readiness, and requested
   accept/revise/reject outcomes as evaluative projections even when no numeric score is present.
   Exclude a document whose primary purpose is an earlier proof/reviewer audit; do not retain its
   verdict by merely changing a status label. A deterministic checker reporting its own execution status (for
   example, `status=PASS` after exact assertions) is evidence replay rather than a prior review and
   may remain. Do not delegate this hygiene check to reviewers: if an evaluative projection is
   discovered during review, invalidate that context and restart the complete three-agent panel on
   a clean, common frozen input.
   Run the bounded recursive archive checker against every registered ZIP supplied to reviewers
   and the exact current Zenodo ZIP before launching them:

   ```bash
   python "$OPENLABS_WORKSPACE/openlabs/workflows/paper/skills/openlabs-paper-review/scripts/check_input_hygiene.py" \
     --archive <registered-evidence.zip> --archive <current-support.zip>
   ```

   A nonzero result is a pre-review blocker. The checker supplements, rather than replaces, direct
   inspection of the explicit review inputs.
2. Confirm authorization for unpublished material. Do not send it to another service unless the
   user has explicitly authorized that processing and it is compatible with venue policy.
3. Freeze and hash one canonical manuscript snapshot after drafting and deterministic checks.
4. Launch exactly three fresh reviewer agents in parallel. Give each the same paper ID, frozen
   snapshot, this skill, and repository instructions. Do not give them earlier review prose,
   scores, suspected defects, intended outcomes, or sibling outputs. Do not run the three reviews
   sequentially as a substitute for independence. If a reviewer sees any unredacted prior-review
   projection, discard that entire reviewer context and replace it with a fresh one.
5. Assign stable IDs `reviewer-1`, `reviewer-2`, and `reviewer-3` and unique immutable output paths
   under one run directory. Each reviewer must set `independent_context: true`,
   `prior_reviews_hidden: true`, and its matching `panel_reviewer_id`.
6. Review only. No reviewer may edit the manuscript, evidence, registry, or another review. Hash
   the canonical manuscript snapshot before and after every review. If three genuinely fresh
   parallel agents are unavailable or any snapshot changes, leave the gate pending.

## Run formal-tool audits once, outside the panel

When the frozen evidence includes a Lean project, the coordinator may appoint one separate,
objective Lean checker or run the bounded checker itself. This checker is not a fourth reviewer,
does not score the paper, and must finish before the three content reviewers are launched. Use one
snapshot-bound audit workflow and give its immutable receipt to all three reviewers:

```bash
python "$OPENLABS_WORKSPACE/openlabs/workflows/paper/skills/openlabs-paper-review/scripts/run_lean_audit.py" \
  --paper-id <paper_id> \
  --project <repo-relative-lean-project> \
  --audit-file <project-relative-axiom-audit.lean> \
  --manuscript-snapshot <sha256> \
  --support-sha256 <sha256> \
  --output reviews/objective-audits/<paper_id>/<snapshot>/lean.json
```

The command serializes Lean work with a host lock and defaults to two Lean threads, two-core CPU
affinity, 16 GiB aggregate descendant RSS, 24 GiB per-process virtual address space, 12 descendant
processes, and a 60-minute wall-clock limit. Repository maxima are four threads, 24 GiB aggregate
RSS, 32 GiB virtual address space per process, 24 processes, and 60 minutes. Preflight also reserves
at least 8 GiB or one quarter of total WSL memory, whichever is larger. The virtual-address
ceiling is intentionally wider than the actual-RSS ceiling because Lean reserves thread stacks and
memory mappings that are not resident memory. Do not exceed those maxima inside a skill or reviewer
prompt. The checker also requires memory/disk headroom, lowers scheduling priority, terminates the
whole process group on a limit breach, and reuses an exact matching PASS receipt instead of
rebuilding. Do not run `lake update` during review: the frozen `lake-manifest.json` and toolchain are
inputs, not files to refresh.

Every reviewer receives the same objective receipt and source hashes, but no reviewer runs
`lake build`, `lake update`, `lake env lean`, or a second formal-tool reconstruction. Reviewers
independently assess the written proof, formulas, assumptions, novelty, significance, exposition,
and the stated boundary of the formal certificate. A resource-limit or timeout result is not a
license to retry in reviewer contexts. The coordinator may resume the same hash-bound incremental
build after diagnosing a guard failure, but the formal axiom-validation command may execute only
once across the receipt chain. If a central claim materially
depends on a successful formal audit and no valid receipt exists, retain an evidence blocker.

## Select the domain rubric

Read `references/rubrics.md` completely, then select from the registry's literal `domain`:

- `ai`, `cs`, or `se`: use `cs_top_tier`. Judge the numeric scores as a top-tier computer-science
  conference reviewer, such as NeurIPS, ICML, or ACL, even when the paper is currently aimed at a
  journal. Produce a top-conference recommendation and a separate, less selective CAS Zone 1
  journal recommendation.
- `math`: use `math` with rubric `math_four_journals`. Judge every numeric score against the shared
  standard of *Annals of Mathematics*, *Inventiones Mathematicae*, *Journal of the American
  Mathematical Society*, and *Acta Mathematica*. Do not replace proof review with computational
  checks and do not relax the score because the current target venue is less selective. Produce a
  four-leading-journal recommendation and a separate, less selective CAS Zone 1 journal
  recommendation. Never produce a conference recommendation for mathematics.
- `materials`: use `materials` with rubric `materials_leading_journals`. Judge physical validity,
  structure/model provenance, numerical convergence, independent references, sampling units,
  uncertainty, mechanistic inference, and reproducibility. Produce a `leading_materials_journals`
  recommendation and a separate CAS Zone 1 journal recommendation; do not produce a conference
  or mathematics-journal view.
- any other domain: stop and add an explicit rubric before scoring.

A named target journal may add a venue-fit note, but it does not replace the base domain rubric.
Treat “CAS Zone 1” as the major-category partition configured by the repository. Never claim that a
specific target is currently Zone 1 unless its current classification and scope were verified from
an identified source. Otherwise use the generic field-appropriate Zone 1 standard and record lower
venue-fit confidence.

## Inspect the complete frozen paper

1. Read the compiled PDF and every transitively included canonical LaTeX and bibliography file.
   Do not substitute a recursive manuscript-directory search, because non-canonical historical
   review files in that directory are outside the frozen paper and break blinding.
2. Read the claim-evidence map and validate every registered result bundle. Inspect the registered
   artifacts needed to test central claims; do not treat a hash alone as scientific validation.
   For Lean evidence, inspect the coordinator-supplied objective receipt and source binding; do not
   rebuild Lean or mathlib inside a score-bearing reviewer context.
3. Check build freshness, citations, unresolved markers, theorem/proof dependencies, statistical
   design, and reproducibility as applicable to the selected rubric.
4. Run `python -m paper_writing support-check --paper-id <paper_id>`. Treat internal Zenodo
   workflow narration, a support-record title that identifies a prior rather than current paper
   title, a standalone reproducibility heading that names a different paper, an unknown or legacy
   claim ID in that standalone statement, a stale Version DOI/title/version/creator list, an
   uncited first support mention, a false public-access claim, a replay/checker/test count that
   contradicts the exact current package, a false outer-root claim for a nested archive member, or stale record
   identity inside the exact ZIP's outer or nested CFF/manifest/README, or a README claim that
   overstates the actual `SHA256SUMS`/manifest inventory coverage, as a formal blocker;
   reviewers must not ask the paper to explain draft-to-release history.
5. Treat missing or contradictory evidence, invalid inference, proof gaps, and unsupported central
   claims as blockers. Do not repair them during scoring.

## Assign independent scores and simulated decisions

Read `references/review-schema.md` completely before writing the result.

- Assign `clarity`, `soundness`, `significance`, `novelty`, and `overall` as integers from 1 to 10.
- Do not use decimals. If the judgment lies between two levels, choose the lower integer and state
  the uncertainty in the rationale.
- Treat `overall` as a conservative holistic judgment, not an arithmetic average.
- Apply the role-specific score anchors in `references/rubrics.md`. For mathematics, technical
  correctness alone does not establish four-journal novelty, significance, or overall readiness.
- Do not tune a result to cross the repository floor or coordinate with another reviewer. Most submission-stage papers should score
  5--7; reserve 8 or above for genuinely strong, well-evidenced work.
- Produce exactly the two role-specific recommendation views independently:
  - `ai`, `cs`, `se`: seven-point `top_conference` plus five-point
    `cas_zone_1_journal`;
  - `math`: five-point `four_top_math_journals` plus five-point
    `cas_zone_1_journal`; no conference view.
- The CAS Zone 1 bar is deliberately lower than the high standard, but it still requires a sound,
  meaningful, well-supported contribution. Do not mechanically derive it by shifting the high-
  standard label.
- Use `minor_revision` only when no new central proof, experiment, data, analysis, or claim is
  required. A scientific blocker prevents an accept recommendation even if the numeric average is
  high.
- Mark both recommendations as simulations. They are not actual editor, program-committee, or
  external-review decisions.

## Aggregate the panel

Only after all three immutable individual records exist may the coordinating context read them.

1. Take the coordinate-wise median of the three integers for `clarity`, `soundness`,
   `significance`, `novelty`, and `overall`. The final `overall` is the median of the three
   reviewers' holistic `overall` judgments, not an average and not a value recomputed from the
   other four medians.
2. Order each decision vocabulary from most favorable to least favorable exactly as in
   `references/rubrics.md` and take its ordinal median independently for the high-standard and CAS
   Zone 1 views. Never convert decisions to scores or shift one venue view mechanically.
3. Synthesize strengths, weaknesses, section feedback, and required changes without changing the
   medians. For a blocker raised by only one reviewer, verify the cited artifact: retain it when
   confirmed or uncertain, and document why it is excluded only when the frozen evidence directly
   disproves it. Never vote away a real proof or evidence defect.
4. Write the final panel record with schema `ara.paper_writing.review.v3`, immutable references and
   SHA-256 hashes for all three `v2` source reviews, and the required panel metadata from the schema
   reference.

The coordinating context may use the auxiliary mechanical aggregator after it has inspected all
three completed records. The helper calculates only required medians, decision medians, hashes,
and lossless unions of findings and blockers; it never reads the manuscript or originates a score:

```bash
python "$OPENLABS_WORKSPACE/openlabs/workflows/paper/skills/openlabs-paper-review/scripts/aggregate_panel.py" \
  --paper-id <paper_id> --review-dir reviews/<review_run_id>/<paper_id> \
  --objective-audit reviews/objective-audits/<paper_id>/<snapshot>/lean.json
```

Omit `--objective-audit` when Lean is not in scope. When supplied, the panel carries the single
shared receipt and the validator checks its file hash, frozen-input bindings, one-execution marker,
source hashes, successful sequential commands, and resource ceilings without rerunning Lean.

Inspect the generated consensus record before applying it. If a duplicated finding needs editorial
condensation, change only the consensus prose; never change a source judgment, score, decision,
source hash, or retained blocker.

## Record and validate

1. Write `reviewer-1.json`, `reviewer-2.json`, and `reviewer-3.json` under
   `reviews/<review_run_id>/<paper_id>/`, then write the aggregate as `review.json`, using the
   schema reference. Include model, reasoning effort, UTC time, paper ID, role, main-TeX SHA-256,
   before/after snapshot hashes, and `manuscript_unchanged` in every source record.
2. Run the auxiliary validator on each individual `v2` record and then on the aggregate `v3`
   record. It checks routing, integer scores, metadata, role-specific views, immutable source
   hashes, common snapshots, and exact medians without judging the paper:

   ```bash
   python "$OPENLABS_WORKSPACE/openlabs/workflows/paper/skills/openlabs-paper-review/scripts/validate_review.py" \
     --paper-id <paper_id> \
     --review reviews/<review_run_id>/<paper_id>/reviewer-1.json

   python "$OPENLABS_WORKSPACE/openlabs/workflows/paper/skills/openlabs-paper-review/scripts/validate_review.py" \
     --paper-id <paper_id> --review reviews/<review_run_id>/<paper_id>/review.json
   ```

3. If validation fails, fix only structural or transcription errors. Do not change a substantive
   individual judgment outside a new three-agent panel.
4. Register the immutable panel result and apply the quality gate with the auxiliary recorder. It
   validates the skill-authored records and manuscript hashes, copies the median score and
   recommendations into the registry, and invokes the stable gate; it never originates or changes
   a score:

   ```bash
   python -m paper_writing review apply \
     --paper-id <paper_id> \
     --review reviews/<review_run_id>/<paper_id>/review.json \
     --venue-type <conference-or-journal>
   ```

   Keep `--venue-type` equal to the actual target venue type. The CAS Zone 1 recommendation remains
   the gate decision regardless of target venue type. Never round the score. By default the helper
   preserves the registry's completed revision-round count; pass `--revision-rounds` only when a
   real revision round was completed.
   A non-empty `unresolved_blockers` list keeps `writing_release` out of `ready` even when the
   numeric score and CAS decision meet their thresholds. Resolve the evidence/scientific blocker
   or create a new review after a real revision; never delete a blocker merely to pass the gate.
5. Any later score-bearing manuscript change invalidates the complete panel and requires three new
   immutable independent reviews on the new snapshot.
6. A `ready` gate is internal evidence about manuscript readiness only. It does not authorize a
   Zenodo release, remote handoff, submission, journal event, or publication fact. Retain blockers
   based on scientific evidence, not on a desired external outcome.
7. Do not record a blocker merely because the controlled registry says `status: draft`. Between
   `zenodo prepare` and `zenodo release`, the active `support.publication.version_doi`,
   `zenodo.reserved_version_doi`, and `zenodo.version_doi` all identify the prepared current version;
   any earlier public identity is internal history under `zenodo.previous_published`. A reserved DOI
   resolving to 404 before release is expected, as is `writing_release.support_package_sha256`
   lagging until the next `review apply` rebinds it. Check that the manuscript uses neutral,
   future-stable wording, cites the current DOI, and makes no claim of present public access. The
   formal manuscript must not narrate the draft/reservation/release transition. See
   `docs/ZENODO_GUIDE.md`.

Report all three score vectors, the five integer medians, both median role-specific simulated
decisions, retained blockers, validation result, quality-gate result, and confirmation that every
reviewer saw the same unchanged manuscript snapshot.
