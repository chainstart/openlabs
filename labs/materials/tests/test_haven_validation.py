from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.haven_queue import run_haven_queue  # noqa: E402
from matfactory.haven_validation import (  # noqa: E402
    build_haven_validation_report,
    reciprocal_quantiles,
)
from matfactory.provenance import fingerprint, sha256_file  # noqa: E402


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _materialize_protocol(tmp_path: Path) -> Path:
    campaign_id = "synthetic-haven-campaign"
    campaign_root = tmp_path / "campaign"
    run_ids = [f"formal-occ{index:02d}" for index in range(5)]
    temperatures = [700, 750, 800, 850, 900]
    campaign_protocol_path = tmp_path / "campaign-protocol.json"
    _write_json(
        campaign_protocol_path,
        {"schema_version": "1.0", "campaign_id": campaign_id},
    )
    campaign_sha = sha256_file(campaign_protocol_path)
    hierarchical_protocol_path = tmp_path / "hierarchical-protocol.json"
    _write_json(hierarchical_protocol_path, {"schema_version": "1.0"})
    hierarchical_sha = sha256_file(hierarchical_protocol_path)

    primary_sources = []
    for group_index, run_id in enumerate(run_ids):
        run_dir = campaign_root / run_id
        protocol_fingerprint = f"fingerprint-{group_index}"
        manifest = {
            "schema_version": "1.0",
            "protocol_fingerprint": protocol_fingerprint,
            "config": {
                "occupancy_seed": group_index,
                "seed": 1701 + group_index * 1000,
                "uncertainty_blocks": 5,
                "provenance": {
                    "campaign_id": campaign_id,
                    "campaign_run_id": run_id,
                    "campaign_protocol_sha256": campaign_sha,
                },
            },
        }
        manifest_path = run_dir / "run_manifest.json"
        _write_json(manifest_path, manifest)
        points = []
        for temperature in temperatures:
            tracer = 1e-7 * math.exp((temperature - 700) / 180)
            ratio = 1.8 * math.exp(0.05 * group_index + 35.0 / temperature)
            collective = tracer * ratio
            points.append(
                {
                    "temperature": temperature,
                    "diffusivity_cm2_s": tracer,
                    "diffusivity_stderr_cm2_s": tracer * 0.08,
                    "collective_diffusivity_cm2_s": collective,
                    "collective_diffusivity_stderr_cm2_s": collective * 0.1,
                    "collective_to_tracer_ratio": ratio,
                    "resolved": True,
                    "collective_resolved": True,
                }
            )
            block_multipliers = [0.9, 0.96, 1.0, 1.05, 1.12]
            blocks = [
                {
                    "block_index": block_index,
                    "tracer_diffusivity_cm2_s": 1.0 + 0.03 * block_index,
                    "collective_diffusivity_cm2_s": (
                        (1.0 + 0.03 * block_index) * ratio * multiplier
                    ),
                }
                for block_index, multiplier in enumerate(block_multipliers)
            ]
            _write_json(
                run_dir / f"T{temperature}.transport.json",
                {
                    "schema_version": "1.0",
                    "protocol_fingerprint": protocol_fingerprint,
                    "transport": {"block_estimates": blocks},
                },
            )
        result_path = run_dir / "result.json"
        _write_json(
            result_path,
            {
                "schema_version": "1.0",
                "protocol_fingerprint": protocol_fingerprint,
                "points": points,
            },
        )
        primary_sources.append(
            {
                "run_id": run_id,
                "manifest_path": str(manifest_path),
                "manifest_sha256": sha256_file(manifest_path),
                "result_path": str(result_path),
                "result_sha256": sha256_file(result_path),
            }
        )

    hierarchical_report = {
        "schema_version": "1.0",
        "report_kind": "hierarchical-transport",
        "analysis_protocol_sha256": hierarchical_sha,
        "hierarchical_gate_pass": True,
        "sources": primary_sources,
    }
    hierarchical_report["report_fingerprint"] = fingerprint(hierarchical_report)
    hierarchical_report_path = tmp_path / "hierarchical-report.json"
    _write_json(hierarchical_report_path, hierarchical_report)

    benchmark = {
        "schema_version": "1.0",
        "reported_haven_ratio": 0.4,
        "reported_haven_definition": "D_tracer/D_sigma",
        "simulation_comparator": 2.5,
        "experimental_uncertainty": None,
        "source": {"doi": "10.synthetic/haven"},
    }
    benchmark_path = tmp_path / "benchmark.json"
    _write_json(benchmark_path, benchmark)
    output_path = tmp_path / "haven-report.json"
    protocol = {
        "schema_version": "1.0",
        "claim_boundary": "synthetic test",
        "primary_hierarchical_input": {
            "report_path": str(hierarchical_report_path),
            "analysis_protocol_path": str(hierarchical_protocol_path),
            "analysis_protocol_sha256": hierarchical_sha,
            "hierarchical_gate_must_pass": True,
        },
        "formal_campaign": {
            "root": str(campaign_root),
            "protocol_path": str(campaign_protocol_path),
            "protocol_sha256": campaign_sha,
            "campaign_id": campaign_id,
            "run_ids": run_ids,
            "temperatures_k": temperatures,
        },
        "ratio_estimator": {"minimum_paired_blocks": 4},
        "ratio_temperature_model": {
            "confidence_level": 0.95,
            "bootstrap": {
                "iterations": 199,
                "seed": 29,
                "quantiles": [0.025, 0.5, 0.975],
                "experimental_prediction_temperatures_k": [298.0],
            },
            "non_arrhenius_diagnostic": {"aicc_improvement_min": 6.0},
        },
        "experimental_benchmark": {
            "path": str(benchmark_path),
            "sha256": sha256_file(benchmark_path),
            "required_doi": "10.synthetic/haven",
            "temperature_k": 298.0,
            "transformed_collective_to_tracer_ratio": 2.5,
        },
        "output_path": str(output_path),
    }
    protocol_path = tmp_path / "haven-protocol.json"
    _write_json(protocol_path, protocol)
    return protocol_path


def test_reciprocal_quantiles_reverse_probability_order():
    result = reciprocal_quantiles({"0.025": 2.0, "0.5": 2.5, "0.975": 4.0})
    assert result == pytest.approx({"0.025": 0.25, "0.5": 0.4, "0.975": 0.5})


def test_haven_builder_maps_conventions_and_retains_all_25_cells(tmp_path):
    protocol_path = _materialize_protocol(tmp_path)
    report = build_haven_validation_report(protocol_path)

    assert report["analysis_completeness_gate_pass"] is True
    assert len(report["analysis_records"]) == 25
    assert report["convention_mapping"]["bare_haven_label_allowed"] is False
    assert report["benchmark"]["transformed_collective_to_tracer_ratio"] == 2.5
    assert report["prediction_at_experimental_temperature"]["is_extrapolation"] is True
    assert isinstance(
        report["experimental_comparison"][
            "compatible_with_new_configuration_prediction"
        ],
        bool,
    )
    assert report["scientific_incompatibility_fails_completeness"] is False


def test_haven_queue_accepts_only_the_same_fingerprinted_protocol(tmp_path):
    protocol_path = _materialize_protocol(tmp_path)
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    report = build_haven_validation_report(protocol_path)
    output_path = Path(protocol["output_path"])
    _write_json(output_path, report)
    state = run_haven_queue(
        protocol_path,
        state_path=tmp_path / "haven-state.json",
        poll_seconds=5,
    )
    assert state["status"] == "complete"
    assert state["output"]["analysis_completeness_gate_pass"] is True


def test_repository_haven_protocol_locks_source_and_ratio_orientation():
    protocol_path = (
        ROOT / "analysis/protocols/llzto_haven_convention_validation_v1.json"
    )
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    benchmark_path = ROOT / protocol["experimental_benchmark"]["path"]
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))

    assert sha256_file(benchmark_path) == protocol["experimental_benchmark"]["sha256"]
    assert benchmark["reported_haven_definition"] == "D_tracer/D_sigma"
    assert benchmark["simulation_reciprocal_definition"] == "D_collective/D_tracer"
    assert benchmark["simulation_comparator"] == pytest.approx(
        1.0 / benchmark["reported_haven_ratio"]
    )
    assert protocol["ratio_temperature_model"]["bootstrap"]["iterations"] == 10000


def test_haven_watchdog_locks_the_waiter_protocol_hash():
    protocol_path = (
        ROOT / "analysis/protocols/llzto_haven_convention_validation_v1.json"
    )
    watchdog_path = ROOT / "analysis/protocols/llzto_haven_watchdog_v1.json"
    watchdog = json.loads(watchdog_path.read_text(encoding="utf-8"))
    managed = watchdog["managed"]

    assert len(managed) == 1
    assert managed[0]["policy"] == "restart-waiting-only"
    assert managed[0]["marker"] == "matfactory.haven_queue"
    assert managed[0]["expected_protocol_sha256"] == sha256_file(protocol_path)
