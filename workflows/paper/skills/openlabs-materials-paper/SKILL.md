---
name: openlabs-materials-paper
description: Run OpenLabs' evidence-bound computational materials manuscript workflow from validated structures, simulations, convergence studies, reference calculations, and experimental context through claim mapping, drafting, skeptical review, the internal quality gate, and controlled supporting-material release. Use for materials-science paper readiness audits, manuscript creation or revision, and journal adaptation; never promote unconverged or model-only evidence into a physical claim or create parallel release state.
---

# OpenLabs materials paper

Use this as a thin coordinator over the private paper registry and the migrated matfactory evidence.
Resolve `paper_root` from `OPENLABS_DATA` or `$OPENLABS_WORKSPACE/openlabs-data`, and read the selected paper
record, its claim–evidence map, the materials result bundles, and the current target-journal policy.
Read `workflows/paper/skills/overlays/quality-gate.md`; when support publication is required, also
read `docs/ZENODO_GUIDE.md`. When creating a workspace or naming a reader-facing file, read
[paper-identifiers.md](../references/paper-identifiers.md).

## Load the bounded components

- Read `workflows/paper/skills/vendor/scientific-writing/SKILL.md` for evidence-bound drafting.
- Read `workflows/paper/skills/vendor/statistical-analysis/SKILL.md` when quantitative inference,
  uncertainty, exclusions, hierarchical sampling, or multiplicity is in scope.
- Read `workflows/paper/skills/vendor/peer-review/SKILL.md` only when the assigned role is
  `reviewer`; a factory `writer` leaves the frozen dual-provider panel to the later
  `$openlabs-paper-review` task.

Do not activate additional writing systems or create a second registry.

## Enforce the materials evidence boundary

1. Map every claimed composition, phase, structure, preparation, temperature/pressure, observable,
   comparator, and mechanism to a hash-bound artifact.
2. Separate pilot, converged production, sensitivity, independent first-principles reference, and
   experimental evidence. A universal or learned potential is not its own independent validator.
3. Treat trajectories or frames from one preparation as correlated observations unless the
   estimand establishes otherwise. Report the true independent unit, uncertainty and exclusions.
4. Preserve non-convergence, instability, unresolved transport, null association, out-of-domain
   behavior, and disagreement with reference calculations.
5. Use “causal mechanism” only when the design identifies it; otherwise write association or
   mechanistic consistency. Agreement with experiment alone may reflect error cancellation.
6. Check numerical convergence, finite-size/time/ensemble sensitivity, model and pseudopotential
   provenance, seeds, environment, code, and stopping rules before strengthening a claim.

## Draft, review, and stop

Revise the canonical LaTeX only after updating the claim–evidence map. Verify each citation against
the actual proposition used, compile the frozen manuscript, and run deterministic repository and
support and style checks, including the single final truthful AI-use declaration required by the
shared overlay. In a factory `writer` task, stop at the frozen `paper_candidate`; do not run or
impersonate either reviewer. The scheduler gives it to a fresh `$openlabs-paper-review` task, whose
independent Codex and blind Packy Claude Opus 5 reviewers use the `materials` rubric and the
`leading_materials_journals` plus `cas_zone_1_journal` simulated views. A `paper_revision` applies
only the declared request; requests for new physical evidence go through a fresh
`evidence_remediation` task before returning to the same writer. Every revised candidate receives a
new panel because any score-bearing edit makes the old panel stale.

After a passing gate, run `paper-writing zenodo release` for an exact prepared support draft without
asking again; the gate authorizes only that hash-bound release. It never authorizes remote handoff,
submission, journal communication, spending, or a publication fact. Report remaining physical-model,
convergence, sampling, literature, and reproducibility risks even when the manuscript passes.
