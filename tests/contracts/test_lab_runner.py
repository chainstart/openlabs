from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

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
            "promotion_policy": "validated_completed_results_only",
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
