"""Quota readings in packages/research-core/lab_runner.py (runtime.quota_snapshot).

Samples are recorded shapes from this host (2026-11-11): Claude Code 2.1.322
``stream-json --verbose`` rate_limit_event lines (the Fable call reports an extra
``seven_day_overage_included`` window), a codex-cli 0.166.0 session file event,
and a real ``codex exec --json`` stream that carries no ``rate_limits``.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "openlabs_test_lab_runner_snapshot",
    CODE_ROOT / "packages" / "research-core" / "lab_runner.py",
)
assert _SPEC is not None and _SPEC.loader is not None
lab_runner = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(lab_runner)

NOW = datetime(2026, 11, 11, 6, 0, 0, tzinfo=UTC)

CLAUDE_FABLE_STREAM = "\n".join(
    json.dumps(item)
    for item in (
        {"type": "system", "subtype": "init", "session_id": "sess-fable",
         "model": "claude-fable-5-2"},
        {"type": "rate_limit_event", "session_id": "sess-fable", "rate_limit_info": {
            "status": "allowed", "resetsAt": 1794385800, "rateLimitType": "five_hour",
            "unifiedWindows": {
                "five_hour": {"utilization": 0.41, "resetsAt": 1794385800, "status": "allowed"},
                "seven_day": {"utilization": 0.38, "resetsAt": 1794826800, "status": "allowed"},
                "seven_day_overage_included": {
                    "utilization": 0.61, "resetsAt": 1794826800, "status": "allowed"},
            }}},
        {"type": "assistant", "session_id": "sess-fable",
         "message": {"content": [{"type": "text", "text": "rate_limit mentioned in prose"}]}},
        {"type": "result", "subtype": "success", "is_error": False, "session_id": "sess-fable",
         "total_cost_usd": 0.21,
         "usage": {"input_tokens": 12, "cache_read_input_tokens": 3000, "output_tokens": 5}},
    )
)
CLAUDE_CHEAP_STREAM = "\n".join(
    json.dumps(item)
    for item in (
        {"type": "system", "subtype": "init", "session_id": "s2", "model": "claude-haiku-5-5"},
        {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "unifiedWindows": {
            "five_hour": {"utilization": 0.44, "resetsAt": 1794385800, "status": "allowed"},
            "seven_day": {"utilization": 0.39, "resetsAt": 1794826800, "status": "allowed"},
        }}},
    )
)
# ~/.codex/sessions/2026/11/10/rollout-...jsonl, event_msg/token_count (trimmed).
CODEX_SESSION_EVENT = {
    "timestamp": "2026-11-09T16:57:06.702Z",
    "type": "event_msg",
    "payload": {
        "type": "token_count",
        "info": None,
        "rate_limits": {
            "limit_id": "codex", "limit_name": None,
            "primary": {"used_percent": 53.0, "window_minutes": 10080, "resets_at": 1794624969},
            "secondary": None,
            "credits": {"has_credits": True, "unlimited": False, "balance": "62500.0000000000"},
            "plan_type": "pro", "rate_limit_reached_type": None,
        },
    },
}
# maintenance/20261028-physics-sixhour/de.events.jsonl (codex exec --json).
CODEX_EXEC_STREAM = (
    '{"type":"thread.started","thread_id":"01a1c13d-61f5-73f1-b70f-b104716b0915"}\n'
    '{"type":"turn.started"}\n'
    '{"type":"turn.completed","usage":{"input_tokens":3931886,"cached_input_tokens":3828608,'
    '"cache_write_input_tokens":0,"output_tokens":37851,"reasoning_output_tokens":8158}}\n'
)


def _windows(snapshot: dict) -> dict[str, dict]:
    return {item["name"]: item for item in snapshot["windows"]}


def test_claude_rate_limit_event_keeps_every_window_as_fraction() -> None:
    snapshot = lab_runner.extract_quota_snapshot(CLAUDE_FABLE_STREAM, adapter="claude", now=NOW)
    assert snapshot["provider"] == "anthropic"
    assert snapshot["model"] == "claude-fable-5-2"
    windows = _windows(snapshot)
    assert set(windows) == {"five_hour", "seven_day", "seven_day_overage_included"}
    assert windows["five_hour"]["used_fraction"] == 0.41
    assert windows["five_hour"]["window_minutes"] == 300
    assert windows["seven_day"]["window_minutes"] == 10080
    # Unknown name: kept, its length inferred from the name prefix.
    assert windows["seven_day_overage_included"]["used_fraction"] == 0.61
    assert windows["seven_day_overage_included"]["window_minutes"] == 10080
    assert windows["seven_day"]["resets_at"] == "2026-11-16T11:00:00Z"
    cheap = lab_runner.extract_quota_snapshot(CLAUDE_CHEAP_STREAM, adapter="claude", now=NOW)
    assert set(_windows(cheap)) == {"five_hour", "seven_day"}
    assert cheap["model"] == "claude-haiku-5-5"


def test_codex_rate_limits_normalize_percent_and_use_window_minutes() -> None:
    windows, balance = lab_runner.codex_quota_windows(
        CODEX_SESSION_EVENT["payload"]["rate_limits"]
    )
    assert windows == [
        {"name": "seven_day", "window_minutes": 10080, "used_fraction": 0.53,
         "resets_at": "2026-11-14T02:56:09Z", "slot": "primary"}
    ]
    assert balance == "62500.0000000000"
    # A secondary slot, if present, is named by its own window length, not its slot.
    both, _ = lab_runner.codex_quota_windows(
        {"primary": {"used_percent": 10.0, "window_minutes": 300, "resets_at": 1794385800},
         "secondary": {"used_percent": 75.5, "window_minutes": 10080, "resets_at": 1794624969}}
    )
    assert [(w["name"], w["used_fraction"]) for w in both] == [
        ("five_hour", 0.1), ("seven_day", 0.755)]


def test_codex_exec_stream_falls_back_to_the_session_file(tmp_path) -> None:
    # The real exec stream has no rate_limits ...
    assert "rate_limits" not in CODEX_EXEC_STREAM
    root = tmp_path / "sessions"
    assert lab_runner.extract_quota_snapshot(
        CODEX_EXEC_STREAM, adapter="codex", now=NOW, sessions_root=root
    ) is None  # ... and without a session file the reading is skipped.
    local = NOW.astimezone()
    day = root / f"{local.year:04d}" / f"{local.month:02d}" / f"{local.day:02d}"
    day.mkdir(parents=True)
    (day / "rollout-2026-11-10T00-56-27-01a1c13d-61f5-73f1-b70f-b104716b0915.jsonl").write_text(
        json.dumps({"type": "session_meta", "payload": {}}) + "\n"
        + json.dumps(CODEX_SESSION_EVENT) + "\n",
        encoding="utf-8",
    )
    (day / "rollout-2026-11-10T00-00-00-other-thread.jsonl").write_text(
        json.dumps({**CODEX_SESSION_EVENT, "payload": {"rate_limits": {
            "primary": {"used_percent": 99.0, "window_minutes": 10080}}}}),
        encoding="utf-8",
    )
    snapshot = lab_runner.extract_quota_snapshot(
        CODEX_EXEC_STREAM, adapter="codex", now=NOW, sessions_root=root, model="gpt-6.1-sol"
    )
    assert snapshot["provider"] == "openai-codex"
    assert snapshot["source"] == "codex_session_file"
    assert snapshot["credits_balance"] == 62500.0
    assert snapshot["model"] == "gpt-6.1-sol"
    assert _windows(snapshot)["seven_day"]["used_fraction"] == 0.53
    # A stream that does carry rate_limits is used directly.
    inline = CODEX_EXEC_STREAM + json.dumps(CODEX_SESSION_EVENT["payload"]) + "\n"
    direct = lab_runner.extract_quota_snapshot(inline, adapter="codex", now=NOW,
                                               sessions_root=tmp_path / "none")
    assert direct["source"] == "codex_exec_json"


def test_run_agent_attaches_snapshot_from_a_fake_claude_process(tmp_path, monkeypatch) -> None:
    output = tmp_path / "out" / "result.json"
    manifest = tmp_path / "openlabs" / "labs" / "math" / "lab.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"lab_id": "math", "domain": "math"}), encoding="utf-8")
    task = {
        "task_id": "task-c", "attempt_id": "attempt-c", "campaign_id": "campaign-c",
        "lab_manifest": str(manifest), "runner": "lead_claude",
        "objective": "Fake step.", "resources": {"cpu_threads": 1},
        "budget": {"wall_seconds": 30},
        "agent": {"role": "researcher", "session_mode": "fresh"},
        "agent_workspace": str(tmp_path / "agent"),
        "run_metadata_path": str(output.parent / "run-metadata.json"),
    }
    stream = tmp_path / "stream.jsonl"
    stream.write_text(CLAUDE_FABLE_STREAM, encoding="utf-8")
    fake = tmp_path / "bin" / "claude"
    fake.parent.mkdir()
    fake.write_text(
        f"#!{sys.executable}\nimport sys\nsys.stdin.read()\n"
        f"print(open({str(stream)!r}).read())\n",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("OPENLABS_WORKSPACE", str(tmp_path))
    monkeypatch.setenv(
        "OPENLABS_AGENT_COMMAND_LEAD_CLAUDE_JSON",
        json.dumps([str(fake), "-p", "--output-format", "stream-json", "--verbose",
                    "--model", "claude-fable-5-2"]),
    )
    monkeypatch.setenv("PATH", f"{fake.parent}{os.pathsep}{os.environ.get('PATH', '')}")
    # Only the stream parsing is under test here; the Claude transaction, result-gate
    # and permission policy are exercised in test_claude_adapter.py.
    monkeypatch.setattr(lab_runner, "_validate_codex_transaction", lambda *a, **k: None)
    monkeypatch.setattr(lab_runner, "_apply_claude_policy", lambda command, **k: command)
    monkeypatch.setattr(lab_runner, "_adapter_version", lambda _command: None)
    runtime = lab_runner._run_agent(task, {"lab_id": "math", "domain": "math"}, output)
    snapshot = runtime["quota_snapshot"]
    assert snapshot["provider"] == "anthropic" and snapshot["model"] == "claude-fable-5-2"
    assert set(_windows(snapshot)) == {"five_hour", "seven_day", "seven_day_overage_included"}
    assert runtime["provider_family"] == "anthropic"
    assert runtime["session_id"] == "sess-fable"
    assert runtime["cached_input_tokens"] == 3000 and runtime["output_tokens"] == 5
    assert runtime["cost_usd"] == 0.21
    assert runtime["profile"] is None and runtime["configured_model"] == "claude-fable-5-2"
