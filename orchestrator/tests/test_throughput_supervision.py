"""Adaptive launch ceiling, measured host load, the ailab load summary and the
read-only ``program utilization`` view."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
import test_quota_routing as qr
import test_research_program_flow as flow
from openlabs import budget as budget_control
from openlabs import utilization
from openlabs.config import BudgetSettings
from test_utilization_routing import _gpt_resets_soon_claude_later, _reading, _window

NOW = qr.NOW
GPT = qr.GPT


# --------------------------------------------------------------------------- adaptive ceiling


def _adaptive(tmp_path, *, used=0.1, resets_in=timedelta(days=1), adaptive=True):
    _, db = qr._setup(tmp_path)
    settings = replace(qr._settings(utilization_target=0.9),
                       budget=BudgetSettings(max_parallel_agents=8, adaptive_parallel=adaptive,
                                             adaptive_step=2))
    for runner in ("worker_gpt", "worker_claude"):
        _reading(db, settings, runner, _window("seven_day", used, minutes=10_080,
                                               resets_in=resets_in))
    return db, settings


def _limit(db, settings, *, active=1, runnable=10, host=None, now=NOW):
    router = budget_control.QuotaRouter.build(db, settings, now=now)
    return utilization.adaptive_launch_limit(
        db, settings, router, hard=budget_control.launch_limit(db, settings),
        active=active, runnable=runnable, host=host or {"cpu_fraction": 0.1,
                                                         "memory_fraction": 0.2},
        now=now,
    )


def test_adaptive_ceiling_ramps_smoothly_to_the_hard_ceiling(tmp_path) -> None:
    db, settings = _adaptive(tmp_path)
    limits = [_limit(db, settings)["limit"] for _ in range(5)]
    assert limits == [3, 5, 7, 8, 8]
    last = _limit(db, settings)
    assert last["limited_by"] == "hard_ceiling" and last["limit"] == 8
    history = json.loads(db.meta_get(utilization.ADAPTIVE_HISTORY_KEY))
    assert [item["limit"] for item in history][-3:] == [8, 8, 8]


def test_adaptive_ceiling_steps_down_on_host_load_and_holds_without_work(tmp_path) -> None:
    db, settings = _adaptive(tmp_path)
    db.update_meta({utilization.ADAPTIVE_KEY: "6"})
    high = _limit(db, settings, host={"cpu_fraction": 0.85, "memory_fraction": 0.2})
    assert high["limit"] == 5 and high["limited_by"] == "host_resources"
    idle = _limit(db, settings, runnable=0)
    assert idle["limit"] == 5 and idle["limited_by"] == "demand"
    near = _limit(db, settings, host={"cpu_fraction": 0.75, "memory_fraction": 0.2})
    assert near["limit"] == 5 and near["limited_by"] == "host_resources"


def test_adaptive_ceiling_drops_when_every_provider_is_over_pace(tmp_path) -> None:
    # 70% used one day into the week: at that pace every window runs out early.
    db, settings = _adaptive(tmp_path, used=0.7, resets_in=timedelta(days=6))
    db.update_meta({utilization.ADAPTIVE_KEY: "6"})
    entry = _limit(db, settings)
    assert entry["limit"] == 5 and entry["limited_by"] == "quota_pacing"
    assert set(entry["quota_signal"].values()) <= {"over", "unavailable"}


def test_adaptive_ceiling_never_exceeds_a_halved_hard_ceiling(tmp_path) -> None:
    db, settings = _adaptive(tmp_path)
    db.update_meta({utilization.ADAPTIVE_KEY: "8", budget_control.EFFECTIVE_PARALLEL_KEY: "4"})
    assert _limit(db, settings)["limit"] == 4


def test_static_ceiling_when_adaptive_is_off(tmp_path) -> None:
    db, settings = _adaptive(tmp_path, adaptive=False)
    entry = _limit(db, settings, active=0, runnable=0)
    assert entry["limit"] == 8 and entry["reasons"] == ["static_ceiling"]
    assert db.meta_get(utilization.ADAPTIVE_KEY) is None


def test_tick_reports_the_ceiling_and_launches_against_it(tmp_path, monkeypatch) -> None:
    paths = flow._paths(tmp_path)
    flow._install_program(paths)
    db = flow._db(paths)
    settings = replace(flow._settings(max_concurrent_scouts=2, scout_min_interval_hours=0),
                       budget=BudgetSettings(max_parallel_agents=4, adaptive_parallel=True))
    report = flow._tick(paths, settings, monkeypatch)
    payload = report.to_dict()
    assert payload["parallel_limit"]["adaptive"] is True
    assert payload["effective_parallel"] == payload["parallel_limit"]["limit"]
    assert len(report.launched) <= payload["parallel_limit"]["limit"]
    assert "host_usage" in payload
    assert payload["balance"]


def test_host_usage_reads_cgroup_files_and_excludes_page_cache(tmp_path) -> None:
    root = tmp_path / "cg"
    root.mkdir()
    (root / "cpu.max").write_text("400000 100000\n")
    (root / "cpu.stat").write_text("usage_usec 1000000\nuser_usec 1\n")
    (root / "memory.current").write_text(str(10 * 1024**3))
    (root / "memory.max").write_text(str(20 * 1024**3))
    (root / "memory.stat").write_text(f"anon 1\nfile {6 * 1024**3}\n")
    _, db = qr._setup(tmp_path)
    first = utilization.host_usage(db, now=NOW, record=True, root=root)
    assert first["cpu_limit"] == 4.0 and "cpu_fraction" not in first
    assert first["memory_fraction"] == pytest.approx(0.2)
    (root / "cpu.stat").write_text("usage_usec 121000000\n")
    second = utilization.host_usage(db, now=NOW + timedelta(seconds=60), record=False, root=root)
    assert second["cpu_fraction"] == pytest.approx(0.5)


# --------------------------------------------------------------------------- ailab


def _job(queue: Path, job_id: str, state: str, cpus: int, memory: int, *,
         ready: bool | None = None, withdrawn: bool = False) -> None:
    directory = queue / "jobs" / job_id
    directory.mkdir(parents=True)
    (directory / "status.json").write_text(json.dumps({"job_id": job_id, "state": state}))
    (directory / "request.json").write_text(json.dumps(
        {"resources": {"cpu_threads": cpus, "memory_mib": memory, "wall_seconds": 60}}
    ))
    # The bridge keeps READY while a job is queued or running and drops it at the end.
    if ready if ready is not None else state in {"queued", "running"}:
        (directory / "READY").write_text(job_id + "\n")
    if withdrawn:
        (directory / "WITHDRAWN.by-submitter").write_text(job_id + "\n")


def test_ailab_summary_counts_active_jobs_and_their_budgets(tmp_path) -> None:
    runner = budget_control._lab_runner_module()
    queue = tmp_path / "queue"
    _job(queue, "a", "running", 4, 16_000)
    _job(queue, "b", "queued", 2, 8_000)
    _job(queue, "c", "succeeded", 8, 60_000)
    (queue / "jobs" / "broken").mkdir()
    summary = runner.remote_queue_summary(queue, {"cpu_threads": 8, "memory_mib": 64_000})
    assert summary["running"] == 1 and summary["queued"] == 1
    assert summary["declared_cpu_threads"] == 6 and summary["declared_memory_mib"] == 24_000
    assert summary["cpu_fraction"] == 0.75
    assert runner.remote_queue_summary(tmp_path / "missing", {}) is None


def test_ailab_summary_ignores_withdrawn_undispatchable_and_terminal_jobs(tmp_path) -> None:
    runner = budget_control._lab_runner_module()
    queue = tmp_path / "queue"
    _job(queue, "live", "running", 8, 32_768)
    # Withdrawn by the submitter: still "queued" in status.json, READY gone or not.
    _job(queue, "w1", "queued", 4, 8_192, ready=False, withdrawn=True)
    _job(queue, "w2", "queued", 1, 4_096, ready=True, withdrawn=True)
    _job(queue, "w3", "running", 4, 16_384, withdrawn=True)
    # Queued without READY: the bridge never dispatches it.
    _job(queue, "orphan", "queued", 2, 2_048, ready=False)
    for state in ("succeeded", "failed"):
        _job(queue, f"done-{state}", state, 8, 60_000, ready=False)
        _job(queue, f"ready-{state}", state, 8, 60_000, ready=True)
    summary = runner.remote_queue_summary(queue, {"cpu_threads": 8, "memory_mib": 62_961})
    assert summary["running"] == 1 and summary["queued"] == 0
    assert summary["declared_cpu_threads"] == 8 and summary["declared_memory_mib"] == 32_768
    assert summary["cpu_fraction"] == 1.0
    assert summary["ignored"] == {"withdrawn": 3, "not_dispatchable": 1}


def test_task_notice_shows_ailab_load_and_omits_it_when_unreadable(tmp_path, monkeypatch):
    runner = budget_control._lab_runner_module()
    code = tmp_path / "code"
    (code / "config").mkdir(parents=True)
    (code / "config" / "remote-compute.json").write_text(json.dumps(
        {"enabled": True, "cpu_threads": 8, "memory_mib": 62961}
    ))
    queue = tmp_path / "queue"
    _job(queue, "a", "running", 3, 4096)
    monkeypatch.setattr(runner, "remote_queue_root", lambda: queue)
    notice = runner._remote_compute_notice(code, "ai")
    assert "1 job(s) running and 0 queued, declaring 3 CPU(s)" in notice
    assert "nine tenths" in notice
    monkeypatch.setattr(runner, "remote_queue_root", lambda: tmp_path / "nowhere")
    quiet = runner._remote_compute_notice(code, "ai")
    assert "Right now ailab" not in quiet and "nine tenths" in quiet


# --------------------------------------------------------------------------- utilization


def test_utilization_command_is_read_only(tmp_path, monkeypatch, capsys) -> None:
    from openlabs import __main__ as cli

    paths, db = qr._setup(tmp_path)
    settings = replace(qr._settings(utilization_target=0.9),
                       budget=BudgetSettings(max_parallel_agents=8, adaptive_parallel=True))
    _gpt_resets_soon_claude_later(db, settings)
    qr._enqueue(db, "q", "cq", runner="balanced")
    monkeypatch.setattr(budget_control, "current_time", lambda: NOW)
    monkeypatch.setattr(cli, "workspace_paths", lambda _workspace=None: paths)
    monkeypatch.setattr(cli, "load_settings", lambda _paths: settings)
    monkeypatch.setattr(utilization, "gpu_usage", lambda: None)
    database = paths.database_file
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    assert cli.main(["program", "utilization", "--no-gpu"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert payload["schema_version"] == utilization.UTILIZATION_SCHEMA
    assert payload["tasks"]["queued"]["worker/unrouted"]["count"] == 1
    gpt = payload["providers"][GPT]
    assert gpt["abundance"] == pytest.approx(1.75, rel=1e-3)
    assert gpt["windows"]["seven_day"]["projected_at_reset_vs_target"].endswith("/ 0.90")
    assert {"cpu_limit", "target"} <= set(payload["host"])
    assert payload["parallel"]["hard_ceiling"] == 8
    items = {row["item"]: row for row in payload["balance"]}
    assert {"quota:anthropic", "quota:openai-codex", "agents"} <= set(items)
    assert items["quota:anthropic"]["below_target"] is True


def test_cli_parses_program_utilization() -> None:
    from openlabs.__main__ import _parser

    args = _parser().parse_args(["program", "utilization", "--history", "3"])
    assert args.program_command == "utilization" and args.history == 3

