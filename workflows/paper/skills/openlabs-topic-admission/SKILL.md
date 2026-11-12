---
name: openlabs-topic-admission
description: Decide, as an independent lead-model editor, whether each topic card in an OpenLabs admission review packet becomes a research campaign (admit, possibly with conditions), waits for a stated condition (hold) or is dropped (reject), and at which venue tier. Use only in the admission-gate portfolio_review task of a research program.
---

# OpenLabs topic admission gate

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

## Reject only for a fatal problem

- prior work already made the same comparison (the difference disappears once it is read);
- the decisive data cannot be obtained;
- the design cannot identify the claim in principle and no revision of the card could fix it;
- a blacklisted or unread `to_verify` licence the topic cannot do without;
- work beyond the system (wet lab, field work, human subjects, real-world interaction).

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

Judge `cost_judgement.proportionate` against routine topics, not against a perfect one. Mark it
false only when the token or agent-time estimate clearly exceeds a routine topic's limits (72
agent hours per topic) or is badly out of proportion to what the result can reach. A missing
itemized or measured basis is not a reason to reject; ask for it as a condition. Judge token
cost and compute cost separately: CPU hours on ailab, a dedicated host that is otherwise idle,
cost calendar time rather than model budget, so a long ailab plan alone does not make a topic too
expensive. Check that `cost_estimate.compute_plan` fits the work: GPU memory for GPU training,
ailab cores, memory and hours for heavy CPU work, nothing heavier than minutes in
`container_cpu`. A location this instance cannot serve is rejected by the control plane
regardless of your verdict. A card entry's `asset_reuse` lists the indexed assets it relies on
(with use counts and last verification), when the packet has one.

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

## Verdicts

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
