"""Render an outcome-aware LLZTO manuscript from the branch-isolated v2 tables."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .attestation import _verify_manifest_outputs
from .manuscript import _markdown_table, _number, _quantile_triplet
from .provenance import (
    atomic_write_json,
    atomic_write_text,
    environment_versions,
    fingerprint,
    git_state,
    sha256_file,
)


_ROOT = Path(__file__).resolve().parents[2]


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def _repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (_ROOT / path).resolve()


def _verify_fingerprint(payload: dict[str, Any], field: str, label: str) -> None:
    unsigned = dict(payload)
    stored = unsigned.pop(field, None)
    if stored != fingerprint(unsigned):
        raise RuntimeError(f"{label} fingerprint mismatch")


def _load_publication_tables(
    manifest: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    tables: dict[str, list[dict[str, Any]]] = {}
    for record in manifest["tables"]:
        table_id = str(record["table_id"])
        json_outputs = [
            row for row in record["outputs"] if row.get("format") == "json"
        ]
        if len(json_outputs) != 1:
            raise RuntimeError(f"table {table_id} has no unique JSON output")
        path = Path(json_outputs[0]["path"]).resolve()
        if sha256_file(path) != json_outputs[0]["sha256"]:
            raise RuntimeError(f"table JSON hash mismatch: {path}")
        payload = _read_json(path)
        _verify_fingerprint(payload, "table_fingerprint", table_id)
        rows = payload.get("rows")
        if (
            payload.get("table_id") != table_id
            or not isinstance(rows, list)
            or not rows
            or len(rows) != payload.get("n_rows")
        ):
            raise RuntimeError(f"table {table_id} payload is incomplete")
        tables[table_id] = rows
    expected = {f"table{index:02d}" for index in range(1, 13)}
    observed = {table_id.split("-", 1)[0] for table_id in tables}
    if len(tables) != 12 or observed != expected:
        raise RuntimeError("research manuscript requires tables 01 through 12")
    return tables


def _aggregate_domain_metrics(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    metric_names = {
        "n_snapshots",
        "centered_energy_mae_ev_atom",
        "centered_energy_rmse_ev_atom",
        "force_component_mae_ev_angstrom",
        "force_component_rmse_ev_angstrom",
        "stress_component_mae_gpa",
    }
    domains: dict[str, dict[str, float]] = {}
    for row in rows:
        if row.get("group_kind") != "aggregate" or row.get("metric") not in metric_names:
            continue
        domains.setdefault(str(row["set_id"]), {})[str(row["metric"])] = float(
            row["value"]
        )
    if not domains or any(set(values) != metric_names for values in domains.values()):
        raise RuntimeError("aggregate model-domain metrics are incomplete")
    return domains


def _activation_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    outputs = {
        str(row["estimator"]): row
        for row in rows
        if row.get("row_type") == "activation_energy_population"
    }
    if set(outputs) != {"tracer", "collective"}:
        raise RuntimeError("population activation-energy rows are incomplete")
    return outputs


def _prediction_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    outputs = {}
    for estimator in ("tracer", "collective"):
        candidates = [
            row
            for row in rows
            if row.get("row_type") == "temperature_prediction"
            and row.get("estimator") == estimator
        ]
        if not candidates:
            raise RuntimeError(f"missing {estimator} temperature prediction")
        outputs[estimator] = min(
            candidates, key=lambda row: abs(float(row["temperature_k"]) - 300.0)
        )
    return outputs


def summarize_research_outcomes(
    protocol: dict[str, Any],
    tables: dict[str, list[dict[str, Any]]],
    publication_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Build a compact narrative state without converting null results to failures."""
    branch = str(protocol["branch"])
    if branch != publication_manifest.get("branch"):
        raise RuntimeError("manuscript and publication model branches differ")
    domains = _aggregate_domain_metrics(tables["table03-domain-errors"])
    transports = tables["table04-formal-transport-points"]
    descriptors = tables["table07-mechanism-descriptors"]
    associations = tables["table08-mechanism-associations"]
    experiment_rows = tables["table09-experiment-and-exclusions"]
    experiments = [
        row for row in experiment_rows if row.get("row_type") == "experimental_comparison"
    ]
    exclusions = [
        row
        for row in experiment_rows
        if row.get("row_type") == "exclusion_or_negative_result"
    ]
    ensemble = tables["table10-production-ensemble"]
    temperature_robustness = tables["table11-temperature-robustness"]
    haven = tables["table12-haven-convention"]
    haven_prediction = [
        row for row in haven if row.get("row_type") == "experimental_prediction"
    ]
    if (
        len(transports) != 25
        or len(descriptors) != 25
        or len(associations) != 12
        or len(experiments) != 9
        or len(temperature_robustness) != 12
        or len(haven_prediction) != 1
        or len(exclusions) < 10
    ):
        raise RuntimeError("manuscript source grid or retained-outcome inventory is incomplete")
    if not all(
        row.get("tracer_resolved") is True
        and row.get("collective_resolved") is True
        for row in transports
    ):
        raise RuntimeError("unresolved formal transport cannot enter the manuscript")
    if not all(row.get("analysis_gate_pass") is True for row in associations):
        raise RuntimeError("unresolved primary mechanism association cannot enter the manuscript")
    if not all(
        row.get("analysis_gate_pass") is True for row in temperature_robustness
    ):
        raise RuntimeError("unresolved temperature robustness cannot enter the manuscript")
    activation = _activation_rows(tables["table05-hierarchical-arrhenius"])
    predictions = _prediction_rows(tables["table05-hierarchical-arrhenius"])
    prediction_intervals = {}
    for estimator, row in predictions.items():
        quantiles = row["new_configuration_predictive"][
            "diffusivity_cm2_s_quantiles"
        ]
        prediction_intervals[estimator] = _quantile_triplet(quantiles)
    supported_primary = [
        row for row in associations if row.get("association_supported") is True
    ]
    retained_temperature = [
        row
        for row in temperature_robustness
        if row.get("association_retained_after_temperature_robustness") is True
    ]
    outcome_flags = publication_manifest["scientific_outcome_flags"]
    return {
        "branch": branch,
        "branch_label": (
            "universal CHGNet"
            if branch == "universal"
            else "outcome-blind fine-tuned CHGNet"
        ),
        "domains": domains,
        "transport": {
            "n_points": len(transports),
            "n_configurations": len({row["run_id"] for row in transports}),
            "temperatures_k": sorted({int(row["temperature_k"]) for row in transports}),
            "tracer_range": [
                min(float(row["tracer_diffusivity_cm2_s"]) for row in transports),
                max(float(row["tracer_diffusivity_cm2_s"]) for row in transports),
            ],
            "collective_range": [
                min(float(row["collective_diffusivity_cm2_s"]) for row in transports),
                max(float(row["collective_diffusivity_cm2_s"]) for row in transports),
            ],
            "ratio_range": [
                min(float(row["collective_to_tracer_ratio"]) for row in transports),
                max(float(row["collective_to_tracer_ratio"]) for row in transports),
            ],
        },
        "activation": activation,
        "predictions": prediction_intervals,
        "primary_supported": supported_primary,
        "temperature_retained": retained_temperature,
        "experiments": experiments,
        "compatible_experiments": sum(
            row.get("compatible_with_simulation_prediction") is True
            for row in experiments
        ),
        "incompatible_experiments": sum(
            row.get("compatible_with_simulation_prediction") is False
            for row in experiments
        ),
        "exclusions": exclusions,
        "ensemble": ensemble,
        "temperature_robustness": temperature_robustness,
        "haven_prediction": haven_prediction[0],
        "outcome_flags": outcome_flags,
        "all_strings_robust": bool(
            all(
                row.get("mechanism_qualification", {}).get(
                    "cooperative_string_claim_supported_across_grid"
                )
                is True
                for row in descriptors
            )
        ),
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


def _domain_sentence(result: dict[str, Any]) -> str:
    fragments = []
    for set_id, metrics in sorted(result["domains"].items()):
        fragments.append(
            f"{set_id} (n={int(metrics['n_snapshots'])}) gave centered-energy "
            f"MAE/RMSE {_number(1000 * metrics['centered_energy_mae_ev_atom'])}/"
            f"{_number(1000 * metrics['centered_energy_rmse_ev_atom'])} meV atom⁻¹, "
            f"force-component MAE/RMSE {_number(metrics['force_component_mae_ev_angstrom'])}/"
            f"{_number(metrics['force_component_rmse_ev_angstrom'])} eV Å⁻¹, and "
            f"stress-component MAE {_number(metrics['stress_component_mae_gpa'])} GPa"
        )
    return "; ".join(fragments) + "."


def _outcome_sentence(flag: bool, positive: str, negative: str) -> str:
    return positive if flag else negative


def render_main(
    protocol: dict[str, Any],
    tables: dict[str, list[dict[str, Any]]],
    publication_manifest: dict[str, Any],
) -> str:
    result = summarize_research_outcomes(protocol, tables, publication_manifest)
    transport = result["transport"]
    tracer_prediction = result["predictions"]["tracer"]
    collective_prediction = result["predictions"]["collective"]
    primary_count = len(result["primary_supported"])
    retained_count = len(result["temperature_retained"])
    flags = result["outcome_flags"]
    branch = result["branch"]
    model = protocol["model_branch"]
    domain_text = _domain_sentence(result)
    if branch == "universal":
        branch_design = (
            "The pretrained universal CHGNet model was evaluated without parameter "
            "updates. A 12-structure feasibility set was development-only, whereas a "
            "disjoint 30-structure publication-heldout set alone authorized the formal "
            "transport branch. Neither set was selected after inspecting model error."
        )
        branch_result = (
            "The universal-domain route passed its frozen development and independent "
            "publication tests, so every reported trajectory uses the unchanged universal "
            "state dictionary."
        )
    else:
        training_records = int(model.get("training_records", 62))
        heldout_records = int(model.get("fresh_heldout_records", 30))
        branch_design = (
            "The preregistered universal-domain test failed before publication release and "
            "was retained as a negative model-selection result. That outcome triggered an "
            f"outcome-blind transfer-learning contingency with {training_records} LLZTO "
            "development labels, early-layer freezing, an exact-composition reference-energy "
            f"alignment, and a fresh {heldout_records}-structure publication-heldout test "
            "that was never read during training or hyperparameter selection."
        )
        branch_result = (
            "Only the independently accepted fine-tuned model was used here. All formal, "
            "nested-velocity, matched-size, fixed-volume, NPT-volume, NVE-ensemble, and "
            "mechanism trajectories were rerun from branch-specific hashed structures; no "
            "universal-model trajectory contributes to a fine-tuned estimator."
        )
    size_sentence = _outcome_sentence(
        flags["size_volume_robustness_supported"] is True,
        "All matched finite-size, fixed-volume, and NPT-volume equivalence intervals stayed inside their preregistered margins for the tested designs.",
        "At least one complete matched size or volume comparison was non-equivalent; this negative physical outcome narrows the quantitative claim to the reported cell and volume design instead of invalidating computational completeness.",
    )
    ensemble_sentence = _outcome_sentence(
        flags["production_ensemble_robustness_supported"] is True,
        "The matched 500 ps NVE/NVT comparison supported production-ensemble equivalence for tracer, collective, and ratio estimators while the NVE stability checks passed.",
        "The NVE trajectory passed the frozen stability checks, but at least one complete NVE/NVT estimator comparison was non-equivalent; this is retained as production-ensemble sensitivity and forbids an ensemble-invariant transport claim.",
    )
    haven_sentence = _outcome_sentence(
        flags["haven_experimental_compatibility"] is True,
        "After explicitly mapping reciprocal conventions, the experimental Haven point lay inside the new-configuration predictive interval.",
        "After explicitly mapping reciprocal conventions, the experimental Haven point lay outside the new-configuration predictive interval; this incompatibility is reported rather than removed.",
    )
    mechanism_sentence = (
        f"The preregistered primary family supported {primary_count} of 12 associations; "
        f"{retained_count} remained supported after an arbitrary categorical-temperature "
        "adjustment, Holm correction, occupancy-cluster bootstrap, and leave-one-occupancy-out "
        "sign check. "
        + (
            "These retained associations are descriptive and do not establish a causal elementary mechanism."
            if retained_count
            else "The complete null or downgraded family is a negative result and does not establish a causal elementary mechanism."
        )
    )
    string_sentence = (
        "Cooperative-string qualification was stable for all 25 formal trajectories across the frozen assignment grid."
        if result["all_strings_robust"]
        else "Cooperative-string qualification was not stable across all 25 trajectories and the formal string claim was therefore withheld."
    )
    figure_ids = ", ".join(row["figure_id"] for row in publication_manifest["figures"])
    table_ids = ", ".join(row["table_id"] for row in publication_manifest["tables"])
    references = "\n".join(
        f"{index}. {row['citation']} https://doi.org/{row['doi']}"
        for index, row in enumerate(protocol["references"], start=1)
    )
    return f"""# Configuration-resolved tracer and collective lithium transport in exact-composition LLZTO under an auditable model-domain and uncertainty chain

## Abstract

Solid-electrolyte transport is frequently compressed into one diffusion coefficient even though configuration, stochastic initialization, cell size, volume, production ensemble, and many-ion correlation can alter the observable. We construct an outcome-aware evidence chain for exact-composition Li6.5La3Zr1.5Ta0.5O12 (LLZTO) from model-blind Quantum ESPRESSO convergence and an independently tested {result['branch_label']} potential to 500 ps tracer and collective transport, replicated uncertainty, jump descriptors, and like-for-like experiments. {branch_result} Five independently ordered occupancy realizations were evaluated at {', '.join(str(value) for value in transport['temperatures_k'])} K, yielding {transport['n_points']} resolved tracer and collective points. Tracer diffusivities spanned {_number(transport['tracer_range'][0])}–{_number(transport['tracer_range'][1])} cm² s⁻¹, collective diffusivities {_number(transport['collective_range'][0])}–{_number(transport['collective_range'][1])} cm² s⁻¹, and Dcollective/Dtracer {_number(transport['ratio_range'][0])}–{_number(transport['ratio_range'][1])}. At 300 K, the new-configuration tracer extrapolation was {_number(tracer_prediction[1])} cm² s⁻¹ (95% predictive interval {_number(tracer_prediction[0])}–{_number(tracer_prediction[2])}); the collective extrapolation was {_number(collective_prediction[1])} cm² s⁻¹ ({_number(collective_prediction[0])}–{_number(collective_prediction[2])}). {size_sentence} {ensemble_sentence} {mechanism_sentence} Exact-composition comparisons placed {result['compatible_experiments']} of nine measurements inside and {result['incompatible_experiments']} outside new-configuration intervals. {haven_sentence} The contribution is the integrated separation and audit of these uncertainty levels, not a claim that one favorable trajectory, one association, or one potential is universally predictive.

## Introduction

Garnet solid electrolytes are attractive because a mechanically robust oxide can in principle combine lithium-ion transport with compatibility against high-voltage cathodes. LLZO-based materials nevertheless exhibit an unusually wide spread of reported conductivity and diffusivity. Composition, dopant distribution, lithium/vacancy ordering, phase fraction, grain boundaries, porosity, secondary phases, thermal history, and electrode contact all contribute. Even for a fixed nominal formula, a periodic ordered model samples only one microscopic realization of a disordered material. A calculated number can therefore be precise while its target population remains poorly defined.

Machine-learned interatomic potentials extend accessible trajectories from the picosecond regime toward times on which diffusive behavior can be diagnosed. CHGNet supplies a broadly trained charge-informed representation, but its universality is a hypothesis to be tested for a particular chemical and thermodynamic domain, not a substitute for reference calculations. Previous work has already examined lithium concentration and site occupancy, strain, many-ion correlations, reverse jumps, diffusion strings, and configurational search in LLZO. We consequently do not claim novelty for using machine-learning molecular dynamics, computing LLZO diffusion, enumerating occupancy patterns, or plotting a Haven-type ratio in isolation.

The unresolved methodological and physical question is whether an exact-composition diffraction model can be connected to tracer and collective transport without collapsing distinct sources of uncertainty. Three separations are central. First, numerical convergence of the independent electronic-structure reference must precede inspection of potential error. Second, potential-development information must remain separate from a publication-heldout domain. Third, trajectory-level uncertainty, stochastic velocity variation, occupancy variation, cell/volume sensitivity, and extrapolation to a new configuration are not interchangeable. Treating a temperature point as an independent configuration would exaggerate inferential sample size; treating a failed equivalence interval as missing data would erase a potentially important physical result.

Here we implement a frozen gate structure that preserves both favorable and unfavorable outcomes. Tracer and collective mean-squared displacements are resolved separately. Five configurations form the population unit for a hierarchical Arrhenius analysis, while a balanced 5 × 3 occupancy-by-velocity design addresses initialization sensitivity at 800 K. Exact matched controls test finite size, fixed experimental volume, thermal volume, and NVE versus NVT production. Site assignment, jump rate, reverse pairs, strings, and Dcollective/Dtracer enter a single multiplicity-controlled association family, followed by a categorical-temperature robustness audit. Finally, nine exact-composition measurements and an explicitly convention-mapped Haven benchmark are compared descriptively. This design makes a complete negative result publishable while reserving hard failure for missing provenance, unresolved estimators, numerical instability, or model-domain failure without an independently validated fallback.

## Methods

### Structure, disorder, and model branch

The atomistic composition was fixed at Li6.5La3Zr1.5Ta0.5O12. Ordered lithium/vacancy and Zr/Ta assignments were generated from the diffraction-compatible parent structure with deterministic occupancy seeds. Each primary configuration was relaxed under the same accepted model branch before dynamics. Replication controls reuse the exact hashed primary relaxed structure or a declared determinant-two periodic supercell so that a nominal size or velocity comparison cannot silently change chemical ordering.

{branch_design}

{branch_result} The model identity, state-dictionary hash, model artifact when applicable, campaign protocol, relaxed structure, trajectory, and downstream report are linked transitively. The exclusion ledger records all development-only, interrupted, superseded, cross-branch, and retained-negative material. A scientific result is never excluded merely because it is inconvenient.

### Independent DFT convergence and potential-domain testing

Quantum ESPRESSO cutoff, k-point, self-consistent-field tolerance, and MPI-rank equivalence were evaluated with model-blind thresholds for relative energies, forces, and stresses. Absolute CHGNet and DFT energy zeros were not compared. Domain testing used centered relative-energy error, force-component and force-vector errors, stress-component error, rank correlation, element-resolved forces, temperature and occupancy strata, and per-snapshot outlier rules. The frozen aggregate limits were 15 meV atom⁻¹ centered-energy MAE, 0.10 eV Å⁻¹ force-component MAE, 0.20 eV Å⁻¹ force-component RMSE, and 0.25 GPa stress-component MAE. A passing average could not conceal a failed stratum or outlier. Domain parity and every source label are shown in fig03-chgnet-dft-domain and table03-domain-errors; numerical decisions are in fig02-dft-numerical-convergence and table02-dft-convergence.

### Molecular dynamics and transport estimands

Each of five occupancy realizations was simulated for 500 ps at 700, 750, 800, 850, and 900 K after matched equilibration. The saved-frame interval was 0.1 ps. A separate 1 fs/2 fs NVE comparison selected the production time step only when the absolute total-energy drift met its frozen limit. Tracer diffusion was estimated from the mean individual lithium displacement. Collective diffusion was estimated from the squared displacement of the summed lithium displacement vector with the normalization stated in the protocol. Their dimensionless ratio is denoted Rσ = Dcollective/Dtracer; this definition is carried explicitly and is not called a bare Haven ratio.

Fit windows were selected under preregistered diffusive-exponent, minimum-MSD, positive-block, relative-uncertainty, temperature, and structural-stability rules. All points had to resolve independently for both estimators. Figure fig04-all-msd-diagnostics retains every MSD curve and fit window; table04-formal-transport-points contains all point estimates, uncertainty, exponents, and diagnostic status. No unresolved point may enter the Arrhenius hierarchy.

### Hierarchical uncertainty and robustness controls

Arrhenius fits were first performed within configuration. Population inference then treated the five configurations—not 25 temperature points—as the independent units, reporting a mean activation energy, confidence interval, heterogeneity, and a new-configuration prediction interval. Nested configuration bootstrap propagates point uncertainty and between-configuration dispersion into temperature predictions. Values near 300 K are labelled extrapolations because the fitted range is 700–900 K. Figure fig05-hierarchical-arrhenius and table05-hierarchical-arrhenius report the full hierarchy.

A crossed 5 × 3 design at 800 K separates occupancy and initial-velocity variance for tracer, collective, and Rσ. Exact matched comparisons test 94 versus 188 atoms, the experimental fixed volume, an NPT-derived thermal volume, and NVE versus NVT production. Equivalence is defined by frozen ratio or activation-energy margins; it is not inferred from a nonsignificant difference. A computed interval outside a margin is a physical sensitivity result, whereas an unestimable interval is a completeness failure. These controls appear in fig06-nested-velocity, fig07-size-and-volume-sensitivity, fig10-production-ensemble, table06-replication-and-sensitivity, and table10-production-ensemble.

### Mechanism associations and experimental comparison

Lithium positions were assigned to a deterministic crystallographic site model. Residence, transition, jump-rate, reverse-pair, and string descriptors were recomputed over a frozen assignment-sensitivity grid. Four primary descriptors were related to log tracer diffusion, log collective diffusion, and log Rσ, producing one family of 12 tests. Support required an analyzable weighted fit, Holm-adjusted permutation probability, an occupancy-cluster-bootstrap interval excluding zero, stable leave-one-occupancy-out sign, and assignment-setting sensitivity. A second model adjusted for temperature as an arbitrary categorical effect. These procedures quantify association and do not establish a causal elementary mechanism. Figure fig08-mechanisms-and-haven-relation, fig11-temperature-robustness, table07-mechanism-descriptors, table08-mechanism-associations, and table11-temperature-robustness retain the full grid and null outcomes.

Nine exact-composition literature measurements were compared with the corresponding tracer, conductivity-derived collective, or activation-energy estimand. Direct and derived quantities, sample type, scope notes, and extrapolation status remain visible. Compatibility means only that an experimental point lies inside the new-configuration prediction interval; it is not a goodness-of-fit test and does not make a periodic crystal representative of ceramic microstructure. The experimental Haven definition HR = Dtracer/Dsigma was mapped to the reciprocal simulation convention Rσ = Dcollective/Dtracer before comparison. Figure fig09-experiment-comparison, fig12-haven-convention, table09-experiment-and-exclusions, and table12-haven-convention report these results.

## Results

### Numerical and model-domain evidence

All three numerical decisions and the MPI equivalence audit passed their frozen energy, force, and stress criteria. {domain_text} These results authorize only the sampled exact-composition LLZTO state domain and do not demonstrate an exhaustive reactive landscape. {branch_result}

### Configuration-resolved tracer and collective transport

All {transport['n_points']} formal points across {transport['n_configurations']} configurations resolved under the frozen tracer and collective checks. Tracer diffusion ranged from {_number(transport['tracer_range'][0])} to {_number(transport['tracer_range'][1])} cm² s⁻¹; collective diffusion ranged from {_number(transport['collective_range'][0])} to {_number(transport['collective_range'][1])} cm² s⁻¹; Rσ ranged from {_number(transport['ratio_range'][0])} to {_number(transport['ratio_range'][1])}. {_activation_sentence('tracer', result['activation']['tracer'])} {_activation_sentence('collective', result['activation']['collective'])}

The 300 K tracer new-configuration median was {_number(tracer_prediction[1])} cm² s⁻¹ with a 95% interval of {_number(tracer_prediction[0])}–{_number(tracer_prediction[2])}. The corresponding collective median was {_number(collective_prediction[1])} cm² s⁻¹ with {_number(collective_prediction[0])}–{_number(collective_prediction[2])}. Both are long Arrhenius extrapolations and are not direct room-temperature simulations.

### Replication, size, volume, and ensemble sensitivity

{size_sentence} {ensemble_sentence} The balanced velocity analysis remains a variance decomposition at 800 K rather than an assertion that five ordered configurations are a thermodynamic ensemble. Complete negative equivalence outcomes remain in the figures and tables and directly determine the scope of the numerical claim.

### Mechanisms, correlations, and experiments

{mechanism_sentence} {string_sentence} The distinction between primary support and survival under categorical-temperature adjustment prevents a smooth shared temperature trend from being presented as mechanism evidence. Likewise, assignment-grid sensitivity prevents a result that depends on one site cutoff or string window from becoming a robust claim.

Of nine exact-composition measurements, {result['compatible_experiments']} were inside and {result['incompatible_experiments']} were incompatible with the corresponding new-configuration prediction intervals. Compatibility is descriptive. {haven_sentence} The reciprocal mapping was performed before interval comparison, eliminating the common ambiguity in which both Dsigma/Dtracer and Dtracer/Dsigma are labelled a Haven ratio.

## Discussion

The results demonstrate why configuration-resolved tracer and collective inference is more informative than a single nominal LLZTO conductivity. Between-configuration dispersion affects the target interval for an unseen ordering, while initial-velocity dispersion affects repeated trajectories from the same ordering. These are different uncertainties and cannot be recovered by treating temperatures as replicates. Rσ adds a many-ion correlation observable, but its microscopic interpretation still depends on robust trajectory descriptors and cannot be inferred from a ratio alone.

The strongest claim supported by this workflow is conditional: within the independently accepted {result['branch_label']} domain, the five frozen occupancy realizations and declared production design yield a fully resolved joint account of individual and collective lithium motion. {size_sentence} {ensemble_sentence} Thus a failed robustness comparison, if present, does not disappear behind a completeness label; it narrows transfer from the primary cell, volume, or ensemble.

Mechanism inference is deliberately conservative. A primary association must survive family-wise multiplicity control and configuration-level resampling, and its sign must remain stable when one occupancy is removed. The categorical-temperature audit then asks whether the association survives without imposing a linear Arrhenius temperature form. {mechanism_sentence} This is stronger evidence discipline than selecting a visually persuasive descriptor after inspecting 25 correlated temperature points, but it still does not identify a causal transition pathway.

Experimental comparison also has a restricted interpretation. The simulations represent periodic bulk crystals, whereas ceramic measurements include grain boundaries, pores, interfaces, electrodes, and processing history; even single crystals can differ in defects and local dopant order. A point outside a predictive interval may signal missing microstructure, an imperfect potential or extrapolation, or a genuinely different configuration population. A point inside does not validate all those omitted factors. The explicit direct/derived labels, scope notes, and Haven convention therefore matter as much as the compatibility count.

Limitations include five rather than a thermodynamically sampled distribution of orderings, classical nuclei, a 700–900 K fitting window, limited power for non-Arrhenius behavior, finite periodic cells, and a potential-domain test that samples rather than exhausts LLZTO phase space. The fine-tuned branch, if selected, additionally demonstrates local transfer learning rather than universality. The universal branch, if selected, demonstrates only in-domain adequacy of the unchanged model. Neither branch establishes grain-boundary or interfacial transport. A complete audited package also cannot guarantee journal placement; importance depends on the magnitude and robustness of the final outcomes relative to current literature.

## Conclusions

We completed a branch-isolated, hash-audited chain from exact-composition LLZTO structure and model-blind DFT convergence through potential-domain testing, {transport['n_points']} resolved formal tracer/collective points, configuration and velocity uncertainty, matched size/volume/ensemble controls, mechanism robustness, and exact-composition experiments. Negative non-equivalence, null association, downgraded mechanism support, and incompatible experiments are retained as outcomes; only unresolved or provenance-invalid evidence blocks completion. The resulting claim is not a universal LLZTO diffusivity and not causal mechanism identification. It is a configuration-resolved uncertainty account of individual and collective lithium motion within a declared model and simulation domain.

## Data and code availability

The repository contains immutable protocols, source hashes, 12 logical figures in SVG/PDF/PNG, 12 logical tables in JSON/CSV, the manuscript package, environment and test attestations, a clean byte-identical regeneration attestation, and a declarative evidence audit. The canonical locations and reproduction commands are provided in the separate data-availability document. Every formal result is traceable to a branch-specific model identity and campaign protocol; universal and fine-tuned trajectories are never pooled.

For audit completeness, the logical figure identifiers are: {figure_ids}. The logical table identifiers are: {table_ids}.

## References

{references}
"""


def _selected_table(
    rows: list[dict[str, Any]], columns: list[str], *, limit: int | None = None
) -> str:
    selected = rows if limit is None else rows[:limit]
    return _markdown_table(columns, selected)


def render_supplement(
    protocol: dict[str, Any],
    tables: dict[str, list[dict[str, Any]]],
    publication_manifest: dict[str, Any],
) -> str:
    result = summarize_research_outcomes(protocol, tables, publication_manifest)
    dft = tables["table02-dft-convergence"]
    domain = tables["table03-domain-errors"]
    transport = tables["table04-formal-transport-points"]
    hierarchy = tables["table05-hierarchical-arrhenius"]
    sensitivity = tables["table06-replication-and-sensitivity"]
    descriptors = tables["table07-mechanism-descriptors"]
    associations = tables["table08-mechanism-associations"]
    experiment_exclusions = tables["table09-experiment-and-exclusions"]
    ensemble = tables["table10-production-ensemble"]
    temperature = tables["table11-temperature-robustness"]
    haven = tables["table12-haven-convention"]
    experiment = [
        row
        for row in experiment_exclusions
        if row.get("row_type") == "experimental_comparison"
    ]
    exclusions = [
        row
        for row in experiment_exclusions
        if row.get("row_type") == "exclusion_or_negative_result"
    ]
    domain_summary = []
    for set_id, values in sorted(result["domains"].items()):
        domain_summary.append(
            {
                "set_id": set_id,
                "n_snapshots": int(values["n_snapshots"]),
                "centered_energy_mae_mev_atom": 1000
                * values["centered_energy_mae_ev_atom"],
                "centered_energy_rmse_mev_atom": 1000
                * values["centered_energy_rmse_ev_atom"],
                "force_component_mae_ev_angstrom": values[
                    "force_component_mae_ev_angstrom"
                ],
                "force_component_rmse_ev_angstrom": values[
                    "force_component_rmse_ev_angstrom"
                ],
                "stress_component_mae_gpa": values[
                    "stress_component_mae_gpa"
                ],
            }
        )
    snapshot_domain = [
        row for row in domain if row.get("group_kind") == "snapshot"
    ]
    artifact_rows = []
    for kind in ("figures", "tables"):
        for artifact in publication_manifest[kind]:
            artifact_id = artifact[f"{kind[:-1]}_id"]
            for output in artifact["outputs"]:
                artifact_rows.append(
                    {
                        "kind": kind[:-1],
                        "artifact_id": artifact_id,
                        "format": output["format"],
                        "sha256": output["sha256"],
                    }
                )
    provenance = tables["table01-provenance"]
    return f"""# Supplementary information: branch-isolated LLZTO transport evidence

## Supplementary methods

This supplement is generated from the same hash-verified table payloads as the main text. The active model branch is **{result['branch']}**. Model identities are never pooled: the publication manifest, campaign protocol, per-run model state dictionary, relaxed structure, trajectory, transport report, mechanism report, and statistical reports form one transitive chain. The analysis manifest separates computational completeness from scientific favorability. Missing provenance, an unresolved tracer or collective estimator, a failed NVE stability test, or incomplete domain evidence blocks the package. A complete non-equivalence interval, null association, temperature-sensitive downgrade, or incompatible experimental point remains a reportable outcome.

The 25-point formal design crosses five occupancy configurations with 700, 750, 800, 850, and 900 K. Each point uses 500 ps of production. A balanced 5 × 3 occupancy-by-velocity grid at 800 K separates stochastic initialization from configuration dispersion. Matched finite-size, fixed-volume, NPT-volume, and NVE/NVT controls change only their declared factor. The mechanism family contains four descriptors and three responses, with all 12 comparisons corrected together. Categorical-temperature robustness is a second frozen analysis, not an opportunity to select a preferred temperature parametrization after seeing the primary outcome.

## Numerical convergence

Table S1 reproduces all selected plane-wave cutoff, k-point, SCF, and MPI comparisons from table02-dft-convergence. A comparison is a computational gate and cannot be converted into a soft caveat. The selected settings were fixed before potential-domain scoring.

{_selected_table(dft, ['row_type', 'stage', 'comparison_index', 'passed', 'selected_comparison', 'lower_settings', 'upper_settings', 'energy_abs_change_mev_atom', 'force_component_max_abs_change_ev_angstrom', 'stress_component_max_abs_change_gpa'])}

## Potential-domain validation

Table S2 summarizes branch-specific aggregate errors. Development scope and publication scope remain distinct. In the universal branch, the feasibility set is development-only and the disjoint publication-heldout set authorizes claims. In the fine-tuned branch, the universal failure is retained separately and only the fresh fine-tuned publication-heldout set authorizes the rerun branch.

{_markdown_table(['set_id', 'n_snapshots', 'centered_energy_mae_mev_atom', 'centered_energy_rmse_mev_atom', 'force_component_mae_ev_angstrom', 'force_component_rmse_ev_angstrom', 'stress_component_mae_gpa'], domain_summary)}

Table S3 retains every snapshot-level numeric error leaf. The repeated snapshot identifier is intentional: each row is one metric, so an unfavorable component cannot be hidden by a reduced aggregate table.

{_selected_table(snapshot_domain, ['set_id', 'publication_claim_gate', 'domain_gate_pass', 'group_id', 'metric', 'value'])}

## All formal transport points

Table S4 lists all 25 tracer and collective estimates. Resolution requires both estimators, their uncertainty blocks, diffusive exponent and displacement criteria, stable temperature/structure diagnostics, and the frozen fit-window rules. The ratio is Rσ = Dcollective/Dtracer.

{_selected_table(transport, ['run_id', 'temperature_k', 'tracer_diffusivity_cm2_s', 'tracer_stderr_cm2_s', 'tracer_r2', 'tracer_diffusive_exponent', 'tracer_final_msd_a2', 'collective_diffusivity_cm2_s', 'collective_stderr_cm2_s', 'collective_r2', 'collective_diffusive_exponent', 'collective_final_msd_a2', 'collective_to_tracer_ratio', 'temperature_mean_k', 'volume_mean_angstrom3', 'minimum_distance_angstrom'])}

## Hierarchical transport inference

Table S5 reproduces configuration Arrhenius fits, population activation-energy meta-analysis, temperature predictions, and the non-Arrhenius diagnostic. Temperature predictions outside 700–900 K are extrapolations. The new-configuration interval includes between-occupancy dispersion and must not be replaced by a confidence interval for the mean.

{_selected_table(hierarchy, ['row_type', 'estimator', 'group_id', 'activation_energy_ev', 'activation_energy_stderr_ev', 'confidence_interval', 'prediction_interval', 'between_configuration_variance_tau2', 'i2_fraction', 'temperature_k', 'is_extrapolation', 'population_geometric_mean', 'new_configuration_predictive', 'non_arrhenius_supported'])}

## Replication, finite-size, volume, and ensemble sensitivity

Table S6 contains every numeric leaf of the nested velocity, matched size, fixed-volume, and NPT-volume reports. “analysis_gate_pass” answers whether an estimand exists; “equivalence_supported” answers a different scientific question. The latter may be false without making the former incomplete.

{_selected_table(sensitivity, ['row_type', 'run_id', 'occupancy_seed', 'velocity_seed', 'estimator', 'resolved', 'value', 'variance_log_value', 'metric', 'section'])}

Table S7 contains the matched NVE/NVT production comparison and the NVE stability diagnostics. A stable NVE trajectory is mandatory even if ensemble equivalence is not supported.

{_selected_table(ensemble, ['row_type', 'estimator', 'central_ratio', 'ratio_quantiles', 'equivalence_interval', 'equivalence_supported', 'analysis_gate_pass', 'total_energy_drift_mev_atom_ps', 'temperature_mean_k', 'stability_gate_pass', 'ensemble_robustness_gate_pass'])}

## Mechanism descriptors and associations

Table S8 lists the primary mechanism descriptors for all formal trajectories. Site populations, jumps, reverse pairs, and string statistics were derived under a deterministic site-model fingerprint and then audited over the frozen assignment grid.

{_selected_table(descriptors, ['run_id', 'occupancy_seed', 'temperature_k', 'volume_mean_angstrom3', 'log_jump_rate', 'tetrahedral_population_fraction', 'reverse_pair_fraction', 'string_excess', 'tracer_diffusivity_cm2_s', 'collective_diffusivity_cm2_s', 'collective_to_tracer_ratio', 'n_jumps', 'mechanism_qualification'])}

Table S9 retains all 12 primary association tests. Holm adjustment is over the complete family. Cluster bootstrap resamples occupancy, and leave-one-occupancy-out stability prevents one configuration from controlling the sign. Support remains non-causal.

{_selected_table(associations, ['response', 'descriptor', 'analysis_gate_pass', 'coefficient_per_sample_sd', 'partial_weighted_r2', 'permutation_p_value', 'holm_adjusted_p_value', 'cluster_bootstrap_quantiles', 'bootstrap_interval_excludes_zero', 'leave_one_occupancy_sign_stable', 'mechanism_setting_sign_stable', 'association_supported'])}

## Categorical-temperature robustness

Table S10 reports every primary association under an arbitrary categorical-temperature adjustment. A primary association is retained only if the adjusted family, cluster bootstrap, leave-one-occupancy-out sign, and primary-sign reconciliation all pass. A downgrade is a negative robustness result, not a missing test.

{_selected_table(temperature, ['response', 'descriptor', 'analysis_gate_pass', 'primary_association_supported', 'categorical_temperature_robustness_supported', 'association_retained_after_temperature_robustness', 'coefficient_per_original_sample_sd', 'holm_adjusted_p_value', 'cluster_bootstrap_interval', 'leave_one_occupancy_out_sign_stable', 'claim_disposition'])}

## Haven convention and experimental comparisons

Table S11 reports trajectory-level Rσ and the 298 K predictive comparison in both reciprocal conventions. The experimental quantity HR = Dtracer/Dsigma maps to 1/Rσ; neither convention is left implicit.

{_selected_table(haven, ['row_type', 'group_id', 'occupancy_seed', 'temperature_k', 'collective_to_tracer_ratio', 'variance_log_ratio', 'stderr_cm2_s', 'temperature_k', 'is_extrapolation', 'new_configuration_collective_to_tracer_quantiles', 'new_configuration_haven_Dtracer_over_Dsigma_quantiles', 'transformed_experimental_collective_to_tracer', 'reported_experimental_haven_Dtracer_over_Dsigma', 'compatible_with_new_configuration_prediction', 'reported_definition', 'reciprocal_relation'])}

Table S12 contains all nine exact-composition comparisons. Direct and derived roles, sample scope, new-configuration interval, and compatibility disposition are retained. The observed compatible/incompatible counts are {result['compatible_experiments']}/{result['incompatible_experiments']}.

{_selected_table(experiment, ['record_id', 'property', 'temperature_k', 'observed', 'predicted_population_median', 'new_configuration_prediction_interval', 'benchmark_role', 'sample_type', 'compatibility_assessment', 'compatible_with_simulation_prediction', 'scope_notes'])}

## Exclusions and retained negative results

Every ledger entry is reproduced below. Exclusion is permitted for design, provenance, branch identity, development-only use, interruption, or supersession—not for an unfavorable scientific result. Universal-domain failure, when present, is retained; universal trajectories never enter fine-tuned estimators; development/training labels never become the fresh publication test.

{_selected_table(exclusions, ['entry_id', 'disposition', 'scope', 'reason', 'identifiers', 'artifacts'])}

## Artifact inventory

The v2 package contains 12 logical figures in three formats and 12 logical tables in two formats, for 60 byte-hashed publication outputs. Table S13 records their logical identifiers and hashes.

{_markdown_table(['kind', 'artifact_id', 'format', 'sha256'], artifact_rows)}

Table S14 lists all transitive source records discovered from the reports. Paths are machine-local provenance; SHA-256 is the portable identity.

{_selected_table(provenance, ['source_id', 'path', 'sha256'])}
"""


def render_data_availability(
    protocol: dict[str, Any],
    tables: dict[str, list[dict[str, Any]]],
    publication_manifest: dict[str, Any],
) -> str:
    result = summarize_research_outcomes(protocol, tables, publication_manifest)
    locations = protocol["canonical_locations"]
    commands = protocol["reproduction_commands"]
    command_block = "\n".join(commands)
    return f"""# LLZTO research package: data and code availability

## Data availability

The active result branch is `{result['branch']}`. Machine-readable publication tables are stored under `{locations['tables']}` and figures under `{locations['figures']}`. The 25 formal transport trajectories and point reports are under `{locations['formal_campaign']}`; mechanism assignments are under `{locations['mechanisms']}`; model-blind DFT convergence and domain labels are under `runs/dft`. The publication manifest `{locations['publication_manifest']}` hashes 12 logical figures, 12 logical tables, and every transitive source discovered from their reports. The exclusion ledger retains interrupted, superseded, development-only, cross-model, and scientifically negative artifacts. Large trajectories are repository-local computational data and may require archival deposition before external submission.

## Code and computational environment

All scientific builders, frozen protocols, the Python dependency lock, the Quantum ESPRESSO explicit lock and executable manifest, model state-dictionary identities, GPU/runtime inventory, and branch-specific run manifests are included in the evidence chain. The environment attestation verifies the installed QE 7.5 executable, MPI record, CUDA-visible PyTorch runtime, Python lock, QE lock, campaign protocol, and exact model state dictionary. The test attestation runs the complete repository suite from a clean tracked commit. The clean-regeneration attestation rebuilds all 60 publication outputs and all three manuscript documents in a temporary directory and compares logical SHA-256 values byte for byte.

## Reproduction commands

Run from the repository root with the locked environment. The persistent supervisor chooses exactly one branch from the immutable research-analysis manifest; these commands do not authorize switching or pooling branches after viewing outcomes.

```bash
{command_block}
```

The canonical manuscript manifest is `{locations['manuscript_manifest']}`, the evidence audit is `{locations['evidence_audit']}`, and the preregistered readiness report is `{locations['readiness']}`. Room-temperature transport values in the manuscript are high-temperature Arrhenius extrapolations, not direct 300 K trajectories.

## Licensing boundary

Repository-authored code and generated text follow the repository license. Third-party CHGNet, PyTorch, ASE, pymatgen, Quantum ESPRESSO, pseudopotentials, and literature data retain their original licenses and citation requirements. A source hash proves identity but does not transfer redistribution rights. Before public deposition, verify licenses for model weights, pseudopotential files, diffraction inputs, and any publisher-supplied supplementary data. No acceptance, journal-quartile, or causal-mechanism guarantee is conveyed by availability of a complete package.
"""


def render_research_manuscript_documents(
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


def validate_research_manuscript_documents(
    protocol: dict[str, Any],
    documents: dict[str, str],
    publication_manifest: dict[str, Any],
) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    prohibited = [str(value).casefold() for value in protocol["prohibited_tokens"]]
    for name, specification in protocol["documents"].items():
        text = documents[name]
        checks[f"{name}_minimum_bytes"] = len(text.encode("utf-8")) >= int(
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
    lowered = combined.casefold()
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
    checks["noncausal_boundary_explicit"] = (
        "does not establish a causal" in lowered
        and "causal elementary mechanism" in lowered
    )
    checks["extrapolation_boundary_explicit"] = "arrhenius extrapolation" in lowered
    checks["negative_outcomes_explicit"] = (
        "negative" in lowered and "incompatible" in lowered
    )
    checks["branch_identity_explicit"] = (
        "universal chgnet" in lowered
        if protocol["branch"] == "universal"
        else "fine-tuned chgnet" in lowered and "universal-domain" in lowered
    )
    checks["complete_v2_inventory"] = bool(
        len(publication_manifest["figures"]) == 12
        and len(publication_manifest["tables"]) == 12
    )
    return checks


def _validate_relocated_publication_protocol(
    canonical_path: Path,
    candidate_path: Path,
    expected_canonical_sha: str,
) -> None:
    if sha256_file(canonical_path) != expected_canonical_sha:
        raise RuntimeError("canonical publication protocol hash mismatch")
    canonical = _read_json(canonical_path)
    candidate = _read_json(candidate_path)
    canonical_without_output = dict(canonical)
    candidate_without_output = dict(candidate)
    canonical_without_output.pop("output", None)
    candidate_without_output.pop("output", None)
    if canonical_without_output != candidate_without_output:
        raise RuntimeError("relocated publication protocol changes scientific content")


def build_research_manuscript_package(
    protocol_path: Path | str,
    *,
    publication_protocol_path_override: Path | str | None = None,
    publication_manifest_path_override: Path | str | None = None,
) -> dict[str, Any]:
    """Verify 60 publication outputs and write three immutable branch-aware documents."""
    source = Path(protocol_path).resolve()
    protocol = _read_json(source)
    if protocol.get("schema_version") != "1.0":
        raise ValueError("research manuscript protocol schema_version must be '1.0'")
    if protocol.get("branch") not in {"universal", "finetuned"}:
        raise ValueError("research manuscript branch must be universal or finetuned")
    canonical_publication_protocol = _repo_path(
        protocol["sources"]["publication_protocol"]
    )
    expected_publication_sha = protocol["sources"][
        "publication_protocol_sha256"
    ]
    publication_protocol = (
        Path(publication_protocol_path_override).resolve()
        if publication_protocol_path_override is not None
        else canonical_publication_protocol
    )
    if publication_protocol_path_override is None:
        if sha256_file(publication_protocol) != expected_publication_sha:
            raise RuntimeError("frozen research publication protocol hash mismatch")
    else:
        _validate_relocated_publication_protocol(
            canonical_publication_protocol,
            publication_protocol,
            expected_publication_sha,
        )
    publication_manifest_path = (
        Path(publication_manifest_path_override).resolve()
        if publication_manifest_path_override is not None
        else _repo_path(protocol["sources"]["publication_manifest"])
    )
    publication_manifest = _read_json(publication_manifest_path)
    logical_outputs = _verify_manifest_outputs(publication_manifest)
    if publication_manifest.get("manifest_gate_pass") is not True:
        raise RuntimeError("research publication manifest did not pass")
    if publication_manifest.get("branch") != protocol["branch"]:
        raise RuntimeError("publication and manuscript branches differ")
    if publication_manifest.get("publication_protocol_sha256") != sha256_file(
        publication_protocol
    ):
        raise RuntimeError("publication manifest references a different protocol")
    if (
        len(publication_manifest.get("figures", [])) != 12
        or len(publication_manifest.get("tables", [])) != 12
        or len(logical_outputs) != 60
    ):
        raise RuntimeError("research manuscript requires exactly 60 v2 publication outputs")
    tables = _load_publication_tables(publication_manifest)
    documents = render_research_manuscript_documents(
        protocol, tables, publication_manifest
    )
    validation = validate_research_manuscript_documents(
        protocol, documents, publication_manifest
    )
    if not all(validation.values()):
        failed = [name for name, passed in validation.items() if not passed]
        raise RuntimeError("research manuscript validation failed: " + ", ".join(failed))

    destinations = {
        name: _repo_path(protocol["output"][name]) for name in documents
    }
    manifest_path = _repo_path(protocol["output"]["manifest"])
    existing = [path for path in [*destinations.values(), manifest_path] if path.exists()]
    if existing:
        raise RuntimeError(
            "refusing to overwrite research manuscript artifacts: "
            + ", ".join(str(path) for path in existing)
        )
    for name, text in documents.items():
        atomic_write_text(destinations[name], text)
    document_records = [
        {
            "document_id": name,
            "path": str(path),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
            "required_sections": protocol["documents"][name]["required_sections"],
            "minimum_bytes": protocol["documents"][name]["minimum_bytes"],
        }
        for name, path in destinations.items()
    ]
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "manifest_kind": "llzto-research-manuscript-package-v2",
        "branch": protocol["branch"],
        "manuscript_protocol_path": str(source),
        "manuscript_protocol_sha256": sha256_file(source),
        "publication_protocol_path": str(publication_protocol),
        "publication_protocol_sha256": sha256_file(publication_protocol),
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
            "publication_figure_count": len(publication_manifest["figures"]) == 12,
            "publication_table_count": len(publication_manifest["tables"]) == 12,
            "publication_output_hash_count": len(logical_outputs) == 60,
            **validation,
        },
        "generation_command": protocol["generation_command"],
        "git_state_at_generation": git_state(_ROOT),
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
    result = build_research_manuscript_package(args.protocol)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
