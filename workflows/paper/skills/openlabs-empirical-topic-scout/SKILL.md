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
paper. The owner wants a steady, regular flow of routine papers (CAS 2025 Zones 3-4) at a sensible
token and compute cost, not breakthroughs, and idle slots and quota are a cost too. Propose
nothing only when nothing in the line clears the routine bar; a sound routine card is worth
more than a clever one that is fragile.

## What to propose

Prefer routine production topics inside the line's positioning: a screening of a new set of
systems with a validated method, the line's standard analysis applied to a new or newly released
dataset, cohort or material family, a simulation case with verification and validation against
published measurements. These are what the lines exist for, and their cost is predictable. Re-audits
of somebody else's benchmark or published numbers (a leaderboard re-check, a "does the reported
value hold" study) are the exception, not the default: they fail most often on prior work that
already did the check and on endpoints that cannot separate the claim from measurement error.

## Paper templates first

When the packet's `research_line_summary.paper_templates` is non-empty, start there. Each
template in `registry/research-lines.yaml` (`lines[].paper_templates`) is a classic routine
paradigm anchored on one family of systems, with its variable dimensions (system family x
property or application), minimum content, hard gates, per-paper compute and agent time,
venues and how its novelty is judged. The owner wants these papers; they are the default
proposal of a line, ahead of re-audits.

1. Pick a template and a concrete system x property combination from its dimensions.
2. Run the occupancy search before anything else: is this exact combination already reported?
   Search the databases the template names (Crossref, arXiv, Google Scholar or Semantic Scholar,
   and the property databases it lists, such as C2DB or VSX/SIMBAD/ADS) with the system names,
   formulas and aliases plus the property. Record it in the card as `occupancy_search`:
   `queries` (the exact strings), `databases`, `searched_at` (date), `findings` (the closest hits
   and why they do not cover the combination). An unreported combination is enough novelty for
   a templated paper; one already reported is not, so pick another member. Parameters that exist
   only in automated batch tables (neural-network or pipeline catalogues, a queue entry's
   `batch_only` verdict) are not a published solution (owner decision 2026-11-13): such a target
   is valid, after the `unreported` ones. List each batch table in `occupancy_search`, cite it in
   `closest_prior_work`, and plan a table comparing your solution with its values and
   the increment of the individual solution (total-eclipse q, third light, uncertainties,
   absolute parameters). A dedicated light-curve study of the target still counts as reported.
3. Set `paper_template` to the template id. To reuse one set of scripts, a card may cover a
   `series`: `members` (two or more adjacent systems: the same host with several ions, one
   support with a row of metals, a few targets of one class) and `shared_pipeline`. A series is
   one paper; do not split one analysis into several cards.
4. Put two papers of the same paradigm from the last two years in your routine venues into
   `audience.citations`; the gate looks for them.
5. When the asset index has an SOP, script or loader for the template (`reusable_assets_summary`),
   list its `asset_id`s in `reusable_assets` (the gate sees them as `asset_reuse`) and lower the
   cost estimate to what remains; say so in `cost_estimate.basis`.
6. Meet the template's hard gates in the plan and in `feasibility_precheck` (for example the
   host's phonon stability as the precheck of an anode paper), and keep to its compute budget.

## How the gate decides (policy v2)

The gate admits a routine card when a stated incremental difference survives the closest prior
work, the decisive data is confirmed, the design can identify the claimed effect, and the card
fits its line and the licence lists. It rejects only for fatal problems: the comparison already
exists, the data cannot be had, the claim cannot be identified even after revision, a blacklisted
licence, or work beyond a computer. Fixable gaps (pre-registration details, manifests,
multiplicity, a baseline to add, an itemized cost, venue evidence still to verify) become
admission conditions that the campaign meets at a stated stage (`before_precheck`,
`before_decisive_analysis`, `before_submission`); they reach the campaign's first task. So write
the card so the difference, the data and the identification are unmistakable; details can follow
as conditions. A held topic, or one rejected as fixable, comes back once as a revision task: you
get the earlier card and its numbered reopen conditions and return one card with
`condition_responses` (`condition` index, `response`), which the gate checks against those
conditions only. A card that fails the machine format checks gets one repair task with the error
list. None of this changes what follows: receipts, citations, fee evidence and checks must be
real.

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
whether the line can run now; a card of a line that is not `ready` is held after admission and
admitted with the gate's decision once the line is ready, without a new card, so propose one or
two strong cards there rather than many.

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
  published in your candidate venues (`citation`, `year`, `venue`). Readers' papers in other
  venues may be listed too; only those in the candidate venues count towards the two. Without
  readers at the venue the editor desk-rejects regardless of quality.
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
  checked); optional `escalation` (`name`, or `venues: [...]` for alternatives, with the
  `condition` that would justify it). The routine pair is the
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
    `budget` (active agent time and compute; time waiting for queued remote jobs is not agent
    time), `on_failure: "freeze"`. After admission this is the first
    research task and nothing else runs before it; a miss freezes the topic.
    Write criteria the line can actually be judged on. A symmetry gate (O'Connell maxima,
    eclipse antisymmetry, bottom tilt) uses significance AND amplitude, the queue's rule
    (`queue_precheck`): fail only when the effect exceeds 3 combined SE (2 sigma for a slope)
    and 1 % of the eclipse depth; with TESS precision a significance-only gate fails almost
    every contact binary. A control criterion uses only what the line's shared control receipt
    can decide: each parameter within 2 combined sigma (quadrature of published and posterior
    uncertainty), plus the receipt's convergence flags. Do not add absolute tolerances such as
    |di| <= 2 deg: published inclination errors (0.01 deg) and the documented inter-pipeline
    systematic (~2 deg) make them unreachable, and the topic freezes at its first check.
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
- templated cards: `paper_template` (a template id of the line), `occupancy_search`
  (`queries`, `databases`, `searched_at`, `findings`), optional `series` (`members` with at least
  two systems, `shared_pipeline`).
- optional `target_tier` (`routine`/`escalation`), `reopens`, `reopen_basis` (`type`,
  `description`). In a revision task the control plane sets `revises`; add
  `condition_responses[]` (`condition`: index into the packet's `target.reopen_conditions`,
  `response`) for every condition marked `answer_required`.

The control plane checks the structure. Mechanical slips (a number written as text, a nameless
escalation, an unknown tier, a missing empty list) are fixed and noted; gaps the gate can weigh
(audience evidence, a data source's version or licence, cost numbers, an occupancy search) travel
to the gate as warnings. Only a gap admission cannot judge around (no question, no complete
primary endpoint, no data source with a DOI or URL, no named routine venue, no closest prior
work, unverified data access, the compute plan, a line card's precheck, licences or fees)
rejects the card; it then gets one automatic repair task, and a second failure is final.

## After admission

The admitted campaign starts from `research_state.json`, which carries the pre-registered
endpoint and its hash, the target tier, the routine fallback venues, the cost budget and any
`admission_conditions` with the stage each one is due. For a
research-line topic the card's `feasibility_precheck` runs first, before anything else, in the
line's environment (`registry/research-lines.yaml` `environment`, with its SOP); when it misses its
pass criterion the campaign returns `gate_result` with `promotion_decision: freeze` and
`freeze_reason_class: feasibility_precheck_failed`. Then run the pre-registered analysis and apply
its stop rule; a failed endpoint is reported, not reworded. Once a paper workspace exists, register `data_sources` and reader-facing
`key_findings` in the paper registry record (the monitoring dashboard reads them).

## Boundaries

This skill proposes topics and venues. It does not admit a topic, start a campaign, choose a
final journal, authorize submission or spending, or bypass the unified review.
