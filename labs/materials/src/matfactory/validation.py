"""Composition-matched validation against curated LLZTO measurements."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .mlipmd import K_B_EV
from .provenance import atomic_write_json, fingerprint, sha256_file

K_B_J = 1.380649e-23
ELEMENTARY_CHARGE_C = 1.602176634e-19


def load_benchmarks(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0" or not payload.get("records"):
        raise ValueError(f"unsupported or empty benchmark file {source}")
    for record in payload["records"]:
        if not record.get("source", {}).get("doi"):
            raise ValueError(f"benchmark {record.get('record_id')} has no DOI")
        for measurement in record.get("measurements", []):
            if not isinstance(measurement.get("value"), (int, float)):
                raise ValueError(f"non-numeric measurement in {record.get('record_id')}")
            if not measurement.get("unit"):
                raise ValueError(f"unit missing in {record.get('record_id')}")
            if measurement.get("derived") and not measurement.get("derivation"):
                raise ValueError(
                    f"derived measurement in {record.get('record_id')} has no derivation"
                )
    return payload


def arrhenius_diffusivity(fit: dict[str, Any], temperature_k: float) -> float:
    if temperature_k <= 0:
        raise ValueError("temperature must be positive")
    return float(fit["prefactor_cm2_s"]) * math.exp(
        -float(fit["activation_energy_ev"]) / (K_B_EV * temperature_k)
    )


def conductivity_from_collective_diffusivity(
    diffusivity_cm2_s: float,
    *,
    temperature_k: float,
    n_mobile: int,
    volume_angstrom3: float,
) -> float:
    """Nernst-Einstein conductivity in S/cm from collective charge diffusion."""
    if diffusivity_cm2_s < 0 or temperature_k <= 0 or n_mobile <= 0 or volume_angstrom3 <= 0:
        raise ValueError("invalid conductivity conversion input")
    number_density_m3 = n_mobile / (volume_angstrom3 * 1e-30)
    diffusivity_m2_s = diffusivity_cm2_s * 1e-4
    conductivity_s_m = (
        number_density_m3
        * ELEMENTARY_CHARGE_C**2
        * diffusivity_m2_s
        / (K_B_J * temperature_k)
    )
    return conductivity_s_m / 100.0


def _simulation_context(result: dict[str, Any]) -> tuple[int, float, tuple[int, int]]:
    points = result.get("points") or []
    if not points:
        raise ValueError("simulation result has no temperature points")
    n_mobile = int(points[0]["n_mobile"])
    volumes = (
        result.get("relaxation", {})
        .get("final_summary", {})
        .get("volume_angstrom3")
    )
    if volumes is None:
        volumes = result.get("structure", {}).get("prepared_summary", {}).get(
            "volume_angstrom3"
        )
    if volumes is None:
        raise ValueError("simulation result has no reference volume")
    temperatures = [int(point["temperature"]) for point in points]
    return n_mobile, float(volumes), (min(temperatures), max(temperatures))


def build_validation_report(
    result: dict[str, Any],
    benchmarks: dict[str, Any],
    *,
    benchmark_path: Path | str | None = None,
) -> dict[str, Any]:
    """Compare like with like and retain experimental context for every row."""
    tracer_fit = result.get("arrhenius")
    collective_fit = result.get("arrhenius_collective")
    if tracer_fit is None:
        raise ValueError("simulation has no resolved tracer Arrhenius fit")
    n_mobile, volume, simulated_range = _simulation_context(result)
    comparisons: list[dict[str, Any]] = []

    for record in benchmarks["records"]:
        for measurement in record.get("measurements", []):
            prop = measurement["property"]
            observed = float(measurement["value"])
            temperature = measurement.get("temperature_k")
            predicted: float | None = None
            prediction_unit = measurement["unit"]
            estimator: str | None = None
            scope_note: str | None = None
            observed_is_derived = bool(measurement.get("derived", False))

            if prop == "tracer_diffusivity" and temperature is not None:
                predicted_cm2_s = arrhenius_diffusivity(tracer_fit, float(temperature))
                if measurement["unit"] == "m2/s":
                    predicted = predicted_cm2_s * 1e-4
                elif measurement["unit"] == "cm2/s":
                    predicted = predicted_cm2_s
                else:
                    raise ValueError(f"unsupported diffusivity unit {measurement['unit']}")
                estimator = "tracer Arrhenius extrapolation"
            elif prop == "total_ionic_conductivity" and temperature is not None:
                if collective_fit is None:
                    continue
                collective_d = arrhenius_diffusivity(collective_fit, float(temperature))
                predicted = conductivity_from_collective_diffusivity(
                    collective_d,
                    temperature_k=float(temperature),
                    n_mobile=n_mobile,
                    volume_angstrom3=volume,
                )
                estimator = "collective diffusivity plus Nernst-Einstein"
                if "polycrystalline" in record.get("sample_type", ""):
                    scope_note = (
                        "intrinsic periodic-cell prediction versus measured total "
                        "bulk-plus-grain-boundary conductivity"
                    )
            elif prop == "activation_energy":
                method = measurement.get("method", "")
                if "NMR" in method or "tracer" in method:
                    predicted = float(tracer_fit["activation_energy_ev"])
                    estimator = "tracer Arrhenius activation energy"
                    if observed_is_derived:
                        scope_note = (
                            "secondary comparator derived from two reported NMR "
                            "diffusivities; not a directly fitted experimental "
                            "Arrhenius barrier and excluded from primary inference"
                        )
                elif collective_fit is not None:
                    predicted = float(collective_fit["activation_energy_ev"])
                    estimator = "collective Arrhenius activation energy"
                    scope_note = "experimental barrier comes from total conductivity"

            if predicted is None:
                continue
            if prop == "activation_energy":
                metric = {
                    "absolute_error_ev": predicted - observed,
                    "absolute_error_magnitude_ev": abs(predicted - observed),
                }
            else:
                metric = {
                    "prediction_to_experiment_ratio": predicted / observed,
                    "log10_ratio": math.log10(predicted / observed),
                }
            comparisons.append(
                {
                    "record_id": record["record_id"],
                    "sample_type": record.get("sample_type"),
                    "phase": record.get("phase"),
                    "property": prop,
                    "temperature_k": temperature,
                    "observed": observed,
                    "observed_method": measurement.get("method"),
                    "observed_is_derived": observed_is_derived,
                    "benchmark_role": (
                        "secondary_derived_comparator"
                        if observed_is_derived
                        else "primary_direct_measurement"
                    ),
                    "derivation": measurement.get("derivation"),
                    "predicted": predicted,
                    "unit": prediction_unit,
                    "estimator": estimator,
                    "scope_note": scope_note,
                    "is_temperature_extrapolation": bool(
                        temperature is not None
                        and not (simulated_range[0] <= float(temperature) <= simulated_range[1])
                    ),
                    "metric": metric,
                    "source": record["source"],
                }
            )

    return {
        "schema_version": "1.0",
        "protocol_fingerprint": result.get("protocol_fingerprint"),
        "material_id": benchmarks["material_id"],
        "nominal_formula": benchmarks["nominal_formula"],
        "benchmark_sha256": sha256_file(benchmark_path) if benchmark_path else None,
        "simulated_temperature_range_k": list(simulated_range),
        "n_mobile": n_mobile,
        "reference_volume_angstrom3": volume,
        "comparisons": comparisons,
        "n_comparisons": len(comparisons),
        "warning": (
            "Room-temperature predictions are high-temperature Arrhenius "
            "extrapolations and must be interpreted with the reported model and "
            "trajectory uncertainty, not as direct room-temperature simulations."
        ),
    }


def _quantile_interval(
    quantiles: dict[str, Any],
    *,
    scale: float = 1.0,
) -> dict[str, Any]:
    parsed = sorted(
        (float(key), float(value) * scale) for key, value in quantiles.items()
    )
    if len(parsed) < 3:
        raise ValueError("prediction distribution needs at least three quantiles")
    median_quantile, median = min(parsed, key=lambda item: abs(item[0] - 0.5))
    return {
        "lower_quantile": parsed[0][0],
        "lower": parsed[0][1],
        "median_quantile": median_quantile,
        "median": median,
        "upper_quantile": parsed[-1][0],
        "upper": parsed[-1][1],
        "all_quantiles": {str(key): value for key, value in parsed},
    }


def _temperature_prediction(
    estimator: dict[str, Any], temperature_k: float
) -> dict[str, Any]:
    predictions = (
        estimator.get("nested_configuration_bootstrap", {})
        .get("temperature_predictions", {})
    )
    matches = [
        row
        for row in predictions.values()
        if math.isclose(
            float(row.get("temperature_k", float("nan"))),
            float(temperature_k),
            rel_tol=0.0,
            abs_tol=1e-8,
        )
    ]
    if len(matches) != 1:
        raise ValueError(
            f"hierarchical report has {len(matches)} predictions at {temperature_k} K"
        )
    return matches[0]


def build_hierarchical_validation_report(
    hierarchical: dict[str, Any],
    benchmarks: dict[str, Any],
    *,
    hierarchical_report_path: Path | str | None = None,
    benchmark_path: Path | str | None = None,
) -> dict[str, Any]:
    """Compare experiments with population intervals and configuration predictions."""
    if hierarchical.get("report_kind") != "hierarchical-transport":
        raise ValueError("expected a hierarchical-transport report")
    if hierarchical.get("report_fingerprint") is not None:
        unsigned = {
            key: value
            for key, value in hierarchical.items()
            if key != "report_fingerprint"
        }
        if fingerprint(unsigned) != hierarchical["report_fingerprint"]:
            raise RuntimeError("hierarchical report fingerprint mismatch")
    estimators = hierarchical.get("estimators", {})
    comparisons: list[dict[str, Any]] = []
    eligible_measurements = 0

    for record in benchmarks["records"]:
        for measurement in record.get("measurements", []):
            prop = measurement["property"]
            if prop not in {
                "tracer_diffusivity",
                "total_ionic_conductivity",
                "activation_energy",
            }:
                continue
            eligible_measurements += 1
            observed = float(measurement["value"])
            temperature = measurement.get("temperature_k")
            observed_is_derived = bool(measurement.get("derived", False))
            method = measurement.get("method", "")
            if prop == "tracer_diffusivity":
                estimator_name = "tracer"
                quantity = "diffusivity_cm2_s_quantiles"
                if measurement["unit"] == "m2/s":
                    scale = 1e-4
                elif measurement["unit"] == "cm2/s":
                    scale = 1.0
                else:
                    raise ValueError(
                        f"unsupported diffusivity unit {measurement['unit']}"
                    )
                estimator_label = "hierarchical tracer Arrhenius extrapolation"
            elif prop == "total_ionic_conductivity":
                estimator_name = "collective"
                quantity = "conductivity_s_cm_quantiles"
                scale = 1.0
                estimator_label = (
                    "hierarchical collective diffusivity plus Nernst-Einstein"
                )
            elif "NMR" in method or "tracer" in method:
                estimator_name = "tracer"
                quantity = "activation_energy"
                scale = 1.0
                estimator_label = "hierarchical tracer activation energy"
            else:
                estimator_name = "collective"
                quantity = "activation_energy"
                scale = 1.0
                estimator_label = "hierarchical collective activation energy"

            base = {
                "record_id": record["record_id"],
                "sample_type": record.get("sample_type"),
                "phase": record.get("phase"),
                "property": prop,
                "temperature_k": temperature,
                "observed": observed,
                "observed_uncertainty": measurement.get("uncertainty"),
                "observed_method": measurement.get("method"),
                "observed_is_derived": observed_is_derived,
                "benchmark_role": (
                    "secondary_derived_comparator"
                    if observed_is_derived
                    else "primary_direct_measurement"
                ),
                "derivation": measurement.get("derivation"),
                "unit": measurement["unit"],
                "estimator": estimator_label,
                "estimator_name": estimator_name,
                "source": record["source"],
            }
            estimator = estimators.get(estimator_name)
            if (
                not isinstance(estimator, dict)
                or estimator.get("analysis_gate_pass") is not True
            ):
                error = (
                    estimator.get("error")
                    if isinstance(estimator, dict)
                    else f"missing {estimator_name} estimator"
                )
                comparisons.append(
                    {
                        **base,
                        "status": "blocked",
                        "error": error,
                        "compatibility_assessment": "not_evaluable",
                    }
                )
                continue

            if quantity == "activation_energy":
                meta = estimator["activation_energy_random_effects"]
                predicted = float(meta["mean"])
                population_interval = {
                    "lower": float(meta["confidence_interval"][0]),
                    "median": predicted,
                    "upper": float(meta["confidence_interval"][1]),
                    "confidence_level": float(meta["confidence_level"]),
                }
                prediction_interval = {
                    "lower": float(meta["prediction_interval"][0]),
                    "median": predicted,
                    "upper": float(meta["prediction_interval"][1]),
                    "confidence_level": float(meta["confidence_level"]),
                }
                is_extrapolation = False
            else:
                if temperature is None:
                    raise ValueError(f"{prop} measurement has no temperature")
                prediction = _temperature_prediction(estimator, float(temperature))
                population_interval = _quantile_interval(
                    prediction["population_geometric_mean"][quantity],
                    scale=scale,
                )
                prediction_interval = _quantile_interval(
                    prediction["new_configuration_predictive"][quantity],
                    scale=scale,
                )
                predicted = float(population_interval["median"])
                is_extrapolation = bool(prediction["is_extrapolation"])

            compatible = bool(
                prediction_interval["lower"]
                <= observed
                <= prediction_interval["upper"]
            )
            if prop == "activation_energy":
                metric = {
                    "prediction_minus_experiment_ev": predicted - observed,
                    "absolute_error_ev": abs(predicted - observed),
                }
            else:
                metric = {
                    "prediction_to_experiment_ratio": predicted / observed,
                    "log10_ratio": math.log10(predicted / observed),
                }
            scope_notes = []
            if (
                prop == "total_ionic_conductivity"
                and "polycrystalline" in record.get("sample_type", "")
            ):
                scope_notes.append(
                    "intrinsic periodic-cell prediction versus measured total "
                    "bulk-plus-grain-boundary conductivity"
                )
            if observed_is_derived:
                scope_notes.append(
                    "secondary value derived from two reported NMR diffusivities; "
                    "excluded from primary experimental inference"
                )
            comparisons.append(
                {
                    **base,
                    "status": "evaluated",
                    "predicted_population_median": predicted,
                    "population_mean_uncertainty_interval": population_interval,
                    "new_configuration_prediction_interval": prediction_interval,
                    "compatibility_assessment": (
                        "observed_point_inside_simulation_prediction_interval"
                        if compatible
                        else "observed_point_outside_simulation_prediction_interval"
                    ),
                    "compatible_with_simulation_prediction": compatible,
                    "is_temperature_extrapolation": is_extrapolation,
                    "metric": metric,
                    "scope_notes": scope_notes,
                }
            )

    report = {
        "schema_version": "1.0",
        "report_kind": "hierarchical-experimental-validation",
        "material_id": benchmarks["material_id"],
        "nominal_formula": benchmarks["nominal_formula"],
        "hierarchical_report_path": (
            str(Path(hierarchical_report_path).resolve())
            if hierarchical_report_path is not None
            else None
        ),
        "hierarchical_report_sha256": (
            sha256_file(hierarchical_report_path)
            if hierarchical_report_path is not None
            else None
        ),
        "hierarchical_report_fingerprint": hierarchical.get("report_fingerprint"),
        "benchmark_path": (
            str(Path(benchmark_path).resolve())
            if benchmark_path is not None
            else None
        ),
        "benchmark_sha256": sha256_file(benchmark_path) if benchmark_path else None,
        "n_eligible_measurements": eligible_measurements,
        "n_comparisons": len(comparisons),
        "n_evaluated": sum(row["status"] == "evaluated" for row in comparisons),
        "n_blocked": sum(row["status"] == "blocked" for row in comparisons),
        "comparisons": comparisons,
        "interpretation_rule": (
            "Compatibility means only that the reported experimental point lies "
            "inside the preregistered simulation new-configuration prediction "
            "interval. It is not an equivalence test, especially when the "
            "experimental uncertainty is unavailable."
        ),
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
    }
    report["report_fingerprint"] = fingerprint(report)
    return report


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--run", help="directory containing result.json")
    inputs.add_argument(
        "--hierarchical-report",
        help="completed hierarchical-transport JSON report",
    )
    parser.add_argument(
        "--benchmarks", default="data/experimental/llzto_matched_v1.json"
    )
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    benchmarks = load_benchmarks(args.benchmarks)
    if args.hierarchical_report:
        hierarchical_path = Path(args.hierarchical_report)
        hierarchical = json.loads(hierarchical_path.read_text(encoding="utf-8"))
        report = build_hierarchical_validation_report(
            hierarchical,
            benchmarks,
            hierarchical_report_path=hierarchical_path,
            benchmark_path=args.benchmarks,
        )
        out = (
            Path(args.out)
            if args.out
            else hierarchical_path.with_name(
                hierarchical_path.stem + ".validation.json"
            )
        )
    else:
        run_path = Path(args.run)
        result = json.loads((run_path / "result.json").read_text(encoding="utf-8"))
        report = build_validation_report(
            result, benchmarks, benchmark_path=args.benchmarks
        )
        out = Path(args.out) if args.out else run_path / "validation.json"
    if out.exists():
        raise RuntimeError(f"refusing to overwrite validation report: {out.resolve()}")
    atomic_write_json(out, report)
    print(f"wrote {out}: {report['n_comparisons']} matched comparisons")


if __name__ == "__main__":
    main()
