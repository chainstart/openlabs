"""Research-line paper templates: summary metadata and old-line queue_candidates injection."""

from __future__ import annotations

import json
from pathlib import Path

import test_research_lines as lines
import test_research_program_flow as flow
from openlabs.research_lines import line_summary, line_templates, load_research_lines


def _templates_file(paths, status: str = "ready") -> Path:
    path = paths.data / "registry" / "research-lines.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "schema_version: openlabs.research_lines.v1\n"
        "lines:\n"
        f"  - id: {lines.LINE}\n"
        "    host_domain: ai\n"
        "    title: test line\n"
        "    paper_templates:\n"
        "      - id: 2d-anode\n"
        "        name: 2D monolayer as alkali-ion anode\n"
        "        paradigm: adsorption, diffusion, voltage and capacity of one host\n"
        "        feasible: true\n"
        "        per_paper_cost: {ailab_core_hours: '250-500', agent_hours: '10-16'}\n"
        "        minimum_content: [phonon stability of the host]\n"
        "    environment:\n"
        f"      status: {status}\n"
        "      sop: sop.md\n",
        encoding="utf-8",
    )
    return path


def _templated_card(n: int = 0, **override) -> dict:
    return lines._line_card(n, **override)


def test_line_summary_carries_the_templates(tmp_path) -> None:
    paths = flow._paths(tmp_path)
    document = load_research_lines(_templates_file(paths))
    summary = line_summary(document, lines.LINE)
    assert [item["id"] for item in summary["paper_templates"]] == ["2d-anode"]
    assert "minimum_content" not in summary["paper_templates"][0]
    assert line_templates(document, lines.LINE)[0]["minimum_content"]
    assert line_summary(document, "unknown")["paper_templates"] == []


def test_queued_template_injects_queue_candidates_into_scout_packet(tmp_path, monkeypatch):
    paths = flow._paths(tmp_path)
    flow._install_program(paths)
    lines._make_line_project(paths)
    path = _templates_file(paths)
    queue = tmp_path / "queue" / "queue.json"
    queue.parent.mkdir(parents=True, exist_ok=True)
    queue.write_text(json.dumps({"candidates": [{"entry_id": "TIC 1", "rank": 1}]}), encoding="utf-8")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "        minimum_content: [phonon stability of the host]\n",
            "        minimum_content: [phonon stability of the host]\n"
            f"        candidate_queue: {queue}\n",
        ),
        encoding="utf-8",
    )
    document = load_research_lines(path)
    assert line_summary(document, lines.LINE)["paper_templates"][0]["candidate_queue"] == str(queue)
    db = flow._db(paths)
    settings = flow._settings()
    queued = _templated_card(0, queue_entry_id="TIC 1")
    _, report = flow._scout_round(paths, db, settings, monkeypatch, [queued])
    assert report.errors == []
    with db.connect() as connection:
        scout = dict(connection.execute(
            "SELECT * FROM tasks WHERE task_type='topic_scout' LIMIT 1").fetchone())
    packet = json.loads(Path(scout["input_path"]).read_text(encoding="utf-8"))
    assert [c["entry_id"] for c in packet["queue_candidates"]] == ["TIC 1"]
    assert "queue_candidates" in scout["objective"]
    admission = flow._admission_task(db)
    entry = flow._packet(admission)["topic_proposals"][0]
    assert entry["proposal"]["queue_entry_id"] == "TIC 1"


def test_scout_without_queue_omits_queue_candidates(tmp_path, monkeypatch):
    paths = flow._paths(tmp_path)
    flow._install_program(paths)
    lines._make_line_project(paths)
    _templates_file(paths)
    db = flow._db(paths)
    _, report = flow._scout_round(paths, db, flow._settings(), monkeypatch, [_templated_card(0)])
    assert report.errors == []
    with db.connect() as connection:
        scout = dict(connection.execute(
            "SELECT * FROM tasks WHERE task_type='topic_scout' LIMIT 1").fetchone())
    packet = json.loads(Path(scout["input_path"]).read_text(encoding="utf-8"))
    assert "queue_candidates" not in packet
