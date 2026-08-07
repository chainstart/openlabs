"""Balanced velocity-within-occupancy inference for the 800 K LLZTO design."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .provenance import atomic_write_json, fingerprint, sha256_file


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def _nested_reml_components(
    values: np.ndarray,
    variances: np.ndarray,
    group_indices: np.ndarray,
    occupancy_variance: float,
    velocity_variance: float,
) -> tuple[float, float, float]:
    """Return REML negative log likelihood, GLS mean, and its variance."""
    if occupancy_variance < 0 or velocity_variance < 0:
        return float("inf"), float("nan"), float("nan")
    covariance = np.diag(variances + velocity_variance)
    covariance += occupancy_variance * (
        group_indices[:, None] == group_indices[None, :]
    )
    sign, log_determinant = np.linalg.slogdet(covariance)
    if sign <= 0 or not math.isfinite(float(log_determinant)):
        return float("inf"), float("nan"), float("nan")
    ones = np.ones(len(values))
    try:
        inverse_values = np.linalg.solve(covariance, values)
        inverse_ones = np.linalg.solve(covariance, ones)
    except np.linalg.LinAlgError:
        return float("inf"), float("nan"), float("nan")
    information = float(ones @ inverse_ones)
    if information <= 0 or not math.isfinite(information):
        return float("inf"), float("nan"), float("nan")
    mean = float(ones @ inverse_values / information)
    residual = values - mean
    quadratic = float(residual @ np.linalg.solve(covariance, residual))
    n_restricted = len(values) - 1
    nll = 0.5 * (
        float(log_determinant)
        + math.log(information)
        + quadratic
        + n_restricted * math.log(2.0 * math.pi)
    )
    return nll, mean, 1.0 / information


def _optimize_one_variance(
    objective: Any,
    *,
    upper: float,
) -> tuple[float, float]:
    from scipy.optimize import minimize_scalar

    optimized = minimize_scalar(
        objective,
        bounds=(0.0, upper),
        method="bounded",
        options={"xatol": 1e-11},
    )
    if not optimized.success:
        raise RuntimeError("one-component REML optimization failed")
    candidates = [(0.0, float(objective(0.0))), (float(optimized.x), float(optimized.fun))]
    return min(candidates, key=lambda item: item[1])


def _fit_nested_arrays(
    values: np.ndarray,
    variances: np.ndarray,
    group_indices: np.ndarray,
    *,
    confidence_level: float,
    force_occupancy_zero: bool = False,
) -> dict[str, Any]:
    from scipy.optimize import minimize
    from scipy.stats import t

    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level must be inside (0,1)")
    observed_variance = float(np.var(values, ddof=1))
    upper = max(1.0, observed_variance * 100.0, float(np.max(variances)) * 100.0)

    def evaluate(occupancy: float, velocity: float) -> float:
        return _nested_reml_components(
            values,
            variances,
            group_indices,
            occupancy,
            velocity,
        )[0]

    if force_occupancy_zero:
        velocity, nll = _optimize_one_variance(
            lambda value: evaluate(0.0, value),
            upper=upper,
        )
        occupancy = 0.0
    else:
        candidates: list[tuple[float, float, float]] = []
        velocity_boundary, boundary_nll = _optimize_one_variance(
            lambda value: evaluate(0.0, value),
            upper=upper,
        )
        candidates.append((0.0, velocity_boundary, boundary_nll))
        occupancy_boundary, boundary_nll = _optimize_one_variance(
            lambda value: evaluate(value, 0.0),
            upper=upper,
        )
        candidates.append((occupancy_boundary, 0.0, boundary_nll))
        candidates.append((0.0, 0.0, evaluate(0.0, 0.0)))
        starts = (
            (observed_variance / 2.0, observed_variance / 2.0),
            (observed_variance, 0.0),
            (0.0, observed_variance),
            (upper * 0.01, upper * 0.01),
        )
        for start in starts:
            optimized = minimize(
                lambda pair: evaluate(float(pair[0]), float(pair[1])),
                x0=np.asarray(start),
                method="L-BFGS-B",
                bounds=((0.0, upper), (0.0, upper)),
                options={"ftol": 1e-12, "gtol": 1e-9, "maxiter": 500},
            )
            if optimized.success and math.isfinite(float(optimized.fun)):
                candidates.append(
                    (
                        float(optimized.x[0]),
                        float(optimized.x[1]),
                        float(optimized.fun),
                    )
                )
        occupancy, velocity, nll = min(candidates, key=lambda item: item[2])
        boundary_tolerance = max(1e-12, upper * 1e-9)
        occupancy = 0.0 if occupancy < boundary_tolerance else occupancy
        velocity = 0.0 if velocity < boundary_tolerance else velocity
        nll = evaluate(occupancy, velocity)

    nll, mean, mean_variance = _nested_reml_components(
        values,
        variances,
        group_indices,
        occupancy,
        velocity,
    )
    n_groups = len(set(group_indices.tolist()))
    degrees_of_freedom = n_groups - 1
    alpha = 1.0 - confidence_level
    critical = float(t.ppf(1.0 - alpha / 2.0, degrees_of_freedom))
    mean_stderr = math.sqrt(mean_variance)
    typical_measurement_variance = float(np.mean(variances))
    latent_total = occupancy + velocity
    observed_total = latent_total + typical_measurement_variance
    return {
        "mean_log_value": mean,
        "mean_value_geometric": math.exp(mean),
        "mean_log_value_stderr": mean_stderr,
        "confidence_level": confidence_level,
        "mean_log_value_confidence_interval": [
            mean - critical * mean_stderr,
            mean + critical * mean_stderr,
        ],
        "mean_value_confidence_interval": [
            math.exp(mean - critical * mean_stderr),
            math.exp(mean + critical * mean_stderr),
        ],
        "occupancy_variance_log_scale": occupancy,
        "occupancy_sd_log_scale": math.sqrt(occupancy),
        "velocity_variance_log_scale": velocity,
        "velocity_sd_log_scale": math.sqrt(velocity),
        "typical_measurement_variance_log_scale": typical_measurement_variance,
        "latent_occupancy_fraction": occupancy / latent_total if latent_total > 0 else 0.0,
        "observed_occupancy_fraction": occupancy / observed_total if observed_total > 0 else 0.0,
        "restricted_negative_log_likelihood": nll,
        "n_observations": len(values),
        "n_occupancies": n_groups,
        "degrees_of_freedom_for_mean": degrees_of_freedom,
        "method": "heteroskedastic_nested_REML",
    }


def fit_nested_reml(
    values: list[float],
    variances: list[float],
    groups: list[int],
    *,
    confidence_level: float = 0.95,
) -> dict[str, Any]:
    """Fit log-scale occupancy and within-occupancy velocity variances."""
    y = np.asarray(values, dtype=float)
    known = np.asarray(variances, dtype=float)
    labels = np.asarray(groups, dtype=int)
    if y.ndim != 1 or known.shape != y.shape or labels.shape != y.shape:
        raise ValueError("nested REML inputs must be matched one-dimensional arrays")
    if len(y) < 6 or len(set(labels.tolist())) < 3:
        raise ValueError("nested REML requires at least three occupancy groups")
    if np.any(~np.isfinite(y)) or np.any(~np.isfinite(known)) or np.any(known <= 0):
        raise ValueError("nested REML values must be finite with positive variances")
    return _fit_nested_arrays(
        y,
        known,
        labels,
        confidence_level=confidence_level,
    )


def infer_nested_velocity(
    values: list[float],
    variances: list[float],
    groups: list[int],
    *,
    confidence_level: float,
    null_iterations: int,
    null_seed: int,
    interval_iterations: int,
    interval_seed: int,
    interval_quantiles: list[float],
    alpha: float,
) -> dict[str, Any]:
    """Fit the full model, test its occupancy boundary, and bootstrap intervals."""
    if null_iterations < 100 or interval_iterations < 100:
        raise ValueError("nested parametric bootstraps need at least 100 iterations")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be inside (0,1)")
    quantiles = np.asarray(interval_quantiles, dtype=float)
    if (
        quantiles.ndim != 1
        or len(quantiles) < 3
        or np.any(quantiles <= 0)
        or np.any(quantiles >= 1)
        or np.any(np.diff(quantiles) <= 0)
    ):
        raise ValueError("interval quantiles must increase strictly inside (0,1)")
    y = np.asarray(values, dtype=float)
    known = np.asarray(variances, dtype=float)
    labels = np.asarray(groups, dtype=int)
    full = fit_nested_reml(
        values,
        variances,
        groups,
        confidence_level=confidence_level,
    )
    null = _fit_nested_arrays(
        y,
        known,
        labels,
        confidence_level=confidence_level,
        force_occupancy_zero=True,
    )
    observed_lrt = max(
        0.0,
        2.0
        * (
            null["restricted_negative_log_likelihood"]
            - full["restricted_negative_log_likelihood"]
        ),
    )

    null_rng = np.random.default_rng(null_seed)
    null_statistics = np.empty(null_iterations)
    null_scale = np.sqrt(
        known + float(null["velocity_variance_log_scale"])
    )
    for index in range(null_iterations):
        simulated = null_rng.normal(float(null["mean_log_value"]), null_scale)
        simulated_full = _fit_nested_arrays(
            simulated,
            known,
            labels,
            confidence_level=confidence_level,
        )
        simulated_null = _fit_nested_arrays(
            simulated,
            known,
            labels,
            confidence_level=confidence_level,
            force_occupancy_zero=True,
        )
        null_statistics[index] = max(
            0.0,
            2.0
            * (
                simulated_null["restricted_negative_log_likelihood"]
                - simulated_full["restricted_negative_log_likelihood"]
            ),
        )
    p_value = float(
        (1 + np.count_nonzero(null_statistics >= observed_lrt))
        / (null_iterations + 1)
    )

    interval_rng = np.random.default_rng(interval_seed)
    unique_groups = sorted(set(labels.tolist()))
    occupancy_draws = np.empty(interval_iterations)
    velocity_draws = np.empty(interval_iterations)
    occupancy_sd = math.sqrt(float(full["occupancy_variance_log_scale"]))
    velocity_variance = float(full["velocity_variance_log_scale"])
    for index in range(interval_iterations):
        effects = {
            group: interval_rng.normal(0.0, occupancy_sd)
            for group in unique_groups
        }
        mean = float(full["mean_log_value"])
        simulated = np.asarray(
            [mean + effects[int(group)] for group in labels],
            dtype=float,
        )
        simulated += interval_rng.normal(0.0, np.sqrt(known + velocity_variance))
        fitted = _fit_nested_arrays(
            simulated,
            known,
            labels,
            confidence_level=confidence_level,
        )
        occupancy_draws[index] = fitted["occupancy_variance_log_scale"]
        velocity_draws[index] = fitted["velocity_variance_log_scale"]

    def interval(values_array: np.ndarray) -> dict[str, float]:
        return {
            str(quantile): float(value)
            for quantile, value in zip(quantiles, np.quantile(values_array, quantiles))
        }

    full["occupancy_variance_boundary_test"] = {
        "statistic": observed_lrt,
        "null_model": null,
        "method": "parametric_bootstrap_REML_likelihood_ratio",
        "iterations": null_iterations,
        "seed": null_seed,
        "p_value": p_value,
        "alpha": alpha,
        "occupancy_variance_supported": bool(
            p_value <= alpha and full["occupancy_variance_log_scale"] > 0
        ),
    }
    full["variance_interval_bootstrap"] = {
        "method": "parametric_bootstrap_fitted_full_model",
        "iterations": interval_iterations,
        "seed": interval_seed,
        "quantiles": interval_quantiles,
        "occupancy_variance_log_scale": interval(occupancy_draws),
        "velocity_variance_log_scale": interval(velocity_draws),
    }
    return full


def paired_log_ratio_variance(
    transport: dict[str, Any],
    *,
    expected_blocks: int,
    minimum_blocks: int,
) -> dict[str, Any]:
    """Estimate log-ratio uncertainty from matched non-overlapping blocks."""
    rows = transport.get("block_estimates")
    method = "explicit_block_indices"
    pairs: list[tuple[int, float, float]] = []
    if isinstance(rows, list) and rows:
        for row in rows:
            tracer = row.get("tracer_diffusivity_cm2_s")
            collective = row.get("collective_diffusivity_cm2_s")
            if (
                isinstance(tracer, (int, float))
                and isinstance(collective, (int, float))
                and tracer > 0
                and collective > 0
            ):
                pairs.append((int(row["block_index"]), float(tracer), float(collective)))
    else:
        tracer_values = transport.get("tracer", {}).get(
            "block_diffusivities_cm2_s", []
        )
        collective_values = transport.get("collective", {}).get(
            "block_diffusivities_cm2_s", []
        )
        if (
            len(tracer_values) == expected_blocks
            and len(collective_values) == expected_blocks
        ):
            method = "legacy_complete_block_order"
            pairs = [
                (index, float(tracer), float(collective))
                for index, (tracer, collective) in enumerate(
                    zip(tracer_values, collective_values)
                )
                if tracer > 0 and collective > 0
            ]
    if len(pairs) < minimum_blocks:
        raise ValueError(
            f"only {len(pairs)} paired positive tracer/collective blocks; "
            f"need at least {minimum_blocks}"
        )
    logs = np.asarray(
        [
            [math.log(tracer), math.log(collective)]
            for _, tracer, collective in pairs
        ]
    )
    covariance = np.cov(logs, rowvar=False, ddof=1) / len(pairs)
    contrast = np.asarray([-1.0, 1.0])
    ratio_variance = float(contrast @ covariance @ contrast)
    if not math.isfinite(ratio_variance) or ratio_variance <= 0:
        raise ValueError("paired log-ratio variance is not positive and finite")
    return {
        "variance_log_ratio": ratio_variance,
        "paired_log_diffusivity_covariance_of_mean": covariance.tolist(),
        "n_paired_blocks": len(pairs),
        "block_indices": [item[0] for item in pairs],
        "pairing_method": method,
    }


def analyze_balanced_records(
    records: list[dict[str, Any]],
    protocol: dict[str, Any],
) -> dict[str, Any]:
    """Analyze tracer, collective, and ratio without dropping any planned cell."""
    model = protocol["nested_velocity_inference"]
    design = protocol["sensitivity_roles"]["velocity_design"]
    expected_occupancies = int(design["occupancy_realizations"])
    expected_velocities = int(design["velocity_initializations_per_occupancy"])
    by_occupancy: dict[int, list[dict[str, Any]]] = {}
    for record in records:
        by_occupancy.setdefault(int(record["occupancy_seed"]), []).append(record)
    if sorted(by_occupancy) != list(range(expected_occupancies)):
        raise ValueError("velocity design does not contain the required occupancies")
    if any(len(items) != expected_velocities for items in by_occupancy.values()):
        raise ValueError("velocity design is not balanced within occupancy")
    if any(
        len({int(item["velocity_seed"]) for item in items}) != expected_velocities
        for items in by_occupancy.values()
    ):
        raise ValueError("velocity design repeats a velocity seed within occupancy")

    test = model["occupancy_variance_test"]
    intervals = model["variance_interval_bootstrap"]
    estimators: dict[str, Any] = {}
    for name in ("tracer", "collective", "collective_to_tracer_ratio"):
        try:
            values = []
            variances = []
            groups = []
            for occupancy in sorted(by_occupancy):
                for record in sorted(
                    by_occupancy[occupancy], key=lambda item: int(item["velocity_seed"])
                ):
                    measurement = record["estimators"][name]
                    if measurement.get("resolved") is not True:
                        raise ValueError(
                            f"{record['run_id']} is unresolved for {name}"
                        )
                    value = float(measurement["log_value"])
                    variance = float(measurement["variance_log_value"])
                    if not math.isfinite(value) or not math.isfinite(variance) or variance <= 0:
                        raise ValueError(f"invalid {name} estimate in {record['run_id']}")
                    values.append(value)
                    variances.append(variance)
                    groups.append(occupancy)
            estimators[name] = {
                **infer_nested_velocity(
                    values,
                    variances,
                    groups,
                    confidence_level=float(model["confidence_level"]),
                    null_iterations=int(test["iterations"]),
                    null_seed=int(test["seed"]),
                    interval_iterations=int(intervals["iterations"]),
                    interval_seed=int(intervals["seed"]),
                    interval_quantiles=intervals["quantiles"],
                    alpha=float(test["alpha"]),
                ),
                "analysis_gate_pass": True,
            }
        except (TypeError, ValueError, RuntimeError, np.linalg.LinAlgError) as exc:
            estimators[name] = {
                "analysis_gate_pass": False,
                "error": f"{type(exc).__name__}: {exc}",
                "required_action": model["hard_rules"]["unresolved_action"],
            }
    return {
        "n_records": len(records),
        "n_occupancies": len(by_occupancy),
        "velocity_initializations_per_occupancy": expected_velocities,
        "temperature_k": int(model["temperature_k"]),
        "estimators": estimators,
        "nested_velocity_gate_pass": all(
            result.get("analysis_gate_pass") is True
            for result in estimators.values()
        ),
    }


def _project_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parents[2] / path


def _load_run_record(
    run_dir: Path,
    *,
    run_id: str,
    temperature_k: int,
    minimum_ratio_blocks: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_path = run_dir / "run_manifest.json"
    result_path = run_dir / "result.json"
    transport_path = run_dir / f"T{temperature_k}.transport.json"
    manifest = _read_json(manifest_path)
    result = _read_json(result_path)
    transport_payload = _read_json(transport_path)
    protocol_fingerprint = manifest.get("protocol_fingerprint")
    if result.get("protocol_fingerprint") != protocol_fingerprint:
        raise RuntimeError(f"result/manifest fingerprint mismatch: {run_id}")
    if transport_payload.get("protocol_fingerprint") != protocol_fingerprint:
        raise RuntimeError(f"transport/manifest fingerprint mismatch: {run_id}")
    provenance = manifest.get("config", {}).get("provenance", {})
    if provenance.get("campaign_run_id") != run_id:
        raise RuntimeError(f"campaign run provenance mismatch: {run_id}")
    points = [
        point
        for point in result.get("points", [])
        if int(point.get("temperature", -1)) == temperature_k
    ]
    if len(points) != 1:
        raise ValueError(f"{run_id} does not contain exactly one {temperature_k} K point")
    point = points[0]
    config = manifest["config"]
    def finite_number(value: Any) -> float | None:
        if not isinstance(value, (int, float)):
            return None
        converted = float(value)
        return converted if math.isfinite(converted) else None

    tracer = finite_number(point.get("diffusivity_cm2_s"))
    tracer_stderr = finite_number(point.get("diffusivity_stderr_cm2_s"))
    collective = finite_number(point.get("collective_diffusivity_cm2_s"))
    collective_stderr = finite_number(
        point.get("collective_diffusivity_stderr_cm2_s")
    )
    ratio = finite_number(point.get("collective_to_tracer_ratio"))
    ratio_uncertainty: dict[str, Any] | None = None
    ratio_error: str | None = None
    try:
        ratio_uncertainty = paired_log_ratio_variance(
            transport_payload["transport"],
            expected_blocks=int(config["uncertainty_blocks"]),
            minimum_blocks=minimum_ratio_blocks,
        )
    except (KeyError, TypeError, ValueError) as exc:
        ratio_error = f"{type(exc).__name__}: {exc}"
    record = {
        "run_id": run_id,
        "campaign_id": provenance.get("campaign_id"),
        "campaign_protocol_sha256": provenance.get("campaign_protocol_sha256"),
        "occupancy_seed": int(config["occupancy_seed"]),
        "velocity_seed": int(config["seed"]),
        "prepared_structure_sha256": manifest.get("prepared_structure_sha256"),
        "relaxed_structure_sha256": result.get("relaxation", {}).get(
            "output_structure_sha256"
        ),
        "physical_config": {
            key: config.get(key)
            for key in (
                "timestep_fs",
                "equilibration_steps",
                "production_steps",
                "loginterval",
                "equilibration_ensemble",
                "production_ensemble",
                "thermostat",
                "thermostat_tau_fs",
                "fit_from_fraction",
                "fit_to_fraction",
                "max_lags",
                "uncertainty_blocks",
                "min_final_msd_a2",
                "min_diffusive_exponent",
                "max_diffusive_exponent",
                "max_relative_diffusivity_stderr",
            )
        },
        "relaxation_performed": bool(
            result.get("relaxation", {}).get("performed", False)
        ),
        "source_structure_sha256": result.get("structure", {}).get("source_sha256"),
        "estimators": {
            "tracer": {
                "value": tracer,
                "log_value": (
                    math.log(tracer)
                    if tracer is not None and tracer > 0
                    else None
                ),
                "variance_log_value": (
                    (tracer_stderr / tracer) ** 2
                    if tracer is not None
                    and tracer_stderr is not None
                    and tracer > 0
                    else None
                ),
                "resolved": point.get("resolved") is True,
            },
            "collective": {
                "value": collective,
                "log_value": (
                    math.log(collective)
                    if collective is not None and collective > 0
                    else None
                ),
                "variance_log_value": (
                    (collective_stderr / collective) ** 2
                    if collective is not None
                    and collective_stderr is not None
                    and collective > 0
                    else None
                ),
                "resolved": point.get("collective_resolved") is True,
            },
            "collective_to_tracer_ratio": {
                "value": ratio,
                "log_value": (
                    math.log(ratio)
                    if ratio is not None and ratio > 0
                    else None
                ),
                "variance_log_value": (
                    ratio_uncertainty["variance_log_ratio"]
                    if ratio_uncertainty is not None
                    else None
                ),
                "resolved": bool(
                    point.get("resolved") is True
                    and point.get("collective_resolved") is True
                    and ratio_uncertainty is not None
                ),
                "paired_block_uncertainty": ratio_uncertainty,
                "paired_block_error": ratio_error,
            },
        },
    }
    source = {
        "source_kind": "md_run",
        "run_id": run_id,
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": sha256_file(manifest_path),
        "result_path": str(result_path.resolve()),
        "result_sha256": sha256_file(result_path),
        "transport_path": str(transport_path.resolve()),
        "transport_sha256": sha256_file(transport_path),
    }
    return record, source


def collect_velocity_records(protocol: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load and verify the five reference plus ten matched supplemental cells."""
    design = protocol["sensitivity_roles"]["velocity_design"]
    model = protocol["nested_velocity_inference"]
    primary_root = _project_path(design["reference_campaign_root"])
    supplemental_root = _project_path(design["supplemental_campaign_root"])
    reference_protocol_path = _project_path(design["reference_protocol_path"])
    supplemental_protocol_path = _project_path(design["supplemental_protocol_path"])
    reference_protocol = _read_json(reference_protocol_path)
    supplemental_protocol = _read_json(supplemental_protocol_path)
    temperature = int(model["temperature_k"])
    minimum_blocks = int(model["hard_rules"]["minimum_paired_ratio_blocks"])
    records = []
    sources = [
        {
            "source_kind": "campaign_protocol",
            "campaign_id": reference_protocol["campaign_id"],
            "path": str(reference_protocol_path.resolve()),
            "sha256": sha256_file(reference_protocol_path),
        },
        {
            "source_kind": "campaign_protocol",
            "campaign_id": supplemental_protocol["campaign_id"],
            "path": str(supplemental_protocol_path.resolve()),
            "sha256": sha256_file(supplemental_protocol_path),
        },
    ]
    primary_by_occupancy: dict[int, tuple[dict[str, Any], Path]] = {}
    for run_id in protocol["formal_run_ids"]:
        run_dir = primary_root / run_id
        record, source = _load_run_record(
            run_dir,
            run_id=run_id,
            temperature_k=temperature,
            minimum_ratio_blocks=minimum_blocks,
        )
        if (
            record["campaign_id"] != reference_protocol["campaign_id"]
            or record["campaign_protocol_sha256"]
            != sha256_file(reference_protocol_path)
        ):
            raise RuntimeError(f"primary campaign provenance mismatch: {run_id}")
        occupancy = int(record["occupancy_seed"])
        if occupancy in primary_by_occupancy:
            raise ValueError("primary velocity design repeats an occupancy")
        relaxed_path = run_dir / "relaxed.structure.json"
        source["relaxed_structure_path"] = str(relaxed_path.resolve())
        source["relaxed_structure_sha256"] = sha256_file(relaxed_path)
        primary_by_occupancy[occupancy] = (record, relaxed_path)
        records.append(record)
        sources.append(source)

    for spec in supplemental_protocol["runs"]:
        run_id = spec["run_id"]
        record, source = _load_run_record(
            supplemental_root / run_id,
            run_id=run_id,
            temperature_k=temperature,
            minimum_ratio_blocks=minimum_blocks,
        )
        if (
            record["campaign_id"] != supplemental_protocol["campaign_id"]
            or record["campaign_protocol_sha256"]
            != sha256_file(supplemental_protocol_path)
        ):
            raise RuntimeError(f"supplemental campaign provenance mismatch: {run_id}")
        occupancy = int(record["occupancy_seed"])
        if occupancy not in primary_by_occupancy:
            raise ValueError(f"supplemental cell has unknown occupancy {occupancy}")
        primary, relaxed_path = primary_by_occupancy[occupancy]
        if not relaxed_path.is_file():
            raise FileNotFoundError(relaxed_path)
        if record["relaxation_performed"]:
            raise ValueError(f"supplemental cell repeated relaxation: {run_id}")
        if record["prepared_structure_sha256"] != primary["relaxed_structure_sha256"]:
            raise ValueError(f"supplemental cell does not match primary structure: {run_id}")
        if record["source_structure_sha256"] != sha256_file(relaxed_path):
            raise ValueError(f"supplemental source hash mismatch: {run_id}")
        if record["physical_config"] != primary["physical_config"]:
            raise ValueError(f"supplemental physical protocol mismatch: {run_id}")
        records.append(record)
        sources.append(source)
    return records, sources


def build_velocity_report(analysis_protocol_path: Path | str) -> dict[str, Any]:
    """Build the immutable balanced nested-velocity report."""
    protocol_path = Path(analysis_protocol_path).resolve()
    protocol = _read_json(protocol_path)
    if protocol.get("schema_version") != "1.0":
        raise ValueError("hierarchical protocol schema_version must be '1.0'")
    records, sources = collect_velocity_records(protocol)
    result = analyze_balanced_records(records, protocol)
    report = {
        "schema_version": "1.0",
        "report_kind": "nested-velocity-within-occupancy",
        "analysis_protocol_path": str(protocol_path),
        "analysis_protocol_sha256": sha256_file(protocol_path),
        "records": records,
        "sources": sources,
        "result": result,
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
    }
    report["report_fingerprint"] = fingerprint(report)
    return report


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = build_velocity_report(args.protocol)
    destination = Path(args.out).resolve()
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite nested-velocity report: {destination}")
    atomic_write_json(destination, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
