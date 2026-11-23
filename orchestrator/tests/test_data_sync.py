"""The shared data checkout is fast-forwarded at tick start only when that is safe."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from openlabs.data_sync import sync_data_checkout


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.test", *args],
                          cwd=str(root), check=True, capture_output=True, text=True).stdout


def _commit(root: Path, name: str, text: str) -> None:
    (root / name).write_text(text)
    _git(root, "add", name)
    _git(root, "commit", "-q", "-m", name)


@pytest.fixture()
def repos(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    monkeypatch.delenv("OPENLABS_DATA_SYNC", raising=False)
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    agent = tmp_path / "agent"
    _git(tmp_path, "clone", "-q", str(origin), str(agent))
    _commit(agent, "registry.yaml", "status: revision_required\n")
    _git(agent, "push", "-q", "origin", "HEAD:main")
    shared = tmp_path / "shared"
    _git(tmp_path, "clone", "-q", str(origin), str(shared))
    # An agent pushes from its own worktree; the shared checkout falls behind.
    _commit(agent, "registry.yaml", "status: ready\n")
    _git(agent, "push", "-q", "origin", "HEAD:main")
    return shared, agent


def test_behind_checkout_is_fast_forwarded(repos) -> None:
    shared, _ = repos
    result = sync_data_checkout(shared)
    assert result["outcome"] == "fast_forwarded" and result["behind"] == 1
    assert (shared / "registry.yaml").read_text() == "status: ready\n"
    assert sync_data_checkout(shared)["outcome"] == "up_to_date"


def test_uncommitted_tracked_change_is_left_alone(repos) -> None:
    shared, _ = repos
    (shared / "registry.yaml").write_text("local edit\n")
    result = sync_data_checkout(shared)
    assert result["outcome"] == "skipped" and result["reason"] == "uncommitted_changes"
    assert result["files"] == ["registry.yaml"]
    assert (shared / "registry.yaml").read_text() == "local edit\n"


def test_untracked_files_do_not_block(repos) -> None:
    shared, _ = repos
    (shared / "receipt.json").write_text("{}")
    assert sync_data_checkout(shared)["outcome"] == "fast_forwarded"


def test_rebase_in_progress_is_left_alone(repos) -> None:
    shared, _ = repos
    marker = Path(_git(shared, "rev-parse", "--git-path", "rebase-merge").strip())
    (shared / marker).mkdir(parents=True)
    head = _git(shared, "rev-parse", "HEAD")
    result = sync_data_checkout(shared)
    assert result == {"outcome": "skipped", "reason": "operation_in_progress:rebase-merge"}
    assert _git(shared, "rev-parse", "HEAD") == head


def test_diverged_history_is_not_merged(repos) -> None:
    shared, _ = repos
    _commit(shared, "local.txt", "local\n")
    head = _git(shared, "rev-parse", "HEAD")
    result = sync_data_checkout(shared)
    assert result["outcome"] == "skipped" and result["reason"] == "diverged"
    assert _git(shared, "rev-parse", "HEAD") == head


def test_detached_head_and_non_checkouts_are_skipped(repos, tmp_path: Path) -> None:
    shared, _ = repos
    _git(shared, "checkout", "-q", "--detach")
    assert sync_data_checkout(shared)["reason"] == "detached_head"
    plain = tmp_path / "plain"
    plain.mkdir()
    assert sync_data_checkout(plain) == {"outcome": "skipped", "reason": "not_a_git_checkout"}
    # A directory inside a checkout is not the checkout itself.
    assert sync_data_checkout(shared / ".git")["reason"] == "not_a_git_checkout"


def test_fetch_failure_is_a_skip(repos) -> None:
    shared, _ = repos
    _git(shared, "remote", "set-url", "origin", str(shared.parent / "missing.git"))
    result = sync_data_checkout(shared)
    assert result["outcome"] == "skipped" and result["reason"] == "fetch_failed"


def test_tick_reports_the_sync_without_an_error(tmp_path: Path, monkeypatch) -> None:
    from openlabs import engine
    from openlabs.config import FactorySettings, WorkspacePaths

    seen = []
    monkeypatch.setattr("openlabs.data_sync.sync_data_checkout",
                        lambda root: seen.append(root) or {"outcome": "skipped",
                                                           "reason": "uncommitted_changes"})
    code = Path(__file__).resolve().parents[2]
    paths = WorkspacePaths(workspace=tmp_path, code=code, data=tmp_path / "data",
                           artifacts=tmp_path / "artifacts", database=tmp_path / "db",
                           database_file=tmp_path / "db" / "live" / "factory.sqlite")
    report = engine.tick(paths, FactorySettings(launch_jobs=False))
    assert seen == [paths.data]
    assert report.to_dict()["data_sync"] == {"outcome": "skipped", "reason": "uncommitted_changes"}
    assert report.errors == []
