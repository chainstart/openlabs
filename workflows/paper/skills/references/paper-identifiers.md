# Paper identifiers

Apply the repository-wide policy in [`docs/PAPER_ID_POLICY.md`](../../../../docs/PAPER_ID_POLICY.md)
whenever a paper workspace or reader-facing file is created.

- New papers use `YYYYMMDD-domain-subdomain-keywords`; date, domain and subdomain match registry.
- Keywords describe stable scientific content. Keep OpenLabs question/task/round/workstream labels
  in provenance metadata, not in `paper_id`, `display_id`, manuscript prose or public filenames.
- Keep established `paper_id` values immutable. Use a compliant `display_id` for legacy records.
- Name exported PDFs `<display_id>-v<MAJOR.MINOR.PATCH>.pdf`; obtain the exact value with
  `paper-writing paper public-name` rather than inventing an ad hoc filename.

An externally recognised catalogue identifier is acceptable only with its identifying namespace
and a verified source. A local number that merely resembles a public catalogue is still internal.
