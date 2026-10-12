# Mandatory bibliography and mathematical checks

The target-journal editor remains the first model screen. After editorial and
rejection-history clearance, fresh independent Codex batches check every printed
reference, citation use, detected formula and main/supplement source passage.
The configured ordinary referee then independently assesses correctness and gaps.

## Bibliographic accuracy

Under the user's 2026-10-12 instruction, reference verification requires real,
accurate bibliographic data, **not acquisition of original documents**. Check
authors, exact title, year/online-versus-print date, journal/book name, volume,
issue, page range/article number and DOI/arXiv/ISBN/version against authoritative
Crossref, DataCite, arXiv, publisher or catalog records. Check available correction
and version notices without claiming a comprehensive retraction search.
No DOI alone is not a defect. Wrong identities or genuinely unresolved metadata
remain blocking. A failed full-text download, paywall, unavailable chapter or
unextractable scan alone does not block. Failed attempts remain in the private
retrieval log; they are never relabeled successful. The legacy report field
`primary_source_check` means authoritative work identity, not mandatory full text.

For this paper's bound `current_support_draft`, check the reserved DOI, creators,
title, year and version against its authenticated draft receipt, and report its
actual prepared/draft state in `publication_status_check`. A missing public DOI
resolver entry while prepared is not a bibliographic defect. A reserved DOI does
not itself assert prior publication. Do not report a draft as published. Public
release and readback remain mandatory after review clearance and before delivery.
This scoped rule does not establish unrelated external references.

DOI and arXiv metadata are fetched automatically; identifier API links do not
automatically trigger PDF downloads. Official URLs printed in references and explicit source declarations
can supply catalogs or optional substantive evidence. For example:

```yaml
formal_check:
  sources:
    - reference_keys: [smith2020]
      url: https://publisher.example/book/official-record
      kind: publisher_catalog
  local_evidence:
    - path: papers/PID/evidence/current-replay.json
      sha256: ACTUAL_COMPLETE_SHA256
      kind: execution_record
      passage_patterns: ["finite enumeration"]
```

## Mathematical correctness and citation correspondence

Independently check every definition, formula, theorem and application: notation,
signs, constants, dimensions, quantifiers, limits, hypotheses, boundary cases and
actual derivation. Distinguish identities, approximations and conditional results.
Check that each citation appropriately attributes the manuscript's actual claim.
Correct metadata is not proof of theoretical or empirical correctness. An actual
error, unjustified inference or uncheckable scientific claim remains blocking;
missing original-document access alone does not.

Prerequisite kinds are `external`, `internal_derivation`, `empirical_evidence`.
For external results, state the identifiable result, its hypotheses/conclusion,
the manuscript instantiation, and concrete condition/formula checks. Valid cited
reference keys are required; original-page quotes and original-document downloads
are optional. Do not invent a page/theorem number or claim to have read unavailable
text. If substantive source quotes are used, they must come from actual primary
text rather than metadata. For internal derivations, independently reconstruct the
actual proof; `original_locator` must be an actual inventory passage ID or a literal
current manuscript proof excerpt of at least 12 characters. No external keys or
evidence are used. Do not misclassify an unproved borrowed result as internal.

Local evidence must be explicitly selected, SHA-256 bound, nonempty UTF-8, and
under this exact paper's directory. Selectors are literal current TeX substrings.
`manuscript_code` proves implementation, not execution; `execution_record` supports
only actual run scope; `research_record` is retained evidence, not a new independent
execution; `author_attestation` establishes only confirmed author facts. These
cannot prove an external theorem or bibliographic identity. Exclude credentials,
signed/edit/upload URLs and private correspondence. Release rechecks original
and model-visible bytes. Own empirical prerequisites need actual local evidence.

## Coverage, provenance and release

Included files and each document's generated BBL/inline bibliography are covered.
Conflicting duplicate keys, missing/recursive/dynamic includes or unrendered
bibliographies block review. Supported math includes inline/display math, standard
equation environments and `ensuremath`. Multiple-argument citation commands stop
inventory; use separate ordinary citations. Final paragraphs with trailing whitespace
are included. Nested formula/citation IDs must match exactly in each batch.

Optional primary URLs can declare inclusive PDF `pages: [first, last]` and
`passage_patterns` for routing. Optional `extraction_method: ocr` requires explicit
ranges of at most 30 PDF pages and available tools; it retains original PDF, images
and fallible transcription. OCR availability is not a gate requirement. Source type
and identifiers are checked after redirects; HTTP 200 challenge pages are rejected.
Any quote used must be a literal retained substring of at least 12 trimmed characters,
with actual source ID and locator. The catalog lists out-of-batch records; unseen
text is not quoted evidence. Packets are bounded, never silently truncated.

An authenticated current support draft verifies this paper's prepared supporting
package identity only. Publication/readback remains required separately by the
existing delivery policy. Keep keys and authenticated upload/edit links private.

Inspect deterministic coverage without network or models:

```bash
bin/openlabs-resource-guard --task-type cpu -- env PYTHONPATH=workflows/paper \
  python -m paper_writing formal-check --paper-id PID --root DATA_ROOT --inventory
```

Without `--inventory`, a standalone audit writes private records and exits nonzero
on incomplete verification; it cannot set the manuscript gate. The sole route to
`writing_release: ready` is fresh unified review. Formal failure counts as an
ordinary review round and stops before the referee. Never construct model outputs,
receipts or passing records. Actual invalid outputs and negative findings remain
retained; no repaired IDs or substituted passing retries. Revisions happen outside
review and receive a fresh run and response letter.

Keep third-party texts and model dialogue private. Apply/handoff rechecks coverage,
policy, source plan, source bytes, actual prompts, outputs and runtime receipts.
Changed policy or accepted inputs require fresh review; historical decisions and
website submission events are preserved. This is not a mechanical proof of all
mathematics. Lean/symbolic certificates add only the scope actually checked.
