# Mandatory reference and prerequisite checks

The editor remains the first model screen. After editor/rejection-history clearance,
fresh Codex verifier batches run before the configured ordinary referee(s). Every
reference and every source passage is covered, including the registered supplementary
document. Citation-use and formula IDs are generated from current source, not an
author-selected checklist. Definitions/notation require consistency checks; original
algebra requires a concrete derivation; an external result requires its original
assumptions/conclusion, precise locator and the conditions of this application.

Each document's inline bibliography or generated BBL contributes to the combined
inventory. Identical keys must have identical entries; conflicting identities
block review. Missing included files, recursive inputs, unsupported dynamic input
syntax and an unrendered requested bibliography also block review. Source type and
identifier are checked after HTTP redirects, so a declared full text cannot turn
a redirected metadata API response into theorem evidence.
The inventory recognizes inline/display math, standard equation environments and
`\ensuremath`. Multiple-argument citation commands such as `\parencites{a}{b}`
currently stop the inventory; express them as separate ordinary citations so no
second argument can silently escape coverage. This is a conservative supported
syntax boundary, not a claim of understanding every possible TeX macro.

DOI records are fetched from Crossref/DataCite; arXiv metadata and original PDFs are
queried when identified. Printed official links and available publisher PDF links
are discovery inputs. Every reference still needs an exact identity check by an
independent verifier, including authors/title/year/venue/pages/version/identifier
and available correction/retraction notices. Resolving a DOI does not establish
claim support. Missing DOI is acceptable with authoritative publisher/catalog
evidence. A network error stays unknown unless another retrieved authoritative
source supplies the necessary information; failed requests remain recorded.

For books, paywalled material with an available original chapter, old non-DOI works,
or APIs without sufficient original text, register actual accessible primary URLs:

```yaml
formal_check:
  sources:
    - reference_keys: [smith2020]
      url: https://publisher.example/book/official-record
      kind: publisher_catalog
    - reference_keys: [smith2020]
      url: https://publisher.example/book/original-chapter.pdf
      kind: primary_text
      pages: [3, 12]  # optional inclusive PDF page numbers, not printed page labels
```

These are source requests, not author attestations. The verifier must establish
their ownership and correspondence to the exact work. PDF extracts retain the
original downloaded bytes plus the explicit page range and extracted text; no
silent truncation is permitted. Register the original pages containing both the
statement and its assumptions. Abstracts/metadata/catalogs cannot verify a theorem
or its proof. Short evidence quotes must occur verbatim in the retained text and
carry original locators. Source declarations cannot turn off the mandatory gate.
Formula evidence must also come from primary text, rather than a metadata record.
The ordinary referee receives the evidence root and retained-file locators for
independent inspection of the source material.

An authenticated draft receipt for this manuscript's own current supporting package
can establish its prepared identity before publication under the existing support
policy. It cannot verify another work or an external theorem. Publication/readback
is still required by the existing delivery policy. Do not inject authenticated
upload/edit links or keys into prompts or public files.

Inspect the coverage without network or model calls:

```bash
bin/openlabs-resource-guard --task-type cpu -- env PYTHONPATH=workflows/paper \
  python -m paper_writing formal-check --paper-id PID --root DATA_ROOT --inventory
```

Omit `--inventory` for an independent standalone check. It writes a private audit
under `reviews/formal-check/` and returns a nonzero exit on incomplete verification;
it cannot pass the manuscript gate. Normal reviews automatically execute and bind
this stage. Failure after editor clearance is `formal_check_blocked` and requests
evidence remediation; it counts as that ordinary review round. Do not manually
construct model outputs, receipts or passing records.

Retain the evidence and model transcripts privately, with the same durable backup
discipline as other accepted inputs. Do not add third-party full texts or internal
audit dialogue to the manuscript, journal source ZIP or public support package.
Apply and handoff recheck current coverage, source plan, policy, evidence bytes,
actual role outputs and receipts. Old gates are historical records, not an exemption
from rerunning this stage. Actual saved prompts must match the reconstructed batch,
complete manuscript and retained source descriptors; self-consistent report hashes
alone cannot establish that the model inspected those particular materials.
This process does not certify all mathematics mechanically;
Lean/symbolic certificates are additional, scoped evidence only when actually run
and matched to the manuscript statement and assumptions.

Validation on 2026-10-11: all 1,014 paper-workflow regression tests passed;
skill structure validation passed. An independent forward test reproduced and
then confirmed repairs for supplementary bibliography omission, missing included
source, metadata redirects and aggregate/prompt rebinding. Its network/role calls
were explicitly mocked in an isolated workspace. A separate live test used the
configured `gpt-6.1-sol` role in four fresh processes against the official 2017
NeurIPS paper *Attention Is All You Need*: the correct scaled-attention definition
passed with all bindings revalidated; changing its denominator from `sqrt(d_k)`
to `sqrt(d_v)` while allowing unequal dimensions blocked the formula, citation and
prerequisite. Live transcripts and third-party source bytes remain private under
the artifact repository's `private/formal-check-mechanism-20261011/20261011T140723Z/`.
These isolated mechanism tests are not self-review decisions for registered papers.
