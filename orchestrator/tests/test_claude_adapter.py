"""Claude Code as a research executor: runtime parity with the Codex adapter.

No real ``claude`` process is started.  A fake executable named ``claude`` speaks
the stream-json protocol and runs the Stop/SessionStart hooks from the settings
file passed with ``--settings`` the way Claude Code does (JSON event on stdin,
``{"decision": "block", "reason"}`` on stdout continues the turn).
"""

from __future__ import annotations

import importlib.util
import json
import shlex
import subprocess
import sys
import textwrap
from dataclasses import replace
from pathlib import Path

import pytest
from openlabs import engine
from openlabs.agent_runtime import HOOK_GATED_ADAPTERS, configure_codex_runtime
from openlabs.config import BudgetSettings, FactorySettings, WorkspacePaths
from openlabs.contracts import RECEIPT_SCHEMA, RESULT_SCHEMA, atomic_write_json, sha256_file
from openlabs.db import FactoryDB
from openlabs.engine import TickReport, ingest_results

CODE_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "openlabs_claude_adapter_lab_runner",
    CODE_ROOT / "packages" / "research-core" / "lab_runner.py",
)
assert _SPEC is not None and _SPEC.loader is not None
lab_runner = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(lab_runner)

FAKE_CLAUDE = textwrap.dedent(
    r'''
    #!/usr/bin/env python3
    """Minimal stand-in for `claude -p --output-format stream-json --verbose`."""
    import json, os, re, subprocess, sys, time

    argv = sys.argv[1:]
    record = os.environ.get("FAKE_CLAUDE_ARGV")
    if record:
        open(record, "w").write(json.dumps(argv))
    mode = os.environ.get("FAKE_CLAUDE_MODE", "write")
    prompt = sys.stdin.read()
    if mode == "silent":
        time.sleep(60)
        sys.exit(0)

    def emit(event):
        print(json.dumps(event), flush=True)

    session = argv[argv.index("--resume") + 1] if "--resume" in argv else "fake-session-1"
    emit({"type": "system", "subtype": "init", "session_id": session,
          "model": "claude-opus-5-5", "cwd": os.getcwd()})
    if mode == "retry":
        for attempt in (1, 2, 3):
            emit({"type": "system", "subtype": "api_retry", "attempt": attempt,
                  "max_retries": 10, "retry_delay_ms": 500, "error_status": None,
                  "error": "Connection error.", "session_id": session})
        time.sleep(60)
        sys.exit(1)

    settings = json.load(open(argv[argv.index("--settings") + 1]))
    transcript = os.path.join(os.getcwd(), "fake-transcript.jsonl")

    def run_hooks(event_name, payload):
        outputs = []
        for group in settings.get("hooks", {}).get(event_name, []):
            for hook in group["hooks"]:
                completed = subprocess.run(
                    hook["command"], shell=True, input=json.dumps(payload),
                    text=True, capture_output=True, timeout=hook.get("timeout", 60),
                )
                if completed.returncode != 0:
                    sys.stderr.write(completed.stderr)
                outputs.append(json.loads(completed.stdout or "{}"))
        return outputs

    base = {"session_id": session, "transcript_path": transcript, "cwd": os.getcwd()}
    run_hooks("SessionStart", {**base, "hook_event_name": "SessionStart",
                               "source": "resume" if "--resume" in argv else "startup"})
    emit({"type": "assistant", "session_id": session,
          "message": {"model": "claude-opus-5-5",
                      "content": [{"type": "text", "text": "Working."}]}})
    result_path = re.search(r"required result path: `([^`]+)`", prompt).group(1)

    def write_result():
        with open(result_path, "w") as handle:
            json.dump({"schema_version": "openlabs.result_bundle.v1", "task_id": "task-1",
                       "campaign_id": "campaign", "lab_id": "math", "domain": "math",
                       "status": "completed", "summary": "Fake Claude finished the step.",
                       "artifacts": [], "claims": [], "next_actions": []}, handle)

    if mode == "write-first":
        write_result()
    stop_hook_active = False
    while True:
        outputs = run_hooks("Stop", {**base, "hook_event_name": "Stop",
                                     "stop_hook_active": stop_hook_active})
        blocked = [item for item in outputs if item.get("decision") == "block"]
        if not blocked:
            break
        # Claude feeds the reason back to the model and continues the turn.
        emit({"type": "user", "session_id": session,
              "message": {"content": [{"type": "text", "text": blocked[0]["reason"]}]}})
        if mode == "write":
            write_result()
        stop_hook_active = True
    emit({"type": "rate_limit_event", "session_id": session,
          "rate_limit_info": {"unifiedWindows": {"five_hour": {"utilization": 0.25}}}})
    emit({"type": "result", "subtype": "success", "is_error": False, "session_id": session,
          "usage": {"input_tokens": 11, "output_tokens": 7, "cache_read_input_tokens": 3},
          "total_cost_usd": 0.01})
    '''
).lstrip()


def _skill(path: Path, name: str) -> None:
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Test Skill.\n---\n\n# Test\n", encoding="utf-8"
    )


def _layout(tmp_path: Path, *, session_id: str | None = None) -> dict:
    """An attempt layout like the engine's, with generated runtime policy."""

    workspace = tmp_path / "factory"
    manifest_path = workspace / "openlabs" / "labs" / "math" / "lab.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps({"lab_id": "math", "domain": "math"}), encoding="utf-8")
    attempt_root = workspace / "openlabs-artifacts" / "attempt-workspaces" / "attempt-1"
    staged = attempt_root / "workspaces" / "math" / "campaign"
    staged.mkdir(parents=True)
    (attempt_root / "artifact-stage").mkdir()
    canonical = workspace / "openlabs-data" / "workspaces" / "math" / "campaign"
    canonical.mkdir(parents=True)
    output = staged / "results" / "task-1" / "attempts" / "attempt-1" / "result.json"
    skill = workspace / "openlabs" / "skills" / "domain-skill"
    _skill(skill, "domain-skill")
    task = {
        "schema_version": "openlabs.task.v3",
        "task_id": "task-1",
        "attempt_id": "attempt-1",
        "campaign_id": "campaign",
        "lab_id": "math",
        "domain": "math",
        "task_type": "research",
        "objective": "Advance one bounded step.",
        "lab_manifest": str(manifest_path),
        "skill_path": str(skill / "SKILL.md"),
        "runner": "worker_claude",
        "input_path": str(staged),
        "output_path": str(output),
        "agent_workspace": str(staged),
        "run_metadata_path": str(output.parent / "run-metadata.json"),
        "resources": {"cpu_threads": 1, "memory_mib": 512, "scratch_mib": 512},
        "budget": {"wall_seconds": 60},
        "agent": {
            "role": "researcher",
            "session_mode": "resume" if session_id else "fresh",
            "session_id": session_id,
        },
        "transaction": {
            "mode": "isolated_attempt_workspace",
            "attempt_root": str(attempt_root),
            "staged_campaign_workspace": str(staged),
            "canonical_campaign_workspace": str(canonical),
            "artifact_staging_root": str(attempt_root / "artifact-stage"),
            "promotion_policy": "validated_results_and_checkpoints",
        },
    }
    task["runtime_policy"] = configure_codex_runtime(
        staged, task=task, output_path=output, skill_dirs=(skill,)
    )
    fake = tmp_path / "bin" / "claude"
    fake.parent.mkdir()
    fake.write_text(FAKE_CLAUDE.replace("/usr/bin/env python3", sys.executable, 1))
    fake.chmod(0o755)
    return {
        "workspace": workspace,
        "attempt_root": attempt_root,
        "staged": staged,
        "output": output,
        "task": task,
        "manifest": {"lab_id": "math", "domain": "math"},
        "fake": fake,
        "argv_record": tmp_path / "claude-argv.json",
    }


@pytest.fixture
def claude_env(monkeypatch):
    """Run the fake under the real policy, minus bubblewrap (absent on this host)."""

    validated: list[str] = []

    def record_validation(task, *, workspace, agent_workspace, agent_label="Codex"):
        validated.append(agent_label)

    def no_bwrap(command, task, workspace):
        assert Path(command[0]).name == "claude"
        return command, "bubblewrap"

    monkeypatch.setattr(lab_runner, "_validate_codex_transaction", record_validation)
    monkeypatch.setattr(lab_runner, "_transaction_sandbox", no_bwrap)
    monkeypatch.setattr(lab_runner, "_adapter_version", lambda _command: "2.1.322 (Claude Code)")
    for name in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    return validated


def _configure(monkeypatch, layout: dict, *, mode: str, resume: bool = False) -> None:
    monkeypatch.setenv("OPENLABS_WORKSPACE", str(layout["workspace"]))
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    monkeypatch.setenv("FAKE_CLAUDE_ARGV", str(layout["argv_record"]))
    fake = str(layout["fake"])
    fresh = [fake, "-p", "--output-format", "stream-json", "--verbose",
             "--model", "claude-opus-5-5"]
    monkeypatch.setenv("OPENLABS_AGENT_COMMAND_WORKER_CLAUDE_JSON", json.dumps(fresh))
    if resume:
        resumed = [fake, "-p", "--resume", "{session_id}", "--output-format", "stream-json",
                   "--verbose", "--model", "claude-opus-5-5"]
        monkeypatch.setenv("OPENLABS_AGENT_RESUME_COMMAND_WORKER_CLAUDE_JSON", json.dumps(resumed))


# ------------------------------------------------------------ generated runtime


def test_runtime_generates_claude_settings_skills_and_unchanged_codex_hooks(tmp_path) -> None:
    layout = _layout(tmp_path)
    staged = layout["staged"]
    policy = layout["task"]["runtime_policy"]

    settings_path = staged / ".claude" / "openlabs-settings.json"
    assert policy["claude_settings"] == str(settings_path)
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    # Hooks only: a settings file that fails validation is silently ignored.
    assert set(settings) == {"hooks"}
    assert set(settings["hooks"]) == {"SessionStart", "Stop"}
    assert settings["hooks"]["SessionStart"][0]["matcher"] == "startup|resume|clear|compact"
    stop = settings["hooks"]["Stop"][0]["hooks"][0]
    assert stop["type"] == "command" and stop["timeout"] == 330
    context = staged / ".codex" / "openlabs-context.json"
    assert shlex.split(stop["command"]) == [
        "/usr/bin/env",
        f"PYTHONPATH={CODE_ROOT / 'orchestrator' / 'src'}",
        sys.executable,
        "-m",
        "openlabs.codex_hook",
        "stop",
        "--context",
        str(context),
        "--adapter",
        "claude",
    ]
    # Codex keeps the same command without the adapter switch.
    codex_hooks = json.loads((staged / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    codex_stop = codex_hooks["hooks"]["Stop"][0]["hooks"][0]["command"]
    assert shlex.split(codex_stop) == shlex.split(stop["command"])[:-2]
    # Claude Code discovers project Skills under .claude/skills.
    linked = staged / ".claude" / "skills" / "domain-skill"
    assert linked.is_symlink()
    assert linked.resolve() == (staged / ".agents" / "skills" / "domain-skill").resolve()


def test_claude_session_start_hook_names_skills_for_the_skill_tool(tmp_path) -> None:
    layout = _layout(tmp_path)
    staged = layout["staged"]
    settings = json.loads((staged / ".claude" / "openlabs-settings.json").read_text())
    command = settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]

    completed = subprocess.run(
        command, shell=True, cwd=staged, text=True, capture_output=True, check=False,
        input=json.dumps({"session_id": "s-1", "hook_event_name": "SessionStart",
                          "transcript_path": "/home/x/.claude/projects/p/s-1.jsonl"}),
        env={"PATH": "/usr/bin:/bin"},
    )

    assert completed.returncode == 0, completed.stderr
    message = json.loads(completed.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "domain-skill (Skill tool)" in message and "$domain-skill" not in message
    assert str(staged / ".claude" / "skills") in message
    receipt = json.loads((staged / ".codex" / "hook-receipts.jsonl").read_text())
    assert receipt["agent_adapter"] == "claude"
    assert receipt["transcript_path"] == "/home/x/.claude/projects/p/s-1.jsonl"


def test_agent_request_is_adapter_specific_and_codex_text_is_unchanged(tmp_path) -> None:
    layout = _layout(tmp_path)
    task = dict(layout["task"])
    codex = lab_runner._agent_request(task, layout["manifest"], layout["output"], adapter="codex")
    default = lab_runner._agent_request(task, layout["manifest"], layout["output"])
    claude = lab_runner._agent_request(task, layout["manifest"], layout["output"], adapter="claude")

    assert codex == default
    assert "Invoke and follow $domain-skill; read their trusted project copies under" in codex
    assert "inside this Codex process" in codex
    assert "Invoke and follow the Skills domain-skill with the Skill tool" in claude
    assert "`.claude/skills/`" in claude
    assert "inside this Claude Code process" in claude


# ------------------------------------------------------------ command policy


def test_claude_command_policy_is_enforced(tmp_path) -> None:
    settings = tmp_path / ".claude" / "openlabs-settings.json"
    settings.parent.mkdir()
    settings.write_text('{"hooks": {}}\n')
    attempt_root = tmp_path / "attempt"

    command = lab_runner._prepare_claude_command(
        ["claude", "-p", "--output-format", "stream-json", "--verbose",
         "--allowedTools", "Bash(git *)", "Read", "--model", "claude-opus-5-5"],
        settings_path=settings,
        attempt_root=attempt_root,
    )

    assert command == [
        "claude", "-p",
        "--add-dir", str(attempt_root),
        "--allowedTools", ",".join(lab_runner.CLAUDE_ALLOWED_TOOLS),
        "--permission-mode", "dontAsk",
        "--setting-sources", "project",
        "--settings", str(settings),
        "--output-format", "stream-json",
        "--verbose",
        "--model", "claude-opus-5-5",
    ]
    for forbidden in (
        ["--dangerously-skip-permissions"],
        ["--allow-dangerously-skip-permissions"],
        ["--permission-mode", "bypassPermissions"],
        ["--bare"],
        ["--safe-mode"],
        ["--disable-slash-commands"],
        ["--settings", "/home/me/.claude/settings.json"],
        ["--setting-sources", "user"],
        ["--output-format", "json"],
    ):
        with pytest.raises(ValueError):
            lab_runner._prepare_claude_command(
                ["claude", "-p", *forbidden], settings_path=settings, attempt_root=attempt_root
            )
    with pytest.raises(ValueError, match="settings with the result-gate hooks are missing"):
        lab_runner._prepare_claude_command(
            ["claude", "-p"], settings_path=tmp_path / "missing.json", attempt_root=attempt_root
        )


def test_claude_resume_command_keeps_the_session_and_adds_the_policy(tmp_path) -> None:
    settings = tmp_path / "openlabs-settings.json"
    settings.write_text('{"hooks": {}}\n')

    command = lab_runner._prepare_claude_command(
        ["claude", "-p", "--resume", "sess-42", "--output-format", "stream-json", "--verbose",
         "--model", "claude-fable-5-2"],
        settings_path=settings,
        attempt_root=tmp_path,
    )

    assert command[command.index("--resume") + 1] == "sess-42"
    assert command[command.index("--model") + 1] == "claude-fable-5-2"
    assert command.count("-p") == 1 and command.count("--verbose") == 1
    assert command[command.index("--settings") + 1] == str(settings)


def test_claude_uses_the_bubblewrap_transaction_sandbox(tmp_path, monkeypatch) -> None:
    layout = _layout(tmp_path)
    monkeypatch.setattr(lab_runner.shutil, "which", lambda _name: "/usr/bin/bwrap")
    command = ["claude", "-p", "--model", "claude-opus-5-5"]

    wrapped, sandbox = lab_runner._transaction_sandbox(
        command, layout["task"], layout["workspace"].resolve()
    )

    assert sandbox == "bubblewrap"
    assert wrapped[0] == "/usr/bin/bwrap" and wrapped[-len(command):] == command
    attempt = str(layout["attempt_root"].resolve())
    assert wrapped[wrapped.index("--") - 2 : wrapped.index("--")] == [attempt, attempt]
    # Codex keeps its native full-access runtime.
    assert lab_runner._transaction_sandbox(["codex", "exec"], layout["task"], tmp_path) == (
        ["codex", "exec"],
        "codex-native-danger-full-access",
    )


def test_claude_requires_the_isolated_transaction(tmp_path) -> None:
    with pytest.raises(ValueError, match="Claude Code research tasks require an isolated"):
        lab_runner._validate_codex_transaction(
            {}, workspace=tmp_path, agent_workspace=tmp_path, agent_label="Claude Code"
        )


# ------------------------------------------------------------ result gate end to end


def test_fake_claude_without_result_is_blocked_then_fails_closed(
    tmp_path, monkeypatch, claude_env
) -> None:
    layout = _layout(tmp_path)
    _configure(monkeypatch, layout, mode="never")

    runtime = lab_runner._run_agent(layout["task"], layout["manifest"], layout["output"])

    hooks = runtime["hooks"]
    assert hooks["stop_blocked"] == 1
    assert hooks["stop_failed_final"] == 1
    assert hooks["stop_passed"] is False
    assert hooks["session_start_count"] == 1
    assert {event["agent_adapter"] for event in hooks["events"]} == {"claude"}
    assert hooks["events"][1]["outcome"] == "result_gate_blocked"
    assert "required result file is missing" in hooks["events"][1]["output_summary"]
    # No bundle: the runner writes a non-committable placeholder.
    result = json.loads(layout["output"].read_text())
    assert result["status"] == "needs_replan"
    assert runtime["adapter"] == "claude" and runtime["session_id"] == "fake-session-1"
    error, _warning = engine._codex_hook_receipt_status(runtime)
    assert error == "Claude Code final Stop gate receipt is incomplete"
    assert claude_env == ["Claude Code"]


def test_fake_claude_is_released_after_writing_result_and_leaves_receipts(
    tmp_path, monkeypatch, claude_env
) -> None:
    layout = _layout(tmp_path)
    _configure(monkeypatch, layout, mode="write")

    runtime = lab_runner._run_agent(layout["task"], layout["manifest"], layout["output"])

    hooks = runtime["hooks"]
    assert [event["outcome"] for event in hooks["events"]] == [
        "context_injected",
        "result_gate_blocked",
        "result_gate_passed",
    ]
    assert hooks["stop_passed"] is True
    assert engine._codex_hook_receipt_status(runtime) == (None, None)
    result = json.loads(layout["output"].read_text())
    assert result["status"] == "completed"
    assert result["schema_version"] == RESULT_SCHEMA
    assert "failure_class" not in runtime
    assert runtime["filesystem_sandbox"] == "bubblewrap"
    assert runtime["input_tokens"] == 11 and runtime["cached_input_tokens"] == 3
    assert runtime["quota_snapshot"]["provider"] == "anthropic"
    assert runtime["claude_endpoint"] == {
        "mode": "default_login", "host": None, "api_key_env": False,
    }
    argv = json.loads(layout["argv_record"].read_text())
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert argv[argv.index("--settings") + 1] == str(
        layout["staged"].resolve() / ".claude" / "openlabs-settings.json"
    )
    assert argv[argv.index("--add-dir") + 1] == str(layout["attempt_root"].resolve())
    assert "--dangerously-skip-permissions" not in argv


def test_fake_claude_resume_uses_the_role_session(tmp_path, monkeypatch, claude_env) -> None:
    layout = _layout(tmp_path, session_id="prior-session")
    _configure(monkeypatch, layout, mode="write-first", resume=True)

    runtime = lab_runner._run_agent(layout["task"], layout["manifest"], layout["output"])

    argv = json.loads(layout["argv_record"].read_text())
    assert argv[argv.index("--resume") + 1] == "prior-session"
    assert runtime["resumed_from"] == "prior-session"
    assert runtime["session_id"] == "prior-session"
    assert [event["outcome"] for event in runtime["hooks"]["events"]] == [
        "context_injected",
        "result_gate_passed",
    ]


# ------------------------------------------------------------ startup watchdog


def test_claude_startup_health_reads_stream_json(tmp_path) -> None:
    log = tmp_path / "agent-stdout.log"
    assert lab_runner._claude_startup_health(log) == (0, False, False)
    log.write_text(json.dumps({"type": "system", "subtype": "init", "session_id": "s"}) + "\n")
    assert lab_runner._claude_startup_health(log) == (0, False, True)
    with log.open("a") as handle:
        handle.write(json.dumps({"type": "system", "subtype": "api_retry", "error_status": None,
                                 "error": "Connection error."}) + "\n")
        handle.write(json.dumps({"type": "system", "subtype": "api_retry", "error_status": 429,
                                 "error": "rate_limit"}) + "\n")
    assert lab_runner._claude_startup_health(log) == (1, False, True)
    with log.open("a") as handle:
        handle.write(json.dumps({"type": "assistant", "message": {"content": []}}) + "\n")
    assert lab_runner._claude_startup_health(log) == (1, True, True)


def test_watchdog_stops_a_silent_claude_process(tmp_path, monkeypatch, claude_env) -> None:
    layout = _layout(tmp_path)
    _configure(monkeypatch, layout, mode="silent")
    monkeypatch.setenv("OPENLABS_AGENT_STARTUP_GRACE_SECONDS", "1")

    runtime = lab_runner._run_agent(layout["task"], layout["manifest"], layout["output"])

    assert runtime["transport_watchdog_triggered"] is True
    assert runtime["startup_stream_silent"] is True
    assert runtime["failure_class"] == "agent_transport"
    assert json.loads(layout["output"].read_text())["status"] == "needs_human"


def test_watchdog_stops_claude_connection_retries(tmp_path, monkeypatch, claude_env) -> None:
    layout = _layout(tmp_path)
    _configure(monkeypatch, layout, mode="retry")
    monkeypatch.setenv("OPENLABS_AGENT_TRANSPORT_FAILURE_THRESHOLD", "2")

    runtime = lab_runner._run_agent(layout["task"], layout["manifest"], layout["output"])

    assert runtime["transport_watchdog_triggered"] is True
    assert runtime["startup_stream_silent"] is False
    assert runtime["startup_transport_failure_count"] >= 2
    assert runtime["failure_class"] == "agent_transport"


# ------------------------------------------------------------ lab runtime preparation


@pytest.mark.parametrize(
    ("executable", "prepared"),
    [("claude", True), ("codex", True), (sys.executable, False)],
)
def test_native_adapters_receive_the_trusted_lab_runtime(
    tmp_path, monkeypatch, executable, prepared
) -> None:
    layout = _layout(tmp_path)
    task = layout["task"]
    task["runner"] = "balanced"
    task_path = tmp_path / "task.json"
    task_path.write_text(json.dumps(task), encoding="utf-8")
    monkeypatch.setenv("OPENLABS_WORKSPACE", str(layout["workspace"]))
    monkeypatch.setenv("OPENLABS_AGENT_COMMAND_JSON", json.dumps([executable, "-p"]))
    calls: list[dict] = []

    def fake_setup(task, manifest, *, workspace, agent_workspace):
        calls.append({"agent_workspace": agent_workspace})
        return {"schema_version": lab_runner.LAB_RUNTIME_SCHEMA, "setups": [{"setup_id": "x"}]}

    def fake_run(task, manifest, output):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("{}")
        return {"adapter": Path(executable).name, "seen_lab_runtime": task["lab_runtime"]}

    monkeypatch.setattr(lab_runner, "_lab_runtime_setup", fake_setup)
    monkeypatch.setattr(lab_runner, "_run_agent", fake_run)
    monkeypatch.setattr(
        sys, "argv", ["lab_runner", "--task", str(task_path), "--output", task["output_path"]]
    )

    assert lab_runner.main() == 0

    metadata = json.loads(Path(task["run_metadata_path"]).read_text())["runtime"]
    if prepared:
        assert calls and metadata["seen_lab_runtime"]["setups"] == [{"setup_id": "x"}]
    else:
        assert not calls and metadata["lab_runtime"]["skipped"] == "non-Codex adapter"


# ------------------------------------------------------------ engine receipt check


def _paths(tmp_path: Path) -> WorkspacePaths:
    paths = WorkspacePaths(
        workspace=tmp_path,
        code=tmp_path / "openlabs",
        data=tmp_path / "data",
        artifacts=tmp_path / "artifacts",
        database=tmp_path / "database",
        database_file=tmp_path / "database" / "live" / "factory.sqlite",
    )
    paths.ensure_runtime_directories()
    return paths


def _ingest_completed(tmp_path: Path, runtime_extra: dict) -> dict:
    paths = _paths(tmp_path)
    db = FactoryDB(paths.database_file)
    db.initialize()
    db.register_campaign("c", domain="math", title="c")
    db.enqueue_task(task_id="t", campaign_id="c", domain="math", task_type="research",
                    objective="Bounded step.", runner="balanced")
    task = db.claim_next_task(owner="test", lease_seconds=600)
    attempt_id = str(task["current_attempt_id"])
    output = paths.data / "workspaces" / "math" / "c" / attempt_id / "r.json"
    db.bind_attempt_spec("t", attempt_id=attempt_id, lab_id="math", output_path=str(output))
    db.mark_running("t", attempt_id=attempt_id, owner="test", pid=1, lease_seconds=600)
    atomic_write_json(output, {
        "schema_version": RESULT_SCHEMA, "task_id": "t", "campaign_id": "c",
        "lab_id": "math", "domain": "math", "status": "completed", "summary": "Agent step.",
        "artifacts": [], "claims": [], "next_actions": [],
    })
    atomic_write_json(paths.result_inbox / f"{attempt_id}.json", {
        "schema_version": RECEIPT_SCHEMA, "task_id": "t", "attempt_id": attempt_id,
        "campaign_id": "c", "lab_id": "math", "domain": "math",
        "agent_role": "researcher", "result_path": str(output),
        "sha256": sha256_file(output),
        "runtime": {"duration_seconds": 2.0, "exit_code": 0, "runner": "balanced",
                    **runtime_extra},
    })
    settings = replace(FactorySettings(budget=BudgetSettings()), auto_continue=False)
    ingest_results(db, paths, settings, TickReport())
    return db.task_attempts("t")[-1]["runtime"]


@pytest.mark.parametrize(("adapter", "label"), [("codex", "Codex"), ("claude", "Claude Code")])
def test_engine_rejects_missing_receipts_for_claude_like_codex(tmp_path, adapter, label) -> None:
    assert adapter in HOOK_GATED_ADAPTERS
    runtime = _ingest_completed(tmp_path, {"adapter": adapter, "session_id": "s"})

    expected = f"{label} lifecycle hook receipts are missing or invalid"
    assert runtime["hook_receipt_error"] == expected


@pytest.mark.parametrize("adapter", ["codex", "claude"])
def test_engine_accepts_a_passing_stop_receipt(tmp_path, adapter) -> None:
    hooks = {"schema_version": "openlabs.hook_runtime.v1", "session_start_count": 1,
             "stop_passed": True}
    runtime = _ingest_completed(tmp_path, {"adapter": adapter, "session_id": "s",
                                           "hooks": hooks})

    assert "hook_receipt_error" not in runtime


def test_transport_doubles_are_not_hook_gated(tmp_path) -> None:
    runtime = _ingest_completed(tmp_path, {"adapter": "python3", "session_id": "s"})

    assert "hook_receipt_error" not in runtime
