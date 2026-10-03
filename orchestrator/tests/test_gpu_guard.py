from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from openlabs import gpu_guard as guard


def test_admission_headroom_and_exclusive_lease(tmp_path):
    gpu = guard.GPU(0, "GPU-test", 12227, 543, 42)
    assert gpu.ceiling == 9170
    directory = tmp_path / "private"
    with guard.reserve(gpu, 8192, directory):
        with pytest.raises(guard.GuardError, match="already reserved"):
            guard.reserve(gpu, 8192, directory)
    with guard.reserve(gpu, 8192, directory):
        pass
    for budget in (0, -1, 768, 9000):
        with pytest.raises(guard.GuardError, match="rejected"):
            guard.reserve(gpu, budget, directory)


def test_allocator_cap_preserves_cuda_and_other_settings():
    env = guard.allocator_environment(
        {"CUDA_VISIBLE_DEVICES": "0", "PYTORCH_CUDA_ALLOC_CONF": "backend:cudaMallocAsync,max_split_size_mb:128,per_process_memory_fraction:1.0"},
        [guard.GPU(0, "GPU-test", 12227, 543, 40)], 8192,
    )
    assert env["CUDA_VISIBLE_DEVICES"] == "0"
    assert env["HF_DEACTIVATE_ASYNC_LOAD"] == "1"
    assert "PYTORCH_CUDA_ALLOC_CONF" not in env
    assert "max_split_size_mb:128,backend:native" in env["PYTORCH_ALLOC_CONF"]
    assert float(env["OPENLABS_GPU_ALLOCATOR_FRACTION"]) == pytest.approx(7424 / 12227)


@pytest.mark.parametrize("row,match", [
    (guard.GPU(0, "GPU-test", 12227, 9200, 40), "ceiling"),
    (guard.GPU(0, "GPU-test", 12227, 3000, 85), "temperature"),
    (guard.GPU(0, "GPU-test", 12227, 5000, 40), "growth"),
    (guard.GPU(0, "GPU-other", 12227, 1000, 40), "disappeared"),
])
def test_watchdog_limits(row, match):
    with pytest.raises(guard.GuardError, match=match):
        guard.check_limits([row], guard.GPU(0, "GPU-test", 12227, 543, 40), 4096)


@pytest.fixture
def fake_gpu(tmp_path):
    binary = tmp_path / "nvidia-smi"
    telemetry = tmp_path / "telemetry"
    telemetry.write_text("0, GPU-test, 12227, 543, 40\n")
    binary.write_text(f"#!/bin/sh\ncat '{telemetry}'\n")
    binary.chmod(0o755)
    env = dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}", XDG_RUNTIME_DIR=str(tmp_path))
    for key in list(env):
        if key.startswith("OPENLABS_GPU_"):
            env.pop(key)
    return telemetry, env


def launch(env, code, *options):
    return subprocess.Popen(
        [sys.executable, guard.__file__, *options, "--", sys.executable, "-c", code],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def wait_file(path):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.03)
    raise AssertionError(f"child did not start: {path}")


@pytest.mark.parametrize("failure", ["overuse", "telemetry", "signal"])
def test_supervisor_stops_own_tree_and_releases_lease(fake_gpu, tmp_path, failure):
    telemetry, env = fake_gpu
    marker = tmp_path / "child.json"
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    code = (
        "import os, subprocess, sys, time, json; from pathlib import Path; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'], start_new_session=True); "
        f"Path({str(marker)!r}).write_text(json.dumps([os.getpid(),p.pid])); time.sleep(30)"
    )
    process = launch(env, code, "--gpu-memory-mib", "4096")
    try:
        wait_file(marker)
        if failure == "overuse":
            telemetry.write_text("0, GPU-test, 12227, 9500, 40\n")
        elif failure == "telemetry":
            telemetry.write_text("N/A\n")
        else:
            process.send_signal(signal.SIGTERM)
        _, stderr = process.communicate(timeout=10)
        assert process.returncode == (143 if failure == "signal" else 75), stderr
        for pid in json.loads(marker.read_text()):
            assert not Path(f"/proc/{pid}").exists()
        assert unrelated.poll() is None
        telemetry.write_text("0, GPU-test, 12227, 543, 40\n")
        retry = launch(env, "print('released')", "--gpu-memory-mib", "4096")
        stdout, stderr = retry.communicate(timeout=5)
        assert retry.returncode == 0, stderr
        assert "released" in stdout
    finally:
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=10)
        unrelated.terminate()
        unrelated.wait(timeout=5)


def test_nested_reuse_and_cpu_command_keeps_cuda(fake_gpu):
    _, env = fake_gpu
    env["CUDA_VISIBLE_DEVICES"] = "0"
    process = launch(env, "import os; print(os.environ['CUDA_VISIBLE_DEVICES'])")
    stdout, stderr = process.communicate(timeout=5)
    assert process.returncode == 0, stderr
    assert stdout.strip() == "0"
    nested = [sys.executable, guard.__file__, "--gpu-memory-mib", "4096", "--",
              sys.executable, "-c", "import os; print(os.environ['OPENLABS_GPU_BUDGET_MIB'])"]
    process = launch(env, f"import subprocess; subprocess.run({nested!r}, check=True)", "--gpu-memory-mib", "4096")
    stdout, stderr = process.communicate(timeout=5)
    assert process.returncode == 0, stderr
    assert stdout.strip() == "4096"


def test_stale_inherited_metadata_does_not_bypass_monitor(fake_gpu):
    telemetry, env = fake_gpu
    env["OPENLABS_GPU_SUPERVISOR_PID"] = "999999999"
    telemetry.write_text("0, GPU-test, 12227, 12000, 40\n")
    process = launch(env, "raise AssertionError('must not execute')", "--gpu-memory-mib", "4096")
    _, stderr = process.communicate(timeout=5)
    assert process.returncode == 75
    assert "ceiling" in stderr


@pytest.mark.parametrize("task_options", [(), ("--task-type", "cpu")])
@pytest.mark.parametrize("telemetry_value", ["0, GPU-test, 12227, 12000, 90\n", "N/A\n"])
def test_cpu_task_runs_without_gpu_admission_or_allocator_changes(fake_gpu, task_options, telemetry_value):
    telemetry, env = fake_gpu
    telemetry.write_text(telemetry_value)
    env["CUDA_VISIBLE_DEVICES"] = "0"
    env["OPENLABS_GPU_SUPERVISOR_PID"] = "999999999"
    env["OPENLABS_GPU_BUDGET_MIB"] = "4096"
    env["PYTORCH_ALLOC_CONF"] = "max_split_size_mb:128"
    code = "import os,json; print(json.dumps(dict(os.environ)))"
    process = launch(env, code, *task_options)
    stdout, stderr = process.communicate(timeout=5)
    assert process.returncode == 0, stderr
    child = json.loads(stdout)
    assert child["OPENLABS_TASK_TYPE"] == "cpu"
    assert child["CUDA_VISIBLE_DEVICES"] == "0"
    assert child["PYTORCH_ALLOC_CONF"] == "max_split_size_mb:128"
    assert not any(key.startswith("OPENLABS_GPU_") for key in child)


def test_cpu_task_does_not_require_nvidia_tools(monkeypatch):
    monkeypatch.setattr(guard, "inherited_supervisor", lambda: False)
    def forbidden(*args, **kwargs):
        raise AssertionError("CPU tasks must not inspect GPUs")
    monkeypatch.setattr(guard.shutil, "which", forbidden)
    monkeypatch.setattr(guard, "snapshot", forbidden)
    calls = []
    monkeypatch.setattr(guard, "supervise", lambda *args: calls.append(args) or 0)
    assert guard.main(["--task-type", "cpu", "--", "cpu-command"]) == 0
    assert calls[0][0] == ["cpu-command"]


def test_cpu_supervisor_survives_gpu_pressure_and_cleans_own_tree(fake_gpu, tmp_path):
    telemetry, env = fake_gpu
    marker = tmp_path / "cpu-tree.json"
    code = (
        "import os, subprocess, sys, time, json; from pathlib import Path; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'], start_new_session=True); "
        f"Path({str(marker)!r}).write_text(json.dumps([os.getpid(),p.pid])); time.sleep(30)"
    )
    process = launch(env, code, "--task-type", "cpu")
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        wait_file(marker)
        telemetry.write_text("0, GPU-test, 12227, 12000, 90\n")
        time.sleep(0.7)
        assert process.poll() is None
        process.send_signal(signal.SIGTERM)
        _, stderr = process.communicate(timeout=10)
        assert process.returncode == 143, stderr
        assert all(not Path(f"/proc/{pid}").exists() for pid in json.loads(marker.read_text()))
        assert unrelated.poll() is None
    finally:
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=10)
        unrelated.terminate()
        unrelated.wait(timeout=5)


@pytest.mark.parametrize("options", [
    ("--task-type", "cpu", "--gpu-memory-mib", "4096"),
    ("--task-type", "cpu", "--gpu-device", "0"),
    ("--task-type", "gpu"),
    ("--gpu-device", "0"),
    ("--task-type", "unknown"),
])
def test_invalid_task_classification_cannot_launch(fake_gpu, options):
    _, env = fake_gpu
    process = launch(env, "raise AssertionError('must not execute')", *options)
    _, stderr = process.communicate(timeout=5)
    assert process.returncode == 2, stderr


def test_gpu_monitor_ignores_other_device_pressure(fake_gpu):
    telemetry, env = fake_gpu
    telemetry.write_text("0, GPU-test, 12227, 543, 40\n1, GPU-other, 12227, 12000, 90\n")
    process = launch(env, "import os; print(os.environ['OPENLABS_TASK_TYPE'])",
                     "--task-type", "gpu", "--gpu-memory-mib", "4096")
    stdout, stderr = process.communicate(timeout=5)
    assert process.returncode == 0, stderr
    assert stdout.strip() == "gpu"


def test_gpu_monitor_queries_only_reserved_device_when_other_telemetry_fails(fake_gpu, tmp_path):
    _, env = fake_gpu
    query_log = tmp_path / "queries"
    binary = tmp_path / "nvidia-smi"
    binary.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> '{query_log}'\n"
        "case \" $* \" in\n"
        "  *' --id=0 '*) printf '0, GPU-test, 12227, 543, 40\\n';;\n"
        "  *) printf '0, GPU-test, 12227, 543, 40\\n1, GPU-other, N/A, N/A, N/A\\n';;\n"
        "esac\n"
    )
    process = launch(env, "print('selected device survived')", "--task-type", "gpu",
                     "--gpu-memory-mib", "4096", "--gpu-device", "0")
    stdout, stderr = process.communicate(timeout=5)
    assert process.returncode == 0, stderr
    assert stdout.strip() == "selected device survived"
    assert query_log.read_text().splitlines()
    assert all("--id=0" in query for query in query_log.read_text().splitlines())


def test_selected_snapshot_skips_unrelated_unavailable_row(monkeypatch):
    calls = []
    def telemetry(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0,
            "0, GPU-other, N/A, N/A, N/A\n1, GPU-selected, 12227, 543, 40\n", "")
    monkeypatch.setattr(guard.subprocess, "run", telemetry)
    assert guard.snapshot(1) == [guard.GPU(1, "GPU-selected", 12227, 543, 40)]
    assert "--id=1" in calls[0]
    with pytest.raises(guard.GuardError, match="telemetry unavailable"):
        guard.snapshot()
    assert not any(arg.startswith("--id=") for arg in calls[1])


def test_telemetry_timeout_is_bounded_and_fails_closed(monkeypatch):
    attempts = []
    def timeout(command, **kwargs):
        assert kwargs["timeout"] == 2
        attempts.append(1)
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])
    monkeypatch.setattr(guard.subprocess, "run", timeout)
    with pytest.raises(guard.GuardError, match="telemetry unavailable"):
        guard.snapshot()
    assert len(attempts) == 3


def test_telemetry_recovers_from_one_timeout(monkeypatch):
    attempts = []
    def transient(command, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return subprocess.CompletedProcess(command, 0, "0, GPU-test, 12227, 543, 40\n", "")
    monkeypatch.setattr(guard.subprocess, "run", transient)
    assert guard.snapshot() == [guard.GPU(0, "GPU-test", 12227, 543, 40)]
    assert len(attempts) == 2


def test_missing_gpu_monitor_rejects_gpu_request(monkeypatch):
    monkeypatch.setattr(guard, "inherited_supervisor", lambda: False)
    monkeypatch.setattr(guard.shutil, "which", lambda name: None)
    with pytest.raises(guard.GuardError, match="unavailable"):
        guard.main(["--gpu-memory-mib", "4096", "--", "must-not-run"])
