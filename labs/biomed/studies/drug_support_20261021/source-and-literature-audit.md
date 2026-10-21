# Dose-support study: source and novelty audit

Checked 2026-10-21. This is an exploratory methods study; no journal selected or publication-readiness asserted.

## Official data verification

Official [Sanger dataset documentation](https://depmap.sanger.ac.uk/documentation/datasets/drug-sensitivity/) describes independently processed GDSC1/GDSC2 screens, different assay readouts, stable model IDs, duplicate compound DrugIDs and the shared nonlinear mixed-effects fitting procedure. Concentration bounds are in micromolar and LN_IC50 is natural log; AUC is normalized over the screen-specific concentration range. Released phenotypes were fitted using whole-dataset information, so held-out downstream labels are not raw-experiment-blind curve fits.

Actual HTTPS HEAD on official release8.5 URLs returned:

| File | Bytes | ETag |
|---|---:|---|
| GDSC1_fitted_dose_response_27Oct23.xlsx | 29353210 | d3db01db37e4bd461641a7bc9231012b |
| GDSC2_fitted_dose_response_27Oct23.xlsx | 21330376 | a57b46470f325ae5800dca24c72c19f5 |

Both support byte ranges. Bounded ZIP-member reads verified their actual 19-column headers, including SANGER_MODEL_ID, DRUG_ID, MIN_CONC, MAX_CONC, LN_IC50, AUC and RMSE. Only independent first rows were read for schema verification before the plan was frozen; no paired cross-screen result was examined at that stage.

Official `screened_compounds_rel_8.5.csv` has 46414 bytes and DrugID, screening site, primary name, synonyms, target and pathway. It has no structural identifier. The study therefore uses conservative official-name grouping with alias-conflict exclusion and explicitly does not claim structure-verified compound cold start.

## Reuse basis

The official Cell Model Passports application footer links to Sanger legal terms, which redirect to [Sanger terms of use](https://www.sanger.ac.uk/terms-of-use/). A dated HTML snapshot is retained in artifact staging. These terms request source acknowledgement for publications and default hosted content to CC BY-NC-ND 4.0 unless otherwise stated. The [original GDSC resource article](https://pmc.ncbi.nlm.nih.gov/articles/PMC3531057/) states that data are freely available without restriction. We use the official files for internal noncommercial research with attribution and retain file-level provenance. We do not infer an unrestricted file licence from the article licence, and we do not redistribute the raw spreadsheets or promise permission for commercial use.

## Nearest literature and contribution boundary

* [The specification game](https://link.springer.com/article/10.1186/s13321-025-00972-y), 2025. Already establishes concentration-range confounding, strong MAX_CONC dummy prediction and the importance of fixed-drug/fixed-cell evaluation. Repeating those observations is insufficient.
* [Benchmarking deep learning models for predicting anticancer drug potency](https://www.nature.com/articles/s42004-026-01916-9), 2026. Already notes extrapolated IC50 and excludes out-of-range fitted points in a model benchmark. Out-of-range prevalence is not novel.
* [Integrating heterogeneous drug sensitivity data](https://pmc.ncbi.nlm.nih.gov/articles/PMC5239501/), 2016, DOI 10.18632/oncotarget.10010. Already harmonizes concentration support through adjusted AUC. Common-support harmonization is not a new method.
* [Drug sensitivity prediction guidelines](https://pmc.ncbi.nlm.nih.gov/articles/PMC8575017/), 2021, DOI 10.1093/bib/bbab294. Already evaluates cross-domain generalization and sensitivity-metric choices. This study does not claim that cross-screen validation is new.

The prospective distinction is a deliberately coarsened **operational partial order** for the paired same-drug/same-cell screening problem: distinguish directly supported order comparisons from point-fit orders that depend on extrapolation; compare matched comparison coverage, report conservative pairwise outer agreement bounds and evaluate fixed translation models. The coarsened intervals are neither true biological bounds nor statistical confidence intervals. The diagnostic may yield a useful result, a duplication/no-go finding or only feasibility evidence. This targeted literature screen does not establish exhaustive novelty.
