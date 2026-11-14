"""Research-line paper templates: card fields, intake check and scout packets."""

from __future__ import annotations

import json
from pathlib import Path

import test_research_lines as lines
import test_research_program_flow as flow
from openlabs.contracts import validate_topic_card
from openlabs.program import open_topic_ledger
from openlabs.research_lines import line_summary, line_templates, load_research_lines

SEARCH = {
    "queries": ['"Janus MoSSe" anode sodium adsorption diffusion barrier'],
    "databases": ["Crossref", "arXiv"],
    "searched_at": "2026-11-12",
    "findings": "No report of Na adsorption on this monolayer; closest is Li on MoSSe.",
}


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
    card = lines._line_card(n)
    card.update({"paper_template": "2d-anode", "occupancy_search": dict(SEARCH)})
    card.update(override)
    return card


def test_template_fields_are_optional_and_checked_when_present() -> None:
    assert validate_topic_card(lines._line_card(), current_year=flow.YEAR).valid
    assert validate_topic_card(_templated_card(), current_year=flow.YEAR).valid
    series = _templated_card(series={"members": ["MoSSe", "WSSe", "MoSTe"],
                                     "shared_pipeline": "one GPAW adsorption/NEB workflow"})
    assert validate_topic_card(series, current_year=flow.YEAR).valid

    no_search = _templated_card()
    no_search.pop("occupancy_search")
    # Template fields are evidence for the gate: gaps are warnings, not rejections
    # (topic-a6968ee3 was rejected for a missing occupancy_search on 2026-11-12).
    check = validate_topic_card(no_search, current_year=flow.YEAR)
    assert check.valid and any(e.startswith("occupancy_search is missing")
                               for e in check.warnings)
    thin = _templated_card(occupancy_search={**SEARCH, "queries": []})
    assert "occupancy_search.queries must be a non-empty array" in validate_topic_card(
        thin, current_year=flow.YEAR).warnings
    lone = _templated_card(series={"members": ["MoSSe"], "shared_pipeline": "x"})
    assert any("at least 2 adjacent systems" in e
               for e in validate_topic_card(lone, current_year=flow.YEAR).warnings)
    unshared = _templated_card(series={"members": ["MoSSe", "WSSe"]})
    assert "series.shared_pipeline is missing (what the members share)" in validate_topic_card(
        unshared, current_year=flow.YEAR).warnings
    lineless = flow._card(paper_template="2d-anode", occupancy_search=dict(SEARCH))
    assert "paper_template needs research_line" in validate_topic_card(
        lineless, current_year=flow.YEAR).warnings


def test_line_summary_carries_the_templates(tmp_path) -> None:
    paths = flow._paths(tmp_path)
    document = load_research_lines(_templates_file(paths))
    summary = line_summary(document, lines.LINE)
    assert [item["id"] for item in summary["paper_templates"]] == ["2d-anode"]
    assert "minimum_content" not in summary["paper_templates"][0]  # compact
    assert line_templates(document, lines.LINE)[0]["minimum_content"]
    assert line_summary(document, "unknown")["paper_templates"] == []


def test_scout_packet_names_templates_and_intake_checks_the_template_id(tmp_path, monkeypatch):
    paths = flow._paths(tmp_path)
    flow._install_program(paths)
    lines._make_line_project(paths)
    _templates_file(paths)
    db = flow._db(paths)
    settings = flow._settings()
    unknown = _templated_card(1, paper_template="perovskite-pv")
    _, report = flow._scout_round(paths, db, settings, monkeypatch, [_templated_card(0), unknown])
    assert report.errors == []
    with db.connect() as connection:
        scout = dict(connection.execute(
            "SELECT * FROM tasks WHERE task_type='topic_scout' LIMIT 1").fetchone())
    assert "paper_templates" in scout["objective"]
    packet = json.loads(Path(scout["input_path"]).read_text(encoding="utf-8"))
    assert packet["research_line_summary"]["paper_templates"][0]["id"] == "2d-anode"
    registered = report.program["cards_registered"]
    # An unknown template id is a warning the gate sees, not a rejection.
    assert len(registered) == 2 and report.program["rejected_cards"] == []
    ledger = open_topic_ledger(paths, settings.program)
    topics = [ledger.topic(item["topic_id"]) for item in registered]
    assert {topic["status"] for topic in topics} == {"proposed"}
    flagged = [topic for topic in topics if topic.get("card_check")]
    assert len(flagged) == 1
    assert any("'perovskite-pv' is not a paper_templates id" in e
               for e in flagged[0]["card_check"]["warnings"])
    admission = flow._admission_task(db)
    assert "paper_template" in admission["objective"]
    entries = flow._packet(admission)["topic_cards"]
    assert {entry["card"]["paper_template"] for entry in entries} == {"2d-anode", "perovskite-pv"}
    assert [bool(entry.get("card_check")) for entry in entries].count(True) == 1


def test_queued_template_scouts_copy_entries_and_admission_is_a_checklist(tmp_path, monkeypatch):
    """A template with a candidate_queue sends scouts to the queue and the gate to a checklist."""

    paths = flow._paths(tmp_path)
    flow._install_program(paths)
    lines._make_line_project(paths)
    path = _templates_file(paths)
    queue = tmp_path / "queue" / "queue.json"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "        minimum_content: [phonon stability of the host]\n",
            "        minimum_content: [phonon stability of the host]\n"
            f"        candidate_queue: {queue}\n",
        ),
        encoding="utf-8",
    )
    document = load_research_lines(path)
    assert line_summary(document, lines.LINE)["paper_templates"][0]["candidate_queue"] == str(
        queue)
    db = flow._db(paths)
    settings = flow._settings()
    queued = _templated_card(0, candidate_queue_entry={
        "queue": str(queue), "entry_id": "TIC 1", "novelty_verdict": "unreported"})
    assert validate_topic_card(queued, current_year=flow.YEAR).valid
    _, report = flow._scout_round(paths, db, settings, monkeypatch, [queued])
    assert report.errors == []
    with db.connect() as connection:
        scout = dict(connection.execute(
            "SELECT * FROM tasks WHERE task_type='topic_scout' LIMIT 1").fetchone())
    assert f"2d-anode: {queue}" in scout["objective"]
    assert "copy each entry's `card_fields`" in scout["objective"]
    admission = flow._admission_task(db)
    assert "admission is a checklist" in admission["objective"]
    entry = flow._packet(admission)["topic_cards"][0]
    assert entry["card"]["candidate_queue_entry"]["entry_id"] == "TIC 1"


def test_scout_without_queue_keeps_the_open_template_search(tmp_path, monkeypatch):
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
    assert "candidate_queue" not in scout["objective"]
