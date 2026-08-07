from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.dft_domain import (  # noqa: E402
    build_domain_report,
    create_g2_release_gate,
    create_sampling_release_gate,
    load_domain_protocol,
)
from matfactory.provenance import fingerprint, sha256_file  # noqa: E402


def _protocol() -> dict:
    return {
        "aggregate_limits": {
            "centered_energy_mae_ev_atom": 0.015,
            "force_component_mae_ev_angstrom": 0.1,
            "force_component_rmse_ev_angstrom": 0.2,
            "stress_component_mae_gpa": 0.25,
        },
        "robustness_limits": {
            "relative_energy_spearman_min": 0.8,
            "force_component_p95_abs_ev_angstrom_max": 0.4,
            "li_force_component_mae_ev_angstrom_max": 0.12,
            "any_element_force_component_mae_ev_angstrom_max": 0.2,
            "any_temperature_force_component_mae_ev_angstrom_max": 0.15,
            "any_occupancy_force_component_mae_ev_angstrom_max": 0.15,
            "any_snapshot_force_component_max_abs_ev_angstrom_max": 0.8,
            "stress_component_max_abs_mean_bias_gpa_max": 0.25,
        },
        "sets": {
            "test": {
                "expected_snapshots": 3,
                "required_temperature_strata_k": [700, 800, 900],
                "required_occupancy_seeds": [0],
                "publication_claim_gate": False,
            }
        },
        "release_requirements": {"failure_action": "stop"},
    }


def _records() -> list[dict]:
    records = []
    for index, temperature in enumerate((700, 800, 900)):
        dft_force = np.zeros((2, 3))
        records.append(
            {
                "snapshot_id": f"s{index}",
                "temperature_k": temperature,
                "occupancy_seed": 0,
                "n_atoms": 2,
                "symbols": ["Li", "O"],
                "dft": {
                    "total_energy_ev": -20.0 + index,
                    "forces_ev_angstrom": dft_force.tolist(),
                    "stress_gpa": np.zeros((3, 3)).tolist(),
                },
                "model": {
                    "total_energy_ev": -20.0 + index + 0.01 * index,
                    "forces_ev_angstrom": (dft_force + 0.01).tolist(),
                    "stress_gpa": (np.zeros((3, 3)) + 0.01).tolist(),
                },
            }
        )
    return records


def test_domain_report_passes_aggregate_and_stratified_gates():
    report = build_domain_report(_records(), _protocol(), set_id="test")
    assert report["domain_gate_pass"] is True
    assert all(report["checks"].values())
    assert set(report["temperature_strata"]) == {"700", "800", "900"}


def test_domain_report_detects_temperature_local_failure_hidden_in_aggregate():
    records = _records()
    records[-1]["model"]["forces_ev_angstrom"] = np.full((2, 3), 0.2).tolist()
    report = build_domain_report(records, _protocol(), set_id="test")
    assert report["aggregate"]["numerical_gate_pass"] is True
    assert report["checks"]["all_temperature_force_mae"] is False
    assert report["domain_gate_pass"] is False


def test_real_domain_protocol_is_hash_consistent():
    protocol, source = load_domain_protocol(
        ROOT / "analysis/protocols/llzto_chgnet_domain_v1.json"
    )
    assert protocol["model"]["name"] == "CHGNet-default"
    assert source.is_absolute()


def test_release_gate_requires_every_passing_domain_and_numerical_report(tmp_path):
    protocol_path = ROOT / "analysis/protocols/llzto_chgnet_domain_v1.json"
    protocol_sha = sha256_file(protocol_path)
    domains = {}
    for set_id in ("feasibility", "publication-heldout"):
        path = tmp_path / f"{set_id}.json"
        payload = {
            "report_kind": "chgnet-dft-domain",
            "set_id": set_id,
            "analysis_protocol_sha256": protocol_sha,
            "domain_gate_pass": True,
            "publication_claim_gate": set_id == "publication-heldout",
        }
        payload["report_fingerprint"] = fingerprint(payload)
        path.write_text(json.dumps(payload))
        domains[set_id] = path
    numerical = {}
    for stage in ("cutoff", "kpoint", "scf"):
        path = tmp_path / f"{stage}.json"
        path.write_text(json.dumps({"numerically_converged": True}))
        numerical[stage] = path

    gate = create_g2_release_gate(
        protocol_path,
        domain_reports=domains,
        numerical_reports=numerical,
        out_path=tmp_path / "gate.json",
    )
    assert gate["status"] == "pass"
    assert len(gate["evidence"]) == 5

    sampling_gate = create_sampling_release_gate(
        protocol_path,
        domain_report=domains["feasibility"],
        numerical_reports=numerical,
        out_path=tmp_path / "sampling-gate.json",
    )
    assert sampling_gate["gate_id"] == "g2-feasibility-domain-sampling"
    assert len(sampling_gate["evidence"]) == 4

    failed = json.loads(domains["feasibility"].read_text())
    failed["domain_gate_pass"] = False
    failed.pop("report_fingerprint")
    failed["report_fingerprint"] = fingerprint(failed)
    domains["feasibility"].write_text(json.dumps(failed))
    with pytest.raises(RuntimeError, match="cannot release G2"):
        create_g2_release_gate(
            protocol_path,
            domain_reports=domains,
            numerical_reports=numerical,
            out_path=tmp_path / "failed-gate.json",
        )
