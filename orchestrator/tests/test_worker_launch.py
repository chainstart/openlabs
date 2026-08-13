from __future__ import annotations

import subprocess

from openlabs.config import WorkspacePaths
from openlabs.engine import _launch_worker, _worker_unit_name


def test_systemd_tick_launches_worker_in_transient_service(tmp_path, monkeypatch) -> None:
    paths = WorkspacePaths(
        workspace=tmp_path,
        code=tmp_path / "openlabs",
        data=tmp_path / "openlabs-data",
        artifacts=tmp_path / "openlabs-artifacts",
        database=tmp_path / "openlabs-database",
        database_file=tmp_path / "openlabs-database" / "live" / "factory.sqlite",
    )
    paths.code.mkdir()
    task = {
        "task_id": "route:node",
        "current_attempt_id": "attempt-1",
        "cpu_threads": 2,
        "memory_mib": 4096,
        "scratch_mib": 4096,
    }
    calls: list[list[str]] = []

    monkeypatch.setenv("INVOCATION_ID", "tick-invocation")
    monkeypatch.setattr("openlabs.engine.shutil.which", lambda name: "/usr/bin/systemd-run")

    def fake_run(command, **kwargs):
        calls.append(list(command))
        if command[0] == "systemctl":
            return subprocess.CompletedProcess(command, 0, stdout="4321\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("openlabs.engine.subprocess.run", fake_run)
    pid = _launch_worker(
        task=task,
        paths=paths,
        job_path=tmp_path / "job.json",
        log_path=tmp_path / "worker.log",
        environment={
            "PYTHONPATH": "/code",
            "OPENLABS_SECRET": "must-not-appear-in-argv",
            "INVOCATION_ID": "old-invocation",
        },
    )

    unit = _worker_unit_name(task)
    assert pid == 4321
    assert calls[0][0] == "/usr/bin/systemd-run"
    assert f"--unit={unit}" in calls[0]
    assert "--slice=openlabs-workers.slice" in calls[0]
    assert "--property=PartOf=openlabs-workers.target" in calls[0]
    assert "--property=MemoryHigh=4096M" in calls[0]
    assert not any(item.startswith("--property=MemoryMax=") for item in calls[0])
    assert "--property=CPUQuota=200%" in calls[0]
    assert "--property=TasksMax=64" in calls[0]
    assert "--property=OOMPolicy=stop" in calls[0]
    assert "--setenv=OPENLABS_SECRET" in calls[0]
    assert "--setenv=INVOCATION_ID" not in calls[0]
    assert all("must-not-appear-in-argv" not in token for token in calls[0])
