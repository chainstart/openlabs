# Portfolio contract

The autonomous mathematics protocol fixes only the following infrastructure contract:

- work occurs in the staged campaign and is promoted atomically only after validation;
- CPU, memory, process, scratch, output, and wall-time ceilings protect the shared machine;
- result artifacts and executable dependency closures are hash-bound and replayable;
- reviewers start blank and never approve their own work;
- the project index records results without ranking or interpreting them;
- the derived index is rebuilt from succeeded, hash-consistent result archives after transient
  failures, and project-declared historical campaigns are eligible for the same mechanical import;
- review packets and cursors are hash-bound control-plane artifacts outside the promotable research
  tree; a failed candidate materialization is retried before its cursor advances;
- a reviewer-authored `candidate_branches` entry mechanically creates an independent continuous
  researcher workstream; it does not certify the idea;
- the project's candidate state template and maturation instruction, not the generic scheduler,
  define the branch envelope and publication aspiration;
- a candidate researcher's evidence-backed `paused` or `completed` state stops fallback reseeding;
- paper writing starts only after a matured researcher result explicitly becomes a paper candidate
  and passes independent readiness review.

Everything else is Codex-owned scientific judgment. Route names, phase names, calendars, target
counts, scoring formulas, and venue labels are descriptive context rather than admissibility gates.

Declared mathematics workstreams use `openlabs.math_research_workspace.v1`; dynamically spawned
candidate workstreams use the domain-neutral `openlabs.project_workstream.v1`. Required fields are only
`project_id`, `workstream_id`, `mode`, `status`, `research_log`, and `verification_receipts`.
Researchers may extend it freely. A receipt listed in `verification_receipts` is replayed by the
trusted protocol validator when it declares Lean or another registered mathematics runtime.
