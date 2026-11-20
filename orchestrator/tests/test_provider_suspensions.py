"""Time-limited provider suspensions (user 2026-11-20): GPT only until a fixed time, then
the configuration as written applies again without anybody touching it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from openlabs import owner as owner_mode
from openlabs import suspensions
from openlabs.engine import TickReport, _record_provider_suspensions
from test_quota_routing import (
    NOW,
    _claim,
    _enqueue,
    _record,
    _routed_events,
    _setup,
    _write_and_load,
)

UNTIL = NOW + timedelta(days=3)
BEFORE, AFTER = UNTIL - timedelta(minutes=1), UNTIL + timedelta(minutes=1)

TOML = """
[program]
enabled = true
[program.owner]
runners = ["worker_gpt", "worker_claude"]
max_topics_per_runner = { worker_claude = 3 }
writing_runner = "worker_claude"

[routing]
protected_models = ["claude-fable-5-2"]
[routing.provider_ceilings.anthropic]
ordinary_ceiling = 0.7
[routing.probe_commands]
anthropic = ["claude", "-p", "ok"]
[routing.provider_suspensions.anthropic]
until = "%s"
by = "user"
date = "2026-11-20"
quote = "取消claude的临时放宽，后面的活都派给gpt"
reason = "test"

[runners.lead_gpt]
provider = "openai-codex"
tier = "lead"
model = "gpt-6-astra"
[runners.lead_claude]
provider = "anthropic"
tier = "lead"
model = "claude-fable-5-2"
[runners.worker_gpt]
provider = "openai-codex"
tier = "worker"
model = "gpt-6.1-sol"
[runners.worker_claude]
provider = "anthropic"
tier = "worker"
model = "claude-opus-5-5"
[runners.light_gpt]
provider = "openai-codex"
tier = "light"
model = "gpt-light"
[runners.light_claude]
provider = "anthropic"
tier = "light"
model = "claude-haiku-5-5"
""" % UNTIL.strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(tmp_path, monkeypatch, moment, text=TOML):
    monkeypatch.setattr(suspensions, "now", lambda: moment)
    return _write_and_load(tmp_path / moment.strftime("%H%M%S"), text)


def test_before_the_deadline_every_seat_is_gpt(tmp_path, monkeypatch) -> None:
    settings = _load(tmp_path, monkeypatch, BEFORE)
    assert {spec.provider for spec in settings.runners.values()} == {"openai-codex"}
    owner = settings.program.owner
    assert owner.runners == ("worker_gpt",) and owner.max_topics_per_runner == {}
    assert owner.writing_runner is None  # the owner writes
    assert settings.routing.protected_models == ()
    assert "anthropic" not in settings.routing.probe_commands
    assert settings.routing.provider_ceilings == {}
    (item,) = settings.provider_suspensions
    assert item.active and item.runners == ("lead_claude", "light_claude", "worker_claude")


def test_after_the_deadline_the_configuration_applies_as_written(tmp_path, monkeypatch) -> None:
    settings = _load(tmp_path, monkeypatch, AFTER)
    assert {spec.provider for spec in settings.runners.values()} == {"openai-codex", "anthropic"}
    owner = settings.program.owner
    assert owner.runners == ("worker_gpt", "worker_claude")
    assert owner.max_topics_per_runner == {"worker_claude": 3}
    assert owner.writing_runner == "worker_claude"
    assert settings.routing.protected_models == ("claude-fable-5-2",)
    assert "anthropic" in settings.routing.probe_commands
    assert settings.routing.provider_ceilings["anthropic"][0] == 0.7
    (item,) = settings.provider_suspensions
    assert not item.active


def test_dispatch_single_family_before_and_cross_family_after(tmp_path, monkeypatch) -> None:
    for moment, expected in ((BEFORE, "openai-codex"), (AFTER, "anthropic")):
        settings = _load(tmp_path, monkeypatch, moment)
        _paths, db = _setup(tmp_path / f"db-{moment:%H%M}")
        _record(db, settings, "lead_gpt", {"seven_day": 0.05})
        if "lead_claude" in settings.runners:
            _record(db, settings, "lead_claude", {"seven_day": 0.05})
        _enqueue(db, "seat", "c", runner="worker_gpt", task_type="topic_owner")
        _enqueue(db, "review", "c", runner="frontier", task_type="paper_review",
                 parent_task_id="seat", agent_role="reviewer", priority=5)
        task, _router = _claim(db, settings)
        assert task["task_id"] == "review"
        assert settings.runners[task["runner"]].provider == expected
        event = _routed_events(db, "review")[0]
        if expected == "openai-codex":
            assert event["independence"] == "same_family_different_model"


def test_writer_brief_before_and_after(tmp_path, monkeypatch) -> None:
    task = {"runner": "worker_gpt"}
    before = _load(tmp_path, monkeypatch, BEFORE)
    assert owner_mode.writing_brief_lines(before, task=task, writing=None) == []
    after = _load(tmp_path, monkeypatch, AFTER)
    assert any("worker_claude writes" in line
               for line in owner_mode.writing_brief_lines(after, task=task, writing=None))


def test_report_and_events(tmp_path, monkeypatch) -> None:
    _paths, db = _setup(tmp_path / "db")
    settings = _load(tmp_path, monkeypatch, BEFORE)
    report = TickReport()
    _record_provider_suspensions(db, settings, report)
    (row,) = report.provider_suspensions
    assert row["active"] and row["until"] == UNTIL.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert 0 < row["remaining_hours"] <= 0.02
    assert report.to_dict()["provider_suspensions"] == report.provider_suspensions
    settings = _load(tmp_path, monkeypatch, AFTER)
    for _ in range(2):
        _record_provider_suspensions(db, settings, TickReport())
    assert db.count_events("scheduler", "provider_suspension", "provider_suspension_expired") == 1
    assert db.count_events("scheduler", "provider_suspension", "provider_suspension_active") == 1


@pytest.mark.parametrize(("entry", "message"), [
    ('until = "2026-11-23T11:00:00"\nby = "u"\ndate = "d"\nquote = "q"', "time zone"),
    ('until = "soon"\nby = "u"\ndate = "d"\nquote = "q"', "ISO time"),
    ('until = "2026-11-23T11:00:00Z"\nby = "u"\ndate = "d"', "needs quote"),
    ('until = "2026-11-23T11:00:00Z"\nby = "u"\ndate = "d"\nquote = "q"\nextra = 1', "unknown key"),
])
def test_invalid_entries_are_rejected(tmp_path, monkeypatch, entry, message) -> None:
    monkeypatch.setattr(suspensions, "now", lambda: NOW)
    with pytest.raises(ValueError, match=message):
        _write_and_load(tmp_path, "[routing.provider_suspensions.anthropic]\n" + entry + "\n")


def test_no_suspension_table_changes_nothing() -> None:
    payload = {"runners": {"a": {"provider": "x", "tier": "lead"}}}
    assert suspensions.apply(payload, datetime(2026, 1, 1, tzinfo=UTC)) == (payload, ())
