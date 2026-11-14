"""Research-program front end: topic scout, card intake, admission gate, materialization."""

from __future__ import annotations

import importlib.util
import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from openlabs import engine
from openlabs.config import (
    BudgetSettings,
    FactorySettings,
    ProgramSettings,
    RunnerSpec,
    WorkspacePaths,
)
from openlabs.contracts import (
    RECEIPT_SCHEMA,
    RESULT_SCHEMA,
    atomic_write_json,
    preregistration_sha256,
    sha256_file,
    validate_topic_admission,
    validate_topic_card,
)
from openlabs.db import FactoryDB
from openlabs.program import (
    activate_topic,
    admit_topic,
    freeze_topic,
    last_rejection_reason,
    mark_topic_in_review,
    mark_topic_ready,
    open_topic_ledger,
    parked_program_projects,
    propose_topic,
    slot_status,
)
from openlabs.program_flow import (
    LAST_SCOUT_KEY,
    backfill_grandfathered,
    intake_card,
    materialize_waiting_topics,
    maybe_schedule_scout,
    run_program_pipeline,
)
from openlabs.portfolio import spawn_candidate_workstreams
from openlabs.projects import load_project

CODE_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = CODE_ROOT / "packages" / "contracts" / "examples" / "research-program"
GPT, CLAUDE = "openai-codex", "anthropic"
RUNNERS = {
    "lead_gpt": RunnerSpec("lead_gpt", GPT, "lead", "gpt-6-astra"),
    "lead_claude": RunnerSpec(
        "lead_claude", CLAUDE, "lead", "claude-fable-5-2",
        windows=("seven_day_overage_included",), protected=True,
    ),
    "worker_gpt": RunnerSpec("worker_gpt", GPT, "worker", "gpt-6.1-sol"),
    "worker_claude": RunnerSpec("worker_claude", CLAUDE, "worker", "claude-opus-5-5"),
}
CLAUDE_ONLY = {name: spec for name, spec in RUNNERS.items() if spec.provider == CLAUDE}
YEAR = datetime.now(UTC).year
EVIDENCE = [{"path": "workspaces/ai/x/primary.json", "sha256": "e" * 64}]


# --------------------------------------------------------------------------- fixtures


def _paths(tmp_path: Path, code: Path = CODE_ROOT) -> WorkspacePaths:
    paths = WorkspacePaths(
        workspace=tmp_path,
        code=code,
        data=tmp_path / "openlabs-data",
        artifacts=tmp_path / "openlabs-artifacts",
        database=tmp_path / "openlabs-database",
        database_file=tmp_path / "openlabs-database" / "live" / "factory.sqlite",
    )
    paths.ensure_runtime_directories()
    return paths


def _settings(runners=RUNNERS, **program) -> FactorySettings:
    return FactorySettings(
        max_worker_processes=8,
        retry_backoff_seconds=0,
        reserve_cpu_threads=0,
        reserve_memory_mib=0,
        reserve_scratch_mib=0,
        default_task_cpu_threads=1,
        default_task_memory_mib=64,
        default_task_scratch_mib=16,
        budget=BudgetSettings(max_parallel_agents=4),
        runners=dict(runners),
        program=ProgramSettings(enabled=True, **program),
    )


def _install_program(paths: WorkspacePaths) -> Path:
    root = paths.data / "workspaces" / "ai" / "projects" / "research-program"
    root.mkdir(parents=True, exist_ok=True)
    for name in ("project.json", "scout_state.json", "admission_state.json"):
        shutil.copyfile(TEMPLATE / name, root / name)
    registry = paths.data / "registry"
    registry.mkdir(parents=True, exist_ok=True)
    (registry / "settings.yaml").write_text("research_portfolio: {}\n", encoding="utf-8")
    atomic_write_json(registry / "journal-rejections.json", {"rejections": []})
    atomic_write_json(registry / "reusable-assets.json", {"assets": []})
    return root / "project.json"


def _db(paths: WorkspacePaths) -> FactoryDB:
    db = FactoryDB(paths.database_file)
    db.initialize()
    return db


def _tick(paths: WorkspacePaths, settings: FactorySettings, monkeypatch) -> engine.TickReport:
    monkeypatch.setattr(engine, "_launch_task", lambda *_args, **_kwargs: None)
    return engine.tick(paths, settings)


def _card(n: int = 0, receipt_sha: str = "0" * 64, **override) -> dict:
    card = json.loads((TEMPLATE / "topic-card.example.json").read_text(encoding="utf-8"))
    card["question"] = f"Question {n}: does retrieval keep its advantage on a later year?"
    card["data_sources"] = [
        {"doi": f"10.13026/example-{n}", "version": "2.2", "license": "PhysioNet 1.5.0"}
    ]
    for item in card["audience"]["citations"]:
        item["year"] = YEAR - 1
    card["decisive_analysis"]["access_receipt"] = {
        "path": "receipts/data-access.json", "sha256": receipt_sha,
    }
    card.update(override)
    return card


def _complete(
    db: FactoryDB,
    paths: WorkspacePaths,
    task_id: str,
    *,
    extra: dict | None = None,
    receipt_files: dict[str, bytes] | None = None,
) -> Path:
    """Fake agent: write a result bundle and receipt for a leased task."""

    task = db.task(task_id)
    assert task is not None and task["status"] == "leased", task
    attempt_id = str(task["current_attempt_id"])
    campaign_root = paths.data / "workspaces" / str(task["domain"]) / str(task["campaign_id"])
    output = campaign_root / "attempts" / attempt_id / "result.json"
    db.bind_attempt_spec(task_id, attempt_id=attempt_id, lab_id="ai", output_path=str(output))
    db.mark_running(task_id, attempt_id=attempt_id, owner="test", pid=1, lease_seconds=600)
    artifacts = []
    for index, (name, content) in enumerate(sorted((receipt_files or {}).items())):
        path = campaign_root / "receipts" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        artifacts.append({"artifact_id": f"receipt-{index}", "kind": "data_access_receipt",
                          "uri": path.resolve().as_uri(), "sha256": sha256_file(path)})
    payload = {
        "schema_version": RESULT_SCHEMA, "task_id": task_id, "campaign_id": task["campaign_id"],
        "lab_id": "ai", "domain": task["domain"], "status": "succeeded",
        "summary": "Fake agent step.", "artifacts": artifacts, "claims": [],
        "next_actions": [], "paper_candidate": False, **(extra or {}),
    }
    atomic_write_json(output, payload)
    atomic_write_json(paths.result_inbox / f"{attempt_id}.json", {
        "schema_version": RECEIPT_SCHEMA, "task_id": task_id, "attempt_id": attempt_id,
        "campaign_id": task["campaign_id"], "lab_id": "ai", "domain": task["domain"],
        "agent_role": task["agent_role"], "result_path": str(output),
        "sha256": sha256_file(output),
        "runtime": {"duration_seconds": 1.0, "exit_code": 0, "runner": task["runner"]},
    })
    return output


RECEIPT = b'{"source": "physionet", "rows": 1024}\n'
RECEIPT_SHA = __import__("hashlib").sha256(RECEIPT).hexdigest()


def _scout_round(paths, db, settings, monkeypatch, cards) -> tuple[str, engine.TickReport]:
    """Tick to schedule+claim a scout, deliver ``cards``, tick to register them."""

    first = _tick(paths, settings, monkeypatch)
    scouts = first.program["scouts_scheduled"]
    assert len(scouts) == 1, first.program
    scout_id = scouts[0]["task_id"]
    assert scout_id in first.launched
    _complete(db, paths, scout_id, extra={"topic_cards": cards},
              receipt_files={"data-access.json": RECEIPT})
    return scout_id, _tick(paths, settings, monkeypatch)


def _admission_task(db: FactoryDB) -> dict:
    with db.connect() as connection:
        row = connection.execute(
            "SELECT * FROM tasks WHERE routing_reason='topic_admission' "
            "ORDER BY created_at DESC, task_id DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    return dict(row)


def _branch(entry: dict, verdict: str = "admit", **admission_override) -> dict:
    endpoint = dict(entry["card"]["primary_endpoint"])
    admission = {
        "verdict": verdict,
        "target_tier": "routine",
        "tier_rationale": "Routine readers; no external cohort.",
        "strongest_rejection_reason": "Could be read as one more benchmark.",
        "closest_prior_work_checked": [
            {"citation": "Example A 2025", "assessment": "Random split only; difference holds."}
        ],
        "data_access_confirmed": True,
        "cost_judgement": {"proportionate": True, "rationale": "Reuses a pipeline."},
        "preregistration": {"primary_endpoint": endpoint,
                            "sha256": preregistration_sha256(endpoint)},
        "reopen_conditions": [],
    }
    if verdict == "hold":
        admission["reopen_conditions"] = [
            {"type": "new_data_source", "description": "A second admission year is released."}
        ]
    admission.update(admission_override)
    return {
        "candidate_id": entry["topic_id"],
        "topic_id": entry["topic_id"],
        "title": entry["card"]["question"][:60],
        "objective": "Run the pre-registered temporal comparison.",
        "rationale": "Judged by the gate.",
        "source_result_ids": [entry["source_result_id"]],
        "admission": admission,
    }


def _packet(task: dict) -> dict:
    return json.loads(Path(str(task["input_path"])).read_text(encoding="utf-8"))


def _to_admission(paths, db, settings, monkeypatch, cards):
    """Run scout + registration; return (scout id, admission task after claim, report)."""

    scout_id, report = _scout_round(paths, db, settings, monkeypatch, cards)
    admission = _admission_task(db)
    return scout_id, admission, report


# --------------------------------------------------------------------------- contracts


def test_topic_card_contract_names_missing_fields() -> None:
    assert validate_topic_card(_card(), current_year=YEAR).valid
    missing = _card()
    for name in ("audience", "cost_estimate", "venues"):
        missing.pop(name)
    check = validate_topic_card(missing, current_year=YEAR)
    # Audience evidence is for the gate to weigh: a warning, not a rejection.
    assert any(error.startswith("audience is missing") for error in check.warnings)
    assert any(error.startswith("cost_estimate is missing") for error in check.errors)
    assert any(error.startswith("venues is missing") for error in check.errors)
    stale = _card()
    for item in stale["audience"]["citations"]:
        item["year"] = YEAR - 6
    stale_check = validate_topic_card(stale, current_year=YEAR)
    assert stale_check.valid and any("last 3 years" in e for e in stale_check.warnings)
    # Only gaps admission cannot judge around reject the card.
    for name in ("primary_endpoint", "data_sources", "question"):
        gap = _card()
        gap.pop(name)
        assert not validate_topic_card(gap, current_year=YEAR).valid, name
    no_venue = _card()
    no_venue["venues"]["routine"] = []
    assert any(e.startswith("venues.routine needs a named routine target venue")
               for e in validate_topic_card(no_venue, current_year=YEAR).errors)
    one_venue = _card()
    one_venue["venues"]["routine"] = one_venue["venues"]["routine"][:1]
    assert validate_topic_card(one_venue, current_year=YEAR).valid
    wet = _card(computational_only=False)
    assert "computational_only must be true" in validate_topic_card(wet).errors
    unverified = _card()
    unverified["decisive_analysis"]["data_access_verified"] = False
    assert "decisive_analysis.data_access_verified must be true" in validate_topic_card(
        unverified
    ).errors


def test_admission_contract_checks_preregistration_hash() -> None:
    entry = {"topic_id": "t", "source_result_id": "s", "card": _card()}
    good = _branch(entry)["admission"]
    assert validate_topic_admission(good).valid
    tampered = json.loads(json.dumps(good))
    tampered["preregistration"]["primary_endpoint"]["stop_rule"] = "never stop"
    assert any("does not match" in e for e in validate_topic_admission(tampered).errors)
    hold = _branch(entry, "hold", reopen_conditions=[])["admission"]
    assert "admission.reopen_conditions is required for hold" in validate_topic_admission(
        hold
    ).errors


# --------------------------------------------------------------------------- scout trigger


def test_open_slot_schedules_a_worker_tier_scout_with_program_inputs(tmp_path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings()

    report = _tick(paths, settings, monkeypatch)

    assert report.errors == []
    scouts = report.program["scouts_scheduled"]
    assert [item["domain"] for item in scouts] == ["ai"]
    task = db.task(scouts[0]["task_id"])
    assert task["task_type"] == "topic_scout"
    assert task["agent_role"] == "researcher" and task["session_mode"] == "fresh"
    assert task["campaign_id"] == "ai-program-scout"
    assert task["runner"] in {"worker_gpt", "worker_claude"}  # routed to the worker tier
    packet = _packet(task)
    labels = {item["label"] for item in packet["read_resources"]}
    assert labels == {"settings.yaml#research_portfolio", "team-rejection-ledger",
                      "reusable-asset-index"}  # no ledger file exists yet
    assert packet["max_cards"] == 3
    # Only the controller schedules scouts: the on_demand workstream is not reseeded.
    again = _tick(paths, settings, monkeypatch)
    assert again.program["scouts_scheduled"] == []
    assert again.program["scout_blocked"] == "scout_in_flight"
    assert db.task_count("ai-program-scout") == 1


def test_scout_not_scheduled_when_full_paused_lead_short_or_too_soon(tmp_path) -> None:
    def setup(name: str, **program):
        paths = _paths(tmp_path / name)
        _install_program(paths)
        db = _db(paths)
        settings = _settings(**program)
        engine._sync_active_projects(db, paths, settings, engine.TickReport())
        return paths, db, settings, open_topic_ledger(paths, settings.program)

    def active_topic(paths, db, settings, ledger, n: int) -> None:
        topic = {"topic_id": f"t{n}", "domain": "ai", "question": f"q{n}",
                 "data_sources": [f"s{n}"], "primary_endpoint": "e"}
        propose_topic(ledger, topic, db=db, decided_by="s")
        admit_topic(ledger, f"t{n}", db=db, settings=settings.program, decided_by="g",
                    admission_task_id="g")
        db.register_campaign(f"c{n}", domain="ai", title="c")
        activate_topic(ledger, f"t{n}", db=db, campaign_id=f"c{n}", decided_by="m")

    paths, db, settings, ledger = setup("full", max_active_topics=1)
    active_topic(paths, db, settings, ledger, 0)
    assert maybe_schedule_scout(db, paths, settings, lead_short=False).reason == "no_free_slot"

    paths, db, settings, ledger = setup("paused", max_ready_unsubmitted=0)
    active_topic(paths, db, settings, ledger, 0)
    mark_topic_in_review(ledger, "t0", db=db, decided_by="r")
    mark_topic_ready(ledger, "t0", db=db, decided_by="r")
    assert maybe_schedule_scout(db, paths, settings, lead_short=False).reason == "admission_paused"

    paths, db, settings, ledger = setup("lead")
    assert maybe_schedule_scout(db, paths, settings, lead_short=True).reason == "lead_quota_short"

    paths, db, settings, ledger = setup("pool", candidate_pool_low_water=1)
    propose_topic(ledger, {"topic_id": "p", "domain": "ai", "question": "q",
                           "data_sources": ["s"], "primary_endpoint": "e"}, db=db, decided_by="s")
    assert maybe_schedule_scout(db, paths, settings, lead_short=False).reason == (
        "candidate_pool_at_low_water"
    )

    paths, db, settings, ledger = setup("interval")
    db.update_meta({LAST_SCOUT_KEY: datetime.now(UTC).isoformat()})
    assert maybe_schedule_scout(db, paths, settings, lead_short=False).reason == (
        "scout_min_interval"
    )
    settings = replace(settings, program=replace(settings.program, scout_min_interval_hours=0))
    assert maybe_schedule_scout(db, paths, settings, lead_short=False).task_id is not None

    paths, db, settings, ledger = setup("norunners")
    settings = replace(settings, runners={})
    assert maybe_schedule_scout(db, paths, settings, lead_short=False).reason == (
        "provider_routing_not_configured"
    )


# --------------------------------------------------------------------------- card intake


def test_invalid_cards_are_rejected_with_their_missing_fields(tmp_path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings()
    no_audience = _card(1, RECEIPT_SHA)
    no_audience.pop("primary_endpoint")
    wet = _card(2, RECEIPT_SHA, computational_only=False)
    unverified = _card(3, RECEIPT_SHA)
    unverified["decisive_analysis"]["data_access_verified"] = False
    unbound = _card(4, "1" * 64)  # receipt not among the scout's artifacts

    _, report = _scout_round(
        paths, db, settings, monkeypatch, [_card(0, RECEIPT_SHA), no_audience, wet, unverified,
                                           unbound],
    )

    assert report.errors == []
    assert len(report.program["cards_registered"]) == 1
    rejected = report.program["rejected_cards"]
    assert len(rejected) == 4
    reasons = [" | ".join(item["errors"]) for item in rejected]
    assert any("primary_endpoint must be an object" in text for text in reasons)
    assert any("computational_only must be true" in text for text in reasons)
    assert any("data_access_verified must be true" in text for text in reasons)
    assert any("not a hash-bound artifact" in text for text in reasons)
    ledger = open_topic_ledger(paths, settings.program).read()
    rejected_topics = [t for t in ledger["topics"] if t["status"] == "rejected"]
    assert all(t["card_errors"] for t in rejected_topics)
    assert {last_rejection_reason(t) for t in rejected_topics} == {"card_invalid"}
    # Each invalid scout card gets its one automatic repair task.
    assert {t["card_repair"]["status"] for t in rejected_topics} == {"scheduled"}


# --------------------------------------------------------------------------- admission gate


def test_admission_goes_to_another_family_lead_and_keeps_independence(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings()
    scout_id, admission, report = _to_admission(
        paths, db, settings, monkeypatch, [_card(0, RECEIPT_SHA)]
    )
    scout_provider = RUNNERS[db.task(scout_id)["runner"]].provider
    assert admission["task_type"] == "portfolio_review"
    assert admission["agent_role"] == "reviewer" and admission["session_mode"] == "fresh"
    assert admission["exclude_provider"] == scout_provider
    assert report.program["admissions_scheduled"][0]["task_id"] == admission["task_id"]
    routed = RUNNERS[db.task(admission["task_id"])["runner"]]
    assert routed.tier == "lead" and routed.provider != scout_provider
    packet = _packet(admission)
    assert packet["program"] is True and len(packet["topic_cards"]) == 1
    assert {item["label"] for item in packet["read_resources"]} >= {
        "topic-ledger", "reusable-asset-index"
    }


def test_no_independent_runner_leaves_topic_proposed_and_records_event(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings(runners=CLAUDE_ONLY)
    _, admission, report = _to_admission(paths, db, settings, monkeypatch,
                                         [_card(0, RECEIPT_SHA)])

    assert db.task(admission["task_id"])["status"] == "queued"
    assert admission["exclude_provider"] == CLAUDE
    waiting = report.program["admissions_waiting"]
    assert waiting and waiting[0]["excluded_provider"] == CLAUDE
    topic_id = waiting[0]["topic_ids"][0]
    ledger = open_topic_ledger(paths, settings.program)
    assert ledger.topic(topic_id)["status"] == "proposed"
    events = db.events(entity_type="topic", entity_id=topic_id)
    assert "topic_admission_waiting" in {event["event_type"] for event in events}
    # Still waiting next tick: never re-routed to the same family.
    later = _tick(paths, settings, monkeypatch)
    assert db.task(admission["task_id"])["status"] == "queued"
    assert admission["task_id"] not in later.launched


def test_end_to_end_slot_scout_admission_campaign_first_task(tmp_path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings()
    _, admission, _ = _to_admission(paths, db, settings, monkeypatch, [_card(0, RECEIPT_SHA)])
    entry = _packet(admission)["topic_cards"][0]
    _complete(db, paths, admission["task_id"],
              extra={"candidate_branches": [_branch(entry)]})

    report = _tick(paths, settings, monkeypatch)

    assert report.errors == []
    assert report.program["admission_decisions"][0]["outcome"] == "admitted"
    ledger = open_topic_ledger(paths, settings.program)
    topic = ledger.topic(entry["topic_id"])
    assert topic["status"] == "active"
    endpoint = entry["card"]["primary_endpoint"]
    assert topic["preregistration_sha256"] == preregistration_sha256(endpoint)
    assert topic["target_tier"] == "routine"
    campaign = db.campaign(topic["campaign_id"])
    assert campaign is not None and campaign["status"] == "active"
    state = json.loads(Path(campaign["workstream_state_path"]).read_text(encoding="utf-8"))
    assert state["topic_id"] == entry["topic_id"]
    assert state["preregistration"]["sha256"] == topic["preregistration_sha256"]
    assert state["target_tier"] == "routine"
    assert [venue["name"] for venue in state["routine_fallback"]] == [
        "Journal of Biomedical Informatics", "Artificial Intelligence in Medicine"
    ]
    assert state["cost_budget"]["gpu_hours"] == 12
    first = db.latest_task(topic["campaign_id"])
    assert first["task_type"] == "candidate_maturation"
    assert first["agent_role"] == "researcher"
    assert first["task_id"] in report.launched or first["status"] == "queued"
    # Replaying the gate's handoff and the materialization (crash recovery)
    # books nothing twice.
    done = db.task(admission["task_id"])
    replay = spawn_candidate_workstreams(
        db, paths, settings, db.campaign("ai-program-admission"), done,
        json.loads(Path(done["result_path"]).read_text(encoding="utf-8")),
        result_path=Path(done["result_path"]),
    )
    assert replay.task_ids == ()
    assert replay.decisions[0]["outcome"] == "admitted"
    again = materialize_waiting_topics(db, paths, settings)
    assert again.campaign_ids == ()
    assert len([h for h in ledger.topic(entry["topic_id"])["history"]
                if h["to"] == "admitted"]) == 1
    assert db.task_count(topic["campaign_id"]) == 1


def test_gate_rejects_unconfirmed_data_and_admits_nothing_without_error(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings()
    _, admission, _ = _to_admission(paths, db, settings, monkeypatch,
                                    [_card(0, RECEIPT_SHA), _card(1, RECEIPT_SHA)])
    entries = _packet(admission)["topic_cards"]
    branches = [
        _branch(entries[0], data_access_confirmed=False),
        _branch(entries[1], "reject"),
    ]
    _complete(db, paths, admission["task_id"], extra={"candidate_branches": branches})
    before = slot_status(open_topic_ledger(paths, settings.program).read(), settings.program)

    report = _tick(paths, settings, monkeypatch)

    assert report.errors == []
    outcomes = {item["topic_id"]: item for item in report.program["admission_decisions"]}
    assert outcomes[entries[0]["topic_id"]]["reason"] == "data_access_not_confirmed"
    assert outcomes[entries[1]["topic_id"]]["outcome"] == "rejected"
    status = slot_status(open_topic_ledger(paths, settings.program).read(), settings.program)
    assert status.free_slots == before.free_slots == settings.program.max_active_topics
    assert report.program["materialized"] == []
    assert not [c for c in db.campaigns() if "candidate" in str(c["campaign_id"])]


def test_hold_and_reject_are_not_materialized_and_return_only_via_reopens(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    project_path = _install_program(paths)
    db = _db(paths)
    settings = _settings()
    cards = [_card(0, RECEIPT_SHA), _card(1, RECEIPT_SHA)]
    scout_id, admission, _ = _to_admission(paths, db, settings, monkeypatch, cards)
    entries = _packet(admission)["topic_cards"]
    _complete(db, paths, admission["task_id"], extra={"candidate_branches": [
        _branch(entries[0], "reject"), _branch(entries[1], "hold"),
    ]})
    _tick(paths, settings, monkeypatch)
    ledger = open_topic_ledger(paths, settings.program)
    rejected, held = (ledger.topic(e["topic_id"]) for e in entries)
    assert rejected["status"] == held["status"] == "rejected"
    assert last_rejection_reason(rejected) == "admission_rejected"
    assert last_rejection_reason(held) == "admission_hold"
    assert held["reopen_conditions"][0]["type"] == "new_data_source"
    assert rejected["campaign_id"] is None and held["campaign_id"] is None

    project = load_project(project_path)
    digests = {RECEIPT_SHA}
    # Resubmitting the identical card is a no-op on the judged topic ...
    same = intake_card(db, paths, settings, project, _card(1, RECEIPT_SHA),
                       decided_by="scout-2", provider=GPT, source_task_id="scout-2",
                       receipt_digests={RECEIPT_SHA})
    assert same["topic_id"] == held["topic_id"] and same["status"] == "rejected"
    # ... and a reworded card with the same fingerprint is rejected as a duplicate.
    reworded = _card(1, RECEIPT_SHA)
    reworded["question"] = reworded["question"].upper() + "  "
    reworded["cost_estimate"]["basis"] = "A different estimate wording."
    duplicate = intake_card(db, paths, settings, project, reworded,
                            decided_by="scout-2", provider=GPT, source_task_id="scout-2",
                            receipt_digests=digests)
    assert duplicate["status"] == "rejected" and duplicate["reason"] == "duplicate_fingerprint"
    # A reopening card citing the declared condition is accepted.
    reopening = intake_card(
        db, paths, settings, project,
        _card(1, RECEIPT_SHA, reopens=held["topic_id"], reopen_basis={
            "type": "new_data_source", "description": "The 2026 admission year is out."}),
        decided_by="scout-3", provider=GPT, source_task_id="scout-3", receipt_digests=digests,
    )
    assert reopening["status"] == "proposed"
    assert ledger.topic(reopening["topic_id"])["supersedes"] == held["topic_id"]


def test_admitted_topics_wait_for_a_slot_and_materialize_in_admission_order(
    tmp_path, monkeypatch
) -> None:
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings(max_active_topics=2)
    ledger = open_topic_ledger(paths, settings.program)
    # One running (grandfathered) topic holds a slot.
    propose_topic(ledger, {"topic_id": "old", "domain": "ai", "question": "old",
                           "data_sources": ["s"], "primary_endpoint": "e"}, db=db,
                  decided_by="backfill")
    admit_topic(ledger, "old", db=db, settings=settings.program, decided_by="b",
                admission_task_id="b")
    db.register_campaign("old-campaign", domain="ai", title="old")
    activate_topic(ledger, "old", db=db, campaign_id="old-campaign", decided_by="b")

    _, admission, _ = _to_admission(paths, db, settings, monkeypatch,
                                    [_card(0, RECEIPT_SHA), _card(1, RECEIPT_SHA)])
    entries = _packet(admission)["topic_cards"]
    # The gate lists the second card first: admission order follows its decisions.
    _complete(db, paths, admission["task_id"], extra={"candidate_branches": [
        _branch(entries[1]), _branch(entries[0]),
    ]})
    report = _tick(paths, settings, monkeypatch)

    first, second = entries[1]["topic_id"], entries[0]["topic_id"]
    assert ledger.topic(first)["status"] == "active"
    assert ledger.topic(second)["status"] == "admitted"
    assert report.program["waiting_admitted"] == [second]
    assert report.program["scouts_scheduled"] == []  # no free slot left

    freeze_topic(ledger, "old", db=db, reason_class="overdue", evidence=EVIDENCE,
                 decided_by="judge")
    report = engine.TickReport()
    report.program = {}
    run_program_pipeline(db, paths, settings, report)
    assert ledger.topic(second)["status"] == "active"
    assert report.program["materialized"] == [ledger.topic(second)["campaign_id"]]
    assert report.program["waiting_admitted"] == []


# --------------------------------------------------------------------------- structure


def _manual_lab(paths: WorkspacePaths) -> None:
    lab = paths.code / "labs" / "test"
    (lab / "skills" / "t").mkdir(parents=True)
    (lab / "skills" / "t" / "SKILL.md").write_text("---\nname: t\ndescription: t\n---\n")
    (lab / "protocols").mkdir()
    (lab / "protocols" / "ok.py").write_text(
        "import json\nprint(json.dumps({'valid': True, 'errors': []}))\n"
    )
    atomic_write_json(lab / "lab.json", {
        "schema_version": "openlabs.lab.v1", "lab_id": "test", "domain": "test-domain",
        "runner": {"command": ["{python}", "runner.py"]},
        "skills": [{"skill_id": "t", "path": "skills/t/SKILL.md"}],
        "protocols": [{"protocol_id": "t", "primary_skill": "t",
                       "validator": {"command": ["{python}", "protocols/ok.py"]}}],
    })
    root = paths.data / "workspaces" / "test-domain"
    atomic_write_json(root / "manual" / "state.json", {"status": "active"})
    atomic_write_json(root / "projects" / "manual" / "project.json", {
        "schema_version": "openlabs.project.v1", "project_id": "manual",
        "domain": "test-domain", "status": "active", "objective": "Manual research.",
        "protocol": {"id": "t", "primary_skill": "t"},
        "workstreams": [{"workstream_id": "manual-stream",
                         "state_path": "../../manual/state.json"}],
    })


def test_enforce_admission_blocks_unadmitted_manual_research(tmp_path) -> None:
    paths = _paths(tmp_path, code=tmp_path / "openlabs")
    _manual_lab(paths)
    db = _db(paths)
    blocked = engine.tick(paths, replace(_settings(enforce_admission=True), launch_jobs=False))
    assert {"campaign_id": "manual-stream", "reason": "topic_not_admitted"}.items() <= (
        blocked.production_blocked[0].items()
    )
    assert db.campaign("manual-stream") is None

    # Default (enforce_admission = false) keeps the old behaviour.
    allowed = engine.tick(paths, replace(_settings(), launch_jobs=False))
    assert "manual-stream" in allowed.production_synced
    assert db.campaign("manual-stream") is not None


def test_enforce_admission_accepts_a_workstream_linked_to_an_admitted_topic(tmp_path) -> None:
    paths = _paths(tmp_path, code=tmp_path / "openlabs")
    _manual_lab(paths)
    db = _db(paths)
    settings = replace(_settings(enforce_admission=True), launch_jobs=False)
    ledger = open_topic_ledger(paths, settings.program)
    propose_topic(ledger, {"topic_id": "m", "domain": "test-domain", "question": "q",
                           "data_sources": ["s"], "primary_endpoint": "e"}, db=db,
                  decided_by="gate")
    admit_topic(ledger, "m", db=db, settings=settings.program, decided_by="g",
                admission_task_id="g")
    db.register_campaign("manual-stream", domain="test-domain", title="m")
    activate_topic(ledger, "m", db=db, campaign_id="manual-stream", decided_by="g")
    report = engine.tick(paths, settings)
    assert "manual-stream" in report.production_synced


def test_program_protocol_rejects_static_research_and_missing_preregistration(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "research_program_protocol",
        CODE_ROOT / "packages" / "research-core" / "research_program_protocol.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    paths = _paths(tmp_path)
    project_path = _install_program(paths)
    root = project_path.parent
    assert module.validate(project_path, root / "scout_state.json", "discovery") == []
    assert module.validate(project_path, root / "admission_state.json", "commit") == []
    research = {"schema_version": "openlabs.research_program_state.v1",
                "project_id": "ai-research-program", "workstream_id": "x",
                "program_role": "research", "status": "active"}
    atomic_write_json(root / "scout_state.json", research)
    errors = module.validate(project_path, root / "scout_state.json", "discovery")
    assert any("only through the admission gate" in e for e in errors)
    assert any("preregistration" in e for e in errors)


def test_backfill_is_dry_run_by_default_and_idempotent(tmp_path) -> None:
    paths = _paths(tmp_path)
    db = _db(paths)
    settings = _settings()
    db.register_campaign("running-study", domain="ai", title="Running study")
    db.register_campaign("review-lane", domain="ai", title="Reviewer")
    db.configure_project_campaign(
        "review-lane", project_config_path="", workstream_state_path="", protocol_id="",
        primary_skill="", execution_policy={}, project_id="p",
        workstream_policy={"default_agent_role": "reviewer"},
    )
    dry = backfill_grandfathered(db, paths, settings)
    assert dry["dry_run"] is True
    assert [item["campaign_id"] for item in dry["planned"]] == ["running-study"]
    assert not (paths.data / "registry" / "topic-ledger.json").exists()

    written = backfill_grandfathered(db, paths, settings, write=True)
    ledger = open_topic_ledger(paths, settings.program)
    topic = ledger.topic(written["registered"][0])
    assert topic["status"] == "active" and topic["campaign_id"] == "running-study"
    assert topic["admission"] == "grandfathered"
    again = backfill_grandfathered(db, paths, settings, write=True)
    assert again["registered"] == []
    assert {"campaign_id": "running-study", "reason": "already_in_ledger"} in again["skipped"]


def test_cli_exposes_program_backfill_and_submit_card() -> None:
    from openlabs.__main__ import _parser

    args = _parser().parse_args(["program", "backfill"])
    assert args.command == "program" and args.program_command == "backfill" and not args.write
    args = _parser().parse_args(["program", "submit-card", "--project", "p.json", "--card",
                                 "c.json"])
    assert args.program_command == "submit-card"


def test_disabled_program_leaves_program_projects_idle(tmp_path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = replace(_settings(), program=ProgramSettings())
    report = _tick(paths, settings, monkeypatch)
    assert report.program == {}
    assert not (paths.data / "registry" / "topic-ledger.json").exists()
    with db.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM tasks WHERE task_type='topic_scout'"
        ).fetchone()[0] == 0
    assert {"campaign_id": "ai-program-admission", "reason": "program_disabled"} in (
        report.production_blocked
    )


@pytest.mark.parametrize("lab", ["ai", "biomed", "materials", "math", "physics", "quant"])
def test_every_lab_registers_the_program_protocol_and_skills(lab: str) -> None:
    from openlabs.labs import load_lab

    manifest = load_lab(CODE_ROOT / "labs" / lab / "lab.json")
    protocol = manifest.protocol("research-program")
    assert protocol is not None
    assert {"openlabs-empirical-topic-scout", "openlabs-topic-admission"} <= set(
        protocol.runtime_skills
    )
    for skill in protocol.runtime_skills:
        assert manifest.skill_path(skill) is not None and manifest.skill_path(skill).is_file()


def test_lead_shortage_pauses_the_admission_gate(tmp_path) -> None:
    from openlabs import budget as budget_control

    paths = _paths(tmp_path)
    db = _db(paths)
    settings = _settings()
    router = budget_control.QuotaRouter.build(db, settings)
    router.lead_short = True
    task = {"task_id": "gate", "task_type": "portfolio_review", "routing_reason": "topic_admission",
            "agent_role": "reviewer", "runner": "frontier"}
    assert router.route(task, {}) is None
    assert router.deferred["gate"]["reason"] == "lead_quota_short"
    ordinary = {**task, "task_id": "review", "routing_reason": "new_project_results_review"}
    assert router.route(ordinary, {}) is not None or router.deferred["review"]["reason"] != (
        "lead_quota_short"
    )


# --------------------------------------------------------------------------- compute locations


def _math_card(n: int, receipt_sha: str = RECEIPT_SHA) -> dict:
    card = _card(n, receipt_sha)
    card["cost_estimate"]["gpu_hours"] = 0
    card["cost_estimate"]["compute_plan"] = {"locations": ["container_cpu", "wsl_math"]}
    return card


def test_topic_card_needs_a_compute_plan_with_sizes_per_location() -> None:
    card = _card()
    card["cost_estimate"].pop("compute_plan")
    errors = validate_topic_card(card, current_year=YEAR).errors
    assert any(e.startswith("cost_estimate.compute_plan is missing") for e in errors)
    card["cost_estimate"]["compute_plan"] = {"locations": ["laptop"]}
    assert any("compute_plan.locations must be" in e
               for e in validate_topic_card(card, current_year=YEAR).errors)
    card["cost_estimate"]["compute_plan"] = {"locations": ["container_cpu", "ailab"]}
    errors = validate_topic_card(card, current_year=YEAR).errors
    assert "cost_estimate.compute_plan.ailab needs cpus, memory_mib and hours" in errors
    assert "cost_estimate.gpu_hours > 0 needs container_gpu in compute_plan.locations" in errors
    card["cost_estimate"]["gpu_hours"] = 0
    card["cost_estimate"]["compute_plan"]["ailab"] = {"cpus": 16, "memory_mib": 8192, "hours": 3}
    assert any("ailab.cpus must be 1-8" in e
               for e in validate_topic_card(card, current_year=YEAR).errors)
    card["cost_estimate"]["compute_plan"]["ailab"]["cpus"] = 8
    assert validate_topic_card(card, current_year=YEAR).valid
    assert validate_topic_card(_math_card(0), current_year=YEAR).valid


def test_container_instance_rejects_wsl_math_cards_at_registration(tmp_path, monkeypatch):
    import openlabs.program_flow as program_flow

    marker = tmp_path / "dockerenv"
    marker.write_text("", encoding="utf-8")
    monkeypatch.setattr(program_flow, "CONTAINER_MARKER", marker)
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings()

    _, report = _scout_round(paths, db, settings, monkeypatch,
                             [_card(0, RECEIPT_SHA), _math_card(1)])

    assert len(report.program["cards_registered"]) == 1
    [rejected] = report.program["rejected_cards"]
    assert any(error.startswith("compute_location_unavailable:wsl_math")
               and "WSL host" in error for error in rejected["errors"])


def test_container_instance_refuses_to_admit_a_wsl_math_topic(tmp_path, monkeypatch):
    import openlabs.program_flow as program_flow

    marker = tmp_path / "dockerenv"
    monkeypatch.setattr(program_flow, "CONTAINER_MARKER", marker)  # absent: not a container
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings()
    _, admission, report = _to_admission(paths, db, settings, monkeypatch, [_math_card(0)])
    assert len(report.program["cards_registered"]) == 1
    [entry] = _packet(admission)["topic_cards"]
    _complete(db, paths, admission["task_id"], extra={"candidate_branches": [_branch(entry)]})
    marker.write_text("", encoding="utf-8")  # the admission runs in the container instance

    report = _tick(paths, settings, monkeypatch)

    [decision] = report.program["admission_decisions"]
    assert decision["outcome"] == "rejected"
    assert decision["reason"].startswith("compute_location_unavailable:wsl_math")
    topic = open_topic_ledger(paths, settings.program).read()["topics"][0]
    assert topic["status"] == "rejected"
    assert report.program["materialized"] == []
    # An explicit [program].compute_locations without wsl_math refuses it anywhere.
    marker.unlink()
    narrowed = replace(settings, program=replace(
        settings.program, compute_locations=("container_cpu", "container_gpu", "ailab")))
    assert program_flow.compute_location_problem(narrowed, _math_card(1)).startswith(
        "compute_location_unavailable:wsl_math")
    assert program_flow.compute_location_problem(settings, _math_card(1)) is None


# --------------------------------------------------------------------------- paused projects


def _set_project_status(project_path: Path, status: str) -> None:
    payload = json.loads(project_path.read_text(encoding="utf-8"))
    payload["status"] = status
    atomic_write_json(project_path, payload)


def test_paused_program_project_parks_its_topics_and_resumes(tmp_path, monkeypatch) -> None:
    """Pausing a program project frees its slots for the others and holds its admitted topics."""

    paths = _paths(tmp_path)
    project_path = _install_program(paths)
    db = _db(paths)
    settings = _settings(max_active_topics=2)
    ledger = open_topic_ledger(paths, settings.program)
    # Two running topics of another, paused program project fill both slots.
    other = paths.data / "workspaces" / "ai" / "projects" / "other-program"
    other.mkdir(parents=True)
    payload = json.loads(project_path.read_text(encoding="utf-8"))
    payload.update({"project_id": "other-program", "status": "paused"})
    for workstream in payload["workstreams"]:
        workstream["workstream_id"] = "other-" + workstream["workstream_id"]
        shutil.copyfile(TEMPLATE / workstream["state_path"], other / workstream["state_path"])
    atomic_write_json(other / "project.json", payload)
    for name in ("parked-a", "parked-b"):
        propose_topic(ledger, {"topic_id": name, "domain": "ai", "question": name,
                               "data_sources": ["s"], "primary_endpoint": "e"}, db=db,
                      decided_by="backfill", metadata={"program_project_id": "other-program"})
        admit_topic(ledger, name, db=db, settings=settings.program, decided_by="b",
                    admission_task_id="b")
        db.register_campaign(f"{name}-campaign", domain="ai", title=name)
        activate_topic(ledger, name, db=db, campaign_id=f"{name}-campaign", decided_by="b")

    assert parked_program_projects(paths) == frozenset({"other-program"})
    document = ledger.read()
    assert slot_status(document, settings.program).free_slots == 0
    parked = slot_status(document, settings.program, parked_program_projects(paths))
    assert (parked.free_slots, parked.parked) == (2, 2)

    # The active project still admits and materializes into the freed slots; the third
    # admitted topic waits for a slot.
    _, admission, _ = _to_admission(paths, db, settings, monkeypatch,
                                    [_card(n, RECEIPT_SHA) for n in range(3)])
    entries = _packet(admission)["topic_cards"]
    _complete(db, paths, admission["task_id"],
              extra={"candidate_branches": [_branch(entry) for entry in entries]})
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == []
    first, second, third = (entry["topic_id"] for entry in entries)
    assert [ledger.topic(t)["status"] for t in (first, second, third)] == [
        "active", "active", "admitted"]
    assert report.program["parked_topics"] == 2

    # Paused, the project's admitted topic is not materialized even when a slot opens.
    _set_project_status(project_path, "paused")
    freeze_topic(ledger, first, db=db, reason_class="overdue", evidence=EVIDENCE,
                 decided_by="judge")
    assert materialize_waiting_topics(db, paths, settings).campaign_ids == ()
    assert ledger.topic(third)["status"] == "admitted"

    # Active again: it takes the slot.
    _set_project_status(project_path, "active")
    spawned = materialize_waiting_topics(db, paths, settings)
    assert spawned.campaign_ids == (ledger.topic(third)["campaign_id"],)
    assert ledger.topic(third)["status"] == "active"
