---
name: openlabs-ai-paper
description: OpenLabs AI/ML manuscript entry skill. Invoke explicitly for AI or machine-learning papers in the OpenLabs data repository; it applies the shared openlabs-paper-writing workflow plus the AI/ML evidence notes below.
---

# OpenLabs AI/ML paper

Follow the shared workflow in `../openlabs-paper-writing/SKILL.md`
(`workflows/paper/skills/openlabs-paper-writing/SKILL.md` in the code repository). Identifiers
and public file names: [paper-identifiers.md](../references/paper-identifiers.md). Venue,
review and author policy: `registry/settings.yaml`. This file adds only what differs for AI/ML.

## AI/ML specifics

- Components: `ai-research-writing-skill` (story, drafting, citation, figures, build),
  `statistical-analysis` for quantitative claims, `peer-review` only as an assigned reviewer.
- Compare against the strongest matched baselines under the same data, compute and tuning
  budget; report variance over seeds, not a single best run.
- Separate held-out, external and temporal evaluation; check for test-set leakage and
  benchmark contamination before claiming generalization.
- Its scripts `fetch_template.py` and `verify_citations.py` use the network: run them only when
  needed, never send confidential manuscript text, and record source and access date.
- Generated images are illustrative only and cannot supply experimental evidence.
