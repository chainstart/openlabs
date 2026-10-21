# GDSC experimental concentration-support pilot

This study replaces the insufficient independent-assay chemistry pilot. It asks whether retrospective cross-screen fitted-IC50 ranking comparisons are supported by the experimental dose ranges. It does not claim true biological intervals, a new censoring algorithm, clinical efficacy or journal readiness.

The [frozen plan](plan-v2-frozen.json), [freeze ledger](freeze-ledger.json) and [source/prior-art audit](source-and-literature-audit.md) define the scope. An independent chemistry agent reviewed the plan and analysis code before joined outcomes. The original initial plan was not archived before edits; the transparently labelled semantic reconstruction preserves its content without claiming original bytes or an earlier timestamp.

Data workspace: `/home/biostar/work/openlabs-data/workspaces/biology/projects/biomed-drug-support-20261021`.

Artifact staging: `/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/drug-support-20261021`.

All interpreters and dataset processing require the repository CPU guard. Reproduction from repository root, after official intake:

```bash
bin/openlabs-resource-guard --task-type cpu -- env OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 labs/biomed/.venv/bin/python labs/biomed/studies/drug_support_20261021/run_pilot.py --root /home/biostar/work/openlabs-artifacts/artifact-stage/biomed/drug-support-20261021 --project /home/biostar/work/openlabs-data/workspaces/biology/projects/biomed-drug-support-20261021
```

Preparation writes exact official-name/model identity reconciliation and frozen diagonal split tables. The separate `--evaluate` option fits fixed predictors and opens the reserved diagonal block once; a marker refuses repeated test evaluation. Do not delete the marker to tune against the same holdout.

Main outputs are per-drug support/ranking statistics, matched-coverage rank controls, translation comparisons and conditional drug-bootstrap intervals. These statistics concern official drug-name groups with alias-conflict exclusions, not structure-verified unseen compounds. Their confidence intervals condition on the observed test cell panel.

The current factory protocol does not support the exact crossed independent-unit/split labels used by these studies. A computed scientific pilot and a factory-protocol-certified completion are distinct; preserve the truthful scientific definition and record any protocol rejection rather than weakening it to obtain a pass.
