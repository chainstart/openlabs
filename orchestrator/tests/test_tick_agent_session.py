from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest
from openlabs.config import FactorySettings, WorkspacePaths
from openlabs.db import FactoryDB
from openlabs.engine import tick
from openlabs.reproduction import _bubblewrap_problem

CODE_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = CODE_ROOT / "orchestrator" / "src"


# The fake agent is not a native Codex adapter, so the lab runner puts it in the
# bubblewrap attempt sandbox; where namespaces are refused it fails closed.
@pytest.mark.skipif(
    _bubblewrap_problem(shutil.which("bwrap")) is not None,
    reason="bubblewrap cannot create a namespace here (e.g. Docker's default seccomp)",
)
def test_tick_records_and_resumes_one_researcher_session(tmp_path, monkeypatch) -> None:
    paths = WorkspacePaths(
        workspace=tmp_path,
        code=CODE_ROOT,
        data=tmp_path / "openlabs-data",
        artifacts=tmp_path / "openlabs-artifacts",
        database=tmp_path / "openlabs-database",
        database_file=tmp_path / "openlabs-database" / "live" / "factory.sqlite",
    )
    existing = os.environ.get("PYTHONPATH", "")
    monkeypatch.setenv(
        "PYTHONPATH",
        str(PACKAGE_ROOT) + (os.pathsep + existing if existing else ""),
    )
    agent_code = (
        "import json,sys; from pathlib import Path; "
        "task=json.loads(Path(sys.argv[1]).read_text()); "
        "result={'schema_version':'openlabs.result_bundle.v1','task_id':task['task_id'],"
        "'campaign_id':task['campaign_id'],'lab_id':task['lab_id'],'domain':task['domain'],"
        "'status':'completed','summary':'bounded step','artifacts':[],'claims':[],"
        "'next_actions':['continue with the frozen state'],'paper_candidate':False}; "
        "Path(sys.argv[2]).write_text(json.dumps(result)); "
        "print(json.dumps({'type':'thread.started','thread_id':'session-research-1'})); "
        "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':11,"
        "'cached_input_tokens':3,'output_tokens':7}}))"
    )
    monkeypatch.setenv(
        "OPENLABS_AGENT_COMMAND_BALANCED_JSON",
        json.dumps([sys.executable, "-c", agent_code, "{task_file}", "{output_file}"]),
    )
    db = FactoryDB(paths.database_file)
    db.initialize()
    # Session continuity is domain-neutral. Use a lab every host can launch: a
    # container without a dedicated math cgroup refuses math workers by design
    # (covered by test_tick_smoke and test_container_worker_launch).
    db.register_campaign("campaign", domain="ai", title="Campaign")
    db.enqueue_task(
        task_id="research",
        campaign_id="campaign",
        domain="ai",
        task_type="research",
        objective="Run one fake bounded Agent step.",
        runner="balanced",
    )
    settings = FactorySettings(
        max_worker_processes=1,
        lease_seconds=30,
        heartbeat_seconds=1,
        retry_backoff_seconds=0,
        max_auto_tasks_per_campaign=2,
        launch_jobs=True,
    )

    # Admission must not depend on the free space of the disk under tmp_path.
    monkeypatch.setattr(
        "openlabs.resources.shutil.disk_usage",
        lambda _path: shutil._ntuple_diskusage(512 * 1024**3, 0, 512 * 1024**3),
    )
    first = tick(paths, settings)
    assert first.launched == ["research"]
    deadline = time.monotonic() + 10
    while not list(paths.result_inbox.glob("*.json")) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert list(paths.result_inbox.glob("*.json"))

    second = tick(paths, settings)

    assert second.ingested == [{"task_id": "research", "status": "succeeded"}]
    assert len(second.enqueued) == 1
    successor = db.task(second.enqueued[0])
    assert successor is not None
    assert successor["agent_role"] == "researcher"
    assert successor["session_mode"] == "resume"
    assert successor["agent_session_id"] == "session-research-1"
    runtime = db.task_attempts("research")[0]["runtime"]
    assert runtime["session_id"] == "session-research-1"
    assert runtime["input_tokens"] == 11
    assert runtime["cached_input_tokens"] == 3
    assert runtime["output_tokens"] == 7
