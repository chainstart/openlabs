"""Verify admission and resource boundaries without starting live agents."""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

spec = importlib.util.spec_from_file_location(
    "four_lane_workers", Path(__file__).with_name("workers.py")
)
workers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workers)


def test_missing_guard_rejects_launch():
    with (
        patch.object(Path, "read_text", return_value="0::/init.scope\n"),
        patch.object(workers.subprocess, "run") as run,
    ):
        with pytest.raises(RuntimeError, match="resource-guard"):
            workers.launch()
    run.assert_not_called()


def test_expired_deadline_rejects():
    with pytest.raises(RuntimeError, match="deadline"):
        workers.remaining_seconds({"deadline_utc": "2000-01-01T00:00:00+00:00"})


def test_launcher_preserves_current_proxy_without_global_sync():
    with patch.dict(workers.os.environ, {"HTTPS_PROXY": "http://127.0.0.1:7890"}):
        command = workers.launch_command(workers.LANES[0], 60)
    assert "--setenv=HTTPS_PROXY=http://127.0.0.1:7890" in command
    assert "--setenv=OPENLABS_PROXY_AUTO_SYNC=0" in command
    assert "--setenv=OPENLABS_PROXY_SYNC_SYSTEMD=0" in command


def fixture_paths(tmp_path):
    code, here, artifact = (tmp_path / name for name in ("code", "campaign", "artifact"))
    for relative in (
        "labs/biomed/.venv/bin/python",
        "labs/biomed/environments/singlecell/.venv/bin/python",
    ):
        path = code / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    here.mkdir()
    for lane in workers.LANES:
        (here / f"{lane}.prompt.txt").write_text("scope")
    return code, here, artifact


def test_three_services_are_bounded_and_separate(tmp_path):
    code, here, artifact = fixture_paths(tmp_path)
    config = {"deadline_utc": (datetime.now(UTC) + timedelta(hours=1)).isoformat()}
    with (
        patch.object(workers, "require_guard"),
        patch.object(workers, "settings", return_value=config),
        patch.object(workers, "CODE", code),
        patch.object(workers, "HERE", here),
        patch.object(workers, "ARTIFACT", artifact),
        patch.object(workers.subprocess, "run") as run,
    ):
        workers.launch()
    assert run.call_count == 3
    commands = [call.args[0] for call in run.call_args_list]
    assert (
        len({next(arg for arg in command if arg.startswith("--unit=")) for command in commands})
        == 3
    )
    for command in commands:
        for required in (
            "--slice=openlabs-workers.slice",
            "--property=MemoryMax=5G",
            "--property=CPUQuota=200%",
            "--property=TasksMax=96",
            "--property=KillMode=control-group",
            "--property=Restart=no",
        ):
            assert required in command
        assert str(code / "bin/openlabs-resource-guard") in command
        assert any(arg.startswith("--property=RuntimeMaxSec=") for arg in command)


def test_duplicate_last_lane_prevents_partial_launch(tmp_path):
    code, here, artifact = fixture_paths(tmp_path)
    path = artifact / workers.LANES[-1] / "process-status.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"status":"running"}')
    config = {"deadline_utc": (datetime.now(UTC) + timedelta(hours=1)).isoformat()}
    with (
        patch.object(workers, "require_guard"),
        patch.object(workers, "settings", return_value=config),
        patch.object(workers, "CODE", code),
        patch.object(workers, "HERE", here),
        patch.object(workers, "ARTIFACT", artifact),
        patch.object(workers.subprocess, "run") as run,
    ):
        with pytest.raises(RuntimeError, match="duplicate"):
            workers.launch()
    run.assert_not_called()
    assert path.read_text() == '{"status":"running"}'
