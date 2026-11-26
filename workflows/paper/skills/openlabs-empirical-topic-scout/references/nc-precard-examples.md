# NC pre-admission card examples (writing examples only)

Four topic cards rewritten on 2026-11-26 from Nature Communications papers published in
July-August 2026, written as they could have been written before the work (no result
numbers; directional claims with an alternative). In the calibration replay
(`/workspace/openlabs/maintenance/20261126-followups/NC-CALIBRATION.md`) the production
prescreen graded each of them `nc`.

**These topics are taken: they are published papers.** Never propose them, a paraphrase or
a refinement of them. Copy the shape - a field-level question, complete free data, a
named authoritative benchmark, a cheap kill test on a subset with a null model - not the
subject. Several fields (`data_access_verified: false`, no access receipt, no fee or
licence check) are incomplete because the cards were written for the replay; a real card
carries the access receipt.

What the four share:

- The question is one a whole field reads (river integrity, exoplanet-system evolution,
  operational earthquake forecasting, energy access), not a detail of one subfield.
- The data is the complete public archive (all rivers above a width, every archival HARPS
  spectrum of PDS 70, eleven years of 27 CSEP models, tariff schedules of 48 countries);
  the kill test alone uses a subset.
- Novelty comes from a new question or a first assembly of scattered public records,
  not from a counter-intuitive twist on a published result.
- The benchmark is an authoritative reference or policy parameter, named.

## NC10-global-riverfronts

- Source paper (taken): https://doi.org/10.1038/s41467-026-75777-0, published 2026-07-18; card written as of 2026-01-15.
- Calibration replay grade: gpt: nc (thresholds met: generality, benchmark, resource).

```json
{
 "question": "River fragmentation has been mapped longitudinally (dams); the lateral water-land interface - riverfronts - is also modified by agriculture and built-up land, but no global map exists. What share of the world's riverfronts is anthropogenically modified, where, by what, and does lateral modification relate to water quality and biodiversity threats?",
 "nc_case": {
  "claim": "Roughly a fifth of global riverfronts are anthropogenically modified, mostly by agriculture and built-up land, concentrated in a modification belt across Africa and Eurasia, a lateral fragmentation that differs from dam-induced longitudinal fragmentation and tracks water-quality and biodiversity threats.",
  "alternative_claim": "Riverfront modification is small and simply mirrors catchment land use, adding nothing beyond existing land-cover and dam-fragmentation indices.",
  "challenges": "The focus of global river-integrity assessments on longitudinal connectivity (free-flowing rivers) that omits lateral human pressure.",
  "benchmark": "Grill et al. 2019 (Nature) free-flowing rivers as the authoritative fragmentation reference; ESA WorldCover and GRWL/MERIT Hydro river networks.",
  "thresholds": {
   "generality": {
    "met": true,
    "evidence": "Global, all rivers above a width threshold."
   },
   "counterintuitive": {
    "met": true,
    "evidence": "Lateral pressure is distinct from and complementary to dam fragmentation."
   },
   "scale": {
    "met": true,
    "evidence": "~7.5 million km of riverfront mapped at high resolution vs regional studies."
   },
   "benchmark": {
    "met": true,
    "evidence": "Compared with the free-flowing rivers index."
   },
   "resource": {
    "met": true,
    "evidence": "Global riverfront modification map released."
   }
  },
  "exemplars": [
   "E4",
   "E1",
   "S1"
  ]
 },
 "data_sources": [
  {
   "catalog_id": "sentinel2-l2a-cogs-aws",
   "url": "https://registry.opendata.aws/sentinel-2-l2a-cogs/",
   "license": "Copernicus open",
   "version": "L2A COGs"
  },
  {
   "catalog_id": "esa-worldcover",
   "catalog_candidate": true,
   "url": "https://esa-worldcover.org/",
   "license": "CC BY 4.0",
   "version": "2021 v200"
  },
  {
   "catalog_id": "grwl",
   "catalog_candidate": true,
   "url": "https://zenodo.org/records/1297434",
   "license": "CC BY 4.0",
   "version": "GRWL v01.01"
  }
 ],
 "data_volume": {
  "total_gb": 900,
  "largest_file_gb": 1,
  "proxy_expected": false,
  "offpeak_days": 5,
  "ailab_storage_gb": 1200
 },
 "decisive_analysis": {
  "description": "Buffer river centerlines; classify riverfront land use with a segmentation model trained on WorldCover plus manual labels; compute modification share by basin; relate to free-flowing index, water quality and IUCN threat data.",
  "data_access_verified": false
 },
 "kill_test": {
  "signal": "On 5 large basins, the riverfront modified share differs from the catchment-average modified share by more than 30% relative.",
  "null_model": "Catchment-average land-use share (riverfront = catchment).",
  "ceiling": "Classification accuracy of the segmentation model.",
  "pass_rule": "Relative difference >= 30% in at least 3 of 5 basins with classification accuracy >= 85%.",
  "core_hours": 2
 },
 "milestones": [
  {
   "name": "5-basin pilot with catchment null",
   "kind": "decisive",
   "agent_hours": 3,
   "core_hours": 2,
   "model_usd": 10
  },
  {
   "name": "Global mapping and driver analysis",
   "kind": "validation",
   "agent_hours": 15,
   "core_hours": 400,
   "model_usd": 50
  },
  {
   "name": "Map release",
   "kind": "resource",
   "agent_hours": 3,
   "core_hours": 10,
   "model_usd": 8
  }
 ],
 "primary_endpoint": {
  "metric": "Global share of modified riverfront length",
  "matched_baseline": "Catchment land-use share",
  "split": "Basins",
  "decision_rule": "Claim holds if riverfront modification differs from catchment null in most basins",
  "stop_rule": "Freeze if pilot difference < 10%"
 },
 "closest_prior_work": [
  {
   "citation": "Grill et al. 2019, Mapping the world's free-flowing rivers, Nature",
   "what_it_shows": "Longitudinal connectivity",
   "our_difference": "Lateral riverfront modification"
  },
  {
   "citation": "Allen & Pavelsky 2018, Global extent of rivers and streams, Science",
   "what_it_shows": "Global river widths (GRWL)",
   "our_difference": "Human imprint along riverbanks"
  }
 ],
 "audience": {
  "who": "River scientists, conservation planners, water managers."
 },
 "venues": {
  "escalation": {
   "name": "Nature Communications",
   "condition": "Global map validated"
  },
  "routine": [
   {
    "name": "Science of the Total Environment"
   },
   {
    "name": "Journal of Hydrology"
   }
  ]
 }
}
```

## NC09-pds70-exocomets

- Source paper (taken): https://doi.org/10.1038/s41467-026-76880-y, published 2026-08-24; card written as of 2026-02-15.
- Calibration replay grade: claude: nc (thresholds met: counterintuitive, benchmark), gpt: nc (thresholds met: counterintuitive).

```json
{
 "question": "JWST detected water in the inner disc of the young planet-hosting star PDS 70, of unclear origin. Do the archival HARPS spectra of PDS 70 show variable, red- or blue-shifted narrow absorption in the Na I D lines - the signature of sublimating exocomets, as in beta Pictoris - that could deliver volatiles to the inner disc?",
 "nc_case": {
  "claim": "PDS 70's archival HARPS spectra show strongly and stochastically variable Na I absorption on daily timescales, best explained by sublimating planetesimals on eccentric orbits transiting the star, which offers a source for the inner-disc water seen by JWST.",
  "alternative_claim": "No variable absorption above the noise, or variability explained by stellar activity, accretion flows or the interstellar medium.",
  "challenges": "The view that exocomet activity is seen mainly in older debris-disc A stars like beta Pic, and that inner-disc water in PDS 70 must come from disc transport alone.",
  "benchmark": "beta Pictoris exocomet families (Kiefer et al. 2014, Nature) as the reference phenomenon; JWST/MIRI water detection (Perotti et al. 2023, Nature).",
  "thresholds": {
   "generality": {
    "met": false,
    "evidence": "One star."
   },
   "counterintuitive": {
    "met": true,
    "evidence": "Exocomet activity in a young, planet-forming T Tauri system."
   },
   "scale": {
    "met": false,
    "evidence": "Single system."
   },
   "benchmark": {
    "met": true,
    "evidence": "Compared with the beta Pic exocomet paradigm and JWST results."
   },
   "resource": {
    "met": false,
    "evidence": "None."
   }
  },
  "exemplars": [
   "P3",
   "P5",
   "P8"
  ]
 },
 "data_sources": [
  {
   "catalog_id": "eso-archive-harps",
   "catalog_candidate": true,
   "url": "https://archive.eso.org/",
   "license": "ESO archive public data",
   "version": "HARPS reduced spectra of PDS 70"
  }
 ],
 "data_volume": {
  "total_gb": 2,
  "largest_file_gb": 0.01,
  "proxy_expected": false,
  "offpeak_days": 0,
  "ailab_storage_gb": 3
 },
 "decisive_analysis": {
  "description": "Retrieve all HARPS spectra; normalize Na I D region; model the stable component; detect variable absorption components (velocity, depth, width) per epoch; test against telluric, ISM and accretion-line behaviour (H-alpha, Ca II).",
  "data_access_verified": false
 },
 "kill_test": {
  "signal": "Na I D residual absorption components exceeding 5 sigma in at least 3 epochs.",
  "null_model": "Noise and telluric residuals measured in comparison stars and in neighbouring continuum.",
  "ceiling": "Number of epochs available.",
  "pass_rule": ">= 3 epochs with >= 5 sigma variable absorption not correlated with H-alpha accretion indicators.",
  "core_hours": 1
 },
 "milestones": [
  {
   "name": "Na I D variability detection",
   "kind": "decisive",
   "agent_hours": 2,
   "core_hours": 1,
   "model_usd": 6
  },
  {
   "name": "Hypothesis tests (accretion, ISM, activity), modelling",
   "kind": "validation",
   "agent_hours": 6,
   "core_hours": 4,
   "model_usd": 20
  }
 ],
 "primary_endpoint": {
  "metric": "Number and significance of variable Na I absorption components",
  "matched_baseline": "Comparison-star residuals",
  "split": "Epochs",
  "decision_rule": "Claim holds if >= 3 significant epochs and accretion correlation rejected",
  "stop_rule": "Freeze if no epoch above 5 sigma"
 },
 "closest_prior_work": [
  {
   "citation": "Kiefer et al. 2014, Two families of exocomets in the beta Pictoris system, Nature",
   "what_it_shows": "Exocomet families from HARPS Ca II",
   "our_difference": "Young planet-forming system"
  },
  {
   "citation": "Perotti et al. 2023, Water in the terrestrial planet-forming zone of the PDS 70 disk, Nature",
   "what_it_shows": "JWST water detection",
   "our_difference": "Possible delivery mechanism"
  }
 ],
 "audience": {
  "who": "Exoplanet and planet-formation astronomers."
 },
 "venues": {
  "escalation": {
   "name": "Nature Communications",
   "condition": "Exocomet interpretation preferred over alternatives"
  },
  "routine": [
   {
    "name": "Monthly Notices of the Royal Astronomical Society"
   },
   {
    "name": "Astronomy & Astrophysics"
   }
  ]
 }
}
```

## NC01-csep-eqforecast

- Source paper (taken): https://doi.org/10.1038/s41467-026-76243-7, published 2026-08-06; card written as of 2026-02-01.
- Calibration replay grade: gpt: nc (thresholds met: generality, benchmark).

```json
{
 "question": "After eleven years of truly prospective operation (2007-2018), which of the 27 next-day earthquake forecasting models run in the CSEP California testing center are consistent with what actually happened, and does the model class used for operational earthquake forecasting (ETAS/STEP-type clustering models) earn its operational status?",
 "nc_case": {
  "claim": "Only a minority of model classes stay consistent with a decade of prospective California seismicity in number, space and magnitude at once, and the clustering models of the type agencies operate are among the few that do, which gives operational earthquake forecasting its first long prospective validation.",
  "alternative_claim": "No model class, including the operational type, is consistently better than a smoothed-seismicity or Poisson reference over the full prospective period, so operational forecasts rest on retrospective evidence only.",
  "challenges": "The practice of putting earthquake forecasts into operation (USGS aftershock forecasts, New Zealand, Italy) on the basis of retrospective tests and short prospective windows; the 5-year RELM experiment was too short and too sparse to separate models.",
  "benchmark": "The CSEP community-vetted consistency tests (N, S, M, CL tests) and comparative T/W tests against a reference model; the ANSS Comprehensive Catalog (ComCat) as ground truth; the RELM 5-year results (Zechar et al. 2013) as the largest prior prospective evaluation.",
  "thresholds": {
   "generality": {
    "met": true,
    "evidence": "The question is whether any short-term earthquake forecast can be trusted prospectively; it applies to every agency that runs OEF."
   },
   "counterintuitive": {
    "met": false,
    "evidence": "Depends on the result; a failure of most models would be counterintuitive to OEF practice, a pass would not be."
   },
   "scale": {
    "met": true,
    "evidence": "About 50,000 next-day forecasts by 27 models over 11 years vs. 5-year, 18-model RELM tests: well over an order of magnitude more forecast-days."
   },
   "benchmark": {
    "met": true,
    "evidence": "Community-standard CSEP tests and ComCat; comparison with the operational model class."
   },
   "resource": {
    "met": true,
    "evidence": "Release the cleaned prospective forecast archive, evaluation code (pyCSEP) and per-model scorecards as a benchmark for new OEF models."
   }
  },
  "exemplars": [
   "N2",
   "A1",
   "P4"
  ]
 },
 "data_sources": [
  {
   "catalog_id": "csep-california-testing-center-archive",
   "catalog_candidate": true,
   "url": "https://cseptesting.org/",
   "license": "CSEP community data (open)",
   "version": "Next-day forecasts 2007-08 to 2018-08 as archived by the SCEC testing center"
  },
  {
   "catalog_id": "usgs-comcat",
   "catalog_candidate": true,
   "url": "https://earthquake.usgs.gov/fdsnws/event/1/",
   "license": "Public domain",
   "version": "ANSS ComCat, California testing region, Mw >= 3.95"
  }
 ],
 "data_volume": {
  "total_gb": 40,
  "largest_file_gb": 0.5,
  "proxy_expected": false,
  "offpeak_days": 0,
  "ailab_storage_gb": 60
 },
 "decisive_analysis": {
  "description": "For every model, run the N, S, M and conditional-likelihood tests over all prospective days and over cumulative windows; compare model pairs with T/W tests against the smoothed-seismicity reference; stratify by model class.",
  "data_access_verified": false
 },
 "kill_test": {
  "signal": "At least one model class is consistent with the prospective data in N, S and M simultaneously while the Poisson reference is not, on a one-year subset.",
  "null_model": "Time-independent smoothed-seismicity (Poisson) reference forecast and a declustered-rate model.",
  "ceiling": "Information gain per earthquake of a perfect clustering model given ComCat (upper bound from the observed aftershock fraction).",
  "pass_rule": "On the 2010 subset, at least 3 models pass N, S and M at alpha = 0.05 and at least one has a positive information gain over the reference with a 95% interval excluding 0.",
  "core_hours": 2
 },
 "milestones": [
  {
   "name": "One-year subset: consistency tests and information gain vs reference",
   "kind": "decisive",
   "agent_hours": 2,
   "core_hours": 2,
   "model_usd": 8
  },
  {
   "name": "Full 11-year evaluation, cumulative windows, class stratification",
   "kind": "validation",
   "agent_hours": 6,
   "core_hours": 40,
   "model_usd": 25
  },
  {
   "name": "Release benchmark archive and scorecards",
   "kind": "resource",
   "agent_hours": 3,
   "core_hours": 4,
   "model_usd": 10
  }
 ],
 "primary_endpoint": {
  "metric": "Fraction of models passing N, S, M tests jointly over the prospective period; information gain per earthquake vs reference",
  "matched_baseline": "Smoothed-seismicity Poisson reference",
  "split": "Fully prospective 2007-2018",
  "decision_rule": "Claim holds if the operational class passes all three tests and has positive information gain with 95% CI excluding 0",
  "stop_rule": "Freeze if no model beats the reference on the one-year subset"
 },
 "closest_prior_work": [
  {
   "citation": "Zechar et al. 2013, Regional Earthquake Likelihood Models I: first-order results, BSSA",
   "what_it_shows": "5-year RELM prospective tests of 18 long-term models",
   "our_difference": "Short-term (next-day) models over 11 years, including the operational class"
  },
  {
   "citation": "Strader et al. 2017, Prospective and retrospective evaluation of five-year earthquake forecast models for California, GJI",
   "what_it_shows": "Extends RELM-type evaluation of 5-year models",
   "our_difference": "Daily models, 50k forecasts, class-level conclusions for OEF"
  },
  {
   "citation": "Schorlemmer et al. 2018, The Collaboratory for the Study of Earthquake Predictability: achievements and priorities, SRL",
   "what_it_shows": "Review of CSEP and its testing centers",
   "our_difference": "A complete evaluation of the California next-day archive"
  }
 ],
 "audience": {
  "who": "Seismologists, agencies running operational earthquake forecasting, forecast-evaluation methodologists."
 },
 "venues": {
  "escalation": {
   "name": "Nature Communications",
   "condition": "The full evaluation separates model classes"
  },
  "routine": [
   {
    "name": "Seismological Research Letters"
   },
   {
    "name": "Bulletin of the Seismological Society of America"
   }
  ]
 }
}
```

## NC08-ssa-grid-affordability

- Source paper (taken): https://doi.org/10.1038/s41467-026-75104-7, published 2026-07-09; card written as of 2026-01-01.
- Calibration replay grade: gpt: nc (thresholds met: generality, benchmark).

```json
{
 "question": "Grid expansion is the main strategy for universal electricity access in Sub-Saharan Africa. Under current residential tariffs, how many people could afford the electricity consumption levels of the Multi-Tier Framework (Tiers 3-5), and where do unaffordable tariffs and loss-making utilities combine into 'electrification traps' where grid expansion cannot pay for itself?",
 "nc_case": {
  "claim": "Under current tariffs about half of Sub-Saharan Africans could not afford Tier 4 electricity and most could not afford Tier 5 at a 10% energy-poverty threshold; combined with utility deficits this identifies countries where grid expansion is financially self-defeating and off-grid is the only feasible SDG7 path.",
  "alternative_claim": "Current tariffs are affordable to most households at Tier 4, and utility deficits come from losses and collection rather than affordability, so grid expansion remains the default.",
  "challenges": "The planning assumption (IEA, World Bank least-cost electrification) that grid extension is the cheapest path wherever density allows, which ignores whether customers can pay tariffs that cover costs.",
  "benchmark": "World Bank Multi-Tier Framework consumption tiers; SDG7 targets; utility financial viability assessments (Kojima & Trimble 2016).",
  "thresholds": {
   "generality": {
    "met": true,
    "evidence": "48 countries, whole population income distributions."
   },
   "counterintuitive": {
    "met": true,
    "evidence": "Grid expansion can deepen utility deficits where tariffs are unaffordable."
   },
   "scale": {
    "met": true,
    "evidence": "48-country tariff dataset vs prior single-country or 10-country studies."
   },
   "benchmark": {
    "met": true,
    "evidence": "MTF tiers, SDG7, utility finances."
   },
   "resource": {
    "met": true,
    "evidence": "Open, standardized residential tariff dataset for 48 SSA countries."
   }
  },
  "exemplars": [
   "N6",
   "N7",
   "S2"
  ]
 },
 "data_sources": [
  {
   "catalog_id": "utility-tariff-schedules",
   "catalog_candidate": true,
   "url": "https://rise.esmap.org/",
   "license": "Public",
   "version": "Utility/regulator published tariff schedules 2023-2025; RISE indicators"
  },
  {
   "catalog_id": "world-bank-pip",
   "catalog_candidate": true,
   "url": "https://pip.worldbank.org/",
   "license": "CC BY 4.0",
   "version": "Poverty and Inequality Platform income/consumption distributions"
  },
  {
   "catalog_id": "world-bank-mtf",
   "catalog_candidate": true,
   "url": "https://mtfenergyaccess.esmap.org/",
   "license": "CC BY 4.0",
   "version": "MTF tier definitions"
  }
 ],
 "data_volume": {
  "total_gb": 0.5,
  "largest_file_gb": 0.1,
  "proxy_expected": false,
  "offpeak_days": 0,
  "ailab_storage_gb": 1
 },
 "decisive_analysis": {
  "description": "Compile tariffs (block structures, fixed charges, taxes) for 48 countries; compute monthly bills for each MTF tier; simulate household income distributions; compute share unable to afford at 5/10/15% thresholds; join with utility financial indicators.",
  "data_access_verified": false
 },
 "kill_test": {
  "signal": "In 10 pilot countries, more than 30% of the population cannot afford Tier 4 at 10% of income.",
  "null_model": "Cost-reflective tariff vs current tariff; lifeline tariff structures.",
  "ceiling": "Share of population below the poverty line.",
  "pass_rule": "Unaffordable share >= 30% in at least 6 of 10 countries.",
  "core_hours": 1
 },
 "milestones": [
  {
   "name": "10-country tariff compilation and affordability",
   "kind": "decisive",
   "agent_hours": 4,
   "core_hours": 1,
   "model_usd": 12
  },
  {
   "name": "48 countries, utility finance join, sensitivity",
   "kind": "validation",
   "agent_hours": 10,
   "core_hours": 4,
   "model_usd": 35
  },
  {
   "name": "Tariff dataset release",
   "kind": "resource",
   "agent_hours": 3,
   "core_hours": 1,
   "model_usd": 8
  }
 ],
 "primary_endpoint": {
  "metric": "Population share unable to afford Tier 4/5",
  "matched_baseline": "Poverty-line share",
  "split": "Thresholds 5/10/15%",
  "decision_rule": "Claim holds if >= 40% cannot afford Tier 4 region-wide",
  "stop_rule": "Freeze if pilot < 20%"
 },
 "closest_prior_work": [
  {
   "citation": "Kojima & Trimble 2016, Making Power Affordable for Africa and Viable for Its Utilities, World Bank",
   "what_it_shows": "Utility quasi-fiscal deficits and affordability of subsistence consumption",
   "our_difference": "All MTF tiers, 48 countries, income distributions, electrification traps"
  },
  {
   "citation": "Blimpo & Cosgrove-Davies 2019, Electricity Access in Sub-Saharan Africa, World Bank",
   "what_it_shows": "Uptake and reliability barriers",
   "our_difference": "Quantified affordability vs utility viability map"
  }
 ],
 "audience": {
  "who": "Energy-access planners, World Bank/IEA, African regulators and utilities."
 },
 "venues": {
  "escalation": {
   "name": "Nature Communications",
   "condition": "Results robust to income and threshold choices"
  },
  "routine": [
   {
    "name": "Energy for Sustainable Development"
   },
   {
    "name": "Energy Policy"
   }
  ]
 }
}
```
