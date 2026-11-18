"""Off-peak window for large proxy-route downloads (user rule 2026-11-18)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from openlabs import download_window as dw
from openlabs.agent_runtime import configure_codex_runtime
from openlabs.config import FactorySettings

SHANGHAI = ZoneInfo("Asia/Shanghai")
SRC = Path(__file__).resolve().parents[1] / "src"
PROXY = "/workspace/.download-bridge/download-submit --url https://x/f.fits --output /workspace/p/f --route proxy"


def _at(hour: int, minute: int) -> datetime:
    return datetime(2026, 11, 18, hour, minute, tzinfo=SHANGHAI)


@pytest.mark.parametrize(("hour", "minute", "inside"),
                         [(1, 59, False), (2, 0, True), (13, 59, True), (14, 0, False),
                          (23, 30, False)])
def test_window_boundaries(hour, minute, inside) -> None:
    assert dw.in_window(_at(hour, minute)) is inside
    refusal = dw.command_refusal(PROXY, _at(hour, minute))
    assert (refusal is None) is inside


def test_window_is_judged_in_its_own_time_zone() -> None:
    utc = timezone.utc  # this container's zoneinfo "UTC" file carries +08:00
    assert dw.in_window(datetime(2026, 11, 18, 17, 59, tzinfo=utc)) is False  # 01:59 +08
    assert dw.in_window(datetime(2026, 11, 18, 18, 0, tzinfo=utc)) is True    # 02:00 +08
    with pytest.raises(ValueError):
        dw.in_window(datetime(2026, 11, 18, 3, 0))


def test_wrapping_window_and_next_start() -> None:
    night = dw.parse_window(["22:00", "06:00"])
    assert dw.in_window(_at(23, 0), night) and dw.in_window(_at(5, 59), night)
    assert not dw.in_window(_at(6, 0), night)
    assert dw.next_window_start(_at(14, 0)) == _at(2, 0).replace(day=19)
    assert dw.next_window_start(_at(1, 0)) == _at(2, 0)
    assert dw.next_window_start(_at(3, 0)) == _at(3, 0)


def test_only_proxy_submissions_without_the_small_marker_are_refused() -> None:
    late = _at(20, 0)
    assert dw.command_refusal(PROXY, late)
    assert dw.command_refusal(PROXY.replace("--route proxy", "--route=proxy"), late)
    assert dw.command_refusal(PROXY.replace("--route proxy", "--route auto"), late) is None
    assert dw.command_refusal("PROXY_SMALL_OK=1 " + PROXY, late) is None
    assert dw.command_refusal("/workspace/.download-bridge/download-submit --status abc", late) is None
    assert dw.command_refusal("ls -la", late) is None
    reason = dw.command_refusal(PROXY, late)
    assert "02:00-14:00 Asia/Shanghai" in reason and "2026-11-19 02:00" in reason


def test_large_thresholds() -> None:
    mib = 1024 * 1024
    assert not dw.is_large(file_bytes=199 * mib, batch_bytes=1023 * mib)
    assert dw.is_large(file_bytes=200 * mib)
    assert dw.is_large(batch_bytes=1024 * mib)


def test_factory_configuration_parsing() -> None:
    policy = dw.load_window({"proxy_download_window": ["01:30", "13:00"],
                             "proxy_download_timezone": "UTC",
                             "proxy_download_large_file_mib": 500,
                             "proxy_download_codex_hook": True})
    assert (policy.start, policy.end, policy.timezone) == ("01:30", "13:00", "UTC")
    assert policy.large_file_mib == 500 and policy.large_batch_mib == 1024 and policy.codex_hook
    assert dw.load_window({}) == dw.ProxyDownloadWindow()
    assert FactorySettings().proxy_download == dw.ProxyDownloadWindow()
    for bad in ({"proxy_download_window": ["2:00", "14:00"]},
                {"proxy_download_window": ["02:00"]},
                {"proxy_download_window": ["02:00", "02:00"]},
                {"proxy_download_timezone": "Mars/Base"},
                {"proxy_download_large_batch_mib": 0}):
        with pytest.raises(ValueError):
            dw.load_window(bad)


def test_hook_outputs_for_claude_and_codex() -> None:
    event = {"tool_name": "Bash", "tool_input": {"command": PROXY}}
    policy = dw.ProxyDownloadWindow()
    code, out, err = dw.pre_tool_use(event, policy, adapter="claude", now=_at(20, 0))
    assert code == 0 and err == ""
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"
    code, out, err = dw.pre_tool_use(event, policy, adapter="codex", now=_at(20, 0))
    assert code == 2 and out == "" and "02:00-14:00" in err
    assert dw.pre_tool_use(event, policy, adapter="claude", now=_at(9, 0)) == (0, "", "")
    codex_event = {"tool_input": {"command": ["bash", "-lc", PROXY]}}
    assert dw.pre_tool_use(codex_event, policy, adapter="codex", now=_at(20, 0))[0] == 2


def test_hook_cli_never_blocks_unrelated_commands() -> None:
    policy = json.dumps(dw.ProxyDownloadWindow().to_dict())
    result = subprocess.run(
        [sys.executable, "-m", "openlabs.download_window", "pre-tool-use", "--adapter", "claude",
         "--policy", policy],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}}),
        capture_output=True, text=True, env={"PYTHONPATH": str(SRC)}, check=False)
    assert result.returncode == 0 and result.stdout == ""


def test_rule_text_reads_the_configuration() -> None:
    text = dw.rule_text(dw.parse_window(["03:00", "12:00"], large_file_mib=300))
    assert "03:00-12:00 Asia/Shanghai" in text and ">= 300 MB" in text


def _runtime(tmp_path: Path, proxy_download):
    workspace = tmp_path / "ws"
    workspace.mkdir(parents=True)
    configure_codex_runtime(
        workspace, task={"task_id": "t", "campaign_id": "c", "lab_id": "ai", "domain": "ai",
                         "objective": "x", "agent": {"role": "researcher"}, "transaction": {}},
        output_path=workspace / "result.json", skill_dirs=(), proxy_download=proxy_download)
    hooks = json.loads((workspace / ".codex" / "hooks.json").read_text())["hooks"]
    claude = json.loads((workspace / ".claude" / "openlabs-settings.json").read_text())["hooks"]
    return hooks, claude


def test_production_sessions_get_the_hook(tmp_path) -> None:
    hooks, claude = _runtime(tmp_path / "a", dw.ProxyDownloadWindow().to_dict())
    assert set(claude) == {"PreToolUse", "SessionStart", "Stop"}
    entry = claude["PreToolUse"][0]
    assert entry["matcher"] == "Bash"
    assert "openlabs.download_window pre-tool-use --adapter claude" in entry["hooks"][0]["command"]
    # Codex keeps exactly the two verified hooks until proxy_download_codex_hook is on.
    assert set(hooks) == {"SessionStart", "Stop"}
    hooks, _claude = _runtime(tmp_path / "b",
                              dw.ProxyDownloadWindow(codex_hook=True).to_dict())
    assert "PreToolUse" in hooks
    hooks, claude = _runtime(tmp_path / "c", None)
    assert set(claude) == {"SessionStart", "Stop"}
