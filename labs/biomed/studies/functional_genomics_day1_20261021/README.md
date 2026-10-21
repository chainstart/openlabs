# Frozen promoter orientation-contrast transfer pilot

This campaign tests a narrow empirical question: whether promoter-specific
sense-minus-antisense reporter effects transfer across cell contexts after
controlling overall reporter activity, source precision and shared sense bias.
It does not claim a new algorithm, mechanism, or publication readiness.

The 2021 Roberts paper (DOI 10.1101/gr.270751.120) already establishes generic
cross-cell strand asymmetry; Agarwal et al. 2025 (10.1038/s41586-024-08430-9)
already study orientation and cross-cell promoter correlations. The frozen
question is only a conditional extension on the latter study's original data.

Project records:
`/home/biostar/work/openlabs-data/workspaces/biology/projects/biomed-functional-genomics-day1-20261021/`.
Immutable intakes, models and predictions:
`/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/day1-functional-genomics-20261021/`.

All commands run from the repository root. Every Python invocation uses:

```bash
bin/openlabs-resource-guard --task-type cpu -- env OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 labs/biomed/.venv/bin/python labs/biomed/studies/functional_genomics_day1_20261021/SCRIPT.py
```

Actual stages, including rejected source/layout investigations, are recorded in
the project's events/status logs and metadata access/failure snapshots:

1. `probe.py`, `audit_sources.py`: official metadata, primary literature and terms.
2. `intake.py ENCSR405QCT ENCFF511XTZ --schema`: source-only format preview.
   The joint library has no paired reverse constructs and is entirely excluded.
3. `intake.py ENCSR022GQD ENCFF774DYO`, then `prepare_metadata.py`:
   three released GRCh38 coordinate BEDs, design fields only.
4. `screening.py`: three genuinely different candidate audits; pinned environment.
5. `freeze.py`: exact shared promoter identities, chromosome split, prospective plan.
   Refuses to overwrite the original freeze.
6. `download_replicates.py` and `download_confirmation.py`: at most two concurrent
   opaque intake streams. `intake.py ENCSR382BVV ENCFF857LYJ` prefetches the final
   planned training replicate after the confirmation stream finishes. The main
   queue reuses its completed immutable manifest. No additional dataset/trial.
7. `software_check.py`: small synthetic oracle checks, not biological experiments.
8. `initialize_state.py`, `literature_record.py`, `progress.py`: bounded local
   evidence bookkeeping, no factory state or scheduling changes.
9. `run.py select`: eight preregistered policies on K562 chr1–16, selection on
   chr17–18; saves models, ledger, source features and selection hashes.
10. `run.py confirm`: exclusively creates the confirmation marker **before** any
    WTC11 numeric parsing; parses only chr19–22 eligible loci, computes all frozen
    diagnostics in one pass. Refuses a second opening, including after a failure.
11. `finalize.py`: hashes payloads/code, reruns split/provenance validation,
    packages the report and result bundle. Never grants paper promotion.

`molecule` is the compatibility unit accepted by the lab's generic split audit;
here it explicitly means a paired genomic DNA locus, not a small molecule.
Uncertainty clusters loci into 1 Mb blocks, with a separate global target-culture
resampling sensitivity analysis. These are conditional intervals, not estimates
over independent cells, donors or laboratories.

An optional **numerical replay**, not a new confirmation experiment, reuses
immutable source files and requires new subdirectories and the exact installed
environment. It does not run automatically:

```bash
bin/openlabs-resource-guard --task-type cpu -- env OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 FG_PROJECT_ROOT=/home/biostar/work/openlabs-data/workspaces/biology/projects/biomed-functional-genomics-day1-20261021/replay FG_ARTIFACT_ROOT=/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/day1-functional-genomics-20261021/replay labs/biomed/.venv/bin/python labs/biomed/studies/functional_genomics_day1_20261021/reproduce.py
```

Do not adapt models, cutoffs or scientific claims using the consumed confirmation.
Any new claim needs a new prospective protocol and truly new validation data.
