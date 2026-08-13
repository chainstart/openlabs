# Transfer of Anthropic's 2026 zeta-function research method

## What the reported result was

Anthropic reported an unconditional improvement in the proportion of nontrivial Riemann-zeta
zeros on the critical line, from the prior 41.6% lower bound to an optimized 67.25% bound. It was a
paper-scale intermediate theorem, not a proof of the Riemann hypothesis. The proof combines
unconditional pair-correlation input with a Weil-form function space and an indefinite
positive/negative-index argument. The core linear-algebra step bounds rank through first- and
second-moment trace information.

Primary records:

- [Anthropic research report](https://www.anthropic.com/research/riemann-zeta)
- [Technical paper](https://www-cdn.anthropic.com/564f962e60643842f5fcb4a17c9dbc8f608f1c37.pdf)
- [Research-process appendix](https://www-cdn.anthropic.com/d7f3ecf1d01392d887f8bc974ca187e2a121b1ed.pdf)
- [Detailed transcripts](https://www-cdn.anthropic.com/8a0d1add3c637b858a9a181e98c40e9548c3f44f.pdf)
- [Sorry-free Lean formalization](https://github.com/anthropics/zeta-23-lean)

## The productive process

The process appendix describes a coordinator working from durable research memos and delegating
isolated, written briefs. Earlier exploration produced a survivor ledger; the successful run then
used a bounded portfolio with separate idea, validation, literature, and writing roles. Explicit
false-world controls included zeta-like functions with known off-line zeros, so a formally elegant
argument that accidentally proved too much could be killed early.

The first breakthrough came from inversion, not persistence with the requested route. An agent
asked to upper-bound a negative index found that route empty and instead lower-bounded a positive
index. The coordinator immediately switched from exploration to three blind hostile reviews. Those
reviews found a mass-matrix gap; an independent derivation and a fourth reviewer repaired it. A
later improvement isolated only two quantitative levers. Numerical experiments killed one; the
other produced the rank-trace inequality. The resulting paper then received cold review,
literature checks, external expert examination, numerical adversarial tests, and Lean
formalization.

The operational lesson is not “launch many agents.” It is:

1. aim at a precise, publishable intermediate theorem with known unconditional inputs;
2. use diverse isolated mechanisms and explicit controls during discovery;
3. let a failed brief invert when it reveals a different provable invariant;
4. stop discovery immediately when a theorem candidate appears;
5. send the claim to disjoint hostile reviewers and an independent re-deriver;
6. repair or terminate on the exact defect, never resume undirected branching;
7. verify novelty, numerics, analytic dependencies, and formal proof separately.

## OpenLabs transfer

The productive ideas transfer as a Codex-owned research pattern, not as a deterministic scheduler
or mandatory stage machine. A researcher may use, reorder, merge, repeat, or abandon these modes as
the mathematics requires:

| Stage | Required durable object | Gate |
|---|---|---|
| Discovery | research memo, false-world controls, isolated mechanism reports, survivor ledger | Codex decides what remains worth pursuing |
| Synthesis | exact intermediate theorem, scope, comparator, dependency graph, consequence | a theorem-shaped candidate exists |
| Hostile validation | blind reproof, hypothesis audit, counterexample search, numerical adversarial tests | independent reviewers identify exact defects |
| Certification | live literature check, formalization where feasible, paper-shadow assessment | Codex reviewer gives a supported verdict |

The scheduler may execute epistemically independent roles separately, but role count and token
volume are not progress. Resource ceilings still prevent runaway jobs. It is the researcher or
reviewer—not a node counter, score, or outer script—who decides whether a killed mechanism should be
inverted, a target should freeze, an exact defect should be repaired, or a different route should
open. A promising result should receive blank-session hostile review without stopping unrelated
free exploration.

This method is transferable to OpenLabs at the workflow level. The specific 67.25% mathematics is
transferable only to lanes whose objects admit the same pair-correlation, indefinite-form, and
rank-trace interfaces. For other RH routes, transfer the experimental controls, role separation,
and theorem-target discipline—not the surface algebra.
