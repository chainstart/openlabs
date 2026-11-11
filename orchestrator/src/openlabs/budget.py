"""Provider-quota backoff and adaptive agent parallelism.

All state lives in the ``meta`` table so it survives restarts:

* ``effective_parallel`` -- current global launch ceiling. Absent means "no
  reduction" (the configured ceiling applies), so scheduling is unchanged until
  the first ``agent_quota`` failure.
* ``provider_backoff_until:<runner>`` -- ISO UTC time before which tasks of that
  runner tier are not claimed.
* ``provider_backoff_level:<runner>`` -- consecutive escalations, indexing
  ``quota_backoff_minutes``; cleared by a healthy completion.
* ``provider_probe:<runner>`` -- set while a runner recovers: after its backoff
  ends only one task of that runner may be in flight until one finishes without
  a quota error.

Times are injectable (``now=``) and default to :func:`current_time`, which tests
may monkeypatch.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .config import BudgetSettings, FactorySettings
from .db import FactoryDB, normalize_runner

EFFECTIVE_PARALLEL_KEY = "effective_parallel"
BACKOFF_UNTIL_PREFIX = "provider_backoff_until:"
BACKOFF_LEVEL_PREFIX = "provider_backoff_level:"
PROBE_PREFIX = "provider_probe:"
# Results that say nothing about provider health and must not restore parallelism.
UNHEALTHY_FAILURE_CLASSES = frozenset(
    {
        "agent_quota",
        "agent_transport",
        "agent_connectivity_preflight",
        "agent_interrupted",
        "lab_runtime_setup",
    }
)


def current_time() -> datetime:
    return datetime.now(UTC)


def _now(now: datetime | None) -> datetime:
    return (now or current_time()).astimezone(UTC)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parallel_ceiling(settings: FactorySettings) -> int:
    """``min(max_worker_processes, max_parallel_agents)``; the latter defaults to the former."""

    configured = settings.budget.max_parallel_agents
    ceiling = settings.max_worker_processes
    if configured is not None:
        ceiling = min(ceiling, int(configured))
    return max(1, ceiling)


def effective_parallel(db: FactoryDB, settings: FactorySettings) -> int:
    ceiling = parallel_ceiling(settings)
    raw = db.meta_get(EFFECTIVE_PARALLEL_KEY)
    if raw is None:
        return ceiling
    try:
        value = int(raw)
    except ValueError:
        return ceiling
    return max(1, min(ceiling, value))


def launch_limit(db: FactoryDB, settings: FactorySettings) -> int:
    """The tick's launch ceiling: min(max_worker_processes, effective, max_parallel_agents)."""

    return min(parallel_ceiling(settings), effective_parallel(db, settings))


def runner_backoffs(db: FactoryDB, *, now: datetime | None = None) -> dict[str, str]:
    """Runner tiers whose provider backoff has not ended yet, with their end time."""

    moment = _now(now)
    active: dict[str, str] = {}
    for runner, value in db.meta_items(BACKOFF_UNTIL_PREFIX).items():
        until = parse_time(value)
        if until is not None and until > moment:
            active[runner] = _iso(until)
    return active


def probe_limits(db: FactoryDB, *, now: datetime | None = None) -> dict[str, int]:
    """Runners recovering from a backoff: at most one task in flight each."""

    blocked = runner_backoffs(db, now=now)
    return {runner: 1 for runner in db.meta_items(PROBE_PREFIX) if runner not in blocked}


@dataclass(frozen=True)
class QuotaBackoff:
    runner: str
    until: str
    level: int
    parallel_before: int
    parallel_after: int
    escalated: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "runner": self.runner,
            "until": self.until,
            "level": self.level,
            "parallel_before": self.parallel_before,
            "parallel_after": self.parallel_after,
            "escalated": self.escalated,
        }


def backoff_until(
    budget: BudgetSettings,
    *,
    level: int,
    now: datetime,
    reset_at: datetime | None,
) -> datetime:
    """``max(exponential step, provider reset)``, capped at ``quota_backoff_cap_minutes``."""

    sequence = budget.quota_backoff_minutes or (15,)
    minutes = sequence[min(max(0, level), len(sequence) - 1)]
    cap = now + timedelta(minutes=max(1, budget.quota_backoff_cap_minutes))
    candidate = now + timedelta(minutes=minutes)
    if reset_at is not None and reset_at > candidate:
        candidate = reset_at
    return min(candidate, cap)


def record_quota_failure(
    db: FactoryDB,
    settings: FactorySettings,
    *,
    runner: Any,
    reset_at: Any = None,
    task_id: str | None = None,
    now: datetime | None = None,
) -> QuotaBackoff:
    """Enter (or extend) provider backoff for ``runner`` and halve parallelism.

    A quota result that arrives while the runner is already backing off (other
    agents launched before the first hit) neither escalates the exponential
    level nor halves parallelism again; it only extends the backoff when the
    provider states a later reset time.
    """

    moment = _now(now)
    runner_name = normalize_runner(runner)
    budget = settings.budget
    reset_time = parse_time(reset_at)
    current_until = parse_time(db.meta_get(BACKOFF_UNTIL_PREFIX + runner_name))
    try:
        level = int(db.meta_get(BACKOFF_LEVEL_PREFIX + runner_name) or 0)
    except ValueError:
        level = 0
    before = effective_parallel(db, settings)
    updates: dict[str, str | None] = {}
    events: list[tuple[str, str, str, Mapping[str, Any]]] = []
    if current_until is not None and current_until > moment:
        until = current_until
        if reset_time is not None and reset_time > current_until:
            until = min(
                reset_time,
                moment + timedelta(minutes=max(1, budget.quota_backoff_cap_minutes)),
            )
        result = QuotaBackoff(
            runner=runner_name,
            until=_iso(until),
            level=max(0, level - 1),
            parallel_before=before,
            parallel_after=before,
            escalated=False,
        )
        if until > current_until:
            updates[BACKOFF_UNTIL_PREFIX + runner_name] = _iso(until)
            events.append(
                (
                    "provider",
                    runner_name,
                    "quota_backoff",
                    {**result.to_dict(), "task_id": task_id, "reset_at": reset_at,
                     "extended": True},
                )
            )
        db.update_meta(updates, events=events)
        return result
    until = backoff_until(budget, level=level, now=moment, reset_at=reset_time)
    after = max(1, before // 2)
    result = QuotaBackoff(
        runner=runner_name,
        until=_iso(until),
        level=level,
        parallel_before=before,
        parallel_after=after,
        escalated=True,
    )
    updates[BACKOFF_UNTIL_PREFIX + runner_name] = result.until
    updates[BACKOFF_LEVEL_PREFIX + runner_name] = str(level + 1)
    updates[PROBE_PREFIX + runner_name] = "1"
    updates[EFFECTIVE_PARALLEL_KEY] = str(after)
    events.append(
        (
            "provider",
            runner_name,
            "quota_backoff",
            {**result.to_dict(), "task_id": task_id, "reset_at": reset_at},
        )
    )
    if after < before:
        events.append(
            (
                "scheduler",
                EFFECTIVE_PARALLEL_KEY,
                "parallel_reduced",
                {"from": before, "to": after, "runner": runner_name, "task_id": task_id},
            )
        )
    db.update_meta(updates, events=events)
    return result


def record_healthy_completion(
    db: FactoryDB,
    settings: FactorySettings,
    *,
    runner: Any,
    task_id: str | None = None,
    now: datetime | None = None,
) -> int | None:
    """A task finished without a quota error: end probing and restore parallelism.

    Returns the new ``effective_parallel`` when it changed, else None. A no-op
    when no quota failure was ever recorded, and while ``runner`` itself is still
    inside its backoff window (such a task started before the quota hit and
    proves nothing about recovery).
    """

    runner_name = normalize_runner(runner)
    if runner_name in runner_backoffs(db, now=now):
        return None
    updates: dict[str, str | None] = {}
    events: list[tuple[str, str, str, Mapping[str, Any]]] = []
    if db.meta_get(PROBE_PREFIX + runner_name) is not None:
        updates[PROBE_PREFIX + runner_name] = None
    if db.meta_get(BACKOFF_LEVEL_PREFIX + runner_name) is not None:
        updates[BACKOFF_LEVEL_PREFIX + runner_name] = None
    restored: int | None = None
    if db.meta_get(EFFECTIVE_PARALLEL_KEY) is not None:
        ceiling = parallel_ceiling(settings)
        before = effective_parallel(db, settings)
        after = min(ceiling, before + max(1, settings.budget.restore_step))
        if after >= ceiling:
            # Fully restored: drop the key so the configured ceiling applies again.
            updates[EFFECTIVE_PARALLEL_KEY] = None
        else:
            updates[EFFECTIVE_PARALLEL_KEY] = str(after)
        if after > before:
            restored = after
            events.append(
                (
                    "scheduler",
                    EFFECTIVE_PARALLEL_KEY,
                    "parallel_restored",
                    {"from": before, "to": after, "runner": runner_name, "task_id": task_id},
                )
            )
    if updates or events:
        db.update_meta(updates, events=events)
    return restored


def is_healthy_result(runtime: Mapping[str, Any]) -> bool:
    """Whether an ingested result proves the provider accepted the agent's work."""

    if str(runtime.get("adapter") or "") in {"deterministic", "unconfigured", "ephemeral"}:
        return False
    return str(runtime.get("failure_class") or "") not in UNHEALTHY_FAILURE_CLASSES


def budget_status(
    db: FactoryDB,
    settings: FactorySettings,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    return {
        "effective_parallel": effective_parallel(db, settings),
        "parallel_ceiling": parallel_ceiling(settings),
        "provider_backoff_until": runner_backoffs(db, now=now),
        "probing_runners": sorted(probe_limits(db, now=now)),
    }
