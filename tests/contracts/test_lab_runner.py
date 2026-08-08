from __future__ import annotations

import importlib.util
import json
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
