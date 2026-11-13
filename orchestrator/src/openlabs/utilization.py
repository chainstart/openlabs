"""Throughput supervision: measured host load, ailab load, the adaptive launch ceiling.

Everything here observes; the only state it writes is two ``meta`` entries of
the tick itself (the previous CPU sample and the adaptive ceiling with a short
history). ``utilization_report`` is the read-only view behind
``python -m openlabs program utilization``.

The adaptive ceiling is deliberately gentle: it moves by at most
``[budget].adaptive_step`` per tick, it never exceeds the static ceiling
(``max_parallel_agents``/``max_worker_processes``, already halved after a quota
hit), and it grows only while there are runnable tasks, the measured container
load is below ``host_utilization_target`` and some provider would end its
window below the target at its current pace. Agents mostly wait for model
responses, so CPU load says little about how many agents fit; quota pace and
the static ceiling are what bound the agent count.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from . import budget as budget_control
from .config import FactorySettings, RunnerSpec, WorkspacePaths
from .db import FactoryDB

CGROUP_ROOT = Path("/sys/fs/cgroup")
HOST_SAMPLE_KEY = "host_cpu_sample"
ADAPTIVE_KEY = "adaptive_parallel"
ADAPTIVE_HISTORY_KEY = "adaptive_parallel_history"
ADAPTIVE_HISTORY_LENGTH = 20
# A provider projected to end its window this far below its ceiling is
# under-used; above the ceiling (or overspeed) it is over-paced.
PACE_MARGIN = 0.05
UTILIZATION_SCHEMA = "openlabs.utilization.v1"


# ------------------------------------------------------------------ host load


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def cgroup_reading(root: Path = CGROUP_ROOT) -> dict[str, Any]:
    """Raw cgroup v2 counters of this container (missing files are left out)."""

    reading: dict[str, Any] = {}
    cpu_max = _read(root / "cpu.max")
    if cpu_max:
        quota, _, period = cpu_max.partition(" ")
        try:
            if quota != "max":
                reading["cpu_limit"] = int(quota) / int(period or 100000)
        except ValueError:
            pass
    reading.setdefault("cpu_limit", float(os.cpu_count() or 1))
    for line in (_read(root / "cpu.stat") or "").splitlines():
        name, _, value = line.partition(" ")
        if name == "usage_usec" and value.isdigit():
            reading["usage_usec"] = int(value)
    current = _read(root / "memory.current")
    limit = _read(root / "memory.max")
    if current and current.isdigit():
        reading["memory_current"] = int(current)
    if limit and limit.isdigit():
        reading["memory_max"] = int(limit)
    for line in (_read(root / "memory.stat") or "").splitlines():
        name, _, value = line.partition(" ")
        if name == "file" and value.isdigit():
            reading["memory_file"] = int(value)
    return reading


def host_usage(
    db: FactoryDB | None,
    *,
    now: datetime,
    record: bool,
    root: Path = CGROUP_ROOT,
) -> dict[str, Any]:
    """Measured container load: CPU since the previous tick's sample, memory now.

    Memory excludes the page cache (reclaimable), so a large file cache does
    not read as pressure. ``record`` stores the CPU sample for the next tick.
    """

    reading = cgroup_reading(root)
    usage: dict[str, Any] = {"cpu_limit": round(float(reading["cpu_limit"]), 2)}
    if db is not None and "usage_usec" in reading:
        previous = None
        raw = db.meta_get(HOST_SAMPLE_KEY)
        if raw:
            try:
                previous = json.loads(raw)
            except json.JSONDecodeError:
                previous = None
        if isinstance(previous, Mapping):
            at = budget_control.parse_time(previous.get("at"))
            before = previous.get("usage_usec")
            if at is not None and isinstance(before, int):
                seconds = (now - at).total_seconds()
                if seconds > 0 and reading["usage_usec"] >= before:
                    busy = (reading["usage_usec"] - before) / 1e6
                    usage["cpu_fraction"] = round(busy / (seconds * reading["cpu_limit"]), 4)
                    usage["cpu_sample_seconds"] = round(seconds, 1)
        if record:
            db.update_meta(
                {HOST_SAMPLE_KEY: json.dumps(
                    {"at": budget_control._iso(now), "usage_usec": reading["usage_usec"]}
                )}
            )
    if "memory_current" in reading and "memory_max" in reading and reading["memory_max"] > 0:
        used = reading["memory_current"] - int(reading.get("memory_file", 0))
        usage["memory_used_mib"] = max(0, used) // (1024 * 1024)
        usage["memory_limit_mib"] = reading["memory_max"] // (1024 * 1024)
        usage["memory_fraction"] = round(max(0, used) / reading["memory_max"], 4)
    return usage


def gpu_usage() -> list[dict[str, Any]] | None:
    """Per-GPU memory and utilization from ``nvidia-smi``; None when unavailable."""

    try:
        from . import gpu_guard

        rows = gpu_guard.snapshot()
    except Exception:  # noqa: BLE001 - the GPU view is advisory.
        return None
    result = []
    for row in rows:
        payload = {key: value for key, value in vars(row).items() if not key.startswith("_")}
        result.append(payload)
    return result


# ---------------------------------------------------------------------- ailab


def ailab_summary(paths: WorkspacePaths) -> dict[str, Any] | None:
    """Read-only ailab queue load (None when remote compute is off or unreadable)."""

    try:
        config_path = Path(paths.code) / "config" / "remote-compute.json"
        if not config_path.is_file():
            return None
        capabilities = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(capabilities, Mapping) or not capabilities.get("enabled"):
            return None
        runner = budget_control._lab_runner_module()
        return runner.remote_queue_summary(runner.remote_queue_root(), capabilities)
    except Exception:  # noqa: BLE001 - the summary is advisory; omit it.
        return None


# ----------------------------------------------------------------- task counts


def runnable_count(db: FactoryDB, *, now: datetime) -> int:
    """Queued tasks whose ``not_before`` has passed in active campaigns."""

    with db.connect() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS n FROM tasks JOIN campaigns USING(campaign_id)
            WHERE tasks.status='queued' AND campaigns.status='active'
              AND (tasks.not_before IS NULL OR tasks.not_before <= ?)
            """,
            (budget_control._iso(now),),
        ).fetchone()
    return int(row["n"])


def task_distribution(db: FactoryDB, settings: FactorySettings) -> dict[str, Any]:
    """Running and queued tasks by tier and provider (and by task type)."""

    with db.connect() as connection:
        rows = connection.execute(
            "SELECT task_type, runner, runner_request, status FROM tasks "
            "WHERE status IN ('queued', 'leased', 'running')"
        ).fetchall()
    result: dict[str, Any] = {"running": {}, "queued": {}}
    for row in rows:
        bucket = "queued" if row["status"] == "queued" else "running"
        runner = str(row["runner"] or "")
        if bucket == "running" or runner in settings.runners:
            provider = budget_control.provider_of(settings, runner)
            tier = budget_control.tier_of(settings, runner) or "unknown"
        else:  # not routed yet: only the requested tier is known
            provider = "unrouted"
            tier = budget_control.tier_of(settings, row["runner_request"] or runner) or "unknown"
        key = f"{tier}/{provider}"
        group = result[bucket].setdefault(key, {"count": 0, "task_types": {}})
        group["count"] += 1
        task_type = str(row["task_type"] or "")
        group["task_types"][task_type] = group["task_types"].get(task_type, 0) + 1
    result["running_total"] = sum(item["count"] for item in result["running"].values())
    result["queued_total"] = sum(item["count"] for item in result["queued"].values())
    return result


# ------------------------------------------------------------------ quota pace


def _shared_spec(settings: FactorySettings, provider: str) -> RunnerSpec:
    specs = [s for s in settings.runners.values() if s.provider == provider]
    shared = next((s for s in specs if not s.protected and not s.windows), None)
    return shared or RunnerSpec(name=f"{provider}:shared", provider=provider, tier="worker")


def provider_pace(router: budget_control.QuotaRouter) -> dict[str, dict[str, Any]]:
    """Per provider: is ordinary work under, on or over the pace that meets its ceiling?

    ``under`` -- at the window's average pace every constraining window ends
    more than ``PACE_MARGIN`` below its ceiling (quota would be left over);
    ``over`` -- some window would pass its ceiling or is overspeed; ``on_pace``
    otherwise. ``unknown`` without a usable reading, ``unavailable`` in backoff
    or below its reserve.
    """

    result: dict[str, dict[str, Any]] = {}
    for provider in sorted({spec.provider for spec in router.settings.runners.values()}):
        spec = _shared_spec(router.settings, provider)
        state = budget_control.runner_availability(
            spec, router.settings.runners, router.readings.get(provider, {}),
            router.settings.routing, klass="ordinary", now=router.now,
        )
        gaps = [
            float(item["ceiling"]) - float(item["projected_at_reset"])
            for item in state.windows
            if item.get("projected_at_reset") is not None
        ]
        if provider in router.backoffs:
            signal = "unavailable"
            reason = "backoff"
        elif not state.usable:
            signal = "unavailable" if state.reason != "overspeed" else "over"
            reason = state.reason
        elif state.state == "unknown" or not gaps:
            signal = "unknown"
            reason = state.reason or "no_projection"
        elif state.overspeed or min(gaps) < 0:
            signal = "over"
            reason = "projected_above_ceiling"
        elif min(gaps) > PACE_MARGIN:
            signal = "under"
            reason = "projected_below_ceiling"
        else:
            signal = "on_pace"
            reason = "projected_near_ceiling"
        result[provider] = {
            "signal": signal,
            "reason": reason,
            "abundance": None if state.abundance is None else round(state.abundance, 4),
            "headroom": None if state.headroom is None else round(state.headroom, 4),
            "estimated": state.estimated,
            "binding_window": state.binding_window,
            "windows": {
                str(item["name"]): {
                    "used_fraction": item.get("used_fraction"),
                    "ceiling": item.get("ceiling"),
                    "abundance": item.get("abundance"),
                    "projected_at_reset": item.get("projected_at_reset"),
                    "resets_at": item.get("resets_at"),
                    "estimated": "estimated_from" in item,
                }
                for item in state.windows
            },
            "unknown_windows": list(state.unknown_windows),
            # Readings too old to use (and not extrapolated), for reference.
            "stale_readings": {
                name: router.readings[provider][name].to_dict()
                for name in state.unknown_windows
                if name in router.readings.get(provider, {})
            },
        }
    return result


# ------------------------------------------------------------- adaptive limit


def _history(db: FactoryDB) -> list[dict[str, Any]]:
    raw = db.meta_get(ADAPTIVE_HISTORY_KEY)
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def adaptive_launch_limit(
    db: FactoryDB,
    settings: FactorySettings,
    router: budget_control.QuotaRouter | None,
    *,
    hard: int,
    active: int,
    runnable: int,
    host: Mapping[str, Any],
    now: datetime,
    record: bool = True,
) -> dict[str, Any]:
    """This tick's launch ceiling and why.

    Without ``[budget].adaptive_parallel`` the static ceiling ``hard`` applies
    unchanged. With it, the ceiling starts at the agents already running and
    moves by at most ``adaptive_step`` per tick:

    * down by one while the measured container CPU or memory is at or above
      ``host_utilization_target`` or every usable provider is over-paced;
    * up while there are runnable tasks, some provider is under-paced and the
      container is clearly below its target (held within 10 points of it);
    * never above ``hard`` and never above what running plus runnable tasks need.
    """

    budget = settings.budget
    entry: dict[str, Any] = {
        "at": budget_control._iso(now),
        "hard_ceiling": hard,
        "static_ceiling": budget_control.parallel_ceiling(settings),
        "active": active,
        "runnable": runnable,
        "adaptive": budget.adaptive_parallel,
    }
    if not budget.adaptive_parallel:
        entry.update({"limit": hard, "previous": hard, "reasons": ["static_ceiling"],
                      "limited_by": "hard_ceiling"})
        return entry
    raw = db.meta_get(ADAPTIVE_KEY)
    try:
        previous = int(raw) if raw is not None else max(1, active)
    except ValueError:
        previous = max(1, active)
    previous = max(1, min(previous, hard))
    step = max(1, budget.adaptive_step)
    target = budget.host_utilization_target
    pace = provider_pace(router) if router is not None else {}
    signals = {provider: item["signal"] for provider, item in pace.items()}
    usable = {p: s for p, s in signals.items() if s != "unavailable"}
    reasons: list[str] = []
    cpu = host.get("cpu_fraction")
    memory = host.get("memory_fraction")
    loads = [value for value in (cpu, memory) if isinstance(value, (int, float))]
    host_high = any(value >= target for value in loads)
    host_near = any(value >= target - 0.1 for value in loads)
    if router is None:
        quota = "none"  # no routing: quota does not limit growth
    elif not usable:
        quota = "exhausted"
    elif any(signal == "under" for signal in usable.values()):
        quota = "under"
    elif all(signal == "over" for signal in usable.values()):
        quota = "over"
    else:
        quota = "hold"
    limit = previous
    limited_by = "steady"
    if host_high:
        limit = previous - 1
        reasons.append("host_load_at_or_above_target")
        limited_by = "host_resources"
    elif quota in {"over", "exhausted"}:
        limit = previous - 1
        reasons.append("quota_over_pace" if quota == "over" else "no_provider_usable")
        limited_by = "quota_pacing"
    elif runnable <= 0:
        reasons.append("no_runnable_tasks")
        limited_by = "demand"
    elif quota == "hold":
        reasons.append("quota_on_pace_or_unknown")
        limited_by = "quota_pacing"
    elif host_near:
        reasons.append("host_load_near_target")
        limited_by = "host_resources"
    else:
        wanted = active + runnable
        if wanted <= previous:
            reasons.append("enough_room_for_runnable_tasks")
            limited_by = "demand"
        else:
            limit = min(previous + step, wanted)
            reasons.append("quota_under_pace_and_host_has_room")
            limited_by = "ramp" if limit < min(wanted, hard) else "demand"
            if limit >= hard and wanted > hard:
                limited_by = "hard_ceiling"
    limit = max(1, min(limit, hard))
    if limit == hard and limited_by in {"ramp", "steady"}:
        limited_by = "hard_ceiling"
    entry.update(
        {
            "limit": limit,
            "previous": previous,
            "reasons": reasons,
            "limited_by": limited_by,
            "quota_signal": signals,
            "host": {key: host.get(key) for key in ("cpu_fraction", "memory_fraction")},
        }
    )
    if record:
        history = (_history(db) + [
            {key: entry[key] for key in ("at", "limit", "previous", "hard_ceiling", "active",
                                         "runnable", "limited_by", "reasons")}
        ])[-ADAPTIVE_HISTORY_LENGTH:]
        db.update_meta(
            {ADAPTIVE_KEY: str(limit), ADAPTIVE_HISTORY_KEY: json.dumps(history)},
            events=(
                [("scheduler", ADAPTIVE_KEY, "adaptive_parallel_changed",
                  {"from": previous, "to": limit, "reasons": reasons})]
                if limit != previous else []
            ),
        )
    return entry


# ------------------------------------------------------------------- balance


def _admission_pass_rate(db: FactoryDB) -> dict[str, Any]:
    with db.connect() as connection:
        rows = connection.execute(
            "SELECT event_type, COUNT(DISTINCT entity_id) AS n FROM events "
            "WHERE entity_type='topic' AND event_type IN ('topic_admitted', 'topic_rejected') "
            "GROUP BY event_type"
        ).fetchall()
    counts = {str(row["event_type"]): int(row["n"]) for row in rows}
    admitted = counts.get("topic_admitted", 0)
    decided = admitted + counts.get("topic_rejected", 0)
    return {"admitted": admitted, "decided": decided,
            "rate": round(admitted / decided, 4) if decided else None}


def balance_summary(
    settings: FactorySettings,
    *,
    parallel: Mapping[str, Any],
    pace: Mapping[str, Mapping[str, Any]],
    host: Mapping[str, Any],
    ailab: Mapping[str, Any] | None,
    program: Mapping[str, Any],
    admission: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """One row per supervised quantity: current, target, below target, what limits it."""

    rows: list[dict[str, Any]] = []
    target = settings.routing.utilization_target

    def work_limiter() -> str:
        """Why there is not more agent work: the first binding constraint."""

        if int(parallel.get("runnable") or 0) > 0:
            return str(parallel.get("limited_by") or "hard_ceiling")
        if program:
            if int(program.get("free_slots") or 0) <= 0:
                return "topic_slots"
            blocked = program.get("scout_blocked")
            if blocked in {"candidate_pool_at_low_water", "candidate_pool_covered_by_scouts"}:
                rate = (admission or {}).get("rate")
                if rate is not None and rate < 0.25:
                    return "admission_pass_rate"
                return "candidate_pool"
            if blocked:
                return f"scouts:{blocked}"
        return "no_runnable_tasks"

    for provider, item in sorted(pace.items()):
        windows = item.get("windows") or {}
        projected = [w.get("projected_at_reset") for w in windows.values()
                     if w.get("projected_at_reset") is not None]
        ceilings = [w.get("ceiling") for w in windows.values() if w.get("ceiling") is not None]
        goal = target if target > 0 else (min(ceilings) if ceilings else None)
        current = max(projected) if projected else None
        below = item.get("signal") == "under"
        rows.append(
            {
                "item": f"quota:{provider}",
                "current": current,
                "measure": "projected used fraction at reset (binding window)",
                "target": goal,
                "below_target": below,
                "limited_by": work_limiter() if below else item.get("reason"),
            }
        )
    host_target = settings.budget.host_utilization_target
    for key in ("cpu_fraction", "memory_fraction"):
        value = host.get(key)
        below = isinstance(value, (int, float)) and value < host_target
        rows.append(
            {
                "item": f"host:{key.split('_')[0]}",
                "current": value,
                "target": host_target,
                "below_target": below,
                # Agents mostly wait on model responses: low CPU alone is no
                # reason for more agents; the agent count is bound elsewhere.
                "limited_by": (
                    "not_measured_yet" if value is None
                    else work_limiter() if below else "at_target"
                ),
            }
        )
    if ailab:
        ailab_target = settings.budget.ailab_utilization_target
        value = max(ailab.get("cpu_fraction") or 0.0, ailab.get("memory_fraction") or 0.0)
        rows.append(
            {
                "item": "ailab",
                "current": round(value, 4),
                "target": ailab_target,
                "below_target": value < ailab_target,
                "limited_by": "agents_submit_remote_jobs" if value < ailab_target else "at_target",
            }
        )
    rows.append(
        {
            "item": "agents",
            "current": parallel.get("active"),
            "target": parallel.get("hard_ceiling"),
            "below_target": int(parallel.get("active") or 0) < int(
                parallel.get("hard_ceiling") or 0
            ),
            "limited_by": work_limiter(),
        }
    )
    return rows


# -------------------------------------------------------------------- report


class ReadOnlyFactoryDB(FactoryDB):
    """Opens the database read-only (``mode=ro``); any write raises."""

    def connect(self):  # type: ignore[override]
        import sqlite3
        from contextlib import contextmanager

        @contextmanager
        def _connection():
            connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=30)
            connection.row_factory = sqlite3.Row
            try:
                yield connection
            finally:
                connection.close()

        return _connection()


def utilization_report(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    now: datetime | None = None,
    history: int = 10,
    cgroup_root: Path = CGROUP_ROOT,
    include_gpu: bool = True,
) -> dict[str, Any]:
    """Read-only utilization snapshot for operators (``program utilization``)."""

    moment = budget_control._now(now)
    router = (
        budget_control.QuotaRouter.build(db, settings, now=moment)
        if budget_control.routing_enabled(settings) else None
    )
    pace = provider_pace(router) if router is not None else {}
    host = host_usage(db, now=moment, record=False, root=cgroup_root)
    ailab = ailab_summary(paths)
    active = db.active_count()
    runnable = runnable_count(db, now=moment)
    hard = budget_control.launch_limit(db, settings)
    raw = db.meta_get(ADAPTIVE_KEY)
    current_limit = hard
    if settings.budget.adaptive_parallel and raw is not None:
        try:
            current_limit = max(1, min(int(raw), hard))
        except ValueError:
            current_limit = hard
    recent = _history(db)[-max(0, history):] if history else []
    parallel = {
        "limit": current_limit,
        "hard_ceiling": hard,
        "static_ceiling": budget_control.parallel_ceiling(settings),
        "adaptive": settings.budget.adaptive_parallel,
        "active": active,
        "runnable": runnable,
        "limited_by": recent[-1]["limited_by"] if recent else (
            "hard_ceiling" if not settings.budget.adaptive_parallel else "unknown"
        ),
        "recent": recent,
    }
    program: dict[str, Any] = {}
    if settings.program.enabled:
        try:
            from .program import open_topic_ledger, parked_program_projects, slot_status

            document = open_topic_ledger(paths, settings.program).read()
            program = slot_status(
                document, settings.program, parked_program_projects(paths)).to_dict()
        except Exception:  # noqa: BLE001 - the ledger view is advisory.
            program = {}
    admission = _admission_pass_rate(db)
    quota_rows: dict[str, Any] = {}
    for provider, item in pace.items():
        rows = {}
        for name, window in item["windows"].items():
            rows[name] = {
                **window,
                "projected_at_reset_vs_target": (
                    None if window.get("projected_at_reset") is None
                    else f"{window['projected_at_reset']:.2f} / "
                    f"{(settings.routing.utilization_target or window.get('ceiling') or 0):.2f}"
                ),
            }
        quota_rows[provider] = {**item, "windows": rows}
    host_target = settings.budget.host_utilization_target
    ailab_target = settings.budget.ailab_utilization_target
    payload = {
        "schema_version": UTILIZATION_SCHEMA,
        "at": budget_control._iso(moment),
        "tasks": task_distribution(db, settings),
        "providers": quota_rows,
        "utilization_target": settings.routing.utilization_target,
        "host": {
            **host,
            "target": host_target,
            "cpu_vs_target": (
                None if host.get("cpu_fraction") is None
                else f"{host['cpu_fraction']:.2f} / {host_target:.2f}"
            ),
            "memory_vs_target": (
                None if host.get("memory_fraction") is None
                else f"{host['memory_fraction']:.2f} / {host_target:.2f}"
            ),
            "gpu": gpu_usage() if include_gpu else None,
        },
        "ailab": (
            None if ailab is None else {
                **ailab,
                "target": ailab_target,
                "vs_target": (
                    f"{max(ailab.get('cpu_fraction') or 0, ailab.get('memory_fraction') or 0):.2f}"
                    f" / {ailab_target:.2f}"
                ),
            }
        ),
        "parallel": parallel,
        "admission": admission,
        "program": program,
    }
    payload["balance"] = balance_summary(
        settings, parallel=parallel, pace=pace, host=host, ailab=ailab, program=program,
        admission=admission,
    )
    return payload
