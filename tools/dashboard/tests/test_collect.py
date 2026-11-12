from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from openlabs_dashboard.collect import build_state


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_build_state_combines_registry_site_projects_and_factory(tmp_path: Path) -> None:
    data = tmp_path / "openlabs-data"
    _write(data / "registry/settings.yaml", "journal_target_policy:\n  venue_eligibility:\n    escalation: {journal_tiers: [1, 2]}\n")
    _write(data / "registry/journal-rejections.json", json.dumps({"updated_at": "2026-11-07T00:00:00+00:00",
                                                                   "rejections": [], "active_submissions": []}))
    _write(data / "registry/papers/20261108-biology-genetics-x.yaml", """
paper_id: 20261108-biology-genetics-x
title: Real cohort result
domain: biology
subdomain: genetics
created_at: '2026-11-08'
target_journal: Journal of Example Genetics
target_journal_tier: 2
data_sources:
  - {name: UK Biobank, kind: clinical_or_cohort_registry, source: 'https://www.ukbiobank.ac.uk/', version: '2026', license_or_access: approved application}
key_findings: [Effect replicates in an external cohort.]
""")
    _write(data / "papers/20261108-biology-genetics-x/manuscript/main.tex",
           "\\begin{abstract}An abstract.\\end{abstract}\\section{Data availability} See https://doi.org/10.1/x.\\end{document}")
    site = [{"paper_id": "20261108-biology-genetics-x", "lifecycle_status": "active",
             "submission_attempts": [{"id": "a", "journal_name": "Journal of Example Genetics", "status": "under_review",
                                      "submitted_at": "2026-11-08T00:00:00Z"}],
             "review_rounds": [], "submission_events": []}]
    snapshot = tmp_path / "maintenance/x/website-details.json"
    _write(snapshot, json.dumps(site))
    project = data / "workspaces/biology/projects/cohort"
    _write(project / "project.json", json.dumps({"project_id": "cohort", "objective": "Find replicable signal", "status": "active"}))
    _write(project / "README.md", "# Cohort study\n\nUses https://example.org/data for analysis.\n")
    db = tmp_path / "openlabs-database/live/factory.sqlite"
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as c:
        c.execute("create table campaigns (campaign_id, domain, title, status, state_path, updated_at, agent_seconds_used)")
        c.execute("create table tasks (task_id, campaign_id, objective, status, priority, created_at)")
        c.execute("insert into campaigns values ('c1','biology','t','active',?, '2026-11-08', 7200)",
                  ("/home/x/openlabs-data/workspaces/biology/projects/cohort",))

    state = build_state(tmp_path)
    paper = state["papers"][0]
    assert paper["stage"] == "在审"
    assert paper["venue"]["level"] == "中科院2区" and paper["venue"]["escalation"] is True
    assert paper["data_sources_registered"] and paper["key_findings"] == ["Effect replicates in an external cohort."]
    assert paper["abstract"] == "An abstract." and "https://doi.org/10.1/x" in paper["data_links"]
    assert state["submission_source"]["kind"] == "snapshot"
    proj = state["projects"][0]
    assert proj["title"] == "Cohort study" and proj["objective"] == "Find replicable signal"
    assert proj["campaigns"] == [{"id": "c1", "status": "active", "agent_hours": 2.0}]
    assert "https://example.org/data" in proj["data_links"]
    assert state["monitor"]["active_submissions"] == 1


def test_frozen_paper_is_shown_as_stopped() -> None:
    from openlabs_dashboard.collect import paper_stage

    writing = {"record_status": "paper_workspace", "writing_release": {"status": "revision_required"}}
    assert paper_stage(writing, [], None) == "写作中"
    frozen = {"record_status": "frozen", "freeze_decision": {"status": "frozen"},
              "writing_release": {"status": "blocked"}}
    assert paper_stage(frozen, [], None) == "已停止"
    assert paper_stage({"freeze_decision": {"status": "frozen"}}, [], None) == "已停止"
