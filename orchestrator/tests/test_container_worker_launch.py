"""Docker worker launch: verified container cgroup, math fails closed. No real worker runs."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from openlabs import container_guard
from openlabs.config import WorkspacePaths
from openlabs.engine import _launch_worker

GIB = 1024**3
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def container(tmp_path, monkeypatch):
    """A fake Docker host: marker, aggregate cgroup, shared GPU lock mount."""

    marker = tmp_path / "dockerenv"
    marker.touch()
    cgroup = tmp_path / "cgroup"
    cgroup.mkdir()
    for name, value in {
        "cpu.max": "100000 100000", "memory.max": str(34 * GIB), "memory.high": "max",
        "memory.swap.max": str(4 * GIB), "pids.max": "512",
    }.items():
        (cgroup / name).write_text(value)
    runtime = tmp_path / "runtime"
    locks = runtime / "openlabs-gpu-guard"
    locks.mkdir(parents=True)
    locks.chmod(0o700)
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(f"1 0 0:1 /openlabs-gpu-guard {locks} rw - tmpfs tmpfs rw\n")
    real_path = container_guard.Path
    monkeypatch.setattr(
        container_guard, "Path",
        lambda value: mountinfo if str(value) == "/proc/self/mountinfo" else real_path(value),
    )
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setattr("openlabs.engine._CONTAINER_MARKER", marker)
    monkeypatch.setattr("openlabs.engine._CONTAINER_CGROUP", cgroup)

    def no_systemd(*args, **kwargs):
        raise AssertionError("container launch must not consult systemd")

    monkeypatch.setattr("openlabs.engine.subprocess.run", no_systemd)
    monkeypatch.setattr("openlabs.engine.shutil.which", lambda name: None)
    launched: list[dict] = []

    class FakePopen:
        pid = 2468

        def __init__(self, command, **kwargs):
            launched.append({"command": list(command), **kwargs})

    monkeypatch.setattr("openlabs.engine.subprocess.Popen", FakePopen)
    return cgroup, launched


def _arguments(tmp_path, domain=None):
    paths = WorkspacePaths(workspace=tmp_path, code=tmp_path / "openlabs",
        data=tmp_path / "data", artifacts=tmp_path / "artifacts",
        database=tmp_path / "database", database_file=tmp_path / "database/factory.sqlite")
    task = {"task_id": "node", "current_attempt_id": "attempt-1",
            "cpu_threads": 2, "memory_mib": 4096, "scratch_mib": 4096}
    if domain:
        task["domain"] = domain
    return dict(task=task, paths=paths, job_path=tmp_path / "job.json",
                log_path=tmp_path / "worker.log", environment={"OPENLABS_X": "1"})


def test_container_worker_starts_through_verified_resource_guard(tmp_path, container):
    _, launched = container
    arguments = _arguments(tmp_path)
    assert _launch_worker(**arguments) == 2468
    (call,) = launched
    command = call["command"]
    assert command[:4] == [str(arguments["paths"].code / "bin/openlabs-resource-guard"),
                           "--task-type", "cpu", "--"]
    assert command[-3:] == ["openlabs", "_worker", str(tmp_path / "job.json")]
    assert not any(token.endswith("gpu_guard.py") for token in command)
    assert call["start_new_session"] is True
    assert call["env"] == {"OPENLABS_X": "1"}


@pytest.mark.parametrize("filename,value", [
    ("cpu.max", "max 100000"), ("memory.max", "max"), ("memory.max", str(35 * GIB)),
    ("memory.swap.max", "max"), ("pids.max", "max"), ("memory.max", None),
])
def test_container_worker_refused_when_limits_missing_or_excessive(
    tmp_path, container, filename, value
):
    cgroup, launched = container
    if value is None:
        (cgroup / filename).unlink()
    else:
        (cgroup / filename).write_text(value)
    with pytest.raises(RuntimeError, match="container resource guard refused worker launch"):
        _launch_worker(**_arguments(tmp_path))
    assert launched == []


def test_container_worker_refused_without_shared_gpu_lock_mount(tmp_path, container, monkeypatch):
    _, launched = container
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "private-runtime"))
    with pytest.raises(RuntimeError, match="not mounted"):
        _launch_worker(**_arguments(tmp_path))
    assert launched == []


def test_math_worker_fails_closed_on_aggregate_container_limit(tmp_path, container):
    _, launched = container
    with pytest.raises(RuntimeError, match="no dedicated math cgroup") as error:
        _launch_worker(**_arguments(tmp_path, domain="math"))
    assert "16/18 GiB, no-swap" in str(error.value)
    assert launched == []


@pytest.mark.parametrize("filename,value", [
    ("memory.max", str(19 * GIB)), ("memory.high", "max"), ("memory.swap.max", str(GIB)),
])
def test_math_worker_refuses_near_miss_math_cgroup(tmp_path, container, filename, value):
    cgroup, launched = container
    for name, limit in {"memory.max": 18 * GIB, "memory.high": 16 * GIB,
                        "memory.swap.max": 0}.items():
        (cgroup / name).write_text(str(limit))
    (cgroup / filename).write_text(value)
    with pytest.raises(RuntimeError, match="no dedicated math cgroup"):
        _launch_worker(**_arguments(tmp_path, domain="math"))
    assert launched == []


def test_math_worker_runs_only_in_dedicated_math_container_cgroup(tmp_path, container):
    cgroup, launched = container
    for name, limit in {"memory.max": 18 * GIB, "memory.high": 16 * GIB,
                        "memory.swap.max": 0}.items():
        (cgroup / name).write_text(str(limit))
    assert _launch_worker(**_arguments(tmp_path, domain="math")) == 2468
    assert launched[0]["command"][1:4] == ["--task-type", "cpu", "--"]


@pytest.mark.skipif(not os.path.exists("/.dockerenv"), reason="requires a Docker container")
def test_math_wrapper_fails_closed_inside_docker_instead_of_recursing():
    completed = subprocess.run(
        [str(REPO / "bin/openlabs-math-resource-guard"), "--", shutil.which("true") or "/bin/true"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert completed.returncode == 78
    assert "no dedicated 16/18 GiB no-swap math cgroup" in completed.stderr
    assert "container guard: verified" not in completed.stderr
