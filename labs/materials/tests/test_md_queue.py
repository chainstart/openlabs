from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.campaign import load_campaign  # noqa: E402
from matfactory.md_queue import (  # noqa: E402
    acquire_gpu_lock,
    inspect_run,
    missing_structure_inputs,
    release_gpu_lock,
    verify_release_gate,
)
from matfactory.provenance import sha256_file  # noqa: E402


def _campaign(tmp_path: Path):
    protocol = tmp_path / "protocol.json"
    protocol.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "campaign_id": "test-campaign",
                "root_dir": str(tmp_path / "runs"),
                "base_config": {
                    "temperatures": [800],
                    "production_steps": 100,
                    "equilibration_steps": 100,
                    "loginterval": 10,
                },
                "runs": [{"run_id": "formal-1", "stage": "formal"}],
            }
        )
    )
    return load_campaign(protocol)


def test_release_gate_requires_pass_and_verifies_evidence(tmp_path):
    evidence = tmp_path / "report.json"
    evidence.write_text("{}\n")
    gate = tmp_path / "gate.json"
    payload = {
        "schema_version": "1.0",
        "gate_id": "g2-potential-domain",
        "status": "pass",
        "evidence": [{"path": str(evidence), "sha256": sha256_file(evidence)}],
    }
    gate.write_text(json.dumps(payload))
    verified = verify_release_gate(gate, gate_id="g2-potential-domain")
    assert verified["evidence_count"] == 1
    evidence.write_text("changed\n")
    with pytest.raises(RuntimeError, match="evidence hash mismatch"):
        verify_release_gate(gate, gate_id="g2-potential-domain")


def test_inspect_run_refuses_partial_and_verifies_completed(tmp_path):
    campaign = _campaign(tmp_path)
    item = campaign.runs[0]
    assert inspect_run(campaign, item)["state"] == "ready"
    item.run_dir.mkdir(parents=True)
    (item.run_dir / "T800.traj").write_text("partial")
    with pytest.raises(RuntimeError, match="partial MD run"):
        inspect_run(campaign, item)

    (item.run_dir / "T800.traj").unlink()
    protocol_fingerprint = "run-fingerprint"
    manifest = {
        "protocol_fingerprint": protocol_fingerprint,
        "config": {
            "provenance": {
                "campaign_run_id": item.run_id,
                "campaign_id": campaign.campaign_id,
                "campaign_protocol_sha256": campaign.protocol_sha256,
            }
        },
    }
    (item.run_dir / "run_manifest.json").write_text(json.dumps(manifest))
    (item.run_dir / "result.json").write_text(
        json.dumps(
            {
                "protocol_fingerprint": protocol_fingerprint,
                "status": "complete_but_unresolved",
            }
        )
    )
    result = inspect_run(campaign, item)
    assert result["state"] == "already_complete"
    assert result["result_status"] == "complete_but_unresolved"


def test_gpu_lock_is_exclusive_across_open_handles(tmp_path):
    lock_path = tmp_path / "gpu.lock"
    first = acquire_gpu_lock(lock_path)
    assert first is not None
    try:
        assert acquire_gpu_lock(lock_path) is None
    finally:
        release_gpu_lock(first)
    second = acquire_gpu_lock(lock_path)
    assert second is not None
    release_gpu_lock(second)


def test_future_derived_structure_is_reported_as_a_waiting_input(tmp_path):
    campaign = _campaign(tmp_path)
    item = campaign.runs[0]
    item.config.structure_file = str(tmp_path / "future.structure.json")
    assert missing_structure_inputs(item) == [
        str((tmp_path / "future.structure.json").resolve())
    ]
    (tmp_path / "future.structure.json").write_text("{}")
    assert missing_structure_inputs(item) == []
