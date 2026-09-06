# OpenLabs paper workflow

This is the deterministic half of paper production: registry validation, evidence bundles,
manuscript inventory, review-record validation, conservative minimum aggregation, quality gates,
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

Every post-basic-draft journal target in a configured domain must satisfy the prospective registry policy for Zone 1/2 in
the 2025 Chinese Academy of Sciences Journal Ranking Table upgraded edition, using the major-category partition, plus an
official no-mandatory-author-fee route and canonical venue format. The compatibility field
`target_journal_tier` stores that CAS zone only; JCR/WOS/JCI quartiles, subject-category partitions,
and XinRui tiers are not substitutes.
Targets newly checked under the fit policy must also document topic-level scope, core readership,
contribution scale, two recent adjacent articles, and a clear same-target history check.
`style-check` and `support-check` are mandatory before review. See
[`docs/ZENODO_GUIDE.md`](../../docs/ZENODO_GUIDE.md) for controlled support-material publication.

Remote handoff and pre-gate Zenodo mutations remain disabled by default and require one explicit
administrator-enabled operation. The sole exception is `zenodo release`: a current `ready` gate
authorizes publication of the exact prepared, hash-bound supporting-material package, and the
command revalidates all bindings. It never authorizes manuscript submission, a journal event, a
spending decision, or a publication claim.

## Default submission-ready contract

### Temporary revision-round exceptions

The repository-wide `quality_gate.maximum_revision_rounds` remains the default.
Only an explicit human authorization may increase a particular paper's revision
budget. This is not a score, scientific-readiness, review, or publication waiver.
Preserve the actual completed round count; do not reset or relabel historical rounds.

A paper can bind one exact current version to a temporary exception:

```yaml
quality_gate_revision_exception:
  schema_version: ara.paper_writing.revision_round_exception.v1
  paper_id: 20260901-math-combinatorics-example
  manuscript_version: 0.1.0
  active: true
  scope: revision_round_budget_only
  maximum_revision_rounds: 7
  authorization:
    actor: user
    confirmed: true
    confirmed_at: '2026-09-06T10:00:00+00:00'
    source: 'user-message:an-auditable-reference'
    quote: '<the actual explicit human authorization, not a generated attestation>'
    record: registry/quality-gate-exceptions/example.json
    sha256: '<SHA256 of the exact authorization JSON bytes>'
```

The local JSON record must contain exactly `schema_version` (set to
`ara.paper_writing.revision_round_authorization.v1`), `paper_ids` (an explicit,
nonempty list of authorized IDs, without wildcards), `scope`,
`maximum_revision_rounds`, `actor`, `confirmed`, `confirmed_at`, `source`, and
`quote`. The latter seven values must agree with the bound exception. Timestamps
must include a timezone and must not be future-dated. The file must be at most
64 KiB, cannot be a symlink, and must sit directly in
`registry/quality-gate-exceptions/`. Creating this record preserves an existing
human instruction; the validator cannot authenticate the human or grant new
authority.

The gate records the complete verified exception in `writing_release`; handoff
revalidates it and requires the authorization file to be Git-frozen along with
the manuscript. Set `active: false` to revoke it. Version changes do not inherit
the exception: an operator must explicitly rebind an eligible new version within
the already authorized scope, then obtain a fresh gate. No configuration here
changes any score, recommendation, support, style, or independent-review check.

### Reusable paper declarations

Paper-bound declarations live in the data repository at
`registry/papers/<paper_id>.yaml` under `declarations.author_contributions` and
`declarations.ai_use`. The extracted copies and reusable, author-name-keyed templates
are in `registry/paper-declarations/`. See that directory's README before reuse.

New model-use disclosures use `declarations.ai_use.model_usage`: record the actual Codex
model and a hash-bound local JSON runtime source (`evidence.path`, `sha256`, and
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

### Release boundary

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
