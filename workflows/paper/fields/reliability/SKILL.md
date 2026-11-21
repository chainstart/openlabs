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
