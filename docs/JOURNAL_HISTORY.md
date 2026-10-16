# Shared team rejection history

The shared paper workflow owns this check, **before journal recommendation and retargeting**.
It applies across disciplines through `workflows/paper/skills/overlays/quality-gate.md` and
`skills/profiles.yaml`. Do not store the operative policy in an individual paper or a dated
maintenance report.

The active data repository owns:

- `registry/journal-rejections.json`: canonical structured ledger of all recorded refusals,
  source event/attempt IDs, dates, reasons, evidence availability and API-observed ongoing submissions.
- `registry/journal-rejections.csv`: generated single detailed table, one refusal per submission attempt.
- `registry/journal-rejections.md`: generated per-journal totals and selection status.
- `registry/settings.yaml#journal_target_policy.team_rejection_history`: enabled flag, paths and thresholds.

The user requested the table and exclusion on 2026-10-15. The operational defaults are
**exclude at 3 distinct rejected team papers** and **caution at 2**; these numeric defaults
were selected by the agent and stated during implementation, rather than quoted as user-specified.
The maximum ledger age is 7 days. These values can be changed in the one settings block.

## Refresh and query

From the code repository, run all Python through the aggregate guard:

```bash
bin/openlabs-resource-guard --task-type cpu -- \
  env PYTHONPATH=orchestrator/src:workflows/paper \
  workflows/paper/.venv/bin/python -m paper_writing journal-history sync \
  --root ../openlabs-data

bin/openlabs-resource-guard --task-type cpu -- \
  env PYTHONPATH=orchestrator/src:workflows/paper \
  workflows/paper/.venv/bin/python -m paper_writing journal-history check \
  --root ../openlabs-data --journal "European Journal of Combinatorics"
```

`sync` reads the management API (`GET` only), then updates local files atomically. It neither
submits papers nor changes website statuses. Refresh at the start of every new selection task
and after recording external decisions. A failed full API read does not replace the ledger.
Older refusals are retained when absent from a later snapshot; corrections to historical
decisions require an explicit evidence-backed reconciliation, not silent deletion.
An existing full site snapshot may be imported with `sync --snapshot <JSON-path>`; record its
origin accurately. Keep raw API snapshots and email bodies outside the registry.

`check` accepts full names and registered aliases. Exit status is 0 for eligible/caution,
1 for an excluded journal, and 2 for an unavailable, malformed, stale or future-dated ledger.
Read the `status` field: caution is a lower-priority alternative, not a first recommendation.
`summary` prints the generated Markdown table. Do not edit the CSV/Markdown independently.

## Counting and enforcement

Each paper counts once per journal, even if there are several attempts or letters. The CSV
retains individual attempts for audit. Count actual management-site rejected statuses; mark
missing original decision events `management_status_only` and leave unknown reasons/dates empty.
Keep conference refusals in the detailed table but exclude them from journal counts. Never merge
European/Electronic Journal of Combinatorics, JCTA/JCTB, Annals/JACO, or unrelated titles.
Add a documented alias under the policy's `aliases` mapping if needed.

New targets are checked by registry validation, unified-review preflight, legacy gate recording
and release/handoff preconditions. An excluded target is stopped before compiling or launching a
new unified review. Read-only inventory can retain historical records. Preserved historical
refusals do not authorize a new review or handoff. A matching ongoing submission sourced from the
management API may continue its existing revision even if the journal has since crossed the
team threshold; this exemption does not apply to a different paper or recommendation query.

This rule adds to existing explicit exclusions, CAS ranking, fee, scope, contribution and
same-paper history checks. A low team refusal count is not evidence of acceptance probability.
User instruction 2026-10-16 supersedes the former rejection-stage selection limits: new recommendations and retargets search directly in 2025 CAS upgraded-edition major-category Zone 4, regardless of rejection count. The canonical setting is `journal_target_policy.new_selection_tiers: [4]`. Historical targets and ongoing submissions/revisions are preserved. Rejection records remain required scientific provenance; team totals never substitute for a paper's own history. Changing the global exclusion requires
an explicit policy change, not a favorable model review or a new cover letter.

Regression tests: `workflows/paper/tests/test_journal_history.py`.

## Handling a rejection

Use the shared paper workflow for the whole sequence, rather than storing operative rules in
one paper's follow-up note:

1. Read the actual decision and match the manuscript number to its submission attempt. Distinguish
   rejection, revision invitation and automated transfer suggestions. Register a new sourced
   decision through the management API once, read it back, and preserve the submitted package.
   Keep private mail and transfer tokens outside public data.
2. Refresh the canonical ledger. Build the pending queue from current external attempts: a paper
   with a later ongoing submission stays in that submission's follow-up queue; a closed paper
   stays closed. An old internal `ready` record does not reverse an external rejection.
3. Diagnose the current manuscript against the actual rejected version and editorial concerns.
   Separate target mismatch, evidence/proof defects, insufficient contribution and unresolved
   historical records. First check whether later revisions already resolved old requests.
   Preserve negative findings and unknown reasons; do not manufacture new scientific demands.
4. Query team history for every candidate, then apply same-paper history, the paper's own CAS
   eligibility, existing paper-specific exceptions, official fee routes and specific readership
   evidence. Record cautious candidates as conditional; never use another paper's exception.
5. Save a dated author-side plan referencing the canonical attempt IDs and ledger hash. Each pending
   paper needs its next action, deliverable, completion condition and conditional shortlist or
   explicit research hold. Link older recommendations to the current plan to avoid competing
   instructions. Do not duplicate the canonical ledger as a second editable rejection database.
6. Complete necessary research and target adaptation before changing clearance. Use the existing
   review router to choose evidence reuse, delta or full review; do not restart scored reviews
   merely to improve a score. A changed journal requires its own valid target assessment and
   release checks. Submission, withdrawal and public release retain their separate authorization.

If substantive contribution or evidence is still missing, define a bounded research question
and a reassessment point; pause journal cycling when it produces no material advance. This is a
work-queue decision, not a fabricated external status, a deletion or a permanent research ban.
