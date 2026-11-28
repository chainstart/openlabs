"""Research-program front end: topic scout, proposal intake, independent review, materialization."""

from __future__ import annotations

import hashlib
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
    SupplySettings,
    WorkspacePaths,
)
from openlabs.contracts import (
    RECEIPT_SCHEMA,
    RESULT_SCHEMA,
    TOPIC_PROPOSAL_SCHEMA,
    atomic_write_json,
    sha256_file,
    validate_topic_proposal,
    validate_topic_review,
)
from openlabs.db import FactoryDB
from openlabs.portfolio import spawn_candidate_workstreams
from openlabs.program import (
    REJECTION_BUDGET_EXCEEDED,
    REJECTION_DUPLICATE_TOPIC,
    REJECTION_PROPOSAL_INVALID,
    REJECTION_REVIEW_NO_GO,
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
    intake_proposal,
    materialize_waiting_topics,
    maybe_schedule_scout,
    run_program_pipeline,
)
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
RECEIPT = b'{"source": "physionet", "rows": 1024}\n'
RECEIPT_SHA = hashlib.sha256(RECEIPT).hexdigest()

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
    # Default grade_before_writing=False for generic flow/owner/autonomy tests;
    # test_nc_grading.py and test_supply_flow.py test grade_before_writing=True explicitly.
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
        program=ProgramSettings(
            enabled=True,
            **{"grade_before_writing": False, **program},
        ),
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


def _brief(n: int) -> str:
    return (
        f"## 1. Question & Claim\nDoes temporal retrieval beat dense baselines on year {n}?\n\n"
        "## 2. Why It Matters\nEvaluates real deployment drift on multi-year clinical records.\n\n"
        "## 3. Closest Prior Work & Delta\nPrior studies used random splits; we test strict temporal splits.\n\n"
        "## 4. Data & Compute\nPublic Zenodo cohort (<2 GB) on container CPU (~4 agent hours).\n\n"
        "## 5. First Milestone (Kill Test)\nFetch subset, verify timestamps, run baseline vs retrieval.\n\n"
        "## 6. Kill Criteria & Risks\nFreeze if timestamp leakage or baseline gap < 0.01 AUROC.\n"
    )


_SAMPLE_QUESTIONS = (
    "Does temporal retrieval keep its advantage on multi-year clinical notes?",
    "Can sparse attention calibrate arrhythmia alerts across hospital cohorts?",
    "Do graph neural surrogates preserve power-grid stability under line outages?",
    "Does photometric phase folding separate contact binaries in TESS sectors?",
    "Can causal pruning reduce false alarms in bearing vibration diagnostics?",
    "Does conformal prediction stabilize solar flare lead-time intervals?",
)


def _proposal(n: int = 0, **override) -> dict:
    question = (
        _SAMPLE_QUESTIONS[n]
        if 0 <= n < len(_SAMPLE_QUESTIONS)
        else f"Question {n}: unique benchmark evaluation for cohort alpha-{n} beta-{n * 7}?"
    )
    proposal = {
        "schema_version": TOPIC_PROPOSAL_SCHEMA,
        "question": question,
        "brief": _brief(n),
        "data_sources": [
            {"id_or_url": f"https://zenodo.org/records/example-{n}", "access": "direct"}
        ],
        "compute_estimate": {
            "locations": ["container_cpu"],
            "data_gb": 2.0,
            "agent_hours": 4.0,
        },
    }
    proposal.update(override)
    return proposal


def _card(n: int = 0, receipt_sha: str = "0" * 64, **override) -> dict:
    del receipt_sha
    return _proposal(n, **override)


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
        artifacts.append({
            "artifact_id": f"receipt-{index}", "kind": "data_access_receipt",
            "uri": path.resolve().as_uri(), "sha256": sha256_file(path),
        })
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


def _scout_round(paths, db, settings, monkeypatch, proposals) -> tuple[str, engine.TickReport]:
    """Tick to schedule+claim a scout, deliver ``proposals``, tick to register them."""

    first = _tick(paths, settings, monkeypatch)
    scouts = first.program["scouts_scheduled"]
    assert len(scouts) == 1, first.program
    scout_id = scouts[0]["task_id"]
    assert scout_id in first.launched
    _complete(db, paths, scout_id, extra={"topic_proposals": proposals})
    return scout_id, _tick(paths, settings, monkeypatch)


def _admission_task(db: FactoryDB) -> dict:
    with db.connect() as connection:
        row = connection.execute(
            "SELECT * FROM tasks WHERE routing_reason='topic_admission' "
            "ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    return dict(row)


def _review(entry: dict, verdict: str = "go", **override) -> dict:
    item = {
        "topic_id": entry["topic_id"],
        "verdict": verdict,
        "rationale": (
            "The question addresses an under-tested temporal generalization gap with clear "
            "closest prior work and a fast CPU kill test on open data."
        ),
        "likely_band": "zone_1",
    }
    item.update(override)
    return item


def _packet(task: dict) -> dict:
    return json.loads(Path(str(task["input_path"])).read_text(encoding="utf-8"))


def _to_admission(paths, db, settings, monkeypatch, proposals):
    """Run scout + registration; return (scout id, admission task after claim, report)."""

    scout_id, report = _scout_round(paths, db, settings, monkeypatch, proposals)
    admission = _admission_task(db)
    return scout_id, admission, report


def _set_project_status(project_path: Path, status: str) -> None:
    payload = json.loads(project_path.read_text(encoding="utf-8"))
    payload["status"] = status
    atomic_write_json(project_path, payload)


# --------------------------------------------------------------------------- contracts


def test_proposal_and_review_contracts_check_minimal_fields() -> None:
    assert validate_topic_proposal(_proposal()).valid
    missing = _proposal()
    missing.pop("brief")
    missing.pop("compute_estimate")
    check = validate_topic_proposal(missing)
    assert not check.valid
    assert any("brief" in e for e in check.errors)
    assert any("compute_estimate" in e for e in check.errors)

    assert validate_topic_review(_review({"topic_id": "t1"})).valid
    bad = validate_topic_review({"topic_id": "t1", "verdict": "maybe", "rationale": ""})
    assert not bad.valid
    assert any("verdict" in e for e in bad.errors)
    assert any("rationale" in e for e in bad.errors)


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
    assert task["runner"] in {"worker_gpt", "worker_claude"}
    packet = _packet(task)
    labels = {item["label"] for item in packet["read_resources"]}
    assert labels == {"settings.yaml#research_portfolio", "team-rejection-ledger",
                      "reusable-asset-index"}
    assert packet["max_proposals"] == settings.program.supply.candidate_pool_size
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

    def active_topic(db, settings, ledger, n: int) -> None:
        topic = {"topic_id": f"t{n}", "domain": "ai", "question": f"q{n}", "data_sources": [f"s{n}"]}
        propose_topic(ledger, topic, db=db, decided_by="s")
        admit_topic(ledger, f"t{n}", db=db, settings=settings.program, decided_by="g",
                    admission_task_id="g")
        db.register_campaign(f"c{n}", domain="ai", title="c")
        activate_topic(ledger, f"t{n}", db=db, campaign_id=f"c{n}", decided_by="m")

    paths, db, settings, ledger = setup("full", max_active_topics=1)
    active_topic(db, settings, ledger, 0)
    assert maybe_schedule_scout(db, paths, settings, lead_short=False).reason == "no_free_slot"

    paths, db, settings, ledger = setup("paused", max_ready_unsubmitted=0)
    active_topic(db, settings, ledger, 0)
    mark_topic_in_review(ledger, "t0", db=db, decided_by="r")
    mark_topic_ready(ledger, "t0", db=db, decided_by="r")
    assert maybe_schedule_scout(db, paths, settings, lead_short=False).reason == "admission_paused"

    paths, db, settings, ledger = setup("lead")
    assert maybe_schedule_scout(db, paths, settings, lead_short=True).reason == "lead_quota_short"

    paths, db, settings, ledger = setup("pool", supply=SupplySettings(candidate_pool_size=1))
    propose_topic(ledger, {"topic_id": "p", "domain": "ai", "question": "q",
                           "data_sources": ["s"]}, db=db, decided_by="s")
    assert maybe_schedule_scout(db, paths, settings, lead_short=False).reason == (
        "candidate_pool_at_low_water"
    )

    paths, db, settings, ledger = setup("interval")
    db.update_meta({LAST_SCOUT_KEY: datetime.now(UTC).isoformat()})
    assert maybe_schedule_scout(db, paths, settings, lead_short=False).reason == (
        "scout_min_interval"
    )
    settings = replace(
        settings,
        program=replace(settings.program, supply=replace(settings.program.supply, scout_min_interval_hours=0)),
    )
    assert maybe_schedule_scout(db, paths, settings, lead_short=False).task_id is not None

    paths, db, settings, ledger = setup("norunners")
    settings = replace(settings, runners={})
    assert maybe_schedule_scout(db, paths, settings, lead_short=False).reason == (
        "provider_routing_not_configured"
    )


# --------------------------------------------------------------------------- intake & review


def test_invalid_proposals_are_rejected_directly_without_repair(tmp_path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings()
    no_brief = _proposal(1)
    no_brief.pop("brief")
    bad_access = _proposal(2, data_sources=[{"id_or_url": "https://x.org/d", "access": "paid"}])

    _, report = _scout_round(paths, db, settings, monkeypatch, [_proposal(0), no_brief, bad_access])

    assert report.errors == []
    assert len(report.program["cards_registered"]) == 1
    rejected = report.program["rejected_cards"]
    assert len(rejected) == 2
    assert {item["reason"] for item in rejected} == {REJECTION_PROPOSAL_INVALID}
    ledger = open_topic_ledger(paths, settings.program).read()
    rejected_topics = [t for t in ledger["topics"] if t["status"] == "rejected"]
    assert {last_rejection_reason(t) for t in rejected_topics} == {REJECTION_PROPOSAL_INVALID}
    assert all(not t.get("card_repair") for t in rejected_topics)


def test_review_goes_to_another_family_and_keeps_independence(tmp_path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings()
    scout_id, admission, report = _to_admission(paths, db, settings, monkeypatch, [_proposal(0)])
    scout_provider = RUNNERS[db.task(scout_id)["runner"]].provider
    assert admission["task_type"] == "portfolio_review"
    assert admission["agent_role"] == "reviewer" and admission["session_mode"] == "fresh"
    assert admission["exclude_provider"] == scout_provider
    assert report.program["admissions_scheduled"][0]["task_id"] == admission["task_id"]
    routed = RUNNERS[db.task(admission["task_id"])["runner"]]
    assert routed.tier == "worker" and routed.provider != scout_provider
    packet = _packet(admission)
    assert packet["program"] is True and len(packet["topic_proposals"]) == 1


def test_no_independent_runner_leaves_topic_proposed_and_records_event(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings(runners={"lead_claude": RUNNERS["lead_claude"]})
    _, admission, report = _to_admission(paths, db, settings, monkeypatch, [_proposal(0)])

    assert db.task(admission["task_id"])["status"] == "queued"
    assert admission["exclude_provider"] == CLAUDE
    waiting = report.program["admissions_waiting"]
    assert waiting and waiting[0]["excluded_provider"] == CLAUDE
    topic_id = waiting[0]["topic_ids"][0]
    assert open_topic_ledger(paths, settings.program).topic(topic_id)["status"] == "proposed"
    events = db.events(entity_type="topic", entity_id=topic_id)
    assert "topic_admission_waiting" in {event["event_type"] for event in events}
    later = _tick(paths, settings, monkeypatch)
    assert admission["task_id"] not in later.launched


def test_single_family_review_goes_to_another_model_of_it(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings(runners=CLAUDE_ONLY)
    _, admission, _ = _to_admission(paths, db, settings, monkeypatch, [_proposal(0)])
    assert admission["exclude_provider"] == CLAUDE
    producer = _packet(admission)["producer_model"]
    _tick(paths, settings, monkeypatch)
    routed = [e["payload"] for e in db.events() if e["event_type"] == "task_routed"
              and e["entity_id"] == admission["task_id"]]
    assert routed and routed[0]["independence"] == "same_family_different_model"
    assert routed[0]["model"] != producer and routed[0]["producer_model"] == producer


def test_end_to_end_slot_scout_review_campaign_and_idempotent_replay(tmp_path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings()
    _, admission, _ = _to_admission(paths, db, settings, monkeypatch, [_proposal(0)])
    entry = _packet(admission)["topic_proposals"][0]
    _complete(db, paths, admission["task_id"], extra={"reviews": [_review(entry, "go")]})

    report = _tick(paths, settings, monkeypatch)

    assert report.errors == []
    assert report.program["admission_decisions"][0]["outcome"] == "admitted"
    ledger = open_topic_ledger(paths, settings.program)
    topic = ledger.topic(entry["topic_id"])
    assert topic["status"] == "active"
    assert topic["preregistration_sha256"] is None
    campaign = db.campaign(topic["campaign_id"])
    assert campaign is not None and campaign["status"] == "active"
    state = json.loads(Path(campaign["workstream_state_path"]).read_text(encoding="utf-8"))
    assert state["topic_id"] == entry["topic_id"]
    assert state["milestone"] == "kill_test"
    assert "## 5. First Milestone (Kill Test)" in state["brief"]
    assert state["compute_estimate"]["data_gb"] == 2.0
    assert state["likely_band"] == "zone_1"
    first = db.latest_task(topic["campaign_id"])
    assert first["task_type"] == "candidate_maturation"
    # Replay is idempotent.
    done = db.task(admission["task_id"])
    replay = spawn_candidate_workstreams(
        db, paths, settings, db.campaign("ai-program-admission"), done,
        json.loads(Path(done["result_path"]).read_text(encoding="utf-8")),
        result_path=Path(done["result_path"]),
    )
    assert replay.task_ids == ()
    assert replay.decisions[0]["outcome"] == "admitted"
    assert materialize_waiting_topics(db, paths, settings).campaign_ids == ()
    assert len([h for h in ledger.topic(entry["topic_id"])["history"]
                if h["to"] == "admitted"]) == 1
    assert db.task_count(topic["campaign_id"]) == 1


def test_no_go_rejects_and_returns_only_via_reopens(tmp_path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    project_path = _install_program(paths)
    db = _db(paths)
    settings = _settings()
    _, admission, _ = _to_admission(paths, db, settings, monkeypatch, [_proposal(0)])
    entry = _packet(admission)["topic_proposals"][0]
    _complete(db, paths, admission["task_id"], extra={"reviews": [_review(entry, "no_go")]})
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == []
    ledger = open_topic_ledger(paths, settings.program)
    rejected = ledger.topic(entry["topic_id"])
    assert rejected["status"] == "rejected"
    assert last_rejection_reason(rejected) == REJECTION_REVIEW_NO_GO
    assert rejected["campaign_id"] is None

    project = load_project(project_path)
    # Identical resubmission returns the already-rejected topic idempotently.
    same = intake_proposal(db, paths, settings, project, _proposal(0),
                           decided_by="scout-2", provider=GPT, source_task_id="scout-2")
    assert same["topic_id"] == rejected["topic_id"] and same["status"] == "rejected"
    # A slightly reworded duplicate without reopens is rejected as duplicate_topic.
    reworded = _proposal(0, brief=_brief(0) + "\nExtra note.\n")
    reworded["question"] = reworded["question"].upper() + "  "
    duplicate = intake_proposal(db, paths, settings, project, reworded,
                                decided_by="scout-2", provider=GPT, source_task_id="scout-2")
    assert duplicate["status"] == "rejected" and duplicate["reason"] == REJECTION_DUPLICATE_TOPIC
    # Reopening a judged rejection succeeds and records supersedes.
    reopening = intake_proposal(
        db, paths, settings, project,
        _proposal(0, brief=_brief(0) + "\nNew cohort released.\n", reopens=rejected["topic_id"]),
        decided_by="scout-3", provider=GPT, source_task_id="scout-3",
    )
    assert reopening["status"] == "proposed"
    assert ledger.topic(reopening["topic_id"])["supersedes"] == rejected["topic_id"]


def test_admitted_topics_wait_for_a_slot_and_materialize_in_review_order(
    tmp_path, monkeypatch
) -> None:
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings(max_active_topics=2)
    ledger = open_topic_ledger(paths, settings.program)
    propose_topic(ledger, {"topic_id": "old", "domain": "ai", "question": "old",
                           "data_sources": ["s"]}, db=db, decided_by="backfill")
    admit_topic(ledger, "old", db=db, settings=settings.program, decided_by="b",
                admission_task_id="b")
    db.register_campaign("old-campaign", domain="ai", title="old")
    activate_topic(ledger, "old", db=db, campaign_id="old-campaign", decided_by="b")

    _, admission, _ = _to_admission(
        paths, db, settings, monkeypatch,
        [_proposal(0, question="Does sparse attention improve long EEG decoding?"),
         _proposal(1, question="Can causal graph pruning reduce hospital readmission drift?")],
    )
    entries = _packet(admission)["topic_proposals"]
    _complete(db, paths, admission["task_id"],
              extra={"reviews": [_review(entries[1]), _review(entries[0])]})
    report = _tick(paths, settings, monkeypatch)

    first, second = entries[1]["topic_id"], entries[0]["topic_id"]
    assert ledger.topic(first)["status"] == "active"
    assert ledger.topic(second)["status"] == "admitted"
    assert report.program["waiting_admitted"] == [second]
    assert report.program["scouts_scheduled"] == []

    freeze_topic(ledger, "old", db=db, reason_class="resources_exhausted", evidence=EVIDENCE,
                 decided_by="judge")
    tick_report = engine.TickReport()
    tick_report.program = {}
    run_program_pipeline(db, paths, settings, tick_report)
    assert ledger.topic(second)["status"] == "active"
    assert tick_report.program["materialized"] == [ledger.topic(second)["campaign_id"]]
    assert tick_report.program["waiting_admitted"] == []


# --------------------------------------------------------------------------- structure & protocol


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


def test_enforce_admission_blocks_manual_and_allows_admitted(tmp_path) -> None:
    paths = _paths(tmp_path, code=tmp_path / "openlabs")
    _manual_lab(paths)
    db = _db(paths)
    blocked = engine.tick(paths, replace(_settings(enforce_admission=True), launch_jobs=False))
    assert {"campaign_id": "manual-stream", "reason": "topic_not_admitted"}.items() <= (
        blocked.production_blocked[0].items()
    )
    assert db.campaign("manual-stream") is None
    settings = replace(_settings(enforce_admission=True), launch_jobs=False)
    ledger = open_topic_ledger(paths, settings.program)
    propose_topic(ledger, {"topic_id": "m", "domain": "test-domain", "question": "q",
                           "data_sources": ["s"]}, db=db, decided_by="gate")
    admit_topic(ledger, "m", db=db, settings=settings.program, decided_by="g",
                admission_task_id="g")
    db.register_campaign("manual-stream", domain="test-domain", title="m")
    activate_topic(ledger, "m", db=db, campaign_id="manual-stream", decided_by="g")
    report = engine.tick(paths, settings)
    assert "manual-stream" in report.production_synced


def test_program_protocol_accepts_simplified_brief_and_rejects_static_research(tmp_path) -> None:
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

    # Dynamic simplified research state passes.
    dyn = root / "dynamic_state.json"
    atomic_write_json(dyn, {
        "schema_version": "openlabs.research_program_state.v1",
        "project_id": "ai-research-program", "workstream_id": "w1",
        "topic_id": "t1", "admission_task_id": "rev-1", "program_role": "research",
        "brief": _brief(0), "compute_estimate": {"locations": ["container_cpu"], "data_gb": 1, "agent_hours": 2},
        "milestone": "kill_test", "status": "active",
    })
    assert module.validate(project_path, dyn, "discovery") == []

    # Static research state without brief or preregistration is rejected.
    research = {"schema_version": "openlabs.research_program_state.v1",
                "project_id": "ai-research-program", "workstream_id": "x",
                "program_role": "research", "status": "active"}
    atomic_write_json(root / "scout_state.json", research)
    errors = module.validate(project_path, root / "scout_state.json", "discovery")
    assert any("only through the admission gate" in e for e in errors)
    assert any("preregistration" in e for e in errors)


def test_backfill_cli_disabled_program_and_lab_registrations(tmp_path, monkeypatch) -> None:
    from openlabs.__main__ import _parser
    from openlabs.labs import load_lab

    paths = _paths(tmp_path / "bf")
    db = _db(paths)
    settings = _settings()
    db.register_campaign("running-study", domain="ai", title="Running study")
    dry = backfill_grandfathered(db, paths, settings)
    assert dry["dry_run"] is True and [i["campaign_id"] for i in dry["planned"]] == ["running-study"]
    written = backfill_grandfathered(db, paths, settings, write=True)
    assert open_topic_ledger(paths, settings.program).topic(written["registered"][0])["status"] == "active"
    assert backfill_grandfathered(db, paths, settings, write=True)["registered"] == []

    args = _parser().parse_args(["program", "backfill"])
    assert args.program_command == "backfill" and not args.write
    assert _parser().parse_args(["program", "submit-card", "--project", "p.json", "--card", "c.json"]).program_command == "submit-card"

    off_paths = _paths(tmp_path / "off")
    _install_program(off_paths)
    _db(off_paths)
    off_report = _tick(off_paths, replace(_settings(), program=ProgramSettings()), monkeypatch)
    assert off_report.program == {}

    for lab in ("ai", "biomed", "materials", "math", "physics", "quant"):
        manifest = load_lab(CODE_ROOT / "labs" / lab / "lab.json")
        protocol = manifest.protocol("research-program")
        assert protocol is not None
        assert {"openlabs-empirical-topic-scout", "openlabs-topic-admission"} <= set(protocol.runtime_skills)


def test_container_rejects_wsl_math_and_paused_project_parks_slots(tmp_path, monkeypatch) -> None:
    import openlabs.program_flow as program_flow

    marker = tmp_path / "dockerenv"
    marker.write_text("", encoding="utf-8")
    monkeypatch.setattr(program_flow, "CONTAINER_MARKER", marker)
    paths = _paths(tmp_path / "wsl")
    _install_program(paths)
    db = _db(paths)
    settings = _settings()
    wsl_prop = _proposal(
        1,
        question="Symbolic convergence proof using wsl_math backend",
        compute_estimate={"locations": ["container_cpu", "wsl_math"], "data_gb": 1.0, "agent_hours": 2.0},
    )
    _, report = _scout_round(paths, db, settings, monkeypatch, [_proposal(0), wsl_prop])
    assert len(report.program["cards_registered"]) == 1
    [rejected] = report.program["rejected_cards"]
    assert rejected["reason"] == REJECTION_BUDGET_EXCEEDED
    assert any("wsl_math" in e for e in rejected["errors"])

    # Paused project parks slots and holds waiting admissions until active again.
    p_paths = _paths(tmp_path / "park")
    project_path = _install_program(p_paths)
    p_db = _db(p_paths)
    p_settings = _settings(max_active_topics=1)
    _, admission, _ = _to_admission(
        p_paths, p_db, p_settings, monkeypatch,
        [_proposal(0, question="Topic alpha on solar wind photometry"),
         _proposal(1, question="Topic beta on power grid congestion forecasting")],
    )
    entries = _packet(admission)["topic_proposals"]
    _complete(p_db, p_paths, admission["task_id"],
              extra={"reviews": [_review(entries[0]), _review(entries[1])]})
    _tick(p_paths, p_settings, monkeypatch)
    ledger = open_topic_ledger(p_paths, p_settings.program)
    first, second = entries[0]["topic_id"], entries[1]["topic_id"]
    assert [ledger.topic(first)["status"], ledger.topic(second)["status"]] == ["active", "admitted"]
    _set_project_status(project_path, "paused")
    freeze_topic(ledger, first, db=p_db, reason_class="negative_result", evidence=EVIDENCE, decided_by="o")
    assert materialize_waiting_topics(p_db, p_paths, p_settings).campaign_ids == ()
    _set_project_status(project_path, "active")
    assert materialize_waiting_topics(p_db, p_paths, p_settings).campaign_ids == (
        ledger.topic(second)["campaign_id"],
    )
