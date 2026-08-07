"""Configuration-level hierarchical transport and Arrhenius inference."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .mlipmd import K_B_EV
from .provenance import atomic_write_json, fingerprint, sha256_file


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def _fit_wls_log_arrhenius(points: list[dict[str, Any]]) -> dict[str, Any]:
    """Fit log(D) = log(D0) - Ea/(k_B T) with declared point errors."""
    if len(points) < 3:
        raise ValueError("configuration Arrhenius fit requires at least three points")
    temperatures = np.asarray([float(item["temperature_k"]) for item in points])
    diffusion = np.asarray([float(item["diffusivity_cm2_s"]) for item in points])
    stderr = np.asarray([float(item["stderr_cm2_s"]) for item in points])
    if len(set(temperatures.tolist())) != len(points):
        raise ValueError("configuration contains duplicate temperatures")
    if np.any(temperatures <= 0) or np.any(diffusion <= 0) or np.any(stderr <= 0):
        raise ValueError("temperature, diffusivity, and stderr must all be positive")
    if any(item.get("resolved") is not True for item in points):
        raise ValueError("unresolved point blocks the configuration Arrhenius fit")

    x = 1.0 / (K_B_EV * temperatures)
    y = np.log(diffusion)
    sigma_y = stderr / diffusion
    design = np.column_stack([np.ones(len(points)), -x])
    weights = 1.0 / sigma_y**2
    information = design.T @ (weights[:, None] * design)
    covariance_unscaled = np.linalg.inv(information)
    parameters = covariance_unscaled @ (design.T @ (weights * y))
    prediction = design @ parameters
    residual = y - prediction
    chi_square = float(np.sum((residual / sigma_y) ** 2))
    dof = len(points) - 2
    reduced_chi_square = chi_square / dof if dof > 0 else float("nan")
    covariance_scale = max(1.0, reduced_chi_square) if dof > 0 else 1.0
    covariance = covariance_unscaled * covariance_scale
    total = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(np.sum(residual**2)) / total if total > 0 else 0.0
    return {
        "activation_energy_ev": float(parameters[1]),
        "activation_energy_stderr_ev": float(math.sqrt(covariance[1, 1])),
        "log_prefactor_cm2_s": float(parameters[0]),
        "prefactor_cm2_s": float(math.exp(parameters[0])),
        "parameter_covariance": covariance.tolist(),
        "r2_log_d": r2,
        "chi_square": chi_square,
        "reduced_chi_square": reduced_chi_square,
        "n_points": len(points),
        "temperature_range_k": [int(temperatures.min()), int(temperatures.max())],
        "method": "weighted_least_squares_log_d_delta_uncertainty",
    }


def reml_random_effects_meta(
    values: list[float], variances: list[float], *, confidence_level: float = 0.95
) -> dict[str, Any]:
    """REML random-effects mean with a modified Hartung-Knapp interval."""
    from scipy.optimize import minimize_scalar
    from scipy.stats import t

    y = np.asarray(values, dtype=float)
    variance = np.asarray(variances, dtype=float)
    if len(y) < 3 or variance.shape != y.shape:
        raise ValueError("random-effects meta-analysis needs three matched estimates")
    if np.any(~np.isfinite(y)) or np.any(~np.isfinite(variance)) or np.any(variance <= 0):
        raise ValueError("meta-analysis inputs must be finite with positive variances")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be inside (0,1)")

    def objective(tau2: float) -> float:
        total = variance + tau2
        weights = 1.0 / total
        mean = float(np.sum(weights * y) / np.sum(weights))
        q = float(np.sum(weights * (y - mean) ** 2))
        return 0.5 * (float(np.sum(np.log(total))) + math.log(float(np.sum(weights))) + q)

    upper = max(1.0, float(np.var(y, ddof=1) * 100), float(np.max(variance) * 100))
    optimized = minimize_scalar(
        objective,
        bounds=(0.0, upper),
        method="bounded",
        options={"xatol": 1e-12},
    )
    if not optimized.success:
        raise RuntimeError("REML heterogeneity optimization failed")
    # ``bounded`` never evaluates the exact boundary. Comparing it explicitly
    # prevents a spurious positive heterogeneity estimate when REML is minimized
    # at tau^2=0, which is common with only five configurations.
    candidate = max(0.0, float(optimized.x))
    tau2 = 0.0 if objective(0.0) <= objective(candidate) else candidate
    weights = 1.0 / (variance + tau2)
    mean = float(np.sum(weights * y) / np.sum(weights))
    q = float(np.sum(weights * (y - mean) ** 2))
    df = len(y) - 1
    hk_scale = max(1.0, q / df)
    stderr = math.sqrt(hk_scale / float(np.sum(weights)))
    alpha = 1.0 - confidence_level
    critical = float(t.ppf(1.0 - alpha / 2.0, df=df))
    interval = [mean - critical * stderr, mean + critical * stderr]
    prediction_half_width = critical * math.sqrt(tau2 + stderr**2)
    typical_within = float(np.mean(variance))
    return {
        "n_configurations": len(y),
        "mean": mean,
        "stderr_modified_hartung_knapp": stderr,
        "confidence_level": confidence_level,
        "confidence_interval": interval,
        "prediction_interval": [
            mean - prediction_half_width,
            mean + prediction_half_width,
        ],
        "between_configuration_variance_tau2": tau2,
        "between_configuration_sd_tau": math.sqrt(tau2),
        "i2_fraction": tau2 / (tau2 + typical_within),
        "q_random_effects": q,
        "degrees_of_freedom": df,
        "method": "REML_modified_Hartung-Knapp",
    }


def _fixed_intercept_curvature(
    grouped: list[list[dict[str, Any]]],
    *,
    override_y: list[np.ndarray] | None = None,
) -> dict[str, Any]:
    group_count = len(grouped)
    x_values = np.concatenate(
        [
            1.0
            / (
                K_B_EV
                * np.asarray([float(item["temperature_k"]) for item in points])
            )
            for points in grouped
        ]
    )
    center = float(x_values.mean())
    rows_linear = []
    rows_quadratic = []
    ys = []
    sigmas = []
    for group_index, points in enumerate(grouped):
        group_y = (
            override_y[group_index]
            if override_y is not None
            else np.log(
                np.asarray([float(item["diffusivity_cm2_s"]) for item in points])
            )
        )
        for point_index, item in enumerate(points):
            x = 1.0 / (K_B_EV * float(item["temperature_k"])) - center
            indicators = [0.0] * group_count
            indicators[group_index] = 1.0
            rows_linear.append([*indicators, x])
            rows_quadratic.append([*indicators, x, x * x])
            ys.append(float(group_y[point_index]))
            sigmas.append(float(item["stderr_cm2_s"]) / float(item["diffusivity_cm2_s"]))
    y = np.asarray(ys)
    sigma = np.asarray(sigmas)
    weights = 1.0 / sigma**2

    def fit(rows: list[list[float]]) -> tuple[np.ndarray, float, float]:
        design = np.asarray(rows, dtype=float)
        information = design.T @ (weights[:, None] * design)
        parameters = np.linalg.solve(information, design.T @ (weights * y))
        chi_square = float(np.sum(((y - design @ parameters) / sigma) ** 2))
        n, k = design.shape
        aic = chi_square + 2 * k
        aicc = aic + 2 * k * (k + 1) / (n - k - 1) if n > k + 1 else float("inf")
        return parameters, chi_square, aicc

    linear_parameters, linear_chi2, linear_aicc = fit(rows_linear)
    quadratic_parameters, quadratic_chi2, quadratic_aicc = fit(rows_quadratic)
    return {
        "linear_chi_square": linear_chi2,
        "quadratic_chi_square": quadratic_chi2,
        "linear_aicc": linear_aicc,
        "quadratic_aicc": quadratic_aicc,
        "linear_minus_quadratic_aicc": linear_aicc - quadratic_aicc,
        "quadratic_coefficient": float(quadratic_parameters[-1]),
        "inverse_kbt_center": center,
        "linear_parameters": linear_parameters.tolist(),
        "quadratic_parameters": quadratic_parameters.tolist(),
    }


def analyze_hierarchical_estimator(
    records: list[dict[str, Any]],
    *,
    required_temperatures_k: list[int],
    bootstrap_iterations: int,
    bootstrap_seed: int,
    bootstrap_quantiles: list[float],
    room_temperature_k: float,
    confidence_level: float,
    curvature_aicc_improvement_min: float,
    prediction_temperatures_k: list[float] | None = None,
    compute_nernst_einstein_conductivity: bool = False,
) -> dict[str, Any]:
    """Analyze complete configuration grids without treating frames as replicates."""
    if bootstrap_iterations < 100:
        raise ValueError("hierarchical bootstrap needs at least 100 iterations")
    by_group: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_group.setdefault(str(record["group_id"]), []).append(record)
    if len(by_group) < 3:
        raise ValueError("hierarchical analysis requires at least three configurations")
    required = sorted(int(value) for value in required_temperatures_k)
    prediction_temperatures = sorted(
        {
            float(room_temperature_k),
            *(
                float(value)
                for value in (prediction_temperatures_k or [])
            ),
        }
    )
    if any(
        not math.isfinite(temperature) or temperature <= 0
        for temperature in prediction_temperatures
    ):
        raise ValueError("prediction temperatures must be finite and positive")
    grouped = []
    configuration_fits = []
    group_metadata = []
    group_contexts = []
    for group_id, points in sorted(by_group.items()):
        points = sorted(points, key=lambda item: int(item["temperature_k"]))
        actual = [int(item["temperature_k"]) for item in points]
        if actual != required:
            raise ValueError(f"configuration {group_id} does not have the complete grid")
        fit = _fit_wls_log_arrhenius(points)
        fit["group_id"] = group_id
        occupancies = {item.get("occupancy_seed") for item in points}
        velocities = {item.get("velocity_seed") for item in points}
        if len(occupancies) > 1 or len(velocities) > 1:
            raise ValueError(f"configuration {group_id} changes identity across temperature")
        fit["occupancy_seed"] = next(iter(occupancies))
        fit["velocity_seed"] = next(iter(velocities))
        configuration_fits.append(fit)
        group_metadata.append((fit["occupancy_seed"], fit["velocity_seed"]))
        mobile_counts = {item.get("n_mobile") for item in points}
        volumes = {item.get("volume_angstrom3") for item in points}
        if len(mobile_counts) > 1 or len(volumes) > 1:
            raise ValueError(f"configuration {group_id} changes density context")
        n_mobile = next(iter(mobile_counts))
        volume = next(iter(volumes))
        if compute_nernst_einstein_conductivity:
            if (
                not isinstance(n_mobile, (int, float))
                or not isinstance(volume, (int, float))
                or float(n_mobile) <= 0
                or float(volume) <= 0
            ):
                raise ValueError(
                    f"configuration {group_id} lacks a valid conductivity context"
                )
        group_contexts.append(
            {
                "group_id": group_id,
                "n_mobile": int(n_mobile) if n_mobile is not None else None,
                "volume_angstrom3": float(volume) if volume is not None else None,
            }
        )
        grouped.append(points)
    known_occupancies = [value[0] for value in group_metadata if value[0] is not None]
    if known_occupancies and len(set(known_occupancies)) != len(known_occupancies):
        raise ValueError("primary hierarchical groups repeat an occupancy realization")

    activation_meta = reml_random_effects_meta(
        [fit["activation_energy_ev"] for fit in configuration_fits],
        [fit["activation_energy_stderr_ev"] ** 2 for fit in configuration_fits],
        confidence_level=confidence_level,
    )
    curvature = _fixed_intercept_curvature(grouped)
    rng = np.random.default_rng(bootstrap_seed)
    group_count = len(grouped)
    activation_draws = np.empty(bootstrap_iterations)
    log_prefactor_draws = np.empty(bootstrap_iterations)
    room_log_d_draws = np.empty(bootstrap_iterations)
    quadratic_draws = np.empty(bootstrap_iterations)
    population_log_d_draws = np.empty(
        (bootstrap_iterations, len(prediction_temperatures))
    )
    new_configuration_log_d_draws = np.empty_like(population_log_d_draws)
    population_log_conductivity_draws = (
        np.empty_like(population_log_d_draws)
        if compute_nernst_einstein_conductivity
        else None
    )
    new_configuration_log_conductivity_draws = (
        np.empty_like(population_log_d_draws)
        if compute_nernst_einstein_conductivity
        else None
    )
    for iteration in range(bootstrap_iterations):
        sampled_indices = rng.integers(0, group_count, size=group_count)
        sampled_groups = [grouped[index] for index in sampled_indices]
        sampled_contexts = [group_contexts[index] for index in sampled_indices]
        sampled_y = []
        parameters = []
        for points in sampled_groups:
            diffusion = np.asarray(
                [float(item["diffusivity_cm2_s"]) for item in points]
            )
            sigma_y = np.asarray(
                [float(item["stderr_cm2_s"]) for item in points]
            ) / diffusion
            y = rng.normal(np.log(diffusion), sigma_y)
            sampled_y.append(y)
            temperatures = np.asarray(
                [float(item["temperature_k"]) for item in points]
            )
            x = 1.0 / (K_B_EV * temperatures)
            design = np.column_stack([np.ones(len(points)), -x])
            weights = 1.0 / sigma_y**2
            parameter = np.linalg.solve(
                design.T @ (weights[:, None] * design),
                design.T @ (weights * y),
            )
            parameters.append(parameter)
        mean_parameters = np.mean(np.stack(parameters), axis=0)
        activation_draws[iteration] = mean_parameters[1]
        log_prefactor_draws[iteration] = mean_parameters[0]
        room_log_d_draws[iteration] = mean_parameters[0] - mean_parameters[1] / (
            K_B_EV * room_temperature_k
        )
        inverse_kbt = 1.0 / (
            K_B_EV * np.asarray(prediction_temperatures, dtype=float)
        )
        population_log_d_draws[iteration] = (
            mean_parameters[0] - mean_parameters[1] * inverse_kbt
        )
        selected_position = int(rng.integers(0, group_count))
        selected_parameters = parameters[selected_position]
        new_configuration_log_d_draws[iteration] = (
            selected_parameters[0] - selected_parameters[1] * inverse_kbt
        )
        if compute_nernst_einstein_conductivity:
            from .validation import ELEMENTARY_CHARGE_C, K_B_J

            group_log_conductivity = []
            for parameter, context in zip(parameters, sampled_contexts):
                number_density_m3 = float(context["n_mobile"]) / (
                    float(context["volume_angstrom3"]) * 1e-30
                )
                log_factor = np.log(
                    number_density_m3
                    * ELEMENTARY_CHARGE_C**2
                    * 1e-4
                    / (K_B_J * np.asarray(prediction_temperatures) * 100.0)
                )
                group_log_conductivity.append(
                    parameter[0] - parameter[1] * inverse_kbt + log_factor
                )
            stacked_conductivity = np.stack(group_log_conductivity)
            assert population_log_conductivity_draws is not None
            assert new_configuration_log_conductivity_draws is not None
            population_log_conductivity_draws[iteration] = np.mean(
                stacked_conductivity, axis=0
            )
            new_configuration_log_conductivity_draws[iteration] = (
                stacked_conductivity[selected_position]
            )
        quadratic_draws[iteration] = _fixed_intercept_curvature(
            sampled_groups, override_y=sampled_y
        )["quadratic_coefficient"]

    quantiles = np.asarray(bootstrap_quantiles, dtype=float)
    if (
        quantiles.ndim != 1
        or len(quantiles) < 3
        or np.any(quantiles <= 0)
        or np.any(quantiles >= 1)
        or np.any(np.diff(quantiles) <= 0)
    ):
        raise ValueError("bootstrap quantiles must be strictly increasing inside (0,1)")

    def summarized(values: np.ndarray) -> dict[str, Any]:
        return {
            "mean": float(np.mean(values)),
            "standard_deviation": float(np.std(values, ddof=1)),
            "quantiles": {
                str(value): float(result)
                for value, result in zip(quantiles, np.quantile(values, quantiles))
            },
        }

    def exponentiated_quantiles(values: np.ndarray) -> dict[str, float]:
        return {
            str(value): float(math.exp(result))
            for value, result in zip(quantiles, np.quantile(values, quantiles))
        }

    temperature_predictions = {}
    for index, temperature in enumerate(prediction_temperatures):
        population_values = population_log_d_draws[:, index]
        predictive_values = new_configuration_log_d_draws[:, index]
        row: dict[str, Any] = {
            "temperature_k": temperature,
            "is_extrapolation": not (
                min(required) <= temperature <= max(required)
            ),
            "population_geometric_mean": {
                "log_diffusivity": summarized(population_values),
                "diffusivity_cm2_s_quantiles": exponentiated_quantiles(
                    population_values
                ),
            },
            "new_configuration_predictive": {
                "log_diffusivity": summarized(predictive_values),
                "diffusivity_cm2_s_quantiles": exponentiated_quantiles(
                    predictive_values
                ),
            },
        }
        if compute_nernst_einstein_conductivity:
            assert population_log_conductivity_draws is not None
            assert new_configuration_log_conductivity_draws is not None
            population_conductivity = population_log_conductivity_draws[:, index]
            predictive_conductivity = new_configuration_log_conductivity_draws[
                :, index
            ]
            row["population_geometric_mean"][
                "conductivity_s_cm_quantiles"
            ] = exponentiated_quantiles(population_conductivity)
            row["new_configuration_predictive"][
                "conductivity_s_cm_quantiles"
            ] = exponentiated_quantiles(predictive_conductivity)
        temperature_predictions[format(temperature, ".12g")] = row

    quadratic_interval = np.quantile(
        quadratic_draws,
        [(1.0 - confidence_level) / 2.0, 1.0 - (1.0 - confidence_level) / 2.0],
    )
    curvature.update(
        quadratic_coefficient_bootstrap_interval=quadratic_interval.tolist(),
        aicc_improvement_required=float(curvature_aicc_improvement_min),
        non_arrhenius_supported=bool(
            curvature["linear_minus_quadratic_aicc"]
            >= curvature_aicc_improvement_min
            and quadratic_interval[0] * quadratic_interval[1] > 0
        ),
    )
    return {
        "n_configurations": group_count,
        "n_temperatures": len(required),
        "inferential_unit": "paired occupancy/velocity configuration",
        "configuration_fits": configuration_fits,
        "configuration_density_contexts": group_contexts,
        "activation_energy_random_effects": activation_meta,
        "nested_configuration_bootstrap": {
            "iterations": bootstrap_iterations,
            "seed": bootstrap_seed,
            "activation_energy_ev": summarized(activation_draws),
            "log_prefactor_cm2_s": summarized(log_prefactor_draws),
            "room_temperature_k": room_temperature_k,
            "room_temperature_log_diffusivity": summarized(room_log_d_draws),
            "room_temperature_diffusivity_cm2_s_quantiles": {
                str(value): float(math.exp(result))
                for value, result in zip(
                    quantiles, np.quantile(room_log_d_draws, quantiles)
                )
            },
            "temperature_predictions": temperature_predictions,
        },
        "non_arrhenius_diagnostic": curvature,
        "analysis_gate_pass": True,
    }


def _campaign_records(
    campaign_root: Path,
    protocol: dict[str, Any],
    estimator: dict[str, Any],
    *,
    expected_campaign_id: str,
    expected_campaign_protocol_sha256: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records = []
    sources = []
    for run_id in protocol["formal_run_ids"]:
        run_dir = campaign_root / run_id
        manifest_path = run_dir / "run_manifest.json"
        result_path = run_dir / "result.json"
        manifest = _read_json(manifest_path)
        result = _read_json(result_path)
        if result.get("protocol_fingerprint") != manifest.get("protocol_fingerprint"):
            raise RuntimeError(f"result/manifest fingerprint mismatch: {run_id}")
        provenance = manifest.get("config", {}).get("provenance", {})
        if provenance.get("campaign_run_id") != run_id:
            raise RuntimeError(f"campaign run provenance mismatch: {run_id}")
        if (
            provenance.get("campaign_id") != expected_campaign_id
            or provenance.get("campaign_protocol_sha256")
            != expected_campaign_protocol_sha256
        ):
            raise RuntimeError(f"campaign protocol provenance mismatch: {run_id}")
        volume = (
            result.get("relaxation", {})
            .get("final_summary", {})
            .get("volume_angstrom3")
        )
        if volume is None:
            volume = (
                result.get("structure", {})
                .get("prepared_summary", {})
                .get("volume_angstrom3")
            )
        for point in result.get("points", []):
            records.append(
                {
                    "group_id": run_id,
                    "occupancy_seed": int(manifest["config"]["occupancy_seed"]),
                    "velocity_seed": int(manifest["config"]["seed"]),
                    "temperature_k": int(point["temperature"]),
                    "diffusivity_cm2_s": point.get(estimator["diffusivity_field"]),
                    "stderr_cm2_s": point.get(estimator["stderr_field"]),
                    "resolved": point.get(estimator["resolved_field"]),
                    "n_mobile": point.get("n_mobile"),
                    "volume_angstrom3": volume,
                }
            )
        sources.append(
            {
                "run_id": run_id,
                "manifest_path": str(manifest_path.resolve()),
                "manifest_sha256": sha256_file(manifest_path),
                "result_path": str(result_path.resolve()),
                "result_sha256": sha256_file(result_path),
            }
        )
    return records, sources


def build_hierarchical_transport_report(
    campaign_root: Path | str,
    analysis_protocol_path: Path | str,
) -> dict[str, Any]:
    """Build tracer and collective reports, retaining any hard-gate failure."""
    root = Path(campaign_root).resolve()
    protocol_path = Path(analysis_protocol_path).resolve()
    protocol = _read_json(protocol_path)
    if protocol.get("schema_version") != "1.0":
        raise ValueError("hierarchical protocol schema_version must be '1.0'")
    campaign_protocol_path = Path(protocol["formal_campaign_protocol_path"])
    if not campaign_protocol_path.is_absolute():
        campaign_protocol_path = (
            Path(__file__).resolve().parents[2] / campaign_protocol_path
        )
    campaign_protocol = _read_json(campaign_protocol_path)
    campaign_protocol_sha256 = sha256_file(campaign_protocol_path)
    bootstrap = protocol["bootstrap"]
    model = protocol["arrhenius_model"]
    curvature = protocol["non_arrhenius_test"]
    estimators = {}
    all_sources: dict[str, dict[str, Any]] = {}
    for name, estimator in protocol["estimators"].items():
        try:
            records, sources = _campaign_records(
                root,
                protocol,
                estimator,
                expected_campaign_id=str(campaign_protocol["campaign_id"]),
                expected_campaign_protocol_sha256=campaign_protocol_sha256,
            )
            result = analyze_hierarchical_estimator(
                records,
                required_temperatures_k=protocol["required_temperatures_k"],
                bootstrap_iterations=int(bootstrap["iterations"]),
                bootstrap_seed=int(bootstrap["seed"]),
                bootstrap_quantiles=bootstrap["reported_intervals"],
                room_temperature_k=float(bootstrap["room_temperature_k"]),
                confidence_level=float(model["confidence_level"]),
                curvature_aicc_improvement_min=float(
                    curvature["aicc_improvement_min"]
                ),
                prediction_temperatures_k=bootstrap.get(
                    "experimental_prediction_temperatures_k", []
                ),
                compute_nernst_einstein_conductivity=bool(
                    estimator.get("compute_nernst_einstein_conductivity", False)
                ),
            )
            estimators[name] = result
            for source in sources:
                all_sources[source["run_id"]] = source
        except (ValueError, RuntimeError, FileNotFoundError, TypeError) as exc:
            estimators[name] = {
                "analysis_gate_pass": False,
                "error": f"{type(exc).__name__}: {exc}",
                "required_action": protocol["hard_rules"]["unresolved_point_action"],
            }
    report = {
        "schema_version": "1.0",
        "report_kind": "hierarchical-transport",
        "analysis_protocol_path": str(protocol_path),
        "analysis_protocol_sha256": sha256_file(protocol_path),
        "formal_campaign_protocol_path": str(campaign_protocol_path.resolve()),
        "formal_campaign_protocol_sha256": campaign_protocol_sha256,
        "campaign_root": str(root),
        "inferential_unit": protocol["inferential_unit"],
        "estimators": estimators,
        "sources": [all_sources[key] for key in sorted(all_sources)],
        "hierarchical_gate_pass": all(
            value.get("analysis_gate_pass") is True for value in estimators.values()
        ),
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
    }
    report["report_fingerprint"] = fingerprint(report)
    return report


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-root", required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = build_hierarchical_transport_report(args.campaign_root, args.protocol)
    destination = Path(args.out).resolve()
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite hierarchical report: {destination}")
    atomic_write_json(destination, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
