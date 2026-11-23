---
name: openlabs-reliability-paper
description: Writing and reviewing reliability engineering and prognostics and health management papers.
---

# Reliability engineering and PHM papers

Use the shared paper-writing workflow. Specify the equipment, sensing, failure modes, operating conditions and maintenance or monitoring decision the result can inform.

- Define runs, machines and acquisition groups before windowing vibration traces. Report sampling, channel, windowing and normalization. Split by the physical unit relevant to generalization and keep evaluation units out of feature selection, tuning and calibration.
- Separate recorded speed, load or sensor shifts from injected noise. Compare paired changes from the same fitted models and held-out units under both challenges. State class weighting, group-level uncertainty and rank stability. For prognostics, state failure/censoring definitions, prediction horizon and asymmetric decision costs.
- In review, trace any claimed robustness or transfer to the actual test conditions. Check equal tuning budgets, a credible conventional baseline, and whether a ranking by retention changes the engineering decision once shifted absolute scores are shown.

RESS emphasizes decision consequences and reliability assumptions. MSSP emphasizes signal-processing validity and acquisition details. EAAI emphasizes an engineering use case and credible generalization. Check author instructions and 2025 CAS evidence in `registry/verified-venues.yaml`; `registry/settings.yaml#journal_target_policy` governs eligibility.

## 本学科常用图型与要求

Assign specimens before windowing and show unit counts in train, tuning and holdout sets. Distinguish observed and forecast time, failure and censoring, and report RUL from the prediction origin. Show rank agreement by rig with the resampling unit, interval and prespecified decision thresholds.

- `specimen-split` — Assign physical specimens before segmenting time series.
- `degradation-rul` — Trace a predictive RUL interval to a registered failure threshold.
- `rank-agreement` — Show per-rig rank agreement and paired bootstrap uncertainty from inputs/ranks.csv.
- `bearing-testbed` (HTML) — rig objects (motor, test bearing, load, sensors, DAQ), sensor and data paths, and health-indicator/RUL insets from data.

Figure routes: result plots in matplotlib; principle, mechanism and system schematics in SVG/HTML with library objects (`paper-writing figures assets WORDS --field reliability`), connectors whose width carries the quantity and small data insets; TikZ only for formula-dense theory diagrams. Keep schematic text to names, numbers and units.

For `rank-agreement` supply `inputs/ranks.csv` with scenario, rig, rho, lower and upper columns. Replace the registered cutoffs, group labels and interval definitions with those of the current protocol.

## Evidence plan before drawing

Read paper_writing/figure-standards.json. Choose manuscript_type from its profiles (for an unrepresented design use other with a substantive count_reason). Keep the existing paper_type. For every figure list evidence_stages (profile stage IDs), panels (integer), and source and data_source. Supply count_reason for justified departures, single_panel_reason for a standalone result, and supplement_coverage mapping checks to appendix figure/table identifiers or explaining complete main-text coverage. The first main figure carries first_stage. Plan evidence before drawing. Use actual study outputs for every result and anchor every schematic in a real measured example or comparison. Explain n, units, intervals and every visual encoding in captions. Compare axes, ordering and color limits at final column width.

- rank_audit (3–6): protocol, split, individual, aggregate, reversal. Figure 1: units, held-out split, challenge, reference and score. Supplement: full model-by-challenge matrix, perturbations, resampling units and failures.

- rul_degradation (9–27): observation, indicator, endpoint, error, failure. Figure 1: fault location, observation process or model inputs and outputs. Supplement: all specimen trajectories, sensitivity and cross-condition tests.
