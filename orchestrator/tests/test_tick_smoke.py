from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from openlabs.config import FactorySettings, WorkspacePaths
from openlabs.db import FactoryDB
from openlabs.engine import tick

CODE_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = CODE_ROOT / "orchestrator" / "src"


@pytest.mark.parametrize("domain", ["math", "ai", "materials", "physics"])
def test_tick_launches_and_ingests_smoke_task(tmp_path, monkeypatch, domain: str) -> None:
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
    db = FactoryDB(paths.database_file)
    db.initialize()
    campaign_id = f"{domain}-smoke-campaign"
    task_id = f"{domain}-smoke-task"
    db.register_campaign(campaign_id, domain=domain, title=f"{domain} smoke")
    db.enqueue_task(
        task_id=task_id,
        campaign_id=campaign_id,
        domain=domain,
        task_type="smoke",
        objective="Exercise the complete file contract.",
    )
    settings = FactorySettings(
        max_worker_processes=1,
        lease_seconds=30,
        heartbeat_seconds=1,
        max_attempts=2,
        launch_jobs=True,
    )
    first = tick(paths, settings)
    assert first.launched == [task_id]
    running = db.task(task_id)
    assert running is not None
    receipt = paths.result_inbox / f"{task_id}-{running['current_attempt_id']}.json"
    deadline = time.monotonic() + 10
    while not receipt.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert receipt.is_file()
    second = tick(paths, settings)
    assert second.ingested == [{"task_id": task_id, "status": "succeeded"}]
    assert db.task(task_id)["status"] == "succeeded"
