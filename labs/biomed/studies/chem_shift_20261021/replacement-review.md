# Independent prospective review: drug-response support and ranking

2026-10-21. Reviewer has not inspected replacement-study results or test labels. This memo concerns the proposed design, not an assessment of observed effects. The original chemical assay-transfer no-go remains unchanged.

## Main design risk: what does an interval mean?

Published fitted log(IC50) outside the tested concentration range establishes extrapolation of a fitted parameter. By itself it establishes neither a statistical confidence interval nor a verified bound on the true biological IC50. Even fitted IC50 inside the concentration range is not known exactly. A maximum-dose metadata field is also not the set of observed viability responses.

With only fitted tables, a defensible analysis is an explicitly declared **coarsening sensitivity analysis**: hide the magnitude of extrapolated fits and retain only an operational range category. One may then study which fitted-response rankings survive that coarsening, or their cross-screen reproducibility. One cannot infer latent true-potency identification or confidence coverage from this operation. Any proposed interval [max dose, infinity) must be named an assumption/policy-based support representation, not an empirically measured censoring interval. Left extrapolation needs its corresponding treatment too.

If raw viability observations, dose schedules and assay controls are obtained, bounds require additional assumptions, such as a monotone response and a reliable crossing threshold. Noise, nonmonotonicity and incomplete efficacy can still invalidate a naive bound. Distinguish absolute 50% viability inhibition from half of a fitted curve's own maximal effect.

## Ranking and fair comparisons

* Predeclare fixed-drug ranking of cell lines and fixed-cell-line ranking of drugs as different tasks. The latter compares drug-specific concentration protocols and is especially vulnerable to dosage design. Global pooled correlation is inadequate.
* For declared intervals [L,U], a strict ordering is supported only when U_a < L_b (and the potency direction is stated). Touching intervals and equal fits do not support a strict order. Infinite endpoints need explicit behavior. The primary estimand must state whether it concerns fitted parameters under coarsening or latent biological response.
* Abstention removes difficult pairs. Higher agreement among retained pairs is not sufficient. Report retained-pair coverage against all eligible pairs, full denominators, drug-weighted performance, and a matched-coverage comparison against random abstention, raw-fit margin filtering and a simple dose/support-only rule. Test any added method against these controls.
* Hundreds of thousands of cell-line pairs do not create hundreds of thousands of independent replications. Pairs share drugs/cells; use drug-level primary aggregation and drug-cluster uncertainty for the fixed-drug task. Sensitivity to cell clustering is needed. Do not bootstrap individual pairs.
* A minimum number of independent held-out drugs must be fixed from provenance/availability before observing effects. Drug aliases and analogs must not cross the intended identity boundary. A null or heterogeneous result must remain admissible.

## Cross-screen boundaries

GDSC1 and GDSC2 are different assay generations, with shared cell lines and drugs. Their overlap can validate within-compound cross-screen reproducibility if underlying measurements are separate. It does not establish independent novel-drug/cell-line prediction or replication in a different laboratory. Pin releases and investigate any shared/repackaged measurements.

Drug matching should prioritize an official compound identity mapping or standardized structure identity, with a frozen alias table and one-to-many ambiguities excluded/flagged. Matching solely on DRUG_ID or a lowercased name can incorrectly split aliases or combine distinct compounds. Cell lines need a stable official identifier; COSMIC/Sanger/DepMap/name mappings require a documented join audit. Replicate rows and multiple concentration protocols for the same compound-cell pair must retain their identity before any aggregation.

Do not directly compare normalized AUC values from different dose ranges. Shared-range AUC requires the relevant curves or sufficient fitted parameters and an explicitly common integration interval; normalization by range width alone does not equalize the integrand's concentration support. Do not relabel a response endpoint as clinical sensitivity.

## Closest literature and what remains potentially distinct

* [Codicè et al., 2025, The specification game](https://doi.org/10.1186/s13321-025-00972-y) already studies strong drug/cell identity and maximum-concentration baselines, aggregation axes, and generalization splits. Repeating the MAXCONC effect or dose-only baseline success is not a new contribution.
* [Pozdeyev et al., 2016, Integrating heterogeneous drug sensitivity data](https://pmc.ncbi.nlm.nih.gov/articles/PMC5239501/) already analyzes incomplete curves, losses from IC50 capping, multiple maximal concentrations, shared-support adjusted AUC, and cross-study agreement. Shared-range response comparison itself is established.
* [Drug sensitivity prediction guidelines, 2021](https://pmc.ncbi.nlm.nih.gov/articles/PMC8575017/) discusses unstable off-support IC50 estimation and the information loss caused by capping. Generic censoring awareness is established.
* The [official GDSC curve-fitting implementation](https://github.com/CancerRxGene/gdscIC50) is the appropriate starting point for interpreting response-table units and concentration scaling. Verify actual release columns and protocol rather than assuming a universal dose schedule.

A narrower potentially useful question is whether a predeclared coarsening-aware abstention rule improves **cross-screen reproducibility of rankings at matched coverage** beyond fit-margin and support-only rules, and whether this survives held-out drugs and dose-range mismatch strata. This remains a candidate gap from bounded primary-source searches, not established novelty. With no raw-curve evidence, avoid the stronger phrase “true rank identifiability.”

## Go/no-go before confirmation

Proceed only after endpoint units, compound/cell mapping, assay-generation provenance, sufficient held-out drugs, operational coarsening semantics, and matched-coverage baselines are frozen. A fitted-table-only feasibility pilot may proceed under the narrower interpretation. Claims of true-potency bounds or clinical utility must remain blocked without additional evidence. No publication, submission, fee or external communication is authorized by this review.

## Review of the first written plan

Read only `studies/drug_support_20261021/plan.json`, before replacement outcomes. Its explicit conditioning on released fits, non-CI disclaimer, source-to-destination direction, pairwise outer-bound disclaimer, identifier policy, and two-axis holdout resolve the largest conceptual risks. The bounds are algebraically valid outer bounds for the declared coarsening scenario when ties are handled explicitly; they do not establish biological rank identification.

Requested amendments before evaluation:

1. Include matched-coverage random and raw-fit-margin abstention controls for the primary reproducibility analysis. A support-selection statistic alone can improve merely by deleting difficult cases.
2. Include a dose/MAXCONC-only secondary prediction baseline, ideally with the same fitting budget as the full feature model. Otherwise the established protocol-design predictor is absent.
3. Mark destination-support restriction as evaluation-only retrospective stratification. It reads destination fitted outcomes and is unavailable as a prospective source-only admission rule.
4. Specify destination ties, empty denominators, minimum supported/ambiguous count per drug, and whether `max_trials: 2` denotes the two split evaluations or individual fitted estimators. Report all fitted estimators and failed trials regardless.
5. Add the 2016 shared-dose-support/IC50-capping paper and 2021 guidelines to the novelty boundary. The absence of an exact match in bounded searches is not proof of novelty.

No results, fit values, test comparisons or observed effect sizes were inspected in making these recommendations.

## Prospective implementation review

Read only `studies/drug_support_20261021/run_pilot.py`, before replacement outcome evaluation. The interval construction matches its declared operational definition; strict interval disjointness and pairwise outer-bound arithmetic are consistent. Random and raw-fit-margin controls retain the same number of eligible comparisons. Predictor fitting/scaling uses the train-drug × train-cell block; uncertainty resamples drugs rather than individual pairs. These checks do not validate biological interpretation or empirical performance.

Implementation changes requested directly to the executor:

* Gate on at least ten **rank-eligible** held-out drug names with at least twenty cells each, separately from the total test-drug count. Handle an empty rank table as non-evaluable rather than crashing.
* Bootstrap primary support-versus-margin/random differences on the same drug intersection. Separate macro means with different missing-drug sets are not paired contrasts.
* Move metadata eligibility checks before the once-only test marker where possible. Preserve a failed opening rather than silently rerunning tests after adaptive changes.
* Reject or explicitly flag concentration minima exceeding maxima; positivity and finiteness alone do not establish valid supports. Guard empty translation-contrast subsets.
* With only exact official names and target/pathway corroboration, use **drug-name-heldout** terminology. Unverified aliases or close analogues can cross the split; compound/scaffold independence is not established. This is a limitation of the inference population and cluster uncertainty, not necessarily a reason to stop the software pilot.
* A full-feature HGB versus dose-only Ridge comparison changes capacity as well as inputs. It cannot isolate biological information beyond dosage. Use a matched-capacity dose-only comparator before making that claim, or omit the stronger interpretation.

The reviewer did not modify the replacement implementation and did not inspect any outcome files.
