---
name: openlabs-empirical-topic-scout
description: Select, scope and stop-or-go real-data interdisciplinary empirical research topics that can reach an eligible fee-free SCIE Zone 1-4 journal or CCF A/B/C conference within the configured time budget. Use before seeding a new OpenLabs empirical campaign or paper, or when deciding whether a running empirical result merits the Zone 1-2 / CCF-A escalation track.
---

# OpenLabs empirical topic scout

Read `registry/settings.yaml#research_portfolio` and `#journal_target_policy.venue_eligibility`,
`../overlays/quality-gate.md` and the team ledger (`paper-writing journal-history sync/check`).
New work is mainly **real-data interdisciplinary empirical research** (user instruction
2026-11-07). Topics must be publishable at an eligible venue: an SCIE journal in 2025 CAS
major-category Zones 1-4 with a fee-free route, or a CCF A/B/C conference with no mandatory
page or publication charge. Never choose a paid route.

## What the 2026-11 audit showed

- Of 113 attempts, 4 were accepted; 47 of 67 dated rejections came within 14 days, almost
  all editorial. The usual reason was narrow scope or insufficient readership interest, not an
  error.
- Accepted or revised work used real data on questions other people already study (LoRA rank
  comparisons, clinical informatics, cosmology data). Narrow variants of one coefficient or a
  self-audit of an earlier in-house experiment did not get past editors.
- Bulk same-day submissions and fast resubmission after rejection hurt credibility.

## Produce a topic card before any campaign

Write `topic-card.yaml` in the proposed campaign/paper workspace with:

1. `question`: one sentence a domain reader recognizes as open or contested. Cite at least two
   recent (last three years) papers from candidate venues that study it.
2. `data_sources`: real public or measured data with stable URL/DOI, version or access date,
   licence/access terms and sample unit. Prefer at least two independent cohorts, sites, time
   periods or instruments so external or temporal validation is possible. Synthetic or simulated
   data may only supplement real data.
3. `primary_endpoint`: fixed before the main analysis, with the matched strongest baseline and
   the decision rule that would stop the topic.
4. `venues`: two routine eligible venues (Zones 3-4 / CCF B-C), each with SCIE or CCF evidence,
   fee-free route, two recent adjacent articles and a team-ledger status (not excluded, cadence
   allowed). Optionally one escalation venue and what result would justify it.
5. `contribution`: what a reader of the routine venue learns that the closest two papers do not
   give. Reject topics whose only novelty is a new parameter range, one more benchmark, or
   correcting our own earlier analysis.
6. `budget`: compute, data-access and calendar estimates; the topic must reach submission within
   `research_portfolio.stop_rules.max_days_from_topic_to_submission` days.
7. `risks`: licensing/ethics constraints, leakage risk, likely reviewer objections.

Score each card 1-5 on readership, data strength, novelty versus closest work, feasibility in
budget and venue fit. Advance at most the top cards that fit current capacity; record rejected
cards and the reason so they are not re-proposed.

## Run, then stop or go

- Pre-register the split, endpoint and baseline in the campaign state before running the main
  analysis. Report negative primary results honestly; a failed endpoint stops the topic or turns
  it into a clearly framed negative result only if a routine venue publishes such work.
- At the first complete result, re-check the contribution against the closest work. If it is
  still incremental, stop instead of adding datasets or rewording.
- Register `data_sources` and `key_findings` in the paper registry record as soon as the paper
  workspace exists; the monitoring dashboard reads them.

## Escalation

Consider Zones 1-2 / CCF-A only when the result holds on external or temporal validation, the
effect is practically meaningful against the strongest baseline, and the unified review scored
at least the configured escalation minimum. Record `target_escalation` with a routine fallback
venue and have a human author approve it. Plan extra work (new cohort, mechanism analysis,
ablation, domain-expert co-author) before escalating, not after a rejection.

## Boundaries

This skill selects topics and venues; it does not authorize submission, spending, a journal
event, or bypassing the unified review, editorial screen or cadence check.
