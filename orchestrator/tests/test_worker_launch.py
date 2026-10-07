from __future__ import annotations

import subprocess
import pytest

from openlabs.config import WorkspacePaths
from openlabs.engine import _launch_worker, _worker_unit_name


@pytest.mark.parametrize("approved", [True, False])
def test_math_worker_requires_and_inherits_shared_math_reservation(tmp_path, monkeypatch, approved):
    paths = WorkspacePaths(workspace=tmp_path, code=tmp_path / "openlabs",
        data=tmp_path / "data", artifacts=tmp_path / "artifacts",
        database=tmp_path / "database", database_file=tmp_path / "database/factory.sqlite")
    task = {"task_id": "math:node", "current_attempt_id": "attempt-1", "domain": "math",
            "cpu_threads": 2, "memory_mib": 4096, "scratch_mib": 4096}
    calls = []
    monkeypatch.setenv("INVOCATION_ID", "tick")
    monkeypatch.setattr("openlabs.engine.shutil.which", lambda name: "/usr/bin/systemd-run")
    def fake_run(command, **kwargs):
        calls.append(command)
        if "--property=LoadState" in command:
            maximum = 18 * 1024**3 if approved else 34 * 1024**3
            output = f"LoadState=loaded\nMemoryHigh={16 * 1024**3}\nMemoryMax={maximum}\nMemorySwapMax=0\n"
        elif command[0] == "systemctl":
            output = "1234\n"
        else:
            output = ""
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")
    monkeypatch.setattr("openlabs.engine.subprocess.run", fake_run)
    arguments = dict(task=task, paths=paths, job_path=tmp_path / "job.json",
                     log_path=tmp_path / "log", environment={})
    if not approved:
        with pytest.raises(RuntimeError, match="approved shared"):
            _launch_worker(**arguments)
        assert len(calls) == 1
    else:
        assert _launch_worker(**arguments) == 1234
        launch = calls[1]
        assert "--slice=openlabs-workers-math.slice" in launch
        assert str(paths.code / "bin/openlabs-math-resource-guard") in launch


def test_systemd_tick_launches_burst_capable_worker_in_transient_service(
    tmp_path,
    monkeypatch,
) -> None:
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
        cpu_ceiling_threads=15,
    )

    unit = _worker_unit_name(task)
    assert pid == 4321
    assert calls[0][0] == "/usr/bin/systemd-run"
    assert f"--unit={unit}" in calls[0]
    assert "--slice=openlabs-workers.slice" in calls[0]
    assert "--property=PartOf=openlabs-workers.target" in calls[0]
    assert "--property=MemoryHigh=4096M" in calls[0]
    assert not any(item.startswith("--property=MemoryMax=") for item in calls[0])
    assert "--property=CPUQuota=1500%" in calls[0]
    assert "--property=TasksMax=512" in calls[0]
    assert "--property=OOMPolicy=stop" in calls[0]
    assert "--setenv=OPENLABS_SECRET" in calls[0]
    assert "--setenv=INVOCATION_ID" not in calls[0]
    assert all("must-not-appear-in-argv" not in token for token in calls[0])
    assert any(token.endswith("/openlabs/gpu_guard.py") for token in calls[0])


def test_manual_tick_uses_transient_service_when_user_systemd_is_available(
    tmp_path,
    monkeypatch,
) -> None:
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
        "task_id": "manual:node",
        "current_attempt_id": "attempt-2",
        "cpu_threads": 1,
        "memory_mib": 2048,
        "scratch_mib": 1024,
    }
    calls: list[list[str]] = []

    monkeypatch.delenv("INVOCATION_ID", raising=False)

    def fake_which(name):
        if name in {"systemctl", "systemd-run"}:
            return f"/usr/bin/{name}"
        return None

    monkeypatch.setattr("openlabs.engine.shutil.which", fake_which)

    def fake_run(command, **kwargs):
        calls.append(list(command))
        if command[0] == "systemctl":
            return subprocess.CompletedProcess(command, 0, stdout="5678\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("openlabs.engine.subprocess.run", fake_run)
    pid = _launch_worker(
        task=task,
        paths=paths,
        job_path=tmp_path / "job.json",
        log_path=tmp_path / "worker.log",
        environment={"PYTHONPATH": "/code"},
        cpu_ceiling_threads=4,
    )

    assert pid == 5678
    assert calls[0][0:3] == ["/usr/bin/systemctl", "--user", "show-environment"]
    assert calls[1][0] == "/usr/bin/systemd-run"
    assert "--slice=openlabs-workers.slice" in calls[1]
    assert any(token.endswith("/openlabs/gpu_guard.py") for token in calls[1])
