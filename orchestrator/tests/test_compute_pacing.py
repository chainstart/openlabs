"""Topic intake and compute submission paced by compute capacity (2026-11-18).

After the 2026-11-16 restart 9 topics were admitted in 10 hours and their owners each
queued tens to hundreds of profile jobs; ailab (8 threads) had 21 jobs queued whose
declared threads were 11x its capacity. The backlog gate holds new scouts, admissions
and materializations while the queues are backlogged; each topic may keep at most
``campaign_compute_threads`` declared threads in the queues, enforced at submission.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from openlabs import engine, local_compute, owner, program_flow, remote_compute, utilization
from openlabs.config import load_program_settings
from openlabs.program_flow import run_program_pipeline, schedule_scouts
from test_research_program_flow import _db, _install_program, _paths, _settings, _tick

CODE_ROOT = Path(__file__).resolve().parents[2]


def _job(root: Path, job_id: str, *, state: str = "queued", cpus: int = 4,
         campaign: str | None = None, ready: bool = True, withdrawn: bool = False) -> Path:
    directory = root / "jobs" / job_id
    directory.mkdir(parents=True)
    (directory / "request.json").write_text(json.dumps(
        {"job_id": job_id, "resources": {"cpu_threads": cpus, "memory_mib": 5120,
                                         "wall_seconds": 3600}}))
    (directory / "status.json").write_text(json.dumps({"job_id": job_id, "state": state}))
    if ready:
        (directory / "READY").write_text(job_id)
    if withdrawn:
        (directory / "WITHDRAWN.moved-to-local").write_text("{}")
    if campaign is not None:
        (directory / remote_compute.SUBMITTER_FILE).write_text(
            json.dumps({"campaign_id": campaign}))
    return directory


@pytest.fixture
def queues(tmp_path, monkeypatch):
    remote, local = tmp_path / "remote", tmp_path / "local"
    (remote / "jobs").mkdir(parents=True)
    (local / "jobs").mkdir(parents=True)
    config = tmp_path / "remote-compute.json"
    config.write_text(json.dumps({"enabled": True, "cpu_threads": 8, "memory_mib": 62961,
                                  "max_concurrent_jobs": 8}))
    monkeypatch.setattr(local_compute, "REMOTE_CONFIG_PATH", config)
    monkeypatch.setattr(local_compute, "CONFIG_PATH", tmp_path / "no-local-config.json")
    monkeypatch.setenv("OPENLABS_REMOTE_QUEUE", str(remote))
    monkeypatch.setenv("OPENLABS_LOCAL_QUEUE", str(local))
    monkeypatch.setenv("OPENLABS_LOCAL_MAX_CPUS", "12")
    return remote, local


def test_config_keys_and_defaults() -> None:
    defaults = load_program_settings({})
    assert defaults.compute_backlog_gate is True
    assert defaults.compute_backlog_ratio == 2.0
    assert defaults.compute_backlog_max_queued_jobs == 0
    assert defaults.campaign_compute_threads == 8
    custom = load_program_settings({"compute_backlog_gate": False, "compute_backlog_ratio": 1.5,
                                    "compute_backlog_max_queued_jobs": 6,
                                    "campaign_compute_threads": 0})
    assert (custom.compute_backlog_gate, custom.compute_backlog_ratio,
            custom.compute_backlog_max_queued_jobs, custom.campaign_compute_threads) == (
        False, 1.5, 6, 0)


def test_backlog_counts_queued_threads_of_both_queues_against_capacity(queues) -> None:
    remote, local = queues
    settings = _settings()
    backlog = utilization.compute_backlog(settings)
    assert backlog["backlogged"] is False and backlog["capacity_threads"] == 20
    # The 2026-11-16 shape: ailab running 2 x 4 threads, many queued.
    _job(remote, "a" * 32, state="running")
    _job(remote, "b" * 32, state="running")
    for n in range(10):
        _job(remote, f"{n:x}" * 32)                      # 10 queued x 4 = 40 threads
    _job(remote, "c" * 32, ready=False)                  # not dispatchable: ignored
    _job(remote, "d" * 32, withdrawn=True)               # moved away: ignored
    backlog = utilization.compute_backlog(settings)
    assert (backlog["queued_jobs"], backlog["queued_threads"]) == (10, 40)
    assert backlog["backlogged"] is False                # 40 is not > 2 x 20
    _job(local, "e" * 32, cpus=2)
    backlog = utilization.compute_backlog(settings)
    assert backlog["backlogged"] is True and "42 CPU threads > 2 x capacity 20" in backlog[
        "detail"]
    jobs_only = _settings(compute_backlog_ratio=10.0, compute_backlog_max_queued_jobs=6)
    assert utilization.compute_backlog(jobs_only)["detail"] == "11 jobs queued > 6"
    assert utilization.compute_backlog(_settings(compute_backlog_gate=False)) is None


def test_backlog_holds_scouts_admissions_and_materialization_then_lifts(
        tmp_path, monkeypatch) -> None:
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings()
    backlog = {"backlogged": True, "detail": "queued jobs declare 90 CPU threads > 2 x 20"}
    monkeypatch.setattr(program_flow, "compute_backlog", lambda _settings: dict(backlog))
    assert schedule_scouts(db, paths, settings, lead_short=False) == ([], "compute_backlog")
    report = _tick(paths, settings, monkeypatch)
    assert report.program["scouts_scheduled"] == []
    assert report.program["scout_blocked"] == "compute_backlog"
    assert report.program["compute_backlog"]["backlogged"] is True
    assert {"campaign_id": "", "reason": "compute_backlog",
            "detail": backlog["detail"]} in report.production_blocked
    spawn = program_flow.materialize_waiting_topics(db, paths, settings)
    assert spawn.campaign_ids == ()
    campaign = db.campaign("ai-program-scout") or {"campaign_id": "x"}
    assert program_flow.schedule_topic_admission(
        db, paths, settings, campaign, epoch=1).reason == "compute_backlog"
    # The backlog falls: the next tick schedules the scout again.
    backlog["backlogged"] = False
    report = _tick(paths, settings, monkeypatch)
    assert [item["domain"] for item in report.program["scouts_scheduled"]] == ["ai"]
    assert not [item for item in report.production_blocked
                if item.get("reason") == "compute_backlog"]


def test_pipeline_reports_the_backlog_without_blocking_when_it_is_low(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    _install_program(paths)
    db = _db(paths)
    settings = _settings()
    monkeypatch.setattr(program_flow, "compute_backlog",
                        lambda _settings: {"backlogged": False, "detail": ""})
    report = engine.TickReport()
    report.program = {}
    run_program_pipeline(db, paths, settings, report)
    assert report.program["compute_backlog"] == {"backlogged": False, "detail": ""}
    assert report.production_blocked == []


def test_submit_refuses_a_topic_over_its_thread_limit_and_says_what_to_do(
        queues, tmp_path, capsys) -> None:
    remote, local = queues
    env = {"OPENLABS_CAMPAIGN_ID": "topic-a", "OPENLABS_CAMPAIGN_COMPUTE_THREADS": "8",
           "OPENLABS_REMOTE_QUEUE": str(remote), "OPENLABS_LOCAL_QUEUE": str(local)}
    roots = (remote, local)
    # Nothing in the queues: any single job may go, even one above the limit.
    assert remote_compute.campaign_limit_problem(8, env, roots) is None
    _job(remote, "a" * 32, state="running", campaign="topic-a")
    _job(local, "b" * 32, cpus=2, campaign="topic-a")
    _job(remote, "c" * 32, cpus=8, campaign="topic-b")             # another topic
    _job(remote, "d" * 32, state="succeeded", campaign="topic-a")  # finished
    _job(remote, "e" * 32, withdrawn=True, campaign="topic-a")     # moved to local
    load = remote_compute.campaign_queue_load("topic-a", roots)
    assert (load["jobs"], load["running"], load["queued"], load["cpu_threads"]) == (2, 1, 1, 6)
    assert remote_compute.campaign_limit_problem(2, env, roots) is None
    problem = remote_compute.campaign_limit_problem(4, env, roots)
    assert problem is not None
    assert "2 job(s)" in problem and "declaring 6 CPU thread(s); limit 8" in problem
    assert "Do not retry in a loop" in problem and "awaiting_remote" in problem
    assert "a" * 32 in problem and "coarse first" in problem
    # No topic identity or no limit: no guard (ad-hoc sessions, limit 0).
    assert remote_compute.campaign_limit_problem(64, {}, roots) is None
    assert remote_compute.campaign_limit_problem(
        64, {**env, "OPENLABS_CAMPAIGN_COMPUTE_THREADS": "0"}, roots) is None


def test_cli_submit_refuses_cheaply_and_tags_accepted_jobs(queues, tmp_path, monkeypatch,
                                                          capsys) -> None:
    remote, _local = queues
    source = tmp_path / "job"
    source.mkdir()
    (source / "run.sh").write_text("echo hi\n")
    monkeypatch.setenv("OPENLABS_CAMPAIGN_ID", "topic-a")
    monkeypatch.setenv("OPENLABS_TASK_ID", "owner:1")
    monkeypatch.setenv("OPENLABS_CAMPAIGN_COMPUTE_THREADS", "8")
    argv = ["submit", "--source", str(source), "--cpus", "4", "--memory-mib", "4096",
            "--timeout-seconds", "60", "--backend", "ailab", "--", "bash", "run.sh"]
    assert remote_compute.main(argv) == remote_compute.EXIT_OK
    job_id = capsys.readouterr().out.split("job_id: ")[1].split()[0]
    tag = json.loads((remote / "jobs" / job_id / remote_compute.SUBMITTER_FILE).read_text())
    assert tag["campaign_id"] == "topic-a" and tag["task_id"] == "owner:1"
    request = json.loads((remote / "jobs" / job_id / "request.json").read_text())
    assert "campaign_id" not in request                    # the bridge's request is unchanged
    assert remote_compute.main(argv) == remote_compute.EXIT_OK          # 8 threads in all
    before = sorted(path.name for path in (remote / "jobs").iterdir())
    assert remote_compute.main(argv) == remote_compute.EXIT_CAMPAIGN_LIMIT
    err = capsys.readouterr().err
    assert "per-topic compute limit" in err and "limit 8" in err
    assert sorted(path.name for path in (remote / "jobs").iterdir()) == before


def _lab_runner():
    path = CODE_ROOT / "packages" / "research-core" / "lab_runner.py"
    spec = importlib.util.spec_from_file_location("lab_runner_pacing", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_lab_runner_gives_the_agent_its_topic_and_limit() -> None:
    runner = _lab_runner()
    seat = {"task_id": "owner:1", "campaign_id": "topic-a",
            "owner": {"campaign_compute_threads": 8, "claude_subagent_model": None}}
    env = runner._agent_environment(seat, "codex")
    assert env["OPENLABS_CAMPAIGN_ID"] == "topic-a" and env["OPENLABS_TASK_ID"] == "owner:1"
    assert env["OPENLABS_CAMPAIGN_COMPUTE_THREADS"] == "8"
    plain = runner._agent_environment({"task_id": "t", "campaign_id": "c"}, "claude")
    assert plain["OPENLABS_CAMPAIGN_ID"] == "c"
    assert "OPENLABS_CAMPAIGN_COMPUTE_THREADS" not in plain


def test_brief_lines_show_capacity_snapshot_and_limit(queues) -> None:
    remote, local = queues
    _job(remote, "a" * 32, state="running", campaign="topic-a")
    _job(remote, "b" * 32, campaign="topic-b")
    _job(local, "c" * 32, cpus=2)
    lines = owner.compute_brief_lines(_settings(), "topic-a")
    text = "\n".join(lines)
    assert "ailab 8 thr/61 GB (4 cores" in text and "1.6x slower" in text
    assert "local 3 jobs/12 thr" in text
    assert "ailab 1/4 (+4 running), local 1/2 (+0); this topic 1/4." in text
    assert "<= 8 thr; submit refuses more" in text
    assert "<= " not in "\n".join(owner.compute_brief_lines(
        _settings(campaign_compute_threads=0), "topic-a"))
