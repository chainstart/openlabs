---
name: openlabs-topic-admission
description: Decide, as an independent lead-model editor, whether each topic card in an OpenLabs admission review packet becomes a research campaign (admit, possibly with conditions), waits for a stated condition (hold) or is dropped (reject), and at which venue tier. Use only in the admission-gate portfolio_review task of a research program.
---

# OpenLabs topic admission gate

**First check the entry's `target_stage` (task type `topic_prescreen`: always `nc_aim`).** For
`nc_aim` entries and every prescreen, the routine purpose in the next two paragraphs ("routine
papers, not breakthroughs", Zones 3-4), the routine admission standard, the templated-series
rules and the tier section do **not** apply: follow "NC aim" and "Prescreen" below. The data,
licence, compute, venue and ledger rules still apply where those sections say so.

## Routine stage

Policy `openlabs.topic_admission_policy.v2` (owner direction 2026-11-12): the program exists to
produce a steady flow of routine papers (CAS 2025 major-category Zones 3-4) at a sensible token
and compute cost, not breakthroughs. You come from a different model family than the scout on
purpose: the point is a second, unshared view of whether a topic is worth a slot.

An idle slot has a cost. Compute and the weekly model quota that are not used on research are
lost, and the program is meant to keep them busy. You do not have to rule out every risk before
admitting: each research-line card carries a cheap decisive `feasibility_precheck` that runs first
and freezes the topic when it misses its numeric criterion, and every topic has hard limits (28
days to ready, 72 agent hours). That precheck is the stop-loss. Your job is to keep out topics
that cannot work, not to demand a finished study design.

## NC aim (entries stamped `target_stage: nc_aim`, user decision 2026-11-25)

For these entries this section replaces the routine standard, the templated-series rules and the
tier section below. Every topic aims at Nature Communications; the results decide the journal
later (NC, else CAS Zone 1, 2, 3-4). Your job is to keep out "small and low" topics and topics
whose claim cannot be tested, not to demand a finished study.

1. **Independent novelty search.** You did not choose the topic. Search the last three years
   yourself, at least 50 papers (preprints, dataset papers, code), and return
   `admission.novelty_search` {window_years, papers_screened, queries[], closest[{citation, year,
   doi_or_url, what_it_shows, our_increment}] (the five closest), increment (one sentence)}. The
   control plane rejects an admit without it.
2. **Check the prescreen; do not score again.** The prescreen (`card_check.prescreen`, another
   model family) already scored the five NC thresholds, read the calibration set and ran the kill
   test; a card that failed any of them never reaches you. Read its result against the card and
   your search: do the thresholds it counted hold, does `calibration_match` (and the expected band
   it caps) stand, and did the kill test show the signal? If one of them does not stand, reject
   and quote it in `strongest_rejection_reason`.
3. **The case holds together**: the one-sentence claim, the view it challenges and the benchmark
   are concrete; the data plan (`data_volume`, download windows, ailab storage) is feasible; the
   first milestone is the decisive analysis.
4. The data, licence, compute and fee rules below still apply, but at the scout stage an nc_aim
   card's `fee_check`, `license_check` and audience citations are only warnings
   (`card_check.warnings`): complete them here as admission conditions (licences
   `before_decisive_analysis`, fees and audience `before_submission`), not as reasons to reject.
   A data source the card marks `needs_registration` (free, the owner registers; noted in
   `card_check.nc_screen.data_catalog`) is no reason to reject either: admit with a
   `before_decisive_analysis` condition naming the registration, provided the kill test ran on
   data obtainable now.

Compare with the `at_admission` descriptions of the accepted NC papers in
`registry/venue-calibration.yaml` (what each looked like before the work: question, data,
design), not with their published hooks: a card is a plan and is matched against plans. The
NC properties are generality, a sentence that overturns a view, an order of magnitude of scale,
an authoritative benchmark, a reusable resource.

## Prescreen (task type `topic_prescreen`, NC funnel levels 2-3)

A cheaper check before admission, on one card whose author is another model family.

- **Calibration match first.** Read the calibration set (`read_resources` venue-calibration) and
  return `calibration_match` (nc|zone_1|zone_2|zones_3_4) and `calibration_neighbours` (2-3 ids).
  Match the card's question, data and design against each paper's `at_admission` (what was
  knowable before the work), not against its `hook` (the published result): every card is a
  plan, so a plan that reads like an NC paper's plan matches nc even though it has no result
  yet. The control plane places the card no higher than its match (the acceptance grade's
  rule); a match below the admission floor rejects it. A result without a match is invalid.
- **Phase A (minutes, no compute).** A quick novelty search of the last three years (list the
  3-5 closest papers; `papers_screened` as counted), including preprints: Research Square,
  arXiv, bioRxiv, medRxiv, SSRN, EarthArXiv. **Also check how each decisive dataset in
  `card.data_sources` is actually obtained and whether all required decisive fields exist in the
  public release**, returning `data_access_check[]`:
  `{source, method: "direct" | "form_or_registration" | "restricted", required_fields_present: true | false, missing_fields: [...], registration: "..."}`.
  Examples: Living Planet Database 2026 requires a named-recipient web form and non-commercial
  terms (`method: "form_or_registration"`, `registration: "..."` so it routes to
  `needs_registration`); PhysioNet Challenge-2021 Georgia subset has no patient-linkage map so
  patient-disjoint splits are impossible (`required_fields_present: false`,
  `missing_fields: ["patient_linkage_map"]`). Then your own scoring of the five NC thresholds.
  When any decisive dataset is `restricted` or missing a required decisive field, when fewer than
  the required number of thresholds hold, when the claim is already reported (`verdict: scooped`),
  or when the calibration match is below the floor, stop and return; do not run phase B.
- **Score the thresholds on the design's potential, as knowable at admission.** generality:
  the planned population is global, a whole population or a law across systems; scale: the
  planned data volume against the largest prior study; benchmark: the named authoritative
  reference the plan compares with; resource: the planned release; counterintuitive: if the
  result comes out as the claim says, it would overturn a view that is explicitly held (name
  who holds it). Do not mark a threshold unmet because the result is not in hand; mark it unmet
  when the plan cannot deliver it or when someone already delivered it for the same claim.
  Reading a plan does not lower the bar. Generality means the field's population (the world's
  rivers, a whole country's population, every model of a field), not the whole of one audited
  catalogue, product, database, pipeline or benchmark: an audit or re-check of one such source
  matches the lower-tier comparators, not nc, unless its conclusion changes practice across a
  field the way A1 and A2 did (several datasets, every model class of the field).
- **Same claim versus adjacent work.** `scooped` means the same claim is already reported: the
  same question on the same population with the same endpoint, so the card's sentence would
  repeat a published one (journal paper or preprint). Adjacent work - the same data, method or
  region with a different claim - is closest prior work: name it in `closest` with its
  `overlap` and judge the increment. `incremental` when prior work already reports the direction
  of the claim (the same effect on a subset, a region or one worked example) and what is left is
  its quantification, extension or refinement; `clear` only when the claim itself is new. Adjacent work does not make the claim scooped;
  whether it removes a threshold depends on what it already showed (an earlier regional study
  that already states the conclusion leaves `counterintuitive` unmet, but not `scale` when the
  card goes an order of magnitude beyond it).
- **Phase B (the kill test, within the packet's core-hour budget, here, no ailab job).** Write a
  small script from the card's `kill_test` and run it on data already on disk or on catalogued
  small samples (any download through the download bridge; nothing above the packet's size
  limit). Report: `signal.present` (true/false, with estimate and interval), the share of the
  effect a null model or simple baseline explains (`null_baseline.explained_fraction`), and the
  theoretical ceiling (`ceiling.value`, `claim_reachable`). A signal that a known formula or
  algebraic relation already determines (for example "98.5% of it is predicted by RR") is
  explained by the null model: set `null_baseline.determined_by_known_relation: true` and name
  the relation in `null_baseline.relation`; it counts as an explained fraction of 1. Save the
  numbers as a JSON file and
  declare it as a hash-bound result artifact (`kill_test.result_artifact` {path, sha256}).
- The control plane decides: signal absent -> the card is rejected (hard stop); the band is
  capped at the calibration match; a null model explaining at least the packet's
  `null_explained_max` (default 0.5) of the effect, or a ceiling below the claim -> one band
  lower; a band below the admission floor -> rejected; otherwise the card goes to admission with
  your result.
- Return `topic_prescreen` {calibration_match, calibration_neighbours, data_access_check,
  novelty_quick, thresholds, kill_test, expected_band, summary}. Be
  honest about a missing signal, restricted source, or missing decisive field: a killed card now
  saves weeks of compute later.

## The routine admission standard

Admit a routine card when all four hold:

1. **A stated incremental difference survives the closest prior work.** Read the closest work
   yourself, item by item (`closest_prior_work_checked`: `citation`, `assessment`), and search
   for anything closer the scout missed: preprints, code repositories, dataset papers. A
   routine paper needs one difference you can state in a sentence (a new cohort or system, a
   temporal or external split, a stronger baseline, a standardized analysis not yet done on
   this data). It does not need to be broad or surprising.
2. **The decisive data is confirmed accessible.** Look at the access receipt and, when you can,
   verify the source and version. Set `data_access_confirmed` only when you are satisfied the
   decisive analysis can run; without it the control plane will not create the campaign.
3. **The design can identify the claimed effect in principle.** The endpoint must be able to
   separate the claimed effect from the obvious alternative explanations (two changes
   confounded, a statistic that cannot separate the effect from measurement error, inputs that
   do not match the stated information set). Missing details of an otherwise identifying design
   are conditions, not reasons to reject.
4. **It fits its research line and the lists.** For a card with `research_line` (the packet's
   `research_lines` and `registry/research-lines.yaml` in `read_resources`): its `positioning`,
   `minimum_validation` and `minimum_novelty_per_paper`, not on the `avoid` list, and every
   item of `license_check` allowed and not blacklisted. A card without a line (an older domain
   project) should make clear why it is worth doing outside the lines.

## Templated series papers

Each research line lists `paper_templates` in `registry/research-lines.yaml`: classic routine
paradigms anchored on one family of systems (for example "a 2D monolayer as an alkali-ion anode",
"single-atom catalysts on one 2D support", "the photometric solution of one contact binary"). The
owner wants this kind of paper explicitly. Covering a family by a fixed recipe, a parameter sweep
across members, or one more member of a well-known paradigm is the expected form of these papers,
not a defect, and it is no reason to reject. A card with `paper_template` (and possibly `series`,
several adjacent systems sharing one pipeline) is admitted at the routine tier when:

1. **the concrete combination is unreported**: no paper reports the same system (or series
   members) for the same property; check its `occupancy_search` (queries, databases, date,
   findings) and repeat the key query yourself. Parameters only in automated batch tables
   (neural-network or pipeline catalogues; queue verdict `batch_only`) are not a report (owner
   decision 2026-11-13) and no reason to reject, provided the card cites each table in closest
   prior work and plans a parameter-by-parameter comparison with it; a dedicated
   (individual or small-sample) light-curve solution of the target is a report. Other lines
   define a report in their template's `novelty_rule` (for example the same market x rule x
   question in the last three years; the same audit of the same practice) and their queues use
   their own verdicts (`keep`, `needs_differentiation`: the card names its increment over every
   screened competitor);
2. **it meets the template's minimum content and hard gates** (for example phonon and AIMD
   stability, hybrid-functional gaps or an explicit statement of the PBE limitation, NEB barriers,
   a reproduced published solution) at the template's stated cost;
3. **the target venue publishes the paradigm**: the card's audience cites two papers of the same
   paradigm from the last two years in its routine venues.

Still reject a templated card when the same system and property are already reported, when the
plan falls below the template's minimum validation, or when one result is split into several
papers (salami slicing: members that share one analysis and one conclusion belong in one paper,
which is what `series` is for). The usual data, licence, fee and line checks apply. Conditions
cover the rest as for any card.

## Reject only for a fatal problem

- prior work already made the same comparison (the difference disappears once it is read);
- the decisive data cannot be obtained;
- the design cannot identify the claim in principle and no revision of the card could fix it;
- a blacklisted or unread `to_verify` licence the topic cannot do without;
- work beyond the system (wet lab, field work, human subjects, real-world interaction);
- for a templated card: the same system and property already reported, validation below the
  template minimum, or one result split into several papers.

Write the strongest reason against the topic first (`strongest_rejection_reason`), then decide
whether it is one of these. If it is not, it does not justify a rejection. When a rejection's
defect could be fixed by a revised card, set `revisable: true`; the topic then comes back once
as a revision card.

## Fixable gaps become conditions

Gaps that a competent researcher fixes in the first days of a campaign go into
`admission.conditions` on an admit, each `{description, due}` with `due` one of
`before_precheck`, `before_decisive_analysis`, `before_submission`:

- pre-registration details: seeds, deduplication and missingness rules, denominators, minimum
  sizes, multiplicity handling, bootstrap unit, how an inconclusive result is reported;
- manifests and alignment checks (cohort manifests, timestamp or hour-label audits) that do not
  look at the endpoint;
- a baseline that must be added, a comparison with a named paper that must be stated;
- an itemized cost basis or a timing probe;
- venue evidence still to verify (see below).

The control plane writes the conditions into the campaign's first task and its research state,
checks the `before_submission` ones as blockers at the submission-handler step, and records them
in the ledger. Keep each condition concrete enough that a later agent can tell whether it is met.

## Cost

Write `cost_judgement` as `{"proportionate": true|false, "rationale": "..."}`: one boolean and one
text that covers agent time, tokens and compute (further keys are kept but do not replace
`rationale`). Judge `cost_judgement.proportionate` against routine topics, not against a perfect one. Mark it
false only when the token or agent-time estimate clearly exceeds a routine topic's limits (72
agent hours per topic) or is badly out of proportion to what the result can reach. A missing
itemized or measured basis is not a reason to reject; ask for it as a condition. Judge token
cost and compute cost separately: CPU hours on ailab, a dedicated host that is otherwise idle,
cost calendar time rather than model budget, so a long ailab plan alone does not make a topic too
expensive. Check that `cost_estimate.compute_plan` fits the work: GPU memory for GPU training,
ailab cores, memory and hours for heavy CPU work, nothing heavier than minutes in
`container_cpu`. A location this instance cannot serve is rejected by the control plane
regardless of your verdict. A card entry's `asset_reuse` lists the indexed assets it relies on
(with use counts and last verification), when the packet has one. A card entry's `card_check`
lists the control plane's mechanical fixes (`normalized`) and the structural gaps it did not
reject the card for (`warnings`: audience evidence, a data source's version or licence note, cost
numbers, an occupancy search, an unknown asset or template id); weigh them like any other gap.

## Venues, fees and ranking evidence

The hard venue rules do not change: SCIE, the CAS 2025 upgraded major-category zone, and a route
without any mandatory author, page or publication fee; a human confirms the actual submission.
Venue evidence that `registry/research-lines.yaml` records as verified is accepted as it stands;
do not ask the scout to verify it again. Evidence that is not yet verified (a zone, a fee route of
the second routine venue) becomes a `before_submission` condition and does not block admission,
as long as one routine venue has a verified fee-free route. A venue known to charge a mandatory
fee is replaced, by condition or by the other routine venue.

## Research-line checks

Judge `feasibility_precheck` as the decisive analysis moved to the front: it must be cheap, run
first, and have a numeric `pass_criterion` that would really kill the topic (a precheck that
cannot fail is no precheck). Check `fee_check` covers page, colour and submission charges of every
routine venue with the evidence level the direction file gives (or a cited newer first-hand
source), and `license_check` against the whitelist and blacklist. A card whose line environment is
not `ready` may still be admitted: the control plane holds it with a `line_environment_ready`
condition and admits it with your decision, without a new review, once the line is ready. Do not
hold a card only because its line is not ready.

## Revision cards and released holds

A packet entry with `revision_of` is a revision of a topic that was held or rejected for a fixable
reason. Its `condition_responses` answer the earlier `reopen_conditions` by index. Check only
whether each condition is met by the revised card; do not re-judge what the earlier review
accepted, and do not add new requirements beyond what a condition or a fatal problem demands.
Admit when the conditions are met (with conditions of your own for what is still open), hold or
reject when a condition is clearly not met. A revision is not revised again. An entry with
`released_from_hold` returns because its line's environment became ready; the earlier review is
attached.

## Compare with the ledger

The packet's `ledger_snapshot` carries each earlier topic's status, rejection reason and reopen
conditions, and the topic ledger the gate's full records. Check that a card is not an earlier
rejected topic proposed again unchanged, and that the three defects that ended earlier topics
(missed prior work that already did the comparison, an endpoint that could not identify the
claim, a model budget out of proportion) are not present in a fatal form.

## Fix the primary endpoint

For an admitted topic, copy or tighten the card's endpoint into
`preregistration.primary_endpoint` (`metric`, `matched_baseline`, `split`, `decision_rule`,
`stop_rule`) and put the SHA-256 of its canonical JSON (sorted keys, no spaces, UTF-8) in
`preregistration.sha256`. The campaign is held to this block; details you leave to conditions are
fixed by the campaign before the analysis, without changing this block.

## Tier

`routine` (CAS 2025 major-category Zones 3-4, CCF B/C) is the floor; every admitted topic keeps the
card's two routine venues as its fallback. Choose `escalation` (Zones 1-2, CCF A) only when all of
these hold: the question matters beyond one subfield; the design has external or temporal
validation against the strongest baseline; a positive result would change practice or
understanding, not just a number; and the cost estimate leaves room for the extra work
(another cohort, mechanism analysis, ablations) that such venues expect. Explain the choice in
`tier_rationale`.

A research line may fix its own tiers in `venues.tier_policy` (registry/research-lines.yaml;
2026-11-19: `power-market-backtest` and `phm-evaluation-audit` target CAS 2025 major-category
Zone 1 journals as their routine venues, with Zone 2 hybrids only as a fee-free
subscription-route fallback). For such a line, judge the card by the line's policy: its routine
venues are the line's targets and `target_tier: routine` means them; the escalation conditions
above do not apply to reaching them, and the fallback venues stay the stated fallback.

## Verdicts

For an entry stamped `target_stage: tier2_aim`, independently judge whether the
idea has a plausible CAS Zones 1–2 contribution. Check the named recent precedent,
data scale and access, controls and external validation. Reject clearly insufficient
contributions, including for template, queue and revision cards. An admit records
`tier2_contribution_supported: true` and the evidence in `tier_rationale`. The
eventual journal is chosen after research from the achieved evidence.

- `admit` — meets the routine standard (or the escalation conditions). Needs `target_tier`,
  `tier_rationale`, the pre-registration and `data_access_confirmed: true`; optional
  `conditions`.
- `hold` — plausible but blocked by something outside the card: data not yet released, a method
  or external result that does not exist yet. List `reopen_conditions` (`type`: new_data_source,
  new_method, venue_policy_change, external_result, line_environment_ready; `description`). The
  control plane schedules one revision card against them; a hold whose only condition is
  `line_environment_ready` is released by the control plane itself.
- `reject` — a fatal problem as listed above. The reason is recorded so the same idea is not
  proposed again unchanged; `revisable: true` when a revision could fix it after all.

## Output

One `candidate_branches` entry per card in the packet: `candidate_id` and `topic_id` (both the
card's `topic_id`), `source_result_ids` (`[source_result_id]`), `title`, `objective` (the research
objective if admitted, otherwise a one-line summary), `rationale`, and the `admission` object
described above. Do not run the research or draft a paper in this task.
