"""Provider-quota backoff, subscription headroom and quota-aware runner routing.

All state lives in the ``meta`` table so it survives restarts:

* ``effective_parallel`` -- current global launch ceiling. Absent means "no
  reduction" (the configured ceiling applies), so scheduling is unchanged until
  the first ``agent_quota`` failure.
* ``provider_backoff_until:<provider>`` -- ISO UTC time before which tasks of
  every runner of that provider are not claimed.
* ``provider_backoff_level:<provider>`` -- consecutive escalations, indexing
  ``quota_backoff_minutes``; cleared by a healthy completion.
* ``provider_probe:<provider>`` -- set while a provider recovers: after its
  backoff ends only one of its tasks may be in flight until one finishes
  without a quota error.
* ``quota_window:<provider>/<window>`` -- newest reading of one quota window
  (JSON: used_fraction, window_minutes, resets_at, observed_at, model, task_id).
  Windows are kept separately, so a cheap-model reading never erases a
  model-specific window (Fable's ``seven_day_overage_included``).
* ``quota_snapshot:<provider>`` -- the last whole snapshot (credits, source).
* ``lead_quota_short`` -- present while no lead runner may take decision tasks.

The "provider" of a runner is its ``[runners.<name>].provider``. Without a
``[runners]`` table every runner name is its own provider, which is exactly the
per-runner keying of the previous release; with one, legacy per-runner keys
(``provider_backoff_until:frontier``) are folded into their provider.

Times are injectable (``now=``) and default to :func:`current_time`, which tests
may monkeypatch. Everything that decides is a pure function of readings and a
clock; only the ``record_*``/``probe_*`` helpers write.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any

from .config import (
    LEGACY_RUNNER_TIERS,
    TIERS,
    BudgetSettings,
    FactorySettings,
    RoutingSettings,
    RunnerSpec,
)
from .db import FactoryDB, normalize_runner

EFFECTIVE_PARALLEL_KEY = "effective_parallel"
BACKOFF_UNTIL_PREFIX = "provider_backoff_until:"
BACKOFF_LEVEL_PREFIX = "provider_backoff_level:"
PROBE_PREFIX = "provider_probe:"
QUOTA_WINDOW_PREFIX = "quota_window:"
QUOTA_SNAPSHOT_PREFIX = "quota_snapshot:"
QUOTA_PROBE_AT_PREFIX = "quota_probe_at:"
LEAD_SHORTAGE_KEY = "lead_quota_short"
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
TASK_CLASSES = ("decision", "review", "ordinary")
ADAPTER_PROVIDERS = {"claude": "anthropic", "codex": "openai-codex"}


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


# ----------------------------------------------------------------- providers


def routing_enabled(settings: FactorySettings) -> bool:
    """Quota-aware routing only runs when a ``[runners]`` table is configured."""

    return bool(settings.runners)


def provider_of(settings: FactorySettings | None, runner: Any) -> str:
    """The account a runner draws quota from (the runner name itself without ``[runners]``)."""

    name = normalize_runner(runner)
    if settings is None or not settings.runners:
        return name
    spec = settings.runners.get(name)
    if spec is not None:
        return spec.provider
    if name in LEGACY_RUNNER_TIERS:
        return settings.routing.legacy_runner_provider
    return name


def tier_of(settings: FactorySettings, runner: Any) -> str | None:
    name = normalize_runner(runner)
    spec = settings.runners.get(name)
    if spec is not None:
        return spec.tier
    return LEGACY_RUNNER_TIERS.get(name) or (name if name in TIERS else None)


def _provider_meta(
    db: FactoryDB,
    prefix: str,
    settings: FactorySettings | None,
    provider: str,
) -> dict[str, str]:
    """Meta entries under ``prefix`` that belong to ``provider`` (incl. legacy runner keys)."""

    return {
        prefix + suffix: value
        for suffix, value in db.meta_items(prefix).items()
        if provider_of(settings, suffix) == provider
    }


# ------------------------------------------------------------------ parallelism


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


def runner_backoffs(
    db: FactoryDB,
    *,
    now: datetime | None = None,
    settings: FactorySettings | None = None,
) -> dict[str, str]:
    """Providers (runner names without ``[runners]``) whose backoff has not ended yet."""

    moment = _now(now)
    active: dict[str, datetime] = {}
    for suffix, value in db.meta_items(BACKOFF_UNTIL_PREFIX).items():
        until = parse_time(value)
        if until is None or until <= moment:
            continue
        provider = provider_of(settings, suffix)
        if provider not in active or until > active[provider]:
            active[provider] = until
    return {provider: _iso(until) for provider, until in sorted(active.items())}


provider_backoffs = runner_backoffs


def blocked_runner_names(
    db: FactoryDB,
    settings: FactorySettings,
    *,
    now: datetime | None = None,
) -> tuple[str, ...]:
    """Runner names to exclude at claim time because their provider backs off."""

    blocked = runner_backoffs(db, now=now, settings=settings)
    if not settings.runners:
        return tuple(blocked)
    names = {name for name, spec in settings.runners.items() if spec.provider in blocked}
    names.update(name for name in LEGACY_RUNNER_TIERS if provider_of(settings, name) in blocked)
    names.update(blocked)
    return tuple(sorted(names))


def probe_limits(
    db: FactoryDB,
    *,
    now: datetime | None = None,
    settings: FactorySettings | None = None,
) -> dict[str, int]:
    """Providers recovering from a backoff: at most one task in flight each."""

    blocked = runner_backoffs(db, now=now, settings=settings)
    providers = {provider_of(settings, suffix) for suffix in db.meta_items(PROBE_PREFIX)}
    return {provider: 1 for provider in sorted(providers) if provider not in blocked}


@dataclass(frozen=True)
class QuotaBackoff:
    runner: str
    until: str
    level: int
    parallel_before: int
    parallel_after: int
    escalated: bool
    provider: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "runner": self.runner,
            "provider": self.provider or self.runner,
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
    """Enter (or extend) provider backoff for ``runner``'s provider and halve parallelism.

    Every runner of the provider shares the backoff. A quota result that arrives
    while the provider is already backing off (other agents launched before the
    first hit) neither escalates the exponential level nor halves parallelism
    again; it only extends the backoff when the provider states a later reset.
    """

    moment = _now(now)
    runner_name = normalize_runner(runner)
    provider = provider_of(settings, runner_name)
    budget = settings.budget
    reset_time = parse_time(reset_at)
    untils = [
        parse_time(value)
        for value in _provider_meta(db, BACKOFF_UNTIL_PREFIX, settings, provider).values()
    ]
    current_until = max((item for item in untils if item is not None), default=None)
    levels: list[int] = []
    for value in _provider_meta(db, BACKOFF_LEVEL_PREFIX, settings, provider).values():
        try:
            levels.append(int(value))
        except ValueError:
            continue
    level = max(levels, default=0)
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
            provider=provider,
        )
        if until > current_until:
            updates[BACKOFF_UNTIL_PREFIX + provider] = _iso(until)
            events.append(
                (
                    "provider",
                    provider,
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
        provider=provider,
    )
    # Fold legacy per-runner keys of this provider into the provider key.
    for prefix in (BACKOFF_UNTIL_PREFIX, BACKOFF_LEVEL_PREFIX, PROBE_PREFIX):
        for key in _provider_meta(db, prefix, settings, provider):
            updates[key] = None
    updates[BACKOFF_UNTIL_PREFIX + provider] = result.until
    updates[BACKOFF_LEVEL_PREFIX + provider] = str(level + 1)
    updates[PROBE_PREFIX + provider] = "1"
    updates[EFFECTIVE_PARALLEL_KEY] = str(after)
    events.append(
        (
            "provider",
            provider,
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
                {"from": before, "to": after, "runner": runner_name, "provider": provider,
                 "task_id": task_id},
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
    when no quota failure was ever recorded, and while the runner's provider is
    still inside its backoff window (such a task started before the quota hit
    and proves nothing about recovery).
    """

    runner_name = normalize_runner(runner)
    provider = provider_of(settings, runner_name)
    if provider in runner_backoffs(db, now=now, settings=settings):
        return None
    updates: dict[str, str | None] = {}
    events: list[tuple[str, str, str, Mapping[str, Any]]] = []
    for prefix in (PROBE_PREFIX, BACKOFF_LEVEL_PREFIX):
        for key in _provider_meta(db, prefix, settings, provider):
            updates[key] = None
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
                    {"from": before, "to": after, "runner": runner_name, "provider": provider,
                     "task_id": task_id},
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


# ------------------------------------------------------------ quota readings


@dataclass(frozen=True)
class WindowReading:
    provider: str
    name: str
    used_fraction: float
    window_minutes: int | None
    resets_at: datetime | None
    observed_at: datetime
    model: str | None = None
    task_id: str | None = None
    # Set on an extrapolated reading (``estimate_stale_readings``): when the
    # real reading it starts from was observed. Never stored.
    estimated_from: datetime | None = None

    @property
    def estimated(self) -> bool:
        return self.estimated_from is not None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "used_fraction": round(self.used_fraction, 4),
            "window_minutes": self.window_minutes,
            "resets_at": _iso(self.resets_at) if self.resets_at else None,
            "observed_at": _iso(self.observed_at),
            "model": self.model,
            "task_id": self.task_id,
        }
        if self.estimated_from is not None:
            payload["estimated_from"] = _iso(self.estimated_from)
        return payload


def _reading_from_json(provider: str, name: str, raw: str) -> WindowReading | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, Mapping):
        return None
    observed = parse_time(payload.get("observed_at"))
    try:
        used = float(payload.get("used_fraction"))
    except (TypeError, ValueError):
        return None
    if observed is None:
        return None
    minutes = payload.get("window_minutes")
    return WindowReading(
        provider=provider,
        name=name,
        used_fraction=max(0.0, min(1.0, used)),
        window_minutes=int(minutes) if isinstance(minutes, int) and minutes > 0 else None,
        resets_at=parse_time(payload.get("resets_at")),
        observed_at=observed,
        model=payload.get("model") if isinstance(payload.get("model"), str) else None,
        task_id=payload.get("task_id") if isinstance(payload.get("task_id"), str) else None,
    )


def normalize_quota_snapshot(raw: Any) -> dict[str, Any] | None:
    """Validate a ``runtime.quota_snapshot``; used fractions are clamped to 0..1."""

    if not isinstance(raw, Mapping):
        return None
    windows: list[dict[str, Any]] = []
    for item in raw.get("windows") or []:
        if not isinstance(item, Mapping) or not str(item.get("name") or "").strip():
            continue
        try:
            used = float(item.get("used_fraction"))
        except (TypeError, ValueError):
            continue
        minutes = item.get("window_minutes")
        windows.append(
            {
                "name": str(item["name"]).strip(),
                "used_fraction": max(0.0, min(1.0, used)),
                "window_minutes": (
                    int(minutes) if isinstance(minutes, (int, float)) and minutes > 0 else None
                ),
                "resets_at": item.get("resets_at") if parse_time(item.get("resets_at")) else None,
            }
        )
    if not windows:
        return None
    return {
        "provider": str(raw.get("provider") or "").strip() or None,
        "observed_at": raw.get("observed_at"),
        "model": raw.get("model") if isinstance(raw.get("model"), str) else None,
        "source": raw.get("source"),
        "credits_balance": raw.get("credits_balance"),
        "windows": windows,
    }


def record_quota_snapshot(
    db: FactoryDB,
    settings: FactorySettings,
    snapshot: Any,
    *,
    runner: Any = None,
    task_id: str | None = None,
    now: datetime | None = None,
) -> str | None:
    """Store a reading per (provider, window); older readings never replace newer ones.

    The provider is the runner's configured provider when ``[runners]`` names it,
    otherwise the snapshot's own provider. Returns the provider written, or None.
    """

    normalized = normalize_quota_snapshot(snapshot)
    if normalized is None:
        return None
    configured = (
        settings.runners.get(normalize_runner(runner)) if runner is not None else None
    )
    provider = configured.provider if configured else normalized["provider"]
    if not provider or "/" in provider:
        return None
    observed = parse_time(normalized["observed_at"]) or _now(now)
    model = normalized["model"] or (configured.model if configured else None)
    stored = db.meta_items(f"{QUOTA_WINDOW_PREFIX}{provider}/")
    updates: dict[str, str | None] = {}
    for window in normalized["windows"]:
        name = window["name"]
        previous = stored.get(name)
        if previous is not None:
            prior = _reading_from_json(provider, name, previous)
            if prior is not None and prior.observed_at > observed:
                continue
        updates[f"{QUOTA_WINDOW_PREFIX}{provider}/{name}"] = json.dumps(
            {
                "used_fraction": window["used_fraction"],
                "window_minutes": window["window_minutes"],
                "resets_at": window["resets_at"],
                "observed_at": _iso(observed),
                "model": model,
                "task_id": task_id,
            },
            sort_keys=True,
        )
    previous_snapshot = db.meta_get(QUOTA_SNAPSHOT_PREFIX + provider)
    prior_observed = None
    if previous_snapshot:
        try:
            prior_observed = parse_time(json.loads(previous_snapshot).get("observed_at"))
        except (json.JSONDecodeError, AttributeError):
            prior_observed = None
    if prior_observed is None or prior_observed <= observed:
        updates[QUOTA_SNAPSHOT_PREFIX + provider] = json.dumps(
            {**normalized, "provider": provider, "observed_at": _iso(observed),
             "model": model, "task_id": task_id},
            sort_keys=True,
            default=str,
        )
    if updates:
        db.update_meta(updates)
    return provider


def quota_readings(db: FactoryDB) -> dict[str, dict[str, WindowReading]]:
    """``{provider: {window: newest reading}}`` from meta."""

    readings: dict[str, dict[str, WindowReading]] = {}
    for suffix, value in db.meta_items(QUOTA_WINDOW_PREFIX).items():
        provider, separator, name = suffix.partition("/")
        if not separator:
            continue
        reading = _reading_from_json(provider, name, value)
        if reading is not None:
            readings.setdefault(provider, {})[name] = reading
    return readings


def reading_is_fresh(
    reading: WindowReading,
    *,
    now: datetime,
    stale_hours: float,
) -> bool:
    """Fresh = observed within ``stale_hours`` and its window has not reset since."""

    if now - reading.observed_at > timedelta(hours=stale_hours):
        return False
    return reading.resets_at is None or reading.resets_at > now


def projected_fraction_at_reset(
    reading: WindowReading,
    *,
    now: datetime,
    min_elapsed_fraction: float = 0.1,
) -> float | None:
    """Linear projection of usage at the window's reset; None without enough information.

    ``rate = used / elapsed`` with ``elapsed = window - time_to_reset``, floored at
    ``min_elapsed_fraction`` of the window so the first minutes of a fresh window
    do not extrapolate a single burst to the whole week.
    """

    if reading.window_minutes is None or reading.resets_at is None:
        return None
    window = timedelta(minutes=reading.window_minutes)
    remaining = max(timedelta(0), reading.resets_at - now)
    if remaining > window:
        remaining = window
    elapsed = window - remaining
    floor = window * max(0.0, min(1.0, min_elapsed_fraction))
    elapsed = max(elapsed, floor, timedelta(seconds=1))
    rate = reading.used_fraction / elapsed.total_seconds()
    return reading.used_fraction + rate * remaining.total_seconds()


def is_overspeed(
    reading: WindowReading,
    *,
    now: datetime,
    min_elapsed_fraction: float = 0.1,
) -> bool:
    """At the current pace the window is used up before it resets."""

    if reading.used_fraction >= 1.0:
        return True
    projected = projected_fraction_at_reset(
        reading, now=now, min_elapsed_fraction=min_elapsed_fraction
    )
    return projected is not None and projected >= 1.0


# Below this share of its window left, a window counts as about to reset; the
# floor keeps relative abundance finite in the last minutes.
MIN_REMAINING_FRACTION = 0.01


def remaining_fraction(reading: WindowReading, *, now: datetime) -> float | None:
    """Share of the window still to run before it resets (None without its shape)."""

    if reading.window_minutes is None or reading.resets_at is None:
        return None
    window = timedelta(minutes=reading.window_minutes).total_seconds()
    remaining = (reading.resets_at - now).total_seconds()
    return max(0.0, min(1.0, remaining / window))


def window_abundance(
    reading: WindowReading,
    ceiling: float,
    *,
    now: datetime,
) -> float | None:
    """Relative abundance: ``(ceiling - used) / share of the window left``.

    The pace, relative to an even spend over one whole window, at which the
    quota left under ``ceiling`` would be used up exactly at the reset. Above 1
    the window holds more than an even pace would use (spend it before it
    resets); below 1 it must be spent more slowly than average. A window about
    to reset with quota left therefore ranks high, a freshly reset one low.
    """

    left = remaining_fraction(reading, now=now)
    if left is None:
        return None
    return (ceiling - reading.used_fraction) / max(left, MIN_REMAINING_FRACTION)


def _attempt_agent_seconds(
    db: FactoryDB,
    settings: FactorySettings,
    *,
    since: datetime,
    now: datetime,
) -> dict[str, float]:
    """Agent-seconds of this instance's attempts per provider since ``since``."""

    with db.connect() as connection:
        rows = connection.execute(
            """
            SELECT task_attempts.started_at, task_attempts.finished_at,
                   task_attempts.run_seconds, tasks.runner
            FROM task_attempts JOIN tasks USING(task_id)
            WHERE task_attempts.started_at IS NOT NULL
              AND (task_attempts.finished_at IS NULL OR task_attempts.finished_at >= ?)
            """,
            (_iso(since),),
        ).fetchall()
    totals: dict[str, float] = {}
    for row in rows:
        started = parse_time(row["started_at"])
        if started is None:
            continue
        finished = parse_time(row["finished_at"]) or now
        seconds = (finished - max(started, since)).total_seconds()
        if seconds <= 0:
            continue
        provider = provider_of(settings, row["runner"])
        totals[provider] = totals.get(provider, 0.0) + seconds
    return totals


def estimate_stale_readings(
    db: FactoryDB,
    settings: FactorySettings,
    readings: Mapping[str, Mapping[str, WindowReading]],
    *,
    now: datetime,
) -> dict[str, dict[str, WindowReading]]:
    """Replace stale-but-recent readings with a conservative extrapolation.

    ``used + window average pace x age + own agent-hours x
    estimate_fraction_per_agent_hour`` (the per-hour cost is stated for a
    7-day window and scaled to the window's length). Only readings younger than
    ``stale_estimate_hours`` whose window has not reset are extrapolated;
    everything else is returned unchanged.
    """

    routing = settings.routing
    result = {provider: dict(windows) for provider, windows in readings.items()}
    if routing.stale_estimate_hours <= 0:
        return result
    usage_cache: dict[datetime, dict[str, float]] = {}
    for provider, windows in result.items():
        for name, reading in list(windows.items()):
            if reading_is_fresh(reading, now=now, stale_hours=routing.snapshot_stale_hours):
                continue
            age = now - reading.observed_at
            if (
                age > timedelta(hours=routing.stale_estimate_hours)
                or reading.window_minutes is None
                or reading.resets_at is None
                or reading.resets_at <= now
            ):
                continue
            window = timedelta(minutes=reading.window_minutes)
            elapsed = window - min(window, max(timedelta(0), reading.resets_at - reading.observed_at))
            elapsed = max(elapsed, window * routing.pace_min_elapsed_fraction,
                          timedelta(seconds=1))
            others = reading.used_fraction / elapsed.total_seconds() * age.total_seconds()
            if reading.observed_at not in usage_cache:
                usage_cache[reading.observed_at] = _attempt_agent_seconds(
                    db, settings, since=reading.observed_at, now=now
                )
            hours = usage_cache[reading.observed_at].get(provider, 0.0) / 3600.0
            own = hours * routing.estimate_fraction_per_agent_hour * (
                10_080 / reading.window_minutes
            )
            windows[name] = WindowReading(
                provider=reading.provider,
                name=reading.name,
                used_fraction=max(0.0, min(1.0, reading.used_fraction + others + own)),
                window_minutes=reading.window_minutes,
                resets_at=reading.resets_at,
                observed_at=now,
                model=reading.model,
                task_id=reading.task_id,
                estimated_from=reading.observed_at,
            )
    return result


# --------------------------------------------------------------- availability


def task_class(settings: FactorySettings, task: Mapping[str, Any]) -> str:
    """``decision`` (admission/direction/portfolio), ``review`` or ``ordinary``."""

    task_type = str(task.get("task_type") or "")
    routing = settings.routing
    if task_type in routing.decision_task_types:
        return "decision"
    if task_type in routing.review_task_types or str(task.get("agent_role") or "") == "reviewer":
        return "review"
    return "ordinary"


def runner_windows(
    spec: RunnerSpec,
    runners: Mapping[str, RunnerSpec],
    observed: Iterable[str],
) -> tuple[str, ...]:
    """Windows constraining ``spec``: shared provider windows plus its own extras.

    A window some other runner of the provider declares as its own extra (Fable's
    ``seven_day_overage_included``) does not constrain the others.
    """

    foreign = {
        name
        for other in runners.values()
        if other.provider == spec.provider and other.name != spec.name
        for name in other.windows
    } - set(spec.windows)
    names = [name for name in observed if name not in foreign]
    names.extend(name for name in spec.windows if name not in names)
    return tuple(sorted(set(names)))


def protected_windows(
    provider: str,
    runners: Mapping[str, RunnerSpec],
    observed: Iterable[str],
) -> frozenset[str]:
    names: set[str] = set()
    observed_names = tuple(observed)
    for spec in runners.values():
        if spec.provider == provider and spec.protected:
            names.update(runner_windows(spec, runners, observed_names))
    return frozenset(names)


def window_ceiling(
    routing: RoutingSettings,
    *,
    klass: str,
    protected_window: bool,
    protected_runner: bool,
) -> float:
    """Highest used fraction a task class may push one window to.

    * ``review_reserve`` (default 15%) of every window is kept for review and
      decision tasks;
    * on windows the protected lead (Fable) depends on, ``lead_decision_reserve``
      (default 25%) is kept for decision tasks only -- reviews may not use it;
    * on the protected lead itself, review and ordinary work stop at
      ``lead_review_ceiling`` used (default 60%);
    * with ``utilization_target`` set, ordinary work also stops at that share:
      what is left above it is kept for review and decision tasks (the
      stricter of the target and the reserves applies).
    """

    decision_reserve = routing.lead_decision_reserve if protected_window else 0.0
    if klass == "decision":
        return 1.0
    if klass == "review":
        ceiling = 1.0 - decision_reserve
    else:
        ceiling = 1.0 - max(routing.review_reserve, decision_reserve)
        if routing.utilization_target > 0:
            ceiling = min(ceiling, routing.utilization_target)
    if protected_runner:
        ceiling = min(ceiling, routing.lead_review_ceiling)
    return ceiling


@dataclass(frozen=True)
class Availability:
    """Whether one runner may take one class of task right now."""

    runner: str
    provider: str
    task_class: str
    state: str  # available | unknown | unavailable
    headroom: float | None
    overspeed: bool
    below_reserve: bool
    binding_window: str | None
    windows: tuple[dict[str, Any], ...] = ()
    unknown_windows: tuple[str, ...] = ()
    # "provider" when the shared windows are unknown, else "runner".
    unknown_scope: str | None = None
    reason: str | None = None
    # Protected lead only: some window has entered the decision reserve.
    in_lead_reserve: bool = False
    # Lowest relative abundance over the constraining windows (None unknown).
    abundance: float | None = None
    # Some constraining window is an extrapolated, not a measured, reading.
    estimated: bool = False

    @property
    def usable(self) -> bool:
        return self.state != "unavailable"

    def to_dict(self) -> dict[str, Any]:
        return {
            "runner": self.runner,
            "provider": self.provider,
            "task_class": self.task_class,
            "state": self.state,
            "headroom": None if self.headroom is None else round(self.headroom, 4),
            "overspeed": self.overspeed,
            "below_reserve": self.below_reserve,
            "binding_window": self.binding_window,
            "unknown_windows": list(self.unknown_windows),
            "reason": self.reason,
            "in_lead_reserve": self.in_lead_reserve,
            "abundance": None if self.abundance is None else round(self.abundance, 4),
            "estimated": self.estimated,
            "windows": list(self.windows),
        }


def runner_availability(
    spec: RunnerSpec,
    runners: Mapping[str, RunnerSpec],
    readings: Mapping[str, WindowReading],
    routing: RoutingSettings,
    *,
    klass: str,
    now: datetime,
) -> Availability:
    """Pure: headroom, pace and reserves of ``spec`` for a task class.

    The runner is unavailable when any constraining window is below its ceiling
    (``below_reserve``) or, for ordinary tasks, overspeed. Missing or stale
    windows make it ``unknown``: dispatch is allowed with parallelism 1 and an
    assumed headroom of ``routing.unknown_headroom``.
    """

    names = runner_windows(spec, runners, readings)
    guarded = protected_windows(spec.provider, runners, readings)
    headroom: float | None = None
    binding: str | None = None
    abundance: float | None = None
    estimated = False
    overspeed = False
    in_reserve = False
    unknown: list[str] = []
    details: list[dict[str, Any]] = []
    for name in names:
        reading = readings.get(name)
        if reading is None or not reading_is_fresh(
            reading, now=now, stale_hours=routing.snapshot_stale_hours
        ):
            unknown.append(name)
            continue
        ceiling = window_ceiling(
            routing,
            klass=klass,
            protected_window=name in guarded,
            protected_runner=spec.protected,
        )
        room = ceiling - reading.used_fraction
        # Overspeed means the hard limit (100%) is reached before the reset at
        # the window's average pace; the target is enforced by the ceiling, so
        # a window close to its reset with quota left is never overspeed.
        fast = is_overspeed(
            reading, now=now, min_elapsed_fraction=routing.pace_min_elapsed_fraction
        )
        overspeed = overspeed or fast
        estimated = estimated or reading.estimated
        if spec.protected and reading.used_fraction >= 1.0 - routing.lead_decision_reserve:
            in_reserve = True
        rich = window_abundance(reading, ceiling, now=now)
        projected = projected_fraction_at_reset(
            reading, now=now, min_elapsed_fraction=routing.pace_min_elapsed_fraction
        )
        details.append(
            {**reading.to_dict(), "ceiling": round(ceiling, 4), "headroom": round(room, 4),
             "overspeed": fast,
             "abundance": None if rich is None else round(rich, 4),
             "projected_at_reset": None if projected is None else round(projected, 4)}
        )
        if rich is not None and (abundance is None or rich < abundance):
            abundance = rich
        if headroom is None or room < headroom:
            headroom, binding = room, name
    below = headroom is not None and headroom <= 0
    reason: str | None = None
    if below:
        state = "unavailable"
        reason = (
            "lead_reserve"
            if spec.protected or (binding in guarded and klass != "decision")
            else "reserve"
        )
    elif overspeed and klass == "ordinary":
        state = "unavailable"
        reason = "overspeed"
    elif unknown or not names:
        state = "unknown"
        reason = "stale_or_missing_reading"
        assumed = routing.unknown_headroom
        headroom = assumed if headroom is None else min(headroom, assumed)
    else:
        state = "available"
    shared_known = any(
        name in readings
        and reading_is_fresh(readings[name], now=now, stale_hours=routing.snapshot_stale_hours)
        for name in names
        if name not in spec.windows
    )
    return Availability(
        runner=spec.name,
        provider=spec.provider,
        task_class=klass,
        state=state,
        headroom=headroom,
        overspeed=overspeed,
        below_reserve=below,
        binding_window=binding,
        windows=tuple(details),
        unknown_windows=tuple(unknown),
        unknown_scope=(None if state != "unknown" else "runner" if shared_known else "provider"),
        reason=reason,
        in_lead_reserve=in_reserve,
        abundance=abundance,
        estimated=estimated,
    )


def lead_availability(
    db: FactoryDB,
    settings: FactorySettings,
    *,
    runner: str | None = None,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Whether the protected lead (Fable) may take decision / review work now.

    Returns ``{runner: {"decision": bool, "review": bool, "state": {...}}}`` for
    ``runner`` or every protected runner. Unknown counts as usable.
    """

    moment = _now(now)
    readings = quota_readings(db)
    backoffs = runner_backoffs(db, now=moment, settings=settings)
    names = [runner] if runner else [n for n, s in settings.runners.items() if s.protected]
    result: dict[str, dict[str, Any]] = {}
    for name in names:
        spec = settings.runners.get(name)
        if spec is None:
            continue
        provider_readings = readings.get(spec.provider, {})
        states = {
            klass: runner_availability(
                spec, settings.runners, provider_readings, settings.routing,
                klass=klass, now=moment,
            )
            for klass in ("decision", "review")
        }
        blocked = spec.provider in backoffs
        result[name] = {
            "decision": states["decision"].usable and not blocked,
            "review": states["review"].usable and not blocked,
            "backoff_until": backoffs.get(spec.provider),
            "state": {klass: item.to_dict() for klass, item in states.items()},
        }
    return result


# -------------------------------------------------------------------- routing


@dataclass
class QuotaRouter:
    """Chooses a concrete runner per claimed task from the current readings.

    Built once per tick; ``route`` is the ``claim_next_task`` callback.
    """

    db: FactoryDB
    settings: FactorySettings
    now: datetime
    readings: dict[str, dict[str, WindowReading]] = field(default_factory=dict)
    backoffs: dict[str, str] = field(default_factory=dict)
    probes: dict[str, int] = field(default_factory=dict)
    deferred: dict[str, dict[str, Any]] = field(default_factory=dict)
    decisions: dict[str, dict[str, Any]] = field(default_factory=dict)
    lead_short: bool = False
    _cache: dict[tuple[str, str], Availability] = field(default_factory=dict)
    _task_cache: dict[str, dict[str, Any] | None] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        db: FactoryDB,
        settings: FactorySettings,
        *,
        now: datetime | None = None,
    ) -> QuotaRouter:
        moment = _now(now)
        router = cls(
            db=db,
            settings=settings,
            now=moment,
            readings=estimate_stale_readings(db, settings, quota_readings(db), now=moment),
            backoffs=runner_backoffs(db, now=moment, settings=settings),
            probes=probe_limits(db, now=moment, settings=settings),
        )
        leads = [spec for spec in settings.runners.values() if spec.tier == "lead"]
        router.lead_short = bool(leads) and not any(
            router.usable(spec, "decision") for spec in leads
        )
        return router

    # -- pure-ish helpers ----------------------------------------------------

    def availability(self, spec: RunnerSpec, klass: str) -> Availability:
        key = (spec.name, klass)
        if key not in self._cache:
            self._cache[key] = runner_availability(
                spec,
                self.settings.runners,
                self.readings.get(spec.provider, {}),
                self.settings.routing,
                klass=klass,
                now=self.now,
            )
        return self._cache[key]

    def usable(self, spec: RunnerSpec, klass: str) -> bool:
        return spec.provider not in self.backoffs and self.availability(spec, klass).usable

    @property
    def utilization_enabled(self) -> bool:
        return self.settings.routing.utilization_target > 0

    def _abundance(self, state: Availability) -> float:
        """Abundance used for ranking; unknown readings assume ``unknown_headroom``."""

        if state.abundance is not None and state.state != "unknown":
            return state.abundance
        assumed = self.settings.routing.unknown_headroom
        return assumed if state.abundance is None else min(state.abundance, assumed)

    def required_tier(self, task: Mapping[str, Any]) -> str:
        routing = self.settings.routing
        request = str(task.get("runner_request") or "")
        if request in TIERS:  # an escalation
            return request
        task_type = str(task.get("task_type") or "")
        if task_type in routing.task_tiers:
            return routing.task_tiers[task_type]
        alias = request or normalize_runner(task.get("runner"))
        if alias in LEGACY_RUNNER_TIERS:
            return LEGACY_RUNNER_TIERS[alias]
        spec = self.settings.runners.get(alias)
        if spec is not None:
            return spec.tier
        return routing.role_tiers.get(str(task.get("agent_role") or ""), "worker")

    def rank(self, task: Mapping[str, Any]) -> int:
        routing = self.settings.routing
        task_type = str(task.get("task_type") or "")
        if task_type in routing.claim_ranks:
            return routing.claim_ranks[task_type]
        if task_class(self.settings, task) == "review":
            return max(routing.claim_ranks.values(), default=routing.default_claim_rank)
        return routing.default_claim_rank

    def constrained(self, launch_limit_value: int) -> bool:
        """Parallelism is limited: reduced ceiling, backoff, or a tight/unknown provider."""

        if launch_limit_value < parallel_ceiling(self.settings) or self.backoffs or self.lead_short:
            return True
        return any(
            self.availability(spec, "ordinary").state != "available"
            for spec in self.settings.runners.values()
        )

    def _task(self, task_id: Any) -> dict[str, Any] | None:
        key = str(task_id or "")
        if not key:
            return None
        if key not in self._task_cache:
            self._task_cache[key] = self.db.task(key)
        return self._task_cache[key]

    def _pinned(self, task: Mapping[str, Any]) -> RunnerSpec | None:
        if task.get("runner_request") is not None:
            return None
        return self.settings.runners.get(normalize_runner(task.get("runner")))

    def _sticky_provider(self, task: Mapping[str, Any]) -> str | None:
        """A resumed session can only continue on the family that created it."""

        if str(task.get("session_mode") or "") != "resume" or not task.get("agent_session_id"):
            return None
        source = self._task(task.get("session_source_task_id"))
        runner = source.get("runner") if source else task.get("runner")
        return provider_of(self.settings, runner)

    def _excluded_provider(self, task: Mapping[str, Any], tier: str, klass: str) -> str | None:
        explicit = str(task.get("exclude_provider") or "").strip()
        if explicit:
            return explicit
        if klass not in {"decision", "review"}:
            return None
        parent = self._task(task.get("parent_task_id"))
        if parent is None:
            return None
        producer = provider_of(self.settings, parent.get("runner"))
        # Independence is only derived when another family can serve this tier.
        providers = {s.provider for s in self.settings.runners.values() if s.tier == tier}
        return producer if providers - {producer} else None

    def _limit_ok(
        self,
        spec: RunnerSpec,
        state: Availability,
        active_by_runner: Mapping[str, int],
    ) -> bool:
        provider_active = sum(
            count
            for name, count in active_by_runner.items()
            if provider_of(self.settings, name) == spec.provider
        )
        if spec.provider in self.probes and provider_active >= self.probes[spec.provider]:
            return False
        if state.state == "unknown":
            if state.unknown_scope == "provider":
                return provider_active < 1
            return int(active_by_runner.get(spec.name, 0)) < 1
        return True

    def _defer(self, task: Mapping[str, Any], reason: str, **detail: Any) -> None:
        self.deferred[str(task["task_id"])] = {"reason": reason, **detail}

    def _choose(
        self,
        candidates: list[RunnerSpec],
        klass: str,
        active_by_runner: Mapping[str, int],
    ) -> tuple[RunnerSpec, Availability] | None:
        usable: list[tuple[RunnerSpec, Availability]] = []
        for spec in candidates:
            if spec.provider in self.backoffs:
                continue
            state = self.availability(spec, klass)
            if not state.usable or not self._limit_ok(spec, state, active_by_runner):
                continue
            usable.append((spec, state))
        if not usable:
            return None
        if klass == "decision":
            # Fable leads decisions while it is above its decision reserve; inside
            # the reserve another family's lead is preferred, and Fable spends its
            # reserve only when no other lead can take the decision.
            def preference(item: tuple[RunnerSpec, Availability]) -> int:
                spec, state = item
                if spec.protected:
                    return 2 if state.in_lead_reserve else 0
                return 1

            usable.sort(
                key=lambda item: (preference(item), -(item[1].headroom or 0.0), item[0].name)
            )
            return usable[0]
        if self.utilization_enabled:
            return self._spread(usable, active_by_runner)
        usable.sort(key=lambda item: (-(item[1].headroom or 0.0), item[0].name))
        return usable[0]

    def _spread(
        self,
        usable: list[tuple[RunnerSpec, Availability]],
        active_by_runner: Mapping[str, int],
    ) -> tuple[RunnerSpec, Availability]:
        """Utilization strategy: share agents between providers by relative abundance.

        Each provider's share of the in-flight agents is proportional to its
        abundance; the task goes to the provider furthest below its share after
        taking it, ties to the more abundant one. With nothing running, the most
        abundant provider wins; as it fills up, the next one gets work too, so a
        provider whose quota resets soon is not starved by a larger one.
        """

        weights: dict[str, float] = {}
        for spec, state in usable:
            weight = max(self._abundance(state), 0.01)
            weights[spec.provider] = max(weights.get(spec.provider, 0.0), weight)
        total = sum(weights.values())
        active: dict[str, int] = {}
        for name, count in active_by_runner.items():
            provider = provider_of(self.settings, name)
            active[provider] = active.get(provider, 0) + int(count)

        def key(item: tuple[RunnerSpec, Availability]) -> tuple[float, float, float, str]:
            spec, state = item
            share = weights[spec.provider] / total
            return (
                (active.get(spec.provider, 0) + 1) / share,
                -self._abundance(state),
                -(state.headroom or 0.0),
                spec.name,
            )

        usable.sort(key=key)
        return usable[0]

    def route(
        self,
        task: Mapping[str, Any],
        active_by_runner: Mapping[str, int],
    ) -> dict[str, Any] | None:
        decision = self._route(task, active_by_runner)
        if decision is not None:
            self.decisions[str(task["task_id"])] = decision
        return decision

    def _route(
        self,
        task: Mapping[str, Any],
        active_by_runner: Mapping[str, int],
    ) -> dict[str, Any] | None:
        klass = task_class(self.settings, task)
        task_type = str(task.get("task_type") or "")
        paused = self.settings.routing.lead_shortage_paused
        # The admission gate runs as a portfolio_review task whose routing reason
        # names the paused decision type.
        if self.lead_short and (
            task_type in paused or str(task.get("routing_reason") or "") in paused
        ):
            self._defer(task, "lead_quota_short")
            return None
        pinned = self._pinned(task)
        if pinned is not None:
            chosen = self._choose([pinned], klass, active_by_runner)
            if chosen is None:
                self._defer(task, "pinned_runner_unavailable", runner=pinned.name)
                return None
            spec, state = chosen
            return self._decision(spec, state, klass, pinned=True)
        tier = self.required_tier(task)
        excluded = self._excluded_provider(task, tier, klass)
        sticky = self._sticky_provider(task)

        def candidates_for(level: str) -> list[RunnerSpec]:
            return [
                spec
                for spec in self.settings.runners.values()
                if spec.tier == level
                and spec.provider != excluded
                and (sticky is None or spec.provider == sticky)
            ]

        # A tier nobody configured falls back light -> worker -> lead.
        configured = {spec.tier for spec in self.settings.runners.values()}
        chain = ("light", "worker", "lead")
        level = next((t for t in chain[chain.index(tier):] if t in configured), tier)
        pool = candidates_for(level)
        if pool:
            chosen = self._choose(pool, klass, active_by_runner)
            if chosen is not None:
                spec, state = chosen
                decision = self._decision(
                    spec, state, klass, requested_tier=tier, excluded=excluded, sticky=sticky
                )
                protected = [item.name for item in pool if item.protected]
                if klass == "decision" and protected and not spec.protected:
                    decision["reassigned_from"] = protected
                    decision["reason"] = "protected lead in or below its decision reserve"
                return decision
            if klass == "review" and level == "lead":
                # The protected lead keeps its reserve: hand the review to the same
                # family's worker tier instead of waiting.
                blocked = [
                    spec for spec in pool
                    if spec.protected and self.availability(spec, klass).reason == "lead_reserve"
                ]
                fallback = [
                    spec
                    for spec in candidates_for("worker")
                    if spec.provider in {item.provider for item in blocked}
                ]
                chosen = self._choose(fallback, klass, active_by_runner)
                if chosen is not None:
                    spec, state = chosen
                    return self._decision(
                        spec, state, klass, requested_tier=tier, excluded=excluded,
                        sticky=sticky, downgraded=True,
                    )
        self._defer(
            task,
            "no_runner_available",
            tier=tier,
            task_class=klass,
            excluded_provider=excluded,
            sticky_provider=sticky,
        )
        return None

    def _decision(
        self,
        spec: RunnerSpec,
        state: Availability,
        klass: str,
        *,
        pinned: bool = False,
        requested_tier: str | None = None,
        excluded: str | None = None,
        sticky: str | None = None,
        downgraded: bool = False,
    ) -> dict[str, Any]:
        decision: dict[str, Any] = {
            "runner": spec.name,
            "provider": spec.provider,
            "tier": spec.tier,
            "model": spec.model,
            "task_class": klass,
            "requested_tier": requested_tier or spec.tier,
            "quota_state": state.state,
            "headroom": None if state.headroom is None else round(state.headroom, 4),
            "pinned": pinned,
        }
        if self.utilization_enabled:
            decision["abundance"] = (
                None if state.abundance is None else round(state.abundance, 4)
            )
        if state.estimated:
            decision["estimated_reading"] = True
        if excluded:
            decision["excluded_provider"] = excluded
        if sticky:
            decision["session_provider"] = sticky
        if downgraded:
            decision["downgraded_for_lead_reserve"] = True
            decision["reason"] = "因负责人额度保留而降级 (lead quota reserved)"
        return decision

    # -- reporting -------------------------------------------------------------

    def provider_summary(self) -> dict[str, dict[str, Any]]:
        """Per provider: newest windows, ordinary-task headroom, pace and reserve state."""

        summary: dict[str, dict[str, Any]] = {}
        providers = sorted({spec.provider for spec in self.settings.runners.values()})
        for provider in providers:
            specs = [s for s in self.settings.runners.values() if s.provider == provider]
            shared = next((s for s in specs if not s.protected and not s.windows), None)
            probe = shared or RunnerSpec(name=f"{provider}:shared", provider=provider,
                                         tier="worker")
            state = runner_availability(
                probe, self.settings.runners, self.readings.get(provider, {}),
                self.settings.routing, klass="ordinary", now=self.now,
            )
            readings = self.readings.get(provider, {})
            summary[provider] = {
                "state": state.state,
                "headroom": None if state.headroom is None else round(state.headroom, 4),
                "abundance": None if state.abundance is None else round(state.abundance, 4),
                "estimated": state.estimated,
                "overspeed": state.overspeed,
                "below_reserve": state.below_reserve,
                "binding_window": state.binding_window,
                "backoff_until": self.backoffs.get(provider),
                "windows": {name: item.to_dict() for name, item in sorted(readings.items())},
                "window_pace": {
                    str(item["name"]): {
                        key: item.get(key)
                        for key in ("ceiling", "abundance", "projected_at_reset", "overspeed")
                    }
                    for item in state.windows
                } if self.utilization_enabled else {},
                "runners": {
                    spec.name: {
                        klass: self.availability(spec, klass).state for klass in TASK_CLASSES
                    }
                    for spec in specs
                },
            }
        return summary

    def lead_summary(self) -> dict[str, Any]:
        leads = [spec for spec in self.settings.runners.values() if spec.tier == "lead"]
        return {
            "short": self.lead_short,
            "paused_task_types": (
                list(self.settings.routing.lead_shortage_paused) if self.lead_short else []
            ),
            "runners": {
                spec.name: {
                    "protected": spec.protected,
                    "decision": self.usable(spec, "decision"),
                    "review": self.usable(spec, "review"),
                }
                for spec in leads
            },
        }


def record_lead_shortage(db: FactoryDB, router: QuotaRouter) -> str | None:
    """Write ``lead_quota_short`` / ``lead_quota_restored`` on a state change."""

    was_short = db.meta_get(LEAD_SHORTAGE_KEY) is not None
    if router.lead_short == was_short:
        return None
    event = "lead_quota_short" if router.lead_short else "lead_quota_restored"
    db.update_meta(
        {LEAD_SHORTAGE_KEY: _iso(router.now) if router.lead_short else None},
        events=[("scheduler", "lead_quota", event, router.lead_summary())],
    )
    return event


# ------------------------------------------------------------ unified-review readings

# ``paper_writing.review_launcher`` runs Claude reviewers with stream-json and
# writes each role's last ``rate_limit_event`` as ``<run>/<role>/quota.json``.
REVIEW_QUOTA_FILE = "quota.json"
REVIEW_QUOTA_SCHEMA = "openlabs.quota_snapshot.v1"


def ingest_review_quota(
    db: FactoryDB,
    settings: FactorySettings,
    data_root: Path,
    decision_record: Any,
    *,
    task_id: str | None = None,
) -> list[str]:
    """Merge the quota readings of one unified-review run into the quota snapshot.

    ``decision_record`` is the data-repository path the review result reports
    (``review_outcome.decision_record``); the role directories next to it hold
    the readings. A reviewer on the protected lead model (Fable) otherwise never
    reports its own windows, because review processes are not agent tasks.
    Returns the providers written; anything unreadable is skipped.
    """

    relative = str(decision_record or "").strip()
    if not relative:
        return []
    root = Path(data_root).resolve()
    run_dir = (root / relative).resolve().parent
    reviews = (root / "reviews").resolve()
    if not run_dir.is_relative_to(reviews) or not run_dir.is_dir():
        return []
    written: list[str] = []
    for path in sorted(run_dir.glob(f"*/{REVIEW_QUOTA_FILE}")):
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(snapshot, Mapping) or snapshot.get("schema_version") != REVIEW_QUOTA_SCHEMA:
            continue
        provider = record_quota_snapshot(db, settings, snapshot, task_id=task_id)
        if provider:
            written.append(provider)
    return written


# ------------------------------------------------------------ active probing


@lru_cache(maxsize=1)
def _lab_runner_module() -> ModuleType:
    """The quota parsers live in the standalone lab runner (stdlib only)."""

    path = Path(__file__).resolve().parents[3] / "packages" / "research-core" / "lab_runner.py"
    spec = importlib.util.spec_from_file_location("openlabs_lab_runner_quota", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load lab runner quota parsers from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def probe_quota(
    settings: FactorySettings,
    provider: str,
    *,
    run: Callable[..., Any] = subprocess.run,
    timeout_seconds: float = 120.0,
) -> dict[str, Any] | None:
    """Actively read one provider's quota; None when nothing could be read.

    Claude: run the configured cheap-model probe command (never Fable) and parse
    its stream-json ``rate_limit_event``. Codex: read the newest session file
    under ``routing.codex_sessions_dir``; no model is called.
    """

    parsers = _lab_runner_module()
    command = settings.routing.probe_commands.get(provider)
    if command:
        try:
            completed = run(
                list(command),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        adapter = Path(command[0]).name
        return parsers.extract_quota_snapshot(str(completed.stdout or ""), adapter=adapter)
    if provider == "openai-codex" and settings.routing.codex_sessions_dir:
        root = Path(settings.routing.codex_sessions_dir).expanduser()
        if not root.is_dir():
            return None
        days = sorted(
            (path for path in root.glob("[0-9]*/[0-9]*/[0-9]*") if path.is_dir()),
            reverse=True,
        )[:3]
        for day in days:
            files = sorted(day.glob("rollout-*.jsonl"), key=lambda item: item.stat().st_mtime)
            for path in reversed(files[-5:]):
                snapshot = parsers.codex_session_quota(path)
                if snapshot is not None:
                    return snapshot
    return None


def probe_stale_providers(
    db: FactoryDB,
    settings: FactorySettings,
    *,
    now: datetime | None = None,
    run: Callable[..., Any] = subprocess.run,
) -> dict[str, str]:
    """Probe providers whose readings went stale, at most once per ``probe_idle_minutes``.

    Meant for resuming after a long idle period; a tick calls it, but the
    per-provider rate limit means it does not probe on every tick. The free
    Codex refresh (newest session file) uses ``stale_refresh_minutes`` instead
    when that is set.
    """

    if not routing_enabled(settings):
        return {}
    moment = _now(now)
    routing = settings.routing
    readings = quota_readings(db)
    outcome: dict[str, str] = {}
    for provider in sorted({spec.provider for spec in settings.runners.values()}):
        if provider not in routing.probe_commands and not (
            provider == "openai-codex" and routing.codex_sessions_dir
        ):
            continue
        fresh = any(
            reading_is_fresh(item, now=moment, stale_hours=routing.snapshot_stale_hours)
            for item in readings.get(provider, {}).values()
        )
        if fresh:
            continue
        last = parse_time(db.meta_get(QUOTA_PROBE_AT_PREFIX + provider))
        interval = routing.probe_idle_minutes
        if provider not in routing.probe_commands and routing.stale_refresh_minutes:
            # Reading the newest Codex session file costs nothing: refresh often.
            interval = routing.stale_refresh_minutes
        if last is not None and moment - last < timedelta(minutes=interval):
            continue
        db.update_meta({QUOTA_PROBE_AT_PREFIX + provider: _iso(moment)})
        snapshot = probe_quota(settings, provider, run=run)
        if snapshot is not None:
            snapshot = {**snapshot, "provider": provider}
            record_quota_snapshot(db, settings, snapshot, now=moment)
        outcome[provider] = "recorded" if snapshot is not None else "no_reading"
        db.update_meta(
            {},
            events=[("provider", provider, "quota_probe", {"outcome": outcome[provider]})],
        )
    return outcome


# --------------------------------------------------------------- comparisons


def execution_record(
    settings: FactorySettings,
    task: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> dict[str, Any]:
    """Provider/tier/model of one attempt, stored in its runtime for later comparison."""

    runner = normalize_runner(runtime.get("runner") or task.get("runner"))
    spec = settings.runners.get(runner)
    snapshot = runtime.get("quota_snapshot")
    family = ADAPTER_PROVIDERS.get(str(runtime.get("adapter") or ""))
    provider = (
        spec.provider
        if spec
        else (snapshot.get("provider") if isinstance(snapshot, Mapping) else None)
        or runtime.get("provider_family")
        or family
        or runner
    )
    return {
        "runner": runner,
        "provider": provider,
        "tier": spec.tier if spec else tier_of(settings, runner),
        "model": runtime.get("model") or runtime.get("configured_model")
        or (spec.model if spec else None),
    }


def execution_summary(
    db: FactoryDB,
    settings: FactorySettings,
    *,
    since: str | None = None,
) -> list[dict[str, Any]]:
    """Finished attempts grouped by (provider, tier) for model-family comparison.

    Each row: attempts, tasks, succeeded, success_rate, input/cached/output/
    reasoning tokens, run_seconds (total and mean). Quota-deferred attempts are
    counted separately as ``quota_deferred``.
    """

    with db.connect() as connection:
        rows = connection.execute(
            """
            SELECT task_attempts.task_id, task_attempts.status, task_attempts.run_seconds,
                   task_attempts.runtime_json, task_attempts.finished_at,
                   tasks.runner AS task_runner
            FROM task_attempts JOIN tasks USING(task_id)
            WHERE task_attempts.finished_at IS NOT NULL
              AND (? IS NULL OR task_attempts.finished_at >= ?)
            """,
            (since, since),
        ).fetchall()
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    token_keys = (
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    )
    for row in rows:
        try:
            runtime = json.loads(str(row["runtime_json"] or "{}"))
        except json.JSONDecodeError:
            runtime = {}
        if not isinstance(runtime, dict):
            runtime = {}
        record = runtime.get("execution")
        if not isinstance(record, Mapping):
            record = execution_record(settings, {"runner": row["task_runner"]}, runtime)
        key = (str(record.get("provider") or "unknown"), str(record.get("tier") or "unknown"))
        group = groups.setdefault(
            key,
            {
                "provider": key[0],
                "tier": key[1],
                "attempts": 0,
                "tasks": set(),
                "succeeded": 0,
                "quota_deferred": 0,
                "run_seconds": 0.0,
                "models": set(),
                **{name: 0 for name in token_keys},
            },
        )
        status = str(row["status"])
        if status == "quota_deferred":
            group["quota_deferred"] += 1
            continue
        group["attempts"] += 1
        group["tasks"].add(str(row["task_id"]))
        group["succeeded"] += int(status == "succeeded")
        group["run_seconds"] += float(row["run_seconds"] or 0.0)
        if record.get("model"):
            group["models"].add(str(record["model"]))
        for name in token_keys:
            value = runtime.get(name)
            if isinstance(value, int) and not isinstance(value, bool):
                group[name] += value
    summary: list[dict[str, Any]] = []
    for key in sorted(groups):
        group = groups[key]
        attempts = int(group["attempts"])
        summary.append(
            {
                **{k: v for k, v in group.items() if k not in {"tasks", "models"}},
                "tasks": len(group["tasks"]),
                "models": sorted(group["models"]),
                "success_rate": (group["succeeded"] / attempts) if attempts else None,
                "mean_run_seconds": (group["run_seconds"] / attempts) if attempts else None,
            }
        )
    return summary


def budget_status(
    db: FactoryDB,
    settings: FactorySettings,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    return {
        "effective_parallel": effective_parallel(db, settings),
        "parallel_ceiling": parallel_ceiling(settings),
        "provider_backoff_until": runner_backoffs(db, now=now, settings=settings),
        "probing_runners": sorted(probe_limits(db, now=now, settings=settings)),
    }
