"""Reusable-asset library: index, retrospectives, check-before-build, archiving, seeding."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from openlabs import assets as library
from openlabs import budget as budget_control
from openlabs import engine
from openlabs.config import AssetSettings, load_asset_settings
from openlabs.contracts import (
    atomic_write_json,
    sha256_file,
    validate_asset_proposal,
)
from openlabs.program import open_topic_ledger
from openlabs.program_flow import intake_card
from openlabs.projects import load_project
from test_program_autonomy import _finish, _lease, _ready, _topic
from test_research_program_flow import (
    RECEIPT,
    RECEIPT_SHA,
    _branch,
    _card,
    _complete,
    _db,
    _install_program,
    _packet,
    _paths,
    _settings,
    _tick,
    _to_admission,
)

ON = AssetSettings(enabled=True, retrospective_enabled=True)


# --------------------------------------------------------------------------- fixtures


def _asset_settings(assets: AssetSettings = ON, **program):
    return replace(_settings(**program), assets=assets)


def _env(tmp_path, assets: AssetSettings = ON, **program):
    paths = _paths(tmp_path)
    _install_program(paths)
    return paths, _db(paths), _asset_settings(assets, **program)


def _receipt(path: Path, command: str, exit_code: int = 0) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"command": command, "exit_code": exit_code,
                                "output_tail": "ok"}), encoding="utf-8")
    return {"path": str(path), "sha256": sha256_file(path)}


def _tool(paths, name: str, *, kind: str = "pipeline", title: str | None = None,
          sources=("10.13026/example-0",), methods=("temporal split",), body: str = "x = 1\n",
          exit_code: int = 0, domains=("ai",)) -> dict:
    """An operator draft for a one-file tool with a passing (or failing) receipt."""

    script = paths.data / "staging" / f"{name}.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(f'"""{name}."""\n{body}', encoding="utf-8")
    command = f"python {script} --sample 10"
    return {
        "kind": kind, "title": title or f"{name} pipeline for the cohort",
        "summary": f"{name}: cohort CSV in, temporal-split metrics out.",
        "domains": list(domains), "data_sources": list(sources), "methods": list(methods),
        "source_paths": [str(script)], "entrypoint": f"python {script}",
        "usage": f"python {script} --input cohort.csv", "requirements": {"python": ">=3.11"},
        "verification": {"command": command,
                         "receipt": _receipt(paths.data / "staging" / f"{name}-receipt.json",
                                             command, exit_code)},
    }


def _lesson(text: str = "Source X returns 403 from this host; the Y mirror serves v2.2.",
            **override) -> dict:
    lesson = {"kind": "lesson", "title": "PhysioNet mirror for cohort downloads",
              "summary": "Direct PhysioNet downloads fail here; the mirror works.",
              "domains": ["ai"], "data_sources": ["10.13026/example-0"], "methods": [],
              "body": text}
    lesson.update(override)
    return lesson


def _register(db, paths, settings, proposal, **kwargs):
    defaults = {"origin": {"registered_by": "test"}, "source_roots": (paths.data,),
                "base": paths.data, "artifacts": None, "decided_by": "test"}
    defaults.update(kwargs)
    return library.register_asset(db, paths, settings, proposal, **defaults)


def _index(paths, settings) -> dict:
    return library.open_asset_index(paths, settings).read()


def _asset(paths, settings, asset_id: str) -> dict:
    found = library.find_asset(_index(paths, settings), asset_id)
    assert found is not None
    return found


def _program(tmp_path, monkeypatch, *, cards=1, assets: AssetSettings = ON,
             before_scout=None, **program):
    paths, db, settings = _env(tmp_path, assets, **program)
    if before_scout is not None:
        before_scout(db, paths, settings)
    built = [_card(n, RECEIPT_SHA, reusable_assets=[]) for n in range(cards)]
    _, admission, _ = _to_admission(paths, db, settings, monkeypatch, built)
    entries = _packet(admission)["topic_cards"]
    _complete(db, paths, admission["task_id"],
              extra={"candidate_branches": [_branch(entry) for entry in entries]})
    report = _tick(paths, settings, monkeypatch)
    assert report.errors == [], report.errors
    ledger = open_topic_ledger(paths, settings.program)
    return paths, db, settings, [ledger.topic(e["topic_id"]) for e in entries], admission


def _tasks(db, task_type: str) -> list[dict]:
    with db.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM tasks WHERE task_type=? ORDER BY rowid", (task_type,)
        ).fetchall()
    return [dict(row) for row in rows]


def _freeze(paths, db, settings, monkeypatch, topic) -> engine.TickReport:
    research = db.latest_task(topic["campaign_id"])
    _lease(paths, settings, monkeypatch, db, research["task_id"])
    receipt = paths.data / "workspaces" / "ai" / "freeze-receipt.json"
    receipt.write_text("{}", encoding="utf-8")
    _finish(db, paths, research["task_id"], extra={
        "primary_endpoint_verdict": "failed",
        "preregistration_sha256": topic["preregistration_sha256"],
        "gate_result": {"promotion_decision": "freeze",
                        "freeze_reason_class": "primary_endpoint_failed",
                        "evidence": [{"path": str(receipt), "sha256": sha256_file(receipt)}],
                        "reopen_conditions": [{"type": "new_data_source",
                                               "description": "A later admission year."}]},
    })
    return _tick(paths, settings, monkeypatch)


NEGATIVE = {
    "kind": "negative_result",
    "title": "Retrieval advantage does not survive a temporal split",
    "summary": "On the later admission year the retrieval model loses to the matched baseline.",
    "domains": ["ai"], "data_sources": ["10.13026/example-0"], "methods": ["temporal split"],
    "negative": {"question": "Does retrieval keep its advantage on a later year?",
                 "attempted": "Pre-registered temporal split against the matched baseline.",
                 "why_failed": "AUROC 0.71 vs 0.74; the advantage came from leakage.",
                 "retry_when": [{"type": "new_data_source",
                                 "description": "A later admission year is released."}]},
}


# --------------------------------------------------------------------------- index


def test_index_writes_are_atomic_idempotent_and_merge_versions(tmp_path) -> None:
    paths, db, settings = _env(tmp_path)
    first = _register(db, paths, settings, _tool(paths, "cohort"))
    assert first["outcome"] == "registered"
    asset = _asset(paths, settings, first["asset_id"])
    assert asset["status"] == "active" and asset["use_count"] == 0
    assert asset["path"] == f"assets/pipeline/{first['asset_id']}"
    assert (paths.data / asset["path"] / "cohort.py").is_file()
    assert asset["verification"]["status"] == "passed"
    assert (paths.data / asset["verification"]["receipt_path"]).is_file()
    assert set(library.SUMMARY_FIELDS) <= set(asset)
    index_file = library.index_path(paths, settings)
    assert not [p for p in index_file.parent.iterdir() if p.name.startswith(".")]
    stamp = index_file.stat().st_mtime_ns

    again = _register(db, paths, settings, _tool(paths, "cohort"))
    assert again == {"outcome": "duplicate", "asset_id": first["asset_id"], "errors": []}
    assert index_file.stat().st_mtime_ns == stamp  # nothing changed, nothing written

    newer = _register(db, paths, settings, _tool(paths, "cohort", body="x = 2\n",
                                                  title="cohort pipeline for the cohorts"))
    assert newer["outcome"] == "new_version" and newer["supersedes"] == first["asset_id"]
    old = _asset(paths, settings, first["asset_id"])
    assert old["status"] == "archived" and old["superseded_by"] == newer["asset_id"]
    assert old["path"].startswith("assets/archive/pipeline/")
    assert (paths.data / old["path"] / "cohort.py").is_file()  # moved, never deleted
    assert _asset(paths, settings, newer["asset_id"])["version"] == 2

    other = _register(db, paths, settings, _tool(paths, "cohort", body="x = 3\n",
                                                  sources=("10.13026/other",)))
    assert other["outcome"] == "registered"  # different data source: not a new version
    events = [e["event_type"] for e in db.events(entity_type="asset",
                                                  entity_id=first["asset_id"])]
    assert events == ["asset_registered", "asset_superseded"]


def test_proposal_fields_workspace_and_receipt_are_checked(tmp_path) -> None:
    paths, db, settings = _env(tmp_path)
    assert not validate_asset_proposal({"kind": "lesson", "title": "x"}).valid
    errors = validate_asset_proposal({**_lesson(), "summary": "two\nlines"}).errors
    assert "summary must be one line" in errors
    assert not validate_asset_proposal({**NEGATIVE, "negative": {
        **NEGATIVE["negative"], "retry_when": [{"type": "wish", "description": "x"}]}}).valid

    workspace = paths.data / "workspaces" / "ai" / "topic-campaign"
    workspace.mkdir(parents=True)
    outside = _tool(paths, "outside")
    rejected = _register(db, paths, settings, outside, source_roots=(workspace,),
                         base=workspace, artifacts={})
    assert rejected["outcome"] == "rejected"
    assert "outside the topic workspace" in rejected["errors"][0]

    inside = _tool(paths, "inside")
    script = workspace / "inside.py"
    script.write_text("x = 1\n", encoding="utf-8")
    inside["source_paths"] = ["inside.py"]
    missing = _register(db, paths, settings, inside, source_roots=(workspace,),
                        base=workspace, artifacts={})
    assert missing["errors"] == ["verification_receipt_not_a_result_artifact"]
    receipt = Path(inside["verification"]["receipt"]["path"])
    bound = {"receipt": (receipt, sha256_file(receipt))}
    accepted = _register(db, paths, settings, inside, source_roots=(workspace,),
                         base=workspace, artifacts=bound)
    assert accepted["outcome"] == "registered"

    failing = _tool(paths, "failing", exit_code=1)
    assert _register(db, paths, settings, failing)["errors"] == ["verification_failed"]
    no_receipt = _tool(paths, "bare")
    no_receipt.pop("verification")
    assert _register(db, paths, settings, no_receipt)["outcome"] == "rejected"


def test_summary_view_ranks_by_domain_and_data_source_and_truncates(tmp_path) -> None:
    paths, db, settings = _env(tmp_path)
    _register(db, paths, settings, _lesson("A fact about biology data.", domains=["biology"],
                                           data_sources=["10.1/bio"], title="Bio lesson"))
    _register(db, paths, settings, _lesson("A fact about the ai cohort.", data_sources=[],
                                           title="AI lesson without source"))
    best = _register(db, paths, settings, _lesson("Cohort mirror fact.", title="Cohort mirror"))
    archived = _register(db, paths, settings, _lesson("Old fact.", title="Old cohort fact"))
    library.archive_asset(db, paths, settings, archived["asset_id"], reason="manual",
                          decided_by="test")
    document = _index(paths, settings)

    view = library.summary_view(document, settings, domains=["ai"],
                                data_sources=["https://doi.org/10.13026/EXAMPLE-0"])
    ids = [line["asset_id"] for line in view["assets"]]
    assert ids[0] == best["asset_id"] and archived["asset_id"] not in ids
    assert view["active_assets"] == 3 and not view["truncated"]
    assert list(view["assets"][0]) == list(library.SUMMARY_FIELDS)
    assert "body" not in view["assets"][0]
    limited = library.summary_view(document, settings, domains=["ai"], limit=1)
    assert limited["shown"] == 1 and limited["truncated"]
    tiny = library.summary_view(document, settings, max_chars=10)
    assert tiny["shown"] == 1  # always at least one line, never more than the budget allows


# --------------------------------------------------------------------------- retrospectives


def _retrospective(db) -> dict:
    tasks = _tasks(db, library.RETROSPECTIVE_TASK_TYPE)
    assert tasks
    return tasks[-1]


def test_frozen_topic_retrospective_registers_a_negative_result_seen_by_the_next_scout(
    tmp_path, monkeypatch
):
    paths, db, settings, (topic,), _ = _program(tmp_path, monkeypatch)
    report = _freeze(paths, db, settings, monkeypatch, topic)
    assert _topic(paths, settings, topic["topic_id"])["status"] == "frozen"
    scheduled = report.program["assets"]["retrospectives_scheduled"]
    assert [item["state"] for item in scheduled] == ["frozen"]
    task = _lease(paths, settings, monkeypatch, db, _retrospective(db)["task_id"])
    assert settings.routing.task_tiers[library.RETROSPECTIVE_TASK_TYPE] == "light"
    assert task["session_mode"] == "fresh" and task["agent_role"] == "researcher"
    assert task["skill_path"] == library.RETROSPECTIVE_SKILL
    packet = json.loads(Path(task["input_path"]).read_text(encoding="utf-8"))
    assert packet["negative_result_required"] is True
    assert packet["ledger_entry"]["reopen_conditions"][0]["type"] == "new_data_source"
    workspace = Path(packet["topic_workspace"])
    loader = workspace / "tools" / "loader.py"
    loader.parent.mkdir(parents=True, exist_ok=True)
    loader.write_text('"""Load the cohort."""\n', encoding="utf-8")
    command = "python tools/loader.py --rows 10"
    receipt = json.dumps({"command": command, "exit_code": 0}).encode()
    tool = {"kind": "data_loader", "title": "Cohort loader",
            "summary": "Cohort CSV in, typed frame out.", "domains": ["ai"],
            "data_sources": ["10.13026/example-0"], "methods": [],
            "source_paths": ["tools/loader.py"], "entrypoint": "python tools/loader.py",
            "usage": "python tools/loader.py --rows N",
            "verification": {"command": command, "receipt": {
                "path": "receipts/verify.json",
                "sha256": __import__("hashlib").sha256(receipt).hexdigest()}}}
    _complete(db, paths, task["task_id"], extra={"asset_proposals": [NEGATIVE, tool]},
              receipt_files={"verify.json": receipt})

    report = _tick(paths, settings, monkeypatch)

    registered = report.program["assets"]["retrospectives_registered"][0]
    assert registered["outcome"] == "registered"
    assert [p["outcome"] for p in registered["proposals"]] == ["registered", "registered"]
    negative = next(a for a in _index(paths, settings)["assets"]
                    if a["kind"] == "negative_result")
    assert negative["origin"]["topic_id"] == topic["topic_id"]
    assert negative["path"] is None and negative["negative"]["retry_when"]
    # Once per topic and state, even after more ticks.
    _tick(paths, settings, monkeypatch)
    assert len(_tasks(db, library.RETROSPECTIVE_TASK_TYPE)) == 1

    # The next topic scout (after the scout interval) sees the negative result.
    scouts = len(_tasks(db, "topic_scout"))
    later = budget_control.current_time() + timedelta(hours=13)
    monkeypatch.setattr(budget_control, "current_time", lambda: later)
    _tick(paths, settings, monkeypatch)
    assert len(_tasks(db, "topic_scout")) == scouts + 1
    latest = _tasks(db, "topic_scout")[-1]
    summary = _packet(latest)["reusable_assets_summary"]
    assert negative["asset_id"] in [line["asset_id"] for line in summary["assets"]]


def test_frozen_retrospective_without_negative_result_retries_then_falls_back(
    tmp_path, monkeypatch
):
    paths, db, settings, (topic,), _ = _program(tmp_path, monkeypatch)
    _freeze(paths, db, settings, monkeypatch, topic)
    for attempt in (1, 2):
        task = _lease(paths, settings, monkeypatch, db, _retrospective(db)["task_id"])
        _complete(db, paths, task["task_id"], extra={"asset_proposals": []})
        report = _tick(paths, settings, monkeypatch)
        outcome = report.program["assets"]["retrospectives_registered"][0]["outcome"]
        assert outcome == "negative_result_missing"
    assert len(_tasks(db, library.RETROSPECTIVE_TASK_TYPE)) == 2
    fallback = report.program["assets"]["retrospective_fallbacks"][0]
    asset = _asset(paths, settings, fallback["asset_id"])
    assert asset["kind"] == "negative_result"
    assert asset["origin"]["generated_from"] == "topic_ledger"
    assert asset["negative"]["retry_when"][0]["description"] == "A later admission year."


def test_ready_topic_gets_exactly_one_retrospective(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,), _ = _program(tmp_path, monkeypatch)
    report = _ready(paths, db, settings, monkeypatch, topic)
    assert _topic(paths, settings, topic["topic_id"])["status"] == "ready_queue"
    assert [i["state"] for i in report.program["assets"]["retrospectives_scheduled"]] == [
        "ready_queue"]
    task = _lease(paths, settings, monkeypatch, db, _retrospective(db)["task_id"])
    packet = json.loads(Path(task["input_path"]).read_text(encoding="utf-8"))
    assert packet["negative_result_required"] is False and packet["results"]
    _complete(db, paths, task["task_id"], extra={"asset_proposals": []})
    report = _tick(paths, settings, monkeypatch)
    assert report.program["assets"]["retrospectives_registered"][0]["outcome"] == "registered"
    _tick(paths, settings, monkeypatch)
    assert len(_tasks(db, library.RETROSPECTIVE_TASK_TYPE)) == 1


# --------------------------------------------------------------------------- check before build


def test_admission_rejects_unknown_or_archived_assets_and_flags_reuse(tmp_path, monkeypatch):
    holder: dict = {}

    def seed(db, paths, settings):
        holder["pipeline"] = _register(db, paths, settings, _tool(paths, "cohort"))["asset_id"]
        old = _register(db, paths, settings, _lesson(title="Old"))["asset_id"]
        library.archive_asset(db, paths, settings, old, reason="manual", decided_by="test")
        holder["archived"] = old

    paths, db, settings = _env(tmp_path)
    seed(db, paths, settings)
    project = load_project(paths.data / "workspaces" / "ai" / "projects" / "research-program"
                           / "project.json")
    receipt = paths.data / "receipts" / "data-access.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_bytes(RECEIPT)

    def intake(n, refs):
        return intake_card(db, paths, settings, project,
                           _card(n, RECEIPT_SHA, reusable_assets=refs), decided_by="manual:t",
                           provider="human", source_task_id=None, receipt_digests=None)

    # A wrong asset reference is recorded for the gate, not a rejection.
    ledger = open_topic_ledger(paths, settings.program)
    unknown = intake(1, ["no-such-asset"])
    assert unknown["status"] == "proposed"
    assert any("'no-such-asset' is not in the reusable-asset index" in e
               for e in ledger.topic(unknown["topic_id"])["card_check"]["warnings"])
    archived = intake(2, [{"asset_id": holder["archived"]}])
    assert archived["status"] == "proposed"
    assert any("is archived" in e
               for e in ledger.topic(archived["topic_id"])["card_check"]["warnings"])
    assert intake(3, [holder["pipeline"]])["status"] == "proposed"

    # Through the scout and the gate: the admission packet carries the reuse fact.
    flow_root = tmp_path / "flow"
    flow_root.mkdir()
    paths_b, db_b, settings_b = _env(flow_root)
    seed(db_b, paths_b, settings_b)
    _, admission, _ = _to_admission(
        paths_b, db_b, settings_b, monkeypatch,
        [_card(0, RECEIPT_SHA, reusable_assets=[holder["pipeline"]])])
    entry = _packet(admission)["topic_cards"][0]
    assert entry["asset_reuse"]["reuses_pipeline_or_data_loader"] is True
    assert entry["asset_reuse"]["referenced"][0]["asset_id"] == holder["pipeline"]
    assert "reusable_assets_summary" in _packet(admission)


def test_research_task_gets_summary_and_referenced_bodies(tmp_path, monkeypatch) -> None:
    holder: dict = {}

    def seed(db, paths, settings):
        holder["id"] = _register(db, paths, settings, _tool(paths, "cohort"))["asset_id"]

    paths, db, settings = _env(tmp_path)
    seed(db, paths, settings)
    _, admission, _ = _to_admission(paths, db, settings, monkeypatch,
                                    [_card(0, RECEIPT_SHA, reusable_assets=[holder["id"]])])
    entry = _packet(admission)["topic_cards"][0]
    _complete(db, paths, admission["task_id"], extra={"candidate_branches": [_branch(entry)]})
    _tick(paths, settings, monkeypatch)
    topic = open_topic_ledger(paths, settings.program).topic(entry["topic_id"])
    research = db.latest_task(topic["campaign_id"])
    campaign = db.campaign(topic["campaign_id"])

    resources = library.research_read_resources(paths, settings, research, campaign)
    labels = [item["label"] for item in resources]
    assert labels == ["reusable-asset-summary", f"reusable-asset:{holder['id']}"]
    view = json.loads(Path(resources[0]["path"]).read_text(encoding="utf-8"))
    assert view["referenced_by_card"][0]["asset_id"] == holder["id"]
    assert Path(resources[1]["path"]).is_dir()
    off = replace(settings, assets=AssetSettings())
    assert library.research_read_resources(paths, off, research, campaign) == []


# --------------------------------------------------------------------------- usage and archive


def _result(db, paths, settings, monkeypatch, task_id, extra):
    _lease(paths, settings, monkeypatch, db, task_id)
    _finish(db, paths, task_id, extra=extra)
    return _tick(paths, settings, monkeypatch)


def test_assets_used_counts_and_two_broken_reports_archive(tmp_path, monkeypatch) -> None:
    holder: dict = {}

    def seed(db, paths, settings):
        holder["tool"] = _register(db, paths, settings, _tool(paths, "cohort"))["asset_id"]
        holder["lesson"] = _register(db, paths, settings, _lesson())["asset_id"]

    paths, db, settings, (topic,), _ = _program(tmp_path, monkeypatch, before_scout=seed)
    research = db.latest_task(topic["campaign_id"])
    report = _result(db, paths, settings, monkeypatch, research["task_id"], {
        "assets_used": [holder["tool"], {"asset_id": holder["lesson"]}],
        "assets_broken": [{"asset_id": holder["lesson"], "reason": "mirror moved"}],
    })
    usage = report.program["assets"]["usage"][0]
    assert usage["used"] == [holder["tool"]] and usage["broken"] == [holder["lesson"]]
    tool = _asset(paths, settings, holder["tool"])
    assert tool["use_count"] == 1 and tool["used_by"] == [topic["topic_id"]]
    assert tool["last_used_at"] and tool["last_verified_at"] == tool["last_used_at"]
    lesson = _asset(paths, settings, holder["lesson"])
    assert lesson["status"] == "active" and lesson["broken_streak"] == 1
    assert lesson["verification"]["status"] == "needs_verification"

    nxt = db.latest_task(topic["campaign_id"])
    report = _result(db, paths, settings, monkeypatch, nxt["task_id"], {
        "assets_broken": [holder["lesson"]]})
    lesson = _asset(paths, settings, holder["lesson"])
    assert lesson["status"] == "archived" and lesson["archive_reason"] == "reported_broken"
    assert report.program["assets"]["usage"][0]["archived"] == [holder["lesson"]]
    assert _asset(paths, settings, holder["tool"])["use_count"] == 1  # replay-safe


def test_periodic_archive_rules(tmp_path, monkeypatch) -> None:
    paths, db, settings = _env(tmp_path, AssetSettings(enabled=True, max_lessons=2))
    unused = _register(db, paths, settings, _tool(paths, "unused"))["asset_id"]
    used = _register(db, paths, settings, _tool(paths, "used", sources=("10.1/x",)))["asset_id"]
    with library.open_asset_index(paths, settings).transaction() as document:
        library.find_asset(document, used)["use_count"] = 3
    titles = ("Mirror for cohort downloads", "Timestamp units in the vitals table",
              "Licence terms forbid redistribution of notes")
    lessons = [_register(db, paths, settings, _lesson(f"Fact {n}.", title=title))["asset_id"]
               for n, title in enumerate(titles)]
    with library.open_asset_index(paths, settings).transaction() as document:
        library.find_asset(document, lessons[0])["last_used_at"] = "2099-01-01T00:00:00Z"
        library.find_asset(document, lessons[1])["created_at"] = "2020-01-01T00:00:00Z"

    assert library.maintain(db, paths, settings) == [
        {"asset_id": lessons[1], "reason": "lesson_cap"}]
    later = budget_control.current_time() + timedelta(days=121)
    archived = library.maintain(db, paths, settings, now=later)
    assert archived == [{"asset_id": unused, "reason": "unused"}]
    assert _asset(paths, settings, used)["status"] == "active"
    assert (paths.data / _asset(paths, settings, unused)["path"] / "unused.py").is_file()

    # The tick runs it at most once per interval.
    report = _tick(paths, settings, monkeypatch)
    assert report.program["assets"]["archived"] == []
    report = _tick(paths, settings, monkeypatch)
    assert "archived" not in report.program["assets"]


# --------------------------------------------------------------------------- operator commands


def test_seed_is_read_only_and_register_writes(tmp_path) -> None:
    paths, db, settings = _env(tmp_path)
    index_file = library.index_path(paths, settings)
    before = index_file.read_bytes()
    seeded = library.seed_candidates(paths, settings)
    assert seeded["dry_run"] is True and seeded["candidates"] > 0
    assert index_file.read_bytes() == before
    names = {Path(d["source_paths"][0]).name for d in seeded["asset_proposals"]}
    assert "__init__.py" not in names
    draft = seeded["asset_proposals"][0]
    assert draft["verification"]["receipt"] == {"path": "", "sha256": ""}
    assert not validate_asset_proposal(draft).valid  # must be completed by the operator

    path = tmp_path / "draft.json"
    atomic_write_json(path, {"asset_proposals": [_tool(paths, "confirmed"), _lesson()]})
    result = library.register_draft(db, paths, settings, path, by="owner")
    assert [item["outcome"] for item in result["outcomes"]] == ["registered", "registered"]
    listed = library.list_assets(paths, settings)["assets"]
    assert len(listed) == 2 and set(listed[0]) == set(library.SUMMARY_FIELDS) | {"status"}
    shown = library.show_asset(paths, settings, listed[0]["asset_id"])
    assert shown["origin"]["registered_by"] == "manual:owner"


def test_cli_seed_and_list_touch_no_runtime_state(tmp_path, capsys) -> None:
    from openlabs.__main__ import main

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "openlabs").symlink_to(Path(__file__).resolve().parents[2])
    assert main(["--workspace", str(workspace), "program", "assets", "seed", "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["candidates"] > 0
    assert sorted(p.name for p in workspace.iterdir()) == ["openlabs"]


def test_reuse_cost_comparison(tmp_path, monkeypatch) -> None:
    holder: dict = {}

    def seed(db, paths, settings):
        holder["id"] = _register(db, paths, settings, _tool(paths, "cohort"))["asset_id"]

    paths, db, settings, (first, second), _ = _program(
        tmp_path, monkeypatch, cards=2, before_scout=seed)
    research = db.latest_task(first["campaign_id"])
    _result(db, paths, settings, monkeypatch, research["task_id"],
            {"assets_used": [holder["id"]]})
    comparison = library.reuse_cost_comparison(db, paths, settings)
    assert comparison["with_assets"]["topics"] == 1
    assert comparison["without_assets"]["topics"] == 1
    assert comparison["with_assets"]["attempts"] == 1
    assert comparison["with_assets"]["run_seconds"] == pytest.approx(10.0)
    assert comparison["without_assets"]["attempts"] == 0
    rows = {row["topic_id"]: row for row in comparison["topics"]}
    assert rows[first["topic_id"]]["assets"] == [holder["id"]]


# --------------------------------------------------------------------------- switches


def test_switches_off_change_nothing(tmp_path, monkeypatch) -> None:
    paths, db, settings, (topic,), admission = _program(tmp_path, monkeypatch,
                                                        assets=AssetSettings())
    assert "asset_reuse" not in _packet(admission)["topic_cards"][0]
    assert "reusable_assets_summary" not in _packet(admission)
    scout = _tasks(db, "topic_scout")[0]
    assert "reusable_assets_summary" not in _packet(scout)
    report = _freeze(paths, db, settings, monkeypatch, topic)
    assert "assets" not in report.program
    assert _tasks(db, library.RETROSPECTIVE_TASK_TYPE) == []
    assert db.meta_get(library.RETRO_SINCE_KEY) is None
    research = {"agent_role": "researcher", "campaign_id": topic["campaign_id"]}
    assert library.research_read_resources(paths, settings, research, None) == []
    assert not (paths.data / "assets").exists()
    # Example cards name free-text assets; without the switch they are not checked.
    assert library.card_reference_errors(paths, settings, {"reusable_assets": ["x"]}) == []


def test_config_table() -> None:
    assert load_asset_settings({}) == AssetSettings()
    loaded = load_asset_settings({"assets": {"enabled": True, "summary_limit": 5,
                                             "seed_paths": ["labs/*/tools"]}})
    assert loaded.enabled and not loaded.retrospective_enabled
    assert loaded.summary_limit == 5 and loaded.seed_paths == ("labs/*/tools",)
    assert load_asset_settings({"retrospective_enabled": True}).retrospective_enabled
    with pytest.raises(ValueError):
        load_asset_settings({"assets": {"root": "../outside"}})
