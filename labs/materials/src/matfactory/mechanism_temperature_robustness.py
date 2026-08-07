"""Categorical-temperature robustness audit for LLZTO mechanism associations."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .mechanism_transport import _weighted_fit, holm_adjusted_pvalues
from .provenance import atomic_write_json, fingerprint, sha256_file


_ROOT = Path(__file__).resolve().parents[2]


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def _repo_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (_ROOT / path).resolve()


def _verify_fingerprint(payload: dict[str, Any], field: str, label: str) -> None:
    unsigned = dict(payload)
    stored = unsigned.pop(field, None)
    if stored != fingerprint(unsigned):
        raise RuntimeError(f"{label} fingerprint mismatch")


def _categorical_temperature_design(
    groups: np.ndarray,
    temperatures: np.ndarray,
    descriptor: np.ndarray,
    *,
    descriptor_center: float | None = None,
    descriptor_scale: float | None = None,
) -> tuple[np.ndarray, np.ndarray, float, float, list[str], list[float]]:
    """Build group and saturated-temperature fixed effects plus one descriptor."""
    normalized_groups = groups.astype(str)
    group_labels = sorted(set(normalized_groups.tolist()))
    temperature_levels = sorted({float(value) for value in temperatures.tolist()})
    if len(group_labels) < 3 or len(temperature_levels) < 3:
        raise ValueError("robustness model needs at least three groups and temperatures")
    if np.any(~np.isfinite(temperatures)) or np.any(~np.isfinite(descriptor)):
        raise ValueError("robustness design values must be finite")

    group_indicators = np.column_stack(
        [normalized_groups == label for label in group_labels]
    ).astype(float)
    # All group indicators already span the intercept, so omit one temperature
    # level to avoid the two-way fixed-effect dummy-variable trap.
    temperature_indicators = np.column_stack(
        [temperatures == level for level in temperature_levels[1:]]
    ).astype(float)
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
    reduced = np.column_stack([group_indicators, temperature_indicators])
    full = np.column_stack([reduced, standardized])
    return reduced, full, center, scale, group_labels, temperature_levels


def fit_categorical_temperature_association(
    response: np.ndarray,
    variances: np.ndarray,
    temperatures: np.ndarray,
    groups: np.ndarray,
    descriptor: np.ndarray,
    *,
    descriptor_center: float | None = None,
    descriptor_scale: float | None = None,
) -> dict[str, Any]:
    """Fit a descriptor after arbitrary common effects of each temperature."""
    from scipy.stats import t

    reduced_design, full_design, center, scale, labels, levels = (
        _categorical_temperature_design(
            groups,
            temperatures,
            descriptor,
            descriptor_center=descriptor_center,
            descriptor_scale=descriptor_scale,
        )
    )
    reduced = _weighted_fit(reduced_design, response, variances)
    full = _weighted_fit(full_design, response, variances)
    coefficient = float(full["coefficients"][-1])
    stderr = float(full["stderr"][-1])
    cluster_df = len(labels) - 1
    critical = float(t.ppf(0.975, df=cluster_df))
    reduced_chi_square = float(reduced["chi_square"])
    partial_r2 = (
        max(
            0.0,
            (reduced_chi_square - float(full["chi_square"]))
            / reduced_chi_square,
        )
        if reduced_chi_square > 0
        else 0.0
    )
    return {
        "descriptor_coefficient_per_original_sample_sd": coefficient,
        "descriptor_standard_error_wls": stderr,
        "descriptor_t_statistic": coefficient / stderr,
        "descriptor_center": center,
        "descriptor_original_sample_sd": scale,
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
        "temperature_levels_k": levels,
        "temperature_model": "categorical_fixed_effects",
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
        raise ValueError("temperature robustness permutation needs at least 99 draws")
    observed = fit_categorical_temperature_association(
        response, variances, temperatures, groups, descriptor
    )
    statistic = abs(float(observed["descriptor_t_statistic"]))
    fitted = np.asarray(observed["_reduced_fitted"], dtype=float)
    residual = np.asarray(observed["_reduced_residual"], dtype=float)
    standardized = residual / np.sqrt(variances)
    group_indices = [np.flatnonzero(groups == label) for label in sorted(set(groups))]
    rng = np.random.default_rng(seed)
    extreme = 0
    for _ in range(iterations):
        permuted = standardized.copy()
        for indices in group_indices:
            permuted[indices] = standardized[rng.permutation(indices)]
        simulated = fitted + permuted * np.sqrt(variances)
        result = fit_categorical_temperature_association(
            simulated, variances, temperatures, groups, descriptor
        )
        if abs(float(result["descriptor_t_statistic"])) >= statistic - 1e-12:
            extreme += 1
    return {
        "method": (
            "Freedman-Lane permutation of measurement-standardized residuals "
            "within occupancy after categorical temperature fixed effects"
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
        raise ValueError("temperature robustness bootstrap needs at least 99 draws")
    quantile_array = np.asarray(quantiles, dtype=float)
    if (
        quantile_array.shape != (3,)
        or np.any(quantile_array <= 0)
        or np.any(quantile_array >= 1)
        or np.any(np.diff(quantile_array) <= 0)
    ):
        raise ValueError("robustness bootstrap needs three increasing quantiles")
    if not 0.0 < minimum_valid_fraction <= 1.0:
        raise ValueError("minimum_valid_fraction must be inside (0,1]")
    labels = sorted(set(groups))
    center = float(np.mean(descriptor))
    scale = float(np.std(descriptor, ddof=1))
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
                np.asarray(
                    [f"bootstrap-{replicate_index}"] * len(indices), dtype=object
                )
            )
        try:
            result = fit_categorical_temperature_association(
                np.concatenate(response_parts),
                np.concatenate(variance_parts),
                np.concatenate(temperature_parts),
                np.concatenate(group_parts),
                np.concatenate(descriptor_parts),
                descriptor_center=center,
                descriptor_scale=scale,
            )
        except (ValueError, np.linalg.LinAlgError):
            continue
        draws.append(
            float(result["descriptor_coefficient_per_original_sample_sd"])
        )
    valid_fraction = len(draws) / iterations
    if valid_fraction < minimum_valid_fraction:
        raise RuntimeError(
            "too few valid categorical-temperature cluster bootstrap fits: "
            f"{valid_fraction:.3f}"
        )
    interval = np.quantile(np.asarray(draws), quantile_array)
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
        result = fit_categorical_temperature_association(
            response[keep],
            variances[keep],
            temperatures[keep],
            groups[keep],
            descriptor[keep],
        )
        coefficients[str(label)] = float(
            result["descriptor_coefficient_per_original_sample_sd"]
        )
    stable = bool(
        primary_sign != 0
        and all(value * primary_sign > 0 for value in coefficients.values())
    )
    return {"omitted_group_coefficients": coefficients, "sign_stable": stable}


def _public_fit(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if not key.startswith("_")}


def analyze_temperature_robustness(
    rows: list[dict[str, Any]],
    primary_analysis: dict[str, Any],
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
    """Reconcile prespecified associations with a saturated temperature model."""
    if not 0.0 < alpha < 1.0:
        raise ValueError("robustness alpha must be inside (0,1)")
    observed = {
        (str(row.get("group_id")), int(row.get("temperature_k"))) for row in rows
    }
    group_levels = sorted({group for group, _ in observed})
    temperature_levels = sorted({temperature for _, temperature in observed})
    grid_complete = bool(
        len(rows) == len(observed) == 25
        and len(group_levels) == 5
        and len(temperature_levels) == 5
        and observed
        == {
            (group, temperature)
            for group in group_levels
            for temperature in temperature_levels
        }
    )
    results: dict[str, dict[str, Any]] = {
        response: {} for response in response_names
    }
    raw_pvalues: dict[str, float] = {}
    for response_index, response_name in enumerate(response_names):
        for descriptor_index, descriptor_name in enumerate(descriptor_names):
            combination = f"{response_name}__{descriptor_name}"
            if not grid_complete:
                results[response_name][descriptor_name] = {
                    "analysis_gate_pass": False,
                    "error": "complete 5 occupancy by 5 temperature grid required",
                }
                continue
            try:
                if any(response_name not in row.get("responses", {}) for row in rows):
                    raise ValueError(f"incomplete response {response_name}")
                if any(
                    descriptor_name not in row.get("primary_descriptors", {})
                    for row in rows
                ):
                    raise ValueError(f"incomplete descriptor {descriptor_name}")
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
                fitted = fit_categorical_temperature_association(
                    response, variances, temperatures, groups, descriptor
                )
                coefficient = float(
                    fitted["descriptor_coefficient_per_original_sample_sd"]
                )
                offset = response_index * len(descriptor_names) + descriptor_index
                permutation = _permutation_pvalue(
                    response,
                    variances,
                    temperatures,
                    groups,
                    descriptor,
                    iterations=permutation_iterations,
                    seed=permutation_seed + offset,
                )
                bootstrap = _cluster_bootstrap(
                    response,
                    variances,
                    temperatures,
                    groups,
                    descriptor,
                    iterations=bootstrap_iterations,
                    seed=bootstrap_seed + offset,
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
                primary = primary_analysis["associations"][response_name][
                    descriptor_name
                ]
                primary_coefficient = float(
                    primary.get("primary_fit", {}).get(
                        "descriptor_coefficient_per_sample_sd", float("nan")
                    )
                )
                raw_pvalue = float(permutation["two_sided_p_value"])
                raw_pvalues[combination] = raw_pvalue
                results[response_name][descriptor_name] = {
                    "analysis_gate_pass": True,
                    "categorical_temperature_fit": _public_fit(fitted),
                    "permutation_test": permutation,
                    "cluster_bootstrap": bootstrap,
                    "leave_one_occupancy_out": leave_one_out,
                    "primary_v1_association_supported": bool(
                        primary.get("association_supported") is True
                    ),
                    "primary_v1_coefficient_per_sample_sd": (
                        primary_coefficient if math.isfinite(primary_coefficient) else None
                    ),
                    "coefficient_sign_matches_primary_v1": bool(
                        math.isfinite(primary_coefficient)
                        and primary_coefficient * coefficient > 0
                    ),
                }
            except (
                ValueError,
                RuntimeError,
                KeyError,
                TypeError,
                np.linalg.LinAlgError,
            ) as exc:
                results[response_name][descriptor_name] = {
                    "analysis_gate_pass": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }

    combinations = [
        f"{response}__{descriptor}"
        for response in response_names
        for descriptor in descriptor_names
    ]
    adjusted = holm_adjusted_pvalues(
        {name: raw_pvalues.get(name, 1.0) for name in combinations}
    )
    primary_supported = 0
    robustness_supported = 0
    retained = 0
    sensitive: list[str] = []
    for response_name in response_names:
        for descriptor_name in descriptor_names:
            combination = f"{response_name}__{descriptor_name}"
            result = results[response_name][descriptor_name]
            primary_cell = (
                primary_analysis.get("associations", {})
                .get(response_name, {})
                .get(descriptor_name, {})
            )
            primary = primary_cell.get("association_supported") is True
            result.setdefault("primary_v1_association_supported", primary)
            result["holm_family_size"] = len(combinations)
            result["holm_adjusted_p_value"] = adjusted[combination]
            robust = bool(
                result.get("analysis_gate_pass") is True
                and adjusted[combination] <= alpha
                and result["cluster_bootstrap"]["interval_excludes_zero"]
                and result["leave_one_occupancy_out"]["sign_stable"]
                and result["coefficient_sign_matches_primary_v1"]
            )
            reconciled = primary and robust
            result["categorical_temperature_robustness_supported"] = robust
            result["association_retained_after_temperature_robustness"] = reconciled
            result["claim_disposition"] = (
                "retained_association_noncausal"
                if reconciled
                else (
                    (
                        "temperature_model_sensitive_downgrade_to_not_supported"
                        if result.get("analysis_gate_pass") is True
                        else "temperature_robustness_unresolved_no_positive_claim"
                    )
                    if primary
                    else "not_supported_by_preregistered_primary_model"
                )
            )
            primary_supported += int(primary)
            robustness_supported += int(robust)
            retained += int(reconciled)
            if primary and not robust:
                sensitive.append(combination)
    complete = bool(
        grid_complete
        and all(
            result.get("analysis_gate_pass") is True
            for by_descriptor in results.values()
            for result in by_descriptor.values()
        )
    )
    return {
        "grid_gate_pass": grid_complete,
        "analysis_completeness_gate_pass": complete,
        "groups": group_levels,
        "temperatures_k": temperature_levels,
        "temperature_model": "categorical fixed effects with one level omitted",
        "multiplicity_method": "Holm family-wise error correction",
        "family_size": len(combinations),
        "alpha": alpha,
        "associations": results,
        "primary_v1_support_count": primary_supported,
        "categorical_temperature_support_count": robustness_supported,
        "retained_association_count": retained,
        "temperature_model_sensitive_primary_associations": sensitive,
        "all_primary_supported_associations_survive": not sensitive,
        "causal_mechanism_claim_allowed": False,
    }


def build_temperature_robustness_report(protocol_path: Path | str) -> dict[str, Any]:
    """Build the frozen robustness report from the fingerprinted v1 report."""
    source = Path(protocol_path).resolve()
    protocol = _read_json(source)
    if protocol.get("schema_version") != "1.0":
        raise ValueError("temperature robustness protocol schema_version must be '1.0'")
    input_config = protocol["input"]
    primary_protocol = _repo_path(input_config["primary_protocol_path"])
    if sha256_file(primary_protocol) != input_config["primary_protocol_sha256"]:
        raise RuntimeError("primary mechanism protocol hash mismatch")
    report_path = _repo_path(input_config["primary_report_path"])
    primary_report = _read_json(report_path)
    _verify_fingerprint(primary_report, "report_fingerprint", "primary report")
    if (
        primary_report.get("analysis_protocol_sha256")
        != input_config["primary_protocol_sha256"]
    ):
        raise RuntimeError("primary report was built with a different protocol")
    for record in primary_report.get("sources", []):
        path = Path(record["path"]).resolve()
        if sha256_file(path) != record["sha256"]:
            raise RuntimeError(f"primary report source hash mismatch: {path}")
    if primary_report.get("source_count") != len(primary_report.get("sources", [])):
        raise RuntimeError("primary report source count mismatch")

    model = protocol["robustness_model"]
    permutation = model["permutation_test"]
    bootstrap = model["cluster_bootstrap"]
    multiplicity = model["multiplicity"]
    analysis = analyze_temperature_robustness(
        primary_report.get("analysis_records", []),
        primary_report.get("analysis", {}),
        descriptor_names=list(protocol["descriptor_names"]),
        response_names=list(protocol["response_names"]),
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
    report = {
        "schema_version": "1.0",
        "report_kind": "mechanism-categorical-temperature-robustness",
        "protocol_path": str(source),
        "protocol_sha256": sha256_file(source),
        "primary_report_path": str(report_path),
        "primary_report_sha256": sha256_file(report_path),
        "primary_report_fingerprint": primary_report["report_fingerprint"],
        "primary_input_gate_pass": primary_report.get("input_gate_pass") is True,
        "analysis": analysis,
        "robustness_completeness_gate_pass": bool(
            primary_report.get("input_gate_pass") is True
            and primary_report.get("analysis", {}).get("grid_gate_pass") is True
            and analysis["analysis_completeness_gate_pass"]
        ),
        "claim_rule": protocol["claim_rule"],
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
        "implementation_dependencies": [
            {
                "path": str(Path(__file__).with_name("mechanism_transport.py")),
                "sha256": sha256_file(
                    Path(__file__).with_name("mechanism_transport.py")
                ),
            },
            {
                "path": str(Path(__file__).with_name("provenance.py")),
                "sha256": sha256_file(Path(__file__).with_name("provenance.py")),
            },
        ],
    }
    report["report_fingerprint"] = fingerprint(report)
    return report


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    destination = Path(args.out).resolve()
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite robustness report: {destination}")
    report = build_temperature_robustness_report(args.protocol)
    atomic_write_json(destination, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
