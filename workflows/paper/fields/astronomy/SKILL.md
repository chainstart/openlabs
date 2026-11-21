---
name: openlabs-astronomy-paper
description: Writing and reviewing astronomy papers on survey photometry and eclipsing binaries.
---

# Astronomy papers

Use the shared paper-writing workflow. Start with the observable result: which systems and sectors support the inference, and how large are the statistical and product-dependent uncertainties?

- Identify targets by catalogue ID. Give TESS sectors, cadence, product (SAP, PDCSAP or extracted light curve), quality masks, detrending and crowding treatment. Report time system (e.g. BJD_TDB), period, epoch and cycle counting. Show representative phase-folded flux and residuals by sector or product.
- Distinguish morphology from the fitted Roche geometry. Explain what totality constrains, profile the mass ratio against inclination and third light, and test sector/product agreement. State priors, limb darkening, integration over exposure and degeneracies. Label masses and radii from Gaia or empirical relations as estimates and distinguish them from dynamical measurements.
- In review, check whether timing evidence discriminates period change from aliasing, timing-system offsets or survey systematics. Ask whether dilution or correlated noise changes the registered result.

Ap&SS is a scope reference for stellar-system studies. For AJ emphasize observations, calibration and machine-readable tables. For MNRAS make the physical inference and its context explicit. Check the chosen journal's author instructions and the 2025 CAS evidence in the main data registry's `registry/verified-venues.yaml`; `registry/settings.yaml#journal_target_policy` governs eligibility.
