# AI/ML evidence gates

## Before execution

- Identify train, validation, and untouched test boundaries.
- Record dataset and model versions, licenses, hashes, preprocessing, seeds, and compute budget.
- Predeclare the primary comparison, metric, uncertainty method, and kill condition.
- Check benchmark contamination, label leakage, duplicate entities, and tuning on the test set.

## Before a supported claim

- Complete all declared seeds or justify a design-appropriate sequential rule fixed in advance.
- Report every planned run, including crashes and unfavorable outcomes.
- Pair aggregate metrics with uncertainty and practically interpretable effect sizes.
- Test the closest alternative explanation with a targeted ablation or control.
- Reproduce from a clean or independently reconstructed environment.

## Before a paper candidate

- Verify the literature position and closest prior work from primary sources.
- Demonstrate that the contribution survives a strong baseline and a meaningful robustness check.
- Freeze a claim-evidence map that excludes unsupported generalization and causal language.
