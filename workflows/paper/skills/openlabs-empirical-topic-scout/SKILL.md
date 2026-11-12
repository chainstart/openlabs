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

The admission gate's rejections on this instance so far share three causes, and each is cheaper
to catch here. First, the claimed difference disappeared once the gate found closer work the
scout had missed: an older forward-validation paper, a recent preprint and a public code
repository running the same comparison, a database paper already filtering the same records.
Search preprints, code repositories and dataset papers for the exact comparison, not only
journals for the topic. Second, the primary endpoint could not identify the claim: an old/new
comparison that changed software and database together, a statistic that could not separate
reporting bias from measurement error, inputs that did not match the information set the
question named. Write down what else would produce the same number and design the endpoint so
that it cannot. Third, multi-million-token estimates without a measured probe or a reused
pipeline were judged out of proportion to an incremental result; base the estimate on a dry run
or an indexed asset and keep the topic as small as its venue tier warrants.

## Research lines

The program scouts by research line (owner direction 2026-11-12: data-based empirical work and
routine computational screening, steady and cheap in tokens and compute; no mathematics, no
theoretical physics). The lines, their minimum validation, venues with fee evidence, licence
lists and avoided directions are in `registry/research-lines.yaml` (summary
`registry/research-lines.md`; both are in the packet's `read_resources`). When the packet names
a `research_line`, every card belongs to that line (the control plane sets the field) and must
meet its `minimum_validation`; the line's `positioning` and `minimum_novelty_per_paper` say what
a paper of that line has to add. If you think a question deserves a line that does not exist,
do not write a card for it: explain in the result summary why the new line would be routine,
stable and cheap, so the owner can add it. `research_line_summary.environment_status` tells you
whether the line can run now; a card of a line that is not `ready` is held after admission until
it is, so propose one or two strong cards there rather than many.

## Before writing a card

1. Read the packet at the task input path: the topic-ledger snapshot, the research-portfolio
   requirements (`settings.yaml#research_portfolio`), the team rejection ledger, and the
   reusable-asset index when present.
2. Check the ledger first. A question already proposed, active, frozen or rejected on its merits
   comes back only as a reopening (`reopens` + `reopen_basis`) that answers the recorded reopen
   condition. Re-proposing it unchanged is rejected as a duplicate.
3. Check the asset index. A topic that reuses an existing pipeline, dataset loader or SOP is
   cheaper and better tested; name what you reuse. When the packet has `reusable_assets_summary`
   (active assets ranked for this domain, one line each), put the `asset_id`s you rely on in
   `reusable_assets[]`; an id that is unknown or archived makes the card invalid.
4. Keep to work done entirely on a computer: existing public databases and datasets, applied or
   interdisciplinary questions. Nothing that needs a wet lab, field work, human subjects or
   other real-world interaction, because the program cannot carry it out.
5. Confirm you can actually obtain the decisive data: download or query a sample, record what you
   got (source, version, row counts, date) in a small receipt file, and add that file as a
   hash-bound artifact of your result. "The data is public" is not a receipt.
6. Design the decisive analysis to run first. The team's failure mode was a decisive analysis run
   last that showed the contribution was too small. Pick the cheapest check that would kill the
   topic (for example 20-50 structures through two MLIPs plus small DFT; one published light-curve
   solution reproduced from the same public data; one benchmark case with grid convergence) and
   fix its numeric pass criterion now.

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
  is not admitted. `cost_estimate.compute_plan` is required: `locations` (from `container_cpu`,
  `container_gpu`, `ailab`, `wsl_math`; chosen as in AGENTS.md "Where computation runs"), with
  `gpu_memory_mib` when the GPU is used and `ailab: {cpus, memory_mib, hours}` for the ailab
  queue (1-8 CPUs, at most 62961 MiB). The container instance cannot run `wsl_math` and rejects
  such a card outright; propose mathematics only where the packet's instance runs it. Keep
  token cost and compute cost apart: heavy computation that parallelises across ailab jobs
  costs calendar hours on an otherwise idle host, not model budget, so do not drop a strong
  question only because its CPU time is long; plan the split and state it here.
- Research-line cards (the packet names a `research_line`) add three fields; the control plane
  rejects a line card without them. `packages/contracts/examples/research-program/topic-card.research-line.example.json` shows
  the shape.
  - `feasibility_precheck` — `description` (the cheap decisive check), `pass_criterion` (numeric),
    `budget` (agent time and compute), `on_failure: "freeze"`. After admission this is the first
    research task and nothing else runs before it; a miss freezes the topic.
  - `license_check` — `items[]` with `name`, `kind` (software, weights, data), `license`,
    `evidence` (the research-lines entry or a licence text you read), `allowed: true`, for every
    package, model weight and dataset the topic uses; `blacklist_checked: true`. Items the line
    marks `to_verify` need their licence text read and cited before you list them.
  - `fee_check[]` — one entry per routine venue: `venue`, `page_charges`, `colour_charges`,
    `submission_fee`, `fee_free_route` (true, or "unverified"), `evidence_level`
    (verified_journal, verified_publisher, secondary, unverified) and `evidence` (the
    research-lines entry or a first-hand page you retrieved). At least one routine venue must be a
    verified fee-free route. Copy the evidence level from `research-lines.yaml` unless you obtained
    a newer first-hand source; never upgrade a level by inference. A venue whose entry says
    `card_rule` (for example Research in Astronomy and Astrophysics while its charges are
    unverified) needs the alternative it names.
- `reusable_assets[]` — index entries you rely on (may be empty).
- `ledger_check.compared_topic_ids` — the ledger topics you compared against.
- optional `target_tier` (`routine`/`escalation`), `reopens`, `reopen_basis` (`type`,
  `description`).

The control plane checks the structure. A card missing a field is recorded as rejected with the
missing fields listed, which costs a whole scout run; checking your own cards is cheaper.

## After admission

The admitted campaign starts from `research_state.json`, which carries the pre-registered
endpoint and its hash, the target tier, the routine fallback venues and the cost budget. For a
research-line topic the card's `feasibility_precheck` runs first, before anything else, in the
line's environment (`registry/research-lines.yaml` `environment`, with its SOP); when it misses its
pass criterion the campaign returns `gate_result` with `promotion_decision: freeze` and
`freeze_reason_class: feasibility_precheck_failed`. Then run the pre-registered analysis and apply
its stop rule; a failed endpoint is reported, not reworded. Once a paper workspace exists, register `data_sources` and reader-facing
`key_findings` in the paper registry record (the monitoring dashboard reads them).

## Boundaries

This skill proposes topics and venues. It does not admit a topic, start a campaign, choose a
final journal, authorize submission or spending, or bypass the unified review.
