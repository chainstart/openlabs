---
name: openlabs-empirical-topic-scout
description: Propose computational, real-data research topics for an OpenLabs research program as machine-checked topic cards (openlabs.topic_card.v1). Use in a topic_scout task, or when a person wants to submit a topic to the admission gate. The scout proposes; an independent lead-model gate decides.
---

# OpenLabs topic scout

**First check the packet's `target_stage`.** When it is `nc_aim`, the routine purpose of this
skill (CAS Zones 3-4, "not breakthroughs", "a sound routine card is worth more than a clever
one"), "What to propose" (prefer routine topics), "Paper templates first" and the routine
gate policy do **not** apply: follow "NC aim" below and treat templates and queues only as
optional pipelines. The other sections (ledger, data, receipts, compute plan, card format)
still apply, with the NC exceptions stated there.

You propose topics; you do not start them. A reviewer from a different model family reads
your cards as an editor would and admits, holds or rejects each one. Only admitted topics
become research campaigns, so a card is the whole case for a topic. It must stand on its own.

## Why this exists (routine stage)

Of 113 submissions, 4 were accepted; most rejections were editorial ("contribution
insufficient", "limited readership"), usually within two weeks. The recent papers came from a
batch campaign whose topic cards were written after the analysis. Cards written first, checked
against the ledger and against the closest prior work, are the cheapest place to stop a weak
paper. The owner wants a steady, regular flow of routine papers (CAS 2025 Zones 3-4) at a sensible
token and compute cost, not breakthroughs, and idle slots and quota are a cost too. Propose
nothing only when nothing in the line clears the routine bar; a sound routine card is worth
more than a clever one that is fragile.

## NC aim (target_stage `nc_aim`, user decision 2026-11-25)

This section replaces the routine standard below whenever the packet says `target_stage:
nc_aim`. User: "后续的投稿目标都设为NC，然后选题也按照这个标准来选 ... 立意要高，但是论文到底投啥，要由做出的实验数据来说话". Every topic aims at Nature Communications; the results decide whether it goes to NC or down to CAS Zone 1, 2, 3-4. Small and low topics are not proposed.

NC publishes about 1,000 papers a month; about 13.5% of them are public data plus computation
(nc-hotspots section 1.4), across environment, earth science, ecology, agriculture, energy,
economics, social science, genetics, physics, materials, computing and more. The space is large.
In the 2026-11-26 calibration the same prescreen graded 11 of 14 rewritten NC papers as nc, yet
rejected 30 of 30 open-line production cards before admission: most were either narrow
audit/meta-science/reporting-rule checks (which calibrate to Zone 1 comparators such as `A7-z1`,
`L6-z1`, `S8-z1`), claims whose data only measured an unvalidated proxy, or refinements of
already-published directions. Write the card in this order:

1. **A substantive, cross-field scientific question, in one sentence.** Prefer questions that
   establish a **new natural, biological, physical or socio-technical phenomenon or mechanism**,
   quantify a **decision-relevant global quantity** with a clear *first / largest / causal* claim,
   or settle a **cross-field open debate** (is an operational forecast trustworthy, how much of
   the world's X is exposed to Y, where does a widely assumed law or mechanism break?).
   - **Avoid audit, meta-science and reporting-rule framings**: do not propose audits of a single
     catalogue, repository lag, reporting checklist, monitoring calendar, station-count coverage,
     or literature body (e.g. Mendelian-randomization checklists, WMO/GBON compliance rules,
     archive metadata QC, OA citation checks). In NC calibration these match lower-tier
     comparators, not NC. **Strict exception:** propose an audit only when it **overturns a widely
     used result, method or benchmark across an entire field** (tested across multiple independent
     datasets and all major model classes, with controls that isolate the exact artifact, as in
     A1 drug-response leakage, A2 LLM-brain confounds, or CSEP 11-year prospective earthquake
     validation) and delivers a field-wide benchmark or fix.
2. **Complete, decisive free data that directly identifies the claim.** Scale belongs to the
   question, not to the test: the claim covers the full population (all stations, basins,
   countries, species, or model classes), and the kill test alone uses a subset. A first assembly
   of scattered public archives into one analysis is itself a contribution (the CSEP archive, 48
   countries' tariff schedules, every archival HARPS spectrum of one young star).
   - **Direct outcome, non-trivial null, adequate power:** verify before proposing that the data
     directly measures the claimed real-world outcome rather than an unvalidated proxy (do not
     claim HVAC/grid failure from weather percentiles alone, real-world blackouts from an
     uncalibrated topology graph, or ecological co-selection from cross-sectional archive
     counts). Check mentally that the headline effect is not trivially explained by an algebraic
     or statistical null (such as independent area fluctuations in yield vs production,
     construction momentum, or selection-induced regression to the mean) and that the number of
     independent events or time steps can actually power the test.
   - Free data that needs a registration is allowed for the full-scale analysis (see Data below).
3. **Novelty search across top journals and the last 18 months of preprints.** Explicitly search
   and cite the **closest prior *Nature Communications*, *Nature*, *Science* (and *PNAS* / top
   sibling) papers** plus the last 18 months of preprints: Research Square (Nature portfolio
   "In Review" preprints, where most NC submissions appear 6-12 months before publication), arXiv,
   bioRxiv, medRxiv, SSRN, EarthArXiv, ESSOAr, plus code repositories and dataset papers. A
   published NC paper is evidence of the direction, not a template to rewrite: its own preprint
   usually appeared long before, so a card that follows a hook is already taken. Separate the
   **same claim** (same question, population and endpoint: drop the card or change the claim)
   from **adjacent work** (same data or method, a different claim: cite it in `closest_prior_work`
   with `our_difference`, explicitly showing what is new beyond the closest NC/Nature/Science
   papers).
4. **Only then the kill test**, on a subset, cheap enough for the prescreen (below).

Worked examples: `references/nc-precard-examples.md` has four pre-admission cards (NC10
riverfronts, NC09 PDS 70 exocomets, NC01 CSEP forecasts, NC08 tariff affordability) that the
same prescreen graded nc. They were rewritten from published papers to show how an NC card reads
before the work is done; their topics are taken and must never be proposed or paraphrased.

- **Cast a wide net across diverse fields.** Read recent literature and the line's data catalogue
  (`research_line_summary.data_catalog`, full file in the packet) and return several distinct
  cards rather than one polished one. On open or interdisciplinary lines, **spread cards across
  distinct fields and mechanisms** (e.g. Earth/climate/oceans/cryosphere, ecology/biodiversity/
  agriculture/fisheries, energy/infrastructure/transport/economics, demography/urban/computational
  social science, genomics/microbiology/evolution, materials/physics/astronomy, AI/computing):
  never return multiple cards from the same subfield or seed direction, and check
  `ledger_snapshot` to avoid repeating domains, datasets or angles where recent cards just failed.
  The pool has a cap (the candidate-pool low water) and a weekly model budget per line; a line
  whose recent cards all failed downstream is backed off.
- **Per-line admission floor** (`admission_min_band` in the packet and task objective; per-line
  `[program.lines.<id>].admission_min_band` if set, else global `[program.funnel].admission_min_band`):
  topics still aim high and the data grade the journal after research, while a card whose
  calibration match or expected band is below that line's floor (e.g. `nc` / `zone_1` on open
  lines, `zone_2` on established lines) is rejected at prescreen.
- **The NC surveys point to fields, not claims** (read_resources `nc-survey`, `nc-hotspots`): the ten
  templates A-J of nc-hotspots section 2 (citation statistics, crowding) and the line's
  `seed_directions` (numbers of nc-hotspots section 3.2) are optional illustrations only, never a
  menu to converge on (parallel scouts that pick the same seed direction produce near-duplicates,
  and audit-style seeds such as MR checklists or single-rule audits fail calibration unless they
  meet the strict field-wide exception above). Template the method and pipeline, never the claim:
  the claim must be new. Down-weight crowded subjects (very high template crowding, three or more
  NC papers in 18 months, the section 3.3 list: global flash drought and vegetation, urban heat
  island and greening cooling) unless the card names the angle they lack.
- Several scouts of one line run at once on different model families (GPT, Gemini, Claude); propose
  your own reading of the line, the near-duplicate screen merges overlaps.
- **Each card makes a complete NC case** across `nc_case`, `audience` and `closest_prior_work`:
  - **Headline finding if the kill test passes** (`nc_case.claim`): write the concrete,
    declarative Nature Communications headline sentence the paper would publish (a falsifiable
    phenomenon, mechanism, or global quantity—not a vague question or workflow description),
    paired with `alternative_claim` (the sentence that still has value if the result goes the
    other way), `challenges` (the widely held view, practice or policy parameter it overturns),
    `benchmark` (the authoritative reference, policy parameter or largest prior study it is
    measured against), `thresholds` (the five NC thresholds below, each `{met, evidence}`), and
    `exemplars` (ids of the hooks it resembles).
  - **Why NC readers across fields would care** (`audience.who`): explicitly explain the
    cross-field significance beyond one narrow subfield (which disciplines, policy bodies, or
    communities outside the immediate specialty would read and cite the result).
  - **Closest prior NC / Nature / Science papers and what is new** (`closest_prior_work[]`):
    include the closest prior *Nature Communications*, *Nature*, *Science* (or top-tier sibling)
    papers and recent preprints, stating concretely what each already showed and what is genuinely
    new in this card.
- **NC thresholds** (at least two must hold, with evidence): generality (global, whole
  population, or a law across systems); a one-sentence counter-intuitive conclusion; scale an
  order of magnitude (at least 4x) beyond the largest prior study; benchmarked against an
  authoritative reference or policy parameter; a reusable resource (dataset, catalogue,
  benchmark, tool). Method complexity is not a threshold: most accepted computational NC papers
  use public data and simple methods.
- **Plan the scale now**: `data_volume` {total_gb, largest_file_gb, proxy_expected,
  offpeak_days, ailab_storage_gb}. Large proxy downloads (>= 200 MB per file or >= 1 GB per
  batch) only run 02:00-14:00 Beijing time, so count the download windows; ailab has six SSDs.
- **Design the kill test**: `kill_test` {signal, null_model, ceiling, pass_rule, core_hours <= 2}
  - does the key signal exist, how much does a null model or simple baseline explain, what is
  the theoretical ceiling. The prescreen runs it; it replaces `feasibility_precheck`, which an
  nc_aim card does not carry. The test is small (a few basins, one year, a sample of the
  archive); the question is not shrunk to fit the test.
- **Milestones with budgets**: `milestones` [{name, kind, agent_hours, core_hours, model_usd}];
  the first has `kind: decisive` (the test that decides whether the main claim holds).
- **Data** (user rule: free sources only; registration-free ones are used directly, ones that
  need a free registration are listed for the owner to register): give each data source its
  catalogue `catalog_id`; a source you found and verified yourself (access receipt) gets
  `catalog_candidate: true`. **For every decisive dataset in `data_sources[]`, check how it is
  obtained and whether every field needed for the decisive analysis actually exists in the public
  release**, and record `access`:
  `{method: "direct" | "form_or_registration" | "restricted", required_fields_present: true | false, required_fields: [...], missing_fields: [...], registration: "..."}`.
  - `direct`: freely downloadable with no form/account and every decisive field verified present in
    the actual public files (not assumed from the paper abstract).
  - `form_or_registration`: free, but requires a named-recipient web form, account, API key, or
    non-commercial data-use agreement (e.g. Living Planet Database 2026 portal form — named
    recipient, non-commercial terms, no redistribution; ERA5/CDS, GRDC, GloFAS, EM-DAT, IHME GBD).
    Mark it `needs_registration: "<what to register, where>"` (and set `access.registration`) on
    the card, and run the kill test and access receipt on a registration-free source or sample.
    L1 routes it through the existing `needs_registration` path to the owner's registration list
    before admission; admission makes the registration a `before_decisive_analysis` condition.
  - `restricted` (paid, closed, or `blocked`) or `required_fields_present: false` (e.g. PhysioNet
    Challenge-2021 Georgia subset lacks a patient-linkage map, making patient-disjoint splits
    impossible): do not propose the card — L1 rejects it with `card_data_unavailable`.
- **Routine venue fields are warnings here.** The routine fallback pair in `venues.routine` is
  still named, but `fee_check`, `license_check` and `audience.citations` of an nc_aim card are
  checked as warnings at this stage and completed as admission conditions. Fill them when they
  are at hand (copy research-lines.yaml evidence); do not spend the task on them. Spend it on the
  question, the data and the preprint search.
- **Do not re-propose** a direction the ledger shows rejected or frozen for its substance; a
  card close to one is rejected mechanically.

Hooks of accepted NC papers (survey 2026-11-25, 63 papers; full list in
`registry/venue-calibration.yaml`, where `at_admission` says what each looked like before the
work). They are published results: read them for the size of question NC takes, not as topics
to refine.

- E1 flash droughts cut global vegetation 9.0% vs 5.3% for ordinary droughts (41 years, global).
- E3 warming makes 71% of basins' snowmelt floods earlier but ~30% later (243k floods, 70 years).
- E4 multi-thread channels are 51% of the world's alluvial river length, against the textbook view.
- N1 simple models beat deep learning for PV forecasting in 17 of 20 settings.
- N2 open probabilistic forecasts beat the system operator's own forecast by ~25%.
- N6 the worst Dunkelflaute winter needs 351 TWh of long-duration storage (~7% of demand).
- A1 a drug-mean baseline explains ~67.5% of drug-response variance; deep models lose to trees.
- A2 untrained models explain >80% of LLM-brain "alignment"; >98% comes from confounds.
- S1 doubling a city's population raises intra-urban inequality ~8-9% (accepted with R^2 ~0.04).
- S2 rich countries' 7-day forecasts are as good as poor countries' 1-day forecasts.
- P4 across 48 clusters, blue stragglers track the binary fraction (r = 0.81), not collisions.

## What to propose (routine stage; not for nc_aim)

Prefer routine production topics inside the line's positioning: a screening of a new set of
systems with a validated method, the line's standard analysis applied to a new or newly released
dataset, cohort or material family, a simulation case with verification and validation against
published measurements. These are what the lines exist for, and their cost is predictable. Re-audits
of somebody else's benchmark or published numbers (a leaderboard re-check, a "does the reported
value hold" study) are the exception, not the default: they fail most often on prior work that
already did the check and on endpoints that cannot separate the claim from measurement error.

## Paper templates first (routine stage; optional pipelines for nc_aim)

When the packet's `research_line_summary.paper_templates` is non-empty, start there. Each
template in `registry/research-lines.yaml` (`lines[].paper_templates`) is a classic routine
paradigm anchored on one family of systems, with its variable dimensions (system family x
property or application), minimum content, hard gates, per-paper compute and agent time,
venues and how its novelty is judged. The owner wants these papers; they are the default
proposal of a line, ahead of re-audits.

A template with a `candidate_queue` is enumerated: draw its queue's `candidates` in `rank`
order (skip entries whose `ledger_occupancy` is blocked; a queue without `ledger_occupancy`
is checked against the entries the task objective lists as already taken, by
`candidate_queue_entry.entry_id`), copy each entry's `card_fields` into
the card with every key unchanged (`reopens` and `reopen_basis` included: they reopen a frozen
topic under the new template version), and write the rest by the template's `card_rules`. Each
queued template has its own queue and rules; the same target in two templates is two topics.
Steps 1-2 below then reduce to checking the copied occupancy search.

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
   is valid; a queue's `rank` decides the draw order. List each batch table in `occupancy_search`, cite it in
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

## How the gate decides (policy v2, routine stage)

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
   other real-world interaction, because the program cannot carry it out. When the packet has
   `research_line_summary.data_catalog`, it lists the data the line can use: `ingested` (on
   disk), `onboarded` (free, fetch tool and tested sample), `catalogued` (free, access
   documented), `needs_registration` (not usable until the owner gets an account) and
   `blocked`. Read the catalogue file it names for endpoints, licence, citation and the fetch
   tool; build on `ingested`/`onboarded` sources first and never rest a routine card on a
   `needs_registration` or `blocked` one (nc_aim cards: a `needs_registration` source may carry
   the full-scale analysis as described under "NC aim", Data; `blocked` never).
5. Confirm you can actually obtain the decisive data: download or query a sample, record what you
   got (source, version, row counts, date) in a small receipt file, and add that file as a
   hash-bound artifact of your result. "The data is public" is not a receipt. Keep the receipt
   and other small text notes (<= 5 MB) in the campaign workspace; put every downloaded document
   (a PDF specification or paper, a data sample, a log, an archive) under the task's
   `transaction.artifact_staging_root` and declare it in `result.artifacts` with its `file://` URI
   and SHA-256. A PDF or log in the workspace (for example under `evidence/`) fails promotion, and
   a file left in `/tmp` or your home directory cannot be cited. Downloads go through
   the bridge with `--route auto`; a large download that would need the proxy route (a file of
   200 MB or more, a batch of 1 GB or more) runs only 02:00-14:00 Asia/Shanghai, so say so in
   the card's cost estimate when the decisive data depends on it.
6. Design the decisive analysis to run first. The team's failure mode was a decisive analysis run
   last that showed the contribution was too small. Pick the cheapest check that would kill the
   topic (for example 20-50 structures through two MLIPs plus small DFT; one published light-curve
   solution reproduced from the same public data; one benchmark case with grid convergence) and
   fix its numeric pass criterion now.

## The card

Return cards in the result bundle as `topic_cards: [...]` (at most the packet's `max_cards`).
Each field is there because the gate needs it to decide:

- `question` — one sentence a domain reader recognizes as open or contested.
- `audience` — `who` cares (for `nc_aim`, explicitly state why Nature Communications readers
  across multiple fields would care, beyond one narrow subfield), and `citations` with at least
  two papers from the last three years published in your candidate venues (`citation`, `year`,
  `venue`). Readers' papers in other venues may be listed too; only those in the candidate venues
  count towards the two. Without readers at the venue the editor desk-rejects regardless of
  quality.
- `closest_prior_work[]` — `citation`, `what_it_shows`, `our_difference`. Be specific; the gate
  checks these one by one and "first to apply X to Y" rarely survives. For `nc_aim`, include the
  closest prior *Nature Communications*, *Nature*, or *Science* papers (plus 18-month preprints)
  and state concretely what is new beyond them.
- `decisive_analysis` — `description` of the one analysis or dataset the topic stands or falls
  on, `data_access_verified: true`, and `access_receipt` `{path, sha256}` matching your artifact.
- `primary_endpoint` — `metric`, `matched_baseline` (the strongest fair baseline),
  `split` (external or temporal when possible), `decision_rule`, `stop_rule`. Written before any
  analysis so a negative result is recognizable. In the existing `stop_rule`, state in one
  sentence which observation against the closest published result would make you abandon the
  topic. Check shared controls and data coverage first. Cite any applicable same-version pilot
  and use trial compute for the uncertainty that could still change the decision.
- `data_sources[]` — each with `doi` or `url`, `version`, `license`, and (required for every
  decisive dataset on `nc_aim` cards) `access`: `{method: "direct" | "form_or_registration" |
  "restricted", required_fields_present: true | false, required_fields: [...], missing_fields:
  [...], registration: "..."}`. Mark any `form_or_registration` dataset `needs_registration`
  (what to register, where) so it routes to the user's registration list before admission; never
  propose a `restricted` dataset or one missing a required decisive field (L1 rejects it). These
  identify the topic in the ledger.
- `computational_only: true` and `computational_only_rationale`.
- `venues` — `routine`: two venues in the routine tiers of
  `settings.yaml#journal_target_policy.venue_eligibility` (fee-free route, team-ledger status
  checked), each a named object: `"routine": [{"name": "Astrophysics and Space Science"},
  {"name": "New Astronomy"}]` (a template's `venues.routine` lists bare names; write each as
  `{"name": ...}`); optional `escalation` (`name`, or `venues: [...]` for alternatives, with the
  `condition` that would justify it). The routine pair is the
  fallback the campaign keeps. A line whose entry sets `venues.tier_policy` uses its own tiers
  (for example CAS Zone 1 targets as `routine` and Zone 2 subscription-route journals under
  the card key the line names, such as `fallback_zone2_subscription_no_fee`); follow the line,
  and copy queue `card_fields.venues` unchanged.
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
- Research-line cards (the packet names a `research_line`) add three fields (nc_aim cards: the
  last two, checked only as warnings and completed at admission; their kill test replaces the
  precheck); the control plane rejects a routine line card without them. `packages/contracts/examples/research-program/topic-card.research-line.example.json` shows
  the shape.
  - `feasibility_precheck` — `description` (the cheap decisive check), `pass_criterion` (numeric),
    `budget` (one text string with the active agent time and compute, e.g. `"5400 active agent
    seconds; 40 CPU core-hours on ailab (4 CPUs, 5120 MiB); GPU 0; queued remote-job time
    excluded"`; time waiting for queued remote jobs is not agent time), `on_failure: "freeze"`. After admission this is the first
    research task and nothing else runs before it; a miss freezes the topic.
    Write criteria the line can actually be judged on. Where the card's template has
    `card_rules` (research-lines.yaml), they decide the endpoint, the feasibility conditions and
    what is forbidden; follow them and skip the two rules below (for example
    contact-binary-solution v2 forbids control gates and stop-on-asymmetry gates). Otherwise:
    A symmetry gate (O'Connell maxima,
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
- for `target_stage: tier2_aim`, include `tier_rationale` explaining the substantive
  advance over the closest recent precedent, the accessible data and its scale, the
  controls, and the external validation design. Prefer ideas with a plausible CAS
  Zones 1–2 contribution. The shortlist may include suitable lower-zone fallbacks.
- optional `target_tier` (`routine`/`escalation`), `reopens`, `reopen_basis` (`type`,
  `description`). In a revision task the control plane sets `revises`; add
  `condition_responses[]` (`condition`: index into the packet's `target.reopen_conditions`,
  `response`) for every condition marked `answer_required`.

The control plane checks the structure. Mechanical slips (a number written as text, a nameless
escalation, an unknown tier, a missing empty list, a venue given as a bare name, a precheck
budget given as an object) are fixed and noted; gaps the gate can weigh
(audience evidence, a data source's version or licence, cost numbers, an occupancy search) travel
to the gate as warnings. Only a gap admission cannot judge around (no question, no complete
primary endpoint, no data source with a DOI or URL, no named routine venue, no closest prior
work, unverified data access, the compute plan, a routine line card's precheck, licences or fees)
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
