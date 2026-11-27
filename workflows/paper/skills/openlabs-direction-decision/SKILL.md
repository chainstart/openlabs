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

## Grade a reviewed manuscript

For trigger `review_venue_grade`, read the completed review and its evidence. Assess the
actual advance over the closest recent work, data scale, controls and external validation.
If the evidence supports CAS Zones 1–2, choose a verified journal in that band. If it
supports Zones 3–4, choose a verified journal in that band for normal delivery. Explain
the evidence in `rationale` and audience fit in `retarget.why_fits`. Use
`retarget_or_short_format` with the exact verified journal name even to keep the current
journal. Add `retarget.achieved_band` with `zones_1_2` or `zones_3_4`. Quote the packet's
grading prompt in `answers_reason`. Check rejection history and the eligible fee route.
When there is no suitable verified journal in the supported band, use `freeze` with
`no_eligible_venue` and a venue-policy reopen condition. A switch requires review at the
new journal. Apply this section to the grading trigger and use the following choices for
other triggers.

### NC-aim grading (packet `grading.stage: nc_aim`)

User decision 2026-11-25: "如果最后得到的结果迈过了上述的真正门槛，有把握的话，那就投NC，没达到标准的话，就降级投1区，2区，依次降级 ... 要由做出的实验数据来说话，这是硬指标".

1. Read the calibration set (`read_resources` label `venue-calibration`): accepted NC papers with
   their hooks, and same-subject papers from lower-tier journals. First decide which tier the
   manuscript resembles: `retarget.calibration_match` (nc, zone_1, zone_2, zones_3_4) and
   `retarget.calibration_neighbours` (2-3 calibration ids).
2. Score the five NC thresholds on the actual evidence, not on the plan:
   `retarget.nc_scorecard` {generality, counterintuitive, scale, benchmark, resource: {met,
   evidence}}; set `retarget.confidence` (high, medium, low).
3. `retarget.achieved_band`: `nc` only with at least two thresholds met, calibration match nc and
   high confidence; otherwise `zone_1`, then `zone_2`, then `zones_3_4`. The control plane
   refuses a decision that breaks this rule.
4. Choose an exact verified journal of that band (`grading.nc_journals` for nc; the CAS zone
   for the others) from `verified_alternatives`. Every band keeps top-journal writing and figure
   standards; only the journal, its length and its format change.
5. After a rejection, retarget one band lower at a time (NC -> Zone 1 -> Zone 2 -> Zones 3-4).

## Choose

Use the choices listed in the packet's `options`. When it includes
`verified_alternatives`, the target has exhausted its review cycle. For a journal
switch, copy the exact journal name from that list into `retarget.venue_or_format`.
For a short communication use `short_format` and explain the intended article
type and scope in `why_fits`. A format change preserves the journal's round count.
Choose `freeze` if neither path addresses the outstanding review findings.

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
  cost-saving outcome, not a failure of judgement. Choose the `reason_class` that matches the
  evidence from the four primary classes (never label a solver, reproduction, budget, or negative
  result as `data_access` / `decisive_data_unavailable`):
  - `data_access` — decisive dataset cannot be obtained (access form/registration needed,
    restricted/paywalled, broken archive, or public release missing a required decisive field).
    Examples: Living Planet Database 2026 portal form/non-commercial terms; PhysioNet
    Challenge-2021 Georgia subset lacking a patient-linkage map; archive lacking point-in-time
    price vintages.
  - `method_capability` — solver, pipeline, or methodological limitation, or failure to reproduce
    a published baseline/control within tolerance. Examples: mandatory shared solver missing
    recovery or spot+third-light support; FEMTO/Paderborn baseline reproduction miss; uncalibrated
    cross-band luminosity conversion.
  - `negative_result` — analysis ran on available data and yielded a failed, null, negligible,
    inconclusive, or insufficient scientific result. Examples: primary endpoint failed; 95% CI
    spanning zero; negligible 0.002% effect below materiality threshold; contribution insufficient.
    (For acceptance-grading freezes with no fitting verified journal, keep `no_eligible_venue`.)
  - `resources_exhausted` — compute allocation, agent-time budget, calendar deadline, provider
    quota/pacing, review-round cap, or infrastructure capacity was exhausted before reaching a
    decisive result. Examples: core-hour allocation exhausted mid-precheck; provider quota pacing
    halt; four review rounds exhausted.
  (Legacy granular codes — `decisive_data_unavailable`, `feasibility_precheck_failed`,
  `primary_endpoint_failed`, `contribution_insufficient`, `no_eligible_venue`, `budget_exhausted`,
  `overdue`, `review_stalled`, `infrastructure` — map onto these four classes.)
  Include at least one concrete reopen condition (`type`: new_data_source, new_method,
  venue_policy_change, external_result; `description`: what would have to become true,
  specifically enough that a later scout can check it).

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
  "freeze": {"reason_class": "data_access | method_capability | negative_result | resources_exhausted", "reopen_conditions": [{"type": "", "description": ""}]}
}
```

Include only the block of your choice. Leave `next_actions` empty and `paper_candidate` false.
Do not run the analysis, edit the manuscript or change the registry in this task.
