"""Convention-explicit experimental validation of the LLZTO Haven-type ratio."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .provenance import atomic_write_json, fingerprint, sha256_file
from .transport_statistics import analyze_hierarchical_estimator
from .velocity_statistics import _load_run_record


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


def reciprocal_quantiles(quantiles: dict[str, Any]) -> dict[str, float]:
    """Transform quantiles of positive R into quantiles of H=1/R."""
    parsed = {float(key): float(value) for key, value in quantiles.items()}
    if len(parsed) < 3 or any(value <= 0 for value in parsed.values()):
        raise ValueError("reciprocal ratio needs at least three positive quantiles")
    transformed: dict[str, float] = {}
    for probability in sorted(parsed):
        complement = 1.0 - probability
        matches = [key for key in parsed if math.isclose(key, complement, abs_tol=1e-12)]
        if len(matches) != 1:
            raise ValueError("ratio quantiles are not symmetric around one half")
        transformed[str(probability)] = 1.0 / parsed[matches[0]]
    return transformed


def _verify_primary_hierarchical_report(
    report_path: Path,
    input_config: dict[str, Any],
) -> dict[str, Any]:
    report = _read_json(report_path)
    _verify_fingerprint(report, "report_fingerprint", "hierarchical report")
    if report.get("report_kind") != "hierarchical-transport":
        raise ValueError("Haven validation requires a hierarchical-transport report")
    if (
        report.get("analysis_protocol_sha256")
        != input_config["analysis_protocol_sha256"]
    ):
        raise RuntimeError("hierarchical report analysis protocol hash mismatch")
    if (
        input_config.get("hierarchical_gate_must_pass") is True
        and report.get("hierarchical_gate_pass") is not True
    ):
        raise RuntimeError("hierarchical transport gate did not pass")
    for record in report.get("sources", []):
        for path_field, hash_field in (
            ("manifest_path", "manifest_sha256"),
            ("result_path", "result_sha256"),
        ):
            path = Path(record[path_field]).resolve()
            if sha256_file(path) != record[hash_field]:
                raise RuntimeError(f"hierarchical source hash mismatch: {path}")
    return report


def collect_ratio_records(
    protocol: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collect 25 ratio estimates with paired-block log variances."""
    campaign = protocol["formal_campaign"]
    campaign_root = _repo_path(campaign["root"])
    campaign_protocol_path = _repo_path(campaign["protocol_path"])
    if sha256_file(campaign_protocol_path) != campaign["protocol_sha256"]:
        raise RuntimeError("formal campaign protocol hash mismatch")
    campaign_protocol = _read_json(campaign_protocol_path)
    if campaign_protocol.get("campaign_id") != campaign["campaign_id"]:
        raise RuntimeError("formal campaign id mismatch")
    minimum_blocks = int(protocol["ratio_estimator"]["minimum_paired_blocks"])
    records: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for run_id in campaign["run_ids"]:
        for temperature in campaign["temperatures_k"]:
            record, source = _load_run_record(
                campaign_root / run_id,
                run_id=run_id,
                temperature_k=int(temperature),
                minimum_ratio_blocks=minimum_blocks,
            )
            if (
                record.get("campaign_id") != campaign["campaign_id"]
                or record.get("campaign_protocol_sha256")
                != campaign["protocol_sha256"]
            ):
                raise RuntimeError(f"formal provenance mismatch: {run_id}")
            ratio = record["estimators"]["collective_to_tracer_ratio"]
            value = ratio.get("value")
            variance = ratio.get("variance_log_value")
            resolved = ratio.get("resolved") is True
            if (
                not isinstance(value, (int, float))
                or not isinstance(variance, (int, float))
                or not math.isfinite(float(value))
                or not math.isfinite(float(variance))
                or float(value) <= 0
                or float(variance) <= 0
            ):
                resolved = False
            value_float = float(value) if isinstance(value, (int, float)) else float("nan")
            variance_float = (
                float(variance) if isinstance(variance, (int, float)) else float("nan")
            )
            records.append(
                {
                    "group_id": run_id,
                    "occupancy_seed": record["occupancy_seed"],
                    "velocity_seed": record["velocity_seed"],
                    "temperature_k": int(temperature),
                    # The shared hierarchy engine accepts any positive response;
                    # these field names are mapped explicitly in the report.
                    "diffusivity_cm2_s": value_float,
                    "stderr_cm2_s": (
                        value_float * math.sqrt(variance_float)
                        if resolved
                        else float("nan")
                    ),
                    "resolved": resolved,
                    "collective_to_tracer_ratio": value_float,
                    "variance_log_ratio": variance_float,
                    "paired_block_uncertainty": ratio.get(
                        "paired_block_uncertainty"
                    ),
                }
            )
            sources.append({**source, "temperature_k": int(temperature)})
    expected = len(campaign["run_ids"]) * len(campaign["temperatures_k"])
    if len(records) != expected:
        raise RuntimeError(f"expected {expected} ratio records, found {len(records)}")
    return records, sources


def build_haven_validation_report(protocol_path: Path | str) -> dict[str, Any]:
    """Build the convention mapping, ratio hierarchy, and experimental comparison."""
    source = Path(protocol_path).resolve()
    protocol = _read_json(source)
    if protocol.get("schema_version") != "1.0":
        raise ValueError("Haven protocol schema_version must be '1.0'")

    primary_config = protocol["primary_hierarchical_input"]
    primary_protocol_path = _repo_path(primary_config["analysis_protocol_path"])
    if sha256_file(primary_protocol_path) != primary_config["analysis_protocol_sha256"]:
        raise RuntimeError("primary hierarchical protocol hash mismatch")
    primary_report_path = _repo_path(primary_config["report_path"])
    primary_report = _verify_primary_hierarchical_report(
        primary_report_path, primary_config
    )

    benchmark_config = protocol["experimental_benchmark"]
    benchmark_path = _repo_path(benchmark_config["path"])
    if sha256_file(benchmark_path) != benchmark_config["sha256"]:
        raise RuntimeError("Haven benchmark hash mismatch")
    benchmark = _read_json(benchmark_path)
    if benchmark.get("source", {}).get("doi") != benchmark_config["required_doi"]:
        raise RuntimeError("Haven benchmark DOI mismatch")
    reported_haven = float(benchmark["reported_haven_ratio"])
    transformed_ratio = float(benchmark["simulation_comparator"])
    if not math.isclose(transformed_ratio, 1.0 / reported_haven, abs_tol=1e-12):
        raise RuntimeError("Haven benchmark reciprocal mapping is inconsistent")
    if not math.isclose(
        transformed_ratio,
        float(benchmark_config["transformed_collective_to_tracer_ratio"]),
        abs_tol=1e-12,
    ):
        raise RuntimeError("protocol and benchmark ratio comparators disagree")

    records, sources = collect_ratio_records(protocol)
    model = protocol["ratio_temperature_model"]
    bootstrap = model["bootstrap"]
    temperature = float(benchmark_config["temperature_k"])
    hierarchy = analyze_hierarchical_estimator(
        records,
        required_temperatures_k=protocol["formal_campaign"]["temperatures_k"],
        bootstrap_iterations=int(bootstrap["iterations"]),
        bootstrap_seed=int(bootstrap["seed"]),
        bootstrap_quantiles=bootstrap["quantiles"],
        room_temperature_k=temperature,
        confidence_level=float(model["confidence_level"]),
        curvature_aicc_improvement_min=float(
            model["non_arrhenius_diagnostic"]["aicc_improvement_min"]
        ),
        prediction_temperatures_k=bootstrap[
            "experimental_prediction_temperatures_k"
        ],
        compute_nernst_einstein_conductivity=False,
    )
    predictions = hierarchy["nested_configuration_bootstrap"][
        "temperature_predictions"
    ]
    matches = [
        row
        for row in predictions.values()
        if math.isclose(float(row["temperature_k"]), temperature, abs_tol=1e-12)
    ]
    if len(matches) != 1:
        raise RuntimeError("ratio hierarchy did not produce one benchmark prediction")
    prediction = matches[0]
    population_ratio = prediction["population_geometric_mean"][
        "diffusivity_cm2_s_quantiles"
    ]
    predictive_ratio = prediction["new_configuration_predictive"][
        "diffusivity_cm2_s_quantiles"
    ]
    population_haven = reciprocal_quantiles(population_ratio)
    predictive_haven = reciprocal_quantiles(predictive_ratio)
    ratio_values = {float(key): float(value) for key, value in predictive_ratio.items()}
    haven_values = {float(key): float(value) for key, value in predictive_haven.items()}
    lower_probability = min(ratio_values)
    upper_probability = max(ratio_values)
    ratio_interval = [ratio_values[lower_probability], ratio_values[upper_probability]]
    haven_interval = [haven_values[lower_probability], haven_values[upper_probability]]
    ratio_compatible = ratio_interval[0] <= transformed_ratio <= ratio_interval[1]
    haven_compatible = haven_interval[0] <= reported_haven <= haven_interval[1]
    if ratio_compatible != haven_compatible:
        raise RuntimeError("reciprocal compatibility decisions disagree")

    report = {
        "schema_version": "1.0",
        "report_kind": "haven-convention-validation",
        "protocol_path": str(source),
        "protocol_sha256": sha256_file(source),
        "primary_hierarchical_report": {
            "path": str(primary_report_path),
            "sha256": sha256_file(primary_report_path),
            "report_fingerprint": primary_report["report_fingerprint"],
        },
        "benchmark": {
            "path": str(benchmark_path),
            "sha256": sha256_file(benchmark_path),
            "doi": benchmark["source"]["doi"],
            "temperature_k": temperature,
            "reported_haven_ratio": reported_haven,
            "reported_definition": benchmark["reported_haven_definition"],
            "transformed_collective_to_tracer_ratio": transformed_ratio,
            "experimental_uncertainty": benchmark.get("experimental_uncertainty"),
        },
        "convention_mapping": {
            "simulation_primary_ratio": "R_sigma = D_collective/D_tracer",
            "experimental_haven_ratio": "H_R = D_tracer/D_sigma",
            "reciprocal_relation": "H_R = 1/R_sigma",
            "bare_haven_label_allowed": False,
        },
        "analysis_records": records,
        "ratio_hierarchy": hierarchy,
        "generic_engine_field_mapping": {
            "diffusivity_cm2_s": "dimensionless D_collective/D_tracer",
            "stderr_cm2_s": "delta-method standard error of the dimensionless ratio",
            "activation_energy_ev": "collective-minus-tracer activation-energy difference",
        },
        "prediction_at_experimental_temperature": {
            "temperature_k": temperature,
            "is_extrapolation": prediction["is_extrapolation"],
            "population_collective_to_tracer_quantiles": population_ratio,
            "new_configuration_collective_to_tracer_quantiles": predictive_ratio,
            "population_haven_Dtracer_over_Dsigma_quantiles": population_haven,
            "new_configuration_haven_Dtracer_over_Dsigma_quantiles": predictive_haven,
        },
        "experimental_comparison": {
            "collective_to_tracer_prediction_interval": ratio_interval,
            "transformed_experimental_collective_to_tracer": transformed_ratio,
            "haven_prediction_interval_Dtracer_over_Dsigma": haven_interval,
            "reported_experimental_haven_Dtracer_over_Dsigma": reported_haven,
            "compatible_with_new_configuration_prediction": ratio_compatible,
            "compatibility_is_descriptive": True,
            "experimental_uncertainty_available": False,
            "temperature_extrapolation": True,
        },
        "analysis_completeness_gate_pass": bool(
            hierarchy["analysis_gate_pass"]
            and len(records) == 25
            and all(record["resolved"] is True for record in records)
        ),
        "scientific_incompatibility_fails_completeness": False,
        "source_count": len(sources),
        "sources": sources,
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
        "implementation_dependencies": [
            {
                "path": str(Path(__file__).with_name("transport_statistics.py")),
                "sha256": sha256_file(
                    Path(__file__).with_name("transport_statistics.py")
                ),
            },
            {
                "path": str(Path(__file__).with_name("velocity_statistics.py")),
                "sha256": sha256_file(
                    Path(__file__).with_name("velocity_statistics.py")
                ),
            },
            {
                "path": str(Path(__file__).with_name("provenance.py")),
                "sha256": sha256_file(Path(__file__).with_name("provenance.py")),
            },
        ],
        "claim_boundary": protocol["claim_boundary"],
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
        raise RuntimeError(f"refusing to overwrite Haven report: {destination}")
    report = build_haven_validation_report(args.protocol)
    atomic_write_json(destination, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
