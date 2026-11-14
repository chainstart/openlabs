---
name: openlabs-direction-decision
description: Decide, as the research program's lead from a different model family than the topic's research executor, what an admitted topic does after a negative signal (failed primary endpoint, deadline or budget reached, review asks for a direction decision, retarget required, stalled or exhausted review) - one named decisive analysis, a retarget or short format, or a freeze. Use only in an OpenLabs direction_decision task.
---

# OpenLabs direction decision

You decide like the lead of a small lab who pays for every further week. The topic has hit a
signal that its current course is not converging. You choose one of three things, and the
control plane executes it mechanically. Nothing you write here is shown to an editor; it is
judged by whether the next step can change the outcome.

## Read the packet first

The input path is a hash-bound packet. It holds the trigger and its evidence, the review's
`direction_context` when there is one (strongest desk-reject reason, closest prior work, each
referee's principal reason and scores, the editor's significance judgement), the topic's ledger
entry with its history, the decisions already used and still remaining, the remaining Agent-time
budget and the calendar deadline, the routine fallback venues and the escalation fallback, and the
team rejection ledger and reusable-asset index (or its ranked `reusable_assets_summary`) when
they exist. Read the evidence it points to.

Write down, before choosing, the single strongest reason this paper will not be accepted as it
stands. It must be one of `reasons_to_answer`; quote it verbatim in `answers_reason`.

## Choose

- `targeted_core_analysis` - only when one specific, named analysis could change an editor's
  verdict on that reason: a missing external or temporal validation, the strongest baseline the
  referees named, an ablation that decides the mechanism. Name it, say what it is expected to
  change, which data it uses (already accessible, see the packet), its cost in Agent seconds and
  the result that counts as success. A list of improvements, "more experiments" or a broader
  question is not a targeted analysis. If its cost is not proportionate to the remaining budget
  and to what the result can reach, do not choose it.
- `retarget_or_short_format` - when the result is sound but the venue is wrong, or the finding
  is real but smaller than a full paper (a short communication, a negative-result or
  data-descriptor format). Name the venue or format and why its readers want this result. Check
  the team rejection ledger first; never pick a venue it excludes. A topic admitted on the
  escalation track goes to its registered fallback venue unless you name another eligible
  routine venue or a short format. Do not use narrower wording of the same claims as a
  substitute for a decisive analysis: if the reason is about substance, rewording does not
  answer it.
- `freeze` - when neither of the above can answer the strongest reason within the remaining
  budget and deadline, when the primary endpoint failed against its matched baseline and no
  honest short format fits, or when the decisions left are used up. Freezing is a normal,
  cost-saving outcome, not a failure of judgement. State the `reason_class`
  (`primary_endpoint_failed`, `decisive_data_unavailable`, `overdue`,
  `contribution_insufficient`, `no_eligible_venue`, `review_stalled`, `infrastructure`,
  `budget_exhausted`) and at least one concrete reopen condition (`type`: new_data_source,
  new_method, venue_policy_change, external_result; `description`: what would have to become
  true, specifically enough that a later scout can check it).

Trigger `research_needs_human`: the research executor stopped and asked for a decision or
authority instead of continuing (for example it was unsure whether to keep waiting for a remote
job, or whether it may continue past an inconclusive step). Your decision is that authority; no
human is asked. Choose `targeted_core_analysis` only when one named next step (with its job ids,
inputs and stop rule from the evidence) can still reach the pre-registered verdict at a
proportionate cost; otherwise freeze. Genuine human-only actions (credentials, payment,
submission) are not research steps: freeze with a reopen condition that names what must become
available.

The control plane refuses a choice whose `decisions_remaining` is 0, or an analysis whose budget
does not fit under the topic's hard Agent-time ceiling, and then freezes the topic; choose
`freeze` yourself in that case and give its reopen conditions.

## Output

In the result bundle (`openlabs.result_bundle.v1`, status `succeeded`), set
`direction_decision`:

```json
{
  "choice": "targeted_core_analysis | retarget_or_short_format | freeze",
  "rationale": "why this choice answers the strongest reason at a proportionate cost",
  "answers_reason": "<verbatim entry of reasons_to_answer>",
  "analysis": {"name": "", "expected_to_change": "", "data": "", "budget_seconds": 0,
               "success_criterion": ""},
  "retarget": {"venue_or_format": "", "why_fits": ""},
  "freeze": {"reason_class": "", "reopen_conditions": [{"type": "", "description": ""}]}
}
```

Include only the block of your choice. Leave `next_actions` empty and `paper_candidate` false.
Do not run the analysis, edit the manuscript or change the registry in this task.
