---
name: openlabs-energy-paper
description: Writing and reviewing energy systems and electricity-market economics papers.
---

# Energy systems and economics papers

Use the shared paper-writing workflow. State the market rule or operational constraint, who is affected, the counterfactual and the size and uncertainty of the effect.

- Document operator data, settlement interval, local time conventions, currency/year and energy and power units. Link prices, dispatch and metering by interval. Distinguish measured generation, reconstructed curtailment and modeled availability, with coverage and a measured-only sensitivity.
- Compare storage and policy scenarios using matched information, asset limits and times. Disclose perfect foresight and the deployable comparison, state-of-charge boundary, efficiency, power/export limits, degradation and which costs and revenue streams enter the margin.
- In review, trace the primary endpoint to paired site-years or aligned time blocks. Check dependence, held-out validation, materiality, price spikes and regulation or regime changes. Require an identification argument for causal policy claims.

Energy Policy readers need a concrete institutional implication and its jurisdictional limits. Applied Energy readers need an auditable operational model and system implications. Energy Economics readers need a clear estimand, identification assumptions and inference. Check author instructions and 2025 CAS evidence in `registry/verified-venues.yaml`; `registry/settings.yaml#journal_target_policy` governs eligibility.

## 本学科常用图型与要求

Balance AC flows at the shared meter. Separate power (MW) from stored energy (MWh), specify the interval, efficiency and initial charge, and apply both pricing rules to identical dispatch. For policy contrasts identify paired sites, common periods, uncertainty and the comparison group.

- `shared-export` — Size shared export and compare storage with PV-only dispatch.
- `settlement-clock` — Price the same dispatch on two settlement clocks.
- `policy-periods` — Explain a matched policy-period contrast with contemporaneous comparison sites.
