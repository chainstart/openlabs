"""``program init-instance``: a separate instance on shared data/artifact repositories."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from openlabs import engine
from openlabs.__main__ import main
from openlabs.config import load_settings, workspace_paths
from openlabs.db import FactoryDB
from openlabs.instance import PRESETS, init_instance, render_toml

CODE_ROOT = Path(__file__).resolve().parents[2]


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "openlabs").symlink_to(CODE_ROOT)
    return workspace


@pytest.fixture(autouse=True)
def _no_instance(monkeypatch):
    for name in ("OPENLABS_INSTANCE", "OPENLABS_DATABASE_ROOT", "OPENLABS_CONFIG_FILE",
                 "OPENLABS_REQUIRE_INSTANCE"):
        monkeypatch.delenv(name, raising=False)


def test_dry_run_writes_nothing_and_write_is_idempotent(tmp_path) -> None:
    workspace = _workspace(tmp_path)
    instance_dir = tmp_path / "instances" / "cc-sg"
    paths = workspace_paths(workspace)

    dry = init_instance(paths, name="cc-sg", instance_dir=instance_dir)
    assert dry["dry_run"] and {a["status"] for a in dry["actions"]} == {"create"}
    assert not instance_dir.exists()
    assert sorted(p.name for p in workspace.iterdir()) == ["openlabs"]

    written = init_instance(paths, name="cc-sg", instance_dir=instance_dir, write=True)
    assert {a["status"] for a in written["actions"]} == {"create"}
    again = init_instance(paths, name="cc-sg", instance_dir=instance_dir, write=True)
    assert {a["status"] for a in again["actions"]} <= {"exists", "unchanged"}

    # Five program projects (no mathematics), all where only this instance looks.
    domains = sorted(Path(p).parts[-6] for p in written["projects"])
    assert domains == ["ai", "biology", "materials", "physics", "quant"]
    # A full preset does not overwrite the existing TOML without --update-config.
    full = init_instance(paths, name="cc-sg", instance_dir=instance_dir, preset="full",
                         write=True)
    assert [a["status"] for a in full["actions"] if a["path"].endswith("openlabs.toml")] == [
        "differs"]
    updated = init_instance(paths, name="cc-sg", instance_dir=instance_dir, preset="full",
                            write=True, update_config=True)
    assert [a["status"] for a in updated["actions"] if a["path"].endswith("openlabs.toml")] == [
        "update"]
    assert list(instance_dir.glob("openlabs.toml.*.bak"))


def test_generated_instance_is_self_consistent_and_isolated(tmp_path, monkeypatch) -> None:
    workspace = _workspace(tmp_path)
    instance_dir = tmp_path / "instances" / "cc-sg"
    init_instance(workspace_paths(workspace), name="cc-sg", instance_dir=instance_dir,
                  write=True)
    environment = dict(
        line.split("=", 1)
        for line in (instance_dir / "instance.env").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    paths = workspace_paths()
    settings = load_settings(paths)

    assert paths.database_file == instance_dir / "database" / "live" / "factory.sqlite"
    assert paths.data == workspace / "openlabs-data"
    assert settings.program.enabled and settings.program.max_active_topics == 5
    assert not settings.program.auto_handoff and not settings.program.auto_release
    assert not settings.assets.enabled and not settings.assets.retrospective_enabled
    assert settings.budget.max_parallel_agents == 3
    assert sorted(settings.runners) == sorted(
        ["lead_gpt", "lead_claude", "worker_gpt", "worker_claude", "light_gpt", "light_claude"])
    assert "wsl_math" not in settings.program.compute_locations
    assert settings.program.ledger_path == "registry/instances/cc-sg/topic-ledger.json"
    # The repository settings file is untouched and still has every switch off.
    repository = tomllib.loads((CODE_ROOT / "config" / "openlabs.toml").read_text("utf-8"))
    assert repository["program"]["enabled"] is False and "runners" not in repository

    # The instance discovers and binds exactly its five program projects.
    db = FactoryDB(paths.database_file)
    db.initialize()
    report = engine.TickReport()
    bindings = engine._active_project_workstreams(paths, report)
    assert report.errors == []
    assert len(bindings) == 10 and all(b.project_id.startswith("cc-sg-") for b in bindings)
    # The default instance (any orchestrator without OPENLABS_INSTANCE) sees none of them.
    for name in environment:
        monkeypatch.delenv(name)
    default_paths = workspace_paths(workspace)
    assert default_paths.project_config_paths() == []
    assert engine._active_project_workstreams(default_paths, engine.TickReport()) == []


def test_cli_defaults_to_dry_run_and_refuses_overlapping_directories(tmp_path, capsys) -> None:
    workspace = _workspace(tmp_path)
    assert main(["--workspace", str(workspace), "program", "init-instance",
                 "--instance-dir", str(tmp_path / "inst")]) == 0
    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    assert not (tmp_path / "inst").exists()
    assert main(["--workspace", str(workspace), "program", "init-instance",
                 "--instance-dir", str(workspace / "openlabs-data" / "x")]) == 1
    assert "overlaps the data repository" in capsys.readouterr().err


def test_tick_refuses_without_an_instance_when_one_is_required(tmp_path, monkeypatch, capsys):
    workspace = _workspace(tmp_path)
    monkeypatch.setenv("OPENLABS_REQUIRE_INSTANCE", "1")
    monkeypatch.setattr("openlabs.__main__.load_local_environment", lambda: None)
    monkeypatch.setattr("openlabs.__main__.ensure_proxy_ready",
                        lambda **_k: pytest.fail("must refuse before the preflight"))
    assert main(["--workspace", str(workspace), "tick"]) == 78
    assert "OPENLABS_REQUIRE_INSTANCE" in capsys.readouterr().err
    assert not (workspace / "openlabs-database").exists()


def test_presets_differ_only_in_the_later_switches() -> None:
    observe, full = PRESETS["observe"], PRESETS["full"]
    assert observe["program.enabled"] and full["program.enabled"]
    assert [key for key in observe if observe[key] != full[key]] == [
        "program.assets.enabled", "program.assets.retrospective_enabled",
        "program.auto_handoff", "program.auto_release"]


def test_render_toml_round_trips_nested_tables() -> None:
    document = {"a": 1, "b": {"c": [1, 2], "d": {"e": "x y", "claude-fable-5-2": ["w"]}},
                "f": {"g": {"h": True}}}
    assert tomllib.loads(render_toml(document, "# header")) == document
