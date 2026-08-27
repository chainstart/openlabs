---
name: quant-backtest-audit
description: Independently audit a quantitative-finance result for time leakage, revised data, survivorship, search multiplicity, weak baselines, unrealistic execution, hidden exposure, capacity limits, reproducibility, and claim inflation. Use before promoting an OpenLabs factor or strategy result, after a surprising backtest, or when reviewing evidence for a quantitative-finance paper.
---

# Quant Backtest Audit

Approach the supplied result as an independent adversarial reviewer. Do not optimize it.

1. Reconstruct the information timeline from raw timestamps through feature availability, order time and
   fill time. Fail the result if any future or revised information crosses that boundary.
2. Trace the historical universe, delistings, corporate actions and exclusions. Quantify selection and
   survivorship effects rather than accepting a current-universe backfill.
3. Recover the full search family from the trial ledger. Treat an unlogged search, reused holdout or
   post-outcome stopping rule as an unresolved blocker.
4. Recalculate net results with credible fees, spread, slippage, funding/borrow, execution lag, turnover,
   leverage, liquidity and capacity assumptions. Stress the assumptions that can reverse the claim.
5. Compare matched baselines and inspect common factor, sector, beta, volatility, liquidity and regime
   exposures. A disguised known exposure is not a novel mechanism.
6. Reproduce claim-bearing outputs from immutable inputs and verify hashes. Record every discrepancy.
7. Return PASS, FAIL or INCONCLUSIVE for each checklist family, with bounded remediation. Do not silently
   edit the researcher's evidence or inspect prior reviewer conclusions.

Read [backtest-checklist.md](references/backtest-checklist.md). Emit an audit artifact that can be bound
to the result bundle. This Skill has no authority to submit orders or claim profitability outside the
tested sample and assumptions.
