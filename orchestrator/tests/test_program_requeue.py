"""program requeue (2026-11-20): a quarantined task whose cause a person fixed runs again."""

from __future__ import annotations

import json

import pytest
from openlabs import spin_guard
from test_overhaul_w3 import _quiet
from test_owner_mode import _latest, _owner_program


def _block(db, campaign_id: str, status: str = "quarantined") -> str:
    """Test only: the campaign's latest task ends blocked (as after three failed attempts)."""

    task_id = _latest(db, campaign_id)["task_id"]
    _quiet(db, campaign_id)
    with db.connect() as connection:
        connection.execute("UPDATE tasks SET status=?, attempt=3, max_attempts=3, "
                           "updated_at='2999-01-01T00:00:00Z' WHERE task_id=?",
                           (status, task_id))
    return task_id


def test_requeue_grants_one_attempt_and_records_who_and_why(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    task_id = _block(db, topic["campaign_id"])
    result = db.requeue_task_manually(task_id, by="user", reason="panel fixed in 014579bf8")
    task = db.task(task_id)
    assert task["status"] == "queued" and int(task["max_attempts"]) == 4
    assert task["last_error"] == "manual_requeue:panel fixed in 014579bf8"
    assert result["prior_status"] == "quarantined" and result["prior_attempt"] == 3
    assert db.count_events("task", task_id, "manual_requeue") == 1
    with pytest.raises(ValueError, match="only quarantined"):
        db.requeue_task_manually(task_id, by="user", reason="again")


def test_needs_human_only_with_the_flag_and_reason_required(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    task_id = _block(db, topic["campaign_id"], status="needs_human")
    with pytest.raises(ValueError, match="--allow-needs-human"):
        db.requeue_task_manually(task_id, by="user", reason="fixed")
    with pytest.raises(ValueError, match="reason"):
        db.requeue_task_manually(task_id, by="user", reason=" ", allow_needs_human=True)
    db.requeue_task_manually(task_id, by="user", reason="fixed", allow_needs_human=True)
    assert db.task(task_id)["status"] == "queued"
    with pytest.raises(ValueError, match="no task"):
        db.requeue_task_manually("missing", by="user", reason="fixed")


def test_inactive_campaign_is_refused(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    task_id = _block(db, topic["campaign_id"])
    db.pause_production_campaign(topic["campaign_id"], reason="test_pause")
    with db.connect() as connection:
        connection.execute("UPDATE tasks SET status='quarantined' WHERE task_id=?", (task_id,))
    with pytest.raises(ValueError, match="not active"):
        db.requeue_task_manually(task_id, by="user", reason="fixed")


def test_topic_without_next_step_names_the_requeue_command(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    task_id = _block(db, topic["campaign_id"])
    report = spin_guard.stuck_report(db, paths, settings)
    (row,) = [item for item in report["topics_without_next_step"]
              if item["topic_id"] == topic["topic_id"]]
    assert row["reason"] == "no_live_task"
    assert row["blocked_task"] == {"task_id": task_id, "task_type": _latest(
        db, topic["campaign_id"])["task_type"], "status": "quarantined"}
    assert row["suggested_command"].startswith(f"python -m openlabs program requeue {task_id}")
    json.dumps(report)


def test_cli_requeue(tmp_path, monkeypatch, capsys) -> None:
    from openlabs import __main__ as cli

    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    task_id = _block(db, topic["campaign_id"])
    monkeypatch.setattr(cli, "load_settings", lambda _paths: settings)
    monkeypatch.setattr(cli, "workspace_paths", lambda _workspace: paths)
    main = cli.main
    assert main(["program", "requeue", task_id, "--reason", "config fixed"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "queued" and payload["by"] == "user"
    assert main(["program", "requeue", task_id, "--reason", "config fixed"]) == 1
    assert "refused" in capsys.readouterr().err
