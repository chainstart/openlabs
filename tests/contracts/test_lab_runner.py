from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

CODE_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = CODE_ROOT / "packages" / "research-core" / "lab_runner.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("openlabs_lab_runner", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_agent_process_group_is_terminated_and_reaped() -> None:
    runner = _load_runner()
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )
    time.sleep(0.05)

    runner._terminate_process_group(process, grace_seconds=1)

    assert process.poll() is not None


def test_lab_runtime_setup_runs_before_the_agent_and_returns_typed_context(tmp_path) -> None:
    runner = _load_runner()
    lab_root = tmp_path / "openlabs" / "labs" / "math"
    lab_root.mkdir(parents=True)
    manifest_path = lab_root / "lab.json"
    manifest_path.write_text("{}\n", encoding="utf-8")
    setup = lab_root / "prepare.py"
    setup.write_text(
        "import json,pathlib,sys\n"
        "target=pathlib.Path(sys.argv[1])/'.openlabs/tools/prepared.json'\n"
        "target.parent.mkdir(parents=True,exist_ok=True)\n"
        "target.write_text('{}\\n')\n"
        "print(json.dumps({'valid':True,'receipt_path':str(target)}))\n",
        encoding="utf-8",
    )
    workspace = tmp_path
    agent_workspace = tmp_path / "openlabs-artifacts" / "attempt-workspaces" / "campaign"
    agent_workspace.mkdir(parents=True)
    task = {
        "lab_manifest": str(manifest_path),
        "agent_workspace": str(agent_workspace),
        "transaction": {"attempt_root": str(agent_workspace.parent)},
    }
    manifest = {
        "runtime_setup": [
            {
                "setup_id": "test-runtime",
                "command": ["{python}", "prepare.py", "{agent_workspace}"],
                "timeout_seconds": 10,
            }
        ]
    }

    result = runner._lab_runtime_setup(
        task,
        manifest,
        workspace=workspace,
        agent_workspace=agent_workspace,
    )

    assert result["schema_version"] == "openlabs.lab_runtime_setup.v1"
    assert result["setups"][0]["setup_id"] == "test-runtime"
    assert Path(result["setups"][0]["receipt_path"]).is_file()


def test_sigterm_persists_recoverable_result_and_runtime(tmp_path) -> None:
    manifest_path = tmp_path / "openlabs" / "labs" / "math" / "lab.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "openlabs.lab.v1",
                "lab_id": "math",
                "domain": "math",
            }
        ),
        encoding="utf-8",
    )
    campaign_workspace = tmp_path / "openlabs-data" / "workspaces" / "math" / "campaign"
    output = campaign_workspace / "results" / "task-1" / "attempts" / "attempt-1" / "result.json"
    metadata = output.parent / "run-metadata.json"
    task_path = tmp_path / "task.json"
    task_path.write_text(
        json.dumps(
            {
                "schema_version": "openlabs.task.v3",
                "task_id": "task-1",
                "attempt_id": "attempt-1",
                "campaign_id": "campaign",
                "lab_id": "math",
                "domain": "math",
                "task_type": "research",
                "objective": "Exercise recoverable SIGTERM handling.",
                "lab_manifest": str(manifest_path),
                "skill_path": "skill.md",
                "runner": "balanced",
                "input_path": str(campaign_workspace),
                "output_path": str(output),
                "agent_workspace": str(campaign_workspace),
                "run_metadata_path": str(metadata),
                "resources": {
                    "cpu_threads": 2,
                    "memory_mib": 4096,
                    "scratch_mib": 4096,
                },
                "budget": {"wall_seconds": 60},
                "agent": {
                    "role": "researcher",
                    "session_mode": "resume",
                    "session_id": None,
                },
            }
        ),
        encoding="utf-8",
    )
    ready = output.parent / "agent-ready"
    command = [
        sys.executable,
        "-c",
        ("import pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text('ready'); time.sleep(60)"),
        str(ready),
    ]
    environment = dict(os.environ)
    environment["OPENLABS_WORKSPACE"] = str(tmp_path)
    environment["OPENLABS_AGENT_COMMAND_JSON"] = json.dumps(command)
    process = subprocess.Popen(
        [
            sys.executable,
            str(RUNNER_PATH),
            "--task",
            str(task_path),
            "--output",
            str(output),
        ],
        env=environment,
    )
    deadline = time.monotonic() + 5
    while not ready.is_file() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)

    assert ready.is_file()
    process.send_signal(signal.SIGTERM)
    assert process.wait(timeout=5) == 0

    result = json.loads(output.read_text(encoding="utf-8"))
    run_metadata = json.loads(metadata.read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert "persisted checkpoint" in result["next_actions"][0]
    assert run_metadata["runtime"]["interrupted"] is True
    assert run_metadata["runtime"]["termination_signal"] == signal.SIGTERM
    assert run_metadata["runtime"]["agent_exit_code"] == -signal.SIGTERM


def test_agent_runs_from_campaign_workspace(tmp_path, monkeypatch) -> None:
    runner = _load_runner()
    manifest_path = tmp_path / "openlabs" / "labs" / "math" / "lab.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{}", encoding="utf-8")
    output = tmp_path / "data" / "workspaces" / "math" / "campaign" / "result.json"
    campaign_workspace = output.parent
    command = [
        sys.executable,
        "-c",
        ("import json,os,sys; open(sys.argv[1],'w').write(json.dumps({'cwd': os.getcwd()}))"),
        "{output_file}",
    ]
    monkeypatch.setenv("OPENLABS_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("OPENLABS_AGENT_COMMAND_JSON", json.dumps(command))
    task = {
        "task_id": "task-1",
        "attempt_id": "attempt-1",
        "campaign_id": "campaign",
        "domain": "math",
        "objective": "Exercise runner cwd.",
        "lab_manifest": str(manifest_path),
        "skill_path": "skill.md",
        "runner": "balanced",
        "input_path": str(output.parent),
        "agent_workspace": str(campaign_workspace),
        "resources": {
            "cpu_threads": 2,
            "memory_mib": 4096,
            "scratch_mib": 4096,
        },
        "budget": {"wall_seconds": 60},
        "agent": {
            "role": "researcher",
            "session_mode": "resume",
            "session_id": None,
        },
    }

    runner._run_agent(task, {"domain": "math"}, output)

    assert json.loads(output.read_text(encoding="utf-8"))["cwd"] == str(campaign_workspace)


def test_transaction_sandbox_blocks_canonical_state_writes(tmp_path, monkeypatch) -> None:
    runner = _load_runner()
    manifest_path = tmp_path / "openlabs" / "labs" / "math" / "lab.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{}", encoding="utf-8")
    canonical = tmp_path / "openlabs-data" / "workspaces" / "math" / "campaign"
    canonical.mkdir(parents=True)
    canonical_file = canonical / "production_lane.json"
    canonical_file.write_text('{"nodes": []}\n', encoding="utf-8")
    attempt_root = tmp_path / "openlabs-artifacts" / "attempt-workspaces" / "attempt-1"
    staged = attempt_root / "workspaces" / "math" / "campaign"
    staged.mkdir(parents=True)
    output = staged / "result.json"
    command = [
        sys.executable,
        "-c",
        (
            "import json,pathlib,sys; canonical=pathlib.Path(sys.argv[1]); "
            "staged=pathlib.Path(sys.argv[2]); protected=False; "
            "\ntry: canonical.write_text('contaminated')"
            "\nexcept OSError: protected=True"
            "\nstaged.write_text('staged')"
            "\npathlib.Path(sys.argv[3]).write_text(json.dumps({'protected': protected}))"
        ),
        str(canonical_file),
        str(staged / "evidence.txt"),
        "{output_file}",
    ]
    monkeypatch.setenv("OPENLABS_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("OPENLABS_AGENT_COMMAND_JSON", json.dumps(command))
    task = {
        "task_id": "task-1",
        "attempt_id": "attempt-1",
        "campaign_id": "campaign",
        "domain": "math",
        "objective": "Exercise filesystem transaction isolation.",
        "lab_manifest": str(manifest_path),
        "skill_path": "skill.md",
        "runner": "balanced",
        "input_path": str(staged),
        "agent_workspace": str(staged),
        "resources": {"cpu_threads": 2, "memory_mib": 4096, "scratch_mib": 4096},
        "budget": {"wall_seconds": 30},
        "agent": {"role": "researcher", "session_mode": "fresh", "session_id": None},
        "transaction": {
            "mode": "isolated_attempt_workspace",
            "attempt_root": str(attempt_root),
            "staged_campaign_workspace": str(staged),
            "canonical_campaign_workspace": str(canonical),
            "promotion_policy": "validated_results_and_checkpoints",
        },
    }

    runtime = runner._run_agent(task, {"domain": "math"}, output)

    assert json.loads(output.read_text(encoding="utf-8"))["protected"] is True
    assert canonical_file.read_text(encoding="utf-8") == '{"nodes": []}\n'
    assert (staged / "evidence.txt").read_text(encoding="utf-8") == "staged"
    assert runtime["filesystem_sandbox"] == "bubblewrap"


def test_agent_resume_uses_only_the_declared_role_session(tmp_path, monkeypatch) -> None:
    runner = _load_runner()
    manifest_path = tmp_path / "openlabs" / "labs" / "math" / "lab.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{}", encoding="utf-8")
    campaign_workspace = tmp_path / "data" / "workspaces" / "math" / "campaign"
    output = campaign_workspace / "result.json"
    command = [
        sys.executable,
        "-c",
        "import json,sys; open(sys.argv[2],'w').write(json.dumps({'session':sys.argv[1]}))",
        "{session_id}",
        "{output_file}",
    ]
    monkeypatch.setenv("OPENLABS_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("OPENLABS_AGENT_RESUME_COMMAND_JSON", json.dumps(command))
    task = {
        "task_id": "task-1",
        "attempt_id": "attempt-1",
        "campaign_id": "campaign",
        "domain": "math",
        "objective": "Resume one role lineage.",
        "lab_manifest": str(manifest_path),
        "skill_path": "skill.md",
        "runner": "balanced",
        "input_path": str(campaign_workspace),
        "agent_workspace": str(campaign_workspace),
        "resources": {
            "cpu_threads": 2,
            "memory_mib": 4096,
            "scratch_mib": 4096,
        },
        "budget": {"wall_seconds": 60},
        "agent": {
            "role": "writer",
            "session_mode": "resume",
            "session_id": "writer-session",
        },
    }

    runtime = runner._run_agent(task, {"domain": "math", "lab_id": "math"}, output)

    assert json.loads(output.read_text(encoding="utf-8"))["session"] == "writer-session"
    assert runtime["resumed_from"] == "writer-session"
    request_path = Path(runtime["agent_request_path"])
    assert request_path == output.parent / "agent-request.md"
    assert runtime["agent_request_sha256"] == runner.sha256_file(request_path)


def test_codex_uses_full_access_and_generated_hooks(tmp_path) -> None:
    runner = _load_runner()
    workspace = tmp_path / "attempt" / "campaign"
    hooks = workspace / ".codex" / "hooks.json"
    hooks.parent.mkdir(parents=True)
    hooks.write_text("{}\n", encoding="utf-8")
    task = {
        "runtime_policy": {
            "schema_version": "openlabs.codex_runtime.v1",
            "hooks": str(hooks),
            "hook_trust": "orchestrator-generated",
        }
    }
    command = runner._prepare_codex_command(
        [
            "codex",
            "exec",
            "--sandbox",
            "danger-full-access",
            "--approve-for-me",
            "resume",
            "--json",
            "session-1",
            "-",
        ],
        agent_workspace=workspace,
        trust_generated_hooks=True,
    )

    wrapped, sandbox = runner._transaction_sandbox(command, task, tmp_path)

    assert wrapped == command
    assert command[:2] == ["codex", "exec"]
    assert 'approval_policy="never"' in command
    assert command[command.index("--sandbox") + 1] == "danger-full-access"
    assert "sandbox_workspace_write.network_access=true" not in command
    assert command[command.index("-C") + 1] == str(workspace)
    assert command.count("--json") == 1
    assert "--dangerously-bypass-hook-trust" in command
    assert command[command.index("--enable") + 1] == "hooks"
    assert command.index('approval_policy="never"') < command.index("resume")
    assert sandbox == "codex-native-danger-full-access"


def test_codex_connectivity_preflight_uses_configured_provider_and_accepts_http_error(
    monkeypatch,
) -> None:
    runner = _load_runner()
    seen: dict[str, object] = {}

    def reachable(request, *, timeout):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        raise runner.urllib.error.HTTPError(
            request.full_url,
            401,
            "authentication required",
            {},
            None,
        )

    monkeypatch.setattr(runner.urllib.request, "urlopen", reachable)
    monkeypatch.setenv("OPENLABS_AGENT_PREFLIGHT_TIMEOUT_SECONDS", "2.5")
    command = [
        "codex",
        "exec",
        "-c",
        'model_providers.local.base_url="https://provider.example/api/codex"',
        "-",
    ]

    assert runner._agent_connectivity_preflight(command) is None
    assert seen == {"url": "https://provider.example/api/codex", "timeout": 2.5}


def test_codex_connectivity_preflight_fails_closed_and_redacts_credentials(
    monkeypatch,
) -> None:
    runner = _load_runner()

    def unreachable(_request, *, timeout):
        assert timeout == 10.0
        raise runner.urllib.error.URLError("proxy refused connection")

    monkeypatch.setattr(runner.urllib.request, "urlopen", unreachable)
    monkeypatch.setenv("OPENLABS_AGENT_PREFLIGHT_STRICT", "true")
    command = [
        "codex",
        "exec",
        "-c",
        'model_providers.local.base_url="https://secret@example.test/backend"',
        "-",
    ]

    error = runner._agent_connectivity_preflight(command)

    assert error is not None
    assert "https://example.test" in error
    assert "secret" not in error


def test_codex_connectivity_preflight_is_advisory_by_default(monkeypatch) -> None:
    runner = _load_runner()

    def unreachable(_request, *, timeout):
        assert timeout == 10.0
        raise runner.urllib.error.URLError("direct HEAD timed out")

    monkeypatch.setattr(runner.urllib.request, "urlopen", unreachable)
    command = [
        "codex",
        "exec",
        "-c",
        'model_providers.local.base_url="https://provider.example/api/codex"',
        "-",
    ]

    assert runner._agent_connectivity_preflight(command) is None


def test_codex_startup_health_distinguishes_transport_loop_from_progress(tmp_path) -> None:
    runner = _load_runner()
    log = tmp_path / "agent-stdout.log"
    log.write_text(
        "\n".join(
            [
                json.dumps({"type": "thread.started", "thread_id": "session"}),
                json.dumps({"type": "turn.started"}),
                json.dumps({"type": "error", "message": "Connection failed"}),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "error", "message": "error sending request"},
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    failures, progressed = runner._jsonl_startup_health(log)

    assert failures == 2
    assert progressed is False
    with log.open("a", encoding="utf-8") as handle:
        handle.write(
            "\n"
            + json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "command_execution", "status": "completed"},
                }
            )
        )
    assert runner._jsonl_startup_health(log) == (2, True)


def test_codex_transport_loop_is_stopped_as_needs_human(tmp_path, monkeypatch) -> None:
    runner = _load_runner()
    fake_codex = tmp_path / "codex"
    fake_codex.write_text(
        "#!/usr/bin/env python3\n"
        "import json,sys,time\n"
        "sys.stdin.read()\n"
        "print(json.dumps({'type':'error','message':'Connection failed'}), flush=True)\n"
        "print(json.dumps({'type':'item.completed','item':"
        "{'type':'error','message':'error sending request'}}), flush=True)\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)
    workspace = tmp_path / "workspace"
    agent_workspace = workspace / "attempt"
    agent_workspace.mkdir(parents=True)
    manifest_path = workspace / "openlabs" / "labs" / "math" / "lab.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{}\n", encoding="utf-8")
    output = agent_workspace / "result.json"
    monkeypatch.setenv("OPENLABS_WORKSPACE", str(workspace))
    monkeypatch.setenv("OPENLABS_AGENT_COMMAND_JSON", json.dumps([str(fake_codex)]))
    monkeypatch.setenv("OPENLABS_AGENT_TRANSPORT_FAILURE_THRESHOLD", "2")
    monkeypatch.setattr(runner, "_validate_codex_transaction", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "_prepare_codex_command", lambda command, **kwargs: command)
    monkeypatch.setattr(runner, "_agent_connectivity_preflight", lambda _command: None)
    monkeypatch.setattr(runner, "_adapter_version", lambda _command: None)
    task = {
        "task_id": "network-loop",
        "attempt_id": "attempt-1",
        "campaign_id": "campaign",
        "lab_id": "math",
        "domain": "math",
        "objective": "Fail fast when the Agent transport is unavailable.",
        "lab_manifest": str(manifest_path),
        "runner": "balanced",
        "agent_workspace": str(agent_workspace),
        "resources": {"cpu_threads": 1, "memory_mib": 512, "scratch_mib": 512},
        "budget": {"wall_seconds": 30},
        "agent": {
            "role": "researcher",
            "session_mode": "fresh",
            "session_id": None,
        },
    }

    started = time.monotonic()
    runtime = runner._run_agent(
        task,
        {"lab_id": "math", "domain": "math"},
        output,
    )

    result = json.loads(output.read_text(encoding="utf-8"))
    assert time.monotonic() - started < 5
    assert result["status"] == "needs_human"
    assert runtime["failure_class"] == "agent_transport"
    assert runtime["transport_watchdog_triggered"] is True
    assert runtime["startup_transport_failure_count"] == 2


def test_runner_collects_structured_hook_receipts(tmp_path) -> None:
    runner = _load_runner()
    workspace = tmp_path / "attempt" / "campaign"
    receipt_path = workspace / ".codex" / "hook-receipts.jsonl"
    receipt_path.parent.mkdir(parents=True)
    events = [
        {
            "schema_version": "openlabs.codex_hook_receipt.v1",
            "hook_event_name": "SessionStart",
            "outcome": "context_injected",
        },
        {
            "schema_version": "openlabs.codex_hook_receipt.v1",
            "hook_event_name": "Stop",
            "outcome": "result_gate_blocked",
        },
        {
            "schema_version": "openlabs.codex_hook_receipt.v1",
            "hook_event_name": "Stop",
            "outcome": "result_gate_passed",
        },
        {
            "schema_version": "openlabs.codex_hook_receipt.v1",
            "hook_event_name": "Stop",
            "outcome": "result_gate_failed_final",
        },
    ]
    receipt_path.write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )

    runtime = runner._hook_runtime(receipt_path, agent_workspace=workspace)

    assert runtime["schema_version"] == "openlabs.hook_runtime.v1"
    assert runtime["session_start_count"] == 1
    assert runtime["stop_count"] == 3
    assert runtime["stop_passed"] is True
    assert runtime["stop_blocked"] == 1
    assert runtime["stop_failed_final"] == 1


def test_codex_adapter_enforces_factory_full_access_policy(tmp_path) -> None:
    runner = _load_runner()

    with pytest.raises(ValueError, match="full-access policy"):
        runner._prepare_codex_command(
            ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "-"],
            agent_workspace=tmp_path,
            trust_generated_hooks=False,
        )

    with pytest.raises(ValueError, match="do not need extra writable"):
        runner._prepare_codex_command(
            ["codex", "exec", "--add-dir", "/canonical", "-"],
            agent_workspace=tmp_path,
            trust_generated_hooks=False,
        )

    with pytest.raises(ValueError, match="runtime policy"):
        runner._prepare_codex_command(
            ["codex", "exec", "-c", 'sandbox_mode="workspace-write"', "-"],
            agent_workspace=tmp_path,
            trust_generated_hooks=False,
        )

    with pytest.raises(ValueError, match="runtime policy"):
        runner._prepare_codex_command(
            [
                "codex",
                "exec",
                "-c",
                "sandbox_workspace_write.network_access=false",
                "-",
            ],
            agent_workspace=tmp_path,
            trust_generated_hooks=False,
        )


def test_result_envelope_repairs_missing_transport_identity(tmp_path) -> None:
    runner = _load_runner()
    output = tmp_path / "result.json"
    output.write_text(
        json.dumps(
            {
                "status": "completed",
                "summary": "Scientific fields remain agent-owned.",
                "artifacts": [],
                "claims": [],
                "next_actions": [],
            }
        ),
        encoding="utf-8",
    )
    task = {
        "task_id": "task-1",
        "campaign_id": "campaign",
        "lab_id": "math",
        "domain": "math",
    }

    repaired, error = runner._seal_result_envelope(task, {"lab_id": "math"}, output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert repaired is True
    assert error is None
    assert payload["schema_version"] == "openlabs.result_bundle.v1"
    assert payload["task_id"] == "task-1"
    assert payload["lab_id"] == "math"
    assert payload["summary"] == "Scientific fields remain agent-owned."


def test_codex_transaction_requires_production_layout_outside_temporary_roots() -> None:
    runner = _load_runner()
    workspace = Path("/home/research/openlabs")
    attempt = workspace / "openlabs-artifacts" / "attempt-workspaces" / "one"
    staged = attempt / "workspaces" / "math" / "campaign"
    canonical = workspace / "openlabs-data" / "workspaces" / "math" / "campaign"
    task = {
        "transaction": {
            "mode": "isolated_attempt_workspace",
            "attempt_root": str(attempt),
            "staged_campaign_workspace": str(staged),
            "canonical_campaign_workspace": str(canonical),
            "artifact_staging_root": str(attempt / "artifact-stage"),
            "artifact_policy": {"schema_version": "openlabs.artifact_policy.v1"},
        }
    }

    runner._validate_codex_transaction(
        task,
        workspace=workspace,
        agent_workspace=staged,
    )

    task["transaction"]["artifact_staging_root"] = str(attempt / "wrong-stage")
    with pytest.raises(ValueError, match="attempt-private payload root"):
        runner._validate_codex_transaction(
            task,
            workspace=workspace,
            agent_workspace=staged,
        )

    temporary_workspace = Path("/tmp/openlabs")
    temporary_attempt = temporary_workspace / "openlabs-artifacts" / "attempt-workspaces" / "one"
    temporary_staged = temporary_attempt / "workspaces" / "math" / "campaign"
    temporary_task = {
        "transaction": {
            "mode": "isolated_attempt_workspace",
            "attempt_root": str(temporary_attempt),
            "staged_campaign_workspace": str(temporary_staged),
            "canonical_campaign_workspace": str(
                temporary_workspace / "openlabs-data" / "workspaces" / "math" / "campaign"
            ),
        }
    }
    with pytest.raises(ValueError, match="temporary root"):
        runner._validate_codex_transaction(
            temporary_task,
            workspace=temporary_workspace,
            agent_workspace=temporary_staged,
        )
