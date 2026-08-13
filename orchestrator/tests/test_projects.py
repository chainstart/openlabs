from __future__ import annotations

import json
from pathlib import Path

from openlabs.attempts import prepare_attempt_workspace
from openlabs.config import FactorySettings, WorkspacePaths
from openlabs.contracts import atomic_write_json
from openlabs.db import FactoryDB
from openlabs.engine import _validate_bound_protocol, tick
from openlabs.projects import load_project


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


def _generic_project(paths: WorkspacePaths, *, valid_state: bool = True) -> tuple[Path, Path]:
    lab = paths.code / "labs" / "test"
    skill = lab / "skills" / "test-protocol"
    protocol_script = lab / "protocols" / "validate.py"
    skill.mkdir(parents=True)
    protocol_script.parent.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: test-protocol\ndescription: Test protocol.\n---\n",
        encoding="utf-8",
    )
    protocol_script.write_text(
        "import argparse,json\n"
        "from pathlib import Path\n"
        "p=argparse.ArgumentParser(); p.add_argument('--project'); "
        "p.add_argument('--state'); p.add_argument('--mode'); a=p.parse_args()\n"
        "state=json.loads(Path(a.state).read_text())\n"
        "errors=[] if state.get('valid') is True else ['state rejected by test protocol']\n"
        "print(json.dumps({'valid':not errors,'errors':errors}))\n"
        "raise SystemExit(1 if errors else 0)\n",
        encoding="utf-8",
    )
    atomic_write_json(
        lab / "lab.json",
        {
            "schema_version": "openlabs.lab.v1",
            "lab_id": "test",
            "domain": "test-domain",
            "runner": {"command": ["{python}", "runner.py"]},
            "skills": [
                {
                    "skill_id": "test-protocol",
                    "path": "skills/test-protocol/SKILL.md",
                }
            ],
            "protocols": [
                {
                    "protocol_id": "test-protocol",
                    "primary_skill": "test-protocol",
                    "validator": {
                        "command": [
                            "{python}",
                            "protocols/validate.py",
                            "--project",
                            "{project_config}",
                            "--state",
                            "{workstream_state}",
                            "--mode",
                            "{validation_mode}",
                        ]
                    },
                }
            ],
        },
    )
    state = paths.data / "workspaces" / "test-domain" / "stream-one" / "state.json"
    atomic_write_json(state, {"valid": valid_state})
    project = (
        paths.data
        / "workspaces"
        / "test-domain"
        / "projects"
        / "project-one"
        / "project.json"
    )
    atomic_write_json(
        project,
        {
            "schema_version": "openlabs.project.v1",
            "project_id": "project-one",
            "domain": "test-domain",
            "status": "active",
            "objective": "Run a protocol-selected research project.",
            "protocol": {
                "id": "test-protocol",
                "primary_skill": "test-protocol",
            },
            "execution": {
                "checkpoint_policy": "role_boundary_or_budget",
                "continue_across_protocol_phases": True,
                "default_session_mode": "resume",
                "fresh_session_boundaries": [
                    "independent_replication",
                    "portfolio_review",
                ],
            },
            "workstreams": [
                {
                    "workstream_id": "stream-one",
                    "state_path": "../../stream-one/state.json",
                    "startup": "active",
                    "priority": 23,
                }
            ],
        },
    )
    return project, state


def test_generic_project_config_selects_protocol_without_core_changes(tmp_path) -> None:
    paths = _paths(tmp_path)
    project_path, state_path = _generic_project(paths)

    project = load_project(project_path)
    report = tick(paths, FactorySettings(auto_continue=False, launch_jobs=False))
    db = FactoryDB(paths.database_file)
    campaign = db.campaign("stream-one")

    assert project.protocol_id == "test-protocol"
    assert project.execution.continue_across_protocol_phases is True
    assert report.production_synced == ["stream-one"]
    assert campaign is not None
    assert campaign["project_config_path"] == str(project_path)
    assert campaign["workstream_state_path"] == str(state_path)
    assert campaign["protocol_id"] == "test-protocol"
    assert campaign["primary_skill"] == "test-protocol"
    assert json.loads(campaign["execution_policy_json"])[
        "continue_across_protocol_phases"
    ] is True
    assert _validate_bound_protocol(paths, campaign) == ()


def test_protocol_rejection_isolated_before_campaign_sync(tmp_path) -> None:
    paths = _paths(tmp_path)
    _generic_project(paths, valid_state=False)

    report = tick(paths, FactorySettings(auto_continue=False, launch_jobs=False))
    db = FactoryDB(paths.database_file)

    assert report.production_synced == []
    assert db.campaign("stream-one") is None
    assert any("state rejected by test protocol" in error for error in report.errors)


def test_protocol_commit_gate_validates_the_private_attempt_state(tmp_path) -> None:
    paths = _paths(tmp_path)
    _generic_project(paths)
    tick(paths, FactorySettings(auto_continue=False, launch_jobs=False))
    db = FactoryDB(paths.database_file)
    db.enqueue_task(
        task_id="mutate-state",
        campaign_id="stream-one",
        domain="test-domain",
        task_type="research_continue",
        objective="Mutate only the private workstream state.",
        skill_path="test-protocol",
    )
    task = db.claim_next_task(owner="test", lease_seconds=60)
    assert task is not None
    campaign = db.campaign("stream-one")
    assert campaign is not None
    attempt = prepare_attempt_workspace(paths, task, campaign)
    staged_state = Path(str(attempt.map_path(campaign["workstream_state_path"])))
    atomic_write_json(staged_state, {"valid": False})

    assert _validate_bound_protocol(paths, campaign) == ()
    errors = _validate_bound_protocol(paths, campaign, attempt_workspace=attempt)
    assert errors == ("state rejected by test protocol",)


def test_database_v7_migrates_generic_project_bindings(tmp_path) -> None:
    db = FactoryDB(tmp_path / "factory.sqlite")
    db.initialize()
    db.register_campaign("stream", domain="test-domain", title="Stream")
    changed = db.configure_project_campaign(
        "stream",
        project_config_path="/data/project.json",
        workstream_state_path="/data/state.json",
        protocol_id="test-protocol",
        primary_skill="test-protocol",
        execution_policy={"default_session_mode": "resume"},
        priority=7,
    )

    assert changed is True
    campaign = db.campaign("stream")
    assert campaign["continuous"] == 1
    assert campaign["project_config_path"] == "/data/project.json"
    with db.connect() as connection:
        version = connection.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()[0]
    assert version == "7"


def test_legacy_and_generic_bindings_replace_each_other_cleanly(tmp_path) -> None:
    db = FactoryDB(tmp_path / "factory.sqlite")
    db.initialize()
    db.register_campaign("stream", domain="test-domain", title="Stream")
    db.configure_project_campaign(
        "stream",
        project_config_path="/data/project.json",
        workstream_state_path="/data/state.json",
        protocol_id="test-protocol",
        primary_skill="test-protocol",
        execution_policy={"default_session_mode": "resume"},
    )

    db.configure_continuous_campaign(
        "stream",
        production_plan_path="/data/legacy-plan.json",
        production_lane_path="/data/legacy-lane.json",
    )
    legacy = db.campaign("stream")
    assert legacy["project_config_path"] is None
    assert legacy["workstream_state_path"] is None
    assert legacy["protocol_id"] is None
    assert legacy["execution_policy_json"] == "{}"

    db.configure_project_campaign(
        "stream",
        project_config_path="/data/project.json",
        workstream_state_path="/data/state.json",
        protocol_id="test-protocol",
        primary_skill="test-protocol",
        execution_policy={"default_session_mode": "resume"},
    )
    generic = db.campaign("stream")
    assert generic["production_plan_path"] is None
    assert generic["production_lane_path"] is None
