# Broad–Sanger CRISPR replication-risk pilot

Question: can a small fixed model identify cross-laboratory measurement disagreement
on source-profiled genes and cell lines absent from target-label training, beyond
effect magnitude, gene variance, contrast and a linear learned risk baseline?

The data workspace owns the frozen plan, environment lock, source audit and state:
`/home/biostar/work/openlabs-data/workspaces/biology/projects/biomed-bio-shift-20261021/`.
Payloads and outputs belong in
`/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/bio-shift-20261021/`.

Only original separate CRISPRcleanR corrected matrices are used. No integrated or
quantile-normalized matrix is an independent validation source. Official historical
ZIPs are 230/339 MiB; bounded validated HTTP ranges retrieve only the 47/68 MiB
compressed processed members. Their raw compressed ranges, strong ETag, CRC-checked
extracted bytes and hashes are retained. No full-archive hash is claimed. A range
manifest supplements, and does not pretend to be, generic full-file dataset intake.
The original-author cell identity map uses the existing canonical intake tool.

Run from the repository root, always through the resource guard:

```bash
bin/openlabs-resource-guard --task-type cpu -- env OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 labs/biomed/.venv/bin/python labs/biomed/studies/bio_shift_20261021/run_pilot.py --root /home/biostar/work/openlabs-artifacts/artifact-stage/biomed/bio-shift-20261021 --project /home/biostar/work/openlabs-data/workspaces/biology/projects/biomed-bio-shift-20261021
```

Do not rerun after `test-evaluation.started`: the target-label holdout is once-only.
The software refuses a second test opening. Any new analysis after that point must
be marked exploratory and cannot recycle the test as confirmation.

The primary comparison is conditional pair-weighted MAE at 50% retention within a
source-defined informative subset, with two-axis gene/cell bootstrap intervals.
The source profiles of target-label-unseen identities are explicitly available.
Two laboratories cannot establish generalization to a new laboratory. Related
cell-line ancestry, historical screen protocols and unmodeled guide-level biases
remain limitations. A positive pilot is not a paper candidate or a publication claim.
