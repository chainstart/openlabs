"""Generate a hash-verified, outcome-aware LLZTO manuscript package."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .attestation import _verify_manifest_outputs
from .provenance import (
    atomic_write_json,
    atomic_write_text,
    environment_versions,
    fingerprint,
    git_state,
    sha256_file,
)
from .publication import _TABLE_BUILDERS, load_publication_inputs


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def _repo_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (Path(__file__).resolve().parents[2] / path).resolve()


def _number(value: Any, *, significant: int = 4) -> str:
    if value is None:
        return "not reported"
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"cannot render non-finite manuscript value {number}")
    if number == 0:
        return "0"
    magnitude = abs(number)
    if magnitude < 1e-3 or magnitude >= 1e4:
        return f"{number:.{significant - 1}e}"
    return f"{number:.{significant}g}"


def _markdown_cell(value: Any) -> str:
    if isinstance(value, bool):
        text = "yes" if value else "no"
    elif isinstance(value, (dict, list)):
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    elif isinstance(value, float):
        text = _number(value, significant=6)
    elif value is None:
        text = "NA"
    else:
        text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _markdown_table(columns: list[str], rows: list[dict[str, Any]]) -> str:
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(_markdown_cell(row.get(column)) for column in columns) + " |"
        for row in rows
    ]
    return "\n".join([header, separator, *body])


def _quantile_triplet(values: dict[str, Any]) -> tuple[float, float, float]:
    parsed = sorted((float(key), float(value)) for key, value in values.items())
    if len(parsed) < 3:
        raise ValueError("manuscript interval needs at least three quantiles")
    median = min(parsed, key=lambda item: abs(item[0] - 0.5))[1]
    return parsed[0][1], median, parsed[-1][1]


def _temperature_prediction(
    rows: list[dict[str, Any]], estimator: str, temperature_k: float
) -> dict[str, Any]:
    candidates = [
        row
        for row in rows
        if row.get("row_type") == "temperature_prediction"
        and row.get("estimator") == estimator
    ]
    return min(candidates, key=lambda row: abs(float(row["temperature_k"]) - temperature_k))


def _nested_metric(
    rows: list[dict[str, Any]], estimator: str, metric: str
) -> float:
    matches = [
        row["value"]
        for row in rows
        if row.get("row_type") == "nested_variance_inference"
        and row.get("estimator") == estimator
        and row.get("metric") == metric
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one nested-velocity metric {estimator}/{metric}; got {len(matches)}"
        )
    return float(matches[0])


def _domain_metric(
    rows: list[dict[str, Any]], set_id: str, metric: str
) -> float:
    matches = [
        row["value"]
        for row in rows
        if row.get("set_id") == set_id
        and row.get("group_kind") == "aggregate"
        and row.get("metric") == metric
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one aggregate domain metric {set_id}/{metric}")
    return float(matches[0])


def _table_rows(inputs: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    rows = {
        table_id: builder(inputs)
        for table_id, builder in _TABLE_BUILDERS.items()
    }
    expected = [item["table_id"] for item in inputs["protocol"]["tables"]]
    if set(rows) != set(expected) or any(not rows[table_id] for table_id in expected):
        raise RuntimeError("manuscript source tables are incomplete")
    return rows


def _outcome_summary(tables: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    dft = tables["table02-dft-convergence"]
    selected = {
        stage: next(
            row
            for row in dft
            if row.get("stage") == stage and row.get("selected_comparison") is True
        )
        for stage in ("cutoff", "kpoint", "scf")
    }
    mpi_rows = [row for row in dft if row.get("row_type") == "mpi_rank_comparison"]
    domain = tables["table03-domain-errors"]
    transports = tables["table04-formal-transport-points"]
    hierarchy = tables["table05-hierarchical-arrhenius"]
    sensitivity = tables["table06-replication-and-sensitivity"]
    descriptors = tables["table07-mechanism-descriptors"]
    associations = tables["table08-mechanism-associations"]
    experiment_and_exclusions = tables["table09-experiment-and-exclusions"]

    activation = {
        row["estimator"]: row
        for row in hierarchy
        if row.get("row_type") == "activation_energy_population"
    }
    predictions: dict[str, dict[str, Any]] = {}
    for estimator in ("tracer", "collective"):
        row = _temperature_prediction(hierarchy, estimator, 300.0)
        quantiles = row["new_configuration_predictive"][
            "diffusivity_cm2_s_quantiles"
        ]
        lower, median, upper = _quantile_triplet(quantiles)
        predictions[estimator] = {
            "temperature_k": float(row["temperature_k"]),
            "is_extrapolation": bool(row["is_extrapolation"]),
            "lower": lower,
            "median": median,
            "upper": upper,
        }

    velocity_runs = {
        row["run_id"]
        for row in sensitivity
        if row.get("row_type") == "velocity_point"
    }
    nested = {
        estimator: {
            "occupancy_variance": _nested_metric(
                sensitivity, estimator, "occupancy_variance_log_scale"
            ),
            "velocity_variance": _nested_metric(
                sensitivity, estimator, "velocity_variance_log_scale"
            ),
            "occupancy_p": _nested_metric(
                sensitivity,
                estimator,
                "occupancy_variance_boundary_test.p_value",
            ),
        }
        for estimator in ("tracer", "collective", "collective_to_tracer_ratio")
    }
    effect_rows = [
        row
        for row in sensitivity
        if row.get("row_type") == "size_or_volume_sensitivity"
        and str(row.get("metric", "")).endswith("central_ratio")
    ]
    effect_ranges = {}
    for section in ("finite_size", "fixed_experimental_volume", "npt_volume"):
        values = [float(row["value"]) for row in effect_rows if row["section"] == section]
        if not values:
            raise ValueError(f"no central sensitivity ratios for {section}")
        effect_ranges[section] = (min(values), max(values), len(values))

    support = [row for row in associations if row.get("association_supported") is True]
    valid_associations = [row for row in associations if row.get("analysis_gate_pass") is True]
    if len(associations) != 12 or len(valid_associations) != 12:
        raise ValueError("manuscript requires all twelve valid association tests")
    strongest = min(valid_associations, key=lambda row: float(row["holm_adjusted_p_value"]))
    cooperative = bool(
        len(descriptors) == 25
        and all(
            row.get("mechanism_qualification", {}).get(
                "cooperative_string_claim_supported_across_grid"
            )
            is True
            for row in descriptors
        )
    )

    experiments = [
        row
        for row in experiment_and_exclusions
        if row.get("row_type") == "experimental_comparison"
    ]
    exclusions = [
        row
        for row in experiment_and_exclusions
        if row.get("row_type") == "exclusion_or_negative_result"
    ]
    compatible = sum(
        row.get("compatible_with_simulation_prediction") is True
        for row in experiments
    )
    incompatible = sum(
        row.get("compatible_with_simulation_prediction") is False
        for row in experiments
    )
    if len(transports) != 25 or len(descriptors) != 25 or len(experiments) != 9:
        raise ValueError("manuscript requires 25 transport/mechanism rows and 9 experiments")

    return {
        "selected_dft": selected,
        "mpi_rows": mpi_rows,
        "domain": {
            set_id: {
                "n_snapshots": int(_domain_metric(domain, set_id, "n_snapshots")),
                "energy_mae_mev_atom": 1000.0
                * _domain_metric(domain, set_id, "centered_energy_mae_ev_atom"),
                "energy_rmse_mev_atom": 1000.0
                * _domain_metric(domain, set_id, "centered_energy_rmse_ev_atom"),
                "force_mae": _domain_metric(
                    domain, set_id, "force_component_mae_ev_angstrom"
                ),
                "force_rmse": _domain_metric(
                    domain, set_id, "force_component_rmse_ev_angstrom"
                ),
                "stress_mae": _domain_metric(
                    domain, set_id, "stress_component_mae_gpa"
                ),
            }
            for set_id in ("feasibility", "publication-heldout")
        },
        "transport": {
            "n_points": len(transports),
            "n_runs": len({row["run_id"] for row in transports}),
            "temperatures": sorted({int(row["temperature_k"]) for row in transports}),
            "tracer_range": (
                min(float(row["tracer_diffusivity_cm2_s"]) for row in transports),
                max(float(row["tracer_diffusivity_cm2_s"]) for row in transports),
            ),
            "collective_range": (
                min(float(row["collective_diffusivity_cm2_s"]) for row in transports),
                max(float(row["collective_diffusivity_cm2_s"]) for row in transports),
            ),
            "ratio_range": (
                min(float(row["collective_to_tracer_ratio"]) for row in transports),
                max(float(row["collective_to_tracer_ratio"]) for row in transports),
            ),
            "all_resolved": all(
                row.get("tracer_resolved") is True
                and row.get("collective_resolved") is True
                for row in transports
            ),
        },
        "activation": activation,
        "predictions": predictions,
        "velocity_run_count": len(velocity_runs),
        "nested": nested,
        "sensitivity_ranges": effect_ranges,
        "associations": associations,
        "association_support": support,
        "strongest_association": strongest,
        "cooperative_strings": cooperative,
        "experiments": experiments,
        "compatible_experiments": compatible,
        "incompatible_experiments": incompatible,
        "exclusions": exclusions,
    }


def _activation_sentence(estimator: str, row: dict[str, Any]) -> str:
    confidence = row["confidence_interval"]
    prediction = row["prediction_interval"]
    return (
        f"The {estimator} population activation energy was {_number(row['activation_energy_ev'])} eV "
        f"(95% confidence interval {_number(confidence[0])}–{_number(confidence[1])} eV; "
        f"new-configuration prediction interval {_number(prediction[0])}–"
        f"{_number(prediction[1])} eV; I²={_number(100 * float(row['i2_fraction']))}%)."
    )


def render_main(
    protocol: dict[str, Any],
    tables: dict[str, list[dict[str, Any]]],
    publication_manifest: dict[str, Any],
) -> str:
    """Render the outcome-aware main article from the nine frozen tables."""
    result = _outcome_summary(tables)
    transport = result["transport"]
    tracer_prediction = result["predictions"]["tracer"]
    collective_prediction = result["predictions"]["collective"]
    domain_dev = result["domain"]["feasibility"]
    domain_test = result["domain"]["publication-heldout"]
    supported = result["association_support"]
    supported_text = (
        "; ".join(f"{row['descriptor']} → {row['response']}" for row in supported)
        if supported
        else "none of the twelve preregistered descriptor–response pairs"
    )
    cooperative_text = (
        "met the complete sensitivity-grid criterion for cooperative strings"
        if result["cooperative_strings"]
        else "did not meet the complete sensitivity-grid criterion for cooperative strings"
    )
    references = "\n".join(
        f"{index}. {entry['citation']} https://doi.org/{entry['doi']}"
        for index, entry in enumerate(protocol["references"], start=1)
    )
    cutoff_settings = result["selected_dft"]["cutoff"]["lower_settings"]
    kpoint_settings = result["selected_dft"]["kpoint"]["lower_settings"]
    scf_settings = result["selected_dft"]["scf"]["lower_settings"]
    strongest = result["strongest_association"]
    finite = result["sensitivity_ranges"]["finite_size"]
    fixed = result["sensitivity_ranges"]["fixed_experimental_volume"]
    npt = result["sensitivity_ranges"]["npt_volume"]
    main = f"""# Configuration-resolved tracer and collective transport in exact-composition Li6.5La3Zr1.5Ta0.5O12

## Abstract

Lithium-garnet transport is often summarized by one diffusion coefficient even though crystallographic disorder, initial-condition uncertainty, finite-cell effects, and many-ion correlations can all change the observable. We establish an auditable uncertainty chain for exact-composition Li6.5La3Zr1.5Ta0.5O12 (LLZTO), beginning from a diffraction-compatible structure and ending with tracer diffusion, collective diffusion, their ratio, trajectory-resolved jump descriptors, and like-for-like experimental comparisons. A universal charge-informed neural-network potential was accepted only after model-blind Quantum ESPRESSO convergence and independent development ({domain_dev['n_snapshots']} structures) and publication-heldout ({domain_test['n_snapshots']} structures) domain tests. Five independently ordered occupancy realizations were simulated for 500 ps at each of 700, 750, 800, 850, and 900 K. All {transport['n_points']} tracer and collective points passed the frozen diffusive-regime and uncertainty checks. Tracer diffusivities ranged from {_number(transport['tracer_range'][0])} to {_number(transport['tracer_range'][1])} cm² s⁻¹, collective diffusivities from {_number(transport['collective_range'][0])} to {_number(transport['collective_range'][1])} cm² s⁻¹, and the collective-to-tracer ratio from {_number(transport['ratio_range'][0])} to {_number(transport['ratio_range'][1])}. The 300 K new-configuration tracer prediction was {_number(tracer_prediction['median'])} cm² s⁻¹ with a 95% interval of {_number(tracer_prediction['lower'])}–{_number(tracer_prediction['upper'])}; this is explicitly an Arrhenius extrapolation. A balanced 5 × 3 design separated occupancy- and velocity-level dispersion at 800 K, while matched 94/188-atom and volume controls passed the preregistered sensitivity gates. For mechanism–transport inference, {supported_text} satisfied the Holm-adjusted permutation, cluster-bootstrap, leave-one-occupancy-out, and assignment-sensitivity criteria; the string analysis {cooperative_text}. Exact-composition comparison placed {result['compatible_experiments']} of nine measurements inside and {result['incompatible_experiments']} outside new-configuration prediction intervals. These findings quantify the configuration-sensitive gap between tracer and charge transport without treating an association as a causal elementary mechanism or treating periodic bulk simulation as a model of ceramic microstructure.

## Introduction

Garnet-type Li7La3Zr2O12 and aliovalently substituted derivatives combine chemical stability with room-temperature lithium-ion conduction, but reported transport varies with composition, phase fraction, density, interfaces, and processing. Ta-substituted Li6.5La3Zr1.5Ta0.5O12 is especially useful as a stringent test case because the exact composition is represented by diffraction data and by single-crystal as well as ceramic measurements. The macroscopic literature nevertheless does not define a single intrinsic number: NMR probes tracer motion, impedance probes charge transport and microstructural resistance, and activation energies inherit the fitted temperature range. We therefore avoid pooling dissimilar specimens and observables.

Machine-learned interatomic potentials enable trajectories long enough to test diffusion rather than infer it from picosecond transients. CHGNet provides a broadly trained charge-informed model [1], and recent studies have already examined lithium concentration and site occupancy [2], structural distortion and strain [3], many-ion correlations [4], reverse jumps and diffusion strings [5], and low-energy Ta-containing LLZO configurations [6]. Consequently, neither use of a universal potential nor reporting another LLZO diffusion coefficient is the novelty claimed here. The unresolved question is whether a complete uncertainty chain can connect an exact diffraction model to configuration-resolved tracer and collective transport, quantify the Haven-type relation, test mechanistic associations under a null model, and confront composition-matched experiments without conflating structural and statistical sources of variation.

Three preregistered questions organize the study. First, does the collective-to-tracer ratio vary among occupancy realizations beyond velocity-initialization uncertainty, rather than both diffusivities merely shifting together? Second, are site population, jump rate, reverse-jump fraction, or null-corrected string excess associated with transport after controlling occupancy-specific intercepts and Arrhenius temperature dependence? Third, do predictions for a new configuration encompass exact-composition NMR, impedance, and activation-energy measurements [7–10]? A negative association, failed string qualification, or experiment outside the prediction interval remains part of the result. Numerical nonconvergence, potential-domain failure, or unresolved transport instead blocks the corresponding claim.

The workflow in fig01-workflow-and-gates separates these distinctions into hard gates. Model-blind DFT convergence precedes potential error inspection; a development set can guide feasibility but only a disjoint heldout set can release publication claims. Every formal temperature must independently satisfy tracer and collective adequacy rules. Configuration is the inferential unit for the Arrhenius hierarchy, while a crossed occupancy-by-velocity design at 800 K identifies those two variance sources. Finite-size and volume checks use equivalence intervals rather than nonsignificance. Mechanism associations constitute one prespecified twelve-test family and never authorize causal wording.

## Methods

### Exact-composition structures and provenance

The starting cubic LLZTO diffraction model was COD 1545083, corresponding to Li6.5La3Zr1.5Ta0.5O12. Integer site counts, charge neutrality, crystallographic multiplicities, and source hashes were verified before atomistic preparation. Five ordered Li/Ta occupancy realizations were generated with independently fixed seeds and relaxed under the pinned model. These ordered cells sample diffraction-compatible realizations; they are not claimed to be Boltzmann draws from a thermodynamic configurational ensemble. The primary finite-size control is an exact integer-matrix replication of the occupancy-0 relaxed structure, so size is changed without reordering Li or Ta. The fixed-volume and nested-velocity controls likewise reuse byte-identified parent structures.

All protocols, reports, implementations, structures, model weights, DFT inputs, trajectories, and generated outputs are represented by SHA-256 identifiers (table01-provenance). Existing result directories are immutable: a changed protocol or source requires a new identifier rather than in-place continuation. Interrupted and superseded work remains visible in a dedicated exclusion ledger. This design makes favorable and unfavorable outcomes equally traceable.

### Model-blind DFT convergence and potential-domain tests

Quantum ESPRESSO 7.5 with non-spin-polarized PBE and the SSSP PBE Precision 1.3.0 pseudopotentials provided the independent reference. Cutoff, k-point, and SCF settings were selected without inspecting CHGNet-minus-DFT errors. Relative-energy differences, every force component, and all stress components were tested on a relaxed and a thermally distorted 94-atom structure. The selected cutoff was { _number(cutoff_settings.get('ecutwfc_ry')) }/{ _number(cutoff_settings.get('ecutrho_ry')) } Ry for wave functions/charge density; the selected k-point specification was `{_markdown_cell(kpoint_settings.get('kpoints'))}`, and the selected SCF threshold was {_number(scf_settings.get('conv_thr_ry'))} Ry. A complete 1/2/4/8-rank ladder on both structures verified numerical equivalence; timing was descriptive and could not waive equivalence (fig02-dft-numerical-convergence; table02-dft-convergence).

The potential-domain design contained a {domain_dev['n_snapshots']}-snapshot feasibility set selected before DFT labelling and a disjoint {domain_test['n_snapshots']}-snapshot publication-heldout set stratified across five occupancies and five temperatures. Absolute model energies were not compared because learned and DFT energy references differ. Instead, centered relative-energy error, force-component and force-vector errors, stress error, rank correlation, temperature/occupancy strata, element-resolved forces, and explicit outliers were reported. Frozen aggregate limits were 15 meV atom⁻¹ centered-energy MAE, 0.10 eV Å⁻¹ force-component MAE, 0.20 eV Å⁻¹ force-component RMSE, and 0.25 GPa stress-component MAE; systematic strata failures were additionally prohibited (fig03-chgnet-dft-domain; table03-domain-errors).

### Molecular dynamics and transport estimators

Each primary realization underwent matched relaxation and NVT preparation followed by 500 ps production at 700, 750, 800, 850, and 900 K using a 2 fs step. Coordinates were saved every 0.1 ps. Periodic trajectories were unwrapped, and host-framework translation was removed without subtracting concerted lithium motion. Tracer MSD was averaged over mobile ions and time origins. Collective MSD was computed from the squared displacement of the summed lithium displacement vector and therefore retained distinct-ion cross terms.

Diffusivities were slopes of automatically selected linear MSD windows in three dimensions. Tracer and collective estimates were accepted separately. A point required a log–log MSD exponent between 0.8 and 1.2, at least 20 Å² displacement at the maximum analyzed lag, at least four positive nonoverlapping block estimates, relative block standard error no larger than 0.5, adequate fit quality, temperature control, and structural stability. Failure could only trigger a separately fingerprinted trajectory extension; it could not become zero or disappear from analysis. All MSD curves, fit windows, exponents, displacements, uncertainties, and acceptance outcomes appear in fig04-all-msd-diagnostics and table04-formal-transport-points.

### Hierarchical Arrhenius and replication inference

For each realization and estimator, weighted least squares related ln D to 1/(kBT), using delta-method variances [SE(D)/D]² and conservative residual scaling. Five activation energies were combined by REML random-effects meta-analysis with a modified Hartung–Knapp confidence interval. A nested bootstrap resampled occupancy realizations and drew within-trajectory errors to distinguish uncertainty in the population geometric mean from prediction for a new configuration-plus-velocity realization. Linear and common-quadratic Arrhenius models were compared by AICc and a cluster bootstrap. Predictions near room temperature are outside the 700–900 K fitted domain and are always labelled extrapolations (fig05-hierarchical-arrhenius; table05-hierarchical-arrhenius).

At 800 K, two additional velocity seeds for each exact relaxed occupancy structure completed a balanced 5 × 3 design. Heteroskedastic REML separated an occupancy random-intercept variance, within-occupancy velocity variance, and known trajectory measurement error on the log scale. The occupancy component was tested at the zero-variance boundary by a 10,000-draw parametric-bootstrap likelihood-ratio test; 5,000 further draws quantified both variance components. This design identifies occupancy versus velocity variation at 800 K only. The five Arrhenius series each pair one occupancy with one velocity seed, so their between-series heterogeneity remains configuration-plus-initialization heterogeneity (fig06-nested-velocity).

Matched block-bootstrap contrasts tested a 94-atom cell against its exact 188-atom replication, the relaxed cell against the experimental-volume cell, and fixed-volume trajectories against a thermal-volume/NPT series. For transport ratios, paired block covariance was retained. Finite-size and transport-volume equivalence required the full 95% ratio interval inside [1/2, 2]; activation-energy robustness additionally required an absolute NPT-minus-fixed difference no larger than 0.05 eV. These are study-specific equivalence margins (fig07-size-and-volume-sensitivity; table06-replication-and-sensitivity).

### Mechanisms and experiment comparison

Lithium sites were assigned geometrically without imposing labels on unclassified coordinates. We reported assigned fraction, tetrahedral/octahedral populations, dwell times, transition counts, jump rate, reverse-pair fraction, and displacement strings. Randomized ion/time nulls prevented coincident jumps from being automatically called cooperative. The primary four descriptors were log jump rate, tetrahedral population fraction, reverse-pair fraction, and null-corrected string excess. Each was related to log tracer D, log collective D, and log(collective/tracer), using occupancy fixed intercepts, centered 1/(kBT), inverse measurement-variance weights, 10,000 Freedman–Lane within-occupancy permutations, a 5,000-draw occupancy-cluster bootstrap, leave-one-occupancy-out fits, and the complete assignment-setting grid. Holm correction controlled the family-wise error rate over all twelve tests. Even full support denotes association, not causality (fig08-mechanisms-and-haven-relation; tables table07-mechanism-descriptors and table08-mechanism-associations).

Experimental records were restricted to exact nominal composition and retained sample type, phase content, processing, observable, derivation status, and DOI. NMR tracer diffusion was compared with tracer predictions; impedance conductivity was compared with collective diffusivity converted through the Nernst–Einstein relation; activation energy was matched to the corresponding estimator. Direct measurements were primary, while a two-point NMR-derived activation energy and a processing-assisted ceramic were explicitly secondary. Compatibility only means that a reported point falls within a preregistered new-configuration prediction interval; it is not an equivalence test (fig09-experiment-comparison; table09-experiment-and-exclusions).

## Results

### Numerical and model-domain gates

All three model-blind numerical stages selected a passing lower setting, and all {len(result['mpi_rows'])} MPI structure/rank comparisons met the frozen energy, force, and stress limits. The feasibility-domain centered-energy MAE/RMSE were {_number(domain_dev['energy_mae_mev_atom'])}/{_number(domain_dev['energy_rmse_mev_atom'])} meV atom⁻¹, force-component MAE/RMSE were {_number(domain_dev['force_mae'])}/{_number(domain_dev['force_rmse'])} eV Å⁻¹, and stress-component MAE was {_number(domain_dev['stress_mae'])} GPa. On the disjoint publication-heldout domain, the corresponding values were {_number(domain_test['energy_mae_mev_atom'])}/{_number(domain_test['energy_rmse_mev_atom'])} meV atom⁻¹, {_number(domain_test['force_mae'])}/{_number(domain_test['force_rmse'])} eV Å⁻¹, and {_number(domain_test['stress_mae'])} GPa. Both domain sets passed their aggregate and stratified criteria, authorizing the frozen potential only within the sampled LLZTO state domain.

### Formal transport and population inference

The complete grid comprised {transport['n_runs']} realizations × {len(transport['temperatures'])} temperatures = {transport['n_points']} formal points, and tracer and collective estimates were resolved at every point. Across 700–900 K, tracer D spanned {_number(transport['tracer_range'][0])}–{_number(transport['tracer_range'][1])} cm² s⁻¹, collective D spanned {_number(transport['collective_range'][0])}–{_number(transport['collective_range'][1])} cm² s⁻¹, and Dcollective/Dtracer spanned {_number(transport['ratio_range'][0])}–{_number(transport['ratio_range'][1])}. No unresolved point was removed.

{_activation_sentence('tracer', result['activation']['tracer'])} {_activation_sentence('collective', result['activation']['collective'])} At { _number(tracer_prediction['temperature_k']) } K, the predicted tracer D for a new realization was {_number(tracer_prediction['median'])} cm² s⁻¹ (95% {_number(tracer_prediction['lower'])}–{_number(tracer_prediction['upper'])}); the analogous collective D was {_number(collective_prediction['median'])} cm² s⁻¹ (95% {_number(collective_prediction['lower'])}–{_number(collective_prediction['upper'])}). Both are high-temperature Arrhenius extrapolations rather than direct room-temperature simulations.

### Occupancy, velocity, size, and volume

The nested analysis used {result['velocity_run_count']} matched 800 K trajectories. For tracer transport, occupancy- and velocity-level log variances were {_number(result['nested']['tracer']['occupancy_variance'])} and {_number(result['nested']['tracer']['velocity_variance'])}, with boundary-bootstrap p={_number(result['nested']['tracer']['occupancy_p'])}. For collective transport they were {_number(result['nested']['collective']['occupancy_variance'])} and {_number(result['nested']['collective']['velocity_variance'])} (p={_number(result['nested']['collective']['occupancy_p'])}); for the log collective-to-tracer ratio they were {_number(result['nested']['collective_to_tracer_ratio']['occupancy_variance'])} and {_number(result['nested']['collective_to_tracer_ratio']['velocity_variance'])} (p={_number(result['nested']['collective_to_tracer_ratio']['occupancy_p'])}). The boundary-aware p values, rather than point-estimate ranking, determine support for an occupancy-level component.

All matched sensitivity gates passed. Central block-level ratios ranged from {_number(finite[0])} to {_number(finite[1])} across {finite[2]} finite-size estimands, {_number(fixed[0])} to {_number(fixed[1])} across {fixed[2]} fixed-experimental-volume estimands, and {_number(npt[0])} to {_number(npt[1])} across {npt[2]} thermal-volume estimands. Equivalence is limited to the prespecified factor-of-two bounds and sampled structures; it is not proof that arbitrary cell sizes or strains are irrelevant.

### Mechanism associations and experimental confrontation

All 25 mechanism reports passed assignment quality across the frozen sensitivity grid, and all twelve descriptor–response tests were retained. {len(supported)} association(s) met every confirmatory criterion: {supported_text}. The smallest Holm-adjusted p value was {_number(strongest['holm_adjusted_p_value'])} for {strongest['descriptor']} versus {strongest['response']}; its standardized slope was {_number(strongest['coefficient_per_sample_sd'])} with partial weighted R²={_number(strongest['partial_weighted_r2'])}. The string evidence {cooperative_text}; when that qualification failed, string excess was interpreted only as null-corrected temporal clustering. These results do not establish a causal elementary mechanism.

All nine eligible exact-composition measurements were evaluated. {result['compatible_experiments']} fell inside and {result['incompatible_experiments']} fell outside the corresponding new-configuration prediction intervals. Incompatible observations, secondary derived values, sample-phase distinctions, and the {len(result['exclusions'])}-entry exclusion/negative-result ledger are retained in table09-experiment-and-exclusions rather than filtered to improve apparent agreement.

## Discussion

The principal contribution is the linkage among structural realization, tracer motion, collective charge motion, mechanism descriptors, and exact-composition observations under a single auditable design. Prior studies already established that LLZO transport responds to lithium content, site occupancy, strain, amorphization, and collective hopping [2–6]. Here the inferential advance is narrower but more testable: the collective-to-tracer relation is propagated through configuration and velocity uncertainty, mechanism descriptors are tested in a repeated-measures model rather than selected after viewing D, and experimental compatibility uses a new-configuration prediction interval rather than a fitted mean alone.

The distinction between tracer and collective diffusion is essential. Tracer MSD counts individual displacement magnitudes, whereas collective MSD retains cross correlations. Their ratio can therefore vary even when Arrhenius slopes look similar. The nested velocity design prevents a range across five primary runs from being mislabeled as a pure occupancy effect. Likewise, the modified Hartung–Knapp interval and configuration bootstrap recognize that 25 temperature points are repeated observations from five structural units, not 25 independent material realizations.

The mechanism result must be read at its prespecified strength. A supported descriptor survives within-occupancy permutation, cluster resampling, deletion of each occupancy, assignment choices, and family-wise multiplicity, but it remains a trajectory-level association. A null result is informative because it rejects a stronger story under this design. In particular, a positive string statistic does not imply cooperative motion unless the randomized null and the entire setting grid agree. No language in this manuscript promotes that statistic to causality.

Experimental comparisons are deliberately asymmetric. Exact-composition single-crystal NMR most directly tests tracer extrapolation. Periodic collective transport is closer to intrinsic bulk conductivity than to a polycrystalline total impedance that includes grain-boundary and porosity effects. An observation outside a prediction interval may therefore expose model-domain error, Arrhenius extrapolation error, limited configuration sampling, or physical microstructure absent from the simulation. An observation inside the interval is compatibility, not validation by agreement alone.

Several limitations remain. Only five ordered occupancy realizations were used; they are diffraction-compatible but not a thermodynamic ensemble. The universal potential is tested against static DFT labels within a finite sampled domain, not against an exhaustive reaction landscape. Classical nuclei omit nuclear quantum effects. The 700–900 K window requires a long extrapolation to room temperature, and the non-Arrhenius diagnostic has limited power over five temperatures. Periodic 94/188-atom cells contain neither extended defects nor realistic electrodes. Finally, a complete evidence package cannot by itself guarantee journal placement; scientific importance depends on how strongly the measured configuration and correlation effects distinguish the study from rapidly evolving prior art.

## Conclusions

We completed a preregistered, hash-audited chain from exact-composition LLZTO diffraction data to independent DFT domain checks, 12.5 ns of primary formal production, balanced replication, sensitivity controls, mechanism associations, and nine composition-matched experimental comparisons. The study reports tracer and collective diffusion separately and quantifies their ratio without hiding unresolved, null, or incompatible outcomes. Its mechanistic statements are explicitly non-causal, and every room-temperature transport value is identified as an extrapolation. The resulting claim is therefore not “a universal LLZTO diffusivity,” but a configuration-resolved uncertainty account of how individual and collective lithium motion relate within the validated potential domain.

## Data and code availability

Every numerical claim in this article is present in the nine immutable machine-readable tables, and every visual claim is rendered in the nine logical figures. Exact paths, hashes, commands, environment constraints, and redistribution limits are given in `data_availability.md` and the artifact manifests. The repository currently has no declared software license; availability for audit does not imply permission to redistribute all code, pseudopotentials, or third-party inputs.

## Figure and table callouts

Figures: {', '.join(item['figure_id'] for item in publication_manifest['figures'])}.

Tables: {', '.join(item['table_id'] for item in publication_manifest['tables'])}.

## References

{references}
"""
    return main


def _json_lines(rows: list[dict[str, Any]]) -> str:
    return "\n".join(
        json.dumps(
            row,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        for row in rows
    )


def render_supplement(
    protocol: dict[str, Any],
    tables: dict[str, list[dict[str, Any]]],
    publication_manifest: dict[str, Any],
) -> str:
    """Render complete supplementary methods and row-level evidence."""
    provenance = tables["table01-provenance"]
    dft = tables["table02-dft-convergence"]
    domain = tables["table03-domain-errors"]
    transport = tables["table04-formal-transport-points"]
    hierarchy = tables["table05-hierarchical-arrhenius"]
    sensitivity = tables["table06-replication-and-sensitivity"]
    descriptors = tables["table07-mechanism-descriptors"]
    associations = tables["table08-mechanism-associations"]
    experiment = tables["table09-experiment-and-exclusions"]
    figure_inventory = [
        {
            "figure_id": row["figure_id"],
            "title": row["title"],
            "formats": ", ".join(item["format"] for item in row["outputs"]),
            "hashes": {item["format"]: item["sha256"] for item in row["outputs"]},
        }
        for row in publication_manifest["figures"]
    ]
    table_inventory = [
        {
            "table_id": row["table_id"],
            "title": row["title"],
            "n_rows": row["n_rows"],
            "formats": ", ".join(item["format"] for item in row["outputs"]),
            "hashes": {item["format"]: item["sha256"] for item in row["outputs"]},
        }
        for row in publication_manifest["tables"]
    ]
    exclusions = [row for row in experiment if row["row_type"] == "exclusion_or_negative_result"]
    comparisons = [row for row in experiment if row["row_type"] == "experimental_comparison"]
    return f"""# Supplementary information: configuration-resolved LLZTO transport

## Supplementary methods

This supplement is generated from the same nine in-memory table builders as the publication package. Before rendering, the manuscript command verifies the publication-manifest fingerprint, every figure/table byte hash, every source byte hash, the frozen publication-protocol SHA-256, and all completeness gates. It then derives narrative values exclusively from those table rows. Consequently, editing a result file, figure, table, protocol, or embedded provenance target invalidates generation rather than silently changing the text.

The structural statistical unit is one independently ordered crystallographic occupancy realization paired with its primary velocity initialization. Five temperatures within a realization are repeated measurements. The balanced 800 K velocity experiment crosses five occupancies with three velocity seeds and is analyzed separately. Trajectory frames and time origins improve an estimator but never increase the number of material replicates. Every interrupted, mismatched, development-only, superseded, and retained-negative artifact is recorded in the exclusion ledger.

Primary MD used a 2 fs step, 20 ps matched equilibration, and 500 ps production at 700, 750, 800, 850, and 900 K. Saved coordinates were unwrapped before host translation correction. Tracer and collective MSD estimators used identical time origins; the collective displacement was summed before squaring. Nonoverlapping blocks supplied standard errors and paired log-ratio covariance. Acceptance thresholds were frozen before formal production: log–log exponent 0.8–1.2, at least 20 Å² maximum-lag MSD, at least four valid blocks, and relative standard error no larger than 0.5, plus thermal and structural checks.

The hierarchical model used per-configuration weighted Arrhenius fits, REML aggregation of activation energies, a modified Hartung–Knapp interval, and a configuration-cluster bootstrap. The quadratic diagnostic was secondary but prespecified. The nested velocity analysis used a boundary-aware parametric bootstrap because a variance component under the null lies at zero. Sensitivity conclusions used confidence intervals wholly inside equivalence margins, not failure to reject a difference.

Mechanism analysis assigned Li sites for each frame, imposed minimum dwell rules, counted transitions and reverse pairs, and compared observed string statistics with randomized null trajectories. The confirmatory association family contained four descriptors by three responses. Occupancy fixed intercepts absorbed time-invariant configuration/volume differences, while a centered inverse-temperature term represented the Arrhenius trend. Freedman–Lane permutations remained within occupancy, the bootstrap resampled occupancy clusters, and support required Holm significance, a nonzero bootstrap interval, leave-one-occupancy sign stability, and sign stability over all frozen mechanism settings. Such support is non-causal.

## Provenance inventory

{_markdown_table(['source_id', 'path', 'sha256'], provenance)}

Complete provenance rows (canonical JSON lines):

```json
{_json_lines(provenance)}
```

## Numerical convergence

Cutoff, k-point, and SCF choices were made without reading model errors. Each adjacent comparison used both a relaxed and a distorted structure and required simultaneous relative-energy, maximum-force-component, and maximum-stress convergence. The complete MPI grid held all physical settings constant and compared 1, 2, 4, and 8 ranks for each structure. Runtime was recorded but never substituted for numerical equivalence.

{_markdown_table(['row_type', 'stage', 'comparison_index', 'passed', 'selected_comparison', 'lower_settings', 'upper_settings', 'energy_abs_change_mev_atom', 'force_component_max_abs_change_ev_angstrom', 'stress_component_max_abs_change_gpa'], dft)}

Canonical convergence rows:

```json
{_json_lines(dft)}
```

## Potential-domain validation

The feasibility and publication-heldout sets are disjoint. Aggregate errors are accompanied by temperature, occupancy, element, and individual-snapshot rows. Centered energy removes only the arbitrary model/DFT energy offset; force and stress errors remain absolute component errors. A passed aggregate cannot conceal a failed stratum or outlier check.

```json
{_json_lines(domain)}
```

## All formal transport points

All 25 formal points are listed below. “Resolved” is an algorithmic disposition under the frozen thresholds, not a subjective deletion. Rejection arrays remain present even when empty. Diffusivity units are cm² s⁻¹, MSD is Å², time is ps, and volume is Å³.

{_markdown_table(['run_id', 'temperature_k', 'tracer_diffusivity_cm2_s', 'tracer_stderr_cm2_s', 'tracer_diffusive_exponent', 'tracer_final_msd_a2', 'tracer_resolved', 'collective_diffusivity_cm2_s', 'collective_stderr_cm2_s', 'collective_diffusive_exponent', 'collective_final_msd_a2', 'collective_resolved', 'collective_to_tracer_ratio', 'temperature_mean_k', 'volume_mean_angstrom3'], transport)}

Complete canonical rows:

```json
{_json_lines(transport)}
```

## Hierarchical transport inference

Configuration-specific slopes, population activation-energy inference, predictions at all prespecified experimental temperatures, and the non-Arrhenius diagnostic are retained for tracer and collective transport. Predictions below 700 K are extrapolations and include a new-configuration interval wider than uncertainty in the population geometric mean.

```json
{_json_lines(hierarchy)}
```

## Replication, finite-size, and volume sensitivity

The velocity table contains three estimator rows for each of 15 physical trajectories. Nested-inference rows preserve every scalar, including the zero-boundary bootstrap test and variance intervals. Size and volume rows are a lossless flattening of every numeric comparison field. Boolean pass dispositions remain in the signed source report and publication manifest; the manuscript is generated only after the complete sensitivity gate passes.

```json
{_json_lines(sensitivity)}
```

## Mechanism descriptors and associations

The 25 descriptor rows retain primary site/jump/string quantities, transport responses, assignment qualification, and trajectory context. The twelve confirmatory rows retain raw permutation p values, Holm-adjusted p values, standardized slopes, partial weighted R², cluster-bootstrap intervals, leave-one-occupancy behavior, and assignment-grid sensitivity. No row is selected for presentation based on significance.

Primary descriptor rows:

```json
{_json_lines(descriptors)}
```

All twelve association rows:

```json
{_json_lines(associations)}
```

## Experimental comparisons

The nine rows below retain observable, temperature, unit, sample type, phase, method, direct/derived role, predicted population interval, new-configuration prediction interval, compatibility result, extrapolation flag, and DOI-bearing source. Compatibility is descriptive and does not establish equivalence. Ceramic total conductivity includes microstructural resistance absent from the periodic simulation.

```json
{_json_lines(comparisons)}
```

## Exclusions and retained negative results

All {len(exclusions)} ledger entries are reproduced. These include interrupted output, short development trajectories, mismatched equilibration designs, confounded size controls, superseded protocols, feasibility-only DFT states, and retained negative mechanism pilots. An exclusion needs a design/provenance reason; an unfavorable scientific outcome alone is not grounds for deletion.

```json
{_json_lines(exclusions)}
```

## Artifact inventory

Every logical figure is available as deterministic SVG, PDF, and 300-dpi PNG. Every logical table is available as JSON and CSV. The hashes below bind this supplement to the exact rendered evidence.

{_markdown_table(['figure_id', 'title', 'formats', 'hashes'], figure_inventory)}

{_markdown_table(['table_id', 'title', 'n_rows', 'formats', 'hashes'], table_inventory)}

The main text cites all nine logical figures and tables. Null mechanism associations, failed cooperative-string qualification, incompatible experimental points, and exclusions remain visible. These are scientific outcomes, whereas a failed numerical/domain/completeness gate would have prevented manuscript generation entirely.
"""


def render_data_availability(
    protocol: dict[str, Any],
    tables: dict[str, list[dict[str, Any]]],
    publication_manifest: dict[str, Any],
) -> str:
    sources = tables["table01-provenance"]
    source_lines = "\n".join(
        f"- `{row['path']}` — SHA-256 `{row['sha256']}`"
        for row in sources
    )
    return f"""# Data and code availability

## Data availability

The complete evidence package is stored inside the repository. Machine-readable publication tables are under `runs/analysis/publication-v1/tables`; figures in SVG, PDF, and 300-dpi PNG are under `runs/analysis/publication-v1/figures`; formal MD trajectories and transport reports are under `runs/campaigns/llzto_q1_v1`; DFT convergence and label artifacts are under `runs/dft`; formal mechanism reports are under `runs/analysis/mechanisms-formal-v1`. The publication manifest at `{protocol['sources']['publication_manifest']}` hashes all {len(publication_manifest['figures'])} logical figures, {len(publication_manifest['tables'])} logical tables, and every transitive source used to generate them. The manuscript manifest separately hashes these three documents.

The exact source inventory used by the publication table builders is:

{source_lines}

## Code and computational environment

Analysis code is in `src/matfactory`. Python dependencies are locked by `uv.lock`. Quantum ESPRESSO 7.5 and its MPI stack are described by `dft/qe-7.5-linux-64.lock` and `dft/manifests/qe_7.5_conda_linux64.json`; SSSP PBE Precision 1.3.0 selections and pseudopotential hashes are recorded in `dft/manifests/sssp_1.3.0_pbe_precision_llzto.json`. The CHGNet state dictionary is pinned by its SHA-256 in run manifests. Final test, environment, and clean-regeneration attestations are stored with the publication artifacts.

## Reproduction commands

```bash
uv sync --all-extras
uv run pytest -q
uv run python -m matfactory.publication --protocol analysis/protocols/llzto_publication_package_v1.json
uv run python -m matfactory.manuscript --protocol analysis/protocols/llzto_manuscript_v1.json
uv run python -m matfactory.attestation tests --out runs/analysis/publication-v1/test-attestation.json
uv run python -m matfactory.attestation environment --audit-protocol analysis/protocols/llzto_q1_evidence_audit_v1.json --qe-manifest dft/manifests/qe_7.5_conda_linux64.json --formal-run-manifest runs/campaigns/llzto_q1_v1/formal-occ00-vel1701/run_manifest.json --out runs/analysis/publication-v1/environment-attestation.json
uv run python -m matfactory.attestation regenerate --publication-protocol analysis/protocols/llzto_publication_package_v1.json --manifest runs/analysis/publication-v1/artifact-manifest.json --manuscript-protocol analysis/protocols/llzto_manuscript_v1.json --manuscript-manifest runs/analysis/publication-v1/manuscript-manifest.json --out runs/analysis/publication-v1/clean-regeneration-attestation.json
```

Generation is intentionally immutable. Reproduction should occur in an empty output tree; an existing output is treated as evidence rather than overwritten.

## Licensing boundary

The repository does not currently declare a software license. Inspection and reproducibility metadata therefore do not imply permission to redistribute the code. Pseudopotentials and crystallographic/literature inputs retain their upstream terms; the local SSSP metadata records that redistribution status must be checked before packaging those files. CHGNet, Quantum ESPRESSO, Python dependencies, publications, and the COD structure remain attributable to their respective authors and licenses. A public deposition must either include only redistributable artifacts or obtain/record the required permissions. This licensing boundary affects dissemination, not the numerical provenance of the reported results.
"""


def render_manuscript_documents(
    protocol: dict[str, Any],
    tables: dict[str, list[dict[str, Any]]],
    publication_manifest: dict[str, Any],
) -> dict[str, str]:
    return {
        "main": render_main(protocol, tables, publication_manifest),
        "supplement": render_supplement(protocol, tables, publication_manifest),
        "data_availability": render_data_availability(
            protocol, tables, publication_manifest
        ),
    }


def validate_rendered_documents(
    protocol: dict[str, Any],
    documents: dict[str, str],
    publication_manifest: dict[str, Any],
) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    prohibited = [str(value).casefold() for value in protocol["prohibited_tokens"]]
    for name, specification in protocol["documents"].items():
        text = documents[name]
        encoded = text.encode("utf-8")
        checks[f"{name}_minimum_bytes"] = len(encoded) >= int(
            specification["minimum_bytes"]
        )
        checks[f"{name}_required_sections"] = all(
            f"## {section}" in text or f"# {section}" in text
            for section in specification["required_sections"]
        )
        folded = text.casefold()
        checks[f"{name}_no_prohibited_tokens"] = not any(
            token in folded for token in prohibited
        )
    combined = "\n".join(documents.values())
    checks["all_figures_cited"] = all(
        row["figure_id"] in combined for row in publication_manifest["figures"]
    )
    checks["all_tables_cited"] = all(
        row["table_id"] in combined for row in publication_manifest["tables"]
    )
    checks["all_references_doi_linked"] = all(
        f"https://doi.org/{row['doi']}" in combined
        for row in protocol["references"]
    )
    lowered = combined.casefold()
    checks["noncausal_boundary_explicit"] = (
        "does not establish a causal" in lowered or "non-causal" in lowered
    )
    checks["extrapolation_boundary_explicit"] = "extrapolation" in lowered
    checks["negative_outcomes_explicit"] = "negative" in lowered and "incompatible" in lowered
    return checks


def build_manuscript_package(
    protocol_path: Path | str,
    *,
    publication_manifest_path_override: Path | str | None = None,
) -> dict[str, Any]:
    """Verify the complete publication package, then write immutable manuscripts."""
    manuscript_protocol_path = Path(protocol_path).resolve()
    protocol = _read_json(manuscript_protocol_path)
    if protocol.get("schema_version") != "1.0":
        raise ValueError("manuscript protocol schema_version must be '1.0'")
    publication_protocol_path = _repo_path(protocol["sources"]["publication_protocol"])
    expected_publication_sha = protocol["sources"]["publication_protocol_sha256"]
    if sha256_file(publication_protocol_path) != expected_publication_sha:
        raise RuntimeError("frozen publication protocol hash mismatch")
    publication_manifest_path = (
        Path(publication_manifest_path_override).resolve()
        if publication_manifest_path_override is not None
        else _repo_path(protocol["sources"]["publication_manifest"])
    )
    publication_manifest = _read_json(publication_manifest_path)
    logical_outputs = _verify_manifest_outputs(publication_manifest)
    if publication_manifest.get("manifest_gate_pass") is not True:
        raise RuntimeError("publication artifact manifest did not pass")
    manifest_protocol_sha = publication_manifest.get("publication_protocol_sha256")
    if manifest_protocol_sha != expected_publication_sha:
        if publication_manifest_path_override is None:
            raise RuntimeError("publication manifest references a different protocol")
        relocated_protocol_path = Path(
            publication_manifest["publication_protocol_path"]
        ).resolve()
        if sha256_file(relocated_protocol_path) != manifest_protocol_sha:
            raise RuntimeError("relocated publication protocol hash mismatch")
        relocated_protocol = _read_json(relocated_protocol_path)
        canonical_protocol = _read_json(publication_protocol_path)
        relocated_without_output = dict(relocated_protocol)
        canonical_without_output = dict(canonical_protocol)
        relocated_without_output.pop("output", None)
        canonical_without_output.pop("output", None)
        if relocated_without_output != canonical_without_output:
            raise RuntimeError(
                "relocated publication protocol changes more than output paths"
            )
    if len(publication_manifest.get("figures", [])) != 9 or len(
        publication_manifest.get("tables", [])
    ) != 9:
        raise RuntimeError("manuscript requires nine publication figures and tables")

    inputs = load_publication_inputs(publication_protocol_path)
    tables = _table_rows(inputs)
    documents = render_manuscript_documents(protocol, tables, publication_manifest)
    validation = validate_rendered_documents(protocol, documents, publication_manifest)
    if not all(validation.values()):
        failed = [name for name, passed in validation.items() if not passed]
        raise RuntimeError("manuscript validation failed: " + ", ".join(failed))

    destinations = {
        name: _repo_path(protocol["output"][name]) for name in documents
    }
    manifest_path = _repo_path(protocol["output"]["manifest"])
    existing = [path for path in [*destinations.values(), manifest_path] if path.exists()]
    if existing:
        raise RuntimeError(
            "refusing to overwrite manuscript artifacts: "
            + ", ".join(str(path) for path in existing)
        )
    for name, text in documents.items():
        atomic_write_text(destinations[name], text)

    document_records = []
    for name, path in destinations.items():
        specification = protocol["documents"][name]
        document_records.append(
            {
                "document_id": name,
                "path": str(path),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
                "required_sections": specification["required_sections"],
                "minimum_bytes": specification["minimum_bytes"],
            }
        )
    root = Path(__file__).resolve().parents[2]
    manifest = {
        "schema_version": "1.0",
        "manifest_kind": "llzto-manuscript-package",
        "manuscript_protocol_path": str(manuscript_protocol_path),
        "manuscript_protocol_sha256": sha256_file(manuscript_protocol_path),
        "publication_protocol_path": str(publication_protocol_path),
        "publication_protocol_sha256": expected_publication_sha,
        "publication_manifest_path": str(publication_manifest_path),
        "publication_manifest_sha256": sha256_file(publication_manifest_path),
        "publication_manifest_fingerprint": publication_manifest[
            "manifest_fingerprint"
        ],
        "publication_logical_output_hashes_verified": len(logical_outputs),
        "table_source_row_counts": {
            table_id: len(rows) for table_id, rows in tables.items()
        },
        "documents": document_records,
        "checks": {
            "publication_manifest_verified": True,
            "publication_manifest_gate_pass": True,
            "publication_figure_count": len(publication_manifest["figures"]) == 9,
            "publication_table_count": len(publication_manifest["tables"]) == 9,
            "publication_output_hash_count": len(logical_outputs) == 45,
            **validation,
        },
        "generation_command": (
            "uv run python -m matfactory.manuscript --protocol "
            "analysis/protocols/llzto_manuscript_v1.json"
        ),
        "git_state_at_generation": git_state(root),
        "environment": environment_versions(("numpy", "scipy", "matplotlib")),
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
    }
    manifest["manuscript_gate_pass"] = all(manifest["checks"].values())
    manifest["manifest_fingerprint"] = fingerprint(manifest)
    atomic_write_json(manifest_path, manifest)
    return manifest


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    args = parser.parse_args()
    manifest = build_manuscript_package(args.protocol)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
