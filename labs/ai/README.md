# OpenLabs AI laboratory

This directory contains the stable AI/ML research tools migrated from AIRA and the
OpenLabs-facing research Skill. Runtime experiments belong in
`$OPENLABS_WORKSPACE/openlabs-data/workspaces/ai`; large datasets, checkpoints, and result objects belong in
the sibling `openlabs-artifacts` repository.

The public boundary is `lab.json` plus `openlabs.task.v2` and
`openlabs.result_bundle.v1`. The retained `aira` package is a compatibility toolset for experiment
bundles, registries, local benchmarks, production plans, evaluation, and experiment memory. It does
not own global scheduling or write the OpenLabs SQLite database.

Run its tests from this directory:

```bash
python3 -m pytest -q
```

The original project overview is retained as `README.legacy.md` for provenance.
