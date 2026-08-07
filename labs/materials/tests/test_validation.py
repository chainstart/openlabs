from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.validation import (  # noqa: E402
    arrhenius_diffusivity,
    build_hierarchical_validation_report,
    build_validation_report,
    conductivity_from_collective_diffusivity,
    load_benchmarks,
)


def _fit(energy=0.4, prefactor=1e-3):
    return {"activation_energy_ev": energy, "prefactor_cm2_s": prefactor}


def test_curated_benchmarks_are_valid_and_exact_composition():
    data = load_benchmarks(ROOT / "data/experimental/llzto_matched_v1.json")
    assert data["nominal_formula"] == "Li6.5La3Zr1.5Ta0.5O12"
    assert len(data["records"]) == 4


def test_derived_benchmark_requires_an_explicit_derivation(tmp_path):
    path = tmp_path / "benchmarks.json"
    path.write_text(
        """{
          "schema_version": "1.0",
          "records": [{
            "record_id": "bad-derived",
            "source": {"doi": "10.1/example"},
            "measurements": [{
              "property": "activation_energy",
              "value": 0.4,
              "unit": "eV",
              "derived": true
            }]
          }]
        }""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="has no derivation"):
        load_benchmarks(path)


def test_nmr_two_point_activation_energy_is_reproducible():
    data = load_benchmarks(ROOT / "data/experimental/llzto_matched_v1.json")
    record = next(row for row in data["records"] if "kataoka" in row["record_id"])
    diffusion = [m for m in record["measurements"] if m["property"] == "tracer_diffusivity"]
    derived = next(m for m in record["measurements"] if m["property"] == "activation_energy")
    k_b = 8.617333262e-5
    energy = k_b * math.log(diffusion[1]["value"] / diffusion[0]["value"]) / (
        1 / diffusion[0]["temperature_k"] - 1 / diffusion[1]["temperature_k"]
    )
    assert energy == pytest.approx(derived["value"], abs=1e-15)


def test_arrhenius_prediction_recovers_definition():
    predicted = arrhenius_diffusivity(_fit(), 1000)
    assert predicted == pytest.approx(1e-3 * math.exp(-0.4 / (8.617333262e-5 * 1000)))


def test_collective_diffusivity_conversion_has_correct_units():
    value = conductivity_from_collective_diffusivity(
        1e-6, temperature_k=300, n_mobile=26, volume_angstrom3=1100
    )
    assert value == pytest.approx(1.465e-1, rel=0.01)


def test_report_keeps_context_and_marks_extrapolation():
    benchmarks = load_benchmarks(ROOT / "data/experimental/llzto_matched_v1.json")
    result = {
        "protocol_fingerprint": "abc",
        "arrhenius": _fit(0.40, 1e-3),
        "arrhenius_collective": _fit(0.42, 2e-3),
        "points": [
            {"temperature": 700, "n_mobile": 26},
            {"temperature": 1000, "n_mobile": 26},
            {"temperature": 1200, "n_mobile": 26},
        ],
        "relaxation": {"final_summary": {"volume_angstrom3": 1100}},
    }
    report = build_validation_report(result, benchmarks)
    assert report["n_comparisons"] >= 8
    assert all(row["source"]["doi"] for row in report["comparisons"])
    room_temperature = [
        row for row in report["comparisons"] if row["temperature_k"] is not None
    ]
    assert all(row["is_temperature_extrapolation"] for row in room_temperature)
    derived = next(row for row in report["comparisons"] if row["observed_is_derived"])
    assert derived["benchmark_role"] == "secondary_derived_comparator"
    assert "excluded from primary inference" in derived["scope_note"]
    assert derived["derivation"].startswith("Ea=kB")
    assert all(
        row["benchmark_role"] == "primary_direct_measurement"
        for row in report["comparisons"]
        if not row["observed_is_derived"]
    )


def _hierarchical_report():
    temperatures = [297.0, 298.0, 298.15, 300.15, 333.0]

    def predictions(collective: bool):
        rows = {}
        for temperature in temperatures:
            population = {
                "diffusivity_cm2_s_quantiles": {
                    "0.025": 1.2e-9,
                    "0.5": 1.57e-9,
                    "0.975": 1.9e-9,
                }
            }
            predictive = {
                "diffusivity_cm2_s_quantiles": {
                    "0.025": 1.0e-9,
                    "0.5": 1.57e-9,
                    "0.975": 2.0e-9,
                }
            }
            if collective:
                population["conductivity_s_cm_quantiles"] = {
                    "0.025": 5e-4,
                    "0.5": 1e-3,
                    "0.975": 1.5e-3,
                }
                predictive["conductivity_s_cm_quantiles"] = {
                    "0.025": 1e-4,
                    "0.5": 1e-3,
                    "0.975": 2e-3,
                }
            rows[format(temperature, ".12g")] = {
                "temperature_k": temperature,
                "is_extrapolation": True,
                "population_geometric_mean": population,
                "new_configuration_predictive": predictive,
            }
        return rows

    def estimator(collective: bool):
        return {
            "analysis_gate_pass": True,
            "activation_energy_random_effects": {
                "mean": 0.4,
                "confidence_level": 0.95,
                "confidence_interval": [0.35, 0.45],
                "prediction_interval": [0.3, 0.5],
            },
            "nested_configuration_bootstrap": {
                "temperature_predictions": predictions(collective)
            },
        }

    return {
        "schema_version": "1.0",
        "report_kind": "hierarchical-transport",
        "estimators": {
            "tracer": estimator(False),
            "collective": estimator(True),
        },
    }


def test_hierarchical_validation_uses_prediction_intervals_and_units():
    benchmarks = load_benchmarks(ROOT / "data/experimental/llzto_matched_v1.json")
    report = build_hierarchical_validation_report(
        _hierarchical_report(),
        benchmarks,
    )
    assert report["n_eligible_measurements"] == 9
    assert report["n_comparisons"] == 9
    assert report["n_evaluated"] == 9
    tracer_298 = next(
        row
        for row in report["comparisons"]
        if row["record_id"] == "kataoka-2018-single-crystal"
        and row["property"] == "tracer_diffusivity"
        and row["temperature_k"] == 298.0
    )
    assert tracer_298["predicted_population_median"] == pytest.approx(1.57e-13)
    assert tracer_298["compatible_with_simulation_prediction"] is True
    assert tracer_298["is_temperature_extrapolation"] is True
    derived = next(row for row in report["comparisons"] if row["observed_is_derived"])
    assert derived["benchmark_role"] == "secondary_derived_comparator"
    assert "excluded from primary" in " ".join(derived["scope_notes"])


def test_hierarchical_validation_retains_blocked_estimator_measurements():
    benchmarks = load_benchmarks(ROOT / "data/experimental/llzto_matched_v1.json")
    hierarchical = _hierarchical_report()
    hierarchical["estimators"]["collective"] = {
        "analysis_gate_pass": False,
        "error": "unresolved collective point",
    }
    report = build_hierarchical_validation_report(hierarchical, benchmarks)
    assert report["n_comparisons"] == report["n_eligible_measurements"] == 9
    assert report["n_blocked"] == 6
    assert all(
        row["status"] == "blocked"
        for row in report["comparisons"]
        if row["estimator_name"] == "collective"
    )


def test_hierarchical_validation_rejects_a_tampered_report_fingerprint():
    benchmarks = load_benchmarks(ROOT / "data/experimental/llzto_matched_v1.json")
    hierarchical = _hierarchical_report()
    hierarchical["report_fingerprint"] = "0" * 64
    with pytest.raises(RuntimeError, match="fingerprint mismatch"):
        build_hierarchical_validation_report(hierarchical, benchmarks)
