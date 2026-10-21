---
name: biomed-research-loop
description: Run OpenLabs public-data computational biology and cheminformatics pilots, including provenance, molecular or donor-aware splits, matched baselines and reproducible evidence. Use for the biomed lab; excludes wet experiments and clinical practice.
---

# Computational biomedicine research

Use `lab_id: biomed`, `domain: biology` and the `biomed-public-data-pilot` protocol.
Read the lab [README](../../README.md), source registry
`../../registries/data_sources.json` and [evidence contract](references/evidence-contract.md)
before creating a project. The protocol admits exploratory computational pilots only;
passing it never establishes novelty, biological mechanism or publication readiness.

Work from a falsifiable question and a dated audit of the closest literature. Prioritize
chemical activity generalization, cross-study transcriptomics and cell-line dependencies.
Single-cell work must retain donor and study identities. No wet experiments, patient
recruitment, clinical intervention, clinical decision service or restricted-access data.
Public patient-derived molecular data remain subject to their actual terms; public access
does not establish exemption from institutional review.

Use official API/download routes, record exact releases/accessions and upstream overlap,
and intake into the task's artifact staging directory with `tools/dataset_intake.py`.
Never substitute a source's web-access status for file-level reuse terms. Resolve identifiers,
assay units, censoring and repeated measurements before modeling. Do not mix IC50/Ki/Kd
or incompatible assays without a justified measurement model.

Freeze the plan, environment, sample table and split audit before comparing models.
Use `tools/split_audit.py`: group by standardized molecule/scaffold, donor or cell line as
appropriate; preserve study groups for external validation. Features, normalization,
imputation and tuning learn only from training folds. Test frozen holdouts once; adaptive
reuse requires a new holdout. Distinguish inductive from explicitly transductive analyses.

Compare with strong simple baselines and the closest relevant method under matched budgets.
Record all trials, seeds, failures, exclusions, effects and uncertainty at the independent
biological unit. Do not treat cells or repeated assays as independent donors/molecules.
Track pretrained-model data overlap and knowledge-graph source circularity. Enrichment,
SHAP, attention and docking are supporting analyses, not proof of mechanism or efficacy.

Run bounded CPU pilots first, with the repository resource guard. CUDA computation always
requires its own GPU reservation. Do not install deep-learning dependencies or download full
atlases merely to explore feasibility. Stop/replan when data provenance, sample independence,
the validation boundary or resource feasibility fails.

Keep plans and small state in the declared data workspace, bulky payloads in artifact staging;
return hash-bound `openlabs.result_bundle.v1` evidence without touching factory SQLite.
Use the existing `openlabs-biology-paper` workflow only after a substantive result, novelty
audit and independent validation. Follow the current repository and data-registry journal
policy at that time; this skill neither selects a journal nor authorizes submission/release.
