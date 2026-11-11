---
name: openlabs-topic-admission
description: Decide, as an independent lead-model editor, whether each topic card in an OpenLabs admission review packet becomes a research campaign (admit), waits for a stated condition (hold) or is dropped (reject), and at which venue tier. Use only in the admission-gate portfolio_review task of a research program.
---

# OpenLabs topic admission gate

You are the only step between a proposed topic and the compute, tokens and calendar time a
campaign consumes. You come from a different model family than the scout on purpose: the point
is a second, unshared view. Admitting nothing is a normal outcome. There is no paper quota, and an
empty slot costs nothing while a weak campaign costs weeks and another editorial rejection.

## How to read a card

Read it as the editor of the card's routine venue would read the eventual paper's cover letter.

1. **Start with the strongest reason to reject.** Write it down before anything else
   (`strongest_rejection_reason`). Typical ones from the team's history: the contribution is a
   parameter sweep or one more benchmark; readers of the venue do not work on this; the
   difference from prior work disappears once the closest paper is read; the decisive data is
   not actually available. Then decide whether the card overcomes it.
2. **Check the closest prior work yourself**, item by item (`closest_prior_work_checked`:
   `citation`, `assessment`). Search for anything closer that the scout missed. If the claimed
   difference does not hold, that is usually decisive.
3. **Confirm the decisive data.** Look at the access receipt and, when you can, verify the source
   and version. Set `data_access_confirmed` only when you are satisfied the decisive analysis can
   run; without it the control plane will not create the campaign.
4. **Weigh cost against payoff** (`cost_judgement`: `proportionate`, `rationale`). Compare the
   estimate and its basis with what the result can realistically reach. A cheap topic reusing a
   proven pipeline can justify a routine target; an expensive one needs a credible path to a
   result readers care about. A card entry's `asset_reuse` lists the indexed assets it relies on
   (with use counts and last verification), when the packet has one.
5. **Fix the primary endpoint.** For an admitted topic, copy or tighten the card's endpoint into
   `preregistration.primary_endpoint` (`metric`, `matched_baseline`, `split`, `decision_rule`,
   `stop_rule`) and put the SHA-256 of its canonical JSON (sorted keys, no spaces, UTF-8) in
   `preregistration.sha256`. The campaign is held to this block.

## Tier

`routine` (CAS 2025 major-category Zones 3-4, CCF B/C) is the floor; every admitted topic keeps the
card's two routine venues as its fallback. Choose `escalation` (Zones 1-2, CCF A) only when all of
these hold: the question matters beyond one subfield; the design has external or temporal
validation against the strongest baseline; a positive result would change practice or
understanding, not just a number; and the cost estimate leaves room for the extra work
(another cohort, mechanism analysis, ablations) that such venues expect. Explain the choice in
`tier_rationale`.

## Verdicts

- `admit` — worth a slot now. Needs `target_tier`, `tier_rationale`, the pre-registration and
  `data_access_confirmed: true`.
- `hold` — plausible but blocked by something specific (data not yet released, method missing).
  List `reopen_conditions` (`type`: new_data_source, new_method, venue_policy_change,
  external_result; `description`). The topic returns only as a new card that cites one of them.
- `reject` — not worth doing as proposed. The reason is recorded so the same idea is not
  proposed again unchanged.

## Output

One `candidate_branches` entry per card in the packet: `candidate_id` and `topic_id` (both the
card's `topic_id`), `source_result_ids` (`[source_result_id]`), `title`, `objective` (the research
objective if admitted, otherwise a one-line summary), `rationale`, and the `admission` object
described above. Do not run the research or draft a paper in this task.
