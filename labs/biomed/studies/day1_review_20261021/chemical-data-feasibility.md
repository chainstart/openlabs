# Chemical data feasibility follow-up

Checked 2026-10-21. Read-only source inspection; no access to reserved scientific outcomes.

## Existing author repository

[rinikerlab/overlapping_assays](https://github.com/rinikerlab/overlapping_assays) contains only maximally curated IC50 and Ki catalogs and their compressed CSV files, plus one analysis notebook. Recursive GitHub tree inspection found no separate minimal/medium-curation exports. Broader levels would require reconstructing the queries against ChEMBL, not downloading an existing hidden level.

Important data-quality finding: the following two differently named endpoint files have **identical decompressed bytes**:

| Path under `datasets/source_data/` | Compressed bytes | Decompressed bytes | Decompressed SHA256 |
|---|---:|---:|---|
| `target_CHEMBL220-1.IC50.csv.gz` | 21076 | 136943 | `14fcb9cb958691999a7c05e99d899f145cf302f97fba21d4bffb06bcee01c074` |
| `target_CHEMBL220-1.Ki.csv.gz` | 21074 | 136943 | `14fcb9cb958691999a7c05e99d899f145cf302f97fba21d4bffb06bcee01c074` |

Both have 1582 rows and fields `assay_chembl_id,compound_chembl_id,canonical_smiles,pchembl_value`, without an endpoint column. This establishes a duplicate for this pair, not an author-error diagnosis or a claim that every export is invalid. The recursive tree shows the same two-byte size difference for many shared IC50/Ki names, motivating endpoint verification rather than treating Ki files as independent expansion. `target_CHEMBL205-1.Ki.csv.gz` has 4194 rows but its endpoint validity was not independently confirmed. Do not infer endpoint solely from filename.

## Other public assay-transition study

[Machine Learning Strategies When Transitioning between Biological Assays](https://pmc.ncbi.nlm.nih.gov/articles/PMC8317157/) states that its hERG/Nav core datasets are proprietary. [Its GitHub repository](https://github.com/pharmbio/assay-transition-study) provides code and a Tox21 example; the paper explains that the public example uses the same experimental setup and is only a crude validation of the different assay-shift setting. It therefore does not solve the need for independent paired assays. The legacy implementation also depends on an academic CPSign licence, so it is not an immediate drop-in execution route.

## Recommended bounded expansion

The chemistry study owner has verified a reduced-field ChEMBL37 endpoint query and is responsible for that download. Avoid duplicating their intake. Use a prospectively fixed target list, endpoint exact IC50, relation `=`, non-null pChEMBL, bounded pages and a per-target total-record cap. Keep activity IDs, standardized structure, assay/document IDs, endpoint/unit/relation, duplication/validity flags. Retrieve assay metadata and document DOI/year only for the resulting bounded distinct identifier lists. Separate eligibility selection using counts/structures/provenance from any performance-based selection. A large target activity count does not establish sufficient paired overlap or independent sources; these must be measured after filtering. Do not silently truncate a target and present it as complete.

## Additional nearest literature

* [From Predicted Ki to Surrogate IC50: Similarity-Guided Empirical Calibration of Drug–Target Affinity Predictions](https://www.biorxiv.org/content/10.64898/2026.09.04.749433v1.full), September 2026 preprint, DOI 10.64898/2026.09.04.749433. Indexed primary record describes similarity-guided residual/offset calibration. Its source is predicted Ki rather than measured source-assay activity, so it is adjacent rather than an identical estimand. Direct full text returned HTTP403 during this check; verify methods before making a novelty claim.
* [Few-Shot Bioactivity Prediction with Meta-Learning under Assay Heterogeneity](https://arxiv.org/abs/2610.07079), submitted October 5, 2026. MetaHeta conditions few-shot prediction on related-assay auxiliary data; the general idea of exploiting related assays under heterogeneity is already being studied.
* [Benchmarking compound activity prediction for real-world drug discovery applications](https://www.nature.com/articles/s42004-024-01204-4), 2024. CARA separates endpoint-specific assays and includes few-shot settings. A small anchor-label budget alone is not a novelty claim.

## Prospective plan review

Read `chem_shift_20261021/plan.json` only. Its explicit same-molecule assay-translation estimand and dependent target-level summaries are appropriate. No obvious label leakage is implied by the written plan, but code was not audited. Fix assay direction prospectively; both directions cannot count as independent assay pairs. Structural scaffold assignment from all candidate molecules is permitted as an explicitly unlabeled design operation. Preserve the >=10 independent-target publication gate; expanding targets is not permission to open the reserved outcomes early.
