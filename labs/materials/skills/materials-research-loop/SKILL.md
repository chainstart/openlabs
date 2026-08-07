---
name: materials-research-loop
description: Run auditable computational materials research from literature and structure provenance through falsifiable mechanism design, ML-potential or first-principles simulation, numerical convergence, uncertainty analysis, independent reference validation, and claim promotion. Use for OpenLabs materials campaigns, matfactory continuation, atomistic simulation planning, transport or mechanism studies, and deciding whether simulation evidence can support a paper claim.
---

# Materials Research Loop

Advance one physical question, not merely another simulation.

1. State the composition, phase, structure, thermodynamic conditions, observable, comparator,
   proposed mechanism, and result that would falsify it.
2. Resolve structure, literature, experimental benchmark, potential, pseudopotential, and software
   provenance before expensive computation.
3. Start with the cheapest calculation that can kill the route. Escalate from analytic checks and
   small cells to pilots, convergence studies, production runs, and independent references only
   after each gate passes.
4. Freeze numerical settings, cell construction, ensembles, equilibration, trajectory length,
   estimators, uncertainty, exclusions, and stopping rules before production.
5. Treat configurations and independent preparations—not timesteps or trajectory frames—as the
   statistical units unless the estimand justifies another design.
6. Validate universal or learned potentials against an appropriate independent first-principles or
   experimental reference. Agreement with experiment alone may be error cancellation.
7. Distinguish association, mechanistic consistency, and causal elementary mechanism. Preserve
   phase instability, non-convergence, null association, and model-domain failure as results.
8. Bind every claim to code, inputs, environment, hashes, convergence evidence, and limitations.

Read [simulation-gates.md](references/simulation-gates.md) before production or promotion. Reuse
the migrated matfactory scientific tools, but let OpenLabs own global leases, retries, and campaign
state. Keep task-specific scripts in the campaign until reuse justifies promotion.

## Keep runtime state out of code

Treat every versioned matfactory protocol under `labs/materials` as a template. Before execution,
copy the selected protocol into the task's declared campaign directory and replace every writable
`root_dir`, output, cache, lock, checkpoint, and report path with an absolute path under:

- `$OPENLABS_WORKSPACE/openlabs-data/workspaces/materials/<campaign-id>/` for small state, protocols,
  summaries, and task-private code;
- `$OPENLABS_WORKSPACE/openlabs-artifacts/experiments/<campaign-id>/` for trajectories, wavefunctions,
  checkpoints, model payloads, and other large products.

Absolute input paths may point to immutable fixtures in `labs/materials`, but no new `runs/`,
`cache/`, lock, or output tree may be created there. Matfactory accepts absolute paths, so do not
run a repository-relative legacy protocol unchanged. Bind any reused legacy artifact by URI and
SHA-256; supervisor state alone is not evidence that the referenced calculation exists.

Finish one bounded OpenLabs task by writing the required `openlabs.result_bundle.v1` to the exact
task output path. Never write SQLite, silently enable a disabled GPU/DFT stage, or treat a completed
workflow stage as a scientific claim.
