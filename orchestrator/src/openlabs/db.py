"""SQLite state store for campaigns, tasks, leases, results, and events."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 8
ACTIVE_STATUSES = ("leased", "running")
AGENT_ROLES = ("researcher", "experimenter", "writer", "reviewer")
SESSION_MODES = ("resume", "fresh")
TERMINAL_STATUSES = (
    "succeeded",
    "needs_replan",
    "needs_human",
    "quarantined",
    "cancelled",
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def utc_after(seconds: int) -> str:
    return (
        (datetime.now(UTC) + timedelta(seconds=seconds))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def retry_not_before(attempt: int, base_seconds: int) -> str | None:
    """Return a bounded exponential retry time; zero keeps tests/manual runs immediate."""

    if base_seconds <= 0:
        return None
    delay = min(86_400, int(base_seconds) * (2 ** max(0, int(attempt) - 1)))
    return utc_after(delay)


def bounded_elapsed(started_at: str | None, finished_at: str, limit: int) -> float:
    if not started_at:
        return 0.0
    start = datetime.fromisoformat(started_at)
    finish = datetime.fromisoformat(finished_at)
    return min(float(max(1, int(limit))), max(0.0, (finish - start).total_seconds()))


@dataclass(frozen=True)
class AttemptDisposition:
    task_id: str
    campaign_id: str
    attempt_id: str
    status: str
    reason: str


@dataclass(frozen=True)
class RecoverySummary:
    requeued: tuple[str, ...]
    quarantined: tuple[str, ...]
    cancelled: tuple[str, ...]
    attempts: tuple[AttemptDisposition, ...] = ()


class FactoryDB:
    """Own all authoritative runtime state transitions.

    Labs never import this class. They exchange task and result files with the
    control plane, which keeps the domain boundary explicit.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        # Journal mode is persistent database state.  Reasserting WAL on every
        # short-lived worker connection turns simultaneous heartbeats into a
        # schema-level lock race, despite each UPDATE being tiny.  Negotiate it
        # only while bootstrapping (or repairing) the database.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        bootstrap = sqlite3.connect(self.path, timeout=30)
        try:
            bootstrap.execute("PRAGMA busy_timeout = 30000")
            current_mode = str(bootstrap.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            if current_mode != "wal":
                selected_mode = str(
                    bootstrap.execute("PRAGMA journal_mode = WAL").fetchone()[0]
                ).lower()
                if selected_mode != "wal":
                    raise RuntimeError(
                        f"Factory database refused WAL journal mode: {selected_mode}"
                    )
        finally:
            bootstrap.close()
        with self.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            version_row = connection.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
            try:
                prior_version = int(version_row["value"]) if version_row is not None else 0
            except (TypeError, ValueError) as exc:
                raise ValueError("Factory database has an invalid schema version") from exc
            if prior_version > SCHEMA_VERSION:
                raise ValueError(
                    f"Factory database schema {prior_version} is newer than {SCHEMA_VERSION}"
                )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS campaigns (
                    campaign_id TEXT PRIMARY KEY,
                    domain TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    priority INTEGER NOT NULL DEFAULT 0,
                    state_path TEXT,
                    source TEXT,
                    max_agent_seconds INTEGER NOT NULL DEFAULT 86400,
                    agent_seconds_used REAL NOT NULL DEFAULT 0,
                    continuous INTEGER NOT NULL DEFAULT 0,
                    production_plan_path TEXT,
                    production_lane_path TEXT,
                    project_config_path TEXT,
                    workstream_state_path TEXT,
                    protocol_id TEXT,
                    primary_skill TEXT,
                    execution_policy_json TEXT NOT NULL DEFAULT '{}',
                    project_id TEXT,
                    workstream_policy_json TEXT NOT NULL DEFAULT '{}',
                    production_epoch INTEGER NOT NULL DEFAULT 1,
                    epoch_agent_seconds_used REAL NOT NULL DEFAULT 0,
                    rollover_count INTEGER NOT NULL DEFAULT 0,
                    last_rollover_at TEXT,
                    last_rollover_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id),
                    domain TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    input_path TEXT,
                    requested_output_path TEXT,
                    output_path TEXT,
                    skill_path TEXT,
                    runner TEXT,
                    routing_reason TEXT NOT NULL DEFAULT 'manual',
                    parent_task_id TEXT,
                    lab_id TEXT,
                    agent_role TEXT NOT NULL DEFAULT 'researcher',
                    session_mode TEXT NOT NULL DEFAULT 'resume',
                    agent_session_id TEXT,
                    session_source_task_id TEXT,
                    campaign_epoch INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'queued',
                    priority INTEGER NOT NULL DEFAULT 0,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    not_before TEXT,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    worker_pid INTEGER,
                    current_attempt_id TEXT,
                    max_wall_seconds INTEGER NOT NULL DEFAULT 43200,
                    cpu_threads INTEGER NOT NULL DEFAULT 2,
                    memory_mib INTEGER NOT NULL DEFAULT 4096,
                    scratch_mib INTEGER NOT NULL DEFAULT 4096,
                    result_path TEXT,
                    result_sha256 TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS tasks_ready_idx
                    ON tasks(status, not_before, priority DESC, created_at);
                CREATE INDEX IF NOT EXISTS tasks_campaign_idx
                    ON tasks(campaign_id, status);

                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS result_bundles (
                    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
                    attempt_id TEXT,
                    path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    valid INTEGER NOT NULL,
                    gate_passed INTEGER NOT NULL,
                    blockers_json TEXT NOT NULL,
                    runtime_json TEXT NOT NULL DEFAULT '{}',
                    ingested_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS task_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    attempt_number INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    lease_owner TEXT NOT NULL,
                    worker_pid INTEGER,
                    started_at TEXT,
                    finished_at TEXT,
                    result_path TEXT,
                    result_sha256 TEXT,
                    run_seconds REAL NOT NULL DEFAULT 0,
                    runtime_json TEXT NOT NULL DEFAULT '{}',
                    resources_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(task_id, attempt_number)
                );

                CREATE TABLE IF NOT EXISTS research_records (
                    record_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS research_records_kind_idx
                    ON research_records(kind, domain, status);
                """
            )
            self._migrate_v3(connection)
            self._migrate_v4(connection)
            self._migrate_v5(connection)
            self._migrate_v6(connection, prior_version=prior_version)
            self._migrate_v7(connection)
            self._migrate_v8(connection)
            connection.executescript(
                """
                CREATE INDEX IF NOT EXISTS task_attempts_task_idx
                    ON task_attempts(task_id, attempt_number);
                CREATE INDEX IF NOT EXISTS tasks_campaign_epoch_idx
                    ON tasks(campaign_id, campaign_epoch, status);
                """
            )
            connection.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )

    @staticmethod
    def _add_column(
        connection: sqlite3.Connection,
        table: str,
        definition: str,
    ) -> None:
        name = definition.split()[0]
        columns = {
            str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if name not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")

    @classmethod
    def _migrate_v3(cls, connection: sqlite3.Connection) -> None:
        """Apply the additive migration needed by existing local v2 databases."""

        task_columns = {
            str(row["name"]) for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
        }
        had_requested_output = "requested_output_path" in task_columns
        for definition in (
            "max_agent_seconds INTEGER NOT NULL DEFAULT 86400",
            "agent_seconds_used REAL NOT NULL DEFAULT 0",
        ):
            cls._add_column(connection, "campaigns", definition)
        for definition in (
            "requested_output_path TEXT",
            "routing_reason TEXT NOT NULL DEFAULT 'manual'",
            "parent_task_id TEXT",
            "lab_id TEXT",
            "agent_role TEXT NOT NULL DEFAULT 'researcher'",
            "session_mode TEXT NOT NULL DEFAULT 'resume'",
            "agent_session_id TEXT",
            "current_attempt_id TEXT",
            "max_wall_seconds INTEGER NOT NULL DEFAULT 43200",
        ):
            cls._add_column(connection, "tasks", definition)
        for definition in (
            "attempt_id TEXT",
            "runtime_json TEXT NOT NULL DEFAULT '{}'",
        ):
            cls._add_column(connection, "result_bundles", definition)
        if not had_requested_output:
            connection.execute(
                """
                UPDATE tasks SET requested_output_path=output_path
                WHERE requested_output_path IS NULL AND output_path IS NOT NULL
                """
            )

    @classmethod
    def _migrate_v4(cls, connection: sqlite3.Connection) -> None:
        """Add explicit resource reservations and resumable-session provenance."""

        for definition in (
            "session_source_task_id TEXT",
            "cpu_threads INTEGER NOT NULL DEFAULT 2",
            "memory_mib INTEGER NOT NULL DEFAULT 4096",
            "scratch_mib INTEGER NOT NULL DEFAULT 4096",
        ):
            cls._add_column(connection, "tasks", definition)
        cls._add_column(
            connection,
            "task_attempts",
            "resources_json TEXT NOT NULL DEFAULT '{}'",
        )

    @classmethod
    def _migrate_v5(cls, connection: sqlite3.Connection) -> None:
        """Add renewable production epochs without erasing lifetime accounting."""

        campaign_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(campaigns)").fetchall()
        }
        task_columns = {
            str(row["name"]) for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
        }
        had_epoch_usage = "epoch_agent_seconds_used" in campaign_columns
        had_task_epoch = "campaign_epoch" in task_columns
        for definition in (
            "continuous INTEGER NOT NULL DEFAULT 0",
            "production_plan_path TEXT",
            "production_lane_path TEXT",
            "production_epoch INTEGER NOT NULL DEFAULT 1",
            "epoch_agent_seconds_used REAL NOT NULL DEFAULT 0",
            "rollover_count INTEGER NOT NULL DEFAULT 0",
            "last_rollover_at TEXT",
            "last_rollover_reason TEXT",
        ):
            cls._add_column(connection, "campaigns", definition)
        cls._add_column(connection, "tasks", "campaign_epoch INTEGER NOT NULL DEFAULT 1")
        if not had_epoch_usage:
            connection.execute("UPDATE campaigns SET epoch_agent_seconds_used=agent_seconds_used")
        if not had_task_epoch:
            connection.execute(
                """
                UPDATE tasks
                SET campaign_epoch=COALESCE(
                    (SELECT production_epoch FROM campaigns
                     WHERE campaigns.campaign_id=tasks.campaign_id),
                    1
                )
                """
            )

    @staticmethod
    def _migrate_v6(connection: sqlite3.Connection, *, prior_version: int) -> None:
        """Remove attempt-local output paths copied into immutable task intent by v5 ticks."""

        if prior_version >= 6:
            return
        connection.execute(
            """
            UPDATE tasks SET requested_output_path=NULL
            WHERE requested_output_path IS NOT NULL
              AND instr(requested_output_path, '/attempt-workspaces/') > 0
            """
        )

    @classmethod
    def _migrate_v7(cls, connection: sqlite3.Connection) -> None:
        """Add generic project/protocol bindings alongside the legacy plan adapter."""

        for definition in (
            "project_config_path TEXT",
            "workstream_state_path TEXT",
            "protocol_id TEXT",
            "primary_skill TEXT",
            "execution_policy_json TEXT NOT NULL DEFAULT '{}'",
        ):
            cls._add_column(connection, "campaigns", definition)

    @classmethod
    def _migrate_v8(cls, connection: sqlite3.Connection) -> None:
        """Store thin scheduling policy separately from domain research state."""

        for definition in (
            "project_id TEXT",
            "workstream_policy_json TEXT NOT NULL DEFAULT '{}'",
        ):
            cls._add_column(connection, "campaigns", definition)

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        entity_type: str,
        entity_id: str,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        connection.execute(
            "INSERT INTO events(created_at, entity_type, entity_id, event_type, payload_json) "
            "VALUES(?, ?, ?, ?, ?)",
            (
                utc_now(),
                entity_type,
                entity_id,
                event_type,
                json.dumps(dict(payload or {}), ensure_ascii=False, sort_keys=True),
            ),
        )

    def register_campaign(
        self,
        campaign_id: str,
        *,
        domain: str,
        title: str,
        status: str = "active",
        priority: int = 0,
        state_path: str | None = None,
        source: str | None = None,
        max_agent_seconds: int | None = None,
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            existing = connection.execute(
                """
                SELECT domain, title, status, priority, state_path, source,
                       max_agent_seconds
                FROM campaigns WHERE campaign_id=?
                """,
                (campaign_id,),
            ).fetchone()
            budget = (
                max(1, int(max_agent_seconds))
                if max_agent_seconds is not None
                else int(existing["max_agent_seconds"])
                if existing is not None
                else 86_400
            )
            desired = (domain, title, status, priority, state_path, source, budget)
            if existing is not None and tuple(existing) == desired:
                return
            connection.execute(
                """
                INSERT INTO campaigns(
                    campaign_id, domain, title, status, priority, state_path, source,
                    max_agent_seconds, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(campaign_id) DO UPDATE SET
                    domain=excluded.domain,
                    title=excluded.title,
                    status=excluded.status,
                    priority=excluded.priority,
                    state_path=excluded.state_path,
                    source=excluded.source,
                    max_agent_seconds=excluded.max_agent_seconds,
                    updated_at=excluded.updated_at
                """,
                (
                    campaign_id,
                    domain,
                    title,
                    status,
                    priority,
                    state_path,
                    source,
                    budget,
                    now,
                    now,
                ),
            )
            event = "campaign_registered" if existing is None else "campaign_updated"
            self._event(connection, "campaign", campaign_id, event)

    def configure_continuous_campaign(
        self,
        campaign_id: str,
        *,
        production_plan_path: str,
        production_lane_path: str,
        priority: int | None = None,
        max_agent_seconds: int | None = None,
    ) -> bool:
        """Bind an administrator-owned lane without renewing its lifetime budget."""

        now = utc_now()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT status, continuous, production_plan_path,
                       production_lane_path, project_config_path,
                       workstream_state_path, protocol_id, primary_skill,
                       execution_policy_json, project_id,
                       workstream_policy_json, priority, max_agent_seconds,
                       agent_seconds_used
                FROM campaigns WHERE campaign_id=?
                """,
                (campaign_id,),
            ).fetchone()
            if row is None:
                raise KeyError(campaign_id)
            status = str(row["status"])
            desired_priority = int(row["priority"]) if priority is None else int(priority)
            desired_budget = (
                int(row["max_agent_seconds"])
                if max_agent_seconds is None
                else max(1, int(max_agent_seconds))
            )
            budget_reauthorized = (
                status == "budget_exhausted"
                and desired_budget > float(row["agent_seconds_used"])
            )
            if status not in {"active", "production_paused"} and not budget_reauthorized:
                raise ValueError(f"Campaign {campaign_id} cannot be activated from status {status}")
            desired = (
                "active",
                1,
                production_plan_path,
                production_lane_path,
                None,
                None,
                None,
                None,
                "{}",
                None,
                "{}",
                desired_priority,
                desired_budget,
            )
            if tuple(row[:-1]) == desired:
                return False
            connection.execute(
                """
                UPDATE campaigns
                SET status='active', continuous=1, production_plan_path=?,
                    production_lane_path=?, project_config_path=NULL,
                    workstream_state_path=NULL, protocol_id=NULL,
                    primary_skill=NULL, execution_policy_json='{}',
                    project_id=NULL, workstream_policy_json='{}',
                    priority=?, max_agent_seconds=?, updated_at=?
                WHERE campaign_id=?
                """,
                (
                    production_plan_path,
                    production_lane_path,
                    desired_priority,
                    desired_budget,
                    now,
                    campaign_id,
                ),
            )
            self._event(
                connection,
                "campaign",
                campaign_id,
                "continuous_production_configured",
                {
                    "production_plan_path": production_plan_path,
                    "production_lane_path": production_lane_path,
                    "priority": desired_priority,
                    "max_agent_seconds": desired_budget,
                },
            )
        return True

    def configure_project_campaign(
        self,
        campaign_id: str,
        *,
        project_config_path: str,
        workstream_state_path: str,
        protocol_id: str,
        primary_skill: str,
        execution_policy: Mapping[str, Any],
        project_id: str | None = None,
        workstream_policy: Mapping[str, Any] | None = None,
        priority: int | None = None,
        max_agent_seconds: int | None = None,
    ) -> bool:
        """Bind a generic project workstream without teaching the DB its science."""

        now = utc_now()
        policy_json = json.dumps(dict(execution_policy), ensure_ascii=False, sort_keys=True)
        stream_policy_json = json.dumps(
            dict(workstream_policy or {}), ensure_ascii=False, sort_keys=True
        )
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT status, continuous, production_plan_path,
                       production_lane_path, project_config_path,
                       workstream_state_path, protocol_id, primary_skill,
                       execution_policy_json, project_id,
                       workstream_policy_json, priority, max_agent_seconds,
                       agent_seconds_used
                FROM campaigns WHERE campaign_id=?
                """,
                (campaign_id,),
            ).fetchone()
            if row is None:
                raise KeyError(campaign_id)
            status = str(row["status"])
            desired_priority = int(row["priority"]) if priority is None else int(priority)
            desired_budget = (
                int(row["max_agent_seconds"])
                if max_agent_seconds is None
                else max(1, int(max_agent_seconds))
            )
            budget_reauthorized = (
                status == "budget_exhausted"
                and desired_budget > float(row["agent_seconds_used"])
            )
            if status not in {"active", "production_paused"} and not budget_reauthorized:
                raise ValueError(f"Campaign {campaign_id} cannot be activated from status {status}")
            desired = (
                "active",
                1,
                None,
                None,
                project_config_path,
                workstream_state_path,
                protocol_id,
                primary_skill,
                policy_json,
                project_id,
                stream_policy_json,
                desired_priority,
                desired_budget,
            )
            if tuple(row[:-1]) == desired:
                return False
            connection.execute(
                """
                UPDATE campaigns
                SET status='active', continuous=1,
                    production_plan_path=NULL, production_lane_path=NULL,
                    project_config_path=?,
                    workstream_state_path=?, protocol_id=?, primary_skill=?,
                    execution_policy_json=?, project_id=?, workstream_policy_json=?,
                    priority=?, max_agent_seconds=?, updated_at=?
                WHERE campaign_id=?
                """,
                (
                    project_config_path,
                    workstream_state_path,
                    protocol_id,
                    primary_skill,
                    policy_json,
                    project_id,
                    stream_policy_json,
                    desired_priority,
                    desired_budget,
                    now,
                    campaign_id,
                ),
            )
            self._event(
                connection,
                "campaign",
                campaign_id,
                "project_workstream_configured",
                {
                    "project_config_path": project_config_path,
                    "workstream_state_path": workstream_state_path,
                    "protocol_id": protocol_id,
                    "primary_skill": primary_skill,
                    "execution_policy": dict(execution_policy),
                    "project_id": project_id,
                    "workstream_policy": dict(workstream_policy or {}),
                    "priority": desired_priority,
                    "max_agent_seconds": desired_budget,
                },
            )
        return True

    def project_campaigns(self) -> list[dict[str, Any]]:
        """Return every campaign bound to project/workstream desired state."""

        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM campaigns
                WHERE production_plan_path IS NOT NULL
                   OR production_lane_path IS NOT NULL
                   OR project_config_path IS NOT NULL
                   OR workstream_state_path IS NOT NULL
                   OR continuous=1
                ORDER BY campaign_id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def production_campaigns(self) -> list[dict[str, Any]]:
        """Compatibility alias for legacy production-plan lifecycle commands."""

        return self.project_campaigns()

    def pause_production_campaign(self, campaign_id: str, *, reason: str) -> tuple[str, ...]:
        """Stop renewal for a lane that disappeared from active desired state.

        Queued work is cancelled immediately. A currently leased/running node may finish,
        but its expired lease is cancelled rather than requeued and result ingestion cannot
        create a successor while the campaign is paused.
        """

        now = utc_now()
        cancelled: list[str] = []
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            campaign = connection.execute(
                "SELECT status, continuous FROM campaigns WHERE campaign_id=?",
                (campaign_id,),
            ).fetchone()
            if campaign is None:
                raise KeyError(campaign_id)
            prior_status = str(campaign["status"])
            target_status = (
                "production_paused"
                if prior_status in {"active", "production_paused"}
                else prior_status
            )
            rows = connection.execute(
                """
                SELECT task_id FROM tasks
                WHERE campaign_id=? AND status='queued'
                ORDER BY task_id
                """,
                (campaign_id,),
            ).fetchall()
            cancelled = [str(row["task_id"]) for row in rows]
            connection.execute(
                """
                UPDATE tasks
                SET status='cancelled', not_before=NULL,
                    last_error=?, updated_at=?
                WHERE campaign_id=? AND status='queued'
                """,
                (f"production_paused:{reason}", now, campaign_id),
            )
            connection.execute(
                """
                UPDATE campaigns
                SET status=?, continuous=0, updated_at=?
                WHERE campaign_id=?
                """,
                (target_status, now, campaign_id),
            )
            if prior_status != target_status or bool(campaign["continuous"]) or cancelled:
                self._event(
                    connection,
                    "campaign",
                    campaign_id,
                    "continuous_production_paused",
                    {
                        "reason": reason,
                        "prior_status": prior_status,
                        "cancelled_tasks": cancelled,
                    },
                )
        return tuple(cancelled)

    def cancel_queued_tasks_for_inactive_campaigns(self) -> tuple[str, ...]:
        """Remove stale queue entries that can never be admitted by the scheduler."""

        now = utc_now()
        cancelled: list[str] = []
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT tasks.task_id, campaigns.status AS campaign_status
                FROM tasks
                JOIN campaigns USING(campaign_id)
                WHERE tasks.status='queued' AND campaigns.status!='active'
                ORDER BY tasks.task_id
                """
            ).fetchall()
            for row in rows:
                task_id = str(row["task_id"])
                error = f"campaign_not_active:{row['campaign_status']}"
                connection.execute(
                    """
                    UPDATE tasks
                    SET status='cancelled', not_before=NULL, last_error=?, updated_at=?
                    WHERE task_id=? AND status='queued'
                    """,
                    (error, now, task_id),
                )
                self._event(
                    connection,
                    "task",
                    task_id,
                    "task_cancelled",
                    {"reason": error},
                )
                cancelled.append(task_id)
        return tuple(cancelled)

    def cancel_active_tasks(
        self,
        campaign_ids: Iterable[str],
        *,
        reason: str,
    ) -> tuple[dict[str, Any], ...]:
        """Atomically cancel leased/running work and account its bounded elapsed time.

        Process termination is deliberately left to the control plane.  Returning the
        recorded worker PIDs lets a supervised shutdown stop both transient systemd
        workers and pre-upgrade detached process groups without leaving authoritative
        task state at ``running``.
        """

        selected = tuple(sorted({str(item).strip() for item in campaign_ids if str(item).strip()}))
        if not selected:
            return ()
        now = utc_now()
        placeholders = ",".join("?" for _ in selected)
        cancelled: list[dict[str, Any]] = []
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                f"""
                SELECT tasks.task_id, tasks.campaign_id, tasks.status,
                       tasks.current_attempt_id, tasks.worker_pid,
                       tasks.max_wall_seconds, task_attempts.started_at
                FROM tasks
                LEFT JOIN task_attempts
                  ON task_attempts.attempt_id=tasks.current_attempt_id
                WHERE tasks.campaign_id IN ({placeholders})
                  AND tasks.status IN ('leased', 'running')
                ORDER BY tasks.task_id
                """,
                selected,
            ).fetchall()
            for row in rows:
                task_id = str(row["task_id"])
                campaign_id = str(row["campaign_id"])
                attempt_id = str(row["current_attempt_id"] or "")
                elapsed = bounded_elapsed(
                    str(row["started_at"]) if row["started_at"] else None,
                    now,
                    int(row["max_wall_seconds"]),
                )
                error = f"operator_cancelled:{reason}"
                updated = connection.execute(
                    """
                    UPDATE tasks
                    SET status='cancelled', lease_owner=NULL, lease_expires_at=NULL,
                        worker_pid=NULL, current_attempt_id=NULL, not_before=NULL,
                        last_error=?, updated_at=?
                    WHERE task_id=? AND status IN ('leased', 'running')
                    """,
                    (error, now, task_id),
                ).rowcount
                if updated != 1:
                    continue
                if attempt_id:
                    connection.execute(
                        """
                        UPDATE task_attempts
                        SET status='cancelled', finished_at=?, run_seconds=?, error=?
                        WHERE attempt_id=? AND status IN ('leased', 'running')
                        """,
                        (now, elapsed, error, attempt_id),
                    )
                connection.execute(
                    """
                    UPDATE campaigns
                    SET agent_seconds_used=agent_seconds_used+?,
                        epoch_agent_seconds_used=epoch_agent_seconds_used+?,
                        updated_at=?
                    WHERE campaign_id=?
                    """,
                    (elapsed, elapsed, now, campaign_id),
                )
                item = {
                    "task_id": task_id,
                    "campaign_id": campaign_id,
                    "attempt_id": attempt_id or None,
                    "worker_pid": int(row["worker_pid"]) if row["worker_pid"] else None,
                    "run_seconds": elapsed,
                    "reason": reason,
                }
                self._event(connection, "task", task_id, "task_cancelled", item)
                cancelled.append(item)
        return tuple(cancelled)

    def enqueue_task(
        self,
        *,
        campaign_id: str,
        domain: str,
        task_type: str,
        objective: str,
        task_id: str | None = None,
        input_path: str | None = None,
        output_path: str | None = None,
        skill_path: str | None = None,
        runner: str | None = None,
        priority: int = 0,
        max_attempts: int = 3,
        not_before: str | None = None,
        routing_reason: str = "manual",
        parent_task_id: str | None = None,
        agent_role: str = "researcher",
        session_mode: str | None = None,
        agent_session_id: str | None = None,
        session_source_task_id: str | None = None,
        max_wall_seconds: int = 43_200,
        cpu_threads: int = 2,
        memory_mib: int = 4_096,
        scratch_mib: int = 4_096,
    ) -> str:
        identifier = task_id or str(uuid.uuid4())
        now = utc_now()
        if agent_role not in AGENT_ROLES:
            raise ValueError(f"agent_role must be one of {AGENT_ROLES}")
        mode = session_mode or ("fresh" if agent_role == "reviewer" else "resume")
        if mode not in SESSION_MODES:
            raise ValueError(f"session_mode must be one of {SESSION_MODES}")
        if agent_role == "reviewer" and mode != "fresh":
            raise ValueError("reviewer tasks must use a fresh session")
        if mode == "fresh":
            agent_session_id = None
            session_source_task_id = None
        resources = {
            "cpu_threads": cpu_threads,
            "memory_mib": memory_mib,
            "scratch_mib": scratch_mib,
        }
        for name, value in resources.items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        with self.connect() as connection:
            campaign = connection.execute(
                "SELECT domain, status, production_epoch FROM campaigns WHERE campaign_id=?",
                (campaign_id,),
            ).fetchone()
            if campaign is None:
                raise KeyError(f"Unknown campaign: {campaign_id}")
            if str(campaign["domain"]) != domain:
                raise ValueError(
                    f"Task domain {domain!r} differs from campaign domain {campaign['domain']!r}"
                )
            if str(campaign["status"]) != "active":
                raise ValueError(f"Campaign {campaign_id} is not active")
            if parent_task_id:
                parent = connection.execute(
                    """
                    SELECT campaign_id, agent_role, agent_session_id
                    FROM tasks WHERE task_id=?
                    """,
                    (parent_task_id,),
                ).fetchone()
                if parent is None:
                    raise KeyError(f"Unknown parent task: {parent_task_id}")
                if str(parent["campaign_id"]) != campaign_id:
                    raise ValueError("A successor cannot cross campaign boundaries")
                if (
                    mode == "resume"
                    and session_source_task_id is None
                    and str(parent["agent_role"]) == agent_role
                ):
                    session_source_task_id = parent_task_id
            if mode == "resume" and session_source_task_id:
                if not parent_task_id:
                    raise ValueError("A session source requires a parent task")
                source = connection.execute(
                    """
                    SELECT campaign_id, agent_role, agent_session_id
                    FROM tasks WHERE task_id=?
                    """,
                    (session_source_task_id,),
                ).fetchone()
                if source is None:
                    raise KeyError(f"Unknown session source task: {session_source_task_id}")
                if str(source["campaign_id"]) != campaign_id:
                    raise ValueError("A session source cannot cross campaign boundaries")
                if str(source["agent_role"]) != agent_role:
                    raise ValueError("A session cannot cross agent-role boundaries")
                source_session = source["agent_session_id"]
                if not source_session:
                    raise ValueError("A session source task has no recorded session")
                if agent_session_id and agent_session_id != source_session:
                    raise ValueError("Successor session differs from its source session")
                if parent_task_id and not self._is_ancestor(
                    connection,
                    ancestor_task_id=session_source_task_id,
                    descendant_task_id=parent_task_id,
                ):
                    raise ValueError("A session source must belong to the parent lineage")
                agent_session_id = str(source_session)
            elif mode == "resume" and parent_task_id:
                parent = connection.execute(
                    "SELECT agent_role FROM tasks WHERE task_id=?",
                    (parent_task_id,),
                ).fetchone()
                if parent is not None and str(parent["agent_role"]) != agent_role:
                    raise ValueError("A cross-role resume requires a same-role session source")
            elif mode == "resume" and agent_session_id:
                raise ValueError("A resumed session must come from a source task")
            connection.execute(
                """
                INSERT INTO tasks(
                    task_id, campaign_id, domain, task_type, objective, input_path,
                    requested_output_path, skill_path, runner, routing_reason,
                    parent_task_id, agent_role, session_mode, agent_session_id,
                    session_source_task_id, campaign_epoch, status, priority,
                    max_attempts, not_before,
                    max_wall_seconds, cpu_threads, memory_mib, scratch_mib,
                    created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                         'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    campaign_id,
                    domain,
                    task_type,
                    objective,
                    input_path,
                    output_path,
                    skill_path,
                    runner,
                    routing_reason,
                    parent_task_id,
                    agent_role,
                    mode,
                    agent_session_id,
                    session_source_task_id,
                    int(campaign["production_epoch"]),
                    priority,
                    max(1, int(max_attempts)),
                    not_before,
                    max(1, int(max_wall_seconds)),
                    cpu_threads,
                    memory_mib,
                    scratch_mib,
                    now,
                    now,
                ),
            )
            self._event(
                connection,
                "task",
                identifier,
                "task_enqueued",
                {
                    "agent_role": agent_role,
                    "session_mode": mode,
                    "session_source_task_id": session_source_task_id,
                    "parent_task_id": parent_task_id,
                    "routing_reason": routing_reason,
                    "resources": resources,
                },
            )
        return identifier

    @staticmethod
    def _is_ancestor(
        connection: sqlite3.Connection,
        *,
        ancestor_task_id: str,
        descendant_task_id: str,
    ) -> bool:
        row = connection.execute(
            """
            WITH RECURSIVE lineage(task_id, parent_task_id) AS (
                SELECT task_id, parent_task_id FROM tasks WHERE task_id=?
                UNION ALL
                SELECT parent.task_id, parent.parent_task_id
                FROM tasks parent
                JOIN lineage child ON parent.task_id=child.parent_task_id
            )
            SELECT 1 FROM lineage WHERE task_id=? LIMIT 1
            """,
            (descendant_task_id, ancestor_task_id),
        ).fetchone()
        return row is not None

    def nearest_session_source(
        self,
        task_id: str,
        *,
        agent_role: str,
    ) -> dict[str, Any] | None:
        """Find the closest task in this lineage that owns a role's session."""

        if agent_role not in AGENT_ROLES:
            raise ValueError(f"agent_role must be one of {AGENT_ROLES}")
        with self.connect() as connection:
            row = connection.execute(
                """
                WITH RECURSIVE lineage(
                    task_id, parent_task_id, agent_role, agent_session_id, depth
                ) AS (
                    SELECT task_id, parent_task_id, agent_role, agent_session_id, 0
                    FROM tasks WHERE task_id=?
                    UNION ALL
                    SELECT parent.task_id, parent.parent_task_id, parent.agent_role,
                           parent.agent_session_id, child.depth + 1
                    FROM tasks parent
                    JOIN lineage child ON parent.task_id=child.parent_task_id
                )
                SELECT task_id, agent_session_id, depth
                FROM lineage
                WHERE agent_role=?
                  AND agent_session_id IS NOT NULL
                  AND agent_session_id != ''
                ORDER BY depth
                LIMIT 1
                """,
                (task_id, agent_role),
            ).fetchone()
        return dict(row) if row else None

    def task(self, task_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def campaign(self, campaign_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id = ?", (campaign_id,)
            ).fetchone()
        return dict(row) if row else None

    def active_count(self) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM tasks WHERE status IN ('leased', 'running')"
            ).fetchone()
        return int(row["n"])

    def active_resource_totals(self) -> dict[str, int]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(cpu_threads), 0) AS cpu_threads,
                       COALESCE(SUM(memory_mib), 0) AS memory_mib,
                       COALESCE(SUM(scratch_mib), 0) AS scratch_mib
                FROM tasks WHERE status IN ('leased', 'running')
                """
            ).fetchone()
        return {
            "cpu_threads": int(row["cpu_threads"]),
            "memory_mib": int(row["memory_mib"]),
            "scratch_mib": int(row["scratch_mib"]),
        }

    def task_count(self, campaign_id: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM tasks WHERE campaign_id=?",
                (campaign_id,),
            ).fetchone()
        return int(row["n"])

    def current_epoch_task_count(self, campaign_id: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS n
                FROM tasks
                JOIN campaigns USING(campaign_id)
                WHERE tasks.campaign_id=?
                  AND tasks.campaign_epoch=campaigns.production_epoch
                """,
                (campaign_id,),
            ).fetchone()
        return int(row["n"])

    def has_active_tasks(self, campaign_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM tasks
                WHERE campaign_id=? AND status IN ('leased', 'running')
                LIMIT 1
                """,
                (campaign_id,),
            ).fetchone()
        return row is not None

    def has_queued_tasks(self, campaign_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM tasks WHERE campaign_id=? AND status='queued' LIMIT 1",
                (campaign_id,),
            ).fetchone()
        return row is not None

    def latest_task(self, campaign_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM tasks
                WHERE campaign_id=?
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                (campaign_id,),
            ).fetchone()
        return dict(row) if row else None

    def result_runtime(self, task_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT runtime_json FROM result_bundles WHERE task_id=?",
                (task_id,),
            ).fetchone()
        if row is None:
            return {}
        payload = json.loads(str(row["runtime_json"]))
        return payload if isinstance(payload, dict) else {}

    def continuous_campaigns(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM campaigns
                WHERE continuous=1 AND status='active'
                ORDER BY priority DESC, campaign_id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def rollover_campaign_epoch(
        self,
        campaign_id: str,
        *,
        reason: str,
        source_task_id: str | None = None,
    ) -> int:
        """Open a new task-count epoch without renewing Agent-time budget."""

        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            campaign = connection.execute(
                """
                SELECT continuous, status, production_epoch, epoch_agent_seconds_used,
                       agent_seconds_used, max_agent_seconds
                FROM campaigns WHERE campaign_id=?
                """,
                (campaign_id,),
            ).fetchone()
            if campaign is None:
                raise KeyError(campaign_id)
            if not bool(campaign["continuous"]):
                raise ValueError(f"Campaign {campaign_id} is not continuous")
            if str(campaign["status"]) != "active":
                raise ValueError(f"Campaign {campaign_id} is not active")
            if float(campaign["agent_seconds_used"]) + 1 > int(campaign["max_agent_seconds"]):
                raise ValueError(f"Campaign {campaign_id} exhausted its Agent-time budget")
            active = connection.execute(
                """
                SELECT COUNT(*) AS n FROM tasks
                WHERE campaign_id=? AND status IN ('leased', 'running')
                """,
                (campaign_id,),
            ).fetchone()
            if int(active["n"]):
                raise ValueError(f"Campaign {campaign_id} still has an active task")
            old_epoch = int(campaign["production_epoch"])
            new_epoch = old_epoch + 1
            connection.execute(
                """
                UPDATE campaigns
                SET production_epoch=?, epoch_agent_seconds_used=0,
                    rollover_count=rollover_count+1, last_rollover_at=?,
                    last_rollover_reason=?, updated_at=?
                WHERE campaign_id=?
                """,
                (new_epoch, now, reason, now, campaign_id),
            )
            connection.execute(
                """
                UPDATE tasks SET campaign_epoch=?, updated_at=?
                WHERE campaign_id=? AND status='queued'
                """,
                (new_epoch, now, campaign_id),
            )
            self._event(
                connection,
                "campaign",
                campaign_id,
                "production_epoch_rolled",
                {
                    "old_epoch": old_epoch,
                    "new_epoch": new_epoch,
                    "reason": reason,
                    "source_task_id": source_task_id,
                    "epoch_agent_seconds_used": float(campaign["epoch_agent_seconds_used"]),
                },
            )
        return new_epoch

    def claim_next_task(
        self,
        *,
        owner: str,
        lease_seconds: int,
        max_active: int | None = None,
        resource_capacity: Mapping[str, int] | None = None,
    ) -> dict[str, Any] | None:
        now = utc_now()
        expires = utc_after(lease_seconds)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if max_active is not None:
                active = connection.execute(
                    "SELECT COUNT(*) AS n FROM tasks WHERE status IN ('leased', 'running')"
                ).fetchone()
                if int(active["n"]) >= max(1, int(max_active)):
                    return None
            rows = connection.execute(
                """
                SELECT tasks.*, campaigns.max_agent_seconds, campaigns.agent_seconds_used,
                       campaigns.continuous, campaigns.production_epoch,
                       campaigns.epoch_agent_seconds_used
                FROM tasks
                JOIN campaigns USING(campaign_id)
                WHERE tasks.status = 'queued'
                  AND campaigns.status = 'active'
                  AND campaigns.agent_seconds_used + 1
                      <= campaigns.max_agent_seconds
                  AND (
                      campaigns.continuous=0
                      OR tasks.campaign_epoch=campaigns.production_epoch
                  )
                  AND (tasks.not_before IS NULL OR tasks.not_before <= ?)
                  AND NOT EXISTS (
                      SELECT 1 FROM tasks active
                      WHERE active.campaign_id=tasks.campaign_id
                        AND active.status IN ('leased', 'running')
                )
                ORDER BY tasks.priority DESC, tasks.created_at, tasks.task_id
                """,
                (now,),
            ).fetchall()
            row = None
            if resource_capacity is None:
                row = rows[0] if rows else None
            else:
                keys = ("cpu_threads", "memory_mib", "scratch_mib")
                capacity = {key: int(resource_capacity[key]) for key in keys}
                active = connection.execute(
                    """
                    SELECT COALESCE(SUM(cpu_threads), 0) AS cpu_threads,
                           COALESCE(SUM(memory_mib), 0) AS memory_mib,
                           COALESCE(SUM(scratch_mib), 0) AS scratch_mib
                    FROM tasks WHERE status IN ('leased', 'running')
                    """
                ).fetchone()
                used = {key: int(active[key]) for key in keys}
                for candidate in rows:
                    if all(used[key] + int(candidate[key]) <= capacity[key] for key in keys):
                        row = candidate
                        break
            if row is None:
                return None
            task_id = str(row["task_id"])
            attempt_id = str(uuid.uuid4())
            attempt_number = int(row["attempt"]) + 1
            connection.execute(
                """
                UPDATE tasks
                SET status='leased', attempt=attempt+1, lease_owner=?, lease_expires_at=?,
                    current_attempt_id=?, output_path=NULL, updated_at=?
                WHERE task_id=? AND status='queued'
                """,
                (owner, expires, attempt_id, now, task_id),
            )
            connection.execute(
                """
                INSERT INTO task_attempts(
                    attempt_id, task_id, attempt_number, status, lease_owner,
                    resources_json, created_at
                ) VALUES(?, ?, ?, 'leased', ?, ?, ?)
                """,
                (
                    attempt_id,
                    task_id,
                    attempt_number,
                    owner,
                    json.dumps(
                        {
                            "cpu_threads": int(row["cpu_threads"]),
                            "memory_mib": int(row["memory_mib"]),
                            "scratch_mib": int(row["scratch_mib"]),
                        },
                        sort_keys=True,
                    ),
                    now,
                ),
            )
            self._event(
                connection,
                "task",
                task_id,
                "task_leased",
                {
                    "owner": owner,
                    "lease_expires_at": expires,
                    "attempt_id": attempt_id,
                    "attempt": attempt_number,
                    "resources": {
                        "cpu_threads": int(row["cpu_threads"]),
                        "memory_mib": int(row["memory_mib"]),
                        "scratch_mib": int(row["scratch_mib"]),
                    },
                },
            )
            claimed = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        return dict(claimed) if claimed else None

    def bind_attempt_spec(
        self,
        task_id: str,
        *,
        attempt_id: str,
        lab_id: str,
        output_path: str,
    ) -> None:
        with self.connect() as connection:
            updated = connection.execute(
                """
                UPDATE tasks SET lab_id=?, output_path=?, updated_at=?
                WHERE task_id=? AND status='leased' AND current_attempt_id=?
                """,
                (lab_id, output_path, utc_now(), task_id, attempt_id),
            ).rowcount
            if updated != 1:
                raise ValueError(f"Task {task_id} is not leased for attempt {attempt_id}")

    def mark_running(
        self,
        task_id: str,
        *,
        attempt_id: str,
        owner: str,
        pid: int | None,
        lease_seconds: int,
    ) -> None:
        now = utc_now()
        expires = utc_after(lease_seconds)
        with self.connect() as connection:
            updated = connection.execute(
                """
                UPDATE tasks SET status='running', worker_pid=?, lease_owner=?,
                    lease_expires_at=?, updated_at=?
                WHERE task_id=? AND status='leased' AND current_attempt_id=?
                """,
                (pid, owner, expires, now, task_id, attempt_id),
            ).rowcount
            if updated != 1:
                raise ValueError(f"Task {task_id} is not leased")
            connection.execute(
                """
                UPDATE task_attempts
                SET status='running', worker_pid=?, started_at=?
                WHERE attempt_id=? AND task_id=? AND status='leased'
                """,
                (pid, now, attempt_id, task_id),
            )
            self._event(
                connection,
                "task",
                task_id,
                "task_started",
                {"pid": pid, "attempt_id": attempt_id},
            )

    def set_worker_pid(self, task_id: str, *, attempt_id: str, pid: int) -> None:
        with self.connect() as connection:
            updated = connection.execute(
                """
                UPDATE tasks SET worker_pid=?, updated_at=?
                WHERE task_id=? AND status='running' AND current_attempt_id=?
                """,
                (pid, utc_now(), task_id, attempt_id),
            ).rowcount
            if updated != 1:
                raise ValueError(f"Task {task_id} is not running for attempt {attempt_id}")
            connection.execute(
                "UPDATE task_attempts SET worker_pid=? WHERE attempt_id=?",
                (pid, attempt_id),
            )

    def heartbeat(
        self,
        task_id: str,
        *,
        attempt_id: str,
        owner: str,
        lease_seconds: int,
    ) -> bool:
        now = utc_now()
        expires = utc_after(lease_seconds)
        with self.connect() as connection:
            updated = connection.execute(
                """
                UPDATE tasks SET lease_expires_at=?, updated_at=?
                WHERE task_id=? AND current_attempt_id=? AND lease_owner=?
                  AND status='running'
                """,
                (expires, now, task_id, attempt_id, owner),
            ).rowcount
        return updated == 1

    def recover_expired(self, retry_backoff_seconds: int = 0) -> RecoverySummary:
        now = utc_now()
        requeued: list[str] = []
        quarantined: list[str] = []
        cancelled: list[str] = []
        attempts: list[AttemptDisposition] = []
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT tasks.task_id, tasks.campaign_id, tasks.attempt,
                       tasks.max_attempts, tasks.current_attempt_id,
                       tasks.max_wall_seconds, campaigns.status AS campaign_status
                FROM tasks
                JOIN campaigns USING(campaign_id)
                WHERE tasks.status IN ('leased', 'running')
                  AND tasks.lease_expires_at IS NOT NULL
                  AND tasks.lease_expires_at < ?
                ORDER BY tasks.task_id
                """,
                (now,),
            ).fetchall()
            for row in rows:
                task_id = str(row["task_id"])
                exhausted = int(row["attempt"]) >= int(row["max_attempts"])
                campaign_active = str(row["campaign_status"]) == "active"
                status = (
                    "cancelled" if not campaign_active else "quarantined" if exhausted else "queued"
                )
                not_before = (
                    None
                    if status != "queued"
                    else retry_not_before(int(row["attempt"]), retry_backoff_seconds)
                )
                recovery_error = (
                    "lease_expired"
                    if campaign_active
                    else f"lease_expired_while_campaign_{row['campaign_status']}"
                )
                connection.execute(
                    """
                    UPDATE tasks SET status=?, lease_owner=NULL, lease_expires_at=NULL,
                        worker_pid=NULL, current_attempt_id=NULL, output_path=NULL,
                        not_before=?, updated_at=?, last_error=?
                    WHERE task_id=?
                    """,
                    (status, not_before, now, recovery_error, task_id),
                )
                attempt_id = str(row["current_attempt_id"] or "")
                elapsed = 0.0
                if attempt_id:
                    attempt = connection.execute(
                        "SELECT started_at FROM task_attempts WHERE attempt_id=?",
                        (attempt_id,),
                    ).fetchone()
                    elapsed = bounded_elapsed(
                        str(attempt["started_at"]) if attempt and attempt["started_at"] else None,
                        now,
                        int(row["max_wall_seconds"]),
                    )
                    connection.execute(
                        """
                        UPDATE task_attempts SET status=?, finished_at=?,
                            run_seconds=?, error=?
                        WHERE attempt_id=? AND status IN ('leased', 'running')
                        """,
                        (
                            status if status == "cancelled" else "lease_expired",
                            now,
                            elapsed,
                            recovery_error,
                            attempt_id,
                        ),
                    )
                    connection.execute(
                        """
                        UPDATE campaigns
                        SET agent_seconds_used=agent_seconds_used+?,
                            epoch_agent_seconds_used=epoch_agent_seconds_used+?,
                            updated_at=?
                        WHERE campaign_id=?
                        """,
                        (elapsed, elapsed, now, str(row["campaign_id"])),
                    )
                    attempts.append(
                        AttemptDisposition(
                            task_id=task_id,
                            campaign_id=str(row["campaign_id"]),
                            attempt_id=attempt_id,
                            status=status,
                            reason=recovery_error,
                        )
                    )
                self._event(
                    connection,
                    "task",
                    task_id,
                    f"task_{status}",
                    {
                        "reason": "lease_expired",
                        "attempt_id": attempt_id,
                        "run_seconds": elapsed,
                    },
                )
                if status == "cancelled":
                    cancelled.append(task_id)
                elif status == "quarantined":
                    quarantined.append(task_id)
                else:
                    requeued.append(task_id)
        return RecoverySummary(
            tuple(requeued),
            tuple(quarantined),
            tuple(cancelled),
            tuple(attempts),
        )

    def fail_launch(
        self,
        task_id: str,
        error: str,
        retry_backoff_seconds: int = 0,
    ) -> AttemptDisposition:
        now = utc_now()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT attempt, max_attempts, current_attempt_id, campaign_id
                FROM tasks WHERE task_id=?
                """,
                (task_id,),
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            status = "quarantined" if int(row["attempt"]) >= int(row["max_attempts"]) else "queued"
            not_before = (
                None
                if status == "quarantined"
                else retry_not_before(int(row["attempt"]), retry_backoff_seconds)
            )
            connection.execute(
                """
                UPDATE tasks SET status=?, lease_owner=NULL, lease_expires_at=NULL,
                    worker_pid=NULL, current_attempt_id=NULL, output_path=NULL,
                    not_before=?, last_error=?, updated_at=? WHERE task_id=?
                """,
                (status, not_before, error, now, task_id),
            )
            attempt_id = str(row["current_attempt_id"] or "")
            if attempt_id:
                connection.execute(
                    """
                    UPDATE task_attempts SET status='launch_failed', finished_at=?, error=?
                    WHERE attempt_id=?
                    """,
                    (now, error, attempt_id),
                )
            self._event(
                connection,
                "task",
                task_id,
                "task_launch_failed",
                {"error": error, "status": status, "attempt_id": attempt_id},
            )
        return AttemptDisposition(
            task_id=task_id,
            campaign_id=str(row["campaign_id"]),
            attempt_id=attempt_id,
            status=status,
            reason=error,
        )

    def reject_attempt(
        self,
        task_id: str,
        *,
        attempt_id: str,
        reason: str,
        result_path: str | None,
        result_sha256: str | None,
        run_seconds: float,
        runtime: Mapping[str, Any],
        retry_backoff_seconds: int = 0,
    ) -> AttemptDisposition:
        """Close a current attempt whose authenticated result transport is invalid."""

        now = utc_now()
        runtime_json = json.dumps(dict(runtime), ensure_ascii=False, sort_keys=True)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT attempt, max_attempts, max_wall_seconds, campaign_id
                FROM tasks
                WHERE task_id=? AND status='running' AND current_attempt_id=?
                """,
                (task_id, attempt_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"Task {task_id} is not running for current attempt {attempt_id}")
            status = "quarantined" if int(row["attempt"]) >= int(row["max_attempts"]) else "queued"
            not_before = (
                None
                if status == "quarantined"
                else retry_not_before(int(row["attempt"]), retry_backoff_seconds)
            )
            bounded_seconds = min(
                float(max(1, int(row["max_wall_seconds"]))),
                max(0.0, float(run_seconds)),
            )
            connection.execute(
                """
                UPDATE tasks SET status=?, lease_owner=NULL, lease_expires_at=NULL,
                    worker_pid=NULL, current_attempt_id=NULL, output_path=NULL,
                    not_before=?, last_error=?, updated_at=?
                WHERE task_id=?
                """,
                (status, not_before, reason, now, task_id),
            )
            updated = connection.execute(
                """
                UPDATE task_attempts
                SET status='result_rejected', finished_at=?, result_path=?, result_sha256=?,
                    run_seconds=?, runtime_json=?, error=?
                WHERE attempt_id=? AND task_id=? AND status='running'
                """,
                (
                    now,
                    result_path,
                    result_sha256,
                    bounded_seconds,
                    runtime_json,
                    reason,
                    attempt_id,
                    task_id,
                ),
            ).rowcount
            if updated != 1:
                raise ValueError(f"Attempt {attempt_id} is not rejectable")
            connection.execute(
                """
                UPDATE campaigns
                SET agent_seconds_used=agent_seconds_used+?,
                    epoch_agent_seconds_used=epoch_agent_seconds_used+?, updated_at=?
                WHERE campaign_id=?
                """,
                (bounded_seconds, bounded_seconds, now, str(row["campaign_id"])),
            )
            self._event(
                connection,
                "task",
                task_id,
                "task_result_rejected",
                {
                    "attempt_id": attempt_id,
                    "reason": reason,
                    "status": status,
                    "run_seconds": bounded_seconds,
                },
            )
        return AttemptDisposition(
            task_id=task_id,
            campaign_id=str(row["campaign_id"]),
            attempt_id=attempt_id,
            status=status,
            reason=reason,
        )

    def ingest_result(
        self,
        task_id: str,
        *,
        attempt_id: str,
        status: str,
        result_path: str,
        result_sha256: str,
        valid: bool,
        gate_passed: bool,
        blockers: list[str],
        run_seconds: float,
        runtime: Mapping[str, Any],
        error: str | None = None,
        retry_backoff_seconds: int = 0,
    ) -> str:
        mapping = {
            "completed": "succeeded",
            "succeeded": "succeeded",
            "failed": "failed",
            "needs_replan": "needs_replan",
            "needs_human": "needs_human",
            "quarantined": "quarantined",
        }
        final_status = mapping.get(status, "failed")
        if not valid or (final_status == "succeeded" and not gate_passed):
            final_status = "needs_replan"
        now = utc_now()
        bounded_seconds = max(0.0, float(run_seconds))
        runtime_json = json.dumps(dict(runtime), ensure_ascii=False, sort_keys=True)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT attempt, max_attempts, campaign_id, agent_role, session_mode,
                       agent_session_id
                FROM tasks
                WHERE task_id=? AND status='running' AND current_attempt_id=?
                """,
                (task_id, attempt_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"Task {task_id} is not running for current attempt {attempt_id}")
            attempt = connection.execute(
                """
                SELECT status FROM task_attempts
                WHERE attempt_id=? AND task_id=?
                """,
                (attempt_id, task_id),
            ).fetchone()
            if attempt is None or str(attempt["status"]) != "running":
                raise ValueError(f"Attempt {attempt_id} is not ingestible")
            if final_status == "failed":
                final_status = (
                    "queued" if int(row["attempt"]) < int(row["max_attempts"]) else "quarantined"
                )
            not_before = (
                retry_not_before(int(row["attempt"]), retry_backoff_seconds)
                if final_status == "queued"
                else None
            )
            session_id = runtime.get("session_id")
            stored_session = (
                str(session_id) if isinstance(session_id, str) and session_id.strip() else None
            )
            prior_session = row["agent_session_id"]
            if (
                str(row["session_mode"]) == "resume"
                and prior_session
                and stored_session
                and stored_session != str(prior_session)
            ):
                raise ValueError("The reported session differs from the resumed task session")
            clear_current = final_status == "queued"
            connection.execute(
                """
                UPDATE tasks SET status=?, result_path=?, result_sha256=?, last_error=?,
                    lease_owner=NULL, lease_expires_at=NULL, worker_pid=NULL, not_before=?,
                    current_attempt_id=CASE WHEN ? THEN NULL ELSE current_attempt_id END,
                    output_path=CASE WHEN ? THEN NULL ELSE output_path END,
                    agent_session_id=COALESCE(?, agent_session_id), updated_at=?
                WHERE task_id=?
                """,
                (
                    final_status,
                    result_path,
                    result_sha256,
                    error,
                    not_before,
                    int(clear_current),
                    int(clear_current),
                    stored_session,
                    now,
                    task_id,
                ),
            )
            connection.execute(
                """
                UPDATE task_attempts
                SET status=?, finished_at=?, result_path=?, result_sha256=?,
                    run_seconds=?, runtime_json=?, error=?
                WHERE attempt_id=?
                """,
                (
                    final_status,
                    now,
                    result_path,
                    result_sha256,
                    bounded_seconds,
                    runtime_json,
                    error,
                    attempt_id,
                ),
            )
            connection.execute(
                """
                UPDATE campaigns
                SET agent_seconds_used=agent_seconds_used+?,
                    epoch_agent_seconds_used=epoch_agent_seconds_used+?,
                    updated_at=?
                WHERE campaign_id=?
                """,
                (bounded_seconds, bounded_seconds, now, str(row["campaign_id"])),
            )
            connection.execute(
                """
                INSERT INTO result_bundles(
                    task_id, attempt_id, path, sha256, valid, gate_passed,
                    blockers_json, runtime_json, ingested_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    attempt_id=excluded.attempt_id, path=excluded.path,
                    sha256=excluded.sha256, valid=excluded.valid,
                    gate_passed=excluded.gate_passed,
                    blockers_json=excluded.blockers_json,
                    runtime_json=excluded.runtime_json, ingested_at=excluded.ingested_at
                """,
                (
                    task_id,
                    attempt_id,
                    result_path,
                    result_sha256,
                    int(valid),
                    int(gate_passed),
                    json.dumps(blockers, ensure_ascii=False, sort_keys=True),
                    runtime_json,
                    now,
                ),
            )
            self._event(
                connection,
                "task",
                task_id,
                "result_ingested",
                {
                    "status": final_status,
                    "valid": valid,
                    "gate_passed": gate_passed,
                    "attempt_id": attempt_id,
                    "run_seconds": bounded_seconds,
                    "runtime": dict(runtime),
                },
            )
        return final_status

    def reopen_protocol_failed_attempt(
        self,
        task_id: str,
        *,
        attempt_id: str,
        expected_error_fragment: str,
        runtime_error_key: str = "transaction_error",
        lease_seconds: int = 600,
    ) -> dict[str, Any]:
        """Reopen one hash-bound result rejected only by named infrastructure.

        This is deliberately narrower than a general status override. The result
        envelope must already have passed its ordinary gate, and both the task and
        attempt must identify the same terminal infrastructure failure. The prior
        runtime charge is removed before replay so successful re-ingestion accounts
        it once.
        """

        if not expected_error_fragment.strip():
            raise ValueError("expected_error_fragment must be non-empty")
        if runtime_error_key not in {"transaction_error", "hook_receipt_error"}:
            raise ValueError("runtime_error_key is not an approved replayable failure")
        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT tasks.campaign_id, tasks.status AS task_status,
                       tasks.current_attempt_id, tasks.last_error,
                       task_attempts.status AS attempt_status,
                       task_attempts.run_seconds,
                       result_bundles.valid, result_bundles.gate_passed,
                       result_bundles.runtime_json
                FROM tasks
                JOIN task_attempts
                  ON task_attempts.attempt_id=tasks.current_attempt_id
                 AND task_attempts.task_id=tasks.task_id
                JOIN result_bundles ON result_bundles.task_id=tasks.task_id
                WHERE tasks.task_id=? AND tasks.current_attempt_id=?
                """,
                (task_id, attempt_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"No current result exists for {task_id}/{attempt_id}")
            if str(row["task_status"]) != "needs_replan":
                raise ValueError(f"Task {task_id} is not a protocol needs_replan result")
            if str(row["attempt_status"]) != "needs_replan":
                raise ValueError(f"Attempt {attempt_id} is not in needs_replan")
            if not bool(row["valid"]) or not bool(row["gate_passed"]):
                raise ValueError("The result did not pass its ordinary evidence gate")
            runtime = json.loads(str(row["runtime_json"]))
            infrastructure_error = str(runtime.get(runtime_error_key) or "")
            last_error = str(row["last_error"] or "")
            if (
                expected_error_fragment not in infrastructure_error
                or expected_error_fragment not in last_error
            ):
                raise ValueError(
                    "The recorded failure does not match the expected infrastructure error"
                )
            charged_seconds = max(0.0, float(row["run_seconds"] or 0.0))
            connection.execute(
                """
                UPDATE tasks
                SET status='running', lease_owner='infrastructure-replay',
                    lease_expires_at=?, worker_pid=NULL, not_before=NULL,
                    last_error=NULL, updated_at=?
                WHERE task_id=? AND current_attempt_id=?
                """,
                (utc_after(lease_seconds), now, task_id, attempt_id),
            )
            connection.execute(
                """
                UPDATE task_attempts
                SET status='running', finished_at=NULL, run_seconds=0, error=NULL
                WHERE task_id=? AND attempt_id=?
                """,
                (task_id, attempt_id),
            )
            connection.execute(
                """
                UPDATE campaigns
                SET agent_seconds_used=MAX(0, agent_seconds_used-?),
                    epoch_agent_seconds_used=MAX(0, epoch_agent_seconds_used-?),
                    updated_at=?
                WHERE campaign_id=?
                """,
                (charged_seconds, charged_seconds, now, str(row["campaign_id"])),
            )
            self._event(
                connection,
                "task",
                task_id,
                "protocol_ingest_reopened",
                {
                    "attempt_id": attempt_id,
                    "expected_error_fragment": expected_error_fragment,
                    "runtime_error_key": runtime_error_key,
                    "prior_run_seconds": charged_seconds,
                },
            )
        return {
            "task_id": task_id,
            "attempt_id": attempt_id,
            "campaign_id": str(row["campaign_id"]),
            "runtime_error_key": runtime_error_key,
            "prior_run_seconds": charged_seconds,
        }

    def stop_budget_exhausted_tasks(self) -> list[str]:
        """Stop queued work once a campaign has consumed its hard Agent-time budget."""

        now = utc_now()
        stopped: list[str] = []
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            campaigns = connection.execute(
                """
                SELECT campaign_id, agent_seconds_used, max_agent_seconds
                FROM campaigns
                WHERE status='active'
                  AND agent_seconds_used + 1 > max_agent_seconds
                ORDER BY campaign_id
                """
            ).fetchall()
            for campaign in campaigns:
                campaign_id = str(campaign["campaign_id"])
                rows = connection.execute(
                    """
                    SELECT task_id FROM tasks
                    WHERE campaign_id=? AND status='queued'
                    ORDER BY task_id
                    """,
                    (campaign_id,),
                ).fetchall()
                connection.execute(
                    """
                    UPDATE tasks SET status='needs_human', not_before=NULL,
                        last_error='campaign_agent_time_budget_exhausted', updated_at=?
                    WHERE campaign_id=? AND status='queued'
                    """,
                    (now, campaign_id),
                )
                connection.execute(
                    """
                    UPDATE campaigns
                    SET status='budget_exhausted', continuous=0, updated_at=?
                    WHERE campaign_id=?
                    """,
                    (now, campaign_id),
                )
                for row in rows:
                    task_id = str(row["task_id"])
                    stopped.append(task_id)
                    self._event(
                        connection,
                        "task",
                        task_id,
                        "task_needs_human",
                        {"reason": "campaign_agent_time_budget_exhausted"},
                    )
                self._event(
                    connection,
                    "campaign",
                    campaign_id,
                    "campaign_budget_exhausted",
                    {
                        "agent_seconds_used": float(campaign["agent_seconds_used"]),
                        "max_agent_seconds": int(campaign["max_agent_seconds"]),
                    },
                )
        return stopped

    def task_attempts(self, task_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM task_attempts
                WHERE task_id=? ORDER BY attempt_number
                """,
                (task_id,),
            ).fetchall()
        attempts: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["runtime"] = json.loads(str(item.pop("runtime_json")))
            item["resources"] = json.loads(str(item.pop("resources_json")))
            attempts.append(item)
        return attempts

    def attempt_record(self, attempt_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM task_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def status_counts(self) -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS n FROM tasks GROUP BY status ORDER BY status"
            ).fetchall()
        return {str(row["status"]): int(row["n"]) for row in rows}

    def upsert_research_record(
        self,
        record_id: str,
        *,
        kind: str,
        domain: str,
        title: str,
        status: str,
        source_path: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Index one durable file-owned object without replacing its source file."""

        now = utc_now()
        metadata_json = json.dumps(dict(metadata or {}), ensure_ascii=False, sort_keys=True)
        with self.connect() as connection:
            existing = connection.execute(
                """
                SELECT kind, domain, title, status, source_path, metadata_json
                FROM research_records WHERE record_id=?
                """,
                (record_id,),
            ).fetchone()
            desired = (kind, domain, title, status, source_path, metadata_json)
            if existing is not None and tuple(existing) == desired:
                return
            connection.execute(
                """
                INSERT INTO research_records(
                    record_id, kind, domain, title, status, source_path,
                    metadata_json, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(record_id) DO UPDATE SET
                    kind=excluded.kind,
                    domain=excluded.domain,
                    title=excluded.title,
                    status=excluded.status,
                    source_path=excluded.source_path,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    record_id,
                    kind,
                    domain,
                    title,
                    status,
                    source_path,
                    metadata_json,
                    now,
                    now,
                ),
            )
            event = "research_record_indexed" if existing is None else "research_record_updated"
            self._event(connection, kind, record_id, event)

    def research_record_counts(self) -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT kind, COUNT(*) AS n FROM research_records GROUP BY kind ORDER BY kind"
            ).fetchall()
        return {str(row["kind"]): int(row["n"]) for row in rows}

    def research_records(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT record_id, kind, domain, title, status, source_path,
                       metadata_json, created_at, updated_at
                FROM research_records
                ORDER BY kind, record_id
                """
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(str(item.pop("metadata_json")))
            result.append(item)
        return result

    def campaigns(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM campaigns ORDER BY domain, campaign_id"
            ).fetchall()
        return [dict(row) for row in rows]
