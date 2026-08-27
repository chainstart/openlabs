# Independent backtest checklist

| Family | Minimum question | Fail-closed condition |
|---|---|---|
| Time | Was every field knowable before the decision and fill? | Timestamp, release lag or vintage cannot be reconstructed |
| Universe | Are entry, exit and delisting histories point-in-time? | Current constituents are projected backward |
| Search | Is every trial and selected family visible? | Holdout reuse or material undocumented search |
| Statistics | Are dependence, selection and multiple tests handled? | Nominal p-values are reported after adaptive selection |
| Execution | Are costs, lag, liquidity, funding and borrow credible? | Net result depends on impossible same-bar fills or omitted material cost |
| Baselines | Are simple and closest methods matched? | Baseline has less information, tuning or risk budget |
| Exposure | Is return distinguishable from known beta/factor/regime exposure? | Central novelty is a relabeled known exposure |
| Reproduction | Can frozen inputs regenerate claim-bearing results? | Missing input, code, environment, command or hash |
| Claim | Does wording stay within markets, dates and capacity tested? | Universal or causal wording exceeds the design |
