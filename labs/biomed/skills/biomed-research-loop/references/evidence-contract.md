# Pilot evidence contract

The executable contract is `protocols/public_data_pilot.py`. All recorded file paths are
relative to the project directory, confined after symlink resolution, with SHA-256 hashes.
The validator uses only the standard library so the control plane need not import ML code.

A project is `openlabs.project.v1`, domain `biology`, protocol
`{"id":"biomed-public-data-pilot","primary_skill":"biomed-research-loop"}`.
Each workstream points at an `openlabs.biomed_pilot_state.v1` state and starts paused.
State records `project_id`, `workstream_id`, `status`, `paper_candidate: false`,
`research_question`, `independent_unit`, `next_experiment`, `plan`, `environment`,
`datasets`, `evidence`, and `claims`.

Plan JSON has `stage: exploratory_pilot`, `independent_unit`, `primary_outcomes`,
`baselines`, `split_strategy`, `leakage_controls`, `stop_conditions`,
`confirmatory_holdout`, `max_trials` and `resource_budget` (CPU threads, memory MiB,
scratch MiB). These are prospective choices, not observed outcomes. The environment file
is the exact lock/export used by the task, not a list of unpinned packages.

Allowed state statuses: configured, running, completed, failed, needs_replan.
Claims remain hypothesis/provisional/refuted; observed claims require evidence.
Completed pilots additionally require at least one hash-bound public-data intake manifest,
a split audit bound to the actual sample CSV, and a results JSON record. The audit must
match the plan's `independent_unit`, `split_strategy` and `group_columns` exactly.
The results record has `stage: exploratory_pilot`, `independent_unit`, `metrics`
(nonempty finite numeric values), `baselines` (name to metric objects covering all planned
baselines), `trials_run`, `limitations` (nonempty list), and `run` (command, code revision,
seed and environment SHA-256). These records validate provenance and bookkeeping;
the validator cannot determine scientific validity, adequate power or actual novelty.

Each intake manifest identifies provider, release/accession, sample unit, source and final
URL, retrieval timestamp, exact terms URL and reuse basis, citation, upstream study IDs,
and a file URI/size/SHA-256 for a payload within its declared staging root. The manifest
itself is bound in state; the validator streams and hashes the payload for completed pilots.
Cross-source independence must be established using upstream experiments/donors, not URLs.

Sample CSV requires `sample_id`, `split` (train/validation/test), and the grouping columns
declared in the plan, e.g. `molecule_id`, `scaffold_id`, `donor_id`, `cell_line_id` or
`study_id`. Each grouping column must be disjoint across partitions. All three partitions
must be present. This is an overlap audit, not an automatic split generator or a check of
chemical standardization, chronology, statistical independence or feature leakage.
