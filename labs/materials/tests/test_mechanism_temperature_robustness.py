from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.mechanism_temperature_queue import (  # noqa: E402
    run_temperature_robustness_queue,
)
from matfactory.mechanism_temperature_robustness import (  # noqa: E402
    analyze_temperature_robustness,
    fit_categorical_temperature_association,
)
from matfactory.mechanism_transport import fit_primary_association  # noqa: E402
from matfactory.mlipmd import K_B_EV  # noqa: E402
from matfactory.provenance import fingerprint, sha256_file  # noqa: E402


def _planted_rows() -> list[dict]:
    rows = []
    temperatures = [700, 750, 800, 850, 900]
    temperature_effect = [0.1, -0.4, 0.3, 0.7, -0.2]
    pattern = np.asarray([-1.4, 0.8, -0.3, 1.5, -0.6])
    for group_index in range(5):
        for temperature_index, temperature in enumerate(temperatures):
            descriptor = float(
                np.roll(pattern, group_index)[temperature_index]
                + 0.04 * group_index
            )
            response = (
                -10.0
                + 0.2 * group_index
                + temperature_effect[temperature_index]
                + 1.25 * descriptor
            )
            rows.append(
                {
                    "group_id": f"occ{group_index}",
                    "occupancy_seed": group_index,
                    "temperature_k": temperature,
                    "responses": {
                        "log_tracer_diffusivity": {
                            "value": response,
                            "variance": 0.02**2,
                        }
                    },
                    "primary_descriptors": {"log_jump_rate": descriptor},
                }
            )
    return rows


def _primary_analysis(*, supported: bool = True) -> dict:
    return {
        "grid_gate_pass": True,
        "associations": {
            "log_tracer_diffusivity": {
                "log_jump_rate": {
                    "analysis_gate_pass": True,
                    "association_supported": supported,
                    "primary_fit": {
                        "descriptor_coefficient_per_sample_sd": 1.0
                    },
                }
            }
        },
    }


def _small_analysis(rows: list[dict], primary: dict) -> dict:
    return analyze_temperature_robustness(
        rows,
        primary,
        descriptor_names=["log_jump_rate"],
        response_names=["log_tracer_diffusivity"],
        permutation_iterations=199,
        permutation_seed=17,
        bootstrap_iterations=199,
        bootstrap_seed=19,
        bootstrap_quantiles=[0.025, 0.5, 0.975],
        bootstrap_minimum_valid_fraction=0.95,
        alpha=0.05,
    )


def test_categorical_temperature_effects_remove_shared_nonlinear_confounding():
    temperatures = np.tile(np.asarray([700.0, 750.0, 800.0, 850.0, 900.0]), 5)
    groups = np.repeat(np.asarray([f"occ{i}" for i in range(5)], dtype=object), 5)
    inverse = 1.0 / (K_B_EV * temperatures)
    standardized = (inverse - inverse.mean()) / inverse.std(ddof=1)
    pattern = np.asarray([-1.4, 0.8, -0.3, 1.5, -0.6])
    interaction = np.concatenate([np.roll(pattern, index) for index in range(5)])
    descriptor = (
        standardized**2
        + 0.2 * interaction
        + np.repeat(np.arange(5) * 0.1, 5)
    )
    # There is no descriptor effect: response and descriptor only share an
    # arbitrary nonlinear temperature curve.
    response = np.repeat(np.arange(5) * 0.15, 5) + 1.2 * standardized**2
    variances = np.full(25, 0.01)

    arrhenius_only = fit_primary_association(
        response, variances, temperatures, groups, descriptor
    )
    saturated = fit_categorical_temperature_association(
        response, variances, temperatures, groups, descriptor
    )

    assert arrhenius_only["descriptor_coefficient_per_sample_sd"] > 0.5
    assert saturated["descriptor_coefficient_per_original_sample_sd"] == pytest.approx(
        0.0, abs=1e-10
    )


def test_planted_within_cell_association_survives_all_robustness_rules():
    report = _small_analysis(_planted_rows(), _primary_analysis())
    result = report["associations"]["log_tracer_diffusivity"]["log_jump_rate"]
    assert report["analysis_completeness_gate_pass"] is True
    assert result["holm_adjusted_p_value"] <= 0.05
    assert result["cluster_bootstrap"]["interval_excludes_zero"] is True
    assert result["leave_one_occupancy_out"]["sign_stable"] is True
    assert result["association_retained_after_temperature_robustness"] is True
    assert report["all_primary_supported_associations_survive"] is True
    assert report["causal_mechanism_claim_allowed"] is False


def test_robustness_cannot_rescue_a_failed_primary_association():
    report = _small_analysis(_planted_rows(), _primary_analysis(supported=False))
    result = report["associations"]["log_tracer_diffusivity"]["log_jump_rate"]
    assert result["categorical_temperature_robustness_supported"] is True
    assert result["association_retained_after_temperature_robustness"] is False
    assert result["claim_disposition"] == "not_supported_by_preregistered_primary_model"


def test_incomplete_grid_is_retained_as_an_explicit_block():
    rows = _planted_rows()
    rows.pop()
    report = _small_analysis(rows, _primary_analysis())
    assert report["grid_gate_pass"] is False
    assert report["analysis_completeness_gate_pass"] is False


def test_persistent_queue_builds_one_fingerprinted_report(tmp_path):
    rows = _planted_rows()
    primary_protocol = tmp_path / "primary.json"
    primary_protocol.write_text('{"schema_version":"1.0"}', encoding="utf-8")
    primary_report = {
        "schema_version": "1.0",
        "report_kind": "mechanism-transport-association",
        "analysis_protocol_sha256": sha256_file(primary_protocol),
        "input_gate_pass": True,
        "analysis_records": rows,
        "analysis": _primary_analysis(),
        "sources": [],
        "source_count": 0,
    }
    primary_report["report_fingerprint"] = fingerprint(primary_report)
    primary_report_path = tmp_path / "primary-report.json"
    primary_report_path.write_text(json.dumps(primary_report), encoding="utf-8")
    destination = tmp_path / "robustness.json"
    protocol = {
        "schema_version": "1.0",
        "input": {
            "primary_protocol_path": str(primary_protocol),
            "primary_protocol_sha256": sha256_file(primary_protocol),
            "primary_report_path": str(primary_report_path),
        },
        "descriptor_names": ["log_jump_rate"],
        "response_names": ["log_tracer_diffusivity"],
        "robustness_model": {
            "permutation_test": {"iterations": 99, "seed": 3},
            "cluster_bootstrap": {
                "iterations": 99,
                "seed": 5,
                "quantiles": [0.025, 0.5, 0.975],
                "minimum_valid_fraction": 0.95,
            },
            "multiplicity": {"alpha": 0.05},
        },
        "claim_rule": "test rule",
        "output_path": str(destination),
    }
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
    state_path = tmp_path / "state.json"

    state = run_temperature_robustness_queue(
        protocol_path, state_path=state_path, poll_seconds=5
    )

    assert state["status"] == "complete"
    assert destination.is_file()
    built = json.loads(destination.read_text(encoding="utf-8"))
    unsigned = dict(built)
    stored = unsigned.pop("report_fingerprint")
    assert stored == fingerprint(unsigned)


def test_repository_protocol_locks_the_primary_family_and_full_resampling():
    protocol_path = (
        ROOT
        / "analysis/protocols/llzto_mechanism_temperature_robustness_v1.json"
    )
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    primary_path = ROOT / protocol["input"]["primary_protocol_path"]

    assert sha256_file(primary_path) == protocol["input"]["primary_protocol_sha256"]
    assert len(protocol["descriptor_names"]) * len(protocol["response_names"]) == 12
    assert protocol["robustness_model"]["permutation_test"]["iterations"] == 10000
    assert protocol["robustness_model"]["cluster_bootstrap"]["iterations"] == 5000
    assert protocol["hard_rules"]["causal_language_allowed"] is False


def test_auxiliary_watchdog_locks_the_robustness_waiter_protocol():
    robustness_path = (
        ROOT
        / "analysis/protocols/llzto_mechanism_temperature_robustness_v1.json"
    )
    watchdog_path = (
        ROOT / "analysis/protocols/llzto_mechanism_temperature_watchdog_v1.json"
    )
    watchdog = json.loads(watchdog_path.read_text(encoding="utf-8"))
    managed = watchdog["managed"]

    assert len(managed) == 1
    assert managed[0]["policy"] == "restart-waiting-only"
    assert managed[0]["expected_protocol_sha256"] == sha256_file(robustness_path)
    assert managed[0]["marker"] == "matfactory.mechanism_temperature_queue"
