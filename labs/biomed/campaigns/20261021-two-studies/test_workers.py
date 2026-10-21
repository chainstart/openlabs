"""Check the campaign's fail-closed launch boundary without starting an agent."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

spec = importlib.util.spec_from_file_location(
    "day1_workers", Path(__file__).with_name("workers.py")
)
workers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workers)


def test_launcher_rejects_missing_resource_slice():
    with (
        patch.object(Path, "read_text", return_value="0::/init.scope\n"),
        patch.object(workers.subprocess, "run") as run,
        pytest.raises(RuntimeError, match="resource-guard"),
    ):
        workers.launch()
    run.assert_not_called()


def test_expired_campaign_never_starts_an_agent():
    with (
        patch.object(Path, "read_text", return_value="0::/openlabs-workers.slice/test.service\n"),
        patch.object(workers, "DEADLINE", datetime(2000, 1, 1, tzinfo=UTC)),
        patch.object(workers.subprocess, "run") as run,
        pytest.raises(RuntimeError, match="deadline"),
    ):
        workers.launch()
    run.assert_not_called()


def test_two_launches_have_independent_limits_and_deadlines(tmp_path):
    with (
        patch.object(Path, "read_text", return_value="0::/openlabs-workers.slice/test.service\n"),
        patch.object(workers, "ARTIFACT", tmp_path),
        patch.object(workers, "DEADLINE", datetime(2099, 1, 1, tzinfo=UTC)),
        patch.object(workers.subprocess, "run") as run,
    ):
        workers.launch()
    assert run.call_count == 2
    commands = [call.args[0] for call in run.call_args_list]
    assert commands[0] != commands[1]
    for command in commands:
        assert "--slice=openlabs-workers.slice" in command
        assert "--property=MemoryMax=2048M" in command
        assert "--property=CPUQuota=200%" in command
        assert "--property=KillMode=control-group" in command
        assert any(arg.startswith("--property=RuntimeMaxSec=") for arg in command)
        assert str(workers.CODE / "bin/openlabs-resource-guard") in command
        assert command[-2] == "--lane"


def test_duplicate_process_record_is_preserved(tmp_path):
    root = tmp_path / workers.LANES[0]
    root.mkdir()
    (root / "process-status.json").write_text('{"status":"running"}')
    with (
        patch.object(Path, "read_text", return_value="0::/openlabs-workers.slice/test.service\n"),
        patch.object(workers, "ARTIFACT", tmp_path),
        patch.object(workers, "DEADLINE", datetime(2099, 1, 1, tzinfo=UTC)),
        patch.object(workers.subprocess, "run") as run,
        pytest.raises(RuntimeError, match="duplicate"),
    ):
        workers.launch()
    run.assert_not_called()
