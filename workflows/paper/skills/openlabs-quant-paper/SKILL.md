---
name: openlabs-quant-paper
description: Run OpenLabs' evidence-bound quantitative-finance manuscript workflow from registered trials, point-in-time data, cost-aware backtests, robustness and independent audit through claim mapping, drafting, skeptical review, and the local quality gate. Use for Quant Lab paper candidates and revisions; never turn an adaptive search or simulated return into an unsupported financial claim, and never publish, submit, or trade implicitly.
---

# OpenLabs quantitative-finance paper

Use this as a thin coordinator over the private paper registry and Quant Lab evidence. Resolve the
paper root from `OPENLABS_DATA` or `$OPENLABS_WORKSPACE/openlabs-data`, then read the selected paper
record, claim–evidence map, trial ledger, point-in-time data manifests, canonical backtest receipts,
independent audit, and current target-journal policy.

## Load the bounded components

- Read `workflows/paper/skills/vendor/scientific-writing/SKILL.md` for evidence-bound drafting.
- Read `workflows/paper/skills/vendor/statistical-analysis/SKILL.md` for dependence, uncertainty,
  multiple testing, effect sizes and robustness.
- Read `workflows/paper/skills/vendor/peer-review/SKILL.md` only for an assigned `reviewer` role;
  a factory `writer` leaves the frozen dual-provider panel to `$openlabs-paper-review`.

Do not activate another writing system or create a second registry.

## Enforce the finance evidence boundary

1. Map every claimed market, universe, date, predictor availability time, rebalance rule, holding
   period, execution assumption, comparator and estimand to hash-bound evidence.
2. Recover the complete registered search family, including failed and null trials. A selected pilot,
   repeatedly exposed holdout or nominal p-value after adaptive search is not confirmation.
3. Verify data vintage, revisions, entry/exit, delistings, corporate actions, calendars and missingness.
   Final revised macro data and current constituents cannot silently stand in for historical information.
4. Report gross and net results, costs, lag, turnover, liquidity/capacity, funding/borrow, leverage,
   drawdown, exposure, uncertainty and multiplicity at the level needed by the claim.
5. Compare strong simple baselines and closest published methods under matched information and risk
   budgets. Separate a new mechanism from a relabeled known exposure or a model swap.
6. Preserve negative regimes, failures, instability and unresolved external validity. A backtest is
   conditional historical evidence, not a promise of future profit or investment advice.

## Draft, review, and stop

Update the canonical claim–evidence map before strengthening prose, then compile the actual LaTeX and
run deterministic checks. In a factory `writer` task, stop at a frozen `paper_candidate`; do not
impersonate either reviewer. The scheduler gives it to a fresh `$openlabs-paper-review` task whose
independent Codex and blind Packy Claude Opus 5 reviewers apply the `quant_finance` rubric and the
`leading_quant_finance_journals` plus `cas_zone_1_journal` simulated views.

A `paper_revision` applies only the declared request. Missing data, backtests, statistical analysis or
independent replication returns through `evidence_remediation`, after which the revised candidate gets
a new panel. A passing gate changes only internal state to `ready`; it never authorizes Zenodo,
submission, journal contact, real-money trading or a claim of acceptance.
