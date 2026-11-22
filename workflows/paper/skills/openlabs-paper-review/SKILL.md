---
name: openlabs-paper-review
description: "Run the sole OpenLabs journal self-review: deterministic preflight, independent target-editor screen with actual rejection history, the configured cross-model referees, bibliography and core-mathematics verification, then a bound decision."
---

# OpenLabs unified paper review

Use `review unified-run` under the resource guard; this is the only route to
`writing_release: ready`. The editor, the referees, their models and the round limit come
from `registry/settings.yaml#review`; do not restate them here. The panel must include a
referee from a model family other than the drafting model (`review.cross_model`); where the
settings record `cross_model.basis: model` (only one model family available), a referee of a
different model of the same family counts, and the decision record says
`same_family_different_model`. Report that label as it is; never describe such a panel as
cross-family. A gate never authorizes journal submission.

For a pre-registered study, compare the hash-bound pre-registration (`research_state.json`
`preregistration`) with the manuscript word for word: quote the registered primary endpoint
and its decision rule, quote what the manuscript reports as the outcome, and say whether the
manuscript's verdict follows from the registered text read literally. A handling added after
registration (an adjusted threshold, a reinterpreted statistic, a discrepancy allowance) is a
supplementary analysis: the manuscript must also report the result judged by the original
text. A mismatch is a scientific blocker, not a text change.

```bash
bin/openlabs-resource-guard --task-type cpu -- env PYTHONPATH=workflows/paper python -m paper_writing \
  review unified-run --paper-id PID --root DATA_ROOT --response RESPONSE.json
```

For a new full review at the same venue, pass the decision-bound JSON response described below. Do not manually construct decisions or
edit manuscript/registry/evidence during review. Preserve actual outputs and model
receipts, including failures. Revised prose remains neutral scientific writing;
keep internal review negotiation and claims about editor approval outside the paper.

## Three gates and human submission

1. Run the author tools. Attach style, narrative, figure, declaration and support findings.
   Correct build failures, irreproducible figures, absent required declarations and missing
   referenced files before review. Preserve actual evidence and report discrepancies.
2. Run the configured editor, referees, independent reader and formal verifier in parallel.
   Return one decision on science, readability and formal accuracy. Read the original
   rejection letters. State the wrong conclusion each blocker would cause. Treat wording,
   definition completion, caption detail, cuts and style as advice. The reader restates the
   question, comparison, answer and significance and identifies the supporting panel.
   Follow-up rounds check prior blockers and changed passages. Explain any previously
   missed material defect. Bind point-by-point responses and apply the configured round cap.
   Preserve every actual model receipt and failed run. Legacy decisions retain their basis.
3. Handoff checks the registered venue and hard limits, support registration, version,
   review snapshot and publication receipts. Route mechanical failures to control-plane
   repair or a retry. Include the advice in the delivery package.

The user reads the entire package and confirms submission. Report the panel models,
decision hash and run directory. Label reviews as internal. Copy the authenticated
writing_release into review_outcome and preserve any round_guard. A technical retry
does not spend a scientific round. For an accepted panel with an outstanding formal
issue, use unified-run --formal-only with the response bound to the blocked decision.
