# OpenLabs paper checks and registry fields

Reference for the deterministic checks and registry fields used by every paper profile. The
workflow is in `../openlabs-paper-writing/SKILL.md`; policy values (venue tiers, fees, ranking
system, cadence, review panel, round limit) are in `registry/settings.yaml`, which is the only
source of thresholds. With `quality_gate.review_process: unified_v1` (user decision 2026-10-06)
the only route to `writing_release.ready` is `review unified-run` (`openlabs-paper-review`,
`workflows/paper/docs/UNIFIED_REVIEW_DESIGN.zh.md`). The older score threshold, CAS Zone 1
decision standard, separate editorial screen, delta and closeout routes and metadata reuse are
gone; their records stay readable (documents in `docs/archive/` and
`workflows/paper/docs/archive/`).

The formal checks below (style, AI declaration, abstract format, support record, unused
sources) do not stop a review: the review records them as `preparation_advisories`, and the
delivery exit (`handoff release`, `zenodo release`) requires them clean. A formal slip should
not cost a scientific review round, but it must not reach a journal either.

## Journal targets

Exclude every title and alias in `settings.yaml#journal_target_policy.excluded_journals` (EPJC
and JHEP, user instruction 2026-09-12: both effectively require prior arXiv posting). For a
replacement journal check whether prior arXiv posting is mandatory; permission to post a
preprint is not a requirement. Keep truthful historical submissions; never swap a target for an
alias or erase history.

Team rejection ledger: `docs/JOURNAL_HISTORY.md` (sync/check commands, thresholds in
`settings.yaml#journal_target_policy.team_rejection_history`). Each team paper counts once per
journal; conference rows and withdrawals do not count; a missing, invalid or stale ledger blocks
new selection. Registry validation, unified preflight and handoff enforce the exclusion; an
ongoing submission sourced from the management API may continue its existing revision. Keep the
separate per-paper `journal_rejections` list as well.

Registry fields for a journal target checked on or after `venue_eligibility.effective_from`:
`target_journal_tier` (the numeric 2025 CAS major-category zone), `target_journal_ranking_year:
2025`, `target_journal_ranking_scope: major_category`, the category name, a dated source and
check date; `target_journal_fee_policy: no_mandatory_author_fee`; `target_journal_indexing` with
`journal`, `indexes` containing `SCIE`, an HTTP(S) `source` and `checked_at`. The canonical
`manuscript/` must be marked and checked as the venue-specific edition; a side candidate alone
is a blocker. Public Zenodo ZIP names and roots use the registered `display_id`.

A conference target:

```yaml
venue_type: conference
target_conference: International Conference on Example Learning 2027
target_conference_checked_at: '2026-11-07'
target_conference_ccf: {rank: C, category: 人工智能, edition: '2026',
                        source: 'https://www.ccf.org.cn/...', checked_at: '2026-11-07'}
target_conference_fee_policy: no_mandatory_publication_fee
target_conference_fee_source: https://example.org/registration
```

An escalation target (Zones 1-2 or CCF-A) additionally needs:

```yaml
target_escalation:
  status: approved
  venue: <exact target name>
  approved_by: <human author who approved the escalation>
  approved_at: '2026-11-07'
  internal_review_score: 7
  internal_review_source: reviews/unified/<record>.json
  strength_evidence: why this result is broader than the routine venue
  fallback_venue: <eligible routine venue used after an escalation rejection>
```

The unified review states its track: routine targets are judged at the venue's actual level,
escalation targets at full selectivity (`quality_gate.review_standard`, user decision
2026-11-07).

Escalate only after a result passed the routine gate with margin; after one escalation rejection
return to the recorded fallback venue instead of descending venue by venue. Research-program
topics admitted with `target_tier: escalation` in `research_state.json` are the exception:
register the paper with `paper-writing program register-escalation --paper-id <id> --venue
<escalation venue> --admission-task-id <admission_task_id> --admission-record
<admission_record.path> --fallback-venue <first routine venue>`. This `provisional` record allows
the escalation-track review; delivery at that target needs the ready review's score, after which
the record becomes `approved`.

Distinct external rejections of this paper go in `journal_rejections`, reconciled with actual
decision letters:

```yaml
journal_rejections:
  - journal: Example Journal
    manuscript_number: EXAMPLE-26-001
    rejected_at: '2026-09-19'
    source: maintenance/decision-audit/decision-receipt.json
```

Desk rejections and rejections after review count; withdrawals, transfer suggestions, internal
LLM decisions and unverified claims do not. Use one canonical title and manuscript number across
duplicate letters; never infer a count from revision numbers or overwrite history.

Targets checked after the fit-policy date also need an approved `target_journal_fit` record:
scope, core readership and contribution scale, each justified; the official scope and at least
two recent topically adjacent articles; a shared-history check. A prior rejection at the same
target blocks reselection until a material scientific revision is identified; reformatting,
reframing or a new cover letter is not one.

Before every actual submission (a human action) run `paper-writing cadence check --venue <venue>
--paper-id <id>` after `journal-history sync` (`settings.yaml#submission_cadence`). Combine
closely related narrow results into one manuscript instead of parallel submissions.

New empirical papers (`venue_eligibility.empirical_real_data.domains`) list `data_sources`: each
row has `name`, `kind` (public_dataset, experimental_measurement, observational_survey,
clinical_or_cohort_registry, field_or_sensor_record, benchmark_with_real_samples; simulation,
synthetic and derived_model_output only alongside real data), an HTTP(S) `source` or `doi`,
`version` or `accessed_at`, and `license_or_access`; plus short reader-facing `key_findings`.

## Editor-facing rewrite pass and cross-model review

User decision 2026-11-07 (blind experiment: rewriting the opening and closing helped in every
model; each model judge preferred its own model's text 4/5):

- Once per target checked on or after `quality_gate.editorial_rewrite.required_from`, before
  its first unified review, run `paper-writing rewrite run <paper_id> [--apply]`. Only a
  missing pass stops the review; its verdict is advice recorded with the review. Each
  configured rewriter rewrites only the abstract, Introduction and closing section in a fresh
  process; judges of both families rank the original and candidates blind. A candidate is used
  only if it passes the deterministic checks (no new citation keys, labels kept, references
  resolve, length within the hard limit), no judge finds a major fidelity issue, every judge
  ranks it above the original, and every judge scores naturalness, restraint, clarity and venue
  fit at least 7/10, affirms `editorial_ready` and reports no located `editorial_blockers`.
  When no version meets these floors the pass ends `editorial_failed`, which the review also
  receives as advice. Necessary qualifications and truthful disclosures stay. Later source
  changes do not trigger a rerun; keyword densities are diagnostics.
- The panel is configured in `settings.yaml#review`; `review.cross_model.required` blocks a panel
  in which every referee is of the drafting model's family (another version of the same family
  does not count). The drafting model is the paper record's `writer_model`; without it the
  review falls back to `review.writer_model` and notes that it was not registered. Never let the
  drafting model's family be the only judge of its own text in an ad-hoc comparison either.

## AI-use disclosure

Author default 2026-10-24: use the short tool/purpose template in the data repository's
`registry/paper-declarations/templates.yaml` (selected by `default_ai_template_id`) unless the
venue requires another format; heading "Declaration of generative AI and AI-assisted
technologies in the manuscript preparation process". Fill it with the actual tool, evidenced
model identifiers and purposes; never copy another paper's model list. The clause that authors
reviewed and edited the output is a factual attestation: omit it when unsupported. Detailed
provenance stays in private records.

Register each use under `declarations.ai_use.model_usage` with `provider: openai-codex`, `tool:
Codex` or `provider: anthropic`, `tool: Claude Code`, `model`, purpose, and `evidence: {path,
sha256, json_pointer}` pointing to a bounded JSON runtime record under the data root. The
checks compare the tools and identifiers named in the statement with the registered usage and
verify hash and pointer; an empty list, changed record or invented identifier blocks delivery. Papers before 2026-09-06 without
structured metadata keep their legacy textual check; never rewrite an old model identity to a
newer name. Model provenance does not attest that humans inspected or ran code; if human checks
have not happened, say so and keep the blocker.

## Voice and readability

Apply `../openlabs-paper-readability/SKILL.md` for every domain: contribution, structure and
argument before sentence polish, preserving meaning. The final manuscript is neutral and
impersonal; revision negotiation, self-review responses and predictions about editorial
interest stay in private revision records. Referees reconstruct problem, result, scope,
literature difference and argument with locations (`openlabs-paper-review/references/`);
substantial exposition problems are required changes, not minor revision. `style-check` is
mechanical and does not assess readability, logic or novelty; with
`quality_gate.editorial_voice.blocking: true` its voice warnings become delivery errors.

## style-check and support-check

`paper-writing style-check --paper-id <paper_id>` scans the compiled TeX tree and bibliography
and rejects AI/tool narration outside the final declaration, internal paths, unresolved markers
and pending-confirmation text. Internal-vocabulary words (`audit`, `quality gate`, `claim map`,
preparation chronology and similar) are only reported with their sentence, because the same
words are legitimate subject matter in some papers; a human judges them before delivery. A registered institutional name is allowed. A publisher-required image
credit may appear in that image's caption through `artwork_disclosures` (hash-bound image and
generation record, one occurrence). Lean work: disclose Lean-code preparation and attribute
formal verification to the pinned toolchain.

`paper-writing support-check --paper-id <paper_id>` checks formal TeX and standalone
reproducibility/availability statements: the current Zenodo Version DOI is cited with current
metadata and title; wording is version-stable with no draft/release history and no public-access
claim for an unpublished draft; the licence resolves from the paper override, then
`support_publication.default_license` (a standing human choice; surface real conflicts). It
inspects the exact registered ZIP: source label, package version, packaged claim map/README and
DOI agree; every printed path exists at its declared archive base; nested payloads carrying this
paper's metadata match the current record; integrity prose matches the actual inventories.
Counts of commands, checkers, tests or certificate groups come from the exact package.

## Lean evidence

When a Lean project is in scope, run one resource-capped audit per frozen snapshot before review
and give the receipt to every reviewer; reviewers never rebuild Lean or mathlib. Choose the mode
from the Lean-input delta (`settings.yaml#lean_audit_policy`): unchanged Lean sources, toolchain,
Lake configuration and lock reuse the PASS receipt (`--reuse-pass-receipt` or
`--reuse-build-report`) even if the manuscript, DOI or support archive changed; a local source
change uses `--build-mode incremental` then the axiom audit; only toolchain, dependency,
configuration or foundational-interface changes use `--build-mode full`. A diagnosed
interruption may continue the same build with a hash-linked receipt; axiom validation runs at
most once over the chain. Disclose whether validation was reused, incremental or full.

## Publication stays outside the gate

The gate never uploads files or publishes. A review does not need a Zenodo draft of the current
version: a selected claim-evidence map in `support.publication.source_files` is read from the
registered source (bound by `support_sources_sha256`; `SUPPORT-CLAIM-MAP-UNPACKAGED` advisory
when it is not yet in the current-version ZIP), and the delivery exit requires it packaged. Before
delivery run `zenodo prepare` (`zenodo verify-draft`), cite the reserved DOI neutrally (through
`references.bib` or `\url{https://doi.org/...}`), rebuild and rerun the review (a DOI/version-only
change is a delta review); the decision records the support package hash. Uploads are code-first
(`docs/ZENODO_GUIDE.md`, `support_publication.package_policy`): a missing unique input is not a
removable intermediate. After a passing gate, `zenodo release` runs under the standing
production authorization with its production and exact-paper confirmations and revalidates
every binding. Readiness or support publication never authorizes a submission, journal event or
publication claim. Author-approval reminders and internal checklists stay out of the manuscript
and `journal-submissions/`; a genuinely required later human action goes only in
`papers/<paper_id>/production/human_action_checklist.md`, outside the upload package.
