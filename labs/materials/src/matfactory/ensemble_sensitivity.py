"""Matched NVT-versus-NVE production-ensemble sensitivity for LLZTO."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .provenance import atomic_write_json, fingerprint, sha256_file
from .transport_sensitivity import (
    _load_run,
    _point,
    bootstrap_log_effect,
    estimator_block_logs,
)


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


def _load_protocol_campaign(config: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    path = _repo_path(config["campaign_protocol_path"])
    if sha256_file(path) != config["campaign_protocol_sha256"]:
        raise RuntimeError(f"campaign protocol hash mismatch: {path}")
    payload = _read_json(path)
    if payload.get("campaign_id") != config["campaign_id"]:
        raise RuntimeError(f"campaign id mismatch: {path}")
    return path, payload


def _matched_config_checks(
    reference: dict[str, Any],
    comparison: dict[str, Any],
    protocol: dict[str, Any],
) -> dict[str, bool]:
    reference_config = reference["manifest"]["config"]
    comparison_config = comparison["manifest"]["config"]
    temperature = int(protocol["temperature_k"])
    fields = protocol["matched_design"]["required_equal_config_fields"]
    observed_differences = {
        key
        for key in set(reference_config) | set(comparison_config)
        if reference_config.get(key) != comparison_config.get(key)
    }
    expected_differences = set(
        protocol["matched_design"]["expected_config_differences"]
    )
    checks = {
        f"equal:{field}": reference_config.get(field) == comparison_config.get(field)
        for field in fields
    }
    checks.update(
        observed_config_differences_are_exactly_preregistered=(
            observed_differences == expected_differences
        ),
        reference_contains_analysis_temperature=(
            temperature in reference_config.get("temperatures", [])
        ),
        comparison_contains_only_analysis_temperature=(
            list(comparison_config.get("temperatures", [])) == [temperature]
        ),
        reference_is_nvt=(
            reference_config.get("production_ensemble")
            == protocol["reference"]["production_ensemble"]
        ),
        comparison_is_nve=(
            comparison_config.get("production_ensemble")
            == protocol["comparison"]["production_ensemble"]
        ),
    )
    reference_relaxed = reference["result"].get("relaxation", {}).get(
        "output_structure_sha256"
    )
    comparison_prepared = comparison["manifest"].get("prepared_structure_sha256")
    comparison_relaxed = comparison["result"].get("relaxation", {}).get(
        "output_structure_sha256"
    )
    comparison_result_prepared = comparison["result"].get("structure", {}).get(
        "prepared_structure_sha256"
    )
    checks.update(
        reference_relaxation_performed=(
            reference["result"].get("relaxation", {}).get("performed") is True
        ),
        reference_relaxation_converged=(
            reference["result"].get("relaxation", {}).get("converged") is True
        ),
        comparison_reuses_reference_relaxed_structure=(
            isinstance(reference_relaxed, str)
            and comparison_prepared == reference_relaxed
            and comparison_result_prepared == reference_relaxed
            and comparison_relaxed == reference_relaxed
        ),
        comparison_relaxation_disabled=(
            comparison["result"].get("relaxation", {}).get("performed") is False
            and comparison_config.get("relax_structure") is False
            and comparison_config.get("relax_cell") is False
        ),
    )
    return checks


def build_ensemble_sensitivity_report(protocol_path: Path | str) -> dict[str, Any]:
    """Build a block-bootstrap NVE/NVT equivalence report at 800 K."""
    source = Path(protocol_path).resolve()
    protocol = _read_json(source)
    if protocol.get("schema_version") != "1.0":
        raise ValueError("ensemble sensitivity protocol schema_version must be '1.0'")
    temperature = int(protocol["temperature_k"])
    reference_config = protocol["reference"]
    comparison_config = protocol["comparison"]
    reference_protocol_path, _ = _load_protocol_campaign(reference_config)
    comparison_protocol_path, _ = _load_protocol_campaign(comparison_config)
    reference = _load_run(
        _repo_path(reference_config["campaign_root"]) / reference_config["run_id"],
        reference_config["run_id"],
        [temperature],
        expected_campaign_id=reference_config["campaign_id"],
        expected_protocol_sha256=reference_config["campaign_protocol_sha256"],
    )
    comparison = _load_run(
        _repo_path(comparison_config["campaign_root"]) / comparison_config["run_id"],
        comparison_config["run_id"],
        [temperature],
        expected_campaign_id=comparison_config["campaign_id"],
        expected_protocol_sha256=comparison_config["campaign_protocol_sha256"],
    )
    matched_checks = _matched_config_checks(reference, comparison, protocol)
    if not all(matched_checks.values()):
        failed = [name for name, passed in matched_checks.items() if not passed]
        raise RuntimeError("ensemble matched-design failure: " + ", ".join(failed))

    comparison_transport = comparison["transports"][temperature]
    diagnostics = comparison_transport.get("trajectory_diagnostics", {})
    drift = diagnostics.get("total_energy_drift_mev_atom_ps")
    mean_temperature = diagnostics.get("temperature_mean_k")
    stability = protocol["nve_stability"]
    stability_checks = {
        "energy_drift_available": isinstance(drift, (int, float))
        and math.isfinite(float(drift)),
        "energy_drift_within_limit": isinstance(drift, (int, float))
        and math.isfinite(float(drift))
        and abs(float(drift))
        <= float(stability["maximum_absolute_energy_drift_mev_atom_ps"]),
        "temperature_available": isinstance(mean_temperature, (int, float))
        and math.isfinite(float(mean_temperature)),
        "temperature_within_limit": isinstance(mean_temperature, (int, float))
        and math.isfinite(float(mean_temperature))
        and abs(float(mean_temperature) - temperature) / temperature
        <= float(stability["temperature_relative_deviation_max"]),
    }
    block = protocol["block_bootstrap"]
    effects: dict[str, Any] = {}
    for estimator_index, estimator in enumerate(protocol["estimators"]):
        try:
            reference_values = estimator_block_logs(
                _point(reference["result"], temperature),
                reference["transports"][temperature],
                estimator,
                expected_blocks=int(
                    reference["manifest"]["config"]["uncertainty_blocks"]
                ),
                minimum_blocks=int(
                    block["minimum_positive_blocks_per_estimator"]
                ),
            )
            comparison_values = estimator_block_logs(
                _point(comparison["result"], temperature),
                comparison["transports"][temperature],
                estimator,
                expected_blocks=int(
                    comparison["manifest"]["config"]["uncertainty_blocks"]
                ),
                minimum_blocks=int(
                    block["minimum_positive_blocks_per_estimator"]
                ),
            )
            effects[estimator] = {
                "analysis_gate_pass": True,
                **bootstrap_log_effect(
                    reference_values,
                    comparison_values,
                    iterations=int(block["iterations"]),
                    seed=int(block["seed"]) + estimator_index,
                    quantiles=block["quantiles"],
                    equivalence_ratio_margin=float(
                        protocol["equivalence"]["ratio_margin"]
                    ),
                ),
            }
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            effects[estimator] = {
                "analysis_gate_pass": False,
                "error": f"{type(exc).__name__}: {exc}",
                "required_action": stability["hard_rule"],
            }

    inputs_complete = bool(
        all(stability_checks.values())
        and all(row.get("analysis_gate_pass") is True for row in effects.values())
    )
    equivalence_pass = bool(
        inputs_complete
        and all(row.get("equivalence_supported") is True for row in effects.values())
    )
    report = {
        "schema_version": "1.0",
        "report_kind": "production-ensemble-sensitivity",
        "protocol_path": str(source),
        "protocol_sha256": sha256_file(source),
        "temperature_k": temperature,
        "reference": {
            "campaign_protocol_path": str(reference_protocol_path),
            "campaign_protocol_sha256": sha256_file(reference_protocol_path),
            "run_id": reference["run_id"],
            "production_ensemble": "nvt",
        },
        "comparison": {
            "campaign_protocol_path": str(comparison_protocol_path),
            "campaign_protocol_sha256": sha256_file(comparison_protocol_path),
            "run_id": comparison["run_id"],
            "production_ensemble": "nve",
        },
        "matched_design_checks": matched_checks,
        "observed_config_differences": sorted(
            key
            for key in set(reference["manifest"]["config"])
            | set(comparison["manifest"]["config"])
            if reference["manifest"]["config"].get(key)
            != comparison["manifest"]["config"].get(key)
        ),
        "nve_stability": {
            "total_energy_drift_mev_atom_ps": drift,
            "temperature_mean_k": mean_temperature,
            "checks": stability_checks,
            "stability_gate_pass": all(stability_checks.values()),
        },
        "effects": effects,
        "analysis_completeness_gate_pass": inputs_complete,
        "ensemble_robustness_gate_pass": equivalence_pass,
        "failed_equivalence_fails_computational_completeness": False,
        "interpretation": (
            "A robustness pass is restricted to occupancy 0 at 800 K. A complete "
            "but non-equivalent result is retained as production-ensemble sensitivity."
        ),
        "sources": [reference["source"], comparison["source"]],
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
        "implementation_dependencies": [
            {
                "path": str(Path(__file__).with_name("transport_sensitivity.py")),
                "sha256": sha256_file(
                    Path(__file__).with_name("transport_sensitivity.py")
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
        raise RuntimeError(f"refusing to overwrite ensemble report: {destination}")
    report = build_ensemble_sensitivity_report(args.protocol)
    atomic_write_json(destination, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
