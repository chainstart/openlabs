"""Research-program supply pipeline: two-step scout -> single cross-family review -> materialize.

Deterministic bookkeeping and routing only (2026-11-28 supply simplification):

1. ``topic_scout`` writes a one-page free-form Proposal Brief plus 6 minimal machine fields
   (old templated lines receive top-10 unoccupied ``queue_candidates`` and ``line_tools``).
2. Control plane runs 5 mechanical intake guards (minimal structure, compute locations,
   data_gb ceiling, free-data guard + ``needs_registration`` collection, duplicate check).
   Failures are rejected directly (no repair or revision loops).
3. One independent cross-family review (``portfolio_review:topic_admission``) judges
   proposals holistically and returns ``go`` or ``no_go`` (optional ``likely_band`` is
   informational only, never a gate).
4. Admitted topics materialize into owner-mode campaigns whose Milestone 1 is the Kill Test.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import assets as asset_library
from . import budget as budget_control
from . import line_facts
from . import usage as usage_accounting
from .config import RESEARCH_STAGE, SUPPLY_STAGE, FactorySettings, WorkspacePaths, dispatch_runner
from .contracts import (
    TOPIC_PROPOSAL_SCHEMA,
    admission_conditions,
    atomic_write_json,
    canonical_json_bytes,
    compute_plan_locations,
    data_source_identifiers,
    freeze_reason_category,
    proposal_from_legacy_card,
    sha256_file,
    validate_topic_proposal,
    validate_topic_review,
)
from .data_catalog import DataCatalogError, load_catalog
from .db import FactoryDB, utc_now
from .portfolio import (
    REVIEW_PACKET_SCHEMA,
    CandidateSpawn,
    ReviewSchedule,
    _review_control_root,
    _review_cursor_path,
    _task_id,
    _verified_review_packet,
    materialize_candidate,
)
from .program import (
    REJECTION_BUDGET_EXCEEDED,
    REJECTION_DATA_RESTRICTED,
    REJECTION_DUPLICATE_TOPIC,
    REJECTION_PROPOSAL_INVALID,
    REJECTION_REVIEW_NO_GO,
    REJECTION_REVIEW_UNDECIDED,
    TopicLedger,
    TopicLedgerError,
    activate_topic,
    admit_topic,
    card_sha256,
    find_topic,
    judged_rejection,
    last_rejection_reason,
    normalize_text,
    note_admission_attempt,
    open_topic_ledger,
    parked_program_projects,
    paused_topic_campaigns,
    propose_topic,
    record_rejected_card,
    reject_topic,
    slot_status,
    topic_for_campaign,
    topics_by_status,
)
from .program_autonomy import topic_budget_seconds
from .projects import ProjectConfig, load_project, workstream_policy
from .research_lines import (
    ENVIRONMENT_READY,
    environment_status,
    line_entry,
    line_resources,
    line_summary,
    queued_templates,
    read_lines_or_none,
)
from .resources import ResourceVector, default_task_resources
from .utilization import compute_backlog

SCOUT_TASK_TYPE = "topic_scout"
CARD_TASK_TYPES = (SCOUT_TASK_TYPE,)
ADMISSION_ROUTING_REASON = "topic_admission"
SCOUT_ROUTING_REASON = "program_slot_open"
SCOUT_PACKET_SCHEMA = "openlabs.topic_scout_packet.v1"
ADMISSION_RECORD_SCHEMA = "openlabs.topic_admission_record.v3"
SCOUT_SKILL = "openlabs-empirical-topic-scout"
ADMISSION_SKILL = "openlabs-topic-admission"
LAST_SCOUT_KEY = "program_last_scout_at"
SCOUT_REGISTERED_PREFIX = "program_scout_registered:"
# Two consecutive invalid or missing review verdicts reject the proposal as review_undecided.
MAX_REVIEW_ATTEMPTS = 2
MAX_QUEUE_CANDIDATES = 10
HUMAN_PROVIDER = "human"
IN_FLIGHT_STATUSES = ("queued", "leased", "running", "awaiting_remote")
POOL_STATUSES = ("proposed",)
SCOUT_LOAD_STATUSES = ("proposed", "admitted", "active", "in_review")
ADMITTED_WORK_STATUSES = ("admitted", "active", "in_review", "ready_queue", "submitted")
LINE_SLOTS_FULL_REASON = "line_slots_full"
POLISH_MODE_REASON = "polish_mode"
COMPUTE_BACKLOG_REASON = "compute_backlog"
WEEKLY_BUDGET_REASON = "scout_weekly_budget"
# Docker marks every container with this file; tests override it.
CONTAINER_MARKER = Path("/.dockerenv")

_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from",
    "how", "in", "into", "is", "it", "of", "on", "or", "over", "that", "the", "their",
    "this", "to", "under", "using", "what", "when", "whether", "which", "with",
})
_WORD_RE = re.compile(r"[a-z0-9]{2,}")


# --------------------------------------------------------------------------- helpers


def _control_root(paths: WorkspacePaths) -> Path:
    return paths.program_control


def _token(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in value).strip("-._")
    return cleaned or "program"


def _now_moment() -> datetime:
    return budget_control.current_time()


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def _clip(value: Any, limit: int = 200) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected an object: {path}")
    return value


def _signed(packet: dict[str, Any]) -> dict[str, Any]:
    packet["content_sha256"] = hashlib.sha256(canonical_json_bytes(packet)).hexdigest()
    return packet


def campaign_project(campaign: Mapping[str, Any]) -> ProjectConfig | None:
    configured = str(campaign.get("project_config_path") or "").strip()
    if not configured:
        return None
    try:
        return load_project(configured)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def scout_workstream_id(project: ProjectConfig) -> str | None:
    for workstream in project.workstreams:
        if workstream.continuation == "on_demand" and workstream.agent_role == "researcher":
            return workstream.workstream_id
    return None


def admission_workstream_id(project: ProjectConfig) -> str | None:
    for workstream in project.workstreams:
        if (
            workstream.continuation == "review_on_new_results"
            and workstream.spawn_candidate_workstreams
        ):
            return workstream.workstream_id
    return None


def _scope_key(line: Any, domain: Any) -> str:
    return str(line) if line else f"domain/{domain or ''}"


def scout_key(project: ProjectConfig) -> str:
    return _scope_key(project.research_line, project.domain)


def _topic_key(topic: Mapping[str, Any]) -> str:
    return _scope_key(topic.get("research_line"), topic.get("domain"))


def _scout_stamp(stamps: Mapping[str, str], key: str) -> str:
    return stamps.get(key, stamps.get(key.removeprefix("domain/"), ""))


def _rotation_projects(
    settings: FactorySettings, projects: list[ProjectConfig]
) -> list[ProjectConfig]:
    lines = settings.program.research_lines
    domains = settings.program.domains
    if lines:
        return [project for project in projects if project.research_line in lines]
    return [project for project in projects if not domains or project.domain in domains]


def research_lines_document(
    paths: WorkspacePaths, settings: FactorySettings
) -> dict[str, Any] | None:
    return read_lines_or_none(paths.data / settings.program.research_lines_path)


def lines_not_ready(
    paths: WorkspacePaths,
    settings: FactorySettings,
    lines: Any,
    *,
    db: FactoryDB | None = None,
) -> dict[str, str]:
    """``{line: environment status}`` for lines whose ``environment.status`` is not ``ready``."""

    del db  # line_facts is disconnected from topic supply.
    wanted = sorted({str(line).strip() for line in lines if str(line or "").strip()})
    if not wanted:
        return {}
    document = research_lines_document(paths, settings)
    if document is None:
        return {}
    statuses = {line: environment_status(document, line) for line in wanted}
    return {line: status for line, status in statuses.items() if status != ENVIRONMENT_READY}


def program_projects(paths: WorkspacePaths) -> list[ProjectConfig]:
    found: list[ProjectConfig] = []
    for path in paths.project_config_paths():
        try:
            project = load_project(path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if project.program and project.status == "active":
            found.append(project)
    return found


def _resource(label: str, path: Path) -> dict[str, str] | None:
    if not path.is_file():
        return None
    return {"label": label, "path": str(path.resolve()), "sha256": sha256_file(path)}


def program_read_resources(
    paths: WorkspacePaths,
    settings: FactorySettings,
    ledger: TopicLedger,
) -> list[dict[str, str]]:
    registry = paths.data / "registry"
    items = [
        _resource("topic-ledger", ledger.path),
        _resource("settings.yaml#research_portfolio", registry / "settings.yaml"),
        _resource("team-rejection-ledger", registry / "journal-rejections.json"),
        _resource("reusable-asset-index", paths.data / settings.program.asset_index_path),
        _resource("research-lines", paths.data / settings.program.research_lines_path),
        _resource(
            "research-lines-summary",
            (paths.data / settings.program.research_lines_path).with_suffix(".md"),
        ),
    ]
    return [item for item in items if item is not None]


def _ledger_snapshot(document: Mapping[str, Any], *, line: str | None = None) -> list[dict[str, Any]]:
    snapshot: list[dict[str, Any]] = []
    for topic in document.get("topics") or []:
        if not isinstance(topic, Mapping):
            continue
        if line and str(topic.get("research_line") or "") != line:
            continue
        item: dict[str, Any] = {
            "topic_id": topic.get("topic_id"),
            "domain": topic.get("domain"),
            "research_line": topic.get("research_line"),
            "question": topic.get("question"),
            "status": topic.get("status"),
        }
        if topic.get("status") == "rejected":
            item["rejection_reason"] = last_rejection_reason(topic)
            admission = topic.get("admission")
            if isinstance(admission, Mapping) and admission.get("rationale"):
                item["review_rationale"] = _clip(admission["rationale"], 240)
        if topic.get("freeze_reason_class"):
            item["freeze_reason_class"] = topic.get("freeze_reason_class")
        if topic.get("freeze_reason_category"):
            item["freeze_reason_category"] = topic.get("freeze_reason_category")
        if topic.get("queue_entry_id"):
            item["queue_entry_id"] = topic.get("queue_entry_id")
        if topic.get("supersedes"):
            item["supersedes"] = topic.get("supersedes")
        snapshot.append(item)
    return snapshot


def packet_read_resources(input_path: Any) -> list[dict[str, str]]:
    """Read resources a program packet asks the task spec to expose (else ``[]``)."""

    value = str(input_path or "").strip()
    if not value:
        return []
    path = Path(value)
    if path.suffix != ".json" or not path.is_file():
        return []
    try:
        packet = _read_object(path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return []
    schema = packet.get("schema_version")
    if schema != SCOUT_PACKET_SCHEMA and not (
        schema == REVIEW_PACKET_SCHEMA and packet.get("program") is True
    ):
        return []
    items: list[dict[str, str]] = []
    for item in packet.get("read_resources") or []:
        if not isinstance(item, Mapping):
            continue
        label = str(item.get("label") or "").strip()
        resource = Path(str(item.get("path") or ""))
        if label and resource.is_absolute() and resource.is_file():
            items.append({"label": label, "path": str(resource)})
    return items


def lead_quota_short(db: FactoryDB, settings: FactorySettings) -> bool:
    if not budget_control.routing_enabled(settings):
        return False
    router = budget_control.QuotaRouter.build(db, settings, now=_now_moment())
    return router.lead_short


def _program_tasks(
    db: FactoryDB,
    *,
    statuses: tuple[str, ...],
    where: str = "",
    parameters: tuple[Any, ...] = (),
) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in statuses)
    with db.connect() as connection:
        rows = connection.execute(
            f"SELECT * FROM tasks WHERE status IN ({placeholders}) {where} "  # noqa: S608
            "ORDER BY created_at, task_id",
            (*statuses, *parameters),
        ).fetchall()
    return [dict(row) for row in rows]


def scout_task_key(db: FactoryDB, task: Mapping[str, Any]) -> str:
    try:
        packet = _read_object(Path(str(task.get("input_path") or "")))
        if packet.get("schema_version") == SCOUT_PACKET_SCHEMA:
            return _topic_key(packet)
    except (OSError, ValueError):
        pass
    project = campaign_project(db.campaign(str(task.get("campaign_id") or "")) or {})
    return scout_key(project) if project else _topic_key(task)


def _scout_task_line(db: FactoryDB, task: Mapping[str, Any]) -> str:
    try:
        packet = _read_object(Path(str(task.get("input_path") or "")))
        if packet.get("schema_version") == SCOUT_PACKET_SCHEMA:
            return str(packet.get("research_line") or "")
    except (OSError, ValueError):
        pass
    project = campaign_project(db.campaign(str(task.get("campaign_id") or "")) or {})
    return str(project.research_line or "") if project else ""


def admission_task_keys(db: FactoryDB, task: Mapping[str, Any]) -> set[str]:
    try:
        packet = _verified_review_packet(Path(str(task.get("input_path") or "")))
        entries = packet.get("topic_proposals") or packet.get("topic_cards") or []
        keys: set[str] = set()
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            body = entry.get("proposal") or entry.get("card")
            if isinstance(body, Mapping):
                keys.add(_topic_key(body))
        if keys:
            return keys
    except (OSError, TypeError, ValueError):
        pass
    project = campaign_project(db.campaign(str(task.get("campaign_id") or "")) or {})
    return {scout_key(project) if project else _topic_key(task)}


def _proposed_pool(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    return topics_by_status(document, *POOL_STATUSES)


def admission_sequence(db: FactoryDB) -> dict[str, int]:
    with db.connect() as connection:
        rows = connection.execute(
            "SELECT entity_id, MIN(event_id) AS seq FROM events "
            "WHERE entity_type='topic' AND event_type='topic_admitted' GROUP BY entity_id"
        ).fetchall()
    return {str(row["entity_id"]): int(row["seq"]) for row in rows}


def waiting_admitted(
    document: Mapping[str, Any],
    sequence: Mapping[str, int] | None = None,
) -> list[dict[str, Any]]:
    order = dict(sequence or {})

    def key(topic: Mapping[str, Any]) -> tuple[int, str, str]:
        topic_id = str(topic.get("topic_id") or "")
        return (order.get(topic_id, 1 << 62), str(topic.get("admitted_at") or ""), topic_id)

    return sorted(topics_by_status(document, "admitted"), key=key)


# --------------------------------------------------------------------------- old-line queues


def _legacy_card_queue_entry_id(topic: Mapping[str, Any]) -> str | None:
    direct = str(topic.get("queue_entry_id") or "").strip()
    if direct:
        return direct
    card_path = Path(str(topic.get("card_path") or ""))
    if not card_path.is_file():
        return None
    try:
        card = _read_object(card_path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    direct = str(card.get("queue_entry_id") or "").strip()
    if direct:
        return direct
    entry = card.get("candidate_queue_entry")
    if isinstance(entry, Mapping):
        for key in ("entry_id", "id", "batch_id"):
            val = str(entry.get(key) or "").strip()
            if val:
                return val
    return None


def _is_superseded(document: Mapping[str, Any], topic: Mapping[str, Any]) -> bool:
    tid = topic.get("topic_id")
    return any(
        isinstance(other, Mapping) and other.get("supersedes") == tid
        and other.get("status") != "rejected"
        for other in document.get("topics") or []
    )


def ledger_queue_entries(document: Mapping[str, Any], line: str | None) -> dict[str, dict[str, str]]:
    """``{entry_id.casefold(): {entry_id, topic_id, status}}`` occupied on ``line``."""

    if not line:
        return {}
    taken: dict[str, dict[str, str]] = {}
    for topic in document.get("topics") or []:
        if not isinstance(topic, Mapping) or str(topic.get("research_line") or "") != line:
            continue
        status = str(topic.get("status") or "")
        if status == "rejected" and not judged_rejection(topic):
            continue
        if status in {"frozen", "rejected"} and _is_superseded(document, topic):
            continue
        entry_id = _legacy_card_queue_entry_id(topic)
        if not entry_id:
            continue
        key = entry_id.casefold()
        if key not in taken or status != "rejected":
            taken[key] = {
                "entry_id": entry_id,
                "topic_id": str(topic.get("topic_id") or ""),
                "status": status,
            }
    return taken


def _summarize_queue_entry(item: Mapping[str, Any], template: str, entry_id: str) -> dict[str, Any]:
    fields = item.get("card_fields") if isinstance(item.get("card_fields"), Mapping) else {}
    occupancy = item.get("ledger_occupancy") if isinstance(item.get("ledger_occupancy"), Mapping) else {}
    summary: dict[str, Any] = {
        "entry_id": entry_id,
        "template": str(
            item.get("suggested_template") or fields.get("paper_template") or template
        ),
    }
    if item.get("rank") is not None:
        summary["rank"] = item["rank"]
    if item.get("title"):
        summary["title"] = _clip(item["title"], 160)
    question = item.get("question") or fields.get("question")
    if question:
        summary["question"] = _clip(question, 220)
    elif item.get("identifiers") and isinstance(item["identifiers"], Mapping):
        ids = item["identifiers"]
        target = ids.get("gaia_dr3") or ids.get("tic") or ids.get("vsx") or entry_id
        extra: list[str] = []
        if isinstance(item.get("period"), Mapping) and item["period"].get("days"):
            extra.append(f"P={item['period']['days']} d")
        if isinstance(item.get("brightness"), Mapping) and item["brightness"].get("g_mag"):
            extra.append(f"G={item['brightness']['g_mag']}")
        summary["target"] = f"{target}" + (f" ({', '.join(extra)})" if extra else "")
    if item.get("market"):
        summary["market"] = _clip(item["market"], 80)
    if item.get("rule_change_or_evolution"):
        summary["rule_change"] = _clip(item["rule_change_or_evolution"], 180)
    if item.get("falsifiable_claim"):
        summary["claim"] = _clip(item["falsifiable_claim"], 180)
    if item.get("data_needed"):
        summary["data"] = _clip(item["data_needed"], 180)
    elif isinstance(item.get("tess"), Mapping):
        tess = item["tess"]
        sectors = tess.get("sectors") or tess.get("n_sectors")
        summary["data"] = _clip(f"TESS sectors={sectors}", 120)
    elif isinstance(fields.get("data_sources"), list):
        ids = data_source_identifiers(fields["data_sources"])
        if ids:
            summary["data"] = _clip(", ".join(ids[:4]), 180)
    if item.get("method"):
        summary["method"] = _clip(item["method"], 160)
    novelty = item.get("novelty")
    if isinstance(novelty, Mapping) and novelty.get("verdict"):
        summary["novelty"] = str(novelty["verdict"])
    reopens = occupancy.get("reopens") or fields.get("reopens") or item.get("reopens")
    if isinstance(reopens, str) and reopens.strip():
        summary["reopens"] = reopens.strip()
    return summary


def queue_candidates(
    paths: WorkspacePaths,
    settings: FactorySettings,
    line: str | None,
    document: Mapping[str, Any],
    *,
    limit: int = MAX_QUEUE_CANDIDATES,
) -> list[dict[str, Any]]:
    """Top ``limit`` unoccupied candidate summaries from an old line's declared queues."""

    if not line or limit <= 0:
        return []
    queues = queued_templates(research_lines_document(paths, settings), line)
    if not queues:
        return []
    taken = ledger_queue_entries(document, line)
    seen_paths: set[str] = set()
    seen_ids: set[str] = set()
    selected: list[dict[str, Any]] = []
    for template, raw_path in queues.items():
        if raw_path in seen_paths:
            continue
        seen_paths.add(raw_path)
        try:
            queue = json.loads(Path(raw_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        candidates = queue.get("candidates") if isinstance(queue, Mapping) else None
        if not isinstance(candidates, list):
            continue
        for item in candidates:
            if not isinstance(item, Mapping):
                continue
            entry_id = str(
                item.get("entry_id") or item.get("id") or item.get("batch_id") or ""
            ).strip()
            if not entry_id or entry_id.casefold() in seen_ids:
                continue
            if str(item.get("status") or "").strip().lower() == "blocked":
                continue
            occupancy = item.get("ledger_occupancy")
            reopens = None
            if isinstance(occupancy, Mapping):
                state = str(occupancy.get("state") or "free")
                if state not in {"free", "reopenable"}:
                    continue
                if state == "reopenable" and isinstance(occupancy.get("reopens"), str):
                    reopens = occupancy["reopens"].strip() or None
            fields = item.get("card_fields") if isinstance(item.get("card_fields"), Mapping) else {}
            if not reopens and isinstance(fields.get("reopens"), str):
                reopens = fields["reopens"].strip() or None
            if entry_id.casefold() in taken and not reopens:
                continue
            seen_ids.add(entry_id.casefold())
            selected.append(_summarize_queue_entry(item, template, entry_id))
            if len(selected) >= limit:
                return selected
    return selected


# --------------------------------------------------------------------------- weekly spend cap


def weekly_supply_spend(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    projects: list[ProjectConfig],
    *,
    moment: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """7-day supply spend (scout + review) per line/scope, including Gemini pricing."""

    now = moment or _now_moment()
    cutoff = now - timedelta(days=7)
    campaign_to_key: dict[str, str] = {}
    for project in projects:
        key = scout_key(project)
        for cid in (scout_workstream_id(project), admission_workstream_id(project)):
            if cid:
                campaign_to_key[cid] = key
    if not campaign_to_key:
        return {}
    totals: dict[str, dict[str, Any]] = {}
    for attempt in usage_accounting.normalized_attempts(db, campaign_ids=campaign_to_key):
        if attempt.get("status") == "quota_deferred":
            continue
        stamp = budget_control.parse_time(attempt.get("finished_at") or attempt.get("started_at"))
        if stamp is None or stamp < cutoff:
            continue
        key = campaign_to_key.get(str(attempt.get("campaign_id") or ""))
        if not key:
            continue
        figures = usage_accounting.attempt_figures(attempt, settings)
        row = totals.setdefault(key, {"usd": 0.0, "agent_hours": 0.0, "attempts": 0, "unpriced": 0})
        row["attempts"] += 1
        row["agent_hours"] += float(figures["agent_seconds"]) / 3600.0
        if figures["equivalent_usd"] is None:
            if figures["has_usage"]:
                row["unpriced"] += 1
        else:
            row["usd"] += float(figures["equivalent_usd"])
    return {
        key: {
            "usd": round(row["usd"], 2),
            "agent_hours": round(row["agent_hours"], 2),
            "attempts": row["attempts"],
            "unpriced": row["unpriced"],
        }
        for key, row in totals.items()
    }


def weekly_budget_blocks(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    projects: list[ProjectConfig],
    *,
    moment: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Lines that reached ``[program.supply].scout_weekly_usd_per_line`` over the last 7 days."""

    cap = float(settings.program.supply.scout_weekly_usd_per_line)
    if cap <= 0:
        return {}
    spend = weekly_supply_spend(db, paths, settings, projects, moment=moment)
    blocks: dict[str, dict[str, Any]] = {}
    for project in projects:
        key = scout_key(project)
        if key in blocks:
            continue
        row = spend.get(key)
        if row and row["usd"] >= cap:
            blocks[key] = {
                "research_line": project.research_line or None,
                "domain": project.domain,
                "reason": WEEKLY_BUDGET_REASON,
                "spent_usd": row["usd"],
                "cap_usd": cap,
                "agent_hours": row["agent_hours"],
                "attempts": row["attempts"],
            }
    return blocks


# --------------------------------------------------------------------------- scouts


@dataclass(frozen=True)
class ScoutDecision:
    task_id: str | None = None
    domain: str | None = None
    reason: str | None = None
    research_line: str | None = None


def _choose_scout_project(
    db: FactoryDB,
    settings: FactorySettings,
    projects: list[ProjectConfig],
    document: Mapping[str, Any],
    *,
    exclude: frozenset[str] = frozenset(),
) -> tuple[ProjectConfig, str] | None:
    lines = list(settings.program.research_lines)
    configured = list(settings.program.domains)
    usable: list[tuple[ProjectConfig, str]] = []
    for project in _rotation_projects(settings, projects):
        if scout_key(project) in exclude:
            continue
        scout_id = scout_workstream_id(project)
        campaign = db.campaign(scout_id) if scout_id else None
        if campaign is None or str(campaign.get("status") or "") != "active":
            continue
        usable.append((project, str(scout_id)))
    if not usable:
        return None
    load: dict[str, int] = {}
    for topic in topics_by_status(document, *SCOUT_LOAD_STATUSES):
        key = _topic_key(topic)
        load[key] = load.get(key, 0) + 1
    last = db.meta_items(LAST_SCOUT_KEY + ":")

    def order_key(item: tuple[ProjectConfig, str]) -> tuple[int, str, int, str]:
        project = item[0]
        rotation = scout_key(project)
        if lines:
            order = lines.index(project.research_line) if project.research_line in lines else 0
        else:
            order = configured.index(project.domain) if project.domain in configured else 0
        return (load.get(rotation, 0), _scout_stamp(last, rotation), order, project.project_id)

    return min(usable, key=order_key)


def _preferred_scout_runner(
    db: FactoryDB, settings: FactorySettings, *, moment: datetime
) -> Any:
    """First usable runner in ``[program.supply].scout_runners``, else first configured."""

    specs = [
        settings.runners[name]
        for name in settings.program.supply.scout_runners
        if name in settings.runners
    ]
    if not specs:
        return None
    try:
        router = budget_control.QuotaRouter.build(db, settings, now=moment)
        for spec in specs:
            if router.usable(spec, "ordinary"):
                return spec
    except Exception:  # noqa: BLE001 - quota readings are advisory here
        pass
    return specs[0]


def _scout_objective(
    project: ProjectConfig, *, max_proposals: int, has_queue: bool
) -> str:
    scope = (
        f"research line `{project.research_line}` ({project.domain})"
        if project.research_line
        else f"domain `{project.domain}` ({project.project_id})"
    )
    queue_rule = (
        " This line provides `queue_candidates` in the packet: draw from them FIRST using the "
        "line's `line_tools` and `data_catalog`, setting `queue_entry_id` on each proposal "
        "(and `reopens` when reopening a listed topic). Only propose outside the queue if the "
        "queue candidates are unsuitable."
        if has_queue
        else " Use the line's `data_catalog` and `line_tools` (when present) plus literature "
        "to propose high-ambition, feasible computational questions."
    )
    return (
        f"Scout up to {max_proposals} topic proposal(s) for {scope} following the "
        f"`{SCOUT_SKILL}` skill. Read the scout packet at the input path (ledger snapshot, "
        "research-lines summary, line tools, data catalogue, queue candidates)."
        + queue_rule
        + " Return proposals in `topic_proposals[]` (openlabs.topic_proposal.v1): each has "
        "`question`, a <=1-page Markdown `brief` (<=6000 chars covering the 6 brief sections), "
        "`data_sources` (free only: `direct` or `form_or_registration`, never `restricted`), "
        "`compute_estimate` (`locations`, `data_gb`, `agent_hours`), and optional "
        "`queue_entry_id` / `reopens`. An empty list is valid if nothing clears the bar. "
        "Do not run the full research."
    )


def _schedule_one_scout(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    document: Mapping[str, Any],
    ledger: TopicLedger,
    status: Any,
    project: ProjectConfig,
    campaign_id: str,
    max_proposals: int,
    moment: datetime,
    preferred: Any = None,
) -> ScoutDecision:
    campaign = db.campaign(campaign_id) or {}
    stamp = _iso(moment)
    rotation = scout_key(project)
    line = project.research_line
    lines_doc = research_lines_document(paths, settings) if line else None
    entry = line_entry(lines_doc, line) if line else None
    candidates = queue_candidates(paths, settings, line, document) if line else []
    tools = line_resources(entry) if entry else {}
    line_fields: dict[str, Any] = {}
    if line:
        line_fields["research_line"] = line
        line_fields["research_line_summary"] = line_summary(lines_doc, line)
        if tools:
            line_fields["line_tools"] = tools
        if candidates:
            line_fields["queue_candidates"] = candidates
        free = status.line_free_slots(line)
        if free is not None:
            line_fields["line_free_slots"] = free
    sequence = db.task_count(campaign_id)
    digest = hashlib.sha256(
        (f"{campaign_id}\0{stamp}" + (f"\0{sequence}" if sequence else "")).encode()
    ).hexdigest()
    task_id = f"topic-scout:{digest[:32]}"
    packet_path = (
        _control_root(paths) / _token(project.project_id) / "scout-packets"
        / f"{stamp.replace(':', '')}-{digest[:12]}.json"
    )
    packet = _signed(
        {
            "schema_version": SCOUT_PACKET_SCHEMA,
            "proposal_schema": TOPIC_PROPOSAL_SCHEMA,
            "project_id": project.project_id,
            "domain": project.domain,
            **line_fields,
            "max_proposals": max_proposals,
            "max_cards": max_proposals,
            "free_slots": status.free_slots,
            "candidate_pool": len(_proposed_pool(document)),
            "ledger_snapshot": _ledger_snapshot(document, line=line),
            "read_resources": program_read_resources(paths, settings, ledger),
            **asset_library.packet_fields(paths, settings, domains=[project.domain]),
            **(
                {
                    budget_control.PREFERRED_RUNNER_FIELD: preferred.name,
                    "preferred_family": preferred.family,
                }
                if preferred is not None
                else {}
            ),
            "created_at": stamp,
        }
    )
    atomic_write_json(packet_path, packet)
    policy = workstream_policy(campaign)
    resources_value = policy.get("resources")
    resources = (
        ResourceVector.from_mapping(resources_value)
        if isinstance(resources_value, Mapping)
        else default_task_resources(settings)
    )
    wall = policy.get("wall_seconds")
    db.enqueue_task(
        task_id=task_id,
        campaign_id=campaign_id,
        domain=project.domain,
        task_type=SCOUT_TASK_TYPE,
        objective=_scout_objective(
            project, max_proposals=max_proposals, has_queue=bool(candidates)
        ),
        input_path=str(packet_path),
        skill_path=SCOUT_SKILL,
        runner=dispatch_runner(settings, SCOUT_TASK_TYPE, SCOUT_ROUTING_REASON, "balanced"),
        routing_reason=SCOUT_ROUTING_REASON,
        agent_role="researcher",
        session_mode="fresh",
        priority=int(campaign.get("priority") or 0),
        max_attempts=settings.max_attempts,
        max_wall_seconds=(
            min(int(wall), settings.max_task_wall_seconds)
            if isinstance(wall, int) and not isinstance(wall, bool) and wall > 0
            else settings.max_task_wall_seconds
        ),
        **resources.to_dict(),
    )
    db.update_meta(
        {LAST_SCOUT_KEY: stamp, f"{LAST_SCOUT_KEY}:{rotation}": stamp},
        events=[
            (
                "program",
                project.project_id,
                "topic_scout_scheduled",
                {
                    "task_id": task_id,
                    "domain": project.domain,
                    "research_line": line,
                    "max_proposals": max_proposals,
                    "queue_candidates": len(candidates),
                    "free_slots": status.free_slots,
                    **(
                        {"preferred_runner": preferred.name, "preferred_family": preferred.family}
                        if preferred is not None
                        else {}
                    ),
                },
            )
        ],
    )
    return ScoutDecision(task_id=task_id, domain=project.domain, research_line=line)


def schedule_scouts(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    lead_short: bool,
    now: datetime | None = None,
) -> tuple[list[ScoutDecision], str | None]:
    """Schedule up to ``supply.max_concurrent_scouts`` scouts (at most 1 per line)."""

    program = settings.program
    supply = program.supply
    if not program.enabled:
        return [], "program_disabled"
    if program.stops(SUPPLY_STAGE):
        return [], POLISH_MODE_REASON
    if not budget_control.routing_enabled(settings):
        return [], "provider_routing_not_configured"
    ledger = open_topic_ledger(paths, program)
    document = ledger.read()
    status = slot_status(
        document, program, parked_program_projects(paths), paused_topic_campaigns(db)
    )
    if status.admission_paused:
        return [], "admission_paused"
    if status.free_slots <= 0:
        return [], "no_free_slot"
    if compute_backlogged(settings):
        return [], COMPUTE_BACKLOG_REASON
    all_projects = program_projects(paths)
    rotating = _rotation_projects(settings, all_projects)
    scouting = [
        project for project in rotating if not program.stops(SUPPLY_STAGE, project.research_line)
    ]
    if rotating and not scouting:
        return [], POLISH_MODE_REASON
    blocked_lines = lines_not_ready(
        paths, settings, [project.research_line for project in scouting]
    )
    ready_projects = [
        project for project in scouting if project.research_line not in blocked_lines
    ]
    if scouting and not ready_projects:
        return [], "research_line_environment_not_ready"
    projects = [
        project for project in ready_projects if not status.line_full(project.research_line)
    ]
    if ready_projects and not projects:
        return [], LINE_SLOTS_FULL_REASON
    if not projects:
        return [], "no_program_project"

    pool_by_key = Counter(_topic_key(topic) for topic in _proposed_pool(document))
    legacy_keys = {scout_key(project) for project in projects if not project.research_line}
    legacy_pool = sum(pool_by_key[key] for key in legacy_keys)
    pool_cap = supply.candidate_pool_size
    needs = {
        scout_key(project): pool_cap - (
            pool_by_key[scout_key(project)] if project.research_line else legacy_pool
        )
        for project in projects
    }
    projects = [project for project in projects if needs[scout_key(project)] > 0]
    if not projects:
        return [], "candidate_pool_at_low_water"
    if lead_short:
        return [], "lead_quota_short"

    in_flight = _program_tasks(
        db, statuses=IN_FLIGHT_STATUSES, where="AND task_type=?", parameters=(SCOUT_TASK_TYPE,)
    )
    flight_keys = [scout_task_key(db, task) for task in in_flight]
    # Fixed per-line concurrency limit: at most 1 in-flight scout per line.
    busy = set(flight_keys)
    room = supply.max_concurrent_scouts - len(in_flight)
    if room <= 0:
        return [], "scout_in_flight" if supply.max_concurrent_scouts == 1 else "max_concurrent_scouts"

    moment = now or _now_moment()
    stamps = db.meta_items(LAST_SCOUT_KEY + ":")
    recent: set[str] = set()
    for project in projects:
        key = scout_key(project)
        last_stamp = _scout_stamp(stamps, key)
        if not stamps and not project.research_line:
            last_stamp = db.meta_get(LAST_SCOUT_KEY)
        last = budget_control.parse_time(last_stamp)
        if last is not None and moment - last < timedelta(hours=supply.scout_min_interval_hours):
            recent.add(key)

    budget_blocks = weekly_budget_blocks(db, paths, settings, projects, moment=moment)
    blocked_keys = frozenset(budget_blocks)
    preferred = _preferred_scout_runner(db, settings, moment=moment)

    scheduled: list[ScoutDecision] = []
    reason: str | None = None
    while len(scheduled) < room:
        chosen = _choose_scout_project(
            db, settings, projects, document,
            exclude=frozenset(busy | recent) | blocked_keys,
        )
        if chosen is None:
            if blocked_keys and _choose_scout_project(
                db, settings, projects, document, exclude=frozenset(busy | recent)
            ) is not None:
                reason = WEEKLY_BUDGET_REASON
            elif _choose_scout_project(db, settings, projects, document) is None:
                reason = "no_program_project"
            elif _choose_scout_project(db, settings, projects, document, exclude=frozenset(busy)) is None:
                reason = "scout_in_flight"
            else:
                reason = "scout_min_interval"
            break
        project, campaign_id = chosen
        key = scout_key(project)
        decision = _schedule_one_scout(
            db, paths, settings, document=document, ledger=ledger, status=status,
            project=project, campaign_id=campaign_id,
            max_proposals=max(1, needs[key]), moment=moment, preferred=preferred,
        )
        scheduled.append(decision)
        busy.add(key)
    if len(scheduled) == room and supply.max_concurrent_scouts > 1:
        reason = "max_concurrent_scouts"
    return scheduled, reason


def maybe_schedule_scout(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    lead_short: bool,
    now: datetime | None = None,
) -> ScoutDecision:
    scheduled, reason = schedule_scouts(db, paths, settings, lead_short=lead_short, now=now)
    if scheduled:
        return scheduled[0]
    return ScoutDecision(reason=reason)


# --------------------------------------------------------------------------- mechanical intake


def available_compute_locations(settings: FactorySettings) -> tuple[str, ...]:
    """Configured experiment locations, minus WSL mathematics inside a container."""

    allowed = settings.program.compute_locations
    if CONTAINER_MARKER.exists():
        allowed = tuple(item for item in allowed if item != "wsl_math")
    return allowed


def compute_location_problem(settings: FactorySettings, proposal: Mapping[str, Any]) -> str | None:
    allowed = available_compute_locations(settings)
    missing = [item for item in compute_plan_locations(proposal) if item not in allowed]
    if not missing:
        return None
    return (
        "compute_location_unavailable:" + ",".join(missing)
        + " (this instance runs " + (", ".join(allowed) or "no location") + ")"
    )


def _line_catalog_index(
    paths: WorkspacePaths, settings: FactorySettings, line: str | None
) -> dict[str, dict[str, Any]]:
    if not line:
        return {}
    entry = line_entry(research_lines_document(paths, settings), line) or {}
    env = entry.get("environment") if isinstance(entry.get("environment"), Mapping) else {}
    raw_path = env.get("data_catalog")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return {}
    try:
        doc = load_catalog(Path(raw_path.strip()))
    except (OSError, DataCatalogError):
        return {}
    index: dict[str, dict[str, Any]] = {}
    for item in doc.get("sources") or []:
        if not isinstance(item, Mapping):
            continue
        for key in (item.get("id"), item.get("name")):
            if isinstance(key, str) and key.strip():
                index[key.strip().casefold()] = dict(item)
    return index


def _merge_registration_items(
    *lists: Any,
) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for items in lists:
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, Mapping):
                continue
            source = str(item.get("source") or "").strip()
            if not source or source.casefold() in seen:
                continue
            seen.add(source.casefold())
            entry: dict[str, str] = {"source": source}
            reg = str(item.get("registration") or "").strip()
            if reg:
                entry["registration"] = reg
            if str(item.get("catalog_id") or "").strip():
                entry["catalog_id"] = str(item["catalog_id"]).strip()
            merged.append(entry)
    return merged


def _check_free_data(
    paths: WorkspacePaths,
    settings: FactorySettings,
    proposal: Mapping[str, Any],
) -> tuple[list[str], list[dict[str, str]]]:
    """Mechanical check #4: reject restricted/blocked sources; collect needs_registration."""

    line = str(proposal.get("research_line") or "").strip() or None
    catalog = _line_catalog_index(paths, settings, line)
    errors: list[str] = []
    registrations: list[dict[str, str]] = []
    for index, source in enumerate(proposal.get("data_sources") or []):
        if not isinstance(source, Mapping):
            continue
        ident = str(source.get("id_or_url") or "").strip()
        access = str(source.get("access") or "").strip()
        cat_id = str(source.get("catalog_id") or "").strip()
        cat_entry = catalog.get(cat_id.casefold()) if cat_id else None
        if cat_entry is None and ident:
            cat_entry = catalog.get(ident.casefold())
        if access == "restricted":
            errors.append(f"data_sources[{index}] ({ident}) is restricted/paid")
        if cat_entry is not None and str(cat_entry.get("status") or "") == "blocked":
            why = str(cat_entry.get("blocked_reason") or "blocked in data catalog")
            errors.append(f"data_sources[{index}] ({cat_entry.get('id') or ident}) is blocked: {why}")
        if access == "form_or_registration" or (
            cat_entry is not None and str(cat_entry.get("status") or "") == "needs_registration"
        ):
            reg_note = (
                str(source.get("registration") or "").strip()
                or str((cat_entry or {}).get("registration") or "").strip()
                or "free registration required"
            )
            item: dict[str, str] = {"source": ident or str((cat_entry or {}).get("id") or ""), "registration": reg_note}
            if cat_entry and cat_entry.get("id"):
                item["catalog_id"] = str(cat_entry["id"])
            elif cat_id:
                item["catalog_id"] = cat_id
            registrations.append(item)
    return errors, _merge_registration_items(registrations)


def _word_tokens(text: Any) -> set[str]:
    return {word for word in _WORD_RE.findall(normalize_text(text)) if word not in _STOPWORDS}


def question_jaccard(first: Any, second: Any) -> float:
    a, b = _word_tokens(first), _word_tokens(second)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _near_duplicate_topics(
    document: Mapping[str, Any],
    proposal: Mapping[str, Any],
    *,
    threshold: float,
) -> list[tuple[str, float]]:
    """Same-line/scope topics whose question Jaccard similarity >= ``threshold``."""

    if threshold <= 0:
        return []
    key = _topic_key(proposal)
    reopens = str(proposal.get("reopens") or "").strip() or None
    question = proposal.get("question")
    matches: list[tuple[str, float]] = []
    for topic in document.get("topics") or []:
        if not isinstance(topic, Mapping) or _topic_key(topic) != key:
            continue
        if topic.get("status") == "rejected" and not judged_rejection(topic):
            continue
        if topic.get("topic_id") == reopens:
            continue
        if topic.get("status") in {"frozen", "rejected"} and _is_superseded(document, topic):
            continue
        sim = question_jaccard(question, topic.get("question"))
        if sim >= threshold:
            matches.append((str(topic["topic_id"]), round(sim, 3)))
    return matches


def _store_proposal(
    paths: WorkspacePaths, project: ProjectConfig, proposal: Mapping[str, Any], *, invalid: bool = False
) -> Path:
    digest = card_sha256(proposal)
    folder = _control_root(paths) / _token(project.project_id) / "cards"
    if invalid:
        folder = folder / "invalid"
    path = folder / f"topic-{digest[:16]}.json"
    if not path.is_file():
        atomic_write_json(path, dict(proposal))
    return path


def intake_proposal(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    project: ProjectConfig,
    raw_proposal: Any,
    *,
    decided_by: str,
    provider: str,
    source_task_id: str | None,
    receipt_digests: set[str] | None = None,
    proposer_task_id: str | None = None,
) -> dict[str, Any]:
    """Run mechanical checks #1-#5 and register a proposal as ``proposed`` or ``rejected``."""

    del receipt_digests  # No receipt hash gate under the simplified brief.
    ledger = open_topic_ledger(paths, settings.program)
    if not isinstance(raw_proposal, Mapping):
        body = {"invalid_proposal": raw_proposal, "domain": project.domain}
        meta = {"program_project_id": project.project_id, "source_task_id": source_task_id,
                "proposer_provider": provider}
        meta["card_path"] = str(_store_proposal(paths, project, body, invalid=True))
        decision = record_rejected_card(
            ledger, body, db=db, decided_by=decided_by,
            errors=["topic proposal must be a JSON object"], metadata=meta,
            reason=REJECTION_PROPOSAL_INVALID,
        )
        return {"topic_id": decision.topic_id, "status": "rejected",
                "reason": REJECTION_PROPOSAL_INVALID, "errors": ["topic proposal must be a JSON object"]}

    # Backward compatibility: adapt an in-flight legacy topic_card into a proposal.
    # Anything explicitly declaring openlabs.topic_proposal.v1 is validated as-is.
    is_legacy = (
        raw_proposal.get("schema_version") != TOPIC_PROPOSAL_SCHEMA
        and (
            not isinstance(raw_proposal.get("brief"), str)
            or not isinstance(raw_proposal.get("compute_estimate"), Mapping)
        )
    )
    proposal = proposal_from_legacy_card(raw_proposal) if is_legacy else dict(raw_proposal)
    proposal.pop("topic_id", None)
    proposal["domain"] = project.domain
    if project.research_line:
        proposal["research_line"] = project.research_line
    line = str(proposal.get("research_line") or "").strip() or None
    author = proposer_task_id or source_task_id
    metadata: dict[str, Any] = {
        "program_project_id": project.project_id,
        "source_task_id": source_task_id,
        "proposer_provider": provider,
        **({"proposer_task_id": author} if author else {}),
        **({"research_line": line} if line else {}),
        **({"queue_entry_id": str(proposal["queue_entry_id"]).strip()}
           if str(proposal.get("queue_entry_id") or "").strip() else {}),
        **({"cost_estimate": proposal["compute_estimate"]}
           if isinstance(proposal.get("compute_estimate"), Mapping) else {}),
    }

    def reject_now(reason: str, errors: list[str], extra_reg: list[dict[str, str]] | None = None) -> dict[str, Any]:
        meta = dict(metadata)
        meta["card_path"] = str(_store_proposal(paths, project, proposal, invalid=True))
        if extra_reg:
            meta["needs_registration"] = extra_reg
        decision = record_rejected_card(
            ledger, proposal, db=db, decided_by=decided_by, errors=errors,
            metadata=meta, reason=reason,
        )
        return {"topic_id": decision.topic_id, "status": "rejected", "reason": reason,
                "errors": errors, "needs_registration": extra_reg or []}

    # Check #1: minimal structural integrity (6 machine fields + non-empty brief <= 6000 chars).
    validation = validate_topic_proposal(proposal)
    if not validation.valid:
        return reject_now(REJECTION_PROPOSAL_INVALID, list(validation.errors))

    # Check #2 & #3: compute locations and data/storage ceiling.
    loc_problem = compute_location_problem(settings, proposal)
    if loc_problem is not None:
        return reject_now(REJECTION_BUDGET_EXCEEDED, [loc_problem])
    data_gb = float(proposal["compute_estimate"]["data_gb"])
    cap_gb = float(settings.program.supply.max_topic_data_gb)
    if data_gb > cap_gb:
        return reject_now(
            REJECTION_BUDGET_EXCEEDED,
            [f"compute_estimate.data_gb ({data_gb:g}) exceeds max_topic_data_gb ({cap_gb:g})"],
        )

    # Check #4: free-data hard guard & needs_registration extraction.
    data_errors, needs_reg = _check_free_data(paths, settings, proposal)
    if needs_reg:
        metadata["needs_registration"] = needs_reg
    if data_errors:
        return reject_now(REJECTION_DATA_RESTRICTED, data_errors, extra_reg=needs_reg)

    # Check #5: duplicate check (idempotent exact resubmission first, then queue_entry_id,
    # Jaccard near-dup, and fingerprint inside propose_topic).
    document = ledger.read()
    digest = card_sha256(proposal)
    existing = find_topic(document, f"topic-{digest[:16]}")
    if existing is not None and existing.get("card_sha256") == digest:
        return {
            "topic_id": str(existing["topic_id"]),
            "status": str(existing["status"]),
            "reason": (
                last_rejection_reason(existing) if existing.get("status") == "rejected" else ""
            ),
            "errors": [],
            "duplicate_of": [],
            "needs_registration": needs_reg,
        }
    reopens = str(proposal.get("reopens") or "").strip() or None
    q_id = str(proposal.get("queue_entry_id") or "").strip()
    if q_id and line:
        occupied = ledger_queue_entries(document, line).get(q_id.casefold())
        if occupied is not None and occupied["topic_id"] != reopens:
            return reject_now(
                REJECTION_DUPLICATE_TOPIC,
                [f"queue_entry_id {q_id} is already occupied by {occupied['topic_id']} ({occupied['status']})"],
                extra_reg=needs_reg,
            )
    near_dups = _near_duplicate_topics(
        document, proposal, threshold=float(settings.program.supply.dedup_similarity)
    )
    if near_dups:
        detail = ", ".join(f"{tid} (jaccard={sim})" for tid, sim in near_dups[:5])
        return reject_now(
            REJECTION_DUPLICATE_TOPIC,
            [f"question near-duplicate of existing topic(s): {detail}"],
            extra_reg=needs_reg,
        )

    metadata["card_path"] = str(_store_proposal(paths, project, proposal))
    try:
        decision = propose_topic(ledger, proposal, db=db, decided_by=decided_by, metadata=metadata)
    except TopicLedgerError as exc:
        return reject_now(REJECTION_PROPOSAL_INVALID, [str(exc)], extra_reg=needs_reg)
    return {
        "topic_id": decision.topic_id,
        "status": decision.status,
        "reason": decision.reason,
        "errors": [],
        "duplicate_of": list(decision.duplicate_of),
        "needs_registration": needs_reg,
    }


# Alias retained for CLI / existing callers.
intake_card = intake_proposal


def register_scout_results(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
) -> list[dict[str, Any]]:
    """Register proposals (and in-flight legacy ``topic_cards``) from succeeded scouts."""

    outcomes: list[dict[str, Any]] = []
    done = db.meta_items(SCOUT_REGISTERED_PREFIX)
    for task in _program_tasks(
        db, statuses=("succeeded",), where="AND task_type=?", parameters=(SCOUT_TASK_TYPE,)
    ):
        task_id = str(task["task_id"])
        if task_id in done:
            continue
        campaign = db.campaign(str(task["campaign_id"])) or {}
        project = campaign_project(campaign)
        if project is None or not project.program:
            continue
        result_path = Path(str(task.get("result_path") or ""))
        expected = str(task.get("result_sha256") or "")
        if not result_path.is_file() or not expected or sha256_file(result_path) != expected:
            db.update_meta(
                {SCOUT_REGISTERED_PREFIX + task_id: utc_now()},
                events=[("program", project.project_id, "topic_cards_unverifiable",
                         {"task_id": task_id, "result_path": str(result_path)})],
            )
            outcomes.append({"source_task_id": task_id, "topic_id": None, "status": "rejected",
                             "reason": "scout_result_not_hash_bound", "errors": []})
            continue
        payload = _read_object(result_path)
        proposals = payload.get("topic_proposals")
        legacy_cards = payload.get("topic_cards")
        items: list[Any] = []
        if isinstance(proposals, list):
            items.extend(proposals)
        if isinstance(legacy_cards, list):
            items.extend(legacy_cards)
        provider = budget_control.family_of(settings, task.get("runner"))
        task_outcomes = [
            {
                "source_task_id": task_id,
                **intake_proposal(
                    db, paths, settings, project, item, decided_by=task_id,
                    provider=provider, source_task_id=task_id,
                ),
            }
            for item in items
        ]
        outcomes.extend(task_outcomes)
        db.update_meta(
            {SCOUT_REGISTERED_PREFIX + task_id: utc_now()},
            events=[
                (
                    "program",
                    project.project_id,
                    "topic_cards_registered",
                    {"task_id": task_id, "cards": len(items), "outcomes": task_outcomes},
                )
            ],
        )
    return outcomes


def submit_topic_card(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    project_path: Path,
    card: Mapping[str, Any],
    *,
    submitted_by: str,
) -> dict[str, Any]:
    """Register a human-written topic proposal (or legacy card) for independent review."""

    project = load_project(project_path)
    if not project.program:
        raise ValueError("proposals are submitted to a research-program project (program: true)")
    return intake_proposal(
        db, paths, settings, project, card, decided_by=f"manual:{submitted_by}",
        provider=HUMAN_PROVIDER, source_task_id=None,
    )


# --------------------------------------------------------------------------- independent review


def _source_id(topic: Mapping[str, Any]) -> str:
    return str(topic.get("source_task_id") or f"manual-card:{topic['topic_id']}")


def _proposal_time(topic: Mapping[str, Any]) -> str:
    history = topic.get("history") or []
    return str(history[0].get("at") or "") if history else ""


def card_author(
    topic: Mapping[str, Any], document: Mapping[str, Any] | None = None
) -> tuple[str, str | None]:
    """``(provider, task_id)`` of the model that wrote a proposal/card (keeps legacy repair_of)."""

    current: Mapping[str, Any] = topic
    seen: set[str] = set()
    while (
        not current.get("proposer_task_id") and current.get("repair_of")
        and document is not None and str(current["repair_of"]) not in seen
    ):
        seen.add(str(current["repair_of"]))
        original = find_topic(document, str(current["repair_of"]))
        if original is None:
            break
        current = original
    provider = str(current.get("proposer_provider") or HUMAN_PROVIDER)
    task_id = str(current.get("proposer_task_id") or current.get("source_task_id") or "")
    return provider, task_id or None


def _proposer_models_fields(
    db: FactoryDB, settings: FactorySettings, author_task_ids: list[str | None]
) -> dict[str, Any]:
    models: set[str] = set()
    complete = True
    for author in author_task_ids:
        task = db.task(author) if author else None
        spec = settings.runners.get(str((task or {}).get("runner") or ""))
        if spec is None or not spec.model:
            complete = False
            continue
        models.add(spec.model)
    return {
        "producer_model": next(iter(models)) if complete and len(models) == 1 else None,
        "producer_models": sorted(models),
    }


def _attempt_task_id(attempt: Any) -> str:
    if isinstance(attempt, Mapping):
        return str(attempt.get("task_id") or "")
    return str(attempt or "")


def _review_objective(project: ProjectConfig, count: int) -> str:
    scope = (
        f"research line `{project.research_line}` ({project.domain})"
        if project.research_line
        else f"domain `{project.domain}` ({project.project_id})"
    )
    return (
        f"Act as the independent cross-family reviewer for {count} topic proposal(s) in {scope} "
        f"following the `{ADMISSION_SKILL}` skill. Read each one-page brief in the review packet "
        "(`topic_proposals`), the `ledger_snapshot`, and any `line_tools` / `research_lines` "
        "context. Judge significance, novelty (verify closest prior work yourself) and "
        "computational/data feasibility holistically — do NOT run experiments (the topic owner "
        "runs the kill test as Milestone 1). Return one entry per proposal in `reviews[]` with "
        "`topic_id`, `verdict` (`\"go\"` or `\"no_go\"`), `rationale` (3-6 crisp sentences), "
        "optional `likely_band` (`nc|zone_1|zone_2|zones_3_4`, informational only), and optional "
        "`needs_registration` (`[{source, registration}]`). Leave `candidate_branches: []`. "
        "Do not start the research."
    )


def schedule_topic_admission(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    campaign: Mapping[str, Any],
    *,
    epoch: int,
) -> ReviewSchedule:
    """Queue one cross-family independent review of this project's proposed topics."""

    if not settings.program.enabled:
        return ReviewSchedule(reason="program_disabled")
    if settings.program.stops(SUPPLY_STAGE):
        return ReviewSchedule(reason=POLISH_MODE_REASON)
    if not budget_control.routing_enabled(settings):
        return ReviewSchedule(reason="admission_requires_provider_routing")
    if compute_backlogged(settings):
        return ReviewSchedule(reason=COMPUTE_BACKLOG_REASON)
    campaign_id = str(campaign["campaign_id"])
    project = load_project(str(campaign["project_config_path"]))
    if settings.program.stops(SUPPLY_STAGE, project.research_line):
        return ReviewSchedule(reason=POLISH_MODE_REASON)
    ledger = open_topic_ledger(paths, settings.program)
    snapshot_document = ledger.read()
    proposed = [
        topic
        for topic in topics_by_status(snapshot_document, "proposed")
        if topic.get("program_project_id") == project.project_id
    ]
    blocked_lines = lines_not_ready(
        paths, settings, [topic.get("research_line") for topic in proposed]
    )
    waiting_for_line = [
        topic for topic in proposed if str(topic.get("research_line") or "") in blocked_lines
    ]
    proposed = [topic for topic in proposed if topic not in waiting_for_line]

    in_flight = {
        str(task["task_id"]): task
        for task in _program_tasks(
            db, statuses=IN_FLIGHT_STATUSES, where="AND routing_reason=?",
            parameters=(ADMISSION_ROUTING_REASON,),
        )
    }
    pending: list[dict[str, Any]] = []
    reviewing = 0
    for topic in proposed:
        attempts = list(topic.get("admission_attempts") or [])
        if attempts and _attempt_task_id(attempts[-1]) in in_flight:
            reviewing += 1
            continue
        if len(attempts) >= MAX_REVIEW_ATTEMPTS:
            reject_topic(
                ledger, str(topic["topic_id"]), db=db, reason=REJECTION_REVIEW_UNDECIDED,
                decided_by=f"program:{campaign_id}",
            )
            continue
        pending.append(topic)
    if not pending:
        return ReviewSchedule(
            reason="admission_batches_in_flight" if reviewing
            else "research_line_environment_not_ready" if waiting_for_line
            else "awaiting_topic_cards"
        )
    cap = settings.program.supply.max_concurrent_reviews
    if len(in_flight) >= cap:
        return ReviewSchedule(reason="max_concurrent_reviews")

    slots = slot_status(
        snapshot_document, settings.program, parked_program_projects(paths),
        paused_topic_campaigns(db),
    )
    reservations = Counter(
        _topic_key(topic) for topic in _proposed_pool(snapshot_document)
        if (attempts := topic.get("admission_attempts"))
        and _attempt_task_id(attempts[-1]) in in_flight
    )
    pending = [
        topic for topic in pending
        if (free := slots.line_free_slots(topic.get("research_line"))) is None
        or free > reservations[_topic_key(topic)]
    ]
    if not pending:
        return ReviewSchedule(reason=LINE_SLOTS_FULL_REASON)

    pending.sort(key=lambda item: (_proposal_time(item), str(item["topic_id"])))
    key = _topic_key(pending[0])
    line_free = slots.line_free_slots(pending[0].get("research_line"))
    pending = [topic for topic in pending if _topic_key(topic) == key]
    authors = {str(topic["topic_id"]): card_author(topic, snapshot_document) for topic in pending}
    provider = authors[str(pending[0]["topic_id"])][0]
    batch_size = max(1, int(workstream_policy(campaign).get("review_batch_size") or 8))
    if line_free is not None:
        batch_size = min(batch_size, line_free - reservations[key])
    batch = [
        topic for topic in pending if authors[str(topic["topic_id"])][0] == provider
    ][:batch_size]

    entries: list[dict[str, Any]] = []
    for topic in batch:
        card_path = Path(str(topic.get("card_path") or ""))
        if not card_path.is_file():
            raise ValueError(f"topic {topic['topic_id']} proposal file is missing: {card_path}")
        raw_card = _read_object(card_path)
        if card_sha256(raw_card) != topic.get("card_sha256"):
            raise ValueError(f"topic {topic['topic_id']} proposal file differs from the ledger")
        legacy = not (
            isinstance(raw_card.get("brief"), str)
            and isinstance(raw_card.get("compute_estimate"), Mapping)
        )
        proposal = proposal_from_legacy_card(raw_card) if legacy else raw_card
        entries.append(
            {
                "topic_id": topic["topic_id"],
                "source_result_id": _source_id(topic),
                "card_sha256": topic["card_sha256"],
                "proposer_provider": provider,
                "proposal": proposal,
                "card": proposal,
                "legacy_card": legacy,
                **({"needs_registration": topic["needs_registration"]}
                   if topic.get("needs_registration") else {}),
            }
        )
    line_ids = sorted({
        str(entry["proposal"].get("research_line"))
        for entry in entries if str(entry["proposal"].get("research_line") or "").strip()
    })
    lines_doc = research_lines_document(paths, settings) if line_ids else None
    topic_ids = [str(entry["topic_id"]) for entry in entries]
    result_ids = sorted({str(entry["source_result_id"]) for entry in entries})
    digest = hashlib.sha256("\0".join(topic_ids + result_ids).encode()).hexdigest()
    latest = db.latest_task(campaign_id)
    task_id = _task_id(campaign_id, epoch, digest + (str(latest.get("task_id")) if latest else ""))
    if db.task(task_id) is not None:
        return ReviewSchedule(reason="review_already_scheduled")
    exclude = None if provider == HUMAN_PROVIDER else provider
    packet_path = _review_control_root(paths, campaign) / "review-packets" / f"{digest[:24]}.json"
    tools_by_line = {
        line: tools for line in line_ids
        if (tools := line_resources(line_entry(lines_doc, line)))
    }
    packet = _signed(
        {
            "schema_version": REVIEW_PACKET_SCHEMA,
            "program": True,
            "project_id": project.project_id,
            "domain": project.domain,
            "review_campaign_id": campaign_id,
            "cursor_path": str(_review_cursor_path(paths, campaign)),
            "result_ids": result_ids,
            "results": [],
            "topic_proposals": entries,
            "topic_cards": entries,
            "proposer_provider": provider,
            "exclude_provider": exclude,
            **_proposer_models_fields(
                db, settings, [authors[str(topic["topic_id"])][1] for topic in batch]
            ),
            **(
                {"research_lines": {line: line_summary(lines_doc, line) for line in line_ids}}
                if line_ids else {}
            ),
            **({"line_tools": tools_by_line} if tools_by_line else {}),
            "ledger_snapshot": _ledger_snapshot(
                ledger.read(), line=line_ids[0] if len(line_ids) == 1 else None
            ),
            "read_resources": program_read_resources(paths, settings, ledger),
            **asset_library.packet_fields(
                paths, settings, domains=[project.domain],
                data_sources=[
                    source for entry in entries
                    for source in data_source_identifiers(entry["proposal"].get("data_sources"))
                ],
            ),
            "created_at": utc_now(),
        }
    )
    atomic_write_json(packet_path, packet)
    db.enqueue_task(
        task_id=task_id,
        campaign_id=campaign_id,
        domain=project.domain,
        task_type="portfolio_review",
        objective=_review_objective(project, len(entries)),
        input_path=str(packet_path),
        skill_path=ADMISSION_SKILL,
        runner=dispatch_runner(
            settings, "portfolio_review", ADMISSION_ROUTING_REASON, "frontier"
        ),
        routing_reason=ADMISSION_ROUTING_REASON,
        agent_role="reviewer",
        session_mode="fresh",
        priority=int(campaign.get("priority") or 0),
        max_attempts=settings.max_attempts,
        max_wall_seconds=settings.max_task_wall_seconds,
        exclude_provider=exclude,
        **default_task_resources(settings).to_dict(),
    )
    for topic_id in topic_ids:
        note_admission_attempt(ledger, topic_id, task_id)
    db.record_event_once(
        "program",
        project.project_id,
        "topic_admission_scheduled",
        {"task_id": task_id, "topic_ids": topic_ids, "exclude_provider": exclude},
        event_key=task_id,
    )
    return ReviewSchedule(task_id=task_id)


def parallel_admission_room(
    db: FactoryDB,
    settings: FactorySettings,
    campaign: Mapping[str, Any],
) -> bool:
    if not settings.program.enabled:
        return False
    if workstream_policy(campaign).get("continuation") != "review_on_new_results":
        return False
    project = campaign_project(campaign)
    if project is None or not project.program:
        return False
    campaign_id = str(campaign.get("campaign_id") or "")
    flights = _program_tasks(
        db, statuses=IN_FLIGHT_STATUSES, where="AND campaign_id=?", parameters=(campaign_id,)
    )
    return bool(flights) and all(
        task.get("routing_reason") == ADMISSION_ROUTING_REASON for task in flights
    )


def record_admission_deferral(
    db: FactoryDB,
    task: Mapping[str, Any],
    detail: Mapping[str, Any],
) -> list[str]:
    if str(task.get("routing_reason") or "") != ADMISSION_ROUTING_REASON:
        return []
    packet_path = Path(str(task.get("input_path") or ""))
    try:
        packet = _verified_review_packet(packet_path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return []
    entries = packet.get("topic_proposals") or packet.get("topic_cards") or []
    topic_ids = [
        str(entry.get("topic_id")) for entry in entries if isinstance(entry, Mapping)
    ]
    for topic_id in topic_ids:
        db.record_event_once(
            "topic",
            topic_id,
            "topic_admission_waiting",
            {
                "task_id": task.get("task_id"),
                "reason": detail.get("reason"),
                "excluded_provider": detail.get("excluded_provider"),
                "tier": detail.get("tier"),
            },
            event_key=":".join(
                (str(task.get("task_id")), str(detail.get("reason")),
                 f"attempt{int(task.get('attempt') or 0)}")
            ),
        )
    return topic_ids


def _admission_record_path(paths: WorkspacePaths, topic_id: str) -> Path:
    return _control_root(paths) / "admissions" / f"{_token(topic_id)}.json"


def _write_admission_record(
    paths: WorkspacePaths,
    topic_id: str,
    *,
    project: ProjectConfig,
    source_campaign: Mapping[str, Any],
    review_task_id: str,
    result_path: Path,
    entry: Mapping[str, Any],
    admission: Mapping[str, Any],
    proposal: Mapping[str, Any],
    needs_registration: list[dict[str, str]],
) -> Path:
    record_path = _admission_record_path(paths, topic_id)
    if record_path.is_file():
        existing = _read_object(record_path)
        if existing.get("review_task_id") == review_task_id:
            return record_path
    atomic_write_json(
        record_path,
        {
            "schema_version": ADMISSION_RECORD_SCHEMA,
            "topic_id": topic_id,
            "project_path": str(project.path),
            "project_id": project.project_id,
            "source_campaign_id": str(source_campaign.get("campaign_id")),
            "review_task_id": review_task_id,
            "result_path": str(result_path),
            "source_result_id": str(entry.get("source_result_id")),
            "admission": dict(admission),
            "proposal": dict(proposal),
            "card_sha256": entry.get("card_sha256"),
            "needs_registration": list(needs_registration),
            "created_at": utc_now(),
        },
    )
    return record_path


def _decided_by(topic: Mapping[str, Any], review_task_id: str) -> bool:
    return any(
        entry.get("decided_by") == review_task_id and entry.get("to") in {"admitted", "rejected"}
        for entry in topic.get("history") or []
    )


def materialize_admission_decisions(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    source_campaign: Mapping[str, Any],
    task: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    result_path: Path,
    project: ProjectConfig,
) -> CandidateSpawn:
    """Apply one independent topic review (``reviews[]``), then materialize waiting topics."""

    if not settings.program.enabled:
        raise ValueError("research program is disabled; defer admission handling")
    packet_path = Path(str(task.get("input_path") or "")).resolve()
    if not packet_path.is_file():
        raise ValueError("admission reviewer has no immutable review packet")
    packet = _verified_review_packet(packet_path)
    if packet.get("program") is not True:
        raise ValueError("admission result does not come from a program review packet")
    raw_entries = packet.get("topic_proposals") or packet.get("topic_cards") or []
    entries = {
        str(entry.get("topic_id")): entry
        for entry in raw_entries
        if isinstance(entry, Mapping)
    }
    ledger = open_topic_ledger(paths, settings.program)
    review_task_id = str(task.get("task_id") or "")
    evidence = [{"path": str(result_path), "sha256": sha256_file(result_path)}]
    decisions: list[dict[str, Any]] = []
    decided: set[str] = set()
    reviews = payload.get("reviews")
    for review in reviews if isinstance(reviews, list) else []:
        if not isinstance(review, Mapping):
            continue
        topic_id = str(review.get("topic_id") or "").strip()

        def note(outcome: str, reason: str, _topic: str = topic_id) -> None:
            decisions.append({"topic_id": _topic, "outcome": outcome, "reason": reason})

        entry = entries.get(topic_id)
        if entry is None:
            note("ignored", "topic_not_in_review_packet")
            continue
        validation = validate_topic_review(review)
        if not validation.valid:
            note("ignored", "review_output_invalid: " + "; ".join(validation.errors))
            continue
        topic = find_topic(ledger.read(), topic_id)
        if topic is None or topic.get("card_sha256") != entry.get("card_sha256"):
            note("ignored", "card_hash_mismatch")
            continue
        if topic_id in decided:
            note("ignored", "duplicate_decision")
            continue
        decided.add(topic_id)

        status = str(topic.get("status"))
        if status != "proposed" and not _decided_by(topic, review_task_id):
            note("unchanged", f"topic_already_{status}")
            continue
        proposal = entry.get("proposal") or entry.get("card") or {}
        if not isinstance(proposal, Mapping):
            proposal = {}
        verdict = str(review["verdict"]).strip()
        rationale = str(review["rationale"]).strip()
        likely_band = str(review.get("likely_band") or "").strip() or None
        merged_reg = _merge_registration_items(
            topic.get("needs_registration"),
            entry.get("needs_registration"),
            review.get("needs_registration"),
        )
        # likely_band is informational only — NEVER a gate!
        summary: dict[str, Any] = {
            "verdict": verdict,
            "rationale": rationale,
            "review_task_id": review_task_id,
            **({"likely_band": likely_band} if likely_band else {}),
            **({"needs_registration": merged_reg} if merged_reg else {}),
        }
        if verdict == "go":
            loc_problem = compute_location_problem(settings, proposal)
            if loc_problem is not None:
                summary["compute_location_error"] = loc_problem
                if status == "proposed":
                    reject_topic(
                        ledger, topic_id, db=db, reason=REJECTION_BUDGET_EXCEEDED,
                        decided_by=review_task_id, evidence=evidence, admission=summary,
                        needs_registration=merged_reg or None,
                    )
                note("rejected", REJECTION_BUDGET_EXCEEDED)
                continue
            if status == "proposed":
                _write_admission_record(
                    paths, topic_id, project=project, source_campaign=source_campaign,
                    review_task_id=review_task_id, result_path=result_path, entry=entry,
                    admission=summary, proposal=proposal, needs_registration=merged_reg,
                )
                admit_topic(
                    ledger, topic_id, db=db, settings=settings.program,
                    decided_by=review_task_id, admission_task_id=review_task_id,
                    preregistration_sha256=None, evidence=evidence,
                    admission=summary, needs_registration=merged_reg or None,
                    queue_when_full=True,
                )
            note("admitted", likely_band or "go")
        else:
            if status == "proposed":
                reject_topic(
                    ledger, topic_id, db=db, reason=REJECTION_REVIEW_NO_GO,
                    decided_by=review_task_id, evidence=evidence, admission=summary,
                    needs_registration=merged_reg or None,
                )
            note("rejected", REJECTION_REVIEW_NO_GO)

    for topic_id in entries:
        if topic_id not in decided:
            decisions.append({
                "topic_id": topic_id,
                "outcome": "undecided",
                "reason": "no_valid_decision_in_review",
            })
    spawned = materialize_waiting_topics(db, paths, settings)
    return CandidateSpawn(spawned.campaign_ids, spawned.task_ids, tuple(decisions))


# --------------------------------------------------------------------------- materialization


def _research_state(
    record: Mapping[str, Any],
    topic: Mapping[str, Any],
    *,
    record_path: Path | None = None,
    agent_seconds_budget: int | None = None,
) -> dict[str, Any]:
    proposal = record.get("proposal") if isinstance(record.get("proposal"), Mapping) else None
    card = record.get("card") if isinstance(record.get("card"), Mapping) else {}
    admission = record.get("admission") if isinstance(record.get("admission"), Mapping) else {}
    extra: dict[str, Any] = {}
    if record_path is not None and record_path.is_file():
        extra["admission_record"] = {"path": str(record_path), "sha256": sha256_file(record_path)}
    if agent_seconds_budget is not None:
        extra["agent_seconds_budget"] = int(agent_seconds_budget)

    # New simplified proposal record (schema v3).
    if proposal is not None:
        line = proposal.get("research_line") or topic.get("research_line")
        q_id = proposal.get("queue_entry_id") or topic.get("queue_entry_id")
        return {
            **extra,
            "program_role": "research",
            "topic_id": topic["topic_id"],
            "question": proposal.get("question") or topic.get("question"),
            "brief": proposal.get("brief"),
            "data_sources": proposal.get("data_sources") or [],
            "needs_registration": record.get("needs_registration") or topic.get("needs_registration") or [],
            "compute_estimate": proposal.get("compute_estimate"),
            "review_rationale": admission.get("rationale"),
            "likely_band": admission.get("likely_band"),
            "milestone": "kill_test",
            "admission_task_id": record.get("review_task_id"),
            "card_sha256": record.get("card_sha256"),
            **({"research_line": line} if line else {}),
            **({"queue_entry_id": q_id} if q_id else {}),
        }

    # Backward compatibility for legacy v1/v2 admission records already on disk.
    venues = card.get("venues") if isinstance(card.get("venues"), Mapping) else {}
    conditions = admission_conditions(admission)
    if conditions:
        extra["admission_conditions"] = conditions
    return {
        **extra,
        "program_role": "research",
        "topic_id": topic["topic_id"],
        "target_tier": admission.get("target_tier"),
        "target_stage": record.get("target_stage"),
        "routine_fallback": venues.get("routine"),
        "escalation_target": venues.get("escalation"),
        "cost_budget": card.get("cost_estimate"),
        **({"preregistration": dict(record["preregistration"])}
           if isinstance(record.get("preregistration"), Mapping) else {}),
        "admission_task_id": record.get("review_task_id"),
        "card_sha256": record.get("card_sha256"),
        "question": card.get("question") or topic.get("question"),
        "milestone": "kill_test",
        **({
            key: card.get(key)
            for key in ("research_line", "feasibility_precheck")
            if card.get(key) is not None
        }),
    }


def materialize_waiting_topics(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
) -> CandidateSpawn:
    """Turn admitted topics into campaigns, oldest admission first, while slots allow."""

    campaign_ids: list[str] = []
    task_ids: list[str] = []
    if settings.program.stops(RESEARCH_STAGE):
        return CandidateSpawn(campaign_ids=(), task_ids=())
    if compute_backlogged(settings):
        return CandidateSpawn(campaign_ids=(), task_ids=())
    ledger = open_topic_ledger(paths, settings.program)
    parked = parked_program_projects(paths)
    paused = paused_topic_campaigns(db)
    skipped: set[str] = set()
    while True:
        document = ledger.read()
        status = slot_status(document, settings.program, parked, paused)
        if not status.can_materialize:
            break
        queue = [
            topic for topic in waiting_admitted(document, admission_sequence(db))
            if str(topic["topic_id"]) not in skipped
            and str(topic.get("program_project_id") or "") not in parked
            and not settings.program.stops(RESEARCH_STAGE, topic.get("research_line"))
            and status.line_can_materialize(topic.get("research_line"))
        ]
        if not queue:
            break
        topic = queue[0]
        topic_id = str(topic["topic_id"])
        record_path = _admission_record_path(paths, topic_id)
        if not record_path.is_file():
            skipped.add(topic_id)
            continue
        record = _read_object(record_path)
        project = load_project(str(record["project_path"]))
        proposal = record.get("proposal") if isinstance(record.get("proposal"), Mapping) else {}
        card = record.get("card") if isinstance(record.get("card"), Mapping) else {}
        estimate = proposal.get("compute_estimate") or card.get("cost_estimate")
        budget = topic_budget_seconds(estimate, settings)
        source_campaign = db.campaign(str(record.get("source_campaign_id") or "")) or {"priority": 0}
        branch = dict(record.get("branch") or {})
        branch["candidate_id"] = topic_id
        branch.setdefault("title", str(topic.get("question") or topic_id))
        branch["objective"] = (
            f"Execute admitted topic `{topic_id}`: {topic.get('question') or ''}. "
            "Read the proposal brief and review rationale in research_state.json. "
            "Run Milestone 1 (Kill Test: sections 5 & 6 of the brief) first on real data; "
            "if it fails, freeze immediately with one of the four freeze classes "
            "(data_access, method_capability, negative_result, resources_exhausted) and evidence; "
            "if it passes, advance to solving and complete the full study."
        ).strip()
        line = str(topic.get("research_line") or "")
        entry = (line_entry(research_lines_document(paths, settings), line) or {}) if line else {}
        paper_profile = (
            {"field": entry["field"], "line_short_name": entry["line_short_name"]}
            if entry.get("field") else None
        )
        campaign_id, first_task = materialize_candidate(
            db,
            paths,
            settings,
            project=project,
            source_campaign=source_campaign,
            branch=branch,
            source_result_ids={str(record.get("source_result_id") or "")} - {""},
            review_task_id=str(record.get("review_task_id") or ""),
            result_path=Path(str(record.get("result_path") or "")),
            extra_state=_research_state(
                record, topic, record_path=record_path, agent_seconds_budget=budget
            ),
            extra_policy={
                "topic_id": topic_id,
                "program_research": True,
                "max_agent_seconds": budget,
                **({"paper_profile": paper_profile} if paper_profile else {}),
            },
            max_agent_seconds=budget,
        )
        activate_topic(
            ledger, topic_id, db=db, campaign_id=campaign_id,
            decided_by=str(record.get("review_task_id") or "program"),
        )
        campaign_ids.append(campaign_id)
        if first_task is not None:
            task_ids.append(first_task)
    return CandidateSpawn(tuple(campaign_ids), tuple(task_ids))


# --------------------------------------------------------------------------- metrics & reports


def workstream_admitted(document: Mapping[str, Any], workstream_id: str) -> bool:
    topic = topic_for_campaign(document, workstream_id)
    return bool(topic and topic.get("status") in ADMITTED_WORK_STATUSES)


def compute_backlogged(settings: FactorySettings) -> bool:
    backlog = compute_backlog(settings)
    return bool(backlog and backlog["backlogged"])


def collect_needs_registration(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Aggregate registration-gated free datasets reported across proposals and reviews."""

    by_source: dict[str, dict[str, Any]] = {}
    for topic in document.get("topics") or []:
        if not isinstance(topic, Mapping):
            continue
        topic_id = str(topic.get("topic_id") or "")
        line = str(topic.get("research_line") or "")
        admission = topic.get("admission") if isinstance(topic.get("admission"), Mapping) else {}
        items = _merge_registration_items(
            topic.get("needs_registration"),
            admission.get("needs_registration"),
        )
        for item in items:
            key = item["source"].casefold()
            entry = by_source.setdefault(
                key,
                {
                    "source": item["source"],
                    "registration": item.get("registration", ""),
                    **({"catalog_id": item["catalog_id"]} if item.get("catalog_id") else {}),
                    "lines": [],
                    "topic_ids": [],
                },
            )
            if not entry["registration"] and item.get("registration"):
                entry["registration"] = item["registration"]
            if line and line not in entry["lines"]:
                entry["lines"].append(line)
            if topic_id and topic_id not in entry["topic_ids"]:
                entry["topic_ids"].append(topic_id)
    return sorted(by_source.values(), key=lambda row: row["source"].casefold())


def supply_metrics(
    document: Mapping[str, Any],
    settings: FactorySettings,
    *,
    db: FactoryDB | None = None,
    paths: WorkspacePaths | None = None,
    moment: datetime | None = None,
) -> dict[str, Any]:
    """Core supply-health metrics per line (admitted->ready, cost/admit, review pass, freezes)."""

    by_line: dict[str, dict[str, Any]] = {}

    def bucket(name: str) -> dict[str, Any]:
        return by_line.setdefault(
            name,
            {
                "total": 0,
                "proposed": 0,
                "admitted_ever": 0,
                "ready_ever": 0,
                "frozen": 0,
                "rejected": 0,
                "review_no_go": 0,
                "queue_proposals": 0,
                "rejection_reasons": Counter(),
                "freeze_categories": Counter(),
            },
        )

    for line in settings.program.research_lines:
        bucket(line)

    for topic in document.get("topics") or []:
        if not isinstance(topic, Mapping):
            continue
        line = str(topic.get("research_line") or f"domain/{topic.get('domain') or 'unknown'}")
        row = bucket(line)
        status = str(topic.get("status") or "")
        history = [e for e in (topic.get("history") or []) if isinstance(e, Mapping)]
        visited = {status, *(str(e.get("to") or "") for e in history)}
        row["total"] += 1
        if status == "proposed":
            row["proposed"] += 1
        if "admitted" in visited:
            row["admitted_ever"] += 1
        if visited & {"ready_queue", "submitted"}:
            row["ready_ever"] += 1
        if status == "frozen":
            row["frozen"] += 1
            cat = (
                topic.get("freeze_reason_category")
                or freeze_reason_category(topic.get("freeze_reason_class"))
                or "other"
            )
            row["freeze_categories"][str(cat)] += 1
        if status == "rejected":
            row["rejected"] += 1
            reason = last_rejection_reason(topic) or "unknown"
            row["rejection_reasons"][reason] += 1
            if reason in {REJECTION_REVIEW_NO_GO, "admission_rejected"}:
                row["review_no_go"] += 1
        if topic.get("queue_entry_id"):
            row["queue_proposals"] += 1

    spend_7d = (
        weekly_supply_spend(db, paths, settings, program_projects(paths), moment=moment)
        if db is not None and paths is not None
        else {}
    )
    formatted_lines: dict[str, dict[str, Any]] = {}
    for line, row in sorted(by_line.items()):
        admitted = row["admitted_ever"]
        no_go = row["review_no_go"]
        ready = row["ready_ever"]
        frozen = row["frozen"]
        spend = spend_7d.get(line)
        formatted_lines[line] = {
            "total": row["total"],
            "proposed": row["proposed"],
            "admitted_ever": admitted,
            "ready_ever": ready,
            "frozen": frozen,
            "rejected": row["rejected"],
            "review_pass_rate": (
                round(admitted / (admitted + no_go), 3) if (admitted + no_go) else None
            ),
            "admitted_to_ready_rate": (
                round(ready / (ready + frozen), 3) if (ready + frozen) else None
            ),
            "queue_proposals": row["queue_proposals"],
            "queue_usage_rate": (
                round(row["queue_proposals"] / row["total"], 3) if row["total"] else None
            ),
            "freeze_categories": dict(sorted(row["freeze_categories"].items())),
            "rejection_reasons": dict(sorted(row["rejection_reasons"].items())),
            **(
                {
                    "supply_spend_7d_usd": spend["usd"],
                    "supply_spend_7d_agent_hours": spend["agent_hours"],
                    "supply_attempts_7d": spend["attempts"],
                }
                if spend is not None
                else {}
            ),
        }
    return {
        "lines": formatted_lines,
        "needs_registration": collect_needs_registration(document),
    }


def backfill_grandfathered(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    write: bool = False,
) -> dict[str, Any]:
    """Register existing active research campaigns as ``active`` grandfathered topics."""

    ledger = open_topic_ledger(paths, settings.program)
    document = ledger.read()
    planned: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for campaign in db.campaigns():
        campaign_id = str(campaign["campaign_id"])
        if str(campaign.get("status") or "") != "active":
            continue
        if topic_for_campaign(document, campaign_id) is not None:
            skipped.append({"campaign_id": campaign_id, "reason": "already_in_ledger"})
            continue
        policy = workstream_policy(campaign)
        project = campaign_project(campaign)
        if project is not None and project.program and not policy.get("dynamic"):
            skipped.append({"campaign_id": campaign_id, "reason": "program_control_workstream"})
            continue
        if (
            policy.get("default_agent_role") == "reviewer"
            or policy.get("continuation") == "review_on_new_results"
        ):
            skipped.append({"campaign_id": campaign_id, "reason": "reviewer_workstream"})
            continue
        title = str(campaign.get("title") or campaign_id)
        digest = hashlib.sha256(campaign_id.encode()).hexdigest()
        planned.append(
            {
                "topic_id": f"grandfathered-{digest[:16]}",
                "campaign_id": campaign_id,
                "domain": str(campaign.get("domain") or ""),
                "question": title,
            }
        )
    registered: list[str] = []
    if write:
        for item in planned:
            card = {
                "topic_id": item["topic_id"],
                "domain": item["domain"],
                "question": item["question"],
                "data_sources": [f"campaign:{item['campaign_id']}"],
                "grandfathered": True,
            }
            decision = propose_topic(
                ledger, card, db=db, decided_by="backfill",
                metadata={"admission": "grandfathered"},
            )
            if decision.status == "rejected":
                continue
            admit_topic(
                ledger, item["topic_id"], db=db, settings=settings.program,
                decided_by="backfill", admission_task_id="backfill",
                admission="grandfathered", queue_when_full=True,
            )
            activate_topic(
                ledger, item["topic_id"], db=db, campaign_id=item["campaign_id"],
                decided_by="backfill",
            )
            registered.append(item["topic_id"])
    return {
        "schema_version": "openlabs.program_backfill.v1",
        "dry_run": not write,
        "ledger_path": str(ledger.path),
        "planned": planned,
        "registered": registered,
        "skipped": skipped,
    }


def report_scheduling_counts(
    db: FactoryDB, paths: WorkspacePaths, settings: FactorySettings, report: Any,
) -> None:
    lines: dict[str, dict[str, Any]] = report.program.get("by_line", {})
    legacy: dict[str, dict[str, int]] = {}

    def bucket(key: str) -> dict[str, Any]:
        if key.startswith("domain/"):
            return legacy.setdefault(key.removeprefix("domain/") or "unknown", {})
        return lines.setdefault(key, {})

    document = open_topic_ledger(paths, settings.program).read()
    for line in settings.program.research_lines:
        bucket(line)
    for topic in document.get("topics") or []:
        counts = bucket(_topic_key(topic))
        status = str(topic["status"])
        counts[status] = counts.get(status, 0) + 1
    for task in _program_tasks(
        db, statuses=IN_FLIGHT_STATUSES,
        where="AND (task_type=? OR routing_reason=?)",
        parameters=(SCOUT_TASK_TYPE, ADMISSION_ROUTING_REASON),
    ):
        if task["task_type"] == SCOUT_TASK_TYPE:
            keys, name = {scout_task_key(db, task)}, "scouts_in_flight"
        else:
            keys, name = admission_task_keys(db, task), "admission_batches_in_flight"
        for key in keys:
            counts = bucket(key)
            counts[name] = counts.get(name, 0) + 1
    for line, slots in report.program.get("lines", {}).items():
        bucket(line).update(slots)
    for item in report.program.get("scouts_scheduled", []):
        counts = bucket(_topic_key(item))
        counts["scouts_scheduled"] = counts.get("scouts_scheduled", 0) + 1
    for item in report.program.get("admissions_scheduled", []):
        task = db.task(item["task_id"])
        if task:
            keys = admission_task_keys(db, task)
            item["research_lines"] = sorted(key for key in keys if not key.startswith("domain/"))
            item["legacy_domains"] = sorted(
                key.removeprefix("domain/") for key in keys if key.startswith("domain/")
            )
            for key in keys:
                counts = bucket(key)
                counts["admission_batches_scheduled"] = counts.get("admission_batches_scheduled", 0) + 1
    report.program["by_line"] = lines
    report.program["legacy_by_domain"] = legacy


def run_program_pipeline(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: Any,
) -> None:
    """Per-tick supply bookkeeping. Disabled: touches nothing."""

    if not settings.program.enabled:
        return
    info = report.program
    program = settings.program
    stopped = {
        line: entry.mode for line, entry in program.lines.items()
        if program.stops(SUPPLY_STAGE, line) or program.stops(RESEARCH_STAGE, line)
    }
    if program.polish_mode or stopped:
        info["polish_mode"] = {
            "on": program.polish_mode,
            "line_modes": {line: entry.mode for line, entry in program.lines.items()},
            "exempt_lines": [line for line, entry in program.lines.items() if entry.mode == "full"],
            "supply_only_lines": [
                line for line, entry in program.lines.items() if entry.mode == "supply_only"
            ],
            "paused": ["topic_scout", "topic_admission", "auto_reopen", "materialize"],
            "running": ["topics_in_research", "writing", "reviews", "delivery",
                        "delivered_revisions", "operator_reopen_grants", "journal_mail"],
            "cancelled": list(db.cancel_queued_tasks(
                [str(task["task_id"]) for task in _program_tasks(
                    db, statuses=("queued",), where="AND task_type=?",
                    parameters=(SCOUT_TASK_TYPE,))
                 if program.stops(SUPPLY_STAGE, _scout_task_line(db, task))],
                reason=POLISH_MODE_REASON)),
        }
    backlog = compute_backlog(settings)
    if backlog is not None:
        info["compute_backlog"] = backlog
        if backlog["backlogged"]:
            report.production_blocked.append({
                "campaign_id": "",
                "reason": COMPUTE_BACKLOG_REASON,
                "detail": str(backlog["detail"]),
            })
    try:
        outcomes = register_scout_results(db, paths, settings)
        info["cards_registered"] = [item for item in outcomes if item["status"] == "proposed"]
        info["rejected_cards"] = [item for item in outcomes if item["status"] == "rejected"]
        # Kept only for legacy paused research topics on line_facts; disconnected from supply.
        line_facts.tick(db, paths, settings, report)
        from .reopen import (
            advance_delivered_revisions,
            reopen_ready_topics,
            repair_half_done_reopens,
        )

        info["delivered_revisions"] = advance_delivered_revisions(db, paths, settings, report)
        info["reopen_repaired"] = repair_half_done_reopens(db, paths, settings, report)
        info["auto_reopen"] = reopen_ready_topics(db, paths, settings, report)
        spawned = materialize_waiting_topics(db, paths, settings)
        report.enqueued.extend(spawned.task_ids)
        report.production_synced.extend(spawned.campaign_ids)
        info["materialized"] = list(spawned.campaign_ids)

        moment = _now_moment()
        scheduled, blocked = schedule_scouts(
            db, paths, settings, lead_short=lead_quota_short(db, settings), now=moment
        )
        report.enqueued.extend(str(item.task_id) for item in scheduled)
        info["scouts_scheduled"] = [
            {
                "task_id": item.task_id,
                "domain": item.domain,
                **({"research_line": item.research_line} if item.research_line else {}),
            }
            for item in scheduled
        ]
        info["scout_blocked"] = blocked
        active_projects = program_projects(paths)
        info["lines_environment_not_ready"] = lines_not_ready(
            paths, settings, [project.research_line for project in active_projects]
        )
        info["weekly_budget_blocks"] = list(
            weekly_budget_blocks(db, paths, settings, active_projects, moment=moment).values()
        )
        info["scouts_in_flight"] = len(_program_tasks(
            db, statuses=IN_FLIGHT_STATUSES, where="AND task_type=?", parameters=(SCOUT_TASK_TYPE,)
        ))
        document = open_topic_ledger(paths, settings.program).read()
        info["candidate_pool"] = len(_proposed_pool(document))
        info["candidate_pool_topics"] = [str(t["topic_id"]) for t in _proposed_pool(document)]
        info["waiting_admitted"] = [
            str(t["topic_id"]) for t in waiting_admitted(document, admission_sequence(db))
        ]
        info.update(slot_status(
            document, settings.program, parked_program_projects(paths),
            paused_topic_campaigns(db),
        ).to_dict())
        info.setdefault("admissions_scheduled", [])
        info.setdefault("admission_decisions", [])
        metrics = supply_metrics(document, settings, db=db, paths=paths, moment=moment)
        info["supply_metrics"] = metrics
        info["needs_registration"] = metrics["needs_registration"]
    except (OSError, TopicLedgerError, KeyError, TypeError, ValueError,
            json.JSONDecodeError) as exc:
        report.errors.append(f"program pipeline: {exc}")
        info["pipeline_error"] = str(exc)
