# Revision-round exceptions and CAS minor-revision closeout (archived)

Moved from `workflows/paper/README.md`. Both belong to the pre-unified review. The closeout
commands were removed; existing `quality_gate_revision_exception` and closeout records are still
revalidated when an old release is read. The active round limit is
`registry/settings.yaml#review.max_rounds_per_target`.

## Temporary revision-round exceptions

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

## Explicitly authorized CAS minor-revision closeout

`review prepare-minor-closeout`, `review validate-minor-closeout`, and
`review closeout-minor` provide a separate, author-side text-repair workflow.
They do **not** create another independent review, change raw scores or historical
aggregates, or add/reset a review round. Ordinary review aggregation stays
conservative; the original `ara_llm_self_review` retains its original snapshot.

This is opt-in for exact paper IDs, source/target versions and original raw-review
SHA-256 values. It requires a valid native review with `scientific_ready: true`,
overall score at least 5 and simulated `cas_zone_1_journal` decision
`minor_revision` or `accept`. For journal papers these conditions now also require a
target-specific editorial screen bound to the current manuscript and selected journal;
see [EDITORIAL_SCREEN.md](docs/archive/EDITORIAL_SCREEN.md). Scientific, evidence, ethics and unclassified
blockers cannot be waived. Only verbatim-authorized, explicitly self-qualified
four-leading-journal suitability findings can be set aside for the CAS decision;
they remain in the raw review and in the closeout's nonblocking findings.
An optional request can be excluded only when it is explicitly optional,
low-priority, text-only, and the original review already has `text_ready: true`.

Place the actual user authorization in a nonsymlink JSON file directly under
`registry/quality-gate-exceptions/`. Its exact fields are:

```json
{
  "schema_version": "ara.paper_writing.minor_closeout_authorization.v1",
  "scope": "cas_minor_text_closeout",
  "actor": "user",
  "confirmed": true,
  "confirmed_at": "2026-09-07T03:27:41+00:00",
  "source": "<auditable source of the real authorization; not an invented message time>",
  "quote": "<the actual user instruction>",
  "minimum_score": 5,
  "decision_standard": "cas_zone_1_journal",
  "minimum_decision": "minor_revision",
  "papers": {
    "20260901-math-combinatorics-example": {
      "source_version": "0.1.0",
      "target_version": "0.1.1",
      "source_review_sha256": "<exact original raw review SHA-256>",
      "venue_suitability_blockers": [],
      "venue_suitability_change_requests": [],
      "venue_suitability_required_changes": [],
      "optional_not_required_change_requests": []
    }
  }
}
```

Do not infer authority from this example. The validator checks the recorded
instruction and exact scope, not the identity or truthfulness of its author.
Any existing round-budget exception must remain valid for the target version.

From the code repository, prepare an unsigned template (stdout only):

```bash
bin/openlabs-math-resource-guard -- env PYTHONPATH=workflows/paper \
  python3 -m paper_writing review prepare-minor-closeout \
  --paper-id PAPER_ID --root ../openlabs-data \
  --authorization registry/quality-gate-exceptions/AUTHORIZATION.json \
  --source-run ORIGINAL_RUN/PAPER_ID \
  --support-archive papers/PAPER_ID/support-materials/zenodo/vVERSION/SUPPORT.zip
```

`source-run` is relative to the sibling `openlabs-artifacts` directory. The
template binds the original raw/panel/apply/postvalidation/packet, full old and
new source/support inventories, exact delta, final PDF, journal source ZIP,
support ZIP and current review fingerprints. Snapshot-only Markdown omitted
from the original journal source ZIP is explicitly marked **not in the review
packet**. Its unchanged bytes must reconstruct the original snapshot hash;
this cannot excuse changed, added or removed notes. Science code/data and
added/deleted source files cannot use this mechanism. `CLAIMS.yaml` and
`claim_evidence_map.md` permit only literal source-to-target version substitution.
`REPRODUCE.md` has the same default restriction; a scoped authorization may
add `support_text_edits` entries containing its exact normalized support `path`,
`before_sha256`, and `after_sha256` for an inspected explanatory-only edit.
This does not whitelist other evidence or program files. The integrity helper
`verify_support_bundle.py` may change only literal version strings and its single
`EXPECTED_BUNDLE_MANIFEST_SHA256` assignment, with both old and new values checked
against the corresponding sibling manifests. Any other program change fails.

Save the template as an auditable certificate, then fill every mandatory request,
required-change and delta resolution with a reason and repository-relative
`{ "path": "...", "sha256": "..." }` evidence binding. The three checks
`clean_build`, `pdf_visual_check`, and `scientific_content_unchanged` must all
pass with bound evidence, plus a truthful `verified_by` and timezone-aware
`verified_at`. These are author-side semantic inspections, not machine proof or
new reviewer scores. An unchanged package may explicitly inherit the original
same-byte build/visual evidence; never claim a fresh build or inspection occurred
when it did not. Any text delta needs an actual scoped inspection for unchanged
scientific claims and complete request closure.

```bash
bin/openlabs-math-resource-guard -- env PYTHONPATH=workflows/paper \
  python3 -m paper_writing review validate-minor-closeout \
  --paper-id PAPER_ID --root ../openlabs-data --certificate maintenance/CERTIFICATE.json
bin/openlabs-math-resource-guard -- env PYTHONPATH=workflows/paper \
  python3 -m paper_writing review closeout-minor \
  --paper-id PAPER_ID --root ../openlabs-data --certificate maintenance/CERTIFICATE.json
```

Only the latter command writes a new `writing_release`. It preserves the full
original gate under `source_quality_gate`, records zero added rounds and no new
independent review, and binds the new snapshot. Both validation and release
replay the certificate and deterministic support/style gates. Handoff includes
the certificate, authorization, original review/apply and all quickcheck evidence
in its Git-frozen release inputs; changing a bound byte invalidates the closeout.
Neither command publishes remotely. The existing publication/handoff safeguards
still apply after closeout.
