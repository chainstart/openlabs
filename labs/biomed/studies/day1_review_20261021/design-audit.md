# Independent day-one design audit

Date: 2026-10-21. Status: prospective methodological review; no experimental results and no publication-readiness claim. No journal selected.

The academic-search MCP inventory is not mounted in this session. Discovery used web searches pointing to primary journal, PubMed, PMC and preprint records. This is a targeted nearest-neighbour screen, not an exhaustive systematic review. ACS full text returned HTTP 403; the PubMed direct page for PMID 42679554 did not return its article body, although the indexed PubMed record exposed title, DOI and abstract. Treat inaccessible full texts as remaining verification work.

## Chemistry: initial idea has high duplication risk

* [Scaffold-shift uncertainty calibration in molecular activity prediction: A multi-target benchmark of coverage, efficiency, and risk-aware selection](https://pubmed.ncbi.nlm.nih.gov/42679554/), 2026, DOI 10.1016/j.compbiolchem.2026.109371. Indexed abstract describes ChEMBL 37, six targets and 20 scaffold-disjoint partitions. A scaffold/conformal benchmark alone is not a defensible novelty claim.
* [Machine Learning Strategies When Transitioning between Biological Assays](https://pubs.acs.org/doi/10.1021/acs.jcim.1c00293), 2021. Describes training with old-assay records and calibration exclusively on a new assay. New-assay calibration itself is established.
* [Studying and mitigating the effects of data drifts on ML model performance at the example of chemical toxicity data](https://www.nature.com/articles/s41598-022-09309-3), 2022. Studies both temporal and assay/source drift with calibration-set updates.
* [Matched pairs demonstrate robustness against inter-assay variability](https://link.springer.com/article/10.1186/s13321-025-00956-y), 2025. Studies paired potency differences, assay metadata curation and noise. Simple matched-pair cancellation is established.
* [Identifying and Addressing Systematic Data Leakage in Protein-Ligand Affinity Benchmarks](https://www.biorxiv.org/content/10.64898/2026.06.29.735309v1.full), 2026 preprint. Flags shared assay/document leakage; do not present publication or assay identifiers as independent without upstream audit.

Potential distinct question, subject to further screening: do structure-only applicability indicators fail to detect measurement-source shifts after controlling chemical similarity, and can a small prespecified source-label budget diagnose that failure? Separate chemical extrapolation from assay measurement heterogeneity. All potency records must share target, measurement type, relation and compatible units. No IC50/Ki/Kd blending. Assay metadata and release must be retained.

Minimum useful evidence: multiple independent assay/source groups; frozen calibration and test boundaries; strongest simple similarity and residual baselines; matched label budgets; molecule/scaffold-aware uncertainty. Stop the paper claim if the dataset contains too few independent groups, source is confounded with chemistry with inadequate common support, prior work already tests the same question, or gains vanish against matched simple controls. A negative result can be valid, but is not automatically publishable.

## Biology: favour cross-laboratory CRISPR risk prediction over generic transcriptomic transfer

The generic cross-study transcriptomics proposal has direct predecessors:

* [Cross-study validation for the assessment of prediction algorithms](https://academic.oup.com/bioinformatics/article/30/12/i105/388164), 2014, DOI 10.1093/bioinformatics/btu279. Already reports CV optimism and changed model rankings.
* [Best holdout assessment is sufficient for cancer transcriptomic model selection](https://pmc.ncbi.nlm.nih.gov/articles/PMC11701843/), 2025. Directly addresses generalization-oriented model selection.
* [High AUROC can mask decision failure in sepsis transcriptomic classifiers](https://pmc.ncbi.nlm.nih.gov/articles/PMC13541173/), 2026, DOI 10.1371/journal.pone.0357585. Includes fixed thresholds, multiple GEO cohorts, cross-platform testing and sample-wise rank preprocessing. Repeating these observations is insufficient.

The proposed Broad/Sanger CRISPR direction has a more specific testable contribution: learn source-laboratory indicators of cross-laboratory disagreement and test their selective error reduction on held-out gene and cell-line blocks. This is not yet established as novel by this limited search.

Relevant primary prior work and boundaries:

* [Official Broad/Sanger joint project](https://depmap.org/broad-sanger/) summarizes the original agreement analysis and unified data. The measurements are not interchangeable independent replications if the released matrix was already integrated using both laboratories.
* [Reproducibility metrics for context-specific CRISPR screens](https://pmc.ncbi.nlm.nih.gov/articles/PMC10266068/), 2023. Explains why global correlations can hide sparse context-specific irreproducibility; introduces WBC. Include a context-specific assessment, not global correlation alone.
* [Benchmark Software and Data for Evaluating CRISPR-Cas9 Experimental Pipelines Through the Assessment of a Calibration Screen](https://journals.sagepub.com/doi/full/10.1089/crispr.2023.0040), 2024. Provides existing quality/reproducibility metrics and highlights misleading high background correlation.

Define the target carefully: raw absolute disagreement includes cross-laboratory scale and location differences. Fit any affine harmonization exclusively on training genes and training cell lines; report raw and harmonized residual targets as prespecified sensitivity analyses. Only two laboratories support transfer to unseen genes/cell lines within this laboratory pair, not to an unseen laboratory. A model that accesses source-laboratory measurements for test genes has target-label cold start, not complete gene-information cold start.

Required comparisons: absolute source effect, gene-level variance, cell-line quality where available, training-only additive gene/cell summaries, a simple regression baseline, and matched-random rejection. Evaluate risk at equal retained fractions, with gene and cell dependence respected. Predeclare primary retention and effect size; do not cherry-pick curves or genes. Stop/replan on integrated-target circularity, incompatible identifiers/scales, insufficient overlap, leakage, or failure to outperform the strongest inexpensive score under appropriate uncertainty. Retain null and failed outcomes.

## Day-one claim boundary

Acceptable deliverables are audited data, a frozen plan, reproducible baselines, effect sizes with dependence-aware uncertainty and a clear novelty gap or stop decision. One day is a computational deadline; it does not establish journal tier, biological causality or publication acceptance.
