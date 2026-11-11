# OpenLabs paper workflow

Before recommending or changing a journal, run `paper-writing journal-history sync` and
`journal-history check --journal <title>`; see [JOURNAL_HISTORY.md](../../docs/JOURNAL_HISTORY.md).
All policy values live in the data repository's `registry/settings.yaml`.

This is the deterministic half of paper production: registry validation, evidence bundles,
manuscript inventory, the unified review's preflight, merge and record binding, delivery checks,
support checks, and immutable package construction. Writing and scientific judgment stay in the
domain-specific OpenLabs paper Skills and their pinned vendored components.

By default, the workflow reads private state from `$OPENLABS_DATA`, or from
`$OPENLABS_WORKSPACE/openlabs-data`. Pass `--root` for an explicit paper repository. The migrated data layout
keeps `registry/`, `papers/`, and `reviews/` directly under that root.

## Paper identifiers

New papers use the immutable ID `YYYYMMDD-domain-subdomain-keywords`; the date is the workspace
creation date and the domain/subdomain segments must match the registry. Keywords describe the
scientific subject, not an OpenLabs question, task, round, or workstream number. New `display_id`
values equal `paper_id`; legacy technical IDs remain immutable but receive a compliant
domain-scoped `display_id` for public use.

Reader-facing PDFs use `<display_id>-v<MAJOR.MINOR.PATCH>.pdf`. Obtain the exact filename with:

```bash
PYTHONPATH=workflows/paper python3 -m paper_writing paper public-name \
  --paper-id 20260828-physics-hep-p5-chain-bootstrap \
  --root "$OPENLABS_WORKSPACE/openlabs-data"
```

The complete policy, including public support archives and legacy migration, is in
[`docs/PAPER_ID_POLICY.md`](../../docs/PAPER_ID_POLICY.md).

```bash
PYTHONPATH=workflows/paper python3 -m paper_writing validate \
  --root "$OPENLABS_WORKSPACE/openlabs-data"
```

Every post-basic-draft target must satisfy `registry/settings.yaml#journal_target_policy`
(venue eligibility, 2025 CAS major-category zone stored in `target_journal_tier`, fee-free route,
canonical venue format, evidence-backed fit); field details are in
[quality-gate.md](skills/overlays/quality-gate.md).
`style-check` and `support-check` findings are advisories during review and hard requirements
at delivery (handoff and `zenodo release`). See
[`docs/ZENODO_GUIDE.md`](../../docs/ZENODO_GUIDE.md) for controlled support-material publication.

Remote handoff and pre-gate Zenodo mutations are disabled by default and need
`OPENLABS_ENABLE_EXTERNAL_WRITES=1` for one explicit operation. Two standing exceptions exist:
`zenodo release` for a current `ready` gate (it revalidates every binding), and, when the
orchestrator's `[program] auto_handoff` is on, delivery of ready research-program papers to the
management site without a submission handler (`paper-writing program deliver`). Neither
authorizes manuscript submission, a journal event, spending, or a publication claim.

## Review and readiness

The only route to `writing_release.ready` is `review unified-run`
([openlabs-paper-review](skills/openlabs-paper-review/SKILL.md)); panel, models and round limit
come from `registry/settings.yaml#review`. The pre-unified scored panel, delta and closeout
commands and per-paper revision-round exceptions are gone or refuse to run; existing
`quality_gate_revision_exception` and closeout records are still revalidated when an old
release is read. Their former instructions are in
[legacy-SKILL-before-20261006.md](skills/openlabs-paper-review/references/archive/legacy-SKILL-before-20261006.md)
and [docs/archive/](docs/archive/) (including the minor-closeout and round-exception contract).

## Reusable paper declarations

Paper-bound declarations live in the data repository at
`registry/papers/<paper_id>.yaml` under `declarations.author_contributions` and
`declarations.ai_use`. The extracted copies and reusable, author-name-keyed templates
are in `registry/paper-declarations/`. See that directory's README before reuse.

New model-use disclosures use `declarations.ai_use.model_usage`: record the actual tool (Codex
or Claude Code), model and a hash-bound local JSON runtime source (`evidence.path`, `sha256`, and
`json_pointer`). Both declaration and style checks verify this binding. No model version
is mandated globally; old model names are not automatically relabeled, and a scaffold
with no recorded model remains blocked. This does not certify human checking of code
or relax any publication gate. See the shared quality overlay for the precise contract.
Do not reuse an entire contribution paragraph across different byline orders: render
the explicit `authors[].credit_roles` in the destination paper's order. Never promote
delegated draft allocations or inherited human-code-verification language to new
author confirmations. Publisher-level guidance is not a verified journal-specific
exemption from a statement requirement.

Validate the canonical source, all-author role coverage, order, exact statement text,
and normalized-text SHA-256 (from the code repository):

```bash
bin/openlabs-resource-guard -- env PYTHONPATH=workflows/paper \
  python3 -m paper_writing.declarations --root ../openlabs-data --paper-id PAPER_ID
```

Add `--latex` to extract the already bound declarations. A deterministic PASS is a
text/metadata consistency result, not evidence of actual contributions, completed
code verification, journal-policy acceptance, or authorization to submit.

## Release boundary

The repository default treats the registered author list, order, affiliations, CRediT allocation,
funding statement, competing-interest statement, data statement, and truthful AI-use declaration
as confirmed inputs.  Manuscripts, cover letters, and current journal packages must not contain
draft-for-approval, pending-confirmation, pre-submission-gate, TODO, or similar internal workflow
language.  A configured review may return `ready` only for a package intended to need no further
author editing before upload.

Human-only legal or portal actions that genuinely cannot be automated belong in
`papers/<paper_id>/production/human_action_checklist.md`, outside every `journal-submissions/`
package.  The file records external actions; it must not be copied into the manuscript or upload
bundle and must not be used to conceal a scientific, evidence, ethics, authorship, or license
blocker.

After a passing current review and exact package binding, the standing repository policy is to
publish the prepared production Zenodo record without asking the authors again.  Automation still
passes the CLI's production and exact-paper confirmations, which remain fail-closed safeguards
rather than interactive approval prompts.  A ready package plus its published Version DOI is the
handoff target.  Actual journal-portal submission remains a separate audited external operation,
but the package must be complete enough that it requires no additional author intervention.
