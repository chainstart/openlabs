"""Parallel topic scouts (one per domain, bounded by the candidate pool) and parallel
admission batches; the new throughput keys default to the old behaviour."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import test_quota_routing as qr
import test_research_program_flow as flow
from openlabs import budget as budget_control
from openlabs import engine
from openlabs.config import FactorySettings, load_settings
from openlabs.db import FactoryDB
from openlabs.program import open_topic_ledger, propose_topic
from openlabs.program_flow import (
    LAST_SCOUT_KEY,
    expected_cards_per_scout,
    maybe_schedule_scout,
    schedule_scouts,
)

NOW = qr.NOW
DOMAINS = ("ai", "physics", "quant")


# --------------------------------------------------------------------------- helpers


def _install_domains(paths, domains=DOMAINS) -> None:
    flow._install_program(paths)  # registry files plus the ai project
    template = json.loads((flow.TEMPLATE / "project.json").read_text(encoding="utf-8"))
    for domain in domains:
        if domain == "ai":
            continue
        root = paths.data / "workspaces" / domain / "projects" / "research-program"
        root.mkdir(parents=True, exist_ok=True)
        for name in ("scout_state.json", "admission_state.json"):
            text = (flow.TEMPLATE / name).read_text(encoding="utf-8")
            (root / name).write_text(text.replace('"ai-', f'"{domain}-'), encoding="utf-8")
        project = json.loads(json.dumps(template).replace('"ai-', f'"{domain}-'))
        project["domain"] = domain
        (root / "project.json").write_text(json.dumps(project), encoding="utf-8")


def _program(tmp_path, domains=DOMAINS, **program):
    paths = flow._paths(tmp_path)
    _install_domains(paths, domains)
    db = flow._db(paths)
    settings = flow._settings(**program)
    engine._sync_active_projects(db, paths, settings, engine.TickReport())
    return paths, db, settings


def _scouts(db: FactoryDB) -> list[dict]:
    with db.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM tasks WHERE task_type='topic_scout' ORDER BY created_at, task_id"
        ).fetchall()
    return [dict(row) for row in rows]


def _finish(db: FactoryDB, task_ids) -> None:
    with db.connect() as connection:
        for task_id in task_ids:
            connection.execute("UPDATE tasks SET status='succeeded' WHERE task_id=?", (task_id,))



def _reading(db, settings, runner: str, *windows: dict, observed: datetime = NOW) -> None:
    spec = qr.RUNNERS[runner]
    budget_control.record_quota_snapshot(
        db, settings,
        {"provider": spec.provider, "observed_at": budget_control._iso(observed),
         "model": spec.model, "windows": list(windows)},
        runner=runner,
    )


# --------------------------------------------------------------------------- scouts


def test_parallel_scouts_one_per_domain_up_to_the_cap(tmp_path) -> None:
    paths, db, settings = _program(tmp_path, max_concurrent_scouts=2,
                                   candidate_pool_low_water=4, scout_min_interval_hours=0)
    scheduled, reason = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    assert len(scheduled) == 2
    assert len({item.domain for item in scheduled}) == 2
    assert reason == "max_concurrent_scouts"
    # Each scout asks for its share of what is missing (4 cards over 2 scouts).
    packets = [json.loads(Path(t["input_path"]).read_text()) for t in _scouts(db)]
    assert [p["max_cards"] for p in packets] == [2, 2]
    # The two in-flight scouts are expected to cover the pool: nothing more
    # until one finishes.
    again, reason = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    assert again == [] and reason == "candidate_pool_covered_by_scouts"
    _finish(db, [scheduled[0].task_id])
    third, _ = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    assert len(third) == 1
    busy = {scheduled[1].domain}
    assert third[0].domain not in busy


def test_default_single_scout_behaviour_is_unchanged(tmp_path) -> None:
    paths, db, settings = _program(tmp_path, scout_min_interval_hours=0)
    first, reason = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    assert len(first) == 1 and reason is None
    packet = json.loads(Path(_scouts(db)[0]["input_path"]).read_text())
    assert packet["max_cards"] == settings.program.candidate_pool_low_water
    assert maybe_schedule_scout(db, paths, settings, lead_short=False).reason == "scout_in_flight"


def test_scout_interval_is_per_domain_when_parallel(tmp_path) -> None:
    paths, db, settings = _program(tmp_path, max_concurrent_scouts=3,
                                   candidate_pool_low_water=12, scout_min_interval_hours=2)
    db.update_meta({f"{LAST_SCOUT_KEY}:ai": budget_control._iso(NOW - timedelta(hours=1)),
                    f"{LAST_SCOUT_KEY}:quant": budget_control._iso(NOW - timedelta(hours=3)),
                    LAST_SCOUT_KEY: budget_control._iso(NOW - timedelta(hours=1))})
    scheduled, reason = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    # ai was scouted an hour ago; physics and quant are due despite the
    # program-wide stamp.
    assert sorted(item.domain for item in scheduled) == ["physics", "quant"]
    assert reason == "scout_min_interval"
    # The single-scout default keeps the program-wide interval.
    single = replace(settings, program=replace(settings.program, max_concurrent_scouts=1))
    _finish(db, [item.task_id for item in scheduled])
    db.update_meta({LAST_SCOUT_KEY: budget_control._iso(NOW - timedelta(hours=1))})
    assert maybe_schedule_scout(db, paths, single, lead_short=False, now=NOW).reason == (
        "scout_min_interval"
    )


def test_low_water_counts_in_flight_scouts_expected_cards(tmp_path) -> None:
    paths, db, settings = _program(tmp_path, max_concurrent_scouts=3,
                                   candidate_pool_low_water=5, scout_min_interval_hours=0)
    ledger = open_topic_ledger(paths, settings.program)
    propose_topic(ledger, {"topic_id": "p0", "domain": "ai", "question": "q",
                           "data_sources": ["s"], "primary_endpoint": "e"},
                  db=db, decided_by="s")
    # pool 1, nothing in flight: 4 missing at 2 per scout -> 2 scouts of 2 cards.
    scheduled, reason = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    assert len(scheduled) == 2 and reason == "candidate_pool_covered_by_scouts"
    # pool 1 + 2 in flight x 2 = 5: covered, no third scout although a slot is open.
    again, reason = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    assert again == [] and reason == "candidate_pool_covered_by_scouts"
    # A lower expectation leaves room for one more scout.
    lean = replace(settings, program=replace(settings.program, scout_expected_cards=1.0))
    more, _ = schedule_scouts(db, paths, lean, lead_short=False, now=NOW)
    assert len(more) == 1


def test_expected_cards_calibrate_on_finished_scouts(tmp_path) -> None:
    paths, db, settings = _program(tmp_path, max_concurrent_scouts=3,
                                   candidate_pool_low_water=30, scout_min_interval_hours=0)
    scheduled, _ = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    assert len(scheduled) == 3
    _finish(db, [item.task_id for item in scheduled])
    ledger = open_topic_ledger(paths, settings.program)
    for n in range(3):  # three cards from one scout, none from the other two
        propose_topic(ledger, {"topic_id": f"c{n}", "domain": "ai", "question": f"q{n}",
                               "data_sources": [f"s{n}"], "primary_endpoint": "e"},
                      db=db, decided_by="s",
                      metadata={"source_task_id": scheduled[0].task_id})
    assert expected_cards_per_scout(db, settings, ledger.read()) == pytest.approx(1.0)


# --------------------------------------------------------------------------- admissions


def _two_admission_batches(tmp_path, monkeypatch, per_domain: int):
    paths = flow._paths(tmp_path)
    flow._install_program(paths)
    db = flow._db(paths)
    settings = flow._settings(candidate_pool_low_water=5, scout_min_interval_hours=0,
                              max_admissions_per_domain=per_domain)
    # Fresh readings for both families: unknown ones would allow one task each.
    now = datetime.now(UTC)
    for runner, names in (("worker_gpt", ("seven_day",)),
                          ("lead_claude", ("seven_day", "seven_day_overage_included"))):
        _reading(db, settings, runner, *[
            {"name": name, "used_fraction": 0.05, "window_minutes": 10_080,
             "resets_at": budget_control._iso(now + timedelta(days=3))} for name in names
        ], observed=now)
    flow._scout_round(paths, db, settings, monkeypatch, [flow._card(0, flow.RECEIPT_SHA)])
    first = flow._admission_task(db)
    assert db.task(first["task_id"])["status"] == "leased"
    # The registering tick already scheduled (and launched) the next scout.
    second = [t for t in _scouts(db) if t["status"] == "leased"]
    assert len(second) == 1
    flow._complete(db, paths, second[0]["task_id"],
                   extra={"topic_cards": [flow._card(1, flow.RECEIPT_SHA)]},
                   receipt_files={"data-access.json": flow.RECEIPT})
    flow._tick(paths, settings, monkeypatch)
    with db.connect() as connection:
        rows = [dict(r) for r in connection.execute(
            "SELECT * FROM tasks WHERE routing_reason='topic_admission' ORDER BY created_at"
        ).fetchall()]
    return paths, db, settings, rows


def test_second_admission_batch_runs_beside_the_first_when_allowed(tmp_path, monkeypatch):
    paths, db, settings, rows = _two_admission_batches(tmp_path, monkeypatch, per_domain=2)
    assert len(rows) == 2
    assert [db.task(r["task_id"])["status"] for r in rows] == ["leased", "leased"]
    topics = [{e["topic_id"] for e in flow._packet(r)["topic_cards"]} for r in rows]
    assert topics[0].isdisjoint(topics[1])  # different batches, no topic reviewed twice


def test_one_admission_per_domain_by_default(tmp_path, monkeypatch):
    _, db, _, rows = _two_admission_batches(tmp_path, monkeypatch, per_domain=1)
    assert len(rows) == 1


def test_claim_keeps_one_task_per_campaign_without_parallel_reasons(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    for n in range(2):
        qr._enqueue(db, f"a{n}", "gate", runner="balanced", task_type="portfolio_review",
                    routing_reason="topic_admission")
    assert db.claim_next_task(owner="t", lease_seconds=60)["task_id"] == "a0"
    assert db.claim_next_task(owner="t", lease_seconds=60) is None
    second = db.claim_next_task(owner="t", lease_seconds=60,
                                parallel_routing_reasons=("topic_admission",))
    assert second is not None and second["task_id"] == "a1"
    # A sibling of another kind still waits for the campaign to be free.
    qr._enqueue(db, "other", "gate", runner="balanced", task_type="research")
    assert db.claim_next_task(owner="t", lease_seconds=60,
                              parallel_routing_reasons=("topic_admission",)) is None


def test_new_keys_load_and_default_to_the_old_behaviour(tmp_path) -> None:
    defaults = FactorySettings()
    assert defaults.program.max_concurrent_scouts == 1
    assert defaults.program.max_admissions_per_domain == 1
    assert defaults.routing.utilization_target == 0
    assert defaults.routing.stale_estimate_hours == 0
    assert defaults.budget.adaptive_parallel is False
    config = tmp_path / "openlabs.toml"
    config.write_text(
        "[program]\nmax_concurrent_scouts = 5\nmax_admissions_per_domain = 2\n"
        "max_concurrent_admissions = 6\nscout_expected_cards = 1.5\n"
        "[budget]\nadaptive_parallel = true\nadaptive_step = 1\n"
        "[routing]\nutilization_target = 0.9\nstale_refresh_minutes = 10\n"
        "stale_estimate_hours = 48\n",
        encoding="utf-8",
    )
    paths = replace(qr._paths(tmp_path / "w"), config_file=config)
    loaded = load_settings(paths)
    assert loaded.program.max_concurrent_scouts == 5
    assert loaded.program.max_concurrent_admissions == 6
    assert loaded.program.scout_expected_cards == 1.5
    assert loaded.budget.adaptive_parallel and loaded.budget.adaptive_step == 1
    assert loaded.routing.utilization_target == 0.9
    assert loaded.routing.stale_refresh_minutes == 10
    assert loaded.routing.stale_estimate_hours == 48
    repository = load_settings(replace(paths, config_file=flow.CODE_ROOT / "config" /
                                       "openlabs.toml"))
    assert repository.routing.utilization_target == 0
    assert repository.program.max_concurrent_scouts == 1
    assert repository.budget.adaptive_parallel is False
