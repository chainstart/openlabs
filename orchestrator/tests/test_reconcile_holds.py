"""program reconcile (2026-11-24): held topics are not archived; hand deliveries are recorded."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from openlabs import program_reconcile
from openlabs.contracts import atomic_write_json
from openlabs.program import mark_topic_delivered, open_topic_ledger
from openlabs.topic_pause import pause_topic
from test_overhaul_w3 import _quiet, _receipt
from test_owner_mode import _latest, _owner_program
from test_program_autonomy import _topic

LATER = timedelta(days=10)


def _topic_rows(planned) -> dict[str, dict]:
    return {row["id"]: row for row in planned["rows"] if row["kind"] == "topic"}


def test_operator_paused_and_held_topics_are_reported_not_archived(tmp_path,
                                                                   monkeypatch) -> None:
    paths, db, settings, topics = _owner_program(tmp_path, monkeypatch, cards=3)
    paused, held, parked = topics
    for item in topics:
        _quiet(db, item["campaign_id"])
    pause_topic(db, paths, settings, topic_id=paused["topic_id"], reason="polish mode",
                by="operator")
    # The hand-written hold of 2026-11-19 (research_state operator_hold, campaign paused).
    state_path = Path(str(db.campaign(held["campaign_id"])["workstream_state_path"]))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    atomic_write_json(state_path, {**state, "status": "paused", "previous_status": "active",
                                   "operator_hold": {"set_at": "2026-11-19T00:59:30Z",
                                                     "set_by": "operator",
                                                     "reason": "user: fewer astro topics"}})
    db.pause_production_campaign(held["campaign_id"], reason="agent_workstream_paused")
    db.pause_production_campaign(parked["campaign_id"], reason="test_pause")
    later = datetime.now(UTC) + LATER
    rows = _topic_rows(program_reconcile.plan(db, paths, settings, now=later))
    assert rows[paused["topic_id"]]["action"] == "report"
    assert rows[paused["topic_id"]]["operator_pause"] == "operator_pause"
    assert "held, not archived" in rows[paused["topic_id"]]["basis"]
    assert rows[held["topic_id"]]["action"] == "report"
    assert rows[held["topic_id"]]["operator_pause"] == "operator_hold"
    # A parked topic without a hold is still archived after reconcile_stale_days.
    assert rows[parked["topic_id"]]["action"] == "archive"
    program_reconcile.apply(db, paths, settings,
                            {"rows": [rows[paused["topic_id"]], rows[held["topic_id"]]]})
    assert _topic(paths, settings, paused["topic_id"])["status"] == "active"
    assert _topic(paths, settings, held["topic_id"])["status"] == "active"

    # 2026-11-25 (B3, P01 retired): a hold is never archived, however old; once its
    # ``until`` has passed it is reported as expired for a person to decide.
    rows = _topic_rows(program_reconcile.plan(db, paths, settings,
                                              now=datetime.now(UTC) + timedelta(days=365)))
    assert rows[paused["topic_id"]]["action"] == "report"
    assert rows[held["topic_id"]]["action"] == "report"
    state_path = Path(str(db.campaign(paused["campaign_id"])["workstream_state_path"]))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    pause = state["operator_pause"]
    assert pause["kind"] == "topic_pause" and pause["scope"] == paused["topic_id"]
    assert pause["condition"] and pause["restore"].startswith("program pause-topic")
    atomic_write_json(state_path, {**state, "operator_pause": {**pause, "until": "2026-01-01"}})
    row = _topic_rows(program_reconcile.plan(db, paths, settings, now=later))[paused["topic_id"]]
    assert row["action"] == "report" and "hold expired" in row["basis"]
    assert row["hold"]["expired"] is True


def _registry(paths, paper_id: str, version: str, delivered: str | None) -> None:
    path = paths.data / "registry" / "papers" / f"{paper_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"paper_id: {paper_id}", f"version: {version}"]
    if delivered:
        lines += ["delivery:", "  awaiting_owner_review: true",
                  "  delivered_at: '2026-11-23T16:28:36+00:00'",
                  f"  package_id: pkg_{paper_id}_{delivered}_x", f"  version: {delivered}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_hand_delivered_ready_topic_is_recorded_once(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _owner_program(tmp_path, monkeypatch)
    paper_id = "20261113-biology-genetics-campylobacter-source-forward-validation"
    ledger = open_topic_ledger(paths, settings.program)
    old = _receipt(paths, paper_id, "0.1.11")
    writer = _latest(db, topic["campaign_id"])["task_id"]
    _quiet(db, topic["campaign_id"])
    with db.connect() as connection:  # a release writer for the old version, still queued
        connection.execute("UPDATE tasks SET status='queued' WHERE task_id=?", (writer,))
    mark_topic_delivered(ledger, topic["topic_id"], db=db, decided_by="test",
                         paper_id=paper_id,
                         evidence=[{"path": str(old), "sha256": "0" * 64}],
                         handoff={"status": "queued", "paper_id": paper_id, "attempts": 0},
                         release={"status": "waiting", "stage": "form_fix_writer",
                                  "writer_task_id": writer, "seq": 4})
    # Registry delivered an older version than the current one: nothing to record.
    _registry(paths, paper_id, "0.1.13", "0.1.11")
    assert topic["topic_id"] not in _topic_rows(program_reconcile.plan(db, paths, settings))

    _registry(paths, paper_id, "0.1.13", "0.1.13")
    receipt = _receipt(paths, paper_id, "0.1.13")
    row = _topic_rows(program_reconcile.plan(db, paths, settings))[topic["topic_id"]]
    assert row["action"] == "report" and "cancel-task" in row["basis"]
    db.cancel_task_manually(writer, by="operator", reason="version superseded")
    row = _topic_rows(program_reconcile.plan(db, paths, settings))[topic["topic_id"]]
    assert row["action"] == "record_delivery"
    assert row["delivery"]["receipt"]["path"] == str(receipt)
    assert _topic(paths, settings, topic["topic_id"])["handoff"]["status"] == "queued"

    result = program_reconcile.apply(db, paths, settings, {"rows": [row]})
    assert result["errors"] == []
    done = _topic(paths, settings, topic["topic_id"])
    assert done["status"] == "ready_queue" and done["awaiting_owner_review"] is True
    assert done["handoff"]["status"] == "delivered"
    assert done["handoff"]["package_id"] == f"pkg_{paper_id}_0.1.13_x"
    assert done["release"]["status"] == "done" and done["release"]["writer_task_id"] is None
    assert done["release"]["seq"] == 5
    assert done["history"][-1]["kind"] == "handoff_delivered"
    # Recorded once: the next plan has nothing for it, a second apply adds no entry.
    assert topic["topic_id"] not in _topic_rows(program_reconcile.plan(db, paths, settings))
    program_reconcile.apply(db, paths, settings, {"rows": [row]})
    assert len(_topic(paths, settings, topic["topic_id"])["history"]) == len(done["history"])
