"""Journal letters the journal_mail rules leave to a person get one light-tier model reading."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace

from openlabs import journal_triage as triage
from openlabs.config import DEFAULT_TASK_TIERS, RunnerSpec, lookup_task_tier
from test_research_program_flow import RUNNERS, _complete, _db, _install_program, _paths, _settings, _tick

LIGHT = {**RUNNERS, "light_gpt": RunnerSpec("light_gpt", "openai-codex", "light", "gpt-6-luna"),
         "light_claude": RunnerSpec("light_claude", "anthropic", "light", "claude-haiku-5-5")}

# The review table as journal_mail creates it (paper_writing.journal_mail.review_table).
TABLE = ("CREATE TABLE review (key TEXT PRIMARY KEY, kind TEXT, reason TEXT, paper_ids TEXT, decisions TEXT, "
         "subject TEXT, sender TEXT, received_at TEXT, notified INTEGER DEFAULT 0, brief TEXT, model_state TEXT, "
         "model TEXT, model_task TEXT, queued_at TEXT, handler_notified INTEGER DEFAULT 0)")
BRIEF = {"subject": "Decision on your manuscript", "sentences": ["We regret to inform you that it was declined."],
         "candidates": [], "rules": {"kind": "unmatched", "reason": "matches no paper", "decisions": ["rejected"]}}


def _env(tmp_path, *, on=True, letters=1):
    paths = replace(_paths(tmp_path), config_file=tmp_path / "instance" / "openlabs.toml")
    _install_program(paths)
    state = paths.settings_file.parent / "state" / "journal-mail"
    state.mkdir(parents=True, mode=0o700)
    with sqlite3.connect(state / "events.sqlite") as db:
        db.execute(TABLE)
        for n in range(letters):
            db.execute("INSERT INTO review(key, kind, reason, brief, model_state, queued_at) VALUES (?,?,?,?,?,?)",
                       (f"uid:{n}", "unmatched", "matches no paper", json.dumps(BRIEF), "pending",
                        "2026-11-26T00:00:00+00:00"))
        db.execute("INSERT INTO review(key, kind, reason) VALUES ('event:x', 'notification_unknown', 'x')")
    return paths, _db(paths), _settings(LIGHT, journal_mail_model_review=on), state / "events.sqlite"


def _rows(path):
    with sqlite3.connect(path) as db:
        return {k: (s, t, json.loads(m) if m else None) for k, s, t, m in
                db.execute("SELECT key, model_state, model_task, model FROM review")}


def _triage_tasks(db):
    with db.connect() as connection:
        return [dict(r) for r in connection.execute("SELECT * FROM tasks WHERE task_type=?", (triage.TASK_TYPE,))]


def test_light_tier_and_off_by_default(tmp_path, monkeypatch):
    assert lookup_task_tier(DEFAULT_TASK_TIERS, triage.TASK_TYPE, triage.ROUTING_REASON) == "light"
    paths, db, settings, journal = _env(tmp_path, on=False)
    report = _tick(paths, settings, monkeypatch)
    assert report.program["journal_mail_triage"]["outcome"] == "skipped_journal_mail_model_review_off"
    assert _triage_tasks(db) == [] and _rows(journal)["uid:0"][0] == "pending"


def test_one_task_per_batch_and_the_answer_reaches_the_row(tmp_path, monkeypatch):
    paths, db, settings, journal = _env(tmp_path, letters=triage.BATCH + 3)
    report = _tick(paths, settings, monkeypatch)
    (task,) = _triage_tasks(db)
    assert report.program["journal_mail_triage"]["dispatched"] == task["task_id"]
    assert task["runner"].startswith("light_") and task["routing_reason"] == triage.ROUTING_REASON
    packet = json.loads(open(task["input_path"]).read())
    assert [item["key"] for item in packet["letters"]] == [f"uid:{n}" for n in range(triage.BATCH)]
    rows = _rows(journal)
    assert rows["uid:0"][:2] == ("dispatched", task["task_id"]) and rows[f"uid:{triage.BATCH}"][0] == "pending"
    assert rows["event:x"][0] is None  # bookkeeping rows are never sent to a model
    # Still in flight: no second task, nothing dispatched twice.
    _tick(paths, settings, monkeypatch)
    assert len(_triage_tasks(db)) == 1
    answer = {"key": "uid:0", "category": "rejected", "paper_id": None, "manuscript_id": None, "due": None,
              "confidence": 0.9, "evidence_quotes": ["We regret to inform you that it was declined."]}
    _complete(db, paths, task["task_id"], extra={"journal_triage": [answer]})
    _tick(paths, settings, monkeypatch)
    _tick(paths, settings, monkeypatch)
    rows = _rows(journal)
    assert rows["uid:0"][0] == "done" and rows["uid:0"][2] == answer
    assert rows["uid:1"][0] == "failed" and "无此信" in rows["uid:1"][2]["error"]
    # The rest of the queue goes out in the next task.
    assert len(_triage_tasks(db)) == 2 and rows[f"uid:{triage.BATCH}"][0] == "dispatched"


def test_a_failed_or_cancelled_task_gives_no_answer(tmp_path, monkeypatch):
    for status in ("failed", "quarantined", "cancelled", "needs_human"):
        paths, db, settings, journal = _env(tmp_path / status)
        _tick(paths, settings, monkeypatch)
        (task,) = _triage_tasks(db)
        with db.connect() as connection:
            connection.execute("UPDATE tasks SET status=? WHERE task_id=?", (status, task["task_id"]))
        with sqlite3.connect(journal) as handle:
            assert triage.collect(db, handle) == {"answered": 0, "failed": 1, "requeued": 0}
        state, _, model = _rows(journal)["uid:0"]
        assert state == "failed" and status in model["error"]


def test_quota_deferral_keeps_waiting_and_a_lost_task_is_asked_again(tmp_path, monkeypatch):
    paths, db, settings, journal = _env(tmp_path)
    _tick(paths, settings, monkeypatch)
    (task,) = _triage_tasks(db)
    with db.connect() as connection:
        connection.execute("UPDATE tasks SET status='quota_deferred' WHERE task_id=?", (task["task_id"],))
    with sqlite3.connect(journal) as handle:
        assert triage.collect(db, handle) == {"answered": 0, "failed": 0, "requeued": 0}
        assert triage.dispatch(db, paths, settings, handle) is None  # one triage task at a time
    assert _rows(journal)["uid:0"][0] == "dispatched"
    with sqlite3.connect(journal) as handle:
        handle.execute("UPDATE review SET model_task='journal-triage:gone'")
        handle.commit()
        assert triage.collect(db, handle)["requeued"] == 1
    assert _rows(journal)["uid:0"][:2] == ("pending", None)


def test_a_digest_already_sent_is_not_overwritten(tmp_path, monkeypatch):
    paths, db, settings, journal = _env(tmp_path)
    _tick(paths, settings, monkeypatch)
    (task,) = _triage_tasks(db)
    with sqlite3.connect(journal) as handle:  # journal_mail sent the digest without the reading
        handle.execute("UPDATE review SET model_state='expired'")
    with db.connect() as connection:
        connection.execute("UPDATE tasks SET status='failed' WHERE task_id=?", (task["task_id"],))
    _tick(paths, settings, monkeypatch)
    assert _rows(journal)["uid:0"][:1] == ("expired",)


def test_an_older_journal_table_is_left_alone(tmp_path, monkeypatch):
    paths, db, settings, journal = _env(tmp_path)
    journal.unlink()
    with sqlite3.connect(journal) as handle:
        handle.execute("CREATE TABLE review (key TEXT PRIMARY KEY, kind TEXT, notified INTEGER DEFAULT 0)")
    report = _tick(paths, settings, monkeypatch)
    assert report.program["journal_mail_triage"]["outcome"] == "journal_mail_not_upgraded"
    assert _triage_tasks(db) == []


def test_the_task_runs_with_its_own_skill_only(tmp_path, monkeypatch):
    from openlabs.engine import _launch_task as launch  # before _tick replaces it

    paths, db, settings, journal = _env(tmp_path)
    _tick(paths, settings, monkeypatch)
    (task,) = _triage_tasks(db)
    monkeypatch.setattr("openlabs.engine._launch_worker", lambda **_kwargs: None)
    launch(db, paths, replace(settings, launch_jobs=False), db.task(task["task_id"]), owner="test")
    running = db.task(task["task_id"])
    job = json.loads((paths.job_inbox / f"{task['task_id']}-{running['current_attempt_id']}.json")
                     .read_text(encoding="utf-8"))
    assert job["runtime_policy"]["skills"] == ["$" + triage.SKILL]
    assert job["task_type"] == triage.TASK_TYPE and job["input_path"] == task["input_path"]
