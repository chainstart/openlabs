"""Antigravity CLI (``agy``) as a third agent adapter and a third model family.

No real ``agy`` process is started. A fake executable named ``agy`` reads the one
stream-json user message from stdin, runs the hooks of ``.agents/hooks.json`` the way
agy 1.5.14 does (camelCase JSON on stdin; ``{"decision": "continue"}`` re-enters a
Stop; ``{"injectSteps": [...]}`` at SessionStart) and answers ``-p /usage`` with the
quota groups. The shapes were measured against the real CLI on 2026-11-23.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from openlabs import budget as budget_control
from openlabs import codex_hook, download_window, engine
from openlabs.agent_runtime import HOOK_GATED_ADAPTERS, configure_codex_runtime
from openlabs.config import (
    ANTIGRAVITY_PROVIDER,
    RunnerSpec,
    load_runner_specs,
    runner_family,
)
from openlabs.contracts import RESULT_SCHEMA
from test_claude_adapter import _ingest_completed, _layout
from test_quota_routing import (
    CLAUDE,
    GPT,
    NOW,
    RUNNERS,
    _claim,
    _enqueue,
    _record,
    _routed_events,
    _settings,
    _setup,
)

CODE_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "openlabs_agy_adapter_lab_runner",
    CODE_ROOT / "packages" / "research-core" / "lab_runner.py",
)
assert _SPEC is not None and _SPEC.loader is not None
lab_runner = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(lab_runner)

USAGE = {
    "conversation_id": "", "status": "SUCCESS", "num_turns": 0,
    "command": {"name": "usage", "data": {"groups": [
        {"name": "Gemini Models", "buckets": [
            {"id": "gemini-weekly", "window": "weekly", "remaining_fraction": 0.75,
             "reset_time": "2099-01-01T00:00:00Z"},
            {"id": "gemini-5h", "window": "5h", "remaining_fraction": 0.9,
             "reset_time": "2099-01-01T00:00:00Z"}]},
        {"name": "Claude and GPT models", "buckets": [
            {"id": "3p-weekly", "window": "weekly", "remaining_fraction": 1,
             "reset_time": "2099-01-01T00:00:00Z"}]},
    ]}},
}

FAKE_AGY = textwrap.dedent(
    r'''
    #!/usr/bin/env python3
    """Minimal stand-in for `agy -p= --input-format stream-json --output-format stream-json`."""
    import json, os, re, subprocess, sys

    argv = sys.argv[1:]
    if "/usage" in argv:
        print(os.environ["FAKE_AGY_USAGE"])
        sys.exit(0)
    record = os.environ.get("FAKE_AGY_ARGV")
    if record:
        open(record, "w").write(json.dumps(argv))
    mode = os.environ.get("FAKE_AGY_MODE", "write")
    message = json.loads(sys.stdin.readline())
    assert message["event"] == "user"
    prompt = message["message"]["content"][0]["text"]
    conversation = argv[argv.index("--conversation") + 1] if "--conversation" in argv else "conv-1"
    model = argv[argv.index("--model") + 1] if "--model" in argv else "gemini-4-hydrogen-high"

    def emit(event):
        print(json.dumps(event), flush=True)

    emit({"event": "init", "conversation_id": conversation,
          "init": {"model": model, "cwd": os.getcwd(), "permission_mode": "always-proceed"}})
    if mode == "quota":
        sys.stderr.write('AGY_ERROR: {"short_error":"You have reached your weekly quota",'
                         '"status":"RESOURCE_EXHAUSTED"}\n')
        emit({"event": "result", "result": {"conversation_id": conversation, "status": "ERROR",
              "error": "weekly quota exhausted", "usage": {}}})
        sys.exit(1)
    hooks = json.load(open(os.path.join(os.getcwd(), ".agents", "hooks.json")))
    base = {"conversationId": conversation, "cwd": os.getcwd(), "modelName": model,
            "transcriptPath": os.path.join(os.getcwd(), "transcript.jsonl"),
            "workspacePaths": [os.getcwd()]}

    def run(event_name, payload):
        outputs = []
        for spec in hooks.values():
            for handler in spec.get(event_name, []):
                done = subprocess.run(handler["command"], shell=True, input=json.dumps(payload),
                                      text=True, capture_output=True,
                                      timeout=handler.get("timeout", 30))
                if done.returncode != 0:
                    sys.stderr.write(done.stderr)
                outputs.append(json.loads(done.stdout or "{}"))
        return outputs

    started = run("SessionStart", {**base, "hookEventName": "SessionStart"})
    assert started and "injectSteps" in started[0], started
    emit({"event": "step_update", "step_update": {"conversation_id": conversation,
          "step_index": 1, "state": "DONE", "step_type": "agent_response",
          "usage": {"input_tokens": 5, "output_tokens": 2}}})
    result_path = re.search(r"required result path: `([^`]+)`", prompt).group(1)

    def write_result():
        with open(result_path, "w") as handle:
            json.dump({"schema_version": "openlabs.result_bundle.v1", "task_id": "task-1",
                       "campaign_id": "campaign", "lab_id": "math", "domain": "math",
                       "status": "completed", "summary": "Fake agy finished the step.",
                       "artifacts": [], "claims": [], "next_actions": []}, handle)

    execution = 0
    while True:
        outputs = run("Stop", {**base, "hookEventName": "Stop", "executionNum": execution,
                               "terminationReason": "NO_TOOL_CALL", "fullyIdle": True,
                               "continuationActive": False})
        if not any(item.get("decision") == "continue" for item in outputs):
            break
        if mode == "write":
            write_result()
        execution += 1
    emit({"event": "result", "result": {"conversation_id": conversation, "status": "SUCCESS",
          "response": "done", "num_turns": 1,
          "usage": {"input_tokens": 11, "output_tokens": 7, "thinking_tokens": 4,
                    "cache_read_tokens": 3, "total_tokens": 18}}})
    '''
).lstrip()


def _agy_layout(tmp_path: Path, monkeypatch, *, mode: str, extra: list[str] | None = None,
                session_id: str | None = None) -> dict:
    layout = _layout(tmp_path, session_id=session_id)
    layout["task"]["runner"] = "worker_gemini"
    fake = tmp_path / "bin" / "agy"
    fake.write_text(FAKE_AGY.replace("/usr/bin/env python3", sys.executable, 1))
    fake.chmod(0o755)
    record = tmp_path / "agy-argv.json"
    monkeypatch.setenv("OPENLABS_WORKSPACE", str(layout["workspace"]))
    monkeypatch.setenv("FAKE_AGY_MODE", mode)
    monkeypatch.setenv("FAKE_AGY_ARGV", str(record))
    monkeypatch.setenv("FAKE_AGY_USAGE", json.dumps(USAGE))
    command = [str(fake), "-p", "--model", "gemini-4-hydrogen-high", *(extra or [])]
    monkeypatch.setenv("OPENLABS_AGENT_COMMAND_WORKER_GEMINI_JSON", json.dumps(command))
    monkeypatch.setenv(
        "OPENLABS_AGENT_RESUME_COMMAND_WORKER_GEMINI_JSON",
        json.dumps([str(fake), "-p", "--conversation", "{session_id}",
                    "--model", "gemini-4-hydrogen-high"]),
    )
    monkeypatch.setattr(lab_runner, "_validate_codex_transaction",
                        lambda task, *, workspace, agent_workspace, agent_label="Codex": None)
    monkeypatch.setattr(lab_runner, "_adapter_version", lambda _command: "1.5.14")
    return {**layout, "fake": fake, "argv_record": record}


# ------------------------------------------------------------ generated runtime


def test_runtime_writes_agy_hooks_next_to_the_shared_skills(tmp_path) -> None:
    layout = _layout(tmp_path)
    policy = layout["task"]["runtime_policy"]
    staged = layout["staged"].resolve()
    assert policy["agy_hooks"] == str(staged / ".agents" / "hooks.json")
    hooks = json.loads(Path(policy["agy_hooks"]).read_text())
    gate = hooks["openlabs-result-gate"]
    # agy layout: flat handler lists for SessionStart and Stop.
    assert gate["SessionStart"][0]["command"].endswith("--adapter agy")
    assert "session-start" in gate["SessionStart"][0]["command"]
    assert gate["Stop"][0]["timeout"] == 330 and " stop " in gate["Stop"][0]["command"]
    assert "PreToolUse" not in gate
    # The Skills agy discovers are the same ``.agents/skills`` Codex reads.
    assert (staged / ".agents" / "skills" / "domain-skill" / "SKILL.md").is_file()
    assert "agy" in HOOK_GATED_ADAPTERS


def test_agy_download_window_hook_matches_run_command(tmp_path) -> None:
    layout = _layout(tmp_path)
    staged = layout["staged"]
    window = {"window": "02:00-14:00", "timezone": "Asia/Shanghai",
              "large_file_mib": 200, "large_batch_mib": 1024}
    policy = configure_codex_runtime(staged, task=layout["task"], output_path=layout["output"],
                                     skill_dirs=(), proxy_download=window)
    gate = json.loads(Path(policy["agy_hooks"]).read_text())["openlabs-result-gate"]
    group = gate["PreToolUse"][0]
    assert group["matcher"] == "run_command"
    assert "--adapter agy" in group["hooks"][0]["command"]


def test_download_window_speaks_the_agy_dialect() -> None:
    window = download_window.ProxyDownloadWindow()
    late = download_window._local(None, window).replace(hour=20)
    ok = {"toolCall": {"name": "run_command", "args": {"CommandLine": "ls -la"}}}
    code, out, _err = download_window.pre_tool_use(ok, window, adapter="agy", now=late)
    assert code == 0 and json.loads(out) == {"decision": "allow"}
    proxy = {"toolCall": {"name": "run_command", "args": {
        "CommandLine": "download-submit --url https://x/y --output /w/y --route proxy"}}}
    code, out, _err = download_window.pre_tool_use(proxy, window, adapter="agy", now=late)
    refused = json.loads(out)
    assert code == 0 and refused["decision"] == "deny" and "02:00" in refused["reason"]


def test_hook_dialect_translation() -> None:
    event = codex_hook._agy_event({"conversationId": "c", "transcriptPath": "/t",
                                   "executionNum": 1, "continuationActive": False})
    assert event["session_id"] == "c" and event["transcript_path"] == "/t"
    assert event["stop_hook_active"] is True
    assert codex_hook._agy_event({"executionNum": 0})["stop_hook_active"] is False
    blocked = codex_hook._agy_output("stop", {"decision": "block", "reason": "write it"})
    assert blocked == {"decision": "continue", "reason": "write it"}
    assert codex_hook._agy_output("stop", {}) == {}
    start = codex_hook._agy_output(
        "session-start", {"hookSpecificOutput": {"additionalContext": "context"}})
    assert start == {"injectSteps": [{"systemMessage": {"systemMessage": "context"}}]}


def test_session_context_names_skills_for_agy(tmp_path) -> None:
    layout = _layout(tmp_path)
    context = json.loads((layout["staged"] / ".codex" / "openlabs-context.json").read_text())
    message = codex_hook._session_context(context, "agy")["hookSpecificOutput"]
    assert "the Skills domain-skill" in message["additionalContext"]
    assert "$domain-skill" not in message["additionalContext"]


# ------------------------------------------------------------ the adapter end to end


def test_fake_agy_is_gated_released_and_reports_usage_and_quota(tmp_path, monkeypatch) -> None:
    layout = _agy_layout(tmp_path, monkeypatch, mode="write")

    runtime = lab_runner._run_agent(layout["task"], layout["manifest"], layout["output"])

    hooks = runtime["hooks"]
    assert [event["outcome"] for event in hooks["events"]] == [
        "context_injected", "result_gate_blocked", "result_gate_passed"]
    assert {event["agent_adapter"] for event in hooks["events"]} == {"agy"}
    assert hooks["events"][1]["session_id"] == "conv-1"
    assert engine._codex_hook_receipt_status(runtime) == (None, None)
    assert json.loads(layout["output"].read_text())["status"] == "completed"
    assert "failure_class" not in runtime
    assert runtime["adapter"] == "agy" and runtime["session_id"] == "conv-1"
    assert runtime["model"] == "gemini-4-hydrogen-high"
    assert runtime["filesystem_sandbox"] == "agy-skip-permissions-full-access"
    assert runtime["input_tokens"] == 11 and runtime["cached_input_tokens"] == 3
    assert runtime["output_tokens"] == 7 and runtime["reasoning_output_tokens"] == 4
    assert runtime["provider_family"] == ANTIGRAVITY_PROVIDER
    snapshot = runtime["quota_snapshot"]
    assert snapshot["provider"] == ANTIGRAVITY_PROVIDER
    windows = {item["name"]: item for item in snapshot["windows"]}
    assert windows["gemini-weekly"]["used_fraction"] == pytest.approx(0.25)
    assert windows["gemini-weekly"]["window_minutes"] == 10080
    assert windows["gemini-5h"]["window_minutes"] == 300
    argv = json.loads(layout["argv_record"].read_text())
    assert argv[:6] == ["-p=", "--input-format", "stream-json", "--output-format",
                        "stream-json", "--dangerously-skip-permissions"]
    assert "-p" not in argv and argv[argv.index("--model") + 1] == "gemini-4-hydrogen-high"


def test_fake_agy_without_result_fails_closed(tmp_path, monkeypatch) -> None:
    layout = _agy_layout(tmp_path, monkeypatch, mode="never")

    runtime = lab_runner._run_agent(layout["task"], layout["manifest"], layout["output"])

    hooks = runtime["hooks"]
    assert hooks["stop_blocked"] == 1 and hooks["stop_failed_final"] == 1
    assert hooks["stop_passed"] is False
    error, _warning = engine._codex_hook_receipt_status(runtime)
    assert error == "Antigravity final Stop gate receipt is incomplete"


def test_fake_agy_resume_continues_the_conversation(tmp_path, monkeypatch) -> None:
    layout = _agy_layout(tmp_path, monkeypatch, mode="write", session_id="conv-prior")

    runtime = lab_runner._run_agent(layout["task"], layout["manifest"], layout["output"])

    argv = json.loads(layout["argv_record"].read_text())
    assert argv[argv.index("--conversation") + 1] == "conv-prior"
    assert runtime["session_id"] == "conv-prior" and runtime["resumed_from"] == "conv-prior"


def test_fake_agy_quota_error_is_classified(tmp_path, monkeypatch) -> None:
    layout = _agy_layout(tmp_path, monkeypatch, mode="quota")

    runtime = lab_runner._run_agent(layout["task"], layout["manifest"], layout["output"])

    assert runtime["failure_class"] == "agent_quota"
    assert runtime["quota"]["kind"] in {"usage_limit", "rate_limit"}
    assert runtime["agy_status"] == "ERROR"


@pytest.mark.parametrize("extra", [["--settings", "{}"], ["--sandbox"], ["--mode", "plan"],
                                   ["--output-format", "json"], ["--remote-agent"]])
def test_agy_command_policy_is_enforced(tmp_path, monkeypatch, extra) -> None:
    layout = _agy_layout(tmp_path, monkeypatch, mode="write", extra=extra)
    with pytest.raises(ValueError):
        lab_runner._run_agent(layout["task"], layout["manifest"], layout["output"])


def test_agy_requires_the_generated_hooks(tmp_path, monkeypatch) -> None:
    layout = _agy_layout(tmp_path, monkeypatch, mode="write")
    layout["task"]["runtime_policy"] = {**layout["task"]["runtime_policy"], "agy_hooks": ""}
    with pytest.raises(ValueError, match="result-gate hooks"):
        lab_runner._run_agent(layout["task"], layout["manifest"], layout["output"])


def test_agy_request_and_stdin_message(tmp_path) -> None:
    layout = _layout(tmp_path)
    request = lab_runner._agent_request(layout["task"], layout["manifest"], layout["output"],
                                        adapter="agy")
    assert "Invoke and follow the Skills domain-skill" in request
    assert "inside this Antigravity process" in request
    message = json.loads(lab_runner.agy_stdin_message("hello"))
    assert message == {"event": "user", "message": {
        "role": "user", "content": [{"type": "text", "text": "hello"}]}}


def test_engine_gates_agy_results_like_the_other_adapters(tmp_path) -> None:
    runtime = _ingest_completed(tmp_path, {"adapter": "agy", "session_id": "s"})
    assert runtime["hook_receipt_error"] == (
        "Antigravity lifecycle hook receipts are missing or invalid")


# ------------------------------------------------------------ quota readings


def test_usage_command_and_error_parsing() -> None:
    snapshot = lab_runner.extract_quota_snapshot(json.dumps(USAGE), adapter="agy",
                                                 model="gemini-4-neon-high")
    assert snapshot["provider"] == ANTIGRAVITY_PROVIDER
    assert {item["name"] for item in snapshot["windows"]} == {
        "gemini-weekly", "gemini-5h", "3p-weekly"}
    assert lab_runner.extract_quota_snapshot("not json", adapter="agy") is None
    result = json.dumps({"event": "result", "result": {"status": "ERROR",
                                                        "error": "RESOURCE_EXHAUSTED"}})
    quota = lab_runner.classify_agent_quota(stdout_text=result)
    assert quota is not None and quota["kind"] == "rate_limit"
    # Successful results and tool output are not provider errors.
    ok = json.dumps({"event": "result", "result": {"status": "SUCCESS",
                                                    "response": "weekly quota fine"}})
    assert lab_runner.classify_agent_quota(stdout_text=ok) is None


def test_agy_probe_is_free_and_refreshed_often(tmp_path) -> None:
    _paths, db = _setup(tmp_path)
    settings = _settings(
        probe_commands={ANTIGRAVITY_PROVIDER: ("agy", "-p", "/usage", "--output-format", "json")},
        stale_refresh_minutes=10,
    )
    settings = replace(settings, runners={
        **settings.runners,
        "worker_gemini": RunnerSpec("worker_gemini", ANTIGRAVITY_PROVIDER, "worker",
                                    "gemini-4-hydrogen-high"),
    })
    calls: list[list[str]] = []

    def run(command, **_kwargs):
        calls.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(USAGE), stderr="")

    # The parser stamps the reading with the wall clock, so the test runs on it too.
    start = datetime.now(UTC)
    outcome = budget_control.probe_stale_providers(db, settings, now=start, run=run)
    assert outcome[ANTIGRAVITY_PROVIDER] == "recorded"
    readings = budget_control.quota_readings(db)[ANTIGRAVITY_PROVIDER]
    assert readings["gemini-weekly"].used_fraction == pytest.approx(0.25)
    # Within stale_refresh_minutes nothing is probed again; after it, it is.
    assert budget_control.probe_stale_providers(
        db, settings, now=start + timedelta(minutes=5), run=run) == {}
    later = budget_control.probe_stale_providers(
        db, settings, now=start + timedelta(minutes=11), run=run)
    assert later[ANTIGRAVITY_PROVIDER] == "recorded" and len(calls) == 2


# ------------------------------------------------------------ families and routing


def test_runner_family_follows_the_model_for_antigravity() -> None:
    assert runner_family(ANTIGRAVITY_PROVIDER, "gemini-4-neon-xhigh") == "google"
    assert runner_family(ANTIGRAVITY_PROVIDER, "claude-opus-5-5-high") == CLAUDE
    assert runner_family(ANTIGRAVITY_PROVIDER, "gpt-oss-120b-medium") == GPT
    assert runner_family(GPT, "anything") == GPT
    specs = load_runner_specs({
        "worker_gemini": {"provider": ANTIGRAVITY_PROVIDER, "tier": "worker",
                          "model": "gemini-4-hydrogen-high", "overflow": True,
                          "task_classes": ["review", "owner"]},
    })
    spec = specs["worker_gemini"]
    assert spec.family == "google" and spec.overflow is True
    assert spec.accepts("review") and not spec.accepts("ordinary")
    with pytest.raises(ValueError, match="task_classes"):
        load_runner_specs({"x": {"provider": GPT, "tier": "worker", "task_classes": ["nope"]}})


GEMINI_WINDOWS = ("gemini-weekly", "gemini-5h")
GEMINI = {
    "lead_gemini": RunnerSpec("lead_gemini", ANTIGRAVITY_PROVIDER, "lead", "gemini-4-neon-xhigh",
                              windows=GEMINI_WINDOWS, overflow=True,
                              task_classes=("review", "decision")),
    "worker_gemini": RunnerSpec("worker_gemini", ANTIGRAVITY_PROVIDER, "worker",
                                "gemini-4-hydrogen-high", windows=GEMINI_WINDOWS,
                                overflow=True, task_classes=("review", "decision", "owner")),
    "light_gemini": RunnerSpec("light_gemini", ANTIGRAVITY_PROVIDER, "light",
                               "gemini-3.8-flash-medium", windows=GEMINI_WINDOWS,
                               overflow=True, task_classes=("review",)),
}


def _three_family_settings(**routing):
    settings = _settings(**routing)
    return replace(settings, runners={**RUNNERS, **GEMINI})


def _gemini_quota(db, settings, used: float = 0.1) -> None:
    budget_control.record_quota_snapshot(db, settings, {
        "provider": ANTIGRAVITY_PROVIDER, "observed_at": budget_control._iso(NOW),
        "windows": [{"name": name, "used_fraction": used, "window_minutes": 10080,
                     "resets_at": budget_control._iso(NOW + timedelta(days=2))}
                    for name in GEMINI_WINDOWS]}, runner="worker_gemini")


def test_gemini_is_an_overflow_reviewer_not_the_first_choice(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    settings = _three_family_settings()
    _record(db, settings, "worker_gpt", {"seven_day": 0.05})
    _record(db, settings, "worker_claude", {"five_hour": 0.2, "seven_day": 0.2})
    _gemini_quota(db, settings)
    _enqueue(db, "draft", "c", runner="worker_claude")
    _enqueue(db, "review", "c", runner="balanced", task_type="paper_review",
             parent_task_id="draft", agent_role="reviewer", priority=5)
    task, _router = _claim(db, settings)
    assert task["task_id"] == "review" and task["runner"] in {"worker_gpt", "lead_gpt"}


def test_gemini_keeps_reviews_cross_family_when_the_other_family_is_out(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    settings = _three_family_settings()
    # GPT wrote the draft; Claude is at its ceiling: Gemini reviews instead of another GPT.
    _record(db, settings, "worker_gpt", {"seven_day": 0.05})
    _record(db, settings, "lead_gpt", {"seven_day": 0.05})
    for runner in ("worker_claude", "lead_claude"):
        _record(db, settings, runner, {"five_hour": 0.99, "seven_day": 0.99,
                                       "seven_day_overage_included": 0.99})
    _gemini_quota(db, settings)
    _enqueue(db, "draft", "c", runner="worker_gpt")
    _enqueue(db, "review", "c", runner="balanced", task_type="paper_review",
             parent_task_id="draft", agent_role="reviewer", priority=5)
    task, _router = _claim(db, settings)
    assert task["task_id"] == "review"
    assert settings.runners[task["runner"]].family == "google"
    event = _routed_events(db, "review")[0]
    assert event["excluded_provider"] == GPT
    assert "independence" not in event  # a real cross-family review, not a fallback


def test_gemini_takes_no_ordinary_work(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    settings = _three_family_settings()
    for runner in ("worker_gpt", "lead_gpt", "light_gpt"):
        _record(db, settings, runner, {"seven_day": 0.99})
    for runner in ("worker_claude", "lead_claude", "light_claude"):
        _record(db, settings, runner, {"five_hour": 0.99, "seven_day": 0.99,
                                       "seven_day_overage_included": 0.99})
    _gemini_quota(db, settings)
    _enqueue(db, "work", "c", runner="balanced")
    task, router = _claim(db, settings)
    assert task is None
    assert router.deferred["work"]["reason"] == "no_runner_available"


def test_antigravity_claude_counts_as_the_anthropic_family(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    agy_opus = RunnerSpec("worker_agy_opus", ANTIGRAVITY_PROVIDER, "worker",
                          "claude-opus-5-5-high", windows=("3p-weekly",), overflow=True,
                          task_classes=("review",))
    settings = replace(_settings(), runners={**RUNNERS, "worker_agy_opus": agy_opus})
    _record(db, settings, "worker_gpt", {"seven_day": 0.99})
    _record(db, settings, "lead_gpt", {"seven_day": 0.99})
    for runner in ("worker_claude", "lead_claude"):
        _record(db, settings, runner, {"five_hour": 0.2, "seven_day": 0.2,
                                       "seven_day_overage_included": 0.2})
    budget_control.record_quota_snapshot(db, settings, {
        "provider": ANTIGRAVITY_PROVIDER, "observed_at": budget_control._iso(NOW),
        "windows": [{"name": "3p-weekly", "used_fraction": 0.0, "window_minutes": 10080,
                     "resets_at": budget_control._iso(NOW + timedelta(days=2))}]},
        runner="worker_agy_opus")
    _enqueue(db, "draft", "c", runner="worker_claude")
    _enqueue(db, "review", "c", runner="balanced", task_type="paper_review",
             parent_task_id="draft", agent_role="reviewer", priority=5)
    task, router = _claim(db, settings)
    # Opus served by agy is still Claude: it never reviews Claude's own work.
    assert task is None or task["runner"] != "worker_agy_opus"


def test_antigravity_runner_is_bound_by_its_own_pool_only() -> None:
    worker = GEMINI["worker_gemini"]
    observed = ("gemini-weekly", "gemini-5h", "3p-weekly", "3p-5h", "gemini-argon-wtu-weekly")
    assert budget_control.runner_windows(worker, GEMINI, observed) == ("gemini-5h", "gemini-weekly")
    undeclared = replace(worker, windows=())
    assert budget_control.runner_windows(undeclared, {"w": undeclared}, observed) == tuple(
        sorted(observed))


def test_provider_summary_reads_the_gemini_pool(tmp_path) -> None:
    _paths_, db = _setup(tmp_path)
    settings = _three_family_settings()
    budget_control.record_quota_snapshot(db, settings, {
        "provider": ANTIGRAVITY_PROVIDER, "observed_at": budget_control._iso(NOW),
        "windows": [
            {"name": "gemini-weekly", "used_fraction": 0.1, "window_minutes": 10080,
             "resets_at": budget_control._iso(NOW + timedelta(days=2))},
            {"name": "gemini-argon-wtu-weekly", "used_fraction": 0.7, "window_minutes": 10080,
             "resets_at": budget_control._iso(NOW + timedelta(days=2))}]}, runner="worker_gemini")
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    summary = router.provider_summary()[ANTIGRAVITY_PROVIDER]
    assert summary["binding_window"] in {"gemini-weekly", "gemini-5h"}
    assert budget_control.shared_probe_spec(GEMINI.values(), ANTIGRAVITY_PROVIDER).name == (
        "worker_gemini")
