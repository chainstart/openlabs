---
name: ai-research-loop
description: Run evidence-bound AI/ML research from a precise hypothesis through benchmark design, leakage control, baselines, pilots, confirmatory runs, ablations, error analysis, and reproducibility audit. Use for autonomous OpenLabs AI experiments, continuation of AIRA campaigns, benchmark or model comparisons, negative-result analysis, and deciding whether an AI result is strong enough for a claim or paper candidate.
---

# AI Research Loop

Advance the assigned hypothesis with the smallest experiment that can change the decision.

1. State the population, task, intervention or method, comparator, metric, and falsifier.
2. Establish the dated literature and benchmark boundary. Separate novelty discovery from claim
   verification.
3. Freeze data splits, preprocessing, leakage checks, primary metrics, baselines, seeds, exclusions,
   and stopping rules before a confirmatory run.
4. Use a pilot only to debug feasibility and variance. Do not promote pilot-selected choices as a
   confirmatory result on the same holdout.
5. Compare against strong simple baselines and the closest relevant method under matched budgets.
6. Report effect sizes, uncertainty, multiplicity handling, per-seed outcomes, failures, and useful
   negative results. Do not reduce independent sample size to rows, frames, or repeated prompts.
7. Perform ablation, robustness, and error analysis targeted at the proposed mechanism rather than
   accumulating unrelated tables.
8. Reproduce the frozen run from its environment, code, input, seed, and command record before
   marking a claim supported.

Read [evidence-gates.md](references/evidence-gates.md) before a confirmatory run or promotion. Use
the migrated AIRA tools and audited statistical/EDA Skills when applicable. Persist reusable
experiment code only after it has worked in at least two campaigns; keep first-use scripts in the
campaign workspace.

Return hypotheses and failed routes as first-class results. A high benchmark number alone does not
establish novelty, mechanism, generality, or practical value.

## OpenLabs handoff

Keep mutable plans, task-private code, small metrics, and checkpoints in the task's declared
`$OPENLABS_WORKSPACE/openlabs-data/workspaces/ai/<campaign-id>/` directory. Put datasets, model weights,
large prediction tables, and checkpoints under
`$OPENLABS_WORKSPACE/openlabs-artifacts/experiments/<campaign-id>/`; refer to them by file URI and SHA-256.
The migrated AIRA registries and fixtures are read-only templates, not a second global scheduler.

Perform one bounded task, then atomically write `openlabs.result_bundle.v1` to the exact output
path. Do not write the factory SQLite database, reuse a holdout after adaptive selection, or infer
claim support from a successful process exit without the declared evaluation evidence.
