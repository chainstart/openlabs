---
name: quant-research-loop
description: Run auditable quantitative-finance research from a dated literature boundary and economic mechanism through point-in-time data, registered trials, leakage-safe pilots, cost-aware confirmation, robustness, independent replication, and paper-claim promotion. Use for OpenLabs factor, trading-strategy, portfolio, risk, market-microstructure, or financial time-series campaigns and for deciding whether a backtest supports a publishable claim.
---

# Quant Research Loop

Advance one falsifiable financial hypothesis, not merely the best curve in a search.

1. State the market, universe, information set, rebalance time, holding period, proposed mechanism,
   comparator, estimand, capacity boundary and a result that would kill the route.
2. Establish the dated closest-work boundary and distinguish a new economic or statistical idea from
   applying another model to familiar data.
3. Freeze a point-in-time data manifest. Record revisions, delistings, corporate actions, asset entry
   and exit, timestamps, time zones, calendars, missingness and every transformation.
4. Register every attempted hypothesis and parameter family before reading its outcome. Pilots may
   debug and estimate variance; they cannot become confirmation after selecting on the same holdout.
5. Start with strong simple baselines and the closest published method under matched information,
   turnover, leverage, risk and compute budgets.
6. Include execution delay, fees, spread/slippage, turnover, borrow/funding and capacity assumptions
   appropriate to the claim. Use event-driven confirmation when vectorized execution assumptions can
   change the conclusion.
7. Report gross and net effects, uncertainty, drawdown, exposure, stability, multiple-testing control,
   regime and subperiod results, failures, and economically meaningful effect sizes.
8. Test the mechanism with targeted falsification and independent replication. A high Sharpe ratio,
   IC or backtest return alone is not novelty and is not a paper.

Read [evidence-gates.md](references/evidence-gates.md) before a confirmatory run or claim promotion.
Invoke `quant-backtest-audit` in a fresh context before promoting an execution-sensitive result.

## OpenLabs handoff

Keep mutable plans, trial ledgers, data manifests, small metrics and campaign code under
`$OPENLABS_WORKSPACE/openlabs-data/workspaces/quant/<campaign-id>/`. Put downloaded datasets, feature
panels, fitted models, predictions and large backtest outputs under
`$OPENLABS_WORKSPACE/openlabs-artifacts/experiments/<campaign-id>/`. Refer to every artifact by URI and
SHA-256; do not copy credentials or licensed raw data into the code repository.

Finish one bounded task by atomically writing the required `openlabs.result_bundle.v1` to the exact
task output path. Preserve null and negative trials. Never trade, connect a brokerage account, reuse
a consumed confirmation holdout, or promote an adaptive search result without its full search family.
