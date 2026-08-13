from __future__ import annotations

import json
from pathlib import Path

import pytest

from openlabs.config import FactorySettings, WorkspacePaths
from openlabs.contracts import atomic_write_json, sha256_file
from openlabs.db import FactoryDB
from openlabs.engine import (
    TickReport,
    _replenish_continuous_campaign,
)
from openlabs.portfolio import (
    reconcile_pending_portfolio_review,
    spawn_candidate_workstreams,
)


def _paths(tmp_path: Path) -> WorkspacePaths:
    paths = WorkspacePaths(
        workspace=tmp_path,
        code=Path(__file__).resolve().parents[2],
        data=tmp_path / "openlabs-data",
        artifacts=tmp_path / "openlabs-artifacts",
        database=tmp_path / "openlabs-database",
        database_file=tmp_path / "openlabs-database" / "live" / "factory.sqlite",
    )
    paths.ensure_runtime_directories()
    return paths


def _portfolio(paths: WorkspacePaths) -> tuple[Path, Path, Path]:
    project_root = paths.data / "workspaces" / "math" / "projects" / "rh"
    review_root = paths.data / "workspaces" / "math" / "rh-review"
    review_state = review_root / "review_state.json"
    index_path = project_root / "research_index.json"
    atomic_write_json(
        review_state,
        {
            "schema_version": "openlabs.math_research_workspace.v1",
            "project_id": "rh",
            "workstream_id": "rh-review",
            "mode": "portfolio_review",
            "status": "active",
            "research_log": [],
            "verification_receipts": [],
        },
    )
    atomic_write_json(
        paths.artifacts / "result-1.json",
        {"summary": "A bounded obstruction was found.", "claims": []},
    )
    atomic_write_json(
        index_path,
        {
            "schema_version": "openlabs.project_research_index.v1",
            "project_id": "rh",
            "results": [
                {
                    "result_id": "research-result-1",
                    "campaign_id": "rh-free",
                    "agent_role": "researcher",
                    "task_type": "research_continue",
                    "status": "succeeded",
                    "summary": "A bounded obstruction was found.",
                    "claims": [],
                    "result_path": str(paths.artifacts / "result-1.json"),
                    "sha256": "a" * 64,
                }
            ],
        },
    )
    project_path = project_root / "project.json"
    atomic_write_json(
        project_path,
        {
            "schema_version": "openlabs.project.v1",
            "project_id": "rh",
            "domain": "math",
            "status": "active",
            "objective": "Freely research RH.",
            "protocol": {"id": "autonomous-math", "primary_skill": "math-autonomous-research"},
            "research_index": {
                "path": "research_index.json",
                "source_campaign_ids": ["rh-free"],
            },
            "portfolio": {
                "allow_dynamic_candidate_workstreams": True,
                "candidate_state_template": {
                    "schema_version": "openlabs.project_workstream.v1",
                    "mode": "candidate_maturation",
                    "status": "active",
                    "research_log": [],
                    "verification_receipts": [],
                },
            },
            "workstreams": [
                {
                    "workstream_id": "rh-review",
                    "state_path": "../../rh-review/review_state.json",
                    "agent_role": "reviewer",
                    "session_mode": "fresh",
                    "continuation": "review_on_new_results",
                    "spawn_candidate_workstreams": True,
                }
            ],
        },
    )
    return project_path, review_state, index_path


def _review_campaign(paths: WorkspacePaths) -> tuple[FactoryDB, dict]:
    project_path, review_state, _ = _portfolio(paths)
    db = FactoryDB(paths.database_file)
    db.initialize()
    result_path = paths.artifacts / "result-1.json"
    db.register_campaign("rh-free", domain="math", title="RH free")
    db.enqueue_task(
        task_id="research-result-1",
        campaign_id="rh-free",
        domain="math",
        task_type="research_continue",
        objective="Produce one research checkpoint.",
        agent_role="researcher",
        session_mode="fresh",
    )
    with db.connect() as connection:
        connection.execute(
            """
            UPDATE tasks SET status='succeeded', result_path=?, result_sha256=?
            WHERE task_id='research-result-1'
            """,
            (str(result_path), sha256_file(result_path)),
        )
    db.register_campaign(
        "rh-review",
        domain="math",
        title="RH review",
        state_path=str(review_state.parent),
    )
    db.configure_project_campaign(
        "rh-review",
        project_config_path=str(project_path),
        workstream_state_path=str(review_state),
        protocol_id="autonomous-math",
        primary_skill="math-autonomous-research",
        execution_policy={},
        project_id="rh",
        workstream_policy={
            "continuation": "review_on_new_results",
            "default_agent_role": "reviewer",
            "default_session_mode": "fresh",
            "review_every_results": 1,
            "spawn_candidate_workstreams": True,
            "objective": "Judge the new results independently.",
        },
    )
    campaign = db.campaign("rh-review")
    assert campaign is not None
    return db, campaign


def test_new_results_schedule_a_blank_portfolio_reviewer(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    db, campaign = _review_campaign(paths)
    report = TickReport()

    _replenish_continuous_campaign(
        db,
        paths,
        FactorySettings(),
        report,
        campaign,
    )

    task = db.latest_task("rh-review")
    assert task is not None
    assert task["task_type"] == "portfolio_review"
    assert task["agent_role"] == "reviewer"
    assert task["session_mode"] == "fresh"
    packet = Path(str(task["input_path"]))
    assert packet.is_file()
    assert packet.is_relative_to(paths.artifacts / "portfolio-control")
    assert "research-result-1" in packet.read_text(encoding="utf-8")
    rebuilt = json.loads(
        (
            paths.data
            / "workspaces"
            / "math"
            / "projects"
            / "rh"
            / "research_index.json"
        ).read_text(encoding="utf-8")
    )
    assert rebuilt["results"][0]["sha256"] == sha256_file(
        paths.artifacts / "result-1.json"
    )


def test_reviewer_candidate_spawns_parallel_continuous_research(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    db, campaign = _review_campaign(paths)
    report = TickReport()
    _replenish_continuous_campaign(db, paths, FactorySettings(), report, campaign)
    review_task = db.latest_task("rh-review")
    assert review_task is not None
    review_result = paths.artifacts / "review-result.json"
    atomic_write_json(review_result, {"summary": "reviewed"})

    spawned = spawn_candidate_workstreams(
        db,
        paths,
        FactorySettings(),
        campaign,
        review_task,
        {
            "candidate_branches": [
                {
                    "candidate_id": "sharp-obstruction",
                    "title": "Sharp obstruction",
                    "objective": "Prove the maximal obstruction theorem.",
                    "rationale": "The reviewed result isolates a stable interface.",
                    "source_result_ids": ["research-result-1"],
                }
            ]
        },
        result_path=review_result,
    )

    candidate_ids = [
        campaign_id
        for campaign_id in spawned.campaign_ids
        if campaign_id.startswith("rh-candidate-sharp-obstruction")
    ]
    assert len(candidate_ids) == 1
    candidate = db.campaign(candidate_ids[0])
    assert candidate is not None
    assert candidate["continuous"] == 1
    assert db.latest_task(candidate_ids[0])["agent_role"] == "researcher"
    assert db.campaign("rh-review")["continuous"] == 1


def test_completed_candidate_is_not_reseeded_by_the_control_plane(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    db, campaign = _review_campaign(paths)
    report = TickReport()
    _replenish_continuous_campaign(db, paths, FactorySettings(), report, campaign)
    review_task = db.latest_task("rh-review")
    assert review_task is not None
    review_result = atomic_write_json(paths.artifacts / "review-result.json", {"summary": "x"})
    spawned = spawn_candidate_workstreams(
        db,
        paths,
        FactorySettings(),
        campaign,
        review_task,
        {
            "candidate_branches": [
                {
                    "candidate_id": "falsified-branch",
                    "title": "Falsified branch",
                    "objective": "Test and abandon this branch if false.",
                    "rationale": "A precise falsification target exists.",
                    "source_result_ids": ["research-result-1"],
                }
            ]
        },
        result_path=review_result,
    )
    candidate_id = spawned.campaign_ids[0]
    candidate = db.campaign(candidate_id)
    assert candidate is not None
    state_path = Path(str(candidate["workstream_state_path"]))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["status"] = "completed"
    atomic_write_json(state_path, state)
    with db.connect() as connection:
        connection.execute(
            "UPDATE tasks SET status='succeeded' WHERE campaign_id=?",
            (candidate_id,),
        )

    _replenish_continuous_campaign(
        db,
        paths,
        FactorySettings(),
        TickReport(),
        db.campaign(candidate_id),
    )

    candidate = db.campaign(candidate_id)
    assert candidate is not None and candidate["status"] == "production_paused"
    assert db.task_count(candidate_id) == 1


def test_failed_candidate_materialization_retries_before_cursor_advance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _paths(tmp_path)
    db, campaign = _review_campaign(paths)
    _replenish_continuous_campaign(
        db,
        paths,
        FactorySettings(),
        TickReport(),
        campaign,
    )
    review_task = db.latest_task("rh-review")
    assert review_task is not None
    result = atomic_write_json(
        paths.artifacts / "review-result.json",
        {
            "candidate_branches": [
                {
                    "candidate_id": candidate_id,
                    "title": candidate_id,
                    "objective": f"Deepen {candidate_id}.",
                    "rationale": "The reviewer selected it.",
                    "source_result_ids": ["research-result-1"],
                }
                for candidate_id in ("branch-one", "branch-two")
            ]
        },
    )
    with db.connect() as connection:
        connection.execute(
            """
            UPDATE tasks SET status='succeeded', result_path=?, result_sha256=?
            WHERE task_id=?
            """,
            (str(result), sha256_file(result), review_task["task_id"]),
        )
    original_enqueue = db.enqueue_task
    candidate_calls = 0

    def flaky_enqueue(**kwargs):
        nonlocal candidate_calls
        if str(kwargs.get("task_id") or "").startswith("candidate:"):
            candidate_calls += 1
            if candidate_calls == 2:
                raise OSError("synthetic materialization interruption")
        return original_enqueue(**kwargs)

    monkeypatch.setattr(db, "enqueue_task", flaky_enqueue)
    with pytest.raises(OSError, match="synthetic materialization"):
        reconcile_pending_portfolio_review(db, paths, FactorySettings(), campaign)
    packet = json.loads(Path(str(review_task["input_path"])).read_text(encoding="utf-8"))
    assert not Path(str(packet["cursor_path"])).exists()

    monkeypatch.setattr(db, "enqueue_task", original_enqueue)
    reconciled = reconcile_pending_portfolio_review(db, paths, FactorySettings(), campaign)

    assert reconciled.reconciled is True
    candidates = [
        item
        for item in db.campaigns()
        if str(item["campaign_id"]).startswith("rh-candidate-branch-")
    ]
    assert len(candidates) == 2
    assert all(db.task_count(str(item["campaign_id"])) == 1 for item in candidates)
    candidate_records = [
        item for item in db.research_records() if item["kind"] == "candidate"
    ]
    assert len(candidate_records) == 2
    cursor = json.loads(Path(str(packet["cursor_path"])).read_text(encoding="utf-8"))
    assert cursor["reviewed_result_ids"] == ["research-result-1"]
    assert len(cursor["content_sha256"]) == 64


def test_corrupt_review_cursor_fails_closed_instead_of_hiding_results(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    db, campaign = _review_campaign(paths)
    _replenish_continuous_campaign(
        db,
        paths,
        FactorySettings(),
        TickReport(),
        campaign,
    )
    review_task = db.latest_task("rh-review")
    assert review_task is not None
    packet = json.loads(Path(str(review_task["input_path"])).read_text(encoding="utf-8"))
    cursor_path = Path(str(packet["cursor_path"]))
    atomic_write_json(
        cursor_path,
        {
            "schema_version": "openlabs.portfolio_review_cursor.v1",
            "reviewed_result_ids": ["research-result-1"],
            "content_sha256": "0" * 64,
        },
    )
    with db.connect() as connection:
        connection.execute("DELETE FROM tasks WHERE campaign_id='rh-review'")

    with pytest.raises(ValueError, match="cursor hash mismatch"):
        _replenish_continuous_campaign(
            db,
            paths,
            FactorySettings(),
            TickReport(),
            db.campaign("rh-review"),
        )
