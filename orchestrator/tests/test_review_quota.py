"""Claude reviewer quota readings (``quota.json`` per review role) reach the quota snapshot."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from openlabs import budget as budget_control
from test_program_autonomy import DECISION_RECORD, _finish, _outcome, _program, _tick, _to_review
from test_research_program_flow import _db, _paths, _settings


def _reading(observed_at: str, used: float = 0.4) -> dict:
    return {"schema_version": "openlabs.quota_snapshot.v1", "provider": "anthropic",
            "observed_at": observed_at, "model": "claude-fable-5-2",
            "source": "unified_review_claude_stream_json", "role": "referee_a",
            "windows": [{"name": "five_hour", "window_minutes": 300, "used_fraction": used,
                         "resets_at": "2099-01-01T00:00:00Z"},
                        {"name": "seven_day_overage_included", "window_minutes": 10080,
                         "used_fraction": 0.7, "resets_at": "2099-01-01T00:00:00Z"}]}


def _write_run(root, record: str, reading: dict | None, *, decision: bool = True) -> None:
    run = (root / record).parent
    (run / "referee_a").mkdir(parents=True, exist_ok=True)
    if decision:
        (run / "decision.json").write_text("{}")
    if reading is not None:
        (run / "referee_a" / "quota.json").write_text(json.dumps(reading))
    (run / "editor").mkdir(exist_ok=True)  # a Codex role: no reading


def test_review_quota_files_are_merged_into_the_snapshot(tmp_path) -> None:
    paths = _paths(tmp_path)
    db = _db(paths)
    settings = _settings()
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    _write_run(paths.data, DECISION_RECORD, _reading(now))
    written = budget_control.ingest_review_quota(db, settings, paths.data, DECISION_RECORD,
                                                 task_id="review-1")
    assert written == ["anthropic"]
    readings = budget_control.quota_readings(db)["anthropic"]
    assert readings["five_hour"].used_fraction == 0.4
    assert "seven_day_overage_included" in readings
    # An older reading never replaces a newer one; paths outside reviews/ are ignored.
    _write_run(paths.data, DECISION_RECORD, _reading("2020-01-01T00:00:00Z", used=0.9))
    budget_control.ingest_review_quota(db, settings, paths.data, DECISION_RECORD)
    assert budget_control.quota_readings(db)["anthropic"]["five_hour"].used_fraction == 0.4
    assert budget_control.ingest_review_quota(db, settings, paths.data, "../x/decision.json") == []
    assert budget_control.ingest_review_quota(db, settings, paths.data, None) == []


def test_ingested_paper_review_records_its_reviewers_quota(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,) = _program(tmp_path, monkeypatch)
    review = _to_review(paths, db, settings, monkeypatch, topic)
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    _write_run(paths.data, DECISION_RECORD, _reading(now, used=0.33), decision=False)
    _finish(db, paths, review["task_id"], extra={
        "paper_candidate": True, "review_outcome": _outcome(status="ready")})
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    reading = budget_control.quota_readings(db)["anthropic"]["five_hour"]
    assert reading.used_fraction == 0.33
