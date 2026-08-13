from __future__ import annotations

import sqlite3

import pytest

from openlabs.db import FactoryDB
from openlabs.worker import _heartbeat_with_contention_tolerance


class _HeartbeatDB:
    def __init__(self, outcome):
        self.outcome = outcome

    def heartbeat(self, *args, **kwargs):
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def test_transient_sqlite_lock_does_not_kill_a_live_agent(capsys) -> None:
    outcome = _heartbeat_with_contention_tolerance(
        _HeartbeatDB(sqlite3.OperationalError("database is locked")),
        "task-1",
        attempt_id="attempt-1",
        owner="worker-1",
        lease_seconds=600,
    )

    assert outcome is None
    assert "will retry within its lease" in capsys.readouterr().err


def test_authoritative_lease_loss_is_still_reported() -> None:
    assert (
        _heartbeat_with_contention_tolerance(
            _HeartbeatDB(False),
            "task-1",
            attempt_id="attempt-1",
            owner="worker-1",
            lease_seconds=600,
        )
        is False
    )


def test_non_contention_sqlite_error_is_not_hidden() -> None:
    with pytest.raises(sqlite3.OperationalError, match="malformed"):
        _heartbeat_with_contention_tolerance(
            _HeartbeatDB(sqlite3.OperationalError("database disk image is malformed")),
            "task-1",
            attempt_id="attempt-1",
            owner="worker-1",
            lease_seconds=600,
        )


def test_factory_connections_reuse_persistent_wal_without_renegotiating(tmp_path) -> None:
    db = FactoryDB(tmp_path / "factory.sqlite")
    db.initialize()

    statements: list[str] = []
    with db.connect() as connection:
        connection.set_trace_callback(statements.append)
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        connection.execute("SELECT 1").fetchone()

    assert not any("journal_mode = wal" in statement.lower() for statement in statements)
