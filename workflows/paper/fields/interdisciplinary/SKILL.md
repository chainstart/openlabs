---
name: openlabs-interdisciplinary-paper
description: Writing and reviewing cross-field papers of the open NC line (any field, free public data).
---

# Cross-field papers (open NC line)

NC angle (NC aim, 2026-11-25): one field-level general question answered with complete free public data at a scale or breadth beyond the largest prior study; the headline finding is a new phenomenon or mechanism, or a decision-relevant global quantity, stated in one declarative sentence that readers outside the field can use.

Use the shared paper-writing workflow. Write for Nature Communications readers across fields: the first paragraph names the question, why it matters beyond one subfield, what was unknown and the answer. Keep the topic, title and abstract fixed on that answer through every revision; answers to internal review go in the response letter, not as caveats in the text.

- State the population the claim covers (all countries, gauges, genomes, events ...), its denominator at every exclusion, the time span and the data version and access date. Separate measured outcomes from modelled or proxy quantities and give the measured-only result.
- Give the comparison that makes the finding non-trivial: the benchmark it is measured against (official forecast, policy parameter, largest prior study) and the null model that a simple statistical or algebraic effect would produce; report the effect beyond that null with uncertainty.
- For causal claims give the identification argument and the main threat; otherwise say association. Check dependence (spatial, temporal, shared sources), robustness to the main analytic choices and held-out or out-of-sample validation.
- In review, trace the headline number to the data and the code, and judge first the 2-3 points that decide desk rejection: significance, novelty against the closest NC/Nature/Science work, fit, and whether the main claim is clear. Minor points are advice.

Follow the field conventions of the discipline the question belongs to (units, standard indices, reporting guidelines such as STROBE for observational health data). Check author instructions and 2025 CAS evidence in `registry/verified-venues.yaml`; `registry/settings.yaml#journal_target_policy` governs eligibility, and the data grade the journal after the research (NC, else CAS Zone 1, 2).

## Figures

Figure 1 explains the question and the data: the population and its coverage (often a world map or a network), the measured outcome and the comparison or null. Then the main effect with uncertainty, its distribution across units, and the mechanism or decision implication. Supplement: every unit, alternative definitions and the sensitivity analyses.

Figure routes: result plots in matplotlib (maps with cartopy or geopandas when installed, else matplotlib); principle, mechanism and system schematics in SVG/HTML with library objects (`paper-writing figures assets WORDS` with the field of the question, e.g. `--field energy` or `--field biomedical`), connectors whose width carries the quantity and small data insets; TikZ only for formula-dense theory diagrams. Keep schematic text to names, numbers and units.

## Evidence plan before drawing

Read paper_writing/figure-standards.json. Choose manuscript_type from its profiles (for an unrepresented design use other with a substantive count_reason). For every figure list evidence_stages (profile stage IDs), panels (integer), and source and data_source. Supply count_reason for justified departures, single_panel_reason for a standalone result, and supplement_coverage mapping checks to appendix figure/table identifiers or explaining complete main-text coverage. The first main figure carries first_stage. Use actual study outputs for every result and anchor every schematic in a real measured example. Explain n, units, intervals and every visual encoding in captions.
