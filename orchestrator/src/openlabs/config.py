"""Workspace discovery and small TOML configuration loader."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WorkspacePaths:
    workspace: Path
    code: Path
    data: Path
    artifacts: Path
    database: Path
    database_file: Path

    @property
    def job_inbox(self) -> Path:
        return self.data / "inbox" / "jobs"

    @property
    def result_inbox(self) -> Path:
        return self.data / "inbox" / "results"

    @property
    def receipt_archive(self) -> Path:
        return self.data / "ledger" / "receipts"

    def ensure_runtime_directories(self) -> None:
        for path in (
            self.data,
            self.artifacts,
            self.database,
            self.job_inbox,
            self.result_inbox,
            self.receipt_archive,
        ):
            path.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class FactorySettings:
    max_concurrent_jobs: int = 2
    lease_seconds: int = 600
    heartbeat_seconds: int = 30
    max_attempts: int = 3
    retry_backoff_seconds: int = 120
    auto_continue: bool = True
    max_auto_tasks_per_campaign: int = 24
    max_task_wall_seconds: int = 14_400
    max_campaign_agent_seconds: int = 86_400
    launch_jobs: bool = True
    archive_result_receipts: bool = True


def _default_workspace() -> Path:
    # .../openlabs/openlabs/orchestrator/src/openlabs/config.py -> outer workspace
    return Path(__file__).resolve().parents[4]


def workspace_paths(explicit: str | Path | None = None) -> WorkspacePaths:
    configured = explicit or os.environ.get("OPENLABS_WORKSPACE")
    workspace = Path(configured).expanduser().resolve() if configured else _default_workspace()
    code = workspace / "openlabs"
    return WorkspacePaths(
        workspace=workspace,
        code=code,
        data=workspace / "openlabs-data",
        artifacts=workspace / "openlabs-artifacts",
        database=workspace / "openlabs-database",
        database_file=workspace / "openlabs-database" / "live" / "factory.sqlite",
    )


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def load_settings(paths: WorkspacePaths) -> FactorySettings:
    path = paths.code / "config" / "openlabs.toml"
    payload: dict[str, Any] = {}
    if path.is_file():
        with path.open("rb") as handle:
            payload = tomllib.load(handle)
    factory = payload.get("factory") if isinstance(payload.get("factory"), dict) else {}
    retention = payload.get("retention") if isinstance(payload.get("retention"), dict) else {}
    return FactorySettings(
        max_concurrent_jobs=_positive_int(factory.get("max_concurrent_jobs"), 2),
        lease_seconds=_positive_int(factory.get("lease_seconds"), 600),
        heartbeat_seconds=_positive_int(factory.get("heartbeat_seconds"), 30),
        max_attempts=_positive_int(factory.get("max_attempts"), 3),
        retry_backoff_seconds=_positive_int(factory.get("retry_backoff_seconds"), 120),
        auto_continue=bool(factory.get("auto_continue", True)),
        max_auto_tasks_per_campaign=_positive_int(
            factory.get("max_auto_tasks_per_campaign"), 24
        ),
        max_task_wall_seconds=_positive_int(
            factory.get("max_task_wall_seconds"), 14_400
        ),
        max_campaign_agent_seconds=_positive_int(
            factory.get("max_campaign_agent_seconds"), 86_400
        ),
        launch_jobs=bool(factory.get("launch_jobs", True)),
        archive_result_receipts=bool(retention.get("archive_result_receipts", True)),
    )
