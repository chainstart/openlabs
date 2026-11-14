"""Research lines: line-keyed scouting, research-line card fields, the environment hold and
the feasibility precheck as the first research task."""

from __future__ import annotations

import json
from pathlib import Path

import test_parallel_program as parallel
import test_research_program_flow as flow
from openlabs import engine
from openlabs.config import load_program_settings
from openlabs.contracts import validate_topic_card
from openlabs.program import open_topic_ledger
from openlabs.program_flow import LAST_SCOUT_KEY, schedule_scouts
from openlabs.research_lines import environment_status, load_research_lines

NOW = parallel.NOW
LINE = "ml-evaluation-protocols"


def _line_fields(card: dict) -> dict:
    routine = [item["name"] for item in card["venues"]["routine"]]
    return {
        "research_line": LINE,
        "feasibility_precheck": {
            "description": "Reproduce the published headline AUROC under its original split.",
            "pass_criterion": "within 0.01 AUROC of the published value",
            "budget": "1 container GPU hour, 2 agent hours",
            "on_failure": "freeze",
        },
        "license_check": {
            "items": [
                {"name": "PyTorch", "kind": "software", "license": "BSD-3-Clause",
                 "evidence": "registry/research-lines.yaml", "allowed": True},
                {"name": "MIMIC-IV-ED", "kind": "data", "license": "PhysioNet 1.5.0",
                 "evidence": "https://physionet.org/content/mimic-iv-ed/", "allowed": True},
            ],
            "blacklist_checked": True,
        },
        "fee_check": [
            {"venue": routine[0], "page_charges": "none", "colour_charges": "none online",
             "submission_fee": "none", "fee_free_route": True,
             "evidence_level": "verified_publisher", "evidence": "research-lines.yaml"},
            {"venue": routine[1], "page_charges": "unknown", "colour_charges": "unknown",
             "submission_fee": "unknown", "fee_free_route": "unverified",
             "evidence_level": "unverified", "evidence": "not obtained"},
        ],
    }


def _line_card(n: int = 0, receipt_sha: str = flow.RECEIPT_SHA, **override) -> dict:
    card = flow._card(n, receipt_sha)
    card.update(_line_fields(card))
    card.update(override)
    return card


def _lines_file(paths, status: str = "not_ready", line: str = LINE) -> Path:
    path = paths.data / "registry" / "research-lines.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "schema_version: openlabs.research_lines.v1\n"
        "lines:\n"
        f"  - id: {line}\n"
        "    host_domain: ai\n"
        "    title: test line\n"
        "    environment:\n"
        f"      status: {status}\n"
        "      sop: sop.md\n",
        encoding="utf-8",
    )
    return path


def _make_line_project(paths, line: str = LINE) -> None:
    project = paths.data / "workspaces" / "ai" / "projects" / "research-program" / "project.json"
    payload = json.loads(project.read_text(encoding="utf-8"))
    payload["research_line"] = line
    project.write_text(json.dumps(payload), encoding="utf-8")


# --------------------------------------------------------------------------- contract


def test_line_cards_need_precheck_licences_and_fees_legacy_cards_do_not() -> None:
    assert validate_topic_card(flow._card(), current_year=flow.YEAR).valid
    assert validate_topic_card(_line_card(), current_year=flow.YEAR).valid
    bare = flow._card(research_line=LINE)
    errors = validate_topic_card(bare, current_year=flow.YEAR).errors
    assert any(e.startswith("feasibility_precheck is missing") for e in errors)
    assert any(e.startswith("license_check is missing") for e in errors)
    assert any(e.startswith("fee_check must cover") for e in errors)

    soft = _line_card()
    soft["feasibility_precheck"]["on_failure"] = "continue"
    assert "feasibility_precheck.on_failure must be freeze" in validate_topic_card(soft).errors

    blocked = _line_card()
    blocked["license_check"]["items"][0]["allowed"] = False
    assert any("allowed must be true" in e for e in validate_topic_card(blocked).errors)

    uncovered = _line_card()
    uncovered["fee_check"] = uncovered["fee_check"][:1]
    assert any("does not cover routine venue" in e for e in validate_topic_card(uncovered).errors)

    unverified = _line_card()
    unverified["fee_check"][0]["evidence_level"] = "secondary"
    assert any("at least one routine venue" in e for e in validate_topic_card(unverified).errors)

    paid = _line_card()
    paid["fee_check"][1]["fee_free_route"] = False
    assert any("mandatory fee" in e for e in validate_topic_card(paid).errors)


def test_direction_file_reader_reports_environment_status(tmp_path) -> None:
    paths = flow._paths(tmp_path)
    document = load_research_lines(_lines_file(paths, "ready"))
    assert environment_status(document, LINE) == "ready"
    assert environment_status(document, "other") == "unknown_line"
    assert environment_status(None, LINE) == "unreadable"
    settings = load_program_settings({"research_lines": ["a", "b"]})
    assert settings.research_lines == ("a", "b")
    assert settings.research_lines_path == "registry/research-lines.yaml"


def test_repository_direction_file_is_consistent_with_the_instance_lines() -> None:
    from openlabs.instance import RESEARCH_LINES

    data = flow.CODE_ROOT.parent / "openlabs-data" / "registry" / "research-lines.yaml"
    if not data.is_file():
        return  # the data repository is not next to this checkout
    document = load_research_lines(data)
    declared = {item["id"]: item["host_domain"] for item in document["lines"]}
    assert declared == dict(RESEARCH_LINES)


# --------------------------------------------------------------------------- scouting


def _line_program(tmp_path, lines, **program):
    """Projects for ai/physics/quant domains plus two physics line projects."""

    paths = flow._paths(tmp_path)
    parallel._install_domains(paths)
    template = json.loads((flow.TEMPLATE / "project.json").read_text(encoding="utf-8"))
    for line in ("astro-photometry", "engineering-vvuq"):
        root = paths.data / "workspaces" / "physics" / "projects" / line
        root.mkdir(parents=True, exist_ok=True)
        for name in ("scout_state.json", "admission_state.json"):
            text = (flow.TEMPLATE / name).read_text(encoding="utf-8")
            (root / name).write_text(text.replace('"ai-', f'"{line}-'), encoding="utf-8")
        project = json.loads(json.dumps(template).replace('"ai-', f'"{line}-'))
        project["domain"] = "physics"
        project["protocol"]["primary_skill"] = "physics-research-loop"
        project["research_line"] = line
        (root / "project.json").write_text(json.dumps(project), encoding="utf-8")
    db = flow._db(paths)
    settings = flow._settings(research_lines=tuple(lines), **program)
    engine._sync_active_projects(db, paths, settings, engine.TickReport())
    return paths, db, settings


def test_scouting_rotates_by_line_and_skips_projects_without_a_line(tmp_path) -> None:
    lines = ("engineering-vvuq", "astro-photometry")
    paths, db, settings = _line_program(tmp_path, lines, max_concurrent_scouts=5,
                                        candidate_pool_low_water=8, scout_min_interval_hours=1)
    scheduled, reason = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    # Two lines of one domain scout side by side; the domain projects get no scout.
    assert sorted(item.research_line for item in scheduled) == sorted(lines)
    assert {item.domain for item in scheduled} == {"physics"}
    assert scheduled[0].research_line == "engineering-vvuq"  # configured order breaks ties
    assert reason == "scout_in_flight"
    stamps = db.meta_items(LAST_SCOUT_KEY + ":")
    assert set(stamps) == set(lines)
    packets = [json.loads(Path(t["input_path"]).read_text()) for t in parallel._scouts(db)]
    assert {p["research_line"] for p in packets} == set(lines)
    assert all(p["research_line_summary"]["environment_status"] == "unreadable"
               for p in packets)
    tasks = parallel._scouts(db)
    assert all("research line" in t["objective"] for t in tasks)
    # Finished scouts: the per-line interval applies.
    parallel._finish(db, [item.task_id for item in scheduled])
    again, reason = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    assert again == [] and reason == "scout_min_interval"


def test_without_research_lines_rotation_stays_by_domain(tmp_path) -> None:
    paths, db, settings = _line_program(tmp_path, (), max_concurrent_scouts=5,
                                        candidate_pool_low_water=20, scout_min_interval_hours=0)
    scheduled, _ = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    # Domain projects rotate as before; the line projects are keyed by their lines.
    assert {item.domain for item in scheduled} == {"ai", "physics", "quant"}


# --------------------------------------------------------------------------- intake and gate


def _line_setup(tmp_path, status: str):
    paths = flow._paths(tmp_path)
    flow._install_program(paths)
    _make_line_project(paths)
    _lines_file(paths, status)
    db = flow._db(paths)
    settings = flow._settings()
    return paths, db, settings


def test_line_project_cards_carry_the_line_and_the_packet_names_it(tmp_path, monkeypatch):
    paths, db, settings = _line_setup(tmp_path, "ready")
    card = _line_card(0, research_line="some-other-line")
    _, admission, report = flow._to_admission(paths, db, settings, monkeypatch, [card])
    assert report.errors == []
    registered = report.program["cards_registered"]
    assert len(registered) == 1, report.program
    topic = open_topic_ledger(paths, settings.program).topic(registered[0]["topic_id"])
    assert topic["research_line"] == LINE  # the project's line, not the agent's
    packet = flow._packet(admission)
    assert packet["research_lines"][LINE]["environment_status"] == "ready"
    assert packet["topic_cards"][0]["card"]["research_line"] == LINE
    labels = {item["label"] for item in packet["read_resources"]}
    assert "research-lines" in labels
    assert "research-lines.yaml" in admission["objective"]


def test_a_line_without_ready_environment_gets_no_scout_and_no_review(tmp_path, monkeypatch):
    # 2026-11-12/13: 24 gate admits were turned into control-plane holds because the
    # line was not ready; 14 never left the hold. Now the tick skips such a line.
    paths, db, settings = _line_setup(tmp_path, "not_ready")
    report = flow._tick(paths, settings, monkeypatch)
    assert report.program["scouts_scheduled"] == []
    assert report.program["scout_blocked"] == "research_line_environment_not_ready"
    assert report.program["lines_environment_not_ready"] == {LINE: "not_ready"}
    assert parallel._scouts(db) == []

    # A card that is already proposed (by hand, or from before) waits unreviewed.
    from openlabs.program_flow import intake_card, schedule_topic_admission
    from openlabs.projects import load_project

    project = load_project(paths.data / "workspaces" / "ai" / "projects" / "research-program"
                           / "project.json")
    receipt = paths.data / "receipts" / "data-access.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_bytes(flow.RECEIPT)
    outcome = intake_card(db, paths, settings, project, _line_card(0), decided_by="manual:t",
                          provider="human", source_task_id=None, receipt_digests=None)
    assert outcome["status"] == "proposed", outcome
    with db.connect() as connection:
        admission_campaign = dict(connection.execute(
            "SELECT * FROM campaigns WHERE campaign_id LIKE '%admission%' LIMIT 1").fetchone())
    schedule = schedule_topic_admission(db, paths, settings, admission_campaign, epoch=1)
    assert schedule.task_id is None
    assert schedule.reason == "research_line_environment_not_ready"
    topic = open_topic_ledger(paths, settings.program).topic(outcome["topic_id"])
    assert topic["status"] == "proposed"

    # Once the line is ready the waiting card goes to the gate.
    _lines_file(paths, "ready")
    schedule = schedule_topic_admission(db, paths, settings, admission_campaign, epoch=1)
    assert schedule.task_id is not None


def test_a_line_that_stops_being_ready_during_review_is_still_held(tmp_path, monkeypatch):
    paths, db, settings = _line_setup(tmp_path, "ready")
    _, admission, _ = flow._to_admission(paths, db, settings, monkeypatch, [_line_card(0)])
    _lines_file(paths, "not_ready")
    entry = flow._packet(admission)["topic_cards"][0]
    flow._complete(db, paths, admission["task_id"],
                   extra={"candidate_branches": [flow._branch(entry)]})
    report = flow._tick(paths, settings, monkeypatch)
    decision = report.program["admission_decisions"][0]
    assert decision["outcome"] == "held"
    assert decision["reason"].startswith(f"research_line_environment_not_ready:{LINE}")
    topic = open_topic_ledger(paths, settings.program).topic(entry["topic_id"])
    assert topic["status"] == "rejected"
    assert topic["history"][-1]["reason"] == "admission_hold"
    conditions = topic["reopen_conditions"]
    assert any(item["type"] == "line_environment_ready" for item in conditions)
    assert db.campaign(f"{entry['topic_id']}") is None


def test_ready_line_admits_and_the_precheck_is_the_first_task(tmp_path, monkeypatch):
    paths, db, settings = _line_setup(tmp_path, "ready")
    _, admission, _ = flow._to_admission(paths, db, settings, monkeypatch, [_line_card(0)])
    entry = flow._packet(admission)["topic_cards"][0]
    flow._complete(db, paths, admission["task_id"],
                   extra={"candidate_branches": [flow._branch(entry)]})
    report = flow._tick(paths, settings, monkeypatch)
    assert report.program["admission_decisions"][0]["outcome"] == "admitted"
    topic = open_topic_ledger(paths, settings.program).topic(entry["topic_id"])
    assert topic["status"] == "active"
    campaign = db.campaign(topic["campaign_id"])
    state = json.loads(Path(campaign["workstream_state_path"]).read_text(encoding="utf-8"))
    assert state["research_line"] == LINE
    assert state["feasibility_precheck"]["on_failure"] == "freeze"
    assert state["fee_check"] and state["license_check"]["blacklist_checked"] is True
    first = db.latest_task(topic["campaign_id"])
    assert "feasibility_precheck" in first["objective"]
    assert "feasibility_precheck_failed" in first["objective"]


def test_research_line_example_card_is_valid() -> None:
    example = flow.TEMPLATE / "topic-card.research-line.example.json"
    card = json.loads(example.read_text(encoding="utf-8"))
    for item in card["audience"]["citations"]:
        item["year"] = flow.YEAR - 1
    assert validate_topic_card(card, current_year=flow.YEAR).valid


def test_precheck_budget_excludes_remote_queue_wait(tmp_path, monkeypatch):
    paths, db, settings = _line_setup(tmp_path, "ready")
    _, admission, _ = flow._to_admission(paths, db, settings, monkeypatch, [_line_card(0)])
    entry = flow._packet(admission)["topic_cards"][0]
    flow._complete(db, paths, admission["task_id"],
                   extra={"candidate_branches": [flow._branch(entry)]})
    flow._tick(paths, settings, monkeypatch)
    topic = open_topic_ledger(paths, settings.program).topic(entry["topic_id"])
    campaign = db.campaign(topic["campaign_id"])
    state = json.loads(Path(campaign["workstream_state_path"]).read_text(encoding="utf-8"))
    assert "queued or running remote jobs" in state["precheck_clock"]["excludes"]
    assert "awaiting_remote" in state["precheck_clock"]["pending_remote_jobs"]
    first = db.latest_task(topic["campaign_id"])
    assert "not time waiting for queued remote jobs" in first["objective"]
