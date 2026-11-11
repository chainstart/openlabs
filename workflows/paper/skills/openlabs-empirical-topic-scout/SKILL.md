---
name: openlabs-empirical-topic-scout
description: Propose computational, real-data research topics for an OpenLabs research program as machine-checked topic cards (openlabs.topic_card.v1). Use in a topic_scout task, or when a person wants to submit a topic to the admission gate. The scout proposes; an independent lead-model gate decides.
---

# OpenLabs topic scout

You propose topics; you do not start them. A reviewer from a different model family reads
your cards as an editor would and admits, holds or rejects each one. Only admitted topics
become research campaigns, so a card is the whole case for a topic. It must stand on its own.

## Why this exists

Of 113 submissions, 4 were accepted; most rejections were editorial ("contribution
insufficient", "limited readership"), usually within two weeks. The recent papers came from a
batch campaign whose topic cards were written after the analysis. Cards written first, checked
against the ledger and against the closest prior work, are the cheapest place to stop a weak
paper. Proposing nothing is a good outcome when nothing clears the bar; the program has no paper
quota and slots may stay empty.

## Before writing a card

1. Read the packet at the task input path: the topic-ledger snapshot, the research-portfolio
   requirements (`settings.yaml#research_portfolio`), the team rejection ledger, and the
   reusable-asset index when present.
2. Check the ledger first. A question already proposed, active, frozen or rejected on its merits
   comes back only as a reopening (`reopens` + `reopen_basis`) that answers the recorded reopen
   condition. Re-proposing it unchanged is rejected as a duplicate.
3. Check the asset index. A topic that reuses an existing pipeline, dataset loader or SOP is
   cheaper and better tested; name what you reuse.
4. Keep to work done entirely on a computer: existing public databases and datasets, applied or
   interdisciplinary questions. Nothing that needs a wet lab, field work, human subjects or
   other real-world interaction, because the program cannot carry it out.
5. Confirm you can actually obtain the decisive data: download or query a sample, record what you
   got (source, version, row counts, date) in a small receipt file, and add that file as a
   hash-bound artifact of your result. "The data is public" is not a receipt.

## The card

Return cards in the result bundle as `topic_cards: [...]` (at most the packet's `max_cards`).
Each field is there because the gate needs it to decide:

- `question` — one sentence a domain reader recognizes as open or contested.
- `audience` — `who` cares, and `citations` with at least two papers from the last three years
  published in your candidate venues (`citation`, `year`, `venue`). Without readers at the venue
  the editor desk-rejects regardless of quality.
- `closest_prior_work[]` — `citation`, `what_it_shows`, `our_difference`. Be specific; the gate
  checks these one by one and "first to apply X to Y" rarely survives.
- `decisive_analysis` — `description` of the one analysis or dataset the topic stands or falls
  on, `data_access_verified: true`, and `access_receipt` `{path, sha256}` matching your artifact.
- `primary_endpoint` — `metric`, `matched_baseline` (the strongest fair baseline),
  `split` (external or temporal when possible), `decision_rule`, `stop_rule`. Written before any
  analysis so a negative result is recognizable.
- `data_sources[]` — each with `doi` or `url`, `version`, `license`. These identify the topic in
  the ledger.
- `computational_only: true` and `computational_only_rationale`.
- `venues` — `routine`: two venues in the routine tiers of
  `settings.yaml#journal_target_policy.venue_eligibility` (fee-free route, team-ledger status
  checked); optional `escalation` with what result would justify it. The routine pair is the
  fallback the campaign keeps.
- `cost_estimate` — `agent_seconds`, `tokens`, `gpu_hours`, `calendar_days`, and `basis`: what
  the estimate rests on (a reusable pipeline, a comparable past campaign, a dry run). The gate
  weighs cost against the tier the result can reach; an expensive topic with an uncertain payoff
  is not admitted.
- `reusable_assets[]` — index entries you rely on (may be empty).
- `ledger_check.compared_topic_ids` — the ledger topics you compared against.
- optional `target_tier` (`routine`/`escalation`), `reopens`, `reopen_basis` (`type`,
  `description`).

The control plane checks the structure. A card missing a field is recorded as rejected with the
missing fields listed, which costs a whole scout run; checking your own cards is cheaper.

## After admission

The admitted campaign starts from `research_state.json`, which carries the pre-registered
endpoint and its hash, the target tier, the routine fallback venues and the cost budget. Run the
pre-registered analysis first and apply its stop rule; a failed endpoint is reported, not
reworded. Once a paper workspace exists, register `data_sources` and reader-facing
`key_findings` in the paper registry record (the monitoring dashboard reads them).

## Boundaries

This skill proposes topics and venues. It does not admit a topic, start a campaign, choose a
final journal, authorize submission or spending, or bypass the unified review.
