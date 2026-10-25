# CRISPRi potency and context: 2026-10-21 bounded research

This is a same-study, donor/guide-aware exploratory experiment, not a paper claim.
It compares target-RNA-only amplitude calibration with frozen simple baselines.
Target RNA is measured after intervention; calibration is not a causal mechanism
or a prediction available before the intervention.

Code lives here. The immutable plan, selections, state and execution ledgers live
in `../openlabs-data/workspaces/biology/projects/biomed-fourlane-perturbation-context-20261021/`
relative to the repository root. Payloads, predictions and reports live in
`../openlabs-artifacts/artifact-stage/biomed/four-lanes-20261021/perturbation_context/`.
`intake.py` binds these to their full current-machine paths. No shared dependency
locks, factory state or other research lanes are modified.

## Execution and recovery

All commands require the assigned service inside `openlabs-workers.slice` and
the repository CPU resource guard. Use the absolute Python paths recorded in
the environment records. Maximum HTTP concurrency is two; numerical workers
use one BLAS/OpenMP thread each. No CUDA, model downloads or nested agents.

1. Verify payload hashes, quarantine damaged files without deleting originals,
   and preserve the original download budget and confirmation markers.
2. Complete `development_controls.csv` using `parallel_extract.py`. Its two
   transport shards do not change scientific splits. Both workers run inside
   the same service, with private writable range caches and shared read-only
   original fragments. Every downloaded range must be HTTP 206 with an exact
   byte range, declared total size, and the original object's ETag.
3. `screen_analysis.py select` freezes targets/features from development controls
   and metadata only. It refuses to overwrite an existing selection.
4. Extract `screen_development_rows.csv`; `screen_analysis.py develop` fits the
   fixed configurations using two development donors and guide 1 only.
5. `screen_analysis.py open` writes the one-time confirmation marker. Extract
   held-donor controls and held-donor targeting rows. `confirm` scores guide 2;
   held-donor guide 1 is used only for the residual replication diagnostic.
6. Independently reconstruct metrics from saved predictions. Such checks are
   verification of exposed outcomes, never new independent confirmation.

`run_screen_campaign.py` sequences the unfinished screen steps under the
original UTC deadline. Do not remove markers, edit frozen selections, reset
configuration/candidate budgets or rerun development after confirmation.
If a worker fails, inspect the retained logs and incomplete output before
resuming. A successful process exit is not a scientific completion criterion.

Example (from repository root, after completing control extraction):

```bash
bin/openlabs-resource-guard --task-type cpu -- env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 /home/biostar/work/projects/openlabs/openlabs/labs/biomed/environments/singlecell/.venv/bin/python labs/biomed/studies/fourlane_perturbation_context_20261021/run_screen_campaign.py
```

`bulk_analysis.py develop` and `confirm` implement the separately frozen
arrayed bulk follow-up. These have already been executed. Confirmation is
guarded against reopening. Two malformed development ENSG records and non-ENSG
annotation rows required a documented preprocessing correction before any fit;
see `bulk_count_exclusions_frozen.json`. The original scientific plan remains
unchanged on disk. Fractional count estimates make the Poisson variance
approximation a sensitivity model, not an established measurement distribution.

## Interpretation boundaries

There are four screen donors (two held out), not thousands of independent
samples. Batches and donors are partly confounded. The bulk panel comprises
nine author-selected targets and thirteen donors in a different culture/batch
regime, with uneven target coverage. It is not independent-laboratory validation.
No result establishes equivalence merely because an interval includes zero.

The pilot contract's three-way donor split applies to bulk. The screen has a
crossed donor/guide design with no independent third development donor and
cannot honestly be marked as passing that three-way contract. Final scientific
disposition belongs in `research_status.json`, `RESULTS.json`, and
`FINAL_REPORT.md`; `process-status.json` tracks only process liveness.
