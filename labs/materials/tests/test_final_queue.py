from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.final_queue import (  # noqa: E402
    _ensure_fingerprinted_output,
    inspect_upstream_state,
)
from matfactory.provenance import fingerprint, sha256_file  # noqa: E402


def test_frozen_final_supervisor_declares_existing_immutable_inputs():
    protocol = json.loads(
        (ROOT / "analysis/protocols/llzto_final_supervisor_v1.json").read_text()
    )
    assert protocol["resources"]["parallel_analysis_workers"] == 4
    assert len(protocol["upstream_states"]) == 6
    assert all(
        sha256_file(ROOT / row["path"]) == row["sha256"]
        for row in protocol["declared_files"]
    )
    assert isinstance(protocol["publication"]["evidence_audit_protocol"], str)


def test_completed_upstream_requires_exact_job_grid_and_protocol():
    specification = {
        "state_id": "queue",
        "expected_protocol_sha256": "a" * 64,
        "expected_run_ids": ["one", "two"],
    }
    payload = {
        "status": "complete",
        "config": {
            "protocol_sha256": "a" * 64,
            "run_ids": ["one", "two"],
        },
        "jobs": {
            "one": {"status": "complete"},
            "two": {"status": "already_complete"},
        },
    }
    inspected = inspect_upstream_state(specification, payload)
    assert inspected["complete"] is True
    assert inspected["terminal_block"] is False

    payload["jobs"].pop("two")
    with pytest.raises(RuntimeError, match="job grid mismatch"):
        inspect_upstream_state(specification, payload)


def test_failed_upstream_remains_visible_as_terminal_block():
    specification = {
        "state_id": "queue",
        "expected_protocol_sha256": "a" * 64,
    }
    payload = {
        "status": "blocked_scientific_failure",
        "config": {"protocol_sha256": "a" * 64},
        "jobs": {},
    }
    inspected = inspect_upstream_state(specification, payload)
    assert inspected["complete"] is False
    assert inspected["terminal_block"] is True


def test_fingerprinted_output_is_idempotent_and_rejects_tampering(tmp_path):
    path = tmp_path / "report.json"
    calls = 0

    def builder():
        nonlocal calls
        calls += 1
        payload = {"value": 3}
        payload["report_fingerprint"] = fingerprint(payload)
        return payload

    first = _ensure_fingerprinted_output(
        path,
        fingerprint_field="report_fingerprint",
        label="test report",
        builder=builder,
    )
    second = _ensure_fingerprinted_output(
        path,
        fingerprint_field="report_fingerprint",
        label="test report",
        builder=builder,
    )
    assert first == second
    assert calls == 1

    tampered = dict(second)
    tampered["value"] = 4
    path.write_text(json.dumps(tampered))
    with pytest.raises(RuntimeError, match="fingerprint mismatch"):
        _ensure_fingerprinted_output(
            path,
            fingerprint_field="report_fingerprint",
            label="test report",
            builder=builder,
        )
