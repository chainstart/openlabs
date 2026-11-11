---
name: openlabs-physics-paper
description: OpenLabs physics manuscript entry skill for validated analytical, numerical, simulation or public-data results. It applies the shared openlabs-paper-writing workflow plus the physics evidence boundary below.
---

# OpenLabs physics paper

Follow the shared workflow in `../openlabs-paper-writing/SKILL.md`
(`workflows/paper/skills/openlabs-paper-writing/SKILL.md` in the code repository). Identifiers
and public file names: [paper-identifiers.md](../references/paper-identifiers.md). Venue,
review and author policy: `registry/settings.yaml`. This file adds only what differs for physics.

## Physics specifics

- Read [physics-evidence-boundary.md](references/physics-evidence-boundary.md). Components:
  `scientific-writing`; `sympy` (the profile's domain component) only for explicit symbolic
  checks; `peer-review` only as an assigned reviewer.
- Write the strongest paper the frozen evidence supports; do not run a fresh research campaign
  inside the writing task or present a partial result as an open-problem solution.
- For every central statement record its regime, assumptions, conventions, evidence type,
  artifact and limitation.
- Say explicitly whether a result is a new theorem, computation, constraint, conjecture, no-go
  result or reproduction, checked against current primary sources.
- Include equations, definitions, error controls and limiting checks needed to reproduce it.
