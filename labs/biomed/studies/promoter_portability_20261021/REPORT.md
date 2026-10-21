# Promoter directionality portability: bounded research report

Completed 2026-10-21T02:48:04.690673+00:00. **Independent reporter-system transfer remains untested; paper_candidate=false.** A prospectively frozen fallback analysis provides new, limited evidence about promoter-activity directionality across minimal-promoter contexts within QUASARR-seq. It is not independent replication of the old Agarwal/WTC11 result, a new algorithm, or a causal mechanism.

## Scientific result

Across **150 held-out genomic elements / 123 locus-homology groups**, a model trained on MYC→GAPDH promoter activity and selected without test labels predicted GAPDH→APOBEC3F forward-minus-reverse promoter activity with MSE **0.305603**, versus **0.385577** for the validation-selected strongest activity/nuisance baseline. Relative improvement was **20.74%**, with paired component-bootstrap 95% interval **4.10% to 32.78%** (2,000 resamples). The frozen criterion required a point improvement ≥5% and absolute-improvement interval above zero; it passed. The interval does not establish that the true improvement exceeds 5%.

The primary endpoint is **promoter paBC log2(RNA/DNA), forward minus reverse**, averaged across two replicate columns. Every analyzed row measures local promoter activity. Including distal elements does not replace the endpoint with enhancer activity, but it limits the claim: the main panel mixes proximal and distal regulatory elements. **Only 55 test elements are annotated proximal promoters.** Their estimated improvement was 16.85%, interval **-11.87% to 34.94%**; promoter-only portability is inconclusive. The 95 distal elements showed 25.51% improvement. These predefined strata are descriptive, not separate confirmations.

## What failed or weakened

* Directly copying source directionality had MSE **0.275216**, better than the selected learned model. The latter was **11.04% worse** than direct copying (post-outcome descriptive comparison; interval includes either ordering). There is no evidence here that the learned method improves on the simplest direction-preserving translation.
* The predefined reverse-complement antisymmetric sequence model had MSE **0.437635**, worse than the selected activity baseline. This small k-mer model supplies no positive sequence-only portability result.
* The same-mapping MYC→GAPDH test improvement was **34.37%**, compared with 20.74% after changing the source/target contexts. Different target variances preclude reading their raw MSE difference as a pure context causal effect.
* Both precision strata and the low-activity stratum had improvement intervals crossing zero. The high-activity stratum contains only 15 loci; it cannot establish a reliable general failure/success boundary. Proximal-promoter insufficiency is the clearest limitation.

The test-best nuisance model, selected after outcomes only as a diagnostic, had MSE 0.373332; the frozen selected model still improved by 18.14% against it. This comparison does not replace the primary selection or add a new configuration.

## Controls and measurement limits

Target replicate directionality correlation was **0.868**. Source/target residual directionality correlation after training-only nuisance regressions was **0.578**. Both target replicate contrasts separately favored the selected source-informed model over the selected baseline. None establishes mechanism or independent-laboratory reproducibility.

There were 1,000 component-wise source sign-flip controls and 1,000 source-direction permutations within source-activity tertiles, applied to frozen models with nuisance features unchanged. No control MSE was at or below observed selected-model MSE (empirical fraction 0/1,000; finite simulation resolution, not p=0). Exact antisymmetry of the sequence model was checked computationally. These are conditional model controls, not independent biological experiments.

## Independent-source feasibility: three routes

1. **QUASARR-seq, Paramo et al. 2026, DOI 10.1038/s41467-026-68780-y, GSE310760.** Official publisher source workbook (4.62 MB) contains element coordinates, sequences and GENCODE classifications; four small processed paBC tables contain explicit `.fwd`/`.rev` pairs. The author repository was pinned at `bfd61cfef97b51428e26e8ea2fa9f918b41316aa`. There are 716 paired elements in the original library and 1,093 / 1,439 / 1,195 in MYC / GAPDH / APOBEC3F contexts before genomic eligibility. Original measurements are a different laboratory/vector from Agarwal. However, **ENCSR382BVV is exactly the old K562 source** and is not independent evidence. Literal coordinate comparisons found zero exact old-promoter tuples and 215 overlaps across all supplied coordinates. Genome-build harmonization and old/new insert sequence/strand identity were not established; the tuple result cannot prove biological disjointness or exact matches. Elements vary 65–703 bp. The fallback therefore evaluates contexts only. Cross-system generalization remains open.
2. **Roberts2021, DOI 10.1101/gr.270751.120.** Cached original XML identifies GSE156857, reused SuRE GSE128325, and Johnson SRP144640. Downloaded official processed HTT/SORT1 stranded tables are 290-bp bin summaries of heterogeneous-fragment STARR assays, not matched exact forward/reverse promoter inserts. SuRE's official file inventory was inspected: stranded genome-wide tracks likewise aggregate fragments. No promoter endpoint was fabricated from these bins, and the 12-GB raw archive was not downloaded. A different bin-level STARR/SuRE comparison would substantially repeat Roberts and would need a separately justified question.
3. **Bose2025, DOI 10.1101/2025.10.13.659964, GSE279057.** Original XML, pinned author analysis code and the 9.15-MB annotation file were inspected. The annotation table has **79,380 records, 39,653 unique sequences, and zero exact non-palindromic reverse-complement sequence entries**. Four plasmid configurations mean INS/SCP1 promoter × upstream/downstream position; CAGE strand annotation is not a reverse-cloned insert measurement. No valid paired-directionality panel was established. Barcode/count payloads were not fetched after this design-level failure.

These findings support a scoped feasibility no-go for the requested exact-insert independent transfer analysis with the audited files, not a claim that no useful independent data exist anywhere. A sequence-only cross-study design would need its own orientation/sequence audit and novelty justification; sequence prediction alone is already prior art.

## Prospective validation boundary

Before numerical outcomes, the sample table, grouping, endpoint, MSE metric, ≥5% criterion, 11 configurations, bootstrap unit and source/target mapping were frozen. The eligible autosomal panel had **358 elements: 159 train, 49 validation, 150 test**, including 124 proximal elements total. The 150 test rows occupy 123 1-Mb blocks. Hash-assigned connected components grouped coordinate overlap, 1-Mb blocks, exact/reverse-complement identity, and ≥20% canonical 21-mer containment. The 40% test allocation was selected before labels to retain ≥100 loci and ≥30 blocks. All 150 test loci passed positive finite RNA/DNA QC; no target-label trimming or imputation occurred.

The source measurements at test loci are explicitly available: this is measured-source transfer. Scaling, imputation-free features and model fitting used training loci only. Validation selected `activity_ridge` and `full_hgb`. No refit followed. Confirmation has one start and one completion marker. The old WTC11 confirmation was never used for selection; all old frozen-input hashes still match. Molecular compatibility fields explicitly mean **DNA locus, not small molecule**.

The split tool passed its supported identifier-overlap audit. It does **not** establish independent studies/donors, genome-build harmonization, exhaustive distant homology, full genome alignment, construct resequencing, or genomic-reference strand identity. Those unsupported audits are explicitly recorded, not marked passed. Author forward/reverse labels are used within contexts; sequence-table orientation is not asserted to be genomic strand. The main selected model uses composition and measured source directionality, not a genomic strand claim.

| Frozen configuration | Validation MSE | Context test MSE (descriptive except selected primary) |
|---|---:|---:|
| zero | 0.262591 | 0.396003 |
| median | 0.266253 | 0.401088 |
| activity_ridge | 0.262460 | 0.385577 |
| nuisance_ridge | 0.264878 | 0.373332 |
| nuisance_hgb | 0.318528 | 0.424563 |
| identity_delta | 0.338949 | 0.275216 |
| delta_ridge | 0.122757 | 0.276066 |
| full_ridge | 0.115382 | 0.274906 |
| full_hgb | 0.107679 | 0.305603 |
| antisym_seq | 0.206065 | 0.437635 |
| full_plus_seq | 0.115085 | 0.350740 |

## Novelty and disposition

Roberts2021 already studies cross-assay strand asymmetry and sequence predictors. Agarwal2025 (DOI 10.1038/s41586-024-08430-9) supplies the old shared-study/vector panel. Bose2025 studies promoter/position biases and sequence/strand associations. Paramo2026 already demonstrates minimal-promoter effects on overall promoter activity. This analysis adds only an incremental, prospectively evaluated **activity-conditioned directionality stress test** with explicit failure/uncertainty findings. It does not establish a new biological mechanism, and no RNA-stability association is given a causal interpretation.

**Paper development no-go pending independent scientific review and a valid independent reporter-system panel.** No claim of Zone 2 quality or publishability is made. No journal recommendation, submission, payment, global scientific database write, external message or public release occurred.

## Verification and reproducibility

All nine scientific payload manifests were revalidated by actual size and SHA-256. Publisher and GEO DNA1/DNA2/RNA1/RNA2 counts agree across all four promoter tables to floating-point precision (maximum relative discrepancy <1.7e-16). Every saved prediction MSE was independently recomputed. The original code freeze and all old frozen-plan hashes passed. A deterministic replay reproduced every metric and the exact prediction CSV bytes; it is labeled replay, not new validation.

Current cgroup peak memory was 494.6 MiB, below the 2-GiB supervisor limit; OOM events were zero. All runtimes inherited the verified worker cgroup, with two-thread limits. Replay explicitly invoked the CPU resource guard. No GPU, package installation or raw sequencing download was used. HTTP concurrency never exceeded two.

See `result_bundle/README.md` for exact replay command, hashes and artifact paths. Primary records: `plan.json`, `samples.csv`, `freeze-hashes.json`, `code-freeze.json`, `complete-trial-ledger.json`, `results.json`, `validation.json`, `design-alternatives.json`, `sequence-locus-audit.json`, `post-outcome-diagnostics.json` and `intake-manifests/`. Failed attempts are preserved in the complete ledger and metadata failure records.
