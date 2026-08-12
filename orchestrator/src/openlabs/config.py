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
    # Resource admission is the primary concurrency control. This is only a
    # final process-count fuse for tiny or incorrectly declared tasks.
    max_worker_processes: int = 8
    lease_seconds: int = 600
    heartbeat_seconds: int = 30
    max_attempts: int = 3
    retry_backoff_seconds: int = 120
    auto_continue: bool = True
    # Lifetime limit for bounded campaigns; renewable per-epoch limit for
    # campaigns bound to an active production plan.
    max_auto_tasks_per_campaign: int = 24
    max_task_wall_seconds: int = 14_400
    max_campaign_agent_seconds: int = 86_400
    launch_jobs: bool = True
    archive_result_receipts: bool = True
    reserve_cpu_threads: int = 2
    reserve_memory_mib: int = 8_192
    reserve_scratch_mib: int = 65_536
    default_task_cpu_threads: int = 2
    default_task_memory_mib: int = 4_096
    default_task_scratch_mib: int = 4_096


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


def _nonnegative_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def load_settings(paths: WorkspacePaths) -> FactorySettings:
    path = paths.code / "config" / "openlabs.toml"
    payload: dict[str, Any] = {}
    if path.is_file():
        with path.open("rb") as handle:
            payload = tomllib.load(handle)
    factory = payload.get("factory") if isinstance(payload.get("factory"), dict) else {}
    resources = payload.get("resources") if isinstance(payload.get("resources"), dict) else {}
    retention = payload.get("retention") if isinstance(payload.get("retention"), dict) else {}
    return FactorySettings(
        max_worker_processes=_positive_int(
            factory.get("max_worker_processes", factory.get("max_concurrent_jobs")), 8
        ),
        lease_seconds=_positive_int(factory.get("lease_seconds"), 600),
        heartbeat_seconds=_positive_int(factory.get("heartbeat_seconds"), 30),
        max_attempts=_positive_int(factory.get("max_attempts"), 3),
        retry_backoff_seconds=_positive_int(factory.get("retry_backoff_seconds"), 120),
        auto_continue=bool(factory.get("auto_continue", True)),
        max_auto_tasks_per_campaign=_positive_int(
            factory.get(
                "max_auto_tasks_per_epoch",
                factory.get("max_auto_tasks_per_campaign"),
            ),
            24,
        ),
        max_task_wall_seconds=_positive_int(factory.get("max_task_wall_seconds"), 14_400),
        max_campaign_agent_seconds=_positive_int(factory.get("max_campaign_agent_seconds"), 86_400),
        launch_jobs=bool(factory.get("launch_jobs", True)),
        archive_result_receipts=bool(retention.get("archive_result_receipts", True)),
        reserve_cpu_threads=_nonnegative_int(resources.get("reserve_cpu_threads"), 2),
        reserve_memory_mib=_nonnegative_int(resources.get("reserve_memory_mib"), 8_192),
        reserve_scratch_mib=_nonnegative_int(resources.get("reserve_scratch_mib"), 65_536),
        default_task_cpu_threads=_positive_int(resources.get("default_task_cpu_threads"), 2),
        default_task_memory_mib=_positive_int(resources.get("default_task_memory_mib"), 4_096),
        default_task_scratch_mib=_positive_int(resources.get("default_task_scratch_mib"), 4_096),
    )
