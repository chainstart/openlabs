# Independent CRISPR plan/code audit

Date: 2026-10-21. Read only `biomed-bio-shift-20261021/plan.json` and `bio_shift_20261021/run_pilot.py` before outcomes; no reserved target results inspected and no other agent's code edited. This is a static audit, not an execution test.

## Main finding

The written plan correctly states **target-label cold start with observed source profiling**, rather than unprofiled genes/cells. Gene features depend on source values from training cells and cell features depend on source values from training genes. The global affine map and both risk models use the training target diagonal block. Validation determines ordering signs and the simple comparator. Test predictions and subsets are formed once after the selection file is written. No obvious computation path uses test destination labels to fit transformations, features, models or selection.

The initial TSV reader loads full destination numeric data into memory, so the plan's phrase “off-diagonal target labels are never read” is physically inaccurate. They are loaded but not extracted into fitted blocks by the visible code. State the computational boundary accurately; full input availability is not itself an analytical leak when operations are constrained as shown.

## Required execution checks identified

* The written stop condition requires adequate informative **validation and test** support; code currently checks the test only. Add the validation check before sign/comparator selection. `metric` receives an empty array without raising a clear error, producing NaN and potentially arbitrary selection.
* `sd_cut=np.quantile(gene_sd[gp==0],.75)` propagates NaNs. Explicitly reject invalid descriptor populations or use a documented finite-only rule and record exclusions. All selected validation metrics and predictions must be finite before selection is frozen.
* Record informative validation/test gene and cell counts separately, and counts retained by each method. Shared full-data counts do not establish support for the primary subset.

## Bootstrap and weighting

The current two-way resampling draws test genes and test cells independently and multiplies their occurrence counts. Within each method's frozen retained set it normalizes by that set's resampled weight sum. Subtracting those two weighted MAEs using the same resample is appropriate for the stated **frozen-policy, pair-weighted conditional contrast**. It does not accidentally apply one method's denominator to the other. If a replicate has no retained observations, report its frequency rather than silently treating fewer successful resamples as 500 valid draws.

The procedure does not refit models, reselect signs, select the baseline again or move retention thresholds. Its interval therefore excludes training and selection variability. It cannot be labelled uncertainty for the full model-development procedure. This frozen-set estimand also differs from refinding exactly 50% retention in each newly sampled population. Preserve the frozen estimand and explain it.

The average is over available informative gene/cell pairs, not a macro-average of genes or cell lines. Genes with more informative events receive more weight. This is defensible if stated explicitly; claiming “target-weighted” or equal-gene error would be inaccurate. Target finite-value filtering means the estimand is conditional on paired available measurements; destination missingness could select a nonrepresentative subset.

Two-way bootstrap does not manufacture independent replication. The number of unique test cell lines, especially in the informative subset, limits confidence. Genes may share pathways and cell lines may share donors/lineages; crossed resampling only approximates that dependence. A minimum of 10 cells is a software feasibility boundary, not a power or publication standard.

## Comparator fairness and interpretation

Validation-only sign choice gives simple scores a reasonable opportunity. However, `positive_pilot_signal` currently means HGB beats the validation-selected simple score only. It can be true even if Ridge is better. Keep the prespecified primary contrast, but report HGB versus Ridge as a paired contrast and require the strongest inexpensive comparator to be addressed before scientific promotion.

Gene standard deviation is tied across every cell for that gene. Stable sorting resolves boundary ties by existing row order; a fixed label-free tie hash would avoid an arbitrary identifier-order effect. Do not interpret accidental tie handling as a methodological gain.

The informative subset excludes many easy flat dependencies by design, which is preferable to a misleading genome-wide correlation. Nevertheless, selecting low source values may introduce regression-to-the-mean differences across laboratories. Include this as an interpretation boundary; a risk model predicting that pattern does not establish a biological mechanism or experimental assay failure.

Only two historical laboratories are represented. Even a positive untouched diagonal test result supports a limited retrospective source-conditioned replication-risk result within that pair. It establishes neither third-laboratory generalization nor a therapeutic target, and remains an exploratory pilot.
