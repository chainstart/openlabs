"""Concurrent attempts on one campaign merge at promotion instead of being discarded."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from openlabs.attempts import (
    AttemptWorkspaceError,
    begin_attempt_promotion,
    finalize_attempt_promotion,
    prepare_attempt_workspace,
    promote_attempt_workspace,
    recover_attempt_promotion,
)
from openlabs.config import WorkspacePaths
from openlabs.contracts import atomic_write_json
from openlabs.db import FactoryDB


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


def _campaign(paths: WorkspacePaths) -> tuple[FactoryDB, Path]:
    root = paths.data / "workspaces" / "ai" / "program"
    root.mkdir(parents=True)
    atomic_write_json(root / "project.json", {"project_id": "p", "notes": {"a": 1}})
    atomic_write_json(root / "scout_state.json", {"rounds": {}, "version": 1})
    (root / "log.md").write_text("# log\n", encoding="utf-8")
    db = FactoryDB(paths.database_file)
    db.initialize()
    db.register_campaign("program", domain="ai", title="Program", state_path=str(root))
    return db, root


def _attempt(paths: WorkspacePaths, db: FactoryDB, task_id: str):
    # Parallel attempts on one campaign (several scouts of one program project).
    task = {"task_id": task_id, "campaign_id": "program", "domain": "ai",
            "current_attempt_id": f"attempt-{task_id}"}
    return prepare_attempt_workspace(paths, task, db.campaign("program") or {})


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_parallel_scouts_with_disjoint_files_both_land(tmp_path) -> None:
    paths = _paths(tmp_path)
    db, root = _campaign(paths)
    first = _attempt(paths, db, "scout-1")
    second = _attempt(paths, db, "scout-2")
    (first.campaign_root / "scout" / "one").mkdir(parents=True)
    (first.campaign_root / "scout" / "one" / "card.json").write_text("{}\n", encoding="utf-8")
    (second.campaign_root / "scout" / "two").mkdir(parents=True)
    (second.campaign_root / "scout" / "two" / "card.json").write_text("[]\n", encoding="utf-8")

    promote_attempt_workspace(first)
    # Before the merge this raised "Canonical campaign changed while the attempt was running".
    metadata = promote_attempt_workspace(second)

    assert metadata["status"] == "committed"
    assert (root / "scout" / "one" / "card.json").is_file()
    assert (root / "scout" / "two" / "card.json").is_file()
    assert metadata["promotion_merge"]["canonical_moved"] is True
    assert metadata["promotion_merge"]["refused"] == []


def test_shared_json_merges_key_by_key_and_conflicting_keys_keep_canonical(tmp_path) -> None:
    paths = _paths(tmp_path)
    db, root = _campaign(paths)
    first = _attempt(paths, db, "scout-1")
    second = _attempt(paths, db, "scout-2")
    atomic_write_json(first.campaign_root / "scout_state.json",
                      {"rounds": {"one": "done"}, "version": 2})
    atomic_write_json(second.campaign_root / "scout_state.json",
                      {"rounds": {"two": "done"}, "version": 3})
    atomic_write_json(second.campaign_root / "project.json",
                      {"project_id": "p", "notes": {"a": 1, "b": 2}})

    promote_attempt_workspace(first)
    metadata = promote_attempt_workspace(second)

    state = _read(root / "scout_state.json")
    assert state["rounds"] == {"one": "done", "two": "done"}
    assert state["version"] == 2  # both changed it: the canonical value stays
    assert _read(root / "project.json")["notes"] == {"a": 1, "b": 2}
    refused = metadata["promotion_merge"]["refused"]
    assert [item["path"] for item in refused] == ["scout_state.json"]
    assert refused[0]["conflicts"] == ["scout_state.json:version"]
    assert refused[0]["partially_merged"] is True
    # The attempt's own version is kept for inspection.
    assert _read(Path(refused[0]["attempt_copy"]))["version"] == 3


def test_append_only_text_keeps_both_tails(tmp_path) -> None:
    paths = _paths(tmp_path)
    db, root = _campaign(paths)
    first = _attempt(paths, db, "scout-1")
    second = _attempt(paths, db, "scout-2")
    (first.campaign_root / "log.md").write_text("# log\n- one\n", encoding="utf-8")
    (second.campaign_root / "log.md").write_text("# log\n- two\n", encoding="utf-8")

    promote_attempt_workspace(first)
    metadata = promote_attempt_workspace(second)

    assert (root / "log.md").read_text(encoding="utf-8") == "# log\n- one\n- two\n"
    assert metadata["promotion_merge"]["content_merged"] == ["log.md"]


def test_same_line_text_edit_is_a_refused_conflict_and_the_rest_lands(tmp_path) -> None:
    paths = _paths(tmp_path)
    db, root = _campaign(paths)
    first = _attempt(paths, db, "scout-1")
    second = _attempt(paths, db, "scout-2")
    (first.campaign_root / "log.md").write_text("# first\n", encoding="utf-8")
    (second.campaign_root / "log.md").write_text("# second\n", encoding="utf-8")
    (second.campaign_root / "receipt.json").write_text("{\"ok\": true}\n", encoding="utf-8")

    promote_attempt_workspace(first)
    metadata = promote_attempt_workspace(second)

    assert (root / "log.md").read_text(encoding="utf-8") == "# first\n"
    assert _read(root / "receipt.json") == {"ok": True}
    refused = metadata["promotion_merge"]["refused"]
    assert refused[0]["path"] == "log.md" and refused[0]["partially_merged"] is False


def test_unchanged_canonical_promotes_exactly_as_before(tmp_path) -> None:
    paths = _paths(tmp_path)
    db, root = _campaign(paths)
    attempt = _attempt(paths, db, "scout-1")
    atomic_write_json(attempt.campaign_root / "scout_state.json", {"rounds": {"x": 1}})

    metadata = promote_attempt_workspace(attempt)

    assert metadata["promotion_merge"] == {
        "canonical_moved": False, "content_merged": [], "refused": [],
    }
    assert _read(root / "scout_state.json") == {"rounds": {"x": 1}}


def test_crash_recovery_after_a_merged_exchange_restores_the_moved_canonical(tmp_path) -> None:
    paths = _paths(tmp_path)
    db, root = _campaign(paths)
    first = _attempt(paths, db, "scout-1")
    second = _attempt(paths, db, "scout-2")
    (first.campaign_root / "one.json").write_text("{}\n", encoding="utf-8")
    (second.campaign_root / "two.json").write_text("{}\n", encoding="utf-8")
    promote_attempt_workspace(first)

    begin_attempt_promotion(second)
    assert (root / "two.json").is_file()
    metadata = recover_attempt_promotion(second, database_committed=False)

    assert metadata["status"] == "quarantined"
    assert (root / "one.json").is_file()  # the other scout's committed work survives
    assert not (root / "two.json").exists()
    with pytest.raises(AttemptWorkspaceError):
        finalize_attempt_promotion(second)
