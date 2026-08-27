---
name: openlabs-physics-paper
description: Write or revise an evidence-bound OpenLabs physics manuscript from validated analytical, numerical, simulation, or public-data results, with explicit regimes and conventions, current literature positioning, reproducible claim support, deterministic style checks, and independent leading-journal review. Use for physics paper creation and revision after a research result has passed its domain evidence and paper-readiness gates.
---

# OpenLabs physics paper

Write the strongest manuscript the frozen evidence supports. Do not perform a fresh research
campaign inside the writing task, inflate a partial result into an open-problem solution, or treat
AI text as evidence.

1. Read the paper registry record, frozen research result, independent readiness audit, and
   [physics-evidence-boundary.md](references/physics-evidence-boundary.md).
2. Invoke `$scientific-writing` for manuscript structure, source verification, citation practice,
   and LaTeX. Invoke `$statistical-analysis` only when the result contains empirical inference or
   uncertainty estimates. `$peer-review` belongs to the independent reviewer, not the writer.
3. Build the claim–evidence map before drafting. For every central statement record its exact
   regime, assumptions, conventions, evidence type, immutable artifact, and limitation.
4. Verify the closest-work boundary from current primary sources. Distinguish a new theorem,
   computation, constraint, conjecture, no-go result, and reproduction explicitly.
5. Make the source tree canonical and reproducible. Include equations, definitions, error controls,
   limiting checks, data provenance, and enough method detail to reproduce every claimed result.
6. Run `python -m paper_writing support-check`, `python -m paper_writing style-check`, the LaTeX
   build, unresolved-marker checks, and any artifact replay before freezing the manuscript.
7. Hand the immutable manuscript and declared evidence to `$openlabs-paper-review`. The writer may
   answer a `text_revision` request but may not score or approve the manuscript.

Publication-level completion requires a current novelty audit, no unsupported central claim, a
fresh dual-provider review, conservative scores of at least soundness 8, novelty 7, significance 7,
and overall 7, a positive CAS major-category Zone 1 view, and no scientific blocker. A named
journal's classification and scope must be verified at review time; do not infer them from a stale
list. Internal readiness never authorizes submission, spending, authorship changes, or public
release.
