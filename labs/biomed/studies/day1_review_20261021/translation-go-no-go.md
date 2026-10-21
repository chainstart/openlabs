# Prospective gate: measured-source assay translation

Date: 2026-10-21. No confirmatory outcomes inspected. This reviews the question, not a claim that the data meet it.

## Identifiable estimand

For a fixed target and endpoint, assume the exact candidate molecule already has an observed source-assay value. Purchase a budget of destination-assay labels on selected anchors; predict destination values for other molecules. This is assay translation, not de novo bioactivity prediction and not the prediction of unseen molecular structures without measured source values. Scaffold holdout means new scaffolds relative to the paired anchor set, not absent source information.

The estimand is conditional on compounds present in both assays. Retrospective overlap is a selected population, so it cannot establish performance for the full source library or prospectively untested compounds. Selection based only on structures and source values is allowed; destination labels must remain hidden until selected anchors are revealed. Source potency itself is legitimate selection information here.

## Strongest simple design competitors

Chemical maxmin versus random alone is insufficient. Include a fixed source-potency coverage selector, such as quantile-spaced source values or one-dimensional maxmin, and a prespecified joint structure/potency selector if feasible. The [Assay Guidance Manual](https://www.ncbi.nlm.nih.gov/books/NBK92013/) already recommends a small number of compounds spanning the activity and potency range for reproducibility/transfer assessment. Such coverage is prior practice, not a novel selector.

Compare selection strategies under identical destination-label budgets and identical held-out molecules, retaining identity, paired offset and affine baselines. Separate the effect of selector from the effect of translation model. Do not choose the best selector/model per test pair and average that oracle. If any policy switches between them, fit its rule using development targets only and freeze it before confirmatory targets.

## What could add scientific value

A potentially substantive result would identify and independently confirm a practically useful boundary: for example, chemical diversity fails when calibration depends on source-potency range, or nonlinear structure residuals remain material after affine correction and cannot be recovered by range coverage alone. It needs quantified differences, uncertainty, retained failures and independent provenance. These are candidate hypotheses, not conclusions to write before results.

Another potentially useful result is a reliable development-only decision rule for whether an assay pair needs only an offset, an affine map, or no safe translation at the available budget. It must beat fixed simple policies on untouched targets, including the cost of diagnosing the relationship. Without sufficiently many training and confirmatory targets, such a rule is not estimable. Do not add it simply to rescue a weak experiment.

## Strict go/no-go

1. **Data gate:** exact endpoint/unit/relation, trustworthy assay and document identities; no filename-only endpoint inference; enough overlap and scaffolds; no copied experiment counted as independent. Exclude same-document pairs from the primary cross-source claim, or explicitly limit the claim. Metadata differences do not prove independent measurement.
2. **Independence gate:** targets, papers and overlapping assay-pair networks are not interchangeable independent observations. Use one prospectively chosen pair per target, or target-level aggregation with paper connectivity disclosed. Shared targets/protein families can still correlate; report that limitation. Repeated seeds and anchor budgets do not increase sample size.
3. **Novelty gate:** gains over identity alone, observable offsets, few labels helping, or maxmin beating random do not exceed existing 2021 assay-transition and 2024/2025 assay-noise findings. Require the above strongest selection baselines and a specific additional testable insight.
4. **Effect gate:** choose the minimum practically relevant MAE difference and primary budget before the new outcomes. Judge a paired target-level effect with uncertainty, not a list of favourable examples. Do not invent a numerical threshold after viewing outcomes. An isolated improvement on one pair is no-go for a general claim.
5. **Confirmation gate:** preserve untouched targets and freeze any criterion before opening them. If fewer than the existing >=10 independent eligible-target rule remain, do not weaken it after seeing the data. Counts alone are not sufficient; a separate confirmation boundary remains necessary.
6. **Robustness gate:** a potential contribution should survive duplicate/source exclusion, fixed assay direction, matched evaluation support and leave-target-out sensitivity, and should not be driven by one target or one document. If all methods nearly equal identity, the data do not test the intended shift question.

Failure at any gate leaves a useful exploratory/feasibility report, not a paper-ready result. The one-day deadline does not justify relaxing these boundaries.
