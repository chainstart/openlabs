---
name: openlabs-energy-paper
description: Writing and reviewing energy systems and electricity-market economics papers.
---

# Energy systems and economics papers

NC angle (NC aim, 2026-11-25): benchmark against the operator's own forecast or plan (N2, N6), multi-market scale and a policy parameter (N7); one sentence that overturns a planning assumption.

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
- `pv-storage-grid` (HTML) — PV, battery, meter and grid as library objects, power flows sized in MW, price/control path and a one-day inset from data.

Figure routes: result plots in matplotlib; principle, mechanism and system schematics in SVG/HTML with library objects (`paper-writing figures assets WORDS --field energy`), connectors whose width carries the quantity and small data insets; TikZ only for formula-dense theory diagrams. Keep schematic text to names, numbers and units.

## Evidence plan before drawing

Read paper_writing/figure-standards.json. Choose manuscript_type from its profiles (for an unrepresented design use other with a substantive count_reason). Keep the existing paper_type. For every figure list evidence_stages (profile stage IDs), panels (integer), and source and data_source. Supply count_reason for justified departures, single_panel_reason for a standalone result, and supplement_coverage mapping checks to appendix figure/table identifiers or explaining complete main-text coverage. The first main figure carries first_stage. Plan evidence before drawing. Use actual study outputs for every result and anchor every schematic in a real measured example or comparison. Explain n, units, intervals and every visual encoding in captions. Compare axes, ordering and color limits at final column width.

- market_dispatch (4–6): boundary, operation, aggregate, mechanism. Figure 1: asset, meter, allowed charging sources and export constraint. Supplement: all site-years, efficiency, prices and rolling replay.

- policy_distribution (5–8): denominator, counterfactual, effect, distribution, mechanism. Figure 1: exposure, population denominator or policy contrast. Supplement: regions, alternative scenarios and extremes.
