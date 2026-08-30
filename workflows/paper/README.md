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

Every post-basic-draft journal target in a configured domain must satisfy the prospective registry policy for an allowed
2026 XinRui Tier 1/2 system, an official no-mandatory-author-fee route, and canonical venue format.
`style-check` and `support-check` are mandatory before review. See
[`docs/ZENODO_GUIDE.md`](../../docs/ZENODO_GUIDE.md) for controlled support-material publication.

Remote handoff and pre-gate Zenodo mutations remain disabled by default and require one explicit
administrator-enabled operation. The sole exception is `zenodo release`: a current `ready` gate
authorizes publication of the exact prepared, hash-bound supporting-material package, and the
command revalidates all bindings. It never authorizes manuscript submission, a journal event, a
spending decision, or a publication claim.
