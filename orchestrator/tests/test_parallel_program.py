"""Parallel topic scouts (one per domain/line, bounded by the candidate pool) and parallel
review batches."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import test_quota_routing as qr
import test_research_program_flow as flow
from openlabs import budget as budget_control
from openlabs import engine
from openlabs.config import FactorySettings, SupplySettings, load_settings
from openlabs.db import FactoryDB
from openlabs.program_flow import (
    LAST_SCOUT_KEY,
    maybe_schedule_scout,
    schedule_scouts,
)

NOW = qr.NOW
DOMAINS = ("ai", "physics", "quant")


# --------------------------------------------------------------------------- helpers


def _install_domains(paths, domains=DOMAINS) -> None:
    flow._install_program(paths)
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
    paths, db, settings = _program(
        tmp_path,
        supply=SupplySettings(max_concurrent_scouts=2, candidate_pool_size=4, scout_min_interval_hours=0),
    )
    scheduled, reason = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    assert len(scheduled) == 2
    assert len({item.domain for item in scheduled}) == 2
    assert reason == "max_concurrent_scouts"
    again, reason = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    assert again == [] and reason == "max_concurrent_scouts"
    _finish(db, [scheduled[0].task_id])
    third, _ = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    assert len(third) == 1
    assert third[0].domain != scheduled[1].domain


def test_single_scout_cap_blocks_second_scout(tmp_path) -> None:
    paths, db, settings = _program(
        tmp_path,
        supply=SupplySettings(max_concurrent_scouts=1, scout_min_interval_hours=0),
    )
    first, reason = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    assert len(first) == 1 and reason is None
    packet = json.loads(Path(_scouts(db)[0]["input_path"]).read_text())
    assert packet["max_proposals"] == settings.program.supply.candidate_pool_size
    assert maybe_schedule_scout(db, paths, settings, lead_short=False).reason == "scout_in_flight"


def test_scout_interval_is_per_domain_when_parallel(tmp_path) -> None:
    paths, db, settings = _program(
        tmp_path,
        supply=SupplySettings(max_concurrent_scouts=3, candidate_pool_size=12, scout_min_interval_hours=2),
    )
    db.update_meta({f"{LAST_SCOUT_KEY}:ai": budget_control._iso(NOW - timedelta(hours=1)),
                    f"{LAST_SCOUT_KEY}:quant": budget_control._iso(NOW - timedelta(hours=3)),
                    LAST_SCOUT_KEY: budget_control._iso(NOW - timedelta(hours=1))})
    scheduled, reason = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    assert sorted(item.domain for item in scheduled) == ["physics", "quant"]
    assert reason == "scout_min_interval"
    single = replace(
        settings,
        program=replace(settings.program, supply=replace(settings.program.supply, max_concurrent_scouts=1)),
    )
    _finish(db, [item.task_id for item in scheduled])
    later = maybe_schedule_scout(db, paths, single, lead_short=False, now=NOW + timedelta(hours=1))
    assert later.task_id is not None and later.domain == "ai"


# --------------------------------------------------------------------------- admissions


def _two_admission_batches(tmp_path, monkeypatch, max_reviews: int):
    paths = flow._paths(tmp_path)
    flow._install_program(paths)
    db = flow._db(paths)
    settings = flow._settings(
        supply=SupplySettings(candidate_pool_size=5, scout_min_interval_hours=0,
                              max_concurrent_reviews=max_reviews),
    )
    now = datetime.now(UTC)
    for runner, names in (("worker_gpt", ("seven_day",)),
                          ("lead_claude", ("seven_day", "seven_day_overage_included"))):
        _reading(db, settings, runner, *[
            {"name": name, "used_fraction": 0.05, "window_minutes": 10_080,
             "resets_at": budget_control._iso(now + timedelta(days=3))} for name in names
        ], observed=now)
    flow._scout_round(paths, db, settings, monkeypatch, [flow._card(0)])
    first = flow._admission_task(db)
    assert db.task(first["task_id"])["status"] == "leased"
    second = [t for t in _scouts(db) if t["status"] == "leased"]
    assert len(second) == 1
    flow._complete(db, paths, second[0]["task_id"], extra={"topic_proposals": [flow._card(1)]})
    flow._tick(paths, settings, monkeypatch)
    with db.connect() as connection:
        rows = [dict(r) for r in connection.execute(
            "SELECT * FROM tasks WHERE routing_reason='topic_admission' ORDER BY rowid"
        ).fetchall()]
    return paths, db, settings, rows


def test_second_review_batch_runs_beside_the_first_when_allowed(tmp_path, monkeypatch):
    paths, db, settings, rows = _two_admission_batches(tmp_path, monkeypatch, max_reviews=2)
    assert len(rows) == 2
    assert [db.task(r["task_id"])["status"] for r in rows] == ["leased", "leased"]
    topics = [{e["topic_id"] for e in flow._packet(r)["topic_proposals"]} for r in rows]
    assert topics[0].isdisjoint(topics[1])


def test_one_review_batch_when_max_concurrent_reviews_is_one(tmp_path, monkeypatch):
    _, db, _, rows = _two_admission_batches(tmp_path, monkeypatch, max_reviews=1)
    assert len(rows) == 1


def test_admission_batches_share_their_campaign_and_others_wait(tmp_path) -> None:
    _, db = qr._setup(tmp_path)
    for n in range(2):
        qr._enqueue(db, f"a{n}", "gate", runner="balanced", task_type="portfolio_review",
                    routing_reason="topic_admission")
    assert db.claim_next_task(owner="t", lease_seconds=60)["task_id"] == "a0"
    second = db.claim_next_task(owner="t", lease_seconds=60)
    assert second is not None and second["task_id"] == "a1"
    qr._enqueue(db, "other", "gate", runner="balanced", task_type="research")
    assert db.claim_next_task(owner="t", lease_seconds=60) is None


def test_supply_and_routing_keys_load_from_toml(tmp_path) -> None:
    defaults = FactorySettings()
    assert defaults.program.supply.max_concurrent_scouts == 2
    assert defaults.program.supply.max_concurrent_reviews == 4
    assert defaults.routing.utilization_target == 0
    assert defaults.routing.stale_estimate_hours == 0
    assert defaults.budget.adaptive_parallel is False
    config = tmp_path / "openlabs.toml"
    config.write_text(
        "[program.supply]\nmax_concurrent_scouts = 5\nmax_concurrent_reviews = 6\n"
        "[budget]\nadaptive_parallel = true\nadaptive_step = 1\n"
        "[routing]\nutilization_target = 0.9\nstale_refresh_minutes = 10\n"
        "stale_estimate_hours = 48\n",
        encoding="utf-8",
    )
    paths = replace(qr._paths(tmp_path / "w"), config_file=config)
    loaded = load_settings(paths)
    assert loaded.program.supply.max_concurrent_scouts == 5
    assert loaded.program.supply.max_concurrent_reviews == 6
