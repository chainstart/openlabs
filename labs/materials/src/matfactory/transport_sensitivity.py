"""Finite-size and volume sensitivity inference for formal LLZTO transport."""

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


def _point(result: dict[str, Any], temperature_k: int) -> dict[str, Any]:
    matches = [
        point
        for point in result.get("points", [])
        if int(point.get("temperature", -1)) == temperature_k
    ]
    if len(matches) != 1:
        raise ValueError(
            f"result contains {len(matches)} points at {temperature_k} K"
        )
    return matches[0]


def estimator_block_logs(
    point: dict[str, Any],
    transport: dict[str, Any],
    estimator: str,
    *,
    expected_blocks: int,
    minimum_blocks: int,
) -> dict[str, Any]:
    """Extract a central estimate and matched non-overlapping block log values."""
    if estimator == "tracer":
        resolved = point.get("resolved") is True
        central = point.get("diffusivity_cm2_s")
    elif estimator == "collective":
        resolved = point.get("collective_resolved") is True
        central = point.get("collective_diffusivity_cm2_s")
    elif estimator == "collective_to_tracer_ratio":
        resolved = bool(
            point.get("resolved") is True
            and point.get("collective_resolved") is True
        )
        central = point.get("collective_to_tracer_ratio")
    else:
        raise ValueError(f"unknown transport estimator {estimator}")
    if not resolved:
        raise ValueError(f"{estimator} is unresolved")
    if not isinstance(central, (int, float)) or float(central) <= 0:
        raise ValueError(f"{estimator} central estimate is not positive")

    transport_estimate = transport.get("transport", transport)
    explicit = transport_estimate.get("block_estimates")
    values: list[tuple[int, float]] = []
    method = "explicit_block_indices"
    if isinstance(explicit, list) and explicit:
        for row in explicit:
            tracer = row.get("tracer_diffusivity_cm2_s")
            collective = row.get("collective_diffusivity_cm2_s")
            if estimator == "tracer":
                value = tracer
            elif estimator == "collective":
                value = collective
            elif (
                isinstance(tracer, (int, float))
                and isinstance(collective, (int, float))
                and tracer > 0
                and collective > 0
            ):
                value = collective / tracer
            else:
                value = None
            if isinstance(value, (int, float)) and value > 0:
                values.append((int(row["block_index"]), float(value)))
    else:
        tracer_values = transport_estimate.get("tracer", {}).get(
            "block_diffusivities_cm2_s", []
        )
        collective_values = transport_estimate.get("collective", {}).get(
            "block_diffusivities_cm2_s", []
        )
        method = "legacy_positive_block_order"
        if estimator == "tracer":
            values = [
                (index, float(value))
                for index, value in enumerate(tracer_values)
                if value > 0
            ]
        elif estimator == "collective":
            values = [
                (index, float(value))
                for index, value in enumerate(collective_values)
                if value > 0
            ]
        elif (
            len(tracer_values) == expected_blocks
            and len(collective_values) == expected_blocks
        ):
            method = "legacy_complete_paired_block_order"
            values = [
                (index, float(collective / tracer))
                for index, (tracer, collective) in enumerate(
                    zip(tracer_values, collective_values)
                )
                if tracer > 0 and collective > 0
            ]
    if len(values) < minimum_blocks:
        raise ValueError(
            f"{estimator} has only {len(values)} positive block estimates; "
            f"need at least {minimum_blocks}"
        )
    return {
        "central_value": float(central),
        "central_log_value": math.log(float(central)),
        "block_indices": [index for index, _value in values],
        "block_log_values": [math.log(value) for _index, value in values],
        "n_blocks": len(values),
        "block_method": method,
    }


def bootstrap_log_effect(
    reference: dict[str, Any],
    comparison: dict[str, Any],
    *,
    iterations: int,
    seed: int,
    quantiles: list[float],
    equivalence_ratio_margin: float,
) -> dict[str, Any]:
    """Center a two-sample block bootstrap on the full-trajectory log effect."""
    if iterations < 100:
        raise ValueError("sensitivity block bootstrap needs at least 100 iterations")
    requested = np.asarray(quantiles, dtype=float)
    if (
        requested.ndim != 1
        or len(requested) < 3
        or np.any(requested <= 0)
        or np.any(requested >= 1)
        or np.any(np.diff(requested) <= 0)
    ):
        raise ValueError("bootstrap quantiles must increase strictly inside (0,1)")
    if equivalence_ratio_margin <= 1:
        raise ValueError("equivalence ratio margin must exceed one")
    reference_blocks = np.asarray(reference["block_log_values"], dtype=float)
    comparison_blocks = np.asarray(comparison["block_log_values"], dtype=float)
    if len(reference_blocks) < 2 or len(comparison_blocks) < 2:
        raise ValueError("each sensitivity arm needs at least two blocks")
    central_effect = float(
        comparison["central_log_value"] - reference["central_log_value"]
    )
    observed_block_effect = float(
        np.mean(comparison_blocks) - np.mean(reference_blocks)
    )
    rng = np.random.default_rng(seed)
    draws = np.empty(iterations)
    for index in range(iterations):
        sampled_reference = rng.choice(
            reference_blocks, size=len(reference_blocks), replace=True
        )
        sampled_comparison = rng.choice(
            comparison_blocks, size=len(comparison_blocks), replace=True
        )
        raw = float(np.mean(sampled_comparison) - np.mean(sampled_reference))
        draws[index] = central_effect + raw - observed_block_effect
    results = np.quantile(draws, requested)
    log_margin = math.log(equivalence_ratio_margin)
    lower = float(results[0])
    upper = float(results[-1])
    return {
        "central_log_effect": central_effect,
        "central_ratio": math.exp(central_effect),
        "block_mean_log_effect": observed_block_effect,
        "central_minus_block_mean_log_effect": central_effect
        - observed_block_effect,
        "bootstrap": {
            "iterations": iterations,
            "seed": seed,
            "method": "independent_within_run_block_resampling_centered_on_full_estimate",
            "log_effect_quantiles": {
                str(quantile): float(value)
                for quantile, value in zip(requested, results)
            },
            "ratio_quantiles": {
                str(quantile): float(math.exp(value))
                for quantile, value in zip(requested, results)
            },
        },
        "equivalence_ratio_margin": equivalence_ratio_margin,
        "equivalence_interval": [
            1.0 / equivalence_ratio_margin,
            equivalence_ratio_margin,
        ],
        "equivalence_supported": bool(lower >= -log_margin and upper <= log_margin),
        "reference_blocks": {
            key: reference[key]
            for key in ("n_blocks", "block_indices", "block_method")
        },
        "comparison_blocks": {
            key: comparison[key]
            for key in ("n_blocks", "block_indices", "block_method")
        },
    }


def _load_run(
    run_dir: Path,
    run_id: str,
    temperatures: list[int],
    *,
    expected_campaign_id: str,
    expected_protocol_sha256: str,
) -> dict[str, Any]:
    manifest_path = run_dir / "run_manifest.json"
    result_path = run_dir / "result.json"
    manifest = _read_json(manifest_path)
    result = _read_json(result_path)
    run_fingerprint = manifest.get("protocol_fingerprint")
    if result.get("protocol_fingerprint") != run_fingerprint:
        raise RuntimeError(f"result/manifest fingerprint mismatch: {run_id}")
    provenance = manifest.get("config", {}).get("provenance", {})
    if (
        provenance.get("campaign_run_id") != run_id
        or provenance.get("campaign_id") != expected_campaign_id
        or provenance.get("campaign_protocol_sha256") != expected_protocol_sha256
    ):
        raise RuntimeError(f"campaign provenance mismatch: {run_id}")
    transports = {}
    transport_sources = []
    for temperature in temperatures:
        path = run_dir / f"T{temperature}.transport.json"
        payload = _read_json(path)
        if payload.get("protocol_fingerprint") != run_fingerprint:
            raise RuntimeError(f"transport/manifest fingerprint mismatch: {run_id}")
        transports[temperature] = payload
        transport_sources.append(
            {
                "temperature_k": temperature,
                "path": str(path.resolve()),
                "sha256": sha256_file(path),
            }
        )
    return {
        "run_id": run_id,
        "run_dir": str(run_dir.resolve()),
        "manifest": manifest,
        "result": result,
        "transports": transports,
        "source": {
            "run_id": run_id,
            "manifest_path": str(manifest_path.resolve()),
            "manifest_sha256": sha256_file(manifest_path),
            "result_path": str(result_path.resolve()),
            "result_sha256": sha256_file(result_path),
            "transport": transport_sources,
        },
    }


def _physical_config(run: dict[str, Any]) -> dict[str, Any]:
    config = run["manifest"]["config"]
    return {
        key: config.get(key)
        for key in (
            "timestep_fs",
            "equilibration_steps",
            "production_steps",
            "loginterval",
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
    }


def _compare(
    reference: dict[str, Any],
    comparison: dict[str, Any],
    *,
    temperature_k: int,
    protocol: dict[str, Any],
    seed_offset: int,
    ratio_margin: float,
) -> dict[str, Any]:
    bootstrap = protocol["sensitivity_inference"]["block_bootstrap"]
    outputs = {}
    for estimator_index, estimator in enumerate(
        ("tracer", "collective", "collective_to_tracer_ratio")
    ):
        try:
            reference_values = estimator_block_logs(
                _point(reference["result"], temperature_k),
                reference["transports"][temperature_k],
                estimator,
                expected_blocks=int(
                    reference["manifest"]["config"]["uncertainty_blocks"]
                ),
                minimum_blocks=int(
                    bootstrap["minimum_positive_blocks_per_estimator"]
                ),
            )
            comparison_values = estimator_block_logs(
                _point(comparison["result"], temperature_k),
                comparison["transports"][temperature_k],
                estimator,
                expected_blocks=int(
                    comparison["manifest"]["config"]["uncertainty_blocks"]
                ),
                minimum_blocks=int(
                    bootstrap["minimum_positive_blocks_per_estimator"]
                ),
            )
            outputs[estimator] = {
                "analysis_gate_pass": True,
                **bootstrap_log_effect(
                    reference_values,
                    comparison_values,
                    iterations=int(bootstrap["iterations"]),
                    seed=int(bootstrap["seed"]) + seed_offset + estimator_index,
                    quantiles=bootstrap["quantiles"],
                    equivalence_ratio_margin=ratio_margin,
                ),
            }
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            outputs[estimator] = {
                "analysis_gate_pass": False,
                "error": f"{type(exc).__name__}: {exc}",
                "required_action": protocol["sensitivity_inference"]["hard_rules"][
                    "missing_or_unresolved_action"
                ],
            }
    return {
        "temperature_k": temperature_k,
        "reference_run_id": reference["run_id"],
        "comparison_run_id": comparison["run_id"],
        "estimators": outputs,
        "comparison_gate_pass": all(
            value.get("analysis_gate_pass") is True for value in outputs.values()
        ),
    }


def _activation_difference(
    reference: dict[str, Any],
    comparison: dict[str, Any],
    estimator: str,
    *,
    margin_ev: float,
) -> dict[str, Any]:
    field = "arrhenius" if estimator == "tracer" else "arrhenius_collective"
    reference_fit = reference["result"].get(field)
    comparison_fit = comparison["result"].get(field)
    if not isinstance(reference_fit, dict) or not isinstance(comparison_fit, dict):
        raise ValueError(f"resolved {estimator} Arrhenius fits are unavailable")
    difference = float(comparison_fit["activation_energy_ev"]) - float(
        reference_fit["activation_energy_ev"]
    )
    reference_stderr = float(reference_fit["activation_energy_stderr_ev"])
    comparison_stderr = float(comparison_fit["activation_energy_stderr_ev"])
    return {
        "comparison_minus_reference_ev": difference,
        "approximate_independent_stderr_ev": math.sqrt(
            reference_stderr**2 + comparison_stderr**2
        ),
        "absolute_difference_margin_ev": margin_ev,
        "within_margin": bool(abs(difference) <= margin_ev),
        "uncertainty_note": (
            "The standard error is an independent-fit approximation; the hard "
            "robustness rule applies to the preregistered absolute point difference."
        ),
    }


def _fixed_volume(result: dict[str, Any]) -> float:
    value = (
        result.get("relaxation", {})
        .get("final_summary", {})
        .get("volume_angstrom3")
    )
    if not isinstance(value, (int, float)) or value <= 0:
        raise ValueError("run has no positive relaxed reference volume")
    return float(value)


def _production_volume(transport: dict[str, Any]) -> dict[str, Any]:
    diagnostics = transport.get("trajectory_diagnostics", {})
    mean = diagnostics.get("volume_mean_angstrom3")
    std = diagnostics.get("volume_std_angstrom3")
    if not isinstance(mean, (int, float)) or mean <= 0:
        raise ValueError("transport diagnostics have no positive production volume")
    return {
        "mean_angstrom3": float(mean),
        "std_angstrom3": float(std) if isinstance(std, (int, float)) else None,
    }


def _project_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parents[2] / path


def build_sensitivity_report(analysis_protocol_path: Path | str) -> dict[str, Any]:
    """Build finite-size, fixed-volume, and NPT-volume sensitivity evidence."""
    protocol_path = Path(analysis_protocol_path).resolve()
    protocol = _read_json(protocol_path)
    roles = protocol["sensitivity_roles"]
    inference = protocol["sensitivity_inference"]
    temperature = int(inference["temperature_k"])
    formal_protocol_path = _project_path(protocol["formal_campaign_protocol_path"])
    size_protocol_path = _project_path(roles["finite_size_protocol_path"])
    fixed_protocol_path = _project_path(
        roles["fixed_experimental_volume_protocol_path"]
    )
    formal_protocol = _read_json(formal_protocol_path)
    size_protocol = _read_json(size_protocol_path)
    fixed_protocol = _read_json(fixed_protocol_path)
    formal_sha = sha256_file(formal_protocol_path)
    size_sha = sha256_file(size_protocol_path)
    fixed_sha = sha256_file(fixed_protocol_path)
    formal_root = _project_path(protocol["formal_campaign_root"])
    size_root = _project_path(roles["finite_size_campaign_root"])
    fixed_root = _project_path(roles["fixed_experimental_volume_campaign_root"])

    primary_id = roles["finite_size_reference_run_id"]
    size_id = roles["finite_size_run_id"]
    fixed_id = roles["fixed_experimental_volume_run_id"]
    npt_id = roles["npt_volume_run_id"]
    temperatures = [int(value) for value in protocol["required_temperatures_k"]]
    primary = _load_run(
        formal_root / primary_id,
        primary_id,
        temperatures,
        expected_campaign_id=formal_protocol["campaign_id"],
        expected_protocol_sha256=formal_sha,
    )
    size = _load_run(
        size_root / size_id,
        size_id,
        [temperature],
        expected_campaign_id=size_protocol["campaign_id"],
        expected_protocol_sha256=size_sha,
    )
    fixed = _load_run(
        fixed_root / fixed_id,
        fixed_id,
        [temperature],
        expected_campaign_id=fixed_protocol["campaign_id"],
        expected_protocol_sha256=fixed_sha,
    )
    npt = _load_run(
        formal_root / npt_id,
        npt_id,
        temperatures,
        expected_campaign_id=formal_protocol["campaign_id"],
        expected_protocol_sha256=formal_sha,
    )
    if _physical_config(size) != _physical_config(primary):
        raise ValueError("matched finite-size physical MD settings differ")
    if _physical_config(fixed) != _physical_config(primary):
        raise ValueError("fixed-experimental-volume physical MD settings differ")
    if _physical_config(npt) != _physical_config(primary):
        raise ValueError("NPT-volume production/analysis MD settings differ")
    parent_hash = (
        size["manifest"]
        .get("structure", {})
        .get("derived_structure_provenance", {})
        .get("parent_structure_sha256")
    )
    if parent_hash != primary["manifest"].get("prepared_structure_sha256"):
        raise ValueError("finite-size supercell parent does not match primary structure")

    finite_margin = float(inference["finite_size_equivalence"]["ratio_margin"])
    volume_margin = float(inference["volume_robustness"]["ratio_margin"])
    finite_size = _compare(
        primary,
        size,
        temperature_k=temperature,
        protocol=protocol,
        seed_offset=0,
        ratio_margin=finite_margin,
    )
    fixed_volume = _compare(
        primary,
        fixed,
        temperature_k=temperature,
        protocol=protocol,
        seed_offset=100,
        ratio_margin=volume_margin,
    )
    fixed_volume_robust = bool(
        fixed_volume["comparison_gate_pass"]
        and all(
            row.get("equivalence_supported") is True
            for row in fixed_volume["estimators"].values()
        )
    )
    npt_by_temperature = []
    for index, current_temperature in enumerate(temperatures):
        comparison = _compare(
            primary,
            npt,
            temperature_k=current_temperature,
            protocol=protocol,
            seed_offset=200 + index * 10,
            ratio_margin=volume_margin,
        )
        comparison["reference_volume"] = _production_volume(
            primary["transports"][current_temperature]
        )
        comparison["comparison_volume"] = _production_volume(
            npt["transports"][current_temperature]
        )
        comparison["volume_ratio"] = (
            comparison["comparison_volume"]["mean_angstrom3"]
            / comparison["reference_volume"]["mean_angstrom3"]
        )
        npt_by_temperature.append(comparison)
    activation = {}
    activation_margin = float(
        inference["volume_robustness"]["activation_energy_difference_margin_ev"]
    )
    for estimator in ("tracer", "collective"):
        try:
            activation[estimator] = {
                "analysis_gate_pass": True,
                **_activation_difference(
                    primary,
                    npt,
                    estimator,
                    margin_ev=activation_margin,
                ),
            }
        except (KeyError, TypeError, ValueError) as exc:
            activation[estimator] = {
                "analysis_gate_pass": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
    npt_effects_robust = all(
        estimator.get("analysis_gate_pass") is True
        and estimator.get("equivalence_supported") is True
        for comparison in npt_by_temperature
        for estimator in comparison["estimators"].values()
    )
    activation_robust = all(
        row.get("analysis_gate_pass") is True and row.get("within_margin") is True
        for row in activation.values()
    )
    report = {
        "schema_version": "1.0",
        "report_kind": "transport-sensitivity",
        "analysis_protocol_path": str(protocol_path),
        "analysis_protocol_sha256": sha256_file(protocol_path),
        "formal_campaign_protocol_path": str(formal_protocol_path.resolve()),
        "formal_campaign_protocol_sha256": formal_sha,
        "finite_size_campaign_protocol_path": str(size_protocol_path.resolve()),
        "finite_size_campaign_protocol_sha256": size_sha,
        "fixed_volume_campaign_protocol_path": str(fixed_protocol_path.resolve()),
        "fixed_volume_campaign_protocol_sha256": fixed_sha,
        "finite_size": {
            **finite_size,
            "reference_n_sites": primary["result"]["structure"][
                "prepared_summary"
            ]["n_sites"],
            "comparison_n_sites": size["result"]["structure"][
                "prepared_summary"
            ]["n_sites"],
            "finite_size_equivalence_gate_pass": bool(
                finite_size["comparison_gate_pass"]
                and all(
                    row.get("equivalence_supported") is True
                    for row in finite_size["estimators"].values()
                )
            ),
        },
        "fixed_experimental_volume": {
            **fixed_volume,
            "reference_volume_angstrom3": _fixed_volume(primary["result"]),
            "comparison_volume_angstrom3": _fixed_volume(fixed["result"]),
            "fixed_volume_robustness_gate_pass": fixed_volume_robust,
        },
        "npt_volume": {
            "by_temperature": npt_by_temperature,
            "activation_energy_difference": activation,
            "transport_effects_within_margin": npt_effects_robust,
            "activation_energy_differences_within_margin": activation_robust,
            "volume_robustness_gate_pass": bool(
                npt_effects_robust and activation_robust
            ),
        },
        "sources": [
            primary["source"],
            size["source"],
            fixed["source"],
            npt["source"],
        ],
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
    }
    report["sensitivity_gate_pass"] = bool(
        report["finite_size"]["finite_size_equivalence_gate_pass"]
        and report["fixed_experimental_volume"][
            "fixed_volume_robustness_gate_pass"
        ]
        and report["npt_volume"]["volume_robustness_gate_pass"]
    )
    report["report_fingerprint"] = fingerprint(report)
    return report


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = build_sensitivity_report(args.protocol)
    destination = Path(args.out).resolve()
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite sensitivity report: {destination}")
    atomic_write_json(destination, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
