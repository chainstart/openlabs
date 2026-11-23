---
name: openlabs-medicine-paper
description: Write and review ECG protocol audits and physiological measurement studies.
---

# ECG and physiological measurement

State the measurement question, reference annotation, sampling frequency, leads, units and acquisition setting. Give record and unique patient denominators at every exclusion. Identify shared patients and derivative databases before claiming external validation. Keep waveforms local and send only aggregate evidence to external models. Use open, application-free data. Limit conclusions to measurement agreement or evaluation error.

Show the patient split and per-site label support, then paired effects with patient-cluster intervals and the prespecified practical difference band. For interval measurements show signed bias, limits of agreement and unmeasurable fractions by database and lead. Show missed beats separately from timing error among matched beats. Mark filters and resampling before comparing annotated boundaries.

For Physiological Measurement structure the abstract as Objective, Approach, Main results and Significance. Give the acquisition and error budget enough detail to reproduce the measurement. A second-stage methods paper for BSPC or CMPB needs an independent cohort, a fixed label mapping and uncertainty by database. Check the venue register and obtain human submission approval.

## Figures

Draw the acquisition and evaluation path (subject, leads and electrodes, recorder, annotation, split, model, metric) as an SVG/HTML schematic: start from `schematic-flow` or the `isolate-tracing` pattern and the biomedical library (ECG, heart and patient objects; Servier items need their CC BY credit). Put short waveform snippets in as matplotlib insets drawn from the records; agreement and error results stay matplotlib plots.

Figure routes: result plots in matplotlib; principle, mechanism and system schematics in SVG/HTML with library objects (`paper-writing figures assets WORDS --field biomedical`), connectors whose width carries the quantity and small data insets; TikZ only for formula-dense theory diagrams. Keep schematic text to names, numbers and units.
