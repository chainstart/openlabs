# Promoter portability study

Prospective fallback context-transfer study. See the committed [report snapshot](REPORT.md); full local evidence is in /home/biostar/work/openlabs-data/workspaces/biology/projects/biomed-promoter-portability-20261021/.

Original order: audit.py, metadata_routes.py, intake.py, geo_intake.py, workbook_schema.py, design.py, identity.py, novelty.py, bose_audit.py, context_feasibility.py, freeze.py; write code-freeze.json before run.py select; run.py confirm once; routes_summary.py; validate.py; reproduce.py; package.py. All code ran in the verified worker cgroup with two-thread limits. Frozen originals cannot be rerun in place.

Exact safe numerical replay:

```bash
bin/openlabs-resource-guard --task-type cpu -- env OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 MKL_NUM_THREADS=2 labs/biomed/.venv/bin/python labs/biomed/studies/promoter_portability_20261021/reproduce.py --output /home/biostar/work/openlabs-artifacts/artifact-stage/biomed/promoter-portability-20261021/replays/reproduction-2
```
