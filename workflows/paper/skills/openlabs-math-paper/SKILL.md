---
name: openlabs-math-paper
description: OpenLabs mathematics manuscript entry skill. Invoke explicitly for mathematics papers in the OpenLabs data repository; it applies the shared openlabs-paper-writing workflow plus the proof boundary below. Never treat prose review or computation as proof.
---

# OpenLabs mathematics paper

Follow the shared workflow in `../openlabs-paper-writing/SKILL.md`
(`workflows/paper/skills/openlabs-paper-writing/SKILL.md` in the code repository). Identifiers
and public file names: [paper-identifiers.md](../references/paper-identifiers.md). Venue,
review and author policy: `registry/settings.yaml`. This file adds only what differs for
mathematics.

## Mathematics specifics

- Components: `scientific-writing`; `sympy` only for an exactly encoded identity, recurrence,
  reduction, boundary case or finite certificate; `peer-review` only as an assigned reviewer.
- No writing, review or symbolic tool verifies a proof. For each central theorem record
  definitions, quantifiers, hypotheses, lemma dependencies and the exact evidence in the
  claim–evidence map; inspect degenerate and boundary cases, hidden assumptions and cycles.
- Distinguish self-contained prose proof, author-reported computation, independently replayed
  computation and formal proof; never promote one to another. A SymPy simplification checks only
  the encoded statement. Weaken or block a claim until an open specialist question is resolved.
- Lean: one resource-capped audit per frozen snapshot (`$openlabs-paper-review` scripts), its
  receipt shared with every reviewer; reuse a PASS receipt when Lean inputs are unchanged
  (`settings.yaml#lean_audit_policy`); never ask each reviewer to rebuild.
- After `support-check`, `scripts/audit_support_materials.py` is an extra path-level lint; pass
  the exact current ZIP (and `--relative-base` when the prose uses a sub-directory base).
- Figures never encode distinct mathematical roles by colour alone; add a redundant cue, state
  the mapping in the caption and check the PDF in grayscale.
