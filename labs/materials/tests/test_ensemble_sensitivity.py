from __future__ import annotations

import copy
import json
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.campaign import load_campaign  # noqa: E402
from matfactory.ensemble_analysis_queue import (  # noqa: E402
    run_ensemble_analysis_queue,
)
from matfactory.ensemble_sensitivity import (  # noqa: E402
    build_ensemble_sensitivity_report,
)
from matfactory.provenance import fingerprint, sha256_file  # noqa: E402


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _materialize_protocol(tmp_path: Path) -> tuple[Path, Path]:
    reference_id = "synthetic-reference"
    comparison_id = "synthetic-comparison"
    reference_run_id = "formal-occ00-vel1701"
    comparison_run_id = "ensemble-nve-matched-occ00-vel1701-800k"
    reference_protocol_path = tmp_path / "reference-campaign.json"
    comparison_protocol_path = tmp_path / "comparison-campaign.json"
    _write_json(
        reference_protocol_path,
        {"schema_version": "1.0", "campaign_id": reference_id},
    )
    _write_json(
        comparison_protocol_path,
        {"schema_version": "1.0", "campaign_id": comparison_id},
    )
    reference_sha = sha256_file(reference_protocol_path)
    comparison_sha = sha256_file(comparison_protocol_path)

    template = json.loads(
        (
            ROOT / "analysis/protocols/llzto_ensemble_sensitivity_v1.json"
        ).read_text(encoding="utf-8")
    )
    comparison_config = copy.deepcopy(
        json.loads(
            (ROOT / "protocols/llzto_ensemble_nve_matched_v1.json").read_text(
                encoding="utf-8"
            )
        )["base_config"]
    )
    comparison_config["provenance"] = {
        "campaign_id": comparison_id,
        "campaign_protocol_sha256": comparison_sha,
        "campaign_run_id": comparison_run_id,
    }
    reference_config = copy.deepcopy(comparison_config)
    reference_config.update(
        production_ensemble="nvt",
        protocol_name="llzto-transport-v3",
        protocol_tier="formal",
        provenance={
            "campaign_id": reference_id,
            "campaign_protocol_sha256": reference_sha,
            "campaign_run_id": reference_run_id,
        },
        relax_cell=True,
        relax_structure=True,
        structure_file="synthetic-raw.cif",
        structure_id="synthetic-raw",
        temperatures=[700, 750, 800, 850, 900],
    )
    reference_root = tmp_path / "reference-runs"
    comparison_root = tmp_path / "comparison-runs"
    relaxed_hash = "synthetic-relaxed-structure-sha256"

    def write_run(
        root: Path,
        run_id: str,
        config: dict,
        *,
        fingerprint_value: str,
        prepared_hash: str,
        relaxed: dict,
        multiplier: float,
        nve: bool,
    ) -> None:
        run_dir = root / run_id
        manifest = {
            "schema_version": "1.0",
            "protocol_fingerprint": fingerprint_value,
            "prepared_structure_sha256": prepared_hash,
            "config": config,
        }
        tracer = 1.0e-6 * multiplier
        collective = 2.0e-6 * multiplier
        result = {
            "schema_version": "2.1",
            "protocol_fingerprint": fingerprint_value,
            "structure": {"prepared_structure_sha256": prepared_hash},
            "relaxation": relaxed,
            "points": [
                {
                    "temperature": 800,
                    "diffusivity_cm2_s": tracer,
                    "collective_diffusivity_cm2_s": collective,
                    "collective_to_tracer_ratio": collective / tracer,
                    "resolved": True,
                    "collective_resolved": True,
                }
            ],
        }
        factors = [0.90, 0.97, 1.00, 1.04, 1.10]
        transport = {
            "schema_version": "1.0",
            "protocol_fingerprint": fingerprint_value,
            "trajectory_diagnostics": {
                "total_energy_drift_mev_atom_ps": 0.08 if nve else None,
                "temperature_mean_k": 803.0 if nve else 800.0,
            },
            "transport": {
                "block_estimates": [
                    {
                        "block_index": index,
                        "tracer_diffusivity_cm2_s": tracer * factor,
                        "collective_diffusivity_cm2_s": collective * factor,
                    }
                    for index, factor in enumerate(factors)
                ]
            },
        }
        _write_json(run_dir / "run_manifest.json", manifest)
        _write_json(run_dir / "result.json", result)
        _write_json(run_dir / "T800.transport.json", transport)

    write_run(
        reference_root,
        reference_run_id,
        reference_config,
        fingerprint_value="reference-fingerprint",
        prepared_hash="synthetic-raw-structure-sha256",
        relaxed={
            "performed": True,
            "converged": True,
            "output_structure_sha256": relaxed_hash,
        },
        multiplier=1.0,
        nve=False,
    )
    write_run(
        comparison_root,
        comparison_run_id,
        comparison_config,
        fingerprint_value="comparison-fingerprint",
        prepared_hash=relaxed_hash,
        relaxed={
            "performed": False,
            "output_structure_sha256": relaxed_hash,
        },
        multiplier=1.08,
        nve=True,
    )

    template["reference"].update(
        campaign_root=str(reference_root),
        campaign_protocol_path=str(reference_protocol_path),
        campaign_protocol_sha256=reference_sha,
        campaign_id=reference_id,
        run_id=reference_run_id,
    )
    template["comparison"].update(
        campaign_root=str(comparison_root),
        campaign_protocol_path=str(comparison_protocol_path),
        campaign_protocol_sha256=comparison_sha,
        campaign_id=comparison_id,
        run_id=comparison_run_id,
    )
    template["block_bootstrap"]["iterations"] = 500
    template["output_path"] = str(tmp_path / "ensemble-report.json")
    protocol_path = tmp_path / "ensemble-protocol.json"
    _write_json(protocol_path, template)
    return protocol_path, comparison_root / comparison_run_id / "run_manifest.json"


def test_matched_ensemble_builder_is_complete_and_preserves_equivalence(tmp_path):
    protocol_path, _ = _materialize_protocol(tmp_path)
    report = build_ensemble_sensitivity_report(protocol_path)

    unsigned = dict(report)
    stored_fingerprint = unsigned.pop("report_fingerprint")
    assert stored_fingerprint == fingerprint(unsigned)
    assert all(report["matched_design_checks"].values())
    assert report["analysis_completeness_gate_pass"] is True
    assert report["ensemble_robustness_gate_pass"] is True
    assert set(report["effects"]) == {
        "tracer",
        "collective",
        "collective_to_tracer_ratio",
    }
    assert report["effects"]["tracer"]["central_ratio"] == pytest.approx(1.08)


def test_matched_ensemble_builder_rejects_a_hidden_design_difference(tmp_path):
    protocol_path, comparison_manifest_path = _materialize_protocol(tmp_path)
    manifest = json.loads(comparison_manifest_path.read_text(encoding="utf-8"))
    manifest["config"]["seed"] += 1
    _write_json(comparison_manifest_path, manifest)

    with pytest.raises(RuntimeError, match="ensemble matched-design failure"):
        build_ensemble_sensitivity_report(protocol_path)


def test_ensemble_queue_accepts_only_the_same_fingerprinted_protocol(tmp_path):
    protocol_path, _ = _materialize_protocol(tmp_path)
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    report = build_ensemble_sensitivity_report(protocol_path)
    _write_json(Path(protocol["output_path"]), report)

    state = run_ensemble_analysis_queue(
        protocol_path,
        state_path=tmp_path / "ensemble-state.json",
        poll_seconds=5,
    )
    assert state["status"] == "complete"
    assert state["output"]["analysis_completeness_gate_pass"] is True


def test_repository_matched_nve_campaign_has_only_preregistered_differences():
    reference_campaign = load_campaign(ROOT / "protocols/llzto_q1_v1.json")
    comparison_campaign = load_campaign(
        ROOT / "protocols/llzto_ensemble_nve_matched_v1.json"
    )
    protocol = json.loads(
        (
            ROOT / "analysis/protocols/llzto_ensemble_sensitivity_v1.json"
        ).read_text(encoding="utf-8")
    )
    reference = asdict(
        next(
            run
            for run in reference_campaign.runs
            if run.run_id == protocol["reference"]["run_id"]
        ).config
    )
    comparison = asdict(comparison_campaign.runs[0].config)
    observed = {
        key
        for key in set(reference) | set(comparison)
        if reference.get(key) != comparison.get(key)
    }

    assert observed == set(
        protocol["matched_design"]["expected_config_differences"]
    )
    for field in protocol["matched_design"]["required_equal_config_fields"]:
        assert reference[field] == comparison[field]
    assert 800 in reference["temperatures"]
    assert comparison["temperatures"] == (800,)
    assert protocol["comparison"]["campaign_protocol_sha256"] == sha256_file(
        ROOT / "protocols/llzto_ensemble_nve_matched_v1.json"
    )


def test_ensemble_watchdog_locks_both_waiter_protocol_hashes():
    watchdog = json.loads(
        (
            ROOT / "analysis/protocols/llzto_ensemble_watchdog_v1.json"
        ).read_text(encoding="utf-8")
    )
    managed = {row["process_id"]: row for row in watchdog["managed"]}

    assert set(managed) == {
        "matched-nve-production-md",
        "matched-ensemble-analysis",
    }
    assert all(row["policy"] == "restart-waiting-only" for row in managed.values())
    assert managed["matched-nve-production-md"][
        "expected_protocol_sha256"
    ] == sha256_file(ROOT / "protocols/llzto_ensemble_nve_matched_v1.json")
    assert managed["matched-ensemble-analysis"][
        "expected_protocol_sha256"
    ] == sha256_file(
        ROOT / "analysis/protocols/llzto_ensemble_sensitivity_v1.json"
    )
