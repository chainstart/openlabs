"""Per-attempt token accounting, equivalent cost and per-topic economics (2026-11-16).

Recording. The lab runner copies the CLI's own usage numbers into an attempt's
runtime. For a resumed session some of them are session totals, not this attempt's
use (measured in the 2026-11-16 cost review, maintenance/20261116-cost-review):

* Codex ``turn.completed`` usage (input, cached input, output, reasoning tokens) is the
  thread's running total: summing it over resumed attempts overstated Codex use 4.6x;
* Claude ``result.total_cost_usd`` is the session's running cost (about 3x on resumed
  attempts); its token usage is per invocation.

:func:`to_increment` turns those counters into this attempt's increment at ingestion:
the attempt's raw values stay under ``usage_cumulative``, the session total before it
under ``usage_session_base`` and the top-level keys become the difference
(``usage_basis = attempt_increment``). Everything that sums the top-level keys
(execution summary, asset reuse comparison, the reports below) then sums real use.
History is never rewritten; the readers here apply the same correction on the fly
to older rows (:func:`normalized_attempts`).

Corrections of 2026-11-20 (W3, maintenance/20261120-pipeline-overhaul/W3-notes.md):

* a Claude process that went on after a blocked Stop hook emitted several ``result``
  events, each with only its own stretch's usage, and the lab runner kept the last one
  (a 95-minute review recorded 154 output tokens). New attempts sum them
  (``result_segments``); for older ones the token counts are lost, so their equivalent
  cost is the CLI's own process cost (``cost_usd`` increment) whenever that is higher than
  the token-priced figure (``cost_from_cli_attempts`` counts them);
* the unified review's reviewer processes (``paper_writing.review_launcher``) are not
  agent attempts; their use is read from the review run's role directories
  (:func:`external_review_usage`) and added to the ``paper_review`` rows and totals here.

Equivalent cost uses ``[reporting.prices]`` (USD per million tokens, the cost review's
list prices by default). It is a list-price equivalent, not a bill: subscriptions are
paid by quota. The runtime has one model per attempt, so all of an attempt's tokens are
priced at that model: a gpt-6-astra seat that hands most work to gpt-6.1-sol sub-agents
is overstated (V0651 Hya: about 108 USD here, 37 USD measured per request). The
long-context surcharge per request is not applied.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import OWNER_TASK_TYPE, FactorySettings, ModelPrice, WorkspacePaths
from .db import FactoryDB

INCREMENT_BASIS = "attempt_increment"
TOKEN_KEYS = (
    "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
    "cache_write_1h_input_tokens", "output_tokens", "reasoning_output_tokens",
)
# Counters a resumed session reports as session totals, per adapter.
CUMULATIVE_KEYS: dict[str, tuple[str, ...]] = {
    "codex": ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"),
    "claude": ("cost_usd",),
}
# Adapters whose input_tokens already include the cached part (OpenAI convention).
INPUT_INCLUDES_CACHED = frozenset({"codex"})
READY_STATUSES = frozenset({"ready_queue", "submitted"})
LIVE_TASK_STATUSES = ("queued", "leased", "running", "awaiting_remote")


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _same(value: float, template: Any) -> float | int:
    return int(value) if isinstance(template, int) else round(float(value), 6)


def _cumulative(runtime: Mapping[str, Any]) -> dict[str, float]:
    """Raw (session-total) counters of one recorded attempt, either basis."""

    adapter = str(runtime.get("adapter") or "")
    keys = CUMULATIVE_KEYS.get(adapter, ())
    if runtime.get("usage_basis") == INCREMENT_BASIS:
        source = runtime.get("usage_cumulative")
        source = source if isinstance(source, Mapping) else {}
    else:
        source = runtime
    return {key: value for key in keys if (value := _number(source.get(key))) is not None}


def to_increment(
    runtime: Mapping[str, Any], prior: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """``runtime`` with session-total counters replaced by this attempt's increment.

    ``prior`` are earlier attempts' runtimes (any session; others are ignored). A value
    below the session's earlier total means the counter restarted (a new process) and
    is kept as it is. A runtime that is already an increment is returned unchanged.
    """

    result = dict(runtime)
    if runtime.get("usage_basis") == INCREMENT_BASIS:
        return result
    adapter = str(runtime.get("adapter") or "")
    session = str(runtime.get("session_id") or "")
    keys = CUMULATIVE_KEYS.get(adapter, ())
    raw = {key: value for key in keys if (value := _number(runtime.get(key))) is not None}
    if not keys or not session or not raw:
        return result
    base: dict[str, float] = {}
    for item in prior:
        if not isinstance(item, Mapping) or str(item.get("session_id") or "") != session:
            continue
        if str(item.get("adapter") or "") != adapter:
            continue
        for key, value in _cumulative(item).items():
            base[key] = max(base.get(key, 0), value)
    result["usage_basis"] = INCREMENT_BASIS
    result["usage_cumulative"] = dict(raw)
    if base:
        result["usage_session_base"] = {key: _same(value, raw.get(key, value))
                                        for key, value in base.items()}
    for key, value in raw.items():
        previous = base.get(key, 0)
        result[key] = _same(value - previous, value) if value >= previous else value
    return result


def prior_session_runtimes(
    db: FactoryDB, task: Mapping[str, Any], runtime: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Recorded runtimes of the same session (sessions never cross campaigns)."""

    session = str(runtime.get("session_id") or "")
    if not session:
        return []
    with db.connect() as connection:
        rows = connection.execute(
            """
            SELECT task_attempts.runtime_json FROM task_attempts JOIN tasks USING(task_id)
            WHERE tasks.campaign_id=? AND task_attempts.attempt_id != ?
              AND task_attempts.runtime_json LIKE ?
            ORDER BY task_attempts.started_at, task_attempts.rowid
            """,
            (str(task.get("campaign_id") or ""), str(task.get("current_attempt_id") or ""),
             f"%{session}%"),
        ).fetchall()
    result = []
    for row in rows:
        try:
            value = json.loads(str(row["runtime_json"] or "{}"))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            result.append(value)
    return result


def record_increment(db: FactoryDB, task: Mapping[str, Any],
                     runtime: Mapping[str, Any]) -> dict[str, Any]:
    """Ingestion side: the runtime to store for this attempt."""

    return to_increment(runtime, prior_session_runtimes(db, task, runtime))


# --------------------------------------------------------------------------- reading


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalized_attempts(db: FactoryDB, *, campaign_ids: Iterable[str] | None = None
                        ) -> list[dict[str, Any]]:
    """Every finished or running attempt with an incremental runtime, oldest first.

    Rows recorded before :func:`to_increment` existed are corrected here the same way
    (against the same session's earlier rows), so history reads right without being
    rewritten. Each item: attempt_id, task_id, task_type, campaign_id, runner, status,
    started_at, finished_at, run_seconds, runtime.
    """

    query = (
        "SELECT a.attempt_id, a.task_id, a.status, a.started_at, a.finished_at, "
        "a.run_seconds, a.runtime_json, t.task_type, t.campaign_id, t.runner "
        "FROM task_attempts a JOIN tasks t ON t.task_id = a.task_id"
    )
    parameters: tuple[Any, ...] = ()
    if campaign_ids is not None:
        ids = sorted({str(item) for item in campaign_ids})
        if not ids:
            return []
        query += f" WHERE t.campaign_id IN ({','.join('?' for _ in ids)})"  # noqa: S608
        parameters = tuple(ids)
    query += " ORDER BY a.started_at, a.rowid"
    with db.connect() as connection:
        rows = [dict(row) for row in connection.execute(query, parameters).fetchall()]
    history: dict[tuple[str, str], list[dict[str, Any]]] = {}
    result = []
    for row in rows:
        try:
            runtime = json.loads(str(row.pop("runtime_json") or "{}"))
        except json.JSONDecodeError:
            runtime = {}
        if not isinstance(runtime, dict):
            runtime = {}
        key = (str(runtime.get("adapter") or ""), str(runtime.get("session_id") or ""))
        earlier = history.setdefault(key, []) if key[1] else []
        normalized = to_increment(runtime, earlier) if key[1] else runtime
        if key[1]:
            earlier.append(runtime)
        result.append({**row, "runtime": normalized})
    return result


def normalized_runtimes(db: FactoryDB) -> dict[str, dict[str, Any]]:
    """``{attempt_id: incremental runtime}`` for every attempt (:func:`normalized_attempts`)."""

    return {str(item["attempt_id"]): item["runtime"] for item in normalized_attempts(db)}


def tokens_read(runtime: Mapping[str, Any]) -> int:
    """Input tokens the model read in this attempt (uncached + cached + cache writes)."""

    adapter = str(runtime.get("adapter") or "")
    value = int(_number(runtime.get("input_tokens")) or 0)
    if adapter not in INPUT_INCLUDES_CACHED:
        value += int(_number(runtime.get("cached_input_tokens")) or 0)
        value += int(_number(runtime.get("cache_write_input_tokens")) or 0)
    return value


def _model(runtime: Mapping[str, Any], settings: FactorySettings, runner: Any) -> str | None:
    execution = runtime.get("execution") if isinstance(runtime.get("execution"), Mapping) else {}
    for value in (execution.get("model"), runtime.get("model"), runtime.get("configured_model")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    spec = settings.runners.get(str(runtime.get("runner") or runner or ""))
    return spec.model if spec is not None and spec.model else None


def _price(prices: Mapping[str, ModelPrice], model: str | None) -> ModelPrice | None:
    if not model:
        return None
    if model in prices:
        return prices[model]
    # Dated or suffixed ids ("claude-opus-5-5-20261101", "gpt-6.1-sol[1m]").
    for name in sorted(prices, key=len, reverse=True):
        if model.startswith(name):
            return prices[name]
    return None


def equivalent_cost(runtime: Mapping[str, Any], price: ModelPrice | None) -> float | None:
    """List-price USD of one attempt's (incremental) usage; None without a price."""

    if price is None:
        return None
    adapter = str(runtime.get("adapter") or "")
    raw_input = float(_number(runtime.get("input_tokens")) or 0)
    cached = float(_number(runtime.get("cached_input_tokens")) or 0)
    write = float(_number(runtime.get("cache_write_input_tokens")) or 0)
    write_hour = min(write, float(_number(runtime.get("cache_write_1h_input_tokens")) or 0))
    output = float(_number(runtime.get("output_tokens")) or 0)
    uncached = max(raw_input - cached, 0.0) if adapter in INPUT_INCLUDES_CACHED else raw_input
    hour_price = price.cache_write_1h if price.cache_write_1h is not None else price.cache_write
    total = (uncached * price.input + cached * price.cached_input
             + (write - write_hour) * price.cache_write + write_hour * hour_price
             + output * price.output)
    return total / 1_000_000


def attempt_figures(item: Mapping[str, Any], settings: FactorySettings) -> dict[str, Any]:
    runtime = item.get("runtime") if isinstance(item.get("runtime"), Mapping) else {}
    model = _model(runtime, settings, item.get("runner"))
    cost = equivalent_cost(runtime, _price(settings.reporting.prices, model))
    has_usage = any(_number(runtime.get(key)) for key in TOKEN_KEYS)
    usd = cost if has_usage else (0.0 if cost is not None else None)
    from_cli = False
    cli = _number(runtime.get("cost_usd"))
    if (str(runtime.get("adapter") or "") == "claude" and not runtime.get("result_segments")
            and cli is not None and cli > (usd or 0.0)):
        # Recorded before the result events were summed: the token counts may hold only
        # the last stretch of the process; the CLI's process cost does not.
        usd, from_cli = float(cli), True
    return {
        "model": model,
        "tokens_read": tokens_read(runtime),
        "output_tokens": int(_number(runtime.get("output_tokens")) or 0),
        "equivalent_usd": usd,
        "has_usage": has_usage or from_cli,
        "cost_from_cli": from_cli,
        "agent_seconds": float(item.get("run_seconds") or 0.0),
    }


def _empty() -> dict[str, Any]:
    return {"attempts": 0, "agent_hours": 0.0, "tokens_read": 0, "output_tokens": 0,
            "equivalent_usd": 0.0, "unpriced_attempts": 0, "cost_from_cli_attempts": 0,
            "external_review_roles": 0, "codex_tokens_unsplit": 0}


def _add(entry: dict[str, Any], figures: Mapping[str, Any]) -> None:
    entry["attempts"] += 1
    entry["agent_hours"] += figures["agent_seconds"] / 3600
    entry["tokens_read"] += figures["tokens_read"]
    entry["output_tokens"] += figures["output_tokens"]
    entry["cost_from_cli_attempts"] += int(bool(figures.get("cost_from_cli")))
    if figures["equivalent_usd"] is None:
        if figures["has_usage"]:
            entry["unpriced_attempts"] += 1
    else:
        entry["equivalent_usd"] += figures["equivalent_usd"]


def _add_external(entry: dict[str, Any], roles: Iterable[Mapping[str, Any]]) -> None:
    """Reviewer processes of one unified review (not attempts: no attempt count)."""

    for role in roles:
        entry["external_review_roles"] += 1
        entry["tokens_read"] += int(role.get("tokens_read") or 0)
        entry["output_tokens"] += int(role.get("output_tokens") or 0)
        entry["codex_tokens_unsplit"] += int(role.get("tokens_total_unsplit") or 0)
        if role.get("equivalent_usd") is not None:
            entry["equivalent_usd"] += float(role["equivalent_usd"])


def _rounded(entry: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(entry)
    result["agent_hours"] = round(float(result["agent_hours"]), 2)
    result["equivalent_usd"] = round(float(result["equivalent_usd"]), 2)
    return result


# --------------------------------------------------------------------------- reviewers


def _claude_stream_usage(text: str) -> dict[str, Any] | None:
    """Summed ``result`` usage and the last ``total_cost_usd`` of a Claude stream-json run."""

    found: dict[str, Any] = {}
    segments = 0
    for line in text.splitlines():
        if '"result"' not in line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, Mapping) or event.get("type") != "result":
            continue
        segments += 1
        usage = event.get("usage") if isinstance(event.get("usage"), Mapping) else {}
        for source, key in (("input_tokens", "input_tokens"),
                            ("cache_read_input_tokens", "cached_input_tokens"),
                            ("cache_creation_input_tokens", "cache_write_input_tokens"),
                            ("output_tokens", "output_tokens")):
            value = _number(usage.get(source))
            if value is not None:
                found[key] = int(found.get(key, 0) + value)
        cost = _number(event.get("total_cost_usd"))
        if cost is not None:
            found["cost_usd"] = float(cost)
    return found if segments else None


def _codex_tokens(stderr: str) -> int | None:
    """The ``tokens used`` total ``codex exec`` prints at the end (no input/output split)."""

    lines = [line.strip() for line in stderr.splitlines()]
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].lower() == "tokens used" and index + 1 < len(lines):
            digits = lines[index + 1].replace(",", "")
            if digits.isdigit():
                return int(digits)
    return None


def external_review_usage(data_root: Path, decision_record: Any) -> list[dict[str, Any]]:
    """Use of the reviewer processes of one unified-review run, one row per role.

    ``decision_record`` is the review result's ``review_outcome.decision_record`` (relative
    to the data repository); its directory holds one folder per role with the process's
    ``stdout.txt``/``stderr.txt`` and ``receipt.json``. Claude roles: summed result usage and
    the CLI cost; Codex roles: the printed total only (``tokens_total_unsplit``, unpriced).
    """

    relative = str(decision_record or "").strip()
    if not relative:
        return []
    root = Path(data_root).resolve()
    run_dir = (root / relative).resolve().parent
    if not run_dir.is_relative_to((root / "reviews").resolve()) or not run_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for receipt_path in sorted(run_dir.glob("*/receipt.json")):
        receipt = _read_json(receipt_path)
        role_dir = receipt_path.parent
        tool = str(receipt.get("tool") or "").lower()
        row: dict[str, Any] = {"role": receipt.get("role") or role_dir.name,
                               "model": receipt.get("model"),
                               "provider": receipt.get("provider")}
        try:
            stdout = (role_dir / "stdout.txt").read_text(encoding="utf-8", errors="replace")
        except OSError:
            stdout = ""
        claude = _claude_stream_usage(stdout) if "codex" not in tool else None
        if claude is not None:
            runtime = {"adapter": "claude", **claude}
            row.update(tokens_read=tokens_read(runtime),
                       output_tokens=int(claude.get("output_tokens") or 0),
                       equivalent_usd=claude.get("cost_usd"))
        else:
            try:
                stderr = (role_dir / "stderr.txt").read_text(encoding="utf-8", errors="replace")
            except OSError:
                stderr = ""
            total = _codex_tokens(stderr)
            if total is None:
                continue
            row.update(tokens_total_unsplit=total, equivalent_usd=None)
        rows.append(row)
    return rows


def _review_runs(db: FactoryDB, data_root: Path | None) -> dict[str, list[dict[str, Any]]]:
    """``{paper_review task id: reviewer rows}`` for succeeded reviews with a run record."""

    if data_root is None:
        return {}
    with db.connect() as connection:
        rows = connection.execute(
            "SELECT task_id, result_path FROM tasks WHERE task_type='paper_review' "
            "AND status='succeeded' AND result_path IS NOT NULL"
        ).fetchall()
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        outcome = _read_json(Path(str(row["result_path"]))).get("review_outcome")
        if not isinstance(outcome, Mapping):
            continue
        try:
            roles = external_review_usage(data_root, outcome.get("decision_record"))
        except OSError:
            continue
        if roles:
            result[str(row["task_id"])] = roles
    return result


def token_cost_summary(
    db: FactoryDB, settings: FactorySettings, *, now: datetime | None = None,
    hours: int | None = None, data_root: Path | None = None,
) -> dict[str, Any]:
    """Tokens and equivalent cost per task type over the last ``hours`` (finished attempts)."""

    window = int(hours or settings.reporting.token_window_hours)
    moment = now or datetime.now(UTC)
    since = moment - timedelta(hours=window)
    by_type: dict[str, dict[str, Any]] = {}
    total = _empty()
    reviews = _review_runs(db, data_root)
    for item in normalized_attempts(db):
        finished = _parse_time(item.get("finished_at"))
        if finished is None or finished < since or str(item.get("status")) == "quota_deferred":
            continue
        figures = attempt_figures(item, settings)
        entry = by_type.setdefault(str(item.get("task_type") or ""), _empty())
        _add(entry, figures)
        _add(total, figures)
        # A review's reviewer processes count once, with its first attempt in the window.
        roles = reviews.pop(str(item.get("task_id") or ""), [])
        _add_external(entry, roles)
        _add_external(total, roles)
    return {
        "window_hours": window, "since": _iso(since),
        "basis": ("list-price equivalent, USD; per-attempt increments; Claude result stretches "
                  "summed (older Claude attempts: CLI process cost where higher); unified-review "
                  "reviewer processes included (Codex reviewers: unsplit token totals, unpriced)"),
        "by_task_type": {key: _rounded(value) for key, value in sorted(by_type.items())},
        "total": _rounded(total),
    }


# --------------------------------------------------------------------------- compute jobs


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def default_job_roots() -> tuple[Path, ...]:
    from . import local_compute, remote_wait

    roots = [remote_wait.default_queue_root() / "jobs",
             local_compute.default_queue_root() / "jobs"]
    return tuple(dict.fromkeys(roots))


def job_core_hours(directory: Path, *, now: datetime | None = None) -> float:
    """CPU core-hours one job used (or has used so far): threads x elapsed time.

    ailab jobs: ``result/receipt.json`` ``elapsed_seconds``; local jobs: status
    ``started_at`` to ``finished_at`` (or now while running). Queued, withdrawn or
    unreadable jobs count 0.
    """

    request = _read_json(directory / "request.json")
    resources = request.get("resources") if isinstance(request.get("resources"), Mapping) else {}
    threads = _number(resources.get("cpu_threads")) or 0
    if threads <= 0:
        return 0.0
    receipt = _read_json(directory / "result" / "receipt.json")
    elapsed = _number(receipt.get("elapsed_seconds"))
    if elapsed is None:
        status = _read_json(directory / "status.json")
        started = _parse_time(status.get("started_at"))
        finished = _parse_time(status.get("finished_at"))
        if started is None:
            return 0.0
        if finished is None:
            if str(status.get("state") or "") != "running":
                return 0.0
            finished = now or datetime.now(UTC)
        elapsed = max(0.0, (finished - started).total_seconds())
    return float(threads) * float(elapsed) / 3600


def campaign_job_ids(db: FactoryDB) -> dict[str, set[str]]:
    """Campaign -> compute job ids its tasks waited on (remote-wait records)."""

    from .remote_wait import WAIT_META_PREFIX

    result: dict[str, set[str]] = {}
    records = db.meta_items(WAIT_META_PREFIX)
    for task_id, raw in records.items():
        try:
            record = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            continue
        if not isinstance(record, Mapping):
            continue
        task = db.task(str(task_id))
        if task is None:
            continue
        ids = {str(item) for item in record.get("job_ids") or [] if isinstance(item, str)}
        if ids:
            result.setdefault(str(task["campaign_id"]), set()).update(ids)
    return result


def campaign_core_hours(
    db: FactoryDB,
    campaigns: Mapping[str, Mapping[str, Any]],
    *,
    job_roots: Iterable[Path] | None = None,
    attempt_root: Path | None = None,
    now: datetime | None = None,
) -> dict[str, float]:
    """Core-hours per campaign from the job status files.

    A job belongs to a campaign when one of its tasks waited on it (remote-wait
    record) or, for local jobs, when its ``source`` directory lies in the campaign's
    canonical or attempt workspaces. ailab jobs that no task waited on are not seen.
    """

    from .attempts import _token

    roots = [Path(root) for root in (job_roots if job_roots is not None else default_job_roots())]
    by_campaign = campaign_job_ids(db)
    workspaces: dict[str, list[Path]] = {}
    for campaign_id, campaign in campaigns.items():
        items = [Path(str(campaign["state_path"])).resolve()] if campaign.get("state_path") else []
        if attempt_root is not None:
            items.append((attempt_root / _token(campaign_id, prefix="campaign")).resolve())
        workspaces[campaign_id] = items
    result: dict[str, float] = {campaign_id: 0.0 for campaign_id in campaigns}
    seen: set[tuple[str, str]] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for directory in root.iterdir():
            if not directory.is_dir():
                continue
            job_id = directory.name
            owners = {cid for cid, ids in by_campaign.items() if job_id in ids and cid in result}
            if not owners:
                source = str(_read_json(directory / "request.json").get("source") or "")
                if source:
                    path = Path(source).resolve()
                    owners = {cid for cid, roots_ in workspaces.items()
                              if any(path == item or path.is_relative_to(item) for item in roots_)}
            if not owners:
                continue
            hours = job_core_hours(directory, now=now)
            for campaign_id in owners:
                if (campaign_id, job_id) in seen:
                    continue
                seen.add((campaign_id, job_id))
                result[campaign_id] += hours
    return result


# --------------------------------------------------------------------------- economics


def topic_economics(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    now: datetime | None = None,
    job_roots: Iterable[Path] | None = None,
) -> dict[str, Any]:
    """Per program topic in research: seats, agent hours, tokens, cost, core-hours, phase.

    Plus the line-wide average equivalent cost of a paper that reached the human
    confirmation queue (``ready_queue``/``submitted``): ``direct`` sums the topic's own
    campaign attempts; ``loaded`` divides every attempt in the window (scouts,
    admissions, decisions, frozen topics included) by the number of such papers.
    """

    if not settings.program.enabled:
        return {}
    from . import owner as owner_mode
    from .program import open_topic_ledger

    document = open_topic_ledger(paths, settings.program).read()
    topics = [topic for topic in document.get("topics") or []
              if isinstance(topic, Mapping) and topic.get("campaign_id")]
    since = _parse_time(settings.reporting.economics_since)
    rows_by_campaign: dict[str, list[dict[str, Any]]] = {}
    loaded = _empty()
    reviews = _review_runs(db, paths.data)
    for item in normalized_attempts(db):
        finished = _parse_time(item.get("finished_at"))
        # Finished attempts only: a seat counts once it has run.
        if finished is None or (since is not None and finished < since):
            continue
        if str(item.get("status")) == "quota_deferred":
            continue
        roles = reviews.pop(str(item.get("task_id") or ""), [])
        rows_by_campaign.setdefault(str(item.get("campaign_id") or ""), []).append(
            {**item, "external_roles": roles})
        _add(loaded, attempt_figures(item, settings))
        _add_external(loaded, roles)
    live = [topic for topic in topics if str(topic.get("status")) in {"active", "in_review"}]
    ready = [topic for topic in topics if str(topic.get("status")) in READY_STATUSES
             and (since is None or (_parse_time(_ready_at(topic)) or since) >= since)]
    campaigns = {str(topic["campaign_id"]): db.campaign(str(topic["campaign_id"])) or {}
                 for topic in [*live, *ready]}
    core_hours = campaign_core_hours(db, campaigns, job_roots=job_roots,
                                     attempt_root=paths.attempt_workspaces, now=now)
    rows = []
    for topic in live:
        campaign_id = str(topic["campaign_id"])
        entry = _empty()
        seats = 0
        for item in rows_by_campaign.get(campaign_id, []):
            _add(entry, attempt_figures(item, settings))
            _add_external(entry, item.get("external_roles") or [])
            seats += int(str(item.get("task_type")) == OWNER_TASK_TYPE)
        rows.append({
            "topic_id": topic.get("topic_id"), "campaign_id": campaign_id,
            "status": topic.get("status"),
            "phase": owner_mode.topic_phase(db, campaign_id, topic=topic),
            "seats": seats, **_rounded(entry),
            "cpu_core_hours": round(core_hours.get(campaign_id, 0.0), 1),
        })
    direct = _empty()
    direct_core = 0.0
    for topic in ready:
        campaign_id = str(topic["campaign_id"])
        for item in rows_by_campaign.get(campaign_id, []):
            _add(direct, attempt_figures(item, settings))
            _add_external(direct, item.get("external_roles") or [])
        direct_core += core_hours.get(campaign_id, 0.0)
    count = len(ready)
    return {
        "since": settings.reporting.economics_since,
        "topics": rows,
        "ready_papers": count,
        "per_ready_paper": None if not count else {
            "direct_equivalent_usd": round(direct["equivalent_usd"] / count, 2),
            "direct_agent_hours": round(direct["agent_hours"] / count, 2),
            "direct_cpu_core_hours": round(direct_core / count, 1),
            "loaded_equivalent_usd": round(loaded["equivalent_usd"] / count, 2),
        },
        "all_attempts": _rounded(loaded),
    }


def _ready_at(topic: Mapping[str, Any]) -> str | None:
    for entry in reversed(list(topic.get("history") or [])):
        if isinstance(entry, Mapping) and entry.get("to") == "ready_queue":
            return str(entry.get("at") or "") or None
    return None


__all__ = [
    "INCREMENT_BASIS",
    "attempt_figures",
    "campaign_core_hours",
    "equivalent_cost",
    "external_review_usage",
    "normalized_attempts",
    "normalized_runtimes",
    "record_increment",
    "to_increment",
    "token_cost_summary",
    "tokens_read",
    "topic_economics",
]
