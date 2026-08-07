# OpenLabs paper workflow

This is the deterministic half of paper production: registry validation, evidence bundles,
manuscript inventory, review-record validation, exact median aggregation, quality gates, support
checks, and immutable package construction. Writing and scientific judgment stay in the three
OpenLabs paper Skills and their pinned vendored components.

By default, the workflow reads private state from `$OPENLABS_DATA`, or from
`$OPENLABS_WORKSPACE/openlabs-data`. Pass `--root` for an explicit paper repository. The migrated data layout
keeps `registry/`, `papers/`, and `reviews/` directly under that root.

```bash
PYTHONPATH=workflows/paper python3 -m paper_writing validate \
  --root "$OPENLABS_WORKSPACE/openlabs-data"
```

Remote handoff and Zenodo mutation adapters are retained for compatibility but disabled by
default. A separate administrator decision must set `OPENLABS_ENABLE_EXTERNAL_WRITES=1` for one
explicit operation. An internal `ready` quality gate never implies publication or submission.
