"""SQLite state store for campaigns, tasks, leases, results, and events."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 4
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
class RecoverySummary:
    requeued: tuple[str, ...]
    quarantined: tuple[str, ...]


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
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
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
                    status TEXT NOT NULL DEFAULT 'queued',
                    priority INTEGER NOT NULL DEFAULT 0,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    not_before TEXT,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    worker_pid INTEGER,
                    current_attempt_id TEXT,
                    max_wall_seconds INTEGER NOT NULL DEFAULT 14400,
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
            connection.executescript(
                """
                CREATE INDEX IF NOT EXISTS task_attempts_task_idx
                    ON task_attempts(task_id, attempt_number);
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
            "max_wall_seconds INTEGER NOT NULL DEFAULT 14400",
        ):
            cls._add_column(connection, "tasks", definition)
        for definition in (
            "attempt_id TEXT",
            "runtime_json TEXT NOT NULL DEFAULT '{}'",
        ):
            cls._add_column(connection, "result_bundles", definition)
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
        max_wall_seconds: int = 14_400,
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
                "SELECT domain, status FROM campaigns WHERE campaign_id=?",
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
                    session_source_task_id, status, priority, max_attempts, not_before,
                    max_wall_seconds, cpu_threads, memory_mib, scratch_mib,
                    created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
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
                SELECT tasks.*, campaigns.max_agent_seconds, campaigns.agent_seconds_used
                FROM tasks
                JOIN campaigns USING(campaign_id)
                WHERE tasks.status = 'queued'
                  AND campaigns.status = 'active'
                  AND campaigns.agent_seconds_used + 1 <= campaigns.max_agent_seconds
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
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT task_id, campaign_id, attempt, max_attempts, current_attempt_id,
                       max_wall_seconds
                FROM tasks
                WHERE status IN ('leased', 'running')
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at < ?
                ORDER BY task_id
                """,
                (now,),
            ).fetchall()
            for row in rows:
                task_id = str(row["task_id"])
                exhausted = int(row["attempt"]) >= int(row["max_attempts"])
                status = "quarantined" if exhausted else "queued"
                not_before = (
                    None
                    if exhausted
                    else retry_not_before(int(row["attempt"]), retry_backoff_seconds)
                )
                connection.execute(
                    """
                    UPDATE tasks SET status=?, lease_owner=NULL, lease_expires_at=NULL,
                        worker_pid=NULL, current_attempt_id=NULL, output_path=NULL,
                        not_before=?, updated_at=?, last_error='lease_expired'
                    WHERE task_id=?
                    """,
                    (status, not_before, now, task_id),
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
                        UPDATE task_attempts SET status='lease_expired', finished_at=?,
                            run_seconds=?, error='lease_expired'
                        WHERE attempt_id=? AND status IN ('leased', 'running')
                        """,
                        (now, elapsed, attempt_id),
                    )
                    connection.execute(
                        """
                        UPDATE campaigns
                        SET agent_seconds_used=agent_seconds_used+?, updated_at=?
                        WHERE campaign_id=?
                        """,
                        (elapsed, now, str(row["campaign_id"])),
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
                (quarantined if exhausted else requeued).append(task_id)
        return RecoverySummary(tuple(requeued), tuple(quarantined))

    def fail_launch(
        self,
        task_id: str,
        error: str,
        retry_backoff_seconds: int = 0,
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT attempt, max_attempts, current_attempt_id
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
                UPDATE campaigns SET agent_seconds_used=agent_seconds_used+?, updated_at=?
                WHERE campaign_id=?
                """,
                (bounded_seconds, now, str(row["campaign_id"])),
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
                WHERE status='active' AND agent_seconds_used + 1 > max_agent_seconds
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
                    UPDATE campaigns SET status='budget_exhausted', updated_at=?
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
