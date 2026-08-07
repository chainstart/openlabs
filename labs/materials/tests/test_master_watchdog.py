from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.master_watchdog import inspect_managed_process  # noqa: E402


def test_waiting_supervisor_is_restartable_only_when_process_is_missing(
    tmp_path, monkeypatch
):
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "status": "waiting_for_release_gate",
                "updated_unix_time": 90.0,
                "config": {"protocol_sha256": "a" * 64},
            }
        )
    )
    specification = {
        "process_id": "waiter",
        "marker": "unique-marker",
        "policy": "restart-waiting-only",
        "state_path": str(state_path),
        "expected_protocol_sha256": "a" * 64,
        "state_stale_seconds": 180,
    }
    monkeypatch.setattr("matfactory.master_watchdog.matching_pids", lambda _: [])
    row = inspect_managed_process(specification, now=100.0)
    assert row["disposition"] == "restartable_waiter_missing"
    assert row["restart_allowed"] is True

    monkeypatch.setattr("matfactory.master_watchdog.matching_pids", lambda _: [22])
    row = inspect_managed_process(specification, now=100.0)
    assert row["disposition"] == "active"
    assert row["healthy"] is True


def test_running_or_blocked_heavy_work_is_never_auto_restartable(
    tmp_path, monkeypatch
):
    state_path = tmp_path / "state.json"
    specification = {
        "process_id": "heavy",
        "marker": "unique-heavy",
        "policy": "observe-heavy",
        "state_path": str(state_path),
        "state_stale_seconds": 180,
    }
    monkeypatch.setattr("matfactory.master_watchdog.matching_pids", lambda _: [])
    for status in ("running", "failed", "blocked_scientific_gate"):
        state_path.write_text(
            json.dumps(
                {
                    "status": status,
                    "updated_unix_time": 90.0,
                    "config": {},
                }
            )
        )
        row = inspect_managed_process(specification, now=100.0)
        assert row.get("restart_allowed") is not True
        assert row["disposition"] != "restartable_waiter_missing"


def test_protocol_hash_mismatch_prevents_restart(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "status": "waiting_for_upstream",
                "updated_unix_time": 90.0,
                "config": {"protocol_sha256": "b" * 64},
            }
        )
    )
    specification = {
        "process_id": "waiter",
        "marker": "unique-marker",
        "policy": "restart-waiting-only",
        "state_path": str(state_path),
        "expected_protocol_sha256": "a" * 64,
        "state_stale_seconds": 180,
    }
    monkeypatch.setattr("matfactory.master_watchdog.matching_pids", lambda _: [])
    row = inspect_managed_process(specification, now=100.0)
    assert row["disposition"] == "protocol_mismatch"
    assert row["healthy"] is False


def test_stale_active_progress_is_degraded_but_not_restarted(
    tmp_path, monkeypatch
):
    progress = tmp_path / "progress.log"
    progress.write_text("progress")
    monkeypatch.setattr("matfactory.master_watchdog.matching_pids", lambda _: [33])
    monkeypatch.setattr(
        "matfactory.master_watchdog._latest_progress",
        lambda _: {"status": "stale", "path": str(progress)},
    )
    specification = {
        "process_id": "heavy",
        "marker": "unique-heavy",
        "policy": "observe-heavy",
        "progress_glob": str(progress),
        "progress_stale_seconds": 10,
        "state_stale_seconds": 180,
    }
    row = inspect_managed_process(specification, now=100.0)
    assert row["disposition"] == "active_but_stale"
    assert row["healthy"] is False
    assert row.get("restart_allowed") is not True


def test_watchdog_protocol_has_unique_process_ids_and_safe_policies():
    protocol = json.loads(
        (ROOT / "analysis/protocols/llzto_master_watchdog_v1.json").read_text()
    )
    ids = [row["process_id"] for row in protocol["managed"]]
    assert len(ids) == len(set(ids)) == 11
    assert {row["policy"] for row in protocol["managed"]} <= {
        "observe-heavy",
        "restart-waiting-only",
    }
    for row in protocol["managed"]:
        if row["policy"] == "restart-waiting-only":
            assert row["module"].startswith("matfactory.")
            assert row["state_path"].startswith("runs/supervisor/")
        else:
            assert "module" not in row
