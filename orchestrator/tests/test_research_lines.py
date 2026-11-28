"""Research lines: line-keyed scouting, environment readiness and paper_profile inheritance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import test_parallel_program as parallel
import test_research_program_flow as flow
from openlabs import engine
from openlabs.config import LineSettings, SupplySettings, load_program_settings
from openlabs.program import open_topic_ledger
from openlabs.program_flow import LAST_SCOUT_KEY, schedule_scouts
from openlabs.projects import workstream_policy
from openlabs.research_lines import environment_status, load_research_lines

NOW = parallel.NOW
LINE = "ml-evaluation-protocols"


def _line_card(n: int = 0, receipt_sha: str = flow.RECEIPT_SHA, **override) -> dict:
    card = flow._card(n, receipt_sha)
    card["research_line"] = LINE
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


# --------------------------------------------------------------------------- direction file


def test_direction_file_reader_reports_environment_status(tmp_path) -> None:
    paths = flow._paths(tmp_path)
    document = load_research_lines(_lines_file(paths, "ready"))
    assert environment_status(document, LINE) == "ready"
    assert environment_status(document, "other") == "unknown_line"
    assert environment_status(None, LINE) == "unreadable"
    settings = load_program_settings({"lines": {"a": {"mode": "full"}, "b": {"mode": "full"}}})
    assert settings.research_lines == ("a", "b")
    assert settings.research_lines_path == "registry/research-lines.yaml"


def test_repository_direction_file_is_consistent_with_the_instance_lines() -> None:
    from openlabs.instance import RESEARCH_LINES

    data = flow.CODE_ROOT.parent / "openlabs-data" / "registry" / "research-lines.yaml"
    if not data.is_file():
        return
    document = load_research_lines(data)
    declared = {item["id"]: item["host_domain"] for item in document["lines"]}
    assert declared == dict(RESEARCH_LINES)


# --------------------------------------------------------------------------- scouting


def _line_program(tmp_path, line_ids, **program):
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
    lines = dict(program.pop("lines", {}))
    if line_ids:
        for line in line_ids:
            lines.setdefault(line, LineSettings(mode="full"))
    settings = flow._settings(lines=lines, **program)
    engine._sync_active_projects(db, paths, settings, engine.TickReport())
    return paths, db, settings


def test_scouting_rotates_by_line_and_skips_projects_without_a_line(tmp_path) -> None:
    lines = ("engineering-vvuq", "astro-photometry")
    paths, db, settings = _line_program(
        tmp_path, lines,
        supply=SupplySettings(max_concurrent_scouts=5, candidate_pool_size=8, scout_min_interval_hours=1),
    )
    scheduled, reason = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    assert sorted(item.research_line for item in scheduled) == sorted(lines)
    assert {item.domain for item in scheduled} == {"physics"}
    assert scheduled[0].research_line == "engineering-vvuq"
    assert reason == "scout_in_flight"
    stamps = db.meta_items(LAST_SCOUT_KEY + ":")
    assert set(stamps) == set(lines)
    packets = [json.loads(Path(t["input_path"]).read_text()) for t in parallel._scouts(db)]
    assert {p["research_line"] for p in packets} == set(lines)
    assert all(p["research_line_summary"]["environment_status"] == "unreadable" for p in packets)
    tasks = parallel._scouts(db)
    assert all("research line" in t["objective"] for t in tasks)
    parallel._finish(db, [item.task_id for item in scheduled])
    again, reason = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    assert again == [] and reason == "scout_min_interval"


def test_without_research_lines_rotation_stays_by_domain(tmp_path) -> None:
    paths, db, settings = _line_program(
        tmp_path, (),
        supply=SupplySettings(max_concurrent_scouts=5, candidate_pool_size=20, scout_min_interval_hours=0),
    )
    scheduled, _ = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    assert {item.domain for item in scheduled} == {"ai", "physics", "quant"}


def test_backlog_of_one_line_does_not_count_against_a_sibling(tmp_path):
    from openlabs.program import propose_topic
    from openlabs.program_flow import report_scheduling_counts

    lines = ("astro-photometry", "engineering-vvuq")
    paths, db, settings = _line_program(
        tmp_path, lines,
        supply=SupplySettings(max_concurrent_scouts=2, candidate_pool_size=2, scout_min_interval_hours=0),
        lines={line: LineSettings(slots=4) for line in lines},
    )
    ledger = open_topic_ledger(paths, settings.program)
    for n, line in enumerate((lines[0], lines[0], None, None)):
        propose_topic(ledger, {"topic_id": f"p{n}", "domain": "physics", "question": f"q{n}",
                               "data_sources": [f"s{n}"]},
                      db=db, decided_by="test", metadata={"research_line": line})
    scheduled, _ = schedule_scouts(db, paths, settings, lead_short=False, now=NOW)
    assert [item.research_line for item in scheduled] == [lines[1]]
    report = engine.TickReport()
    report_scheduling_counts(db, paths, settings, report)
    assert report.program["by_line"][lines[0]]["proposed"] == 2
    assert report.program["by_line"][lines[1]]["scouts_in_flight"] == 1
    assert report.program["legacy_by_domain"]["physics"]["proposed"] == 2


# --------------------------------------------------------------------------- intake and gate


def _line_setup(tmp_path, status: str):
    paths = flow._paths(tmp_path)
    flow._install_program(paths)
    _make_line_project(paths)
    _lines_file(paths, status)
    db = flow._db(paths)
    settings = flow._settings()
    return paths, db, settings


def test_line_project_proposals_carry_the_line_and_the_packet_names_it(tmp_path, monkeypatch):
    paths, db, settings = _line_setup(tmp_path, "ready")
    card = _line_card(0, research_line="some-other-line")
    _, admission, report = flow._to_admission(paths, db, settings, monkeypatch, [card])
    assert report.errors == []
    registered = report.program["cards_registered"]
    assert len(registered) == 1, report.program
    topic = open_topic_ledger(paths, settings.program).topic(registered[0]["topic_id"])
    assert topic["research_line"] == LINE
    packet = flow._packet(admission)
    assert packet["research_lines"][LINE]["environment_status"] == "ready"
    assert packet["topic_proposals"][0]["proposal"]["research_line"] == LINE
    labels = {item["label"] for item in packet["read_resources"]}
    assert "research-lines" in labels


def test_a_line_without_ready_environment_gets_no_scout_and_no_review(tmp_path, monkeypatch):
    from openlabs.program_flow import intake_proposal, schedule_topic_admission
    from openlabs.projects import load_project

    paths, db, settings = _line_setup(tmp_path, "not_ready")
    report = flow._tick(paths, settings, monkeypatch)
    assert report.program["scouts_scheduled"] == []
    assert report.program["scout_blocked"] == "research_line_environment_not_ready"
    assert report.program["lines_environment_not_ready"] == {LINE: "not_ready"}
    assert parallel._scouts(db) == []

    project = load_project(paths.data / "workspaces" / "ai" / "projects" / "research-program"
                           / "project.json")
    outcome = intake_proposal(db, paths, settings, project, _line_card(0), decided_by="manual:t",
                              provider="human", source_task_id=None)
    assert outcome["status"] == "proposed", outcome
    with db.connect() as connection:
        admission_campaign = dict(connection.execute(
            "SELECT * FROM campaigns WHERE campaign_id LIKE '%admission%' LIMIT 1").fetchone())
    schedule = schedule_topic_admission(db, paths, settings, admission_campaign, epoch=1)
    assert schedule.task_id is None
    assert schedule.reason == "research_line_environment_not_ready"

    _lines_file(paths, "ready")
    schedule = schedule_topic_admission(db, paths, settings, admission_campaign, epoch=1)
    assert schedule.task_id is not None


@pytest.mark.parametrize("field, short", [(None, None), ("reliability", "phm"), ("medicine", "ecg")])
def test_ready_line_admits_with_kill_test_milestone_and_paper_profile(tmp_path, monkeypatch, field, short):
    paths, db, settings = _line_setup(tmp_path, "ready")
    profile = {"field": field, "line_short_name": short} if field else None
    if profile:
        lines = paths.data / "registry" / "research-lines.yaml"
        lines.write_text(lines.read_text().replace(
            "    host_domain: ai\n",
            f"    host_domain: ai\n    field: {field}\n    line_short_name: {short}\n",
        ))
    _, admission, _ = flow._to_admission(paths, db, settings, monkeypatch, [_line_card(0)])
    entry = flow._packet(admission)["topic_proposals"][0]
    flow._complete(db, paths, admission["task_id"], extra={"reviews": [flow._review(entry)]})
    report = flow._tick(paths, settings, monkeypatch)
    assert report.program["admission_decisions"][0]["outcome"] == "admitted"
    topic = open_topic_ledger(paths, settings.program).topic(entry["topic_id"])
    assert topic["status"] == "active"
    campaign = db.campaign(topic["campaign_id"])
    state = json.loads(Path(campaign["workstream_state_path"]).read_text(encoding="utf-8"))
    assert Path(campaign["state_path"]) == paths.data / "workspaces" / "lines" / LINE / topic["campaign_id"]
    assert state["research_line"] == LINE
    assert state["milestone"] == "kill_test"
    first = db.latest_task(topic["campaign_id"])
    assert "Milestone 1 (Kill Test)" in first["objective"]
    assert workstream_policy(campaign).get("paper_profile") == profile

    lines = paths.data / "registry" / "research-lines.yaml"
    original = _lines_file(paths, "ready").read_text()
    lines.write_text(original.replace(
        "    host_domain: ai\n",
        "    host_domain: ai\n    field: astronomy\n    line_short_name: survey\n", 1,
    ))
    task = {**first, "task_type": "paper_write", "skill_path": "openlabs-ai-paper",
            "current_attempt_id": "field-skill-test", "attempt": 1}
    attempt = engine.prepare_attempt_workspace(paths, task, campaign)
    output = engine.attempt_output_path(attempt, task)
    output.parent.mkdir(parents=True, exist_ok=True)
    skill = paths.code / "workflows/paper/skills/openlabs-ai-paper/SKILL.md"
    spec = engine._write_task_spec(
        paths, task, attempt_workspace=attempt, lab_id="ai",
        manifest_path=paths.code / "labs/ai/lab.json", skill_path=skill,
        output_path=output, wall_seconds=60, campaign=campaign,
    )
    job = json.loads(spec.read_text())
    assert job.get("paper_profile") == profile
    skills = job["runtime_policy"]["skills"]
    if field:
        assert f"$openlabs-{field}-paper" in skills
    assert ("$openlabs-ai-paper" in skills) == (field is None)


def test_materialization_keeps_a_persisted_legacy_workspace(tmp_path, monkeypatch):
    from openlabs.portfolio import _candidate_campaign_id

    paths, db, settings = _line_setup(tmp_path, "ready")
    _, admission, _ = flow._to_admission(paths, db, settings, monkeypatch, [_line_card()])
    packet = flow._packet(admission)
    entry = packet["topic_proposals"][0]
    campaign_id = _candidate_campaign_id(packet["project_id"], entry["topic_id"])
    legacy = paths.data / "workspaces" / "ai" / campaign_id
    legacy.mkdir(parents=True)
    evidence = legacy / "evidence.txt"
    evidence.write_text("persisted reference")
    db.register_campaign(campaign_id, domain="ai", title="Existing topic", state_path=str(legacy))
    flow._complete(db, paths, admission["task_id"], extra={"reviews": [flow._review(entry)]})
    report = flow._tick(paths, settings, monkeypatch)
    assert report.errors == []
    topic = open_topic_ledger(paths, settings.program).topic(entry["topic_id"])
    assert topic["campaign_id"] == campaign_id and topic["status"] == "active"
    campaign = db.campaign(campaign_id)
    assert Path(campaign["workstream_state_path"]) == legacy / "research_state.json"
    assert evidence.read_text() == "persisted reference"
    assert not (paths.data / "workspaces" / "lines" / LINE / campaign_id).exists()
