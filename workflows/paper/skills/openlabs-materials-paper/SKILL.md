---
name: openlabs-materials-paper
description: Run OpenLabs' evidence-bound computational materials manuscript workflow from validated structures, simulations, convergence studies, reference calculations, and experimental context through claim mapping, drafting, skeptical review, and the internal quality gate. Use for materials-science paper readiness audits, manuscript creation or revision, and journal adaptation; never promote unconverged or model-only evidence into a physical claim, and never publish or submit implicitly.
---

# OpenLabs materials paper

Use this as a thin coordinator over the private paper registry and the migrated matfactory evidence.
Resolve `paper_root` from `OPENLABS_DATA` or `$OPENLABS_WORKSPACE/openlabs-data`, and read the selected paper
record, its claim–evidence map, the materials result bundles, and the current target-journal policy.

## Load the bounded components

- Read `workflows/paper/skills/vendor/scientific-writing/SKILL.md` for evidence-bound drafting.
- Read `workflows/paper/skills/vendor/statistical-analysis/SKILL.md` when quantitative inference,
  uncertainty, exclusions, hierarchical sampling, or multiplicity is in scope.
- Read `workflows/paper/skills/vendor/peer-review/SKILL.md` and use
  `$openlabs-paper-review` for the frozen three-reviewer panel.

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
support checks. Give the unchanged snapshot to exactly three independent reviewer contexts using
the `materials` rubric and the `leading_materials_journals` plus `cas_zone_1_journal` simulated
views. Apply exact median aggregation; any score-bearing edit makes the panel stale.

A passing gate changes only internal state to `ready`. It never authorizes Zenodo, remote handoff,
submission, journal communication, or public release. Report remaining physical-model,
convergence, sampling, literature, and reproducibility risks even when the manuscript passes.
