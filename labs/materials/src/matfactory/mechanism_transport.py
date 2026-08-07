"""Preregistered repeated-measures links between LLZTO mechanisms and transport."""

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


def _resolve_repo_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (Path(__file__).resolve().parents[2] / path).resolve()


def _finite_positive(value: Any, *, label: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be finite and positive")
    return number


def _setting_number(value: float) -> str:
    return format(float(value), ".12g")


def holm_adjusted_pvalues(p_values: dict[str, float]) -> dict[str, float]:
    """Return monotone Holm family-wise adjusted p-values."""
    if not p_values:
        return {}
    for name, value in p_values.items():
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(f"invalid p-value for {name}: {value}")
    ordered = sorted(p_values, key=lambda name: (p_values[name], name))
    family_size = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, name in enumerate(ordered):
        candidate = min(1.0, (family_size - rank) * p_values[name])
        running = max(running, candidate)
        adjusted[name] = running
    return adjusted


def _design(
    groups: np.ndarray,
    temperatures: np.ndarray,
    descriptor: np.ndarray,
    *,
    descriptor_center: float | None = None,
    descriptor_scale: float | None = None,
) -> tuple[np.ndarray, np.ndarray, float, float, list[str]]:
    labels = sorted({str(value) for value in groups.tolist()})
    if len(labels) < 3:
        raise ValueError("association model requires at least three occupancy groups")
    indicators = np.column_stack([groups == label for label in labels]).astype(float)
    inverse_kbt = 1.0 / (K_B_EV * temperatures)
    temperature_scale = float(np.std(inverse_kbt, ddof=1))
    if not math.isfinite(temperature_scale) or temperature_scale <= 0:
        raise ValueError("association model requires multiple temperatures")
    centered_temperature = (inverse_kbt - float(np.mean(inverse_kbt))) / temperature_scale
    center = (
        float(np.mean(descriptor))
        if descriptor_center is None
        else float(descriptor_center)
    )
    scale = (
        float(np.std(descriptor, ddof=1))
        if descriptor_scale is None
        else float(descriptor_scale)
    )
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("mechanism descriptor has zero or invalid variation")
    standardized = (descriptor - center) / scale
    reduced = np.column_stack([indicators, centered_temperature])
    full = np.column_stack([reduced, standardized])
    return reduced, full, center, scale, labels


def _weighted_fit(
    design: np.ndarray,
    response: np.ndarray,
    variances: np.ndarray,
) -> dict[str, Any]:
    if design.shape[0] != len(response) or response.shape != variances.shape:
        raise ValueError("WLS arrays have incompatible shapes")
    if np.any(~np.isfinite(design)) or np.any(~np.isfinite(response)):
        raise ValueError("WLS inputs must be finite")
    if np.any(~np.isfinite(variances)) or np.any(variances <= 0):
        raise ValueError("WLS variances must be finite and positive")
    root_weight = 1.0 / np.sqrt(variances)
    weighted_design = design * root_weight[:, None]
    weighted_response = response * root_weight
    coefficients, _, rank, _ = np.linalg.lstsq(
        weighted_design, weighted_response, rcond=None
    )
    if rank != design.shape[1]:
        raise ValueError("association design matrix is rank deficient")
    fitted = design @ coefficients
    residual = response - fitted
    chi_square = float(np.sum(residual**2 / variances))
    degrees_of_freedom = design.shape[0] - design.shape[1]
    if degrees_of_freedom <= 0:
        raise ValueError("association model has no residual degrees of freedom")
    covariance_scale = max(1.0, chi_square / degrees_of_freedom)
    information = weighted_design.T @ weighted_design
    covariance = np.linalg.inv(information) * covariance_scale
    stderr = np.sqrt(np.diag(covariance))
    return {
        "coefficients": coefficients,
        "stderr": stderr,
        "fitted": fitted,
        "residual": residual,
        "chi_square": chi_square,
        "degrees_of_freedom": degrees_of_freedom,
        "covariance_scale": covariance_scale,
    }


def fit_primary_association(
    response: np.ndarray,
    variances: np.ndarray,
    temperatures: np.ndarray,
    groups: np.ndarray,
    descriptor: np.ndarray,
    *,
    descriptor_center: float | None = None,
    descriptor_scale: float | None = None,
) -> dict[str, Any]:
    """Fit the frozen occupancy-intercept plus temperature association model."""
    from scipy.stats import t

    reduced_design, full_design, center, scale, labels = _design(
        groups,
        temperatures,
        descriptor,
        descriptor_center=descriptor_center,
        descriptor_scale=descriptor_scale,
    )
    reduced = _weighted_fit(reduced_design, response, variances)
    full = _weighted_fit(full_design, response, variances)
    coefficient = float(full["coefficients"][-1])
    stderr = float(full["stderr"][-1])
    cluster_df = len(labels) - 1
    critical = float(t.ppf(0.975, df=cluster_df))
    reduced_chi_square = float(reduced["chi_square"])
    partial_r2 = (
        max(0.0, (reduced_chi_square - float(full["chi_square"])) / reduced_chi_square)
        if reduced_chi_square > 0
        else 0.0
    )
    return {
        "descriptor_coefficient_per_sample_sd": coefficient,
        "descriptor_standard_error_wls": stderr,
        "descriptor_t_statistic": coefficient / stderr,
        "descriptor_center": center,
        "descriptor_sample_sd": scale,
        "descriptive_95pct_interval_cluster_t_reference": [
            coefficient - critical * stderr,
            coefficient + critical * stderr,
        ],
        "cluster_reference_degrees_of_freedom": cluster_df,
        "partial_weighted_r2": partial_r2,
        "reduced_chi_square": reduced_chi_square,
        "full_chi_square": float(full["chi_square"]),
        "full_residual_degrees_of_freedom": int(full["degrees_of_freedom"]),
        "residual_variance_inflation": float(full["covariance_scale"]),
        "n_observations": int(len(response)),
        "n_occupancy_groups": len(labels),
        "_reduced_design": reduced_design,
        "_full_design": full_design,
        "_reduced_fitted": reduced["fitted"],
        "_reduced_residual": reduced["residual"],
    }


def _permutation_pvalue(
    response: np.ndarray,
    variances: np.ndarray,
    temperatures: np.ndarray,
    groups: np.ndarray,
    descriptor: np.ndarray,
    *,
    iterations: int,
    seed: int,
) -> dict[str, Any]:
    if iterations < 99:
        raise ValueError("association permutation test requires at least 99 iterations")
    observed = fit_primary_association(
        response, variances, temperatures, groups, descriptor
    )
    statistic = abs(float(observed["descriptor_t_statistic"]))
    reduced_fitted = np.asarray(observed["_reduced_fitted"], dtype=float)
    reduced_residual = np.asarray(observed["_reduced_residual"], dtype=float)
    standardized_residual = reduced_residual / np.sqrt(variances)
    group_indices = [np.flatnonzero(groups == label) for label in sorted(set(groups))]
    rng = np.random.default_rng(seed)
    extreme = 0
    for _ in range(iterations):
        permuted = standardized_residual.copy()
        for indices in group_indices:
            permuted[indices] = standardized_residual[rng.permutation(indices)]
        simulated = reduced_fitted + permuted * np.sqrt(variances)
        fitted = fit_primary_association(
            simulated, variances, temperatures, groups, descriptor
        )
        if abs(float(fitted["descriptor_t_statistic"])) >= statistic - 1e-12:
            extreme += 1
    return {
        "method": (
            "Freedman-Lane permutation of measurement-standardized reduced-model "
            "residuals within occupancy realization"
        ),
        "iterations": iterations,
        "seed": seed,
        "observed_absolute_t": statistic,
        "extreme_replicates": extreme,
        "two_sided_p_value": (extreme + 1) / (iterations + 1),
    }


def _cluster_bootstrap(
    response: np.ndarray,
    variances: np.ndarray,
    temperatures: np.ndarray,
    groups: np.ndarray,
    descriptor: np.ndarray,
    *,
    iterations: int,
    seed: int,
    quantiles: list[float],
    minimum_valid_fraction: float,
) -> dict[str, Any]:
    if iterations < 99:
        raise ValueError("association cluster bootstrap requires at least 99 iterations")
    quantile_array = np.asarray(quantiles, dtype=float)
    if (
        quantile_array.shape != (3,)
        or np.any(quantile_array <= 0)
        or np.any(quantile_array >= 1)
        or np.any(np.diff(quantile_array) <= 0)
    ):
        raise ValueError("association bootstrap requires three increasing quantiles")
    labels = sorted(set(groups))
    if not 0.0 < minimum_valid_fraction <= 1.0:
        raise ValueError("minimum_valid_fraction must be inside (0,1]")
    descriptor_center = float(np.mean(descriptor))
    descriptor_scale = float(np.std(descriptor, ddof=1))
    rng = np.random.default_rng(seed)
    draws: list[float] = []
    for _ in range(iterations):
        sampled = rng.integers(0, len(labels), size=len(labels))
        response_parts = []
        variance_parts = []
        temperature_parts = []
        descriptor_parts = []
        group_parts = []
        for replicate_index, sampled_index in enumerate(sampled):
            indices = np.flatnonzero(groups == labels[int(sampled_index)])
            response_parts.append(
                rng.normal(response[indices], np.sqrt(variances[indices]))
            )
            variance_parts.append(variances[indices])
            temperature_parts.append(temperatures[indices])
            descriptor_parts.append(descriptor[indices])
            group_parts.append(
                np.asarray([f"bootstrap-{replicate_index}"] * len(indices), dtype=object)
            )
        try:
            fitted = fit_primary_association(
                np.concatenate(response_parts),
                np.concatenate(variance_parts),
                np.concatenate(temperature_parts),
                np.concatenate(group_parts),
                np.concatenate(descriptor_parts),
                descriptor_center=descriptor_center,
                descriptor_scale=descriptor_scale,
            )
        except ValueError:
            continue
        draws.append(float(fitted["descriptor_coefficient_per_sample_sd"]))
    valid_fraction = len(draws) / iterations
    if valid_fraction < minimum_valid_fraction:
        raise RuntimeError(
            "too few valid occupancy-cluster bootstrap association fits: "
            f"{valid_fraction:.3f}"
        )
    values = np.asarray(draws)
    interval = np.quantile(values, quantile_array)
    return {
        "method": "occupancy-cluster bootstrap plus within-trajectory Normal draw",
        "iterations_requested": iterations,
        "iterations_valid": len(draws),
        "valid_fraction": valid_fraction,
        "seed": seed,
        "quantiles": {
            str(value): float(result)
            for value, result in zip(quantile_array, interval)
        },
        "interval_excludes_zero": bool(interval[0] * interval[-1] > 0),
    }


def _leave_one_group_out(
    response: np.ndarray,
    variances: np.ndarray,
    temperatures: np.ndarray,
    groups: np.ndarray,
    descriptor: np.ndarray,
    *,
    primary_sign: float,
) -> dict[str, Any]:
    coefficients: dict[str, float] = {}
    for label in sorted(set(groups)):
        keep = groups != label
        fitted = fit_primary_association(
            response[keep],
            variances[keep],
            temperatures[keep],
            groups[keep],
            descriptor[keep],
        )
        coefficients[str(label)] = float(
            fitted["descriptor_coefficient_per_sample_sd"]
        )
    sign_stable = bool(
        primary_sign != 0
        and all(value * primary_sign > 0 for value in coefficients.values())
    )
    return {
        "omitted_group_coefficients": coefficients,
        "sign_stable": sign_stable,
    }


def _sensitivity_slopes(
    rows: list[dict[str, Any]],
    descriptor_name: str,
    response_name: str,
    *,
    primary_sign: float,
) -> dict[str, Any]:
    setting_sets = [
        set(row["descriptor_settings"][descriptor_name]) for row in rows
    ]
    if not setting_sets or any(values != setting_sets[0] for values in setting_sets):
        raise ValueError(f"{descriptor_name} sensitivity settings do not match")
    settings = sorted(setting_sets[0])
    response = np.asarray([row["responses"][response_name]["value"] for row in rows])
    variances = np.asarray(
        [row["responses"][response_name]["variance"] for row in rows]
    )
    temperatures = np.asarray([row["temperature_k"] for row in rows], dtype=float)
    groups = np.asarray([row["group_id"] for row in rows], dtype=object)
    slopes: dict[str, float] = {}
    failures: dict[str, str] = {}
    for setting in settings:
        descriptor = np.asarray(
            [row["descriptor_settings"][descriptor_name][setting] for row in rows],
            dtype=float,
        )
        try:
            fitted = fit_primary_association(
                response, variances, temperatures, groups, descriptor
            )
            slopes[setting] = float(
                fitted["descriptor_coefficient_per_sample_sd"]
            )
        except (ValueError, np.linalg.LinAlgError) as exc:
            failures[setting] = f"{type(exc).__name__}: {exc}"
    sign_stable = bool(
        primary_sign != 0
        and len(slopes) == len(settings)
        and all(value * primary_sign > 0 for value in slopes.values())
    )
    return {
        "n_settings_expected": len(settings),
        "n_settings_fitted": len(slopes),
        "slope_range": (
            [float(min(slopes.values())), float(max(slopes.values()))]
            if slopes
            else None
        ),
        "slopes": slopes,
        "failures": failures,
        "sign_stable": sign_stable,
    }


def _between_configuration_ranks(
    rows: list[dict[str, Any]], descriptor_name: str, response_name: str
) -> dict[str, Any]:
    from scipy.stats import spearmanr

    by_temperature: dict[str, Any] = {}
    for temperature in sorted({int(row["temperature_k"]) for row in rows}):
        selected = [row for row in rows if int(row["temperature_k"]) == temperature]
        descriptor = [row["primary_descriptors"][descriptor_name] for row in selected]
        response = [row["responses"][response_name]["value"] for row in selected]
        result = spearmanr(descriptor, response)
        rho = float(result.statistic)
        by_temperature[str(temperature)] = {
            "n_configurations": len(selected),
            "spearman_rho": rho if math.isfinite(rho) else None,
            "p_value_intentionally_not_reported": True,
        }
    return {
        "scope": "descriptive_only_with_five_configurations",
        "by_temperature_k": by_temperature,
    }


def _public_fit(fitted: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in fitted.items() if not key.startswith("_")}


def analyze_association_records(
    rows: list[dict[str, Any]],
    *,
    descriptor_names: list[str],
    response_names: list[str],
    permutation_iterations: int,
    permutation_seed: int,
    bootstrap_iterations: int,
    bootstrap_seed: int,
    bootstrap_quantiles: list[float],
    bootstrap_minimum_valid_fraction: float,
    alpha: float,
) -> dict[str, Any]:
    """Analyze a complete 5x5 table and retain blocked response/descriptor cells."""
    if not 0.0 < alpha < 1.0:
        raise ValueError("association alpha must be inside (0,1)")
    observed_grid = {
        (str(row.get("group_id")), int(row.get("temperature_k"))) for row in rows
    }
    groups_present = sorted({group for group, _ in observed_grid})
    temperatures_present = sorted({temperature for _, temperature in observed_grid})
    grid_complete = bool(
        len(rows) == len(observed_grid) == 25
        and len(groups_present) == 5
        and len(temperatures_present) == 5
        and observed_grid
        == {
            (group, temperature)
            for group in groups_present
            for temperature in temperatures_present
        }
    )
    results: dict[str, dict[str, Any]] = {
        response: {} for response in response_names
    }
    raw_pvalues: dict[str, float] = {}
    if not grid_complete:
        error = (
            "complete 5 occupancy by 5 temperature grid required; observed "
            f"{len(observed_grid)} unique cells"
        )
        for response in response_names:
            for descriptor in descriptor_names:
                results[response][descriptor] = {
                    "analysis_gate_pass": False,
                    "error": error,
                }
        return {
            "grid_gate_pass": False,
            "groups": groups_present,
            "temperatures_k": temperatures_present,
            "associations": results,
            "family_size": len(descriptor_names) * len(response_names),
            "association_support_count": 0,
        }

    for response_index, response_name in enumerate(response_names):
        for descriptor_index, descriptor_name in enumerate(descriptor_names):
            combination = f"{response_name}__{descriptor_name}"
            try:
                if any(response_name not in row.get("responses", {}) for row in rows):
                    raise ValueError(f"incomplete or unresolved response {response_name}")
                if any(
                    descriptor_name not in row.get("primary_descriptors", {})
                    for row in rows
                ):
                    raise ValueError(
                        f"incomplete or quality-blocked descriptor {descriptor_name}"
                    )
                response = np.asarray(
                    [row["responses"][response_name]["value"] for row in rows],
                    dtype=float,
                )
                variances = np.asarray(
                    [row["responses"][response_name]["variance"] for row in rows],
                    dtype=float,
                )
                temperatures = np.asarray(
                    [row["temperature_k"] for row in rows], dtype=float
                )
                groups = np.asarray([row["group_id"] for row in rows], dtype=object)
                descriptor = np.asarray(
                    [row["primary_descriptors"][descriptor_name] for row in rows],
                    dtype=float,
                )
                fitted = fit_primary_association(
                    response, variances, temperatures, groups, descriptor
                )
                coefficient = float(
                    fitted["descriptor_coefficient_per_sample_sd"]
                )
                combination_seed = (
                    permutation_seed + response_index * len(descriptor_names) + descriptor_index
                )
                permutation = _permutation_pvalue(
                    response,
                    variances,
                    temperatures,
                    groups,
                    descriptor,
                    iterations=permutation_iterations,
                    seed=combination_seed,
                )
                bootstrap = _cluster_bootstrap(
                    response,
                    variances,
                    temperatures,
                    groups,
                    descriptor,
                    iterations=bootstrap_iterations,
                    seed=(
                        bootstrap_seed
                        + response_index * len(descriptor_names)
                        + descriptor_index
                    ),
                    quantiles=bootstrap_quantiles,
                    minimum_valid_fraction=bootstrap_minimum_valid_fraction,
                )
                leave_one_out = _leave_one_group_out(
                    response,
                    variances,
                    temperatures,
                    groups,
                    descriptor,
                    primary_sign=coefficient,
                )
                sensitivity = _sensitivity_slopes(
                    rows,
                    descriptor_name,
                    response_name,
                    primary_sign=coefficient,
                )
                raw_pvalue = float(permutation["two_sided_p_value"])
                raw_pvalues[combination] = raw_pvalue
                results[response_name][descriptor_name] = {
                    "analysis_gate_pass": True,
                    "primary_fit": _public_fit(fitted),
                    "permutation_test": permutation,
                    "cluster_bootstrap": bootstrap,
                    "leave_one_occupancy_out": leave_one_out,
                    "mechanism_setting_sensitivity": sensitivity,
                    "between_configuration_rank_summary": _between_configuration_ranks(
                        rows, descriptor_name, response_name
                    ),
                }
            except (ValueError, RuntimeError, KeyError, TypeError, np.linalg.LinAlgError) as exc:
                results[response_name][descriptor_name] = {
                    "analysis_gate_pass": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }

    # A blocked cell still belongs to the preregistered family. Assigning p=1
    # prevents missingness from making the multiplicity correction less conservative.
    all_combinations = [
        f"{response}__{descriptor}"
        for response in response_names
        for descriptor in descriptor_names
    ]
    adjusted = holm_adjusted_pvalues(
        {name: raw_pvalues.get(name, 1.0) for name in all_combinations}
    )
    support_count = 0
    for response_name in response_names:
        for descriptor_name in descriptor_names:
            combination = f"{response_name}__{descriptor_name}"
            result = results[response_name][descriptor_name]
            result["holm_family_size"] = len(all_combinations)
            result["holm_adjusted_p_value"] = adjusted[combination]
            supported = bool(
                result.get("analysis_gate_pass") is True
                and adjusted[combination] <= alpha
                and result["cluster_bootstrap"]["interval_excludes_zero"]
                and result["leave_one_occupancy_out"]["sign_stable"]
                and result["mechanism_setting_sensitivity"]["sign_stable"]
            )
            result["association_supported"] = supported
            if supported:
                support_count += 1
    return {
        "grid_gate_pass": True,
        "groups": groups_present,
        "temperatures_k": temperatures_present,
        "multiplicity_method": "Holm family-wise error correction",
        "family_size": len(all_combinations),
        "alpha": alpha,
        "associations": results,
        "association_support_count": support_count,
        "causal_mechanism_claim_allowed": False,
    }


def publication_analysis_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Retain point-level primary values without duplicating the full sensitivity grid."""
    fields = (
        "group_id",
        "occupancy_seed",
        "temperature_k",
        "volume_mean_angstrom3",
        "responses",
        "response_errors",
        "primary_descriptors",
        "mechanism_qualification",
    )
    return [{key: row[key] for key in fields} for row in rows]


def _paired_ratio_variance(
    transport: dict[str, Any], *, minimum_blocks: int
) -> tuple[float, int, str]:
    block_records = transport.get("block_estimates")
    pairs: list[tuple[float, float]] = []
    mode = "explicit_shared_block_records"
    if isinstance(block_records, list) and block_records:
        for row in block_records:
            tracer = row.get("tracer_diffusivity_cm2_s")
            collective = row.get("collective_diffusivity_cm2_s")
            if tracer is None or collective is None:
                continue
            tracer_value = float(tracer)
            collective_value = float(collective)
            if (
                math.isfinite(tracer_value)
                and math.isfinite(collective_value)
                and tracer_value > 0
                and collective_value > 0
            ):
                pairs.append((tracer_value, collective_value))
    else:
        tracer_blocks = transport["tracer"].get("block_diffusivities_cm2_s", [])
        collective_blocks = transport["collective"].get(
            "block_diffusivities_cm2_s", []
        )
        if len(tracer_blocks) != len(collective_blocks):
            raise ValueError("legacy tracer/collective block lists are not paired")
        mode = "legacy_positionally_paired_complete_block_lists"
        for tracer, collective in zip(tracer_blocks, collective_blocks):
            tracer_value = float(tracer)
            collective_value = float(collective)
            if (
                math.isfinite(tracer_value)
                and math.isfinite(collective_value)
                and tracer_value > 0
                and collective_value > 0
            ):
                pairs.append((tracer_value, collective_value))
    if len(pairs) < minimum_blocks:
        raise ValueError(
            f"collective/tracer ratio needs {minimum_blocks} paired blocks; "
            f"found {len(pairs)}"
        )
    values = np.asarray([math.log(collective / tracer) for tracer, collective in pairs])
    variance = float(np.var(values, ddof=1) / len(values))
    if not math.isfinite(variance) or variance <= 0:
        raise ValueError("paired log-ratio measurement variance is invalid")
    return variance, len(pairs), mode


def _transport_responses(
    payload: dict[str, Any], *, minimum_ratio_blocks: int
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    transport = payload["transport"]
    responses: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    for name, branch, gate in (
        ("log_tracer_diffusivity", "tracer", "resolved_after_all_checks"),
        (
            "log_collective_diffusivity",
            "collective",
            "collective_resolved_after_all_checks",
        ),
    ):
        try:
            if payload.get(gate) is not True:
                raise ValueError(f"transport gate {gate} did not pass")
            diffusion = _finite_positive(
                transport[branch]["diffusivity_cm2_s"], label=f"{branch} diffusion"
            )
            stderr = _finite_positive(
                transport[branch]["diffusivity_stderr_cm2_s"],
                label=f"{branch} diffusion stderr",
            )
            responses[name] = {
                "value": math.log(diffusion),
                "variance": (stderr / diffusion) ** 2,
                "diffusivity_cm2_s": diffusion,
                "diffusivity_stderr_cm2_s": stderr,
            }
        except (ValueError, KeyError, TypeError) as exc:
            errors[name] = f"{type(exc).__name__}: {exc}"
    ratio_name = "log_collective_to_tracer_ratio"
    try:
        if (
            payload.get("resolved_after_all_checks") is not True
            or payload.get("collective_resolved_after_all_checks") is not True
        ):
            raise ValueError("both tracer and collective gates must pass for the ratio")
        tracer = _finite_positive(
            transport["tracer"]["diffusivity_cm2_s"], label="tracer diffusion"
        )
        collective = _finite_positive(
            transport["collective"]["diffusivity_cm2_s"],
            label="collective diffusion",
        )
        variance, n_blocks, pairing_mode = _paired_ratio_variance(
            transport, minimum_blocks=minimum_ratio_blocks
        )
        responses[ratio_name] = {
            "value": math.log(collective / tracer),
            "variance": variance,
            "collective_to_tracer_ratio": collective / tracer,
            "n_paired_blocks": n_blocks,
            "block_pairing_mode": pairing_mode,
        }
    except (ValueError, KeyError, TypeError) as exc:
        errors[ratio_name] = f"{type(exc).__name__}: {exc}"
    return responses, errors


def _mechanism_descriptors(
    payload: dict[str, Any], descriptor_protocol: dict[str, Any]
) -> tuple[
    dict[str, float], dict[str, dict[str, float]], dict[str, Any]
]:
    if payload.get("summary", {}).get("all_settings_pass_quality") is not True:
        raise ValueError("not all mechanism assignment settings pass quality")
    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) != 9:
        raise ValueError("mechanism sensitivity report must contain exactly nine rows")
    primary: dict[str, float] = {}
    settings: dict[str, dict[str, float]] = {
        name: {} for name in descriptor_protocol
    }
    primary_matches = 0
    for row in rows:
        cutoff = float(row["assignment_cutoff_angstrom"])
        dwell = float(row["min_dwell_ps"])
        base = f"cutoff={_setting_number(cutoff)}|dwell={_setting_number(dwell)}"
        jump_rate = _finite_positive(
            row["jump_rate_per_ion_ps"], label="jump rate"
        )
        populations = row["mean_mobile_population_by_site_type"]
        population_total = float(sum(float(value) for value in populations.values()))
        tetrahedral = float(populations.get("tetrahedral-24d", 0.0))
        if not math.isfinite(population_total) or population_total <= 0:
            raise ValueError("assigned mobile population is invalid")
        tetrahedral_fraction = tetrahedral / population_total
        string_excess = float(row["primary_string"]["observed_minus_null_mean"])
        if not math.isfinite(string_excess):
            raise ValueError("string excess is invalid")
        settings["log_jump_rate"][base] = math.log(jump_rate)
        settings["tetrahedral_population_fraction"][base] = tetrahedral_fraction
        settings["string_excess"][base] = string_excess
        for window, value in row["reverse_pair_fraction_by_window_ps"].items():
            if value is None or not math.isfinite(float(value)):
                raise ValueError("reverse-pair fraction is missing or invalid")
            reverse_setting = f"{base}|reverse={_setting_number(float(window))}"
            settings["reverse_pair_fraction"][reverse_setting] = float(value)

        is_primary = all(
            math.isclose(
                actual,
                float(descriptor_protocol[name][field]),
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            for name, field, actual in (
                ("log_jump_rate", "primary_assignment_cutoff_angstrom", cutoff),
                ("log_jump_rate", "primary_min_dwell_ps", dwell),
            )
        )
        if is_primary:
            primary_matches += 1
            primary["log_jump_rate"] = math.log(jump_rate)
            primary["tetrahedral_population_fraction"] = tetrahedral_fraction
            primary["string_excess"] = string_excess
            reverse_window = descriptor_protocol["reverse_pair_fraction"][
                "primary_reverse_window_ps"
            ]
            reverse_key = _setting_number(float(reverse_window))
            reverse_values = row["reverse_pair_fraction_by_window_ps"]
            if reverse_key not in reverse_values:
                raise ValueError("primary reverse-window descriptor is missing")
            primary["reverse_pair_fraction"] = float(reverse_values[reverse_key])
    if primary_matches != 1 or set(primary) != set(descriptor_protocol):
        raise ValueError("mechanism report does not contain one complete primary setting")
    expected_setting_counts = {
        "log_jump_rate": 9,
        "tetrahedral_population_fraction": 9,
        "reverse_pair_fraction": 27,
        "string_excess": 9,
    }
    if any(
        len(settings[name]) != expected
        for name, expected in expected_setting_counts.items()
    ):
        raise ValueError("mechanism sensitivity grid is incomplete or duplicated")
    qualification = {
        "mechanism_robustness_gate_pass": payload["summary"].get(
            "mechanism_robustness_gate_pass"
        ),
        "cooperative_string_claim_supported_across_grid": payload["summary"].get(
            "cooperative_string_claim_supported_across_grid"
        ),
    }
    return primary, settings, qualification


def build_mechanism_transport_report(
    campaign_root: Path | str,
    mechanism_root: Path | str,
    analysis_protocol_path: Path | str,
) -> dict[str, Any]:
    """Load immutable formal artifacts and run the frozen association family."""
    campaign_root_path = Path(campaign_root).resolve()
    mechanism_root_path = Path(mechanism_root).resolve()
    protocol_path = Path(analysis_protocol_path).resolve()
    protocol = _read_json(protocol_path)
    if protocol.get("schema_version") != "1.0":
        raise ValueError("association protocol schema_version must be '1.0'")

    campaign_config = protocol["formal_campaign"]
    campaign_protocol_path = _resolve_repo_path(campaign_config["protocol_path"])
    if sha256_file(campaign_protocol_path) != campaign_config["protocol_sha256"]:
        raise RuntimeError("formal campaign protocol hash does not match association protocol")
    mechanism_config = protocol["mechanism_inputs"]
    mechanism_protocol_path = _resolve_repo_path(mechanism_config["protocol_path"])
    if sha256_file(mechanism_protocol_path) != mechanism_config["protocol_sha256"]:
        raise RuntimeError("mechanism protocol hash does not match association protocol")

    rows: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    input_errors: list[dict[str, Any]] = []
    occupancy_seeds: set[int] = set()
    string_qualifications: list[dict[str, Any]] = []
    pattern = str(mechanism_config["relative_report_pattern"])
    minimum_blocks = int(
        protocol["responses"]["log_collective_to_tracer_ratio"][
            "minimum_paired_blocks"
        ]
    )
    for run_id in campaign_config["run_ids"]:
        run_path = campaign_root_path / run_id
        manifest_path = run_path / "run_manifest.json"
        try:
            manifest = _read_json(manifest_path)
            provenance = manifest["config"]["provenance"]
            if provenance.get("campaign_id") != campaign_config["campaign_id"]:
                raise RuntimeError(f"{run_id} campaign id mismatch")
            if provenance.get("campaign_run_id") != run_id:
                raise RuntimeError(f"{run_id} manifest run id mismatch")
            if (
                provenance.get("campaign_protocol_sha256")
                != campaign_config["protocol_sha256"]
            ):
                raise RuntimeError(f"{run_id} campaign protocol hash mismatch")
            occupancy_seed = int(manifest["config"]["occupancy_seed"])
            if occupancy_seed in occupancy_seeds:
                raise RuntimeError("formal association groups repeat an occupancy seed")
            occupancy_seeds.add(occupancy_seed)
            expected_fingerprint = manifest["protocol_fingerprint"]
            sources.append(
                {
                    "kind": "run_manifest",
                    "run_id": run_id,
                    "path": str(manifest_path.resolve()),
                    "sha256": sha256_file(manifest_path),
                }
            )
        except (FileNotFoundError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            input_errors.append(
                {
                    "run_id": run_id,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        for temperature in campaign_config["temperatures_k"]:
            transport_path = run_path / f"T{temperature}.transport.json"
            mechanism_path = mechanism_root_path / pattern.format(
                run_id=run_id, temperature_k=temperature
            )
            try:
                transport_payload = _read_json(transport_path)
                if int(transport_payload["temperature_k"]) != int(temperature):
                    raise RuntimeError("transport temperature mismatch")
                if transport_payload.get("protocol_fingerprint") != expected_fingerprint:
                    raise RuntimeError("transport protocol fingerprint mismatch")
                mechanism_payload = _read_json(mechanism_path)
                if (
                    mechanism_payload.get("protocol_sha256")
                    != mechanism_config["protocol_sha256"]
                ):
                    raise RuntimeError("mechanism analysis protocol hash mismatch")
                expected_trajectory = (run_path / f"T{temperature}.traj").resolve()
                reported_trajectory = Path(
                    mechanism_payload["trajectory_path"]
                ).resolve()
                if reported_trajectory != expected_trajectory:
                    raise RuntimeError("mechanism report points to the wrong trajectory")
                trajectory_hash = sha256_file(expected_trajectory)
                if mechanism_payload.get("trajectory_sha256") != trajectory_hash:
                    raise RuntimeError("mechanism trajectory hash mismatch")
                responses, response_errors = _transport_responses(
                    transport_payload, minimum_ratio_blocks=minimum_blocks
                )
                primary, descriptor_settings, qualification = _mechanism_descriptors(
                    mechanism_payload, protocol["descriptors"]
                )
                row = {
                    "group_id": run_id,
                    "occupancy_seed": occupancy_seed,
                    "temperature_k": int(temperature),
                    "volume_mean_angstrom3": transport_payload.get(
                        "trajectory_diagnostics", {}
                    ).get("volume_mean_angstrom3"),
                    "responses": responses,
                    "response_errors": response_errors,
                    "primary_descriptors": primary,
                    "descriptor_settings": descriptor_settings,
                    "mechanism_qualification": qualification,
                }
                rows.append(row)
                string_qualifications.append(
                    {
                        "run_id": run_id,
                        "temperature_k": int(temperature),
                        **qualification,
                    }
                )
                sources.extend(
                    [
                        {
                            "kind": "transport",
                            "run_id": run_id,
                            "temperature_k": int(temperature),
                            "path": str(transport_path.resolve()),
                            "sha256": sha256_file(transport_path),
                        },
                        {
                            "kind": "mechanism_sensitivity",
                            "run_id": run_id,
                            "temperature_k": int(temperature),
                            "path": str(mechanism_path.resolve()),
                            "sha256": sha256_file(mechanism_path),
                            "trajectory_sha256": trajectory_hash,
                        },
                    ]
                )
            except (
                FileNotFoundError,
                ValueError,
                KeyError,
                TypeError,
                RuntimeError,
            ) as exc:
                input_errors.append(
                    {
                        "run_id": run_id,
                        "temperature_k": int(temperature),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

    model = protocol["primary_model"]
    permutation = model["permutation_test"]
    bootstrap = model["cluster_bootstrap"]
    multiplicity = model["multiplicity"]
    analysis = analyze_association_records(
        rows,
        descriptor_names=list(protocol["descriptors"]),
        response_names=list(protocol["responses"]),
        permutation_iterations=int(permutation["iterations"]),
        permutation_seed=int(permutation["seed"]),
        bootstrap_iterations=int(bootstrap["iterations"]),
        bootstrap_seed=int(bootstrap["seed"]),
        bootstrap_quantiles=bootstrap["quantiles"],
        bootstrap_minimum_valid_fraction=float(
            bootstrap["minimum_valid_fraction"]
        ),
        alpha=float(multiplicity["alpha"]),
    )
    cooperative_all = bool(
        len(string_qualifications) == 25
        and all(
            row.get("cooperative_string_claim_supported_across_grid") is True
            for row in string_qualifications
        )
    )
    report = {
        "schema_version": "1.0",
        "report_kind": "mechanism-transport-association",
        "analysis_protocol_path": str(protocol_path),
        "analysis_protocol_sha256": sha256_file(protocol_path),
        "campaign_root": str(campaign_root_path),
        "mechanism_root": str(mechanism_root_path),
        "input_gate_pass": not input_errors and len(rows) == 25,
        "input_errors": input_errors,
        "analysis_records": publication_analysis_records(rows),
        "analysis": analysis,
        "string_claim_qualification": {
            "all_25_trajectories_support_cooperative_strings_across_grid": cooperative_all,
            "allowed_label": (
                "cooperative_string_excess"
                if cooperative_all
                else "null_corrected_temporal_clustering_excess"
            ),
            "causal_claim_allowed": False,
            "trajectory_qualifications": string_qualifications,
        },
        "source_count": len(sources),
        "sources": sources,
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
    }
    report["report_fingerprint"] = fingerprint(report)
    return report


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-root", required=True)
    parser.add_argument("--mechanism-root", required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = build_mechanism_transport_report(
        args.campaign_root, args.mechanism_root, args.protocol
    )
    destination = Path(args.out).resolve()
    if destination.exists():
        raise RuntimeError(
            f"refusing to overwrite mechanism-transport report: {destination}"
        )
    atomic_write_json(destination, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
