# OpenLabs AI laboratory

This directory contains the stable AI/ML research tools migrated from AIRA and the
OpenLabs-facing research Skill. Runtime experiments belong in
`$OPENLABS_WORKSPACE/openlabs-data/workspaces/ai`; large datasets, checkpoints, and result objects belong in
the sibling `openlabs-artifacts` repository.

The public boundary is `lab.json` plus `openlabs.task.v3` and
`openlabs.result_bundle.v1`. The retained `aira` package is a compatibility toolset for experiment
bundles, registries, local benchmarks, production plans, evaluation, and experiment memory. It does
not own global scheduling or write the OpenLabs SQLite database.

Run its tests from this directory:

```bash
../../bin/openlabs-resource-guard -- python3 -m pytest -q
```

The original project overview is retained as `README.legacy.md` for provenance.

Exploratory projects can bind to the `ai-research-pilot` protocol with primary
skill `ai-research-loop`. Its validator checks project/workstream identity,
relative paths, plan and environment hashes, and evidence hashes. Completed
pilots require evidence; pilot claims remain hypotheses, provisional observations,
or refuted hypotheses, and `paper_candidate` must be false. Passing this validator
does not establish scientific validity, novelty, independent replication, or
publication readiness. Both discovery and commit modes check the hashes.

Use project-local scripts for new experiments. Record the unit of analysis,
controls, budgets, stopping rules, environment and untouched holdout boundary
before running. Keep bulk trajectories and model files in `openlabs-artifacts`;
store small summaries and hash manifests in the data project. A manually executed
bounded pilot should use `startup: paused` to prevent duplicate scheduler runs.
Starting an autonomous workstream is a separate execution setting; merely creating
a project configuration does not mean a background researcher is running.
