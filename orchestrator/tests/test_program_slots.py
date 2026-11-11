from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from openlabs.config import (
    FactorySettings,
    ProgramSettings,
    WorkspacePaths,
    load_settings,
)
from openlabs.contracts import atomic_write_json
from openlabs.db import FactoryDB
from openlabs.engine import tick
from openlabs.program import (
    IllegalTopicTransition,
    TopicLedgerError,
    TopicSlotUnavailable,
    activate_topic,
    admit_topic,
    freeze_topic,
    mark_topic_in_review,
    mark_topic_ready,
    mark_topic_submitted,
    open_topic_ledger,
    program_slots,
    propose_topic,
    reject_topic,
    slot_status,
    topic_fingerprint,
)

EVIDENCE = [{"path": "workspaces/ai/t/primary-analysis.json", "sha256": "a" * 64}]


def _paths(tmp_path: Path) -> WorkspacePaths:
    paths = WorkspacePaths(
        workspace=tmp_path,
        code=tmp_path / "openlabs",
        data=tmp_path / "openlabs-data",
        artifacts=tmp_path / "openlabs-artifacts",
        database=tmp_path / "openlabs-database",
        database_file=tmp_path / "openlabs-database" / "live" / "factory.sqlite",
    )
    paths.ensure_runtime_directories()
    return paths


def _program(**overrides) -> ProgramSettings:
    return replace(ProgramSettings(enabled=True), **overrides)


def _setup(tmp_path: Path, **program):
    paths = _paths(tmp_path)
    db = FactoryDB(paths.database_file)
    db.initialize()
    settings = _program(**program)
    return paths, db, settings, open_topic_ledger(paths, settings)


def _card(n: int, **extra) -> dict:
    card = {
        "topic_id": f"topic-{n}",
        "domain": "ai",
        "question": f"Does intervention {n} reduce readmission?",
        "data_sources": [f"source-{n}"],
        "primary_endpoint": "30-day readmission",
        "target_tier": 3,
    }
    card.update(extra)
    return card


def _active_topic(paths, db, settings, ledger, n: int) -> str:
    topic_id = f"topic-{n}"
    propose_topic(ledger, _card(n), db=db, decided_by=f"scout-{n}")
    admit_topic(
        ledger,
        topic_id,
        db=db,
        settings=settings,
        decided_by=f"gate-{n}",
        admission_task_id=f"gate-{n}",
        preregistration_sha256="b" * 64,
    )
    db.register_campaign(f"campaign-{n}", domain="ai", title=f"Topic {n}")
    activate_topic(ledger, topic_id, db=db, campaign_id=f"campaign-{n}", decided_by="materialize")
    return topic_id


def _topic_events(db: FactoryDB, topic_id: str | None = None) -> list[dict]:
    return db.events(entity_type="topic", entity_id=topic_id)


def test_full_program_reports_zero_free_slots(tmp_path) -> None:
    paths, db, settings, ledger = _setup(tmp_path, max_active_topics=3)
    for n in range(3):
        _active_topic(paths, db, settings, ledger, n)
    mark_topic_in_review(ledger, "topic-2", db=db, decided_by="review-2", paper_id="p-2")

    status = program_slots(paths, settings)
    assert (status.active, status.in_review, status.occupied) == (2, 1, 3)
    assert status.free_slots == 0
    assert not status.can_admit

    propose_topic(ledger, _card(9), db=db, decided_by="scout-9")
    with pytest.raises(TopicSlotUnavailable):
        admit_topic(
            ledger, "topic-9", db=db, settings=settings, decided_by="gate", admission_task_id="g"
        )

    report = tick(paths, FactorySettings(launch_jobs=False, program=settings))
    assert report.program["free_slots"] == 0
    assert report.program["occupied"] == 3
    assert report.program["max_active_topics"] == 3
    assert report.to_dict()["program"]["free_slots"] == 0


def test_freeze_releases_slot_and_records_ledger_and_events(tmp_path) -> None:
    paths, db, settings, ledger = _setup(tmp_path, max_active_topics=2)
    for n in range(2):
        _active_topic(paths, db, settings, ledger, n)
    db.enqueue_task(
        task_id="queued-0",
        campaign_id="campaign-0",
        domain="ai",
        task_type="research",
        objective="Continue the analysis.",
    )
    assert slot_status(ledger.read(), settings).free_slots == 0

    decision = freeze_topic(
        ledger,
        "topic-0",
        db=db,
        reason_class="primary_endpoint_failed",
        evidence=EVIDENCE,
        decided_by="judge-task-1",
        reopen_conditions=[{"type": "new_data_source", "description": "Linked claims data."}],
    )

    assert decision.status == "frozen" and decision.changed
    assert decision.cancelled_tasks == ("queued-0",)
    assert slot_status(ledger.read(), settings).free_slots == 1
    topic = ledger.topic("topic-0")
    assert topic["freeze_reason_class"] == "primary_endpoint_failed"
    assert topic["freeze_evidence"] == EVIDENCE
    assert topic["decided_by"] == "judge-task-1"
    assert topic["frozen_at"]
    assert topic["history"][-1]["from"] == "active"
    assert topic["history"][-1]["to"] == "frozen"
    assert topic["history"][-1]["evidence"] == EVIDENCE
    assert db.campaign("campaign-0")["status"] == "frozen"
    assert db.task("queued-0")["status"] == "cancelled"
    types = [event["event_type"] for event in _topic_events(db, "topic-0")]
    assert types == ["topic_proposed", "topic_admitted", "topic_activated", "topic_frozen"]
    campaign_events = [
        e["event_type"] for e in db.events(entity_type="campaign", entity_id="campaign-0")
    ]
    assert "campaign_frozen" in campaign_events

    report = tick(paths, FactorySettings(launch_jobs=False, program=settings))
    assert report.program["free_slots"] == 1
    assert report.program["status_counts"]["frozen"] == 1


def test_frozen_campaign_is_not_claimed(tmp_path) -> None:
    paths, db, settings, ledger = _setup(tmp_path)
    _active_topic(paths, db, settings, ledger, 0)
    freeze_topic(
        ledger, "topic-0", db=db, reason_class="overdue", evidence=EVIDENCE, decided_by="j"
    )
    # enqueue_task refuses inactive campaigns; even a row written directly after
    # the freeze must never be claimed.
    with db.connect() as connection:
        connection.execute(
            "INSERT INTO tasks(task_id, campaign_id, domain, task_type, objective, status, "
            "created_at, updated_at) VALUES('late-task', 'campaign-0', 'ai', 'research', "
            "'x', 'queued', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )
    assert db.claim_next_task(owner="test", lease_seconds=30) is None


def _write_project_plan(paths: WorkspacePaths, lane_id: str) -> Path:
    plan_path = (
        paths.data / "workspaces" / "math" / "production" / "test-plan" / "production_plan.json"
    )
    lane_path = paths.data / "workspaces" / "math" / lane_id / "production_lane.json"
    atomic_write_json(
        plan_path,
        {
            "schema_version": "openlabs.math_production_plan.v1",
            "plan_id": "test-plan",
            "status": "active",
            "objective": "Produce results.",
            "lanes": [
                {
                    "lane_id": lane_id,
                    "config_path": f"../../{lane_id}/production_lane.json",
                    "startup": "active",
                    "priority": 3,
                }
            ],
        },
    )
    atomic_write_json(
        lane_path,
        {
            "schema_version": "openlabs.math_production_lane.v1",
            "plan_id": "test-plan",
            "lane_id": lane_id,
            "plan_path": "../production/test-plan/production_plan.json",
            "stage": "radar",
            "cycle": 1,
            "theme": {"name": "Lane"},
            "selection_gate": {},
            "node_policy": {},
            "selected_target": None,
            "archived_targets": [],
            "nodes": [],
            "history": [],
        },
    )
    return plan_path


def test_frozen_campaign_is_not_reactivated_or_blocked_by_project_sync(tmp_path) -> None:
    paths, db, settings, ledger = _setup(tmp_path)
    lane_id = "frozen-lane"
    plan_path = _write_project_plan(paths, lane_id)
    tick(paths, FactorySettings(auto_continue=False, launch_jobs=False))
    assert db.campaign(lane_id)["status"] == "active"
    assert db.campaign(lane_id)["continuous"] == 1

    db.freeze_campaign(lane_id, reason="test")
    report = tick(paths, FactorySettings(launch_jobs=False))
    campaign = db.campaign(lane_id)
    assert campaign["status"] == "frozen"
    assert report.production_blocked == []
    assert lane_id not in report.production_synced
    assert lane_id not in report.production_paused
    assert report.enqueued == []

    # Plan leaves desired state: the frozen campaign is skipped, not paused.
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["status"] = "paused"
    atomic_write_json(plan_path, plan)
    report = tick(paths, FactorySettings(launch_jobs=False))
    assert db.campaign(lane_id)["status"] == "frozen"
    assert report.production_paused == []
    assert report.production_blocked == []


def test_ledger_writes_are_atomic_and_idempotent(tmp_path, monkeypatch) -> None:
    paths, db, settings, ledger = _setup(tmp_path)
    _active_topic(paths, db, settings, ledger, 0)
    before = ledger.path.read_bytes()
    # Replaying every decision changes nothing and duplicates no history or event.
    _active_topic(paths, db, settings, ledger, 0)
    assert ledger.path.read_bytes() == before
    for _ in range(2):
        freeze_topic(
            ledger,
            "topic-0",
            db=db,
            reason_class="decisive_data_unavailable",
            evidence=EVIDENCE,
            decided_by="judge",
        )
    topic = ledger.topic("topic-0")
    assert [entry["to"] for entry in topic["history"]] == [
        "proposed",
        "admitted",
        "active",
        "frozen",
    ]
    assert len(_topic_events(db, "topic-0")) == 4
    assert not list(ledger.path.parent.glob(".topic-ledger.json.*"))

    # A crash during the write leaves the previous ledger intact.
    snapshot = ledger.path.read_bytes()

    def explode(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("openlabs.contracts.os.replace", explode)
    with pytest.raises(OSError):
        propose_topic(ledger, _card(5), db=db, decided_by="scout")
    assert ledger.path.read_bytes() == snapshot
    assert not list(ledger.path.parent.glob(".topic-ledger.json.*"))
    assert ledger.topic("topic-5") is None


def test_illegal_transitions_are_rejected(tmp_path) -> None:
    paths, db, settings, ledger = _setup(tmp_path)
    propose_topic(ledger, _card(0), db=db, decided_by="scout")
    with pytest.raises(IllegalTopicTransition):
        mark_topic_in_review(ledger, "topic-0", db=db, decided_by="x")
    with pytest.raises(IllegalTopicTransition):
        freeze_topic(
            ledger, "topic-0", db=db, reason_class="overdue", evidence=EVIDENCE, decided_by="j"
        )
    with pytest.raises(TopicLedgerError):
        freeze_topic(
            ledger, "topic-0", db=db, reason_class="bored", evidence=EVIDENCE, decided_by="j"
        )
    reject_topic(ledger, "topic-0", db=db, reason="weak_contribution", decided_by="gate")
    with pytest.raises(IllegalTopicTransition):
        admit_topic(
            ledger, "topic-0", db=db, settings=settings, decided_by="g", admission_task_id="g"
        )

    _active_topic(paths, db, settings, ledger, 1)
    mark_topic_in_review(ledger, "topic-1", db=db, decided_by="r")
    mark_topic_ready(ledger, "topic-1", db=db, decided_by="r2", paper_id="paper-1")
    with pytest.raises(IllegalTopicTransition):
        freeze_topic(
            ledger, "topic-1", db=db, reason_class="overdue", evidence=EVIDENCE, decided_by="j"
        )
    mark_topic_submitted(ledger, "topic-1", db=db, decided_by="submit")
    with pytest.raises(IllegalTopicTransition):
        mark_topic_ready(ledger, "topic-1", db=db, decided_by="other")
    # Freeze needs evidence with a path and a digest.
    _active_topic(paths, db, settings, ledger, 2)
    with pytest.raises(TopicLedgerError):
        freeze_topic(ledger, "topic-2", db=db, reason_class="overdue", evidence=[], decided_by="j")
    assert ledger.topic("topic-2")["status"] == "active"
    # Rejected decisions left no trace in the ledger history.
    assert [e["to"] for e in ledger.topic("topic-0")["history"]] == ["proposed", "rejected"]


def test_duplicate_fingerprint_rejected_and_reopen_supersedes(tmp_path) -> None:
    paths, db, settings, ledger = _setup(tmp_path)
    _active_topic(paths, db, settings, ledger, 0)
    assert topic_fingerprint("A  Question?", ["s1", "S2"], "Endpoint") == topic_fingerprint(
        "a question", ["s2", "s1"], "endpoint."
    )

    same = _card(0, topic_id="topic-dup", question="  DOES intervention 0 reduce readmission ")
    decision = propose_topic(ledger, same, db=db, decided_by="scout-2")
    assert decision.status == "rejected"
    assert decision.reason == "duplicate_fingerprint"
    assert decision.duplicate_of == ("topic-0",)
    rejected_events = [
        e for e in _topic_events(db, "topic-dup") if e["event_type"] == "topic_rejected"
    ]
    assert rejected_events[0]["payload"]["duplicate_of"] == ["topic-0"]

    # Reopening a topic that is not frozen is rejected too.
    reopen = _card(
        0,
        topic_id="topic-0b",
        reopens="topic-0",
        reopen_basis={"type": "new_data_source", "description": "New registry linkage."},
    )
    assert propose_topic(ledger, reopen, db=db, decided_by="s").reason == (
        "reopens_topic_not_frozen"
    )

    freeze_topic(
        ledger,
        "topic-0",
        db=db,
        reason_class="decisive_data_unavailable",
        evidence=EVIDENCE,
        decided_by="judge",
        reopen_conditions=[{"type": "new_data_source", "description": "Registry linkage."}],
    )
    # Without reopens the identical card is still a duplicate.
    plain = propose_topic(ledger, _card(0, topic_id="topic-0c"), db=db, decided_by="s")
    assert plain.status == "rejected"
    # Basis type must match a declared reopen condition.
    wrong = _card(
        0,
        topic_id="topic-0d",
        reopens="topic-0",
        reopen_basis={"type": "new_method", "description": "Different estimator."},
    )
    assert propose_topic(ledger, wrong, db=db, decided_by="s").reason == (
        "reopen_basis_not_declared_by_frozen_topic"
    )

    accepted = propose_topic(
        ledger, _card(0, topic_id="topic-0e", reopens="topic-0", reopen_basis={
            "type": "new_data_source", "description": "Registry linkage now public."
        }), db=db, decided_by="scout-3",
    )
    assert accepted.status == "proposed"
    assert accepted.supersedes == "topic-0"
    assert ledger.topic("topic-0e")["supersedes"] == "topic-0"
    assert ledger.topic("topic-0e")["topic_id"] != "topic-0"
    # The frozen topic can be superseded only once.
    again = _card(
        0,
        topic_id="topic-0f",
        reopens="topic-0",
        reopen_basis={"type": "new_data_source", "description": "Another linkage."},
    )
    assert propose_topic(ledger, again, db=db, decided_by="s").reason == (
        "reopens_topic_already_superseded"
    )
    # Same topic_id with a different card is a conflict, same card is a no-op.
    assert not propose_topic(ledger, _card(0, topic_id="topic-0c"), db=db, decided_by="s").changed
    with pytest.raises(TopicLedgerError):
        propose_topic(ledger, _card(1, topic_id="topic-0c"), db=db, decided_by="s")


def test_ready_queue_over_limit_pauses_admission(tmp_path) -> None:
    paths, db, settings, ledger = _setup(tmp_path, max_active_topics=5, max_ready_unsubmitted=1)
    for n in range(2):
        _active_topic(paths, db, settings, ledger, n)
        mark_topic_in_review(ledger, f"topic-{n}", db=db, decided_by="r")
        mark_topic_ready(ledger, f"topic-{n}", db=db, decided_by="r2")
    status = slot_status(ledger.read(), settings)
    assert status.occupied == 0 and status.free_slots == 5
    assert status.ready_unsubmitted == 2
    assert status.admission_paused and status.pause_reasons == ["ready_queue_over_limit"]
    propose_topic(ledger, _card(7), db=db, decided_by="scout")
    with pytest.raises(TopicSlotUnavailable):
        admit_topic(
            ledger, "topic-7", db=db, settings=settings, decided_by="g", admission_task_id="g"
        )
    report = tick(paths, FactorySettings(launch_jobs=False, program=settings))
    assert report.program["admission_paused"] is True
    assert report.program["free_slots"] == 5

    mark_topic_submitted(ledger, "topic-0", db=db, decided_by="submit")
    assert not slot_status(ledger.read(), settings).admission_paused


def test_tick_reconciles_frozen_topic_whose_campaign_is_still_active(tmp_path) -> None:
    paths, db, settings, ledger = _setup(tmp_path)
    _active_topic(paths, db, settings, ledger, 0)
    db.enqueue_task(
        task_id="queued-0",
        campaign_id="campaign-0",
        domain="ai",
        task_type="research",
        objective="Continue.",
    )
    # Simulate a crash after the ledger write but before the campaign freeze.
    with ledger.transaction() as document:
        topic = document["topics"][0]
        topic["status"] = "frozen"
        topic["freeze_reason_class"] = "overdue"
    report = tick(paths, FactorySettings(launch_jobs=False, program=settings))
    assert report.program["campaigns_frozen"] == ["campaign-0"]
    assert "queued-0" in report.cancelled
    assert db.campaign("campaign-0")["status"] == "frozen"


def test_disabled_program_creates_no_ledger_and_keeps_tick_unchanged(tmp_path) -> None:
    paths = _paths(tmp_path)
    db = FactoryDB(paths.database_file)
    db.initialize()
    db.register_campaign("c", domain="ai", title="c")
    db.enqueue_task(task_id="t", campaign_id="c", domain="ai", task_type="research", objective="o")
    settings = FactorySettings(launch_jobs=False)
    assert settings.program.enabled is False

    report = tick(paths, settings).to_dict()

    assert report["program"] == {}
    assert not (paths.data / "registry").exists()
    assert not (paths.database / "live" / "topic-ledger.lock").exists()
    assert db.events(entity_type="topic") == []
    assert set(report) == {
        "schema_version", "ingested", "recovered", "quarantined", "cancelled", "launched",
        "enqueued", "budget_stopped", "production_synced", "production_paused",
        "production_reseeded", "production_blocked", "rollovers", "attempts_committed",
        "attempts_quarantined", "attempts_recovered", "errors", "status_counts",
        "resource_capacity", "resource_reserved", "program",
    }
    assert report["errors"] == []
    assert db.task("t")["status"] == "queued"

    # Enabled but with no ledger yet: report slots, still do not create the file.
    enabled = FactorySettings(launch_jobs=False, program=ProgramSettings(enabled=True))
    report = tick(paths, enabled)
    assert report.program["free_slots"] == 5
    assert report.program["ledger_exists"] is False
    assert not (paths.data / "registry" / "topic-ledger.json").exists()


def test_program_config_is_loaded_from_toml(tmp_path) -> None:
    paths = _paths(tmp_path)
    config = paths.code / "config" / "openlabs.toml"
    config.parent.mkdir(parents=True)
    config.write_text("[factory]\nlaunch_jobs = false\n", encoding="utf-8")
    assert load_settings(paths).program == ProgramSettings()
    config.write_text(
        "[program]\nenabled = true\nmax_active_topics = 4\nmax_ready_unsubmitted = 2\n"
        'ledger_path = "registry/topics.json"\n',
        encoding="utf-8",
    )
    program = load_settings(paths).program
    assert program == ProgramSettings(
        enabled=True, max_active_topics=4, max_ready_unsubmitted=2,
        ledger_path="registry/topics.json",
    )
    config.write_text('[program]\nledger_path = "../escape.json"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_settings(paths)
    repository = Path(__file__).resolve().parents[2] / "config" / "openlabs.toml"
    assert load_settings(replace(paths, code=repository.parents[1])).program == ProgramSettings()
