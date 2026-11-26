"""Research-program pipeline: topic scouts, card intake and the admission gate.

Deterministic bookkeeping and routing only. A ``topic_scout`` agent proposes
topic cards, an independent worker-tier reviewer of another model family (user
2026-11-18, ``[routing.task_tiers]``) judges them in a
``portfolio_review`` task (routing reason ``topic_admission``), and this module

* schedules a scout when the program has room and the candidate pool is low,
* checks each returned card against ``openlabs.topic_card.v1`` and registers it
  in the topic ledger (``proposed``), or records it as ``rejected`` with the
  failed checks,
* builds the admission review packet and routes it away from the proposer's
  model family (``exclude_provider``), never falling back to the same family,
* applies the gate's decisions with mechanical checks (slot, data access,
  computational-only, packet membership, pre-registration hash) and
  materializes admitted topics, in admission order, as research campaigns,
  carrying the gate's admission conditions into the first task,
* gives a format-invalid scout card one automatic repair (a revalidation
  under the current contract, else a light repair task); a second failure is
  final,
* releases holds whose research line became ready, and schedules one revision
  task per held or fixably rejected topic (the gate then checks only the
  recorded reopen conditions).

Whether a topic is worth doing is never decided here.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import assets as asset_library
from . import budget as budget_control
from . import card_precheck as card_checks
from . import line_facts
from . import nc_funnel
from . import supply_screen
from . import target_stage
from .config import FactorySettings, WorkspacePaths, dispatch_runner
from .utilization import compute_backlog
from .contracts import (
    ADMISSION_POLICY_VERSION,
    admission_conditions,
    artifact_digests,
    atomic_write_json,
    canonical_json_bytes,
    compute_plan_locations,
    data_source_identifiers,
    normalize_topic_card,
    sha256_file,
    validate_topic_admission,
    validate_topic_card,
)
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
    AUTOMATIC_REOPEN_TYPES,
    HOLD_RELEASE_ADMITTED,
    HOLD_RELEASE_FOR_REVIEW,
    TopicLedger,
    TopicLedgerError,
    activate_topic,
    admit_topic,
    card_sha256,
    find_topic,
    last_rejection_reason,
    note_admission_attempt,
    open_topic_ledger,
    parked_program_projects,
    paused_topic_campaigns,
    propose_topic,
    record_rejected_card,
    record_topic_note,
    reject_topic,
    release_held_topic,
    revision_eligible,
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
    line_summary,
    line_templates,
    queued_templates,
    read_lines_or_none,
)
from .resources import ResourceVector, default_task_resources

SCOUT_TASK_TYPE = "topic_scout"
# One light task that fixes a format-invalid card, and one worker task that
# revises a held or fixably rejected topic against its reopen conditions. Both
# return ``topic_cards`` like a scout and are registered the same way.
REPAIR_TASK_TYPE = "topic_card_repair"
REVISION_TASK_TYPE = "topic_revision"
CARD_TASK_TYPES = (SCOUT_TASK_TYPE, REPAIR_TASK_TYPE, REVISION_TASK_TYPE)
ADMISSION_ROUTING_REASON = "topic_admission"
SCOUT_ROUTING_REASON = "program_slot_open"
REPAIR_ROUTING_REASON = "topic_card_repair"
REVISION_ROUTING_REASON = "topic_revision"
SCOUT_PACKET_SCHEMA = "openlabs.topic_scout_packet.v1"
REPAIR_PACKET_SCHEMA = "openlabs.topic_card_repair_packet.v1"
REVISION_PACKET_SCHEMA = "openlabs.topic_revision_packet.v1"
CARD_PACKET_SCHEMAS = (SCOUT_PACKET_SCHEMA, REPAIR_PACKET_SCHEMA, REVISION_PACKET_SCHEMA)
# v2: the record also carries the gate's admission conditions and, for a
# control-plane hold, the line it waits for (v1 records are read the same way).
ADMISSION_RECORD_SCHEMA = "openlabs.topic_admission_record.v2"
# Format-invalid cards recorded before automatic repair existed get one repair
# when they are this recent.
LEGACY_REPAIR_WINDOW = timedelta(days=14)
TERMINAL_FAILED_STATUSES = ("failed", "needs_human", "needs_replan", "quarantined", "cancelled")
SCOUT_SKILL = "openlabs-empirical-topic-scout"
ADMISSION_SKILL = "openlabs-topic-admission"
LAST_SCOUT_KEY = "program_last_scout_at"
# ``{SCOUT_FAMILY_KEY}:{line}@{family}``: when a scout of the line last asked for that model
# family (``[program].scout_runners``).
SCOUT_FAMILY_KEY = "program_scout_family_at"
SCOUT_REGISTERED_PREFIX = "program_scout_registered:"
# Per rotation key (line, else domain): the empty-draw streak of its scouts, JSON
# {fingerprint, count, last_at, last_task_id, last_created_at, last_summary, reason}.
SCOUT_SUPPLY_PREFIX = "program_scout_supply:"
# Scout outcomes that end the draw: a result exists to count its cards.
SCOUT_FINISHED_STATUSES = ("succeeded", "needs_replan", "needs_human")
# A topic included in this many admission packets without a valid decision is
# rejected as ``admission_undecided`` (it may be resubmitted as a new card).
MAX_ADMISSION_ATTEMPTS = 3
HUMAN_PROVIDER = "human"
# awaiting_remote: parked on remote compute jobs (openlabs.remote_wait); still in flight.
IN_FLIGHT_STATUSES = ("queued", "leased", "running", "awaiting_remote")
POOL_STATUSES = ("proposed",)
SCOUT_LOAD_STATUSES = ("proposed", "admitted", "active", "in_review")
# Research campaigns may continue in these ledger states (enforce_admission).
ADMITTED_WORK_STATUSES = ("admitted", "active", "in_review", "ready_queue", "submitted")


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


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected an object: {path}")
    return value


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
    # '/' is excluded from project identifiers, so legacy keys cannot collide with line IDs.
    return str(line) if line else f"domain/{domain or ''}"


def scout_key(project: ProjectConfig) -> str:
    return _scope_key(project.research_line, project.domain)


def _topic_key(topic: Mapping[str, Any]) -> str:
    return _scope_key(topic.get("research_line"), topic.get("domain"))


def _scout_stamp(stamps: Mapping[str, str], key: str) -> str:
    return stamps.get(key, stamps.get(key.removeprefix("domain/"), ""))


def _rotation_projects(settings: FactorySettings, projects: list[ProjectConfig]) -> list[ProjectConfig]:
    lines = settings.program.research_lines
    domains = settings.program.domains
    if lines:
        return [project for project in projects if project.research_line in lines]
    return [project for project in projects if not domains or project.domain in domains]


def research_lines_document(
    paths: WorkspacePaths, settings: FactorySettings
) -> dict[str, Any] | None:
    """The parsed direction file, or ``None`` when absent or unreadable."""

    return read_lines_or_none(paths.data / settings.program.research_lines_path)


def lines_not_ready(
    paths: WorkspacePaths,
    settings: FactorySettings,
    lines: Any,
    *,
    db: FactoryDB | None = None,
) -> dict[str, str]:
    """``{line: environment status}`` of the given research lines that are not ready.

    A topic of such a line could not run its first research task (the feasibility
    precheck), so the program neither scouts nor reviews topics for it until the
    line's environment is ``ready`` in registry/research-lines.yaml.
    """

    wanted = sorted({str(line).strip() for line in lines if str(line or "").strip()})
    if not wanted:
        return {}
    # A line blocked on its shared reference (line_facts.py) opens no new topic either.
    blocked = {line: status for line, status in line_facts.blocked_lines(db).items()
               if line in wanted} if settings.program.supply.line_facts else {}
    document = research_lines_document(paths, settings)
    if document is None:
        # Without a readable direction file nothing is known to be unready; the
        # admission-time hold still keeps such a topic from starting.
        return blocked
    statuses = {line: environment_status(document, line) for line in wanted}
    return {**{line: status for line, status in statuses.items()
               if status != ENVIRONMENT_READY}, **blocked}


def program_projects(paths: WorkspacePaths) -> list[ProjectConfig]:
    """Active research-program projects (invalid configs are reported elsewhere)."""

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
    """Inputs offered to scouts and the admission gate; absent files are skipped."""

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


def _ledger_snapshot(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    from .program import last_rejection_reason

    snapshot: list[dict[str, Any]] = []
    for topic in document.get("topics") or []:
        snapshot.append(
            {
                "topic_id": topic.get("topic_id"),
                "domain": topic.get("domain"),
                "research_line": topic.get("research_line"),
                "question": topic.get("question"),
                "fingerprint": topic.get("fingerprint"),
                "status": topic.get("status"),
                "rejection_reason": (
                    last_rejection_reason(topic) if topic.get("status") == "rejected" else None
                ),
                "freeze_reason_class": topic.get("freeze_reason_class"),
                "reopen_conditions": topic.get("reopen_conditions") or [],
                "supersedes": topic.get("supersedes"),
                "revision_of": topic.get("revision_of"),
                "revision_open": revision_eligible(topic),
                **({"screen_feedback": feedback}
                   if (feedback := _screen_feedback(topic)) else {}),
            }
        )
    return snapshot


def _screen_feedback(topic: Mapping[str, Any]) -> dict[str, Any] | None:
    """What the independent NC prescreen found on a judged card (fed back to scouts)."""

    check = topic.get("card_check") if isinstance(topic.get("card_check"), Mapping) else {}
    state = check.get("prescreen") if isinstance(check.get("prescreen"), Mapping) else {}
    if state.get("status") not in {"pass", "fail"}:
        return None
    feedback = {key: state[key] for key in ("status", "met", "novelty", "expected_band", "why",
                                            "downgrades")
                if state.get(key) not in (None, [], "")}
    if state.get("summary"):
        feedback["summary"] = str(state["summary"])[:800]
    return feedback


def _signed(packet: dict[str, Any]) -> dict[str, Any]:
    packet["content_sha256"] = hashlib.sha256(canonical_json_bytes(packet)).hexdigest()
    return packet


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
    if schema not in (*CARD_PACKET_SCHEMAS, nc_funnel.PRESCREEN_PACKET_SCHEMA) and not (
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


def _program_tasks(db: FactoryDB, *, statuses: tuple[str, ...], where: str = "",
                   parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
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
    """The research line a scout task works for ('' when it has none)."""

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
        keys = {_topic_key(entry["card"]) for entry in packet.get("topic_cards", [])
                if isinstance(entry, Mapping) and isinstance(entry.get("card"), Mapping)}
        if keys:
            return keys
    except (OSError, TypeError, ValueError):
        pass
    project = campaign_project(db.campaign(str(task.get("campaign_id") or "")) or {})
    return {scout_key(project) if project else _topic_key(task)}


# --------------------------------------------------------------------------- scouts


@dataclass(frozen=True)
class ScoutDecision:
    task_id: str | None = None
    domain: str | None = None
    reason: str | None = None
    research_line: str | None = None


def _proposed_pool(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    return topics_by_status(document, *POOL_STATUSES)


LINE_SLOTS_FULL_REASON = "line_slots_full"
# ``[program] polish_mode`` (2026-11-23): no new topic supply, no new research starts.
POLISH_MODE_REASON = "polish_mode"


def line_scout_room(status: Any, document: Mapping[str, Any], line: Any, *,
                    funnel_pool: int | None = None) -> int | None:
    """Cards a scout of ``line`` may still usefully add (None: the line has no own limit).

    The line's free slots (``[program].line_max_active_topics`` minus its admitted,
    active and in-review topics) less its cards already waiting for admission.

    ``funnel_pool`` (an NC-aimed line, 2026-11-25 trial): most cards are screened out before
    admission (prescreen, kill test, admission bar), so a free slot is filled from a pool of
    up to ``funnel_pool`` waiting cards instead of one card per slot. A line without a free
    slot still gets no scout.
    """

    free = status.line_free_slots(line) if hasattr(status, "line_free_slots") else None
    if free is None:
        return None
    key = str(line or "").strip()
    waiting = sum(1 for topic in _proposed_pool(document)
                  if str(topic.get("research_line") or "").strip() == key)
    if funnel_pool is not None:
        return 0 if free <= 0 else max(free, funnel_pool) - waiting
    return free - waiting


def lines_without_scout_room(status: Any, document: Mapping[str, Any],
                             funnel_pools: Mapping[str, int] | None = None) -> frozenset[str]:
    """Limited lines that get no scout now (no free slot left after their waiting cards)."""

    limits = getattr(status, "line_limits", None) or {}
    pools = funnel_pools or {}
    return frozenset(line for line in limits
                     if (room := line_scout_room(status, document, line,
                                                 funnel_pool=pools.get(line))) is not None
                     and room <= 0)


def funnel_pool(db: FactoryDB | None, settings: FactorySettings, line: Any) -> int | None:
    """The waiting-card pool of an NC-aimed line (None: one card per free slot)."""

    if not line or target_stage.stage_for(db, line, settings) != target_stage.NC_AIM:
        return None
    return int(settings.program.candidate_pool_low_water)


def admission_sequence(db: FactoryDB) -> dict[str, int]:
    """Topic id -> id of its ``topic_admitted`` event (a strict admission order)."""

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
    """Admitted topics without a campaign, oldest admission first."""

    order = dict(sequence or {})

    def key(topic: Mapping[str, Any]) -> tuple[int, str, str]:
        topic_id = str(topic.get("topic_id") or "")
        return (order.get(topic_id, 1 << 62), str(topic.get("admitted_at") or ""), topic_id)

    return sorted(topics_by_status(document, "admitted"), key=key)


def _choose_scout_project(
    db: FactoryDB,
    settings: FactorySettings,
    projects: list[ProjectConfig],
    document: Mapping[str, Any],
    *,
    exclude: frozenset[str] = frozenset(),
) -> tuple[ProjectConfig, str] | None:
    """Line (or domain) with the fewest topics in flight; ties go to the least recently scouted.

    With ``[program].research_lines`` set, only projects of those lines rotate,
    keyed by line and ordered by that list; otherwise ``[program].domains``
    restricts the rotation by domain and breaks remaining ties by its order.
    Keys in ``exclude`` (a scout in flight, or scouted too recently) are skipped.
    """

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
        topic_key = _topic_key(topic)
        load[topic_key] = load.get(topic_key, 0) + 1
    last = db.meta_items(LAST_SCOUT_KEY + ":")

    def key(item: tuple[ProjectConfig, str]) -> tuple[int, str, int, str]:
        project = item[0]
        rotation = scout_key(project)
        if lines:
            order = lines.index(project.research_line) if project.research_line in lines else 0
        else:
            order = configured.index(project.domain) if project.domain in configured else 0
        return (load.get(rotation, 0), _scout_stamp(last, rotation), order, project.project_id)

    return min(usable, key=key)


# Finished scouts whose registered cards calibrate ``expected_cards_per_scout``.
SCOUT_CALIBRATION_WINDOW = 10
SCOUT_CALIBRATION_MINIMUM = 3


def expected_cards_per_scout(
    db: FactoryDB,
    settings: FactorySettings,
    document: Mapping[str, Any],
) -> float:
    """Cards one scout is expected to register.

    The mean over this instance's last finished scouts (cards of every status,
    rejected ones included) once a few have finished, else
    ``[program].scout_expected_cards``. Floored at 0.5 so a run of empty scouts
    does not open the floodgates.
    """

    finished = _program_tasks(
        db, statuses=("succeeded",), where="AND task_type=?", parameters=(SCOUT_TASK_TYPE,)
    )[-SCOUT_CALIBRATION_WINDOW:]
    if len(finished) < SCOUT_CALIBRATION_MINIMUM:
        return settings.program.scout_expected_cards
    ids = {str(task["task_id"]) for task in finished}
    cards = sum(
        1 for topic in document.get("topics") or []
        if str(topic.get("source_task_id") or "") in ids
    )
    return max(0.5, cards / len(finished))


def queue_scout_instruction(
    queues: Mapping[str, str],
    held_released: Mapping[str, bool] | None = None,
    supply: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    taken: Mapping[str, str] | None = None,
) -> str:
    """Scout objective addition for templates with an enumerated candidate queue.

    ``held_released`` maps the release key of held queue entries (``held_candidates``,
    e.g. a needs-spot hold) to whether the control plane found it met this tick;
    ``supply`` the per-template draw state (``template_supply``: drawable entries, empty
    draws since the queue last changed).
    """

    if not queues:
        return ""
    held = ""
    if held_released:
        released = sorted(key for key, value in held_released.items() if value)
        waiting = sorted(key for key, value in held_released.items() if not value)
        held = (
            " Entries under `held_candidates` wait for a line capability (their "
            "draw_hold.release_when); checked this tick: "
            + "; ".join([*(f"{key} met" for key in released),
                         *(f"{key} not met" for key in waiting)])
            + ". Draw a held entry only when its key is met, after the `candidates`, with a "
            "card that pre-registers that capability instead of a gate against it."
        )
    state = ""
    if supply:
        state = " Queue state: " + "; ".join(
            f"{template}: {item.get('drawable', '?')} drawable"
            + (f", {item['empty_draws']} empty draw(s) since it last changed - skip it unless "
               "an entry is free" if item.get("empty_draws") else "")
            for template, item in sorted(supply.items())) + "."
    if taken:
        state += (
            " Entries without `ledger_occupancy` are checked against the topic ledger by "
            "their candidate_queue_entry.entry_id; already taken (skip them unless the entry "
            "carries `reopens`): "
            + ", ".join(f"{entry} ({status})" for entry, status in sorted(taken.items())[:40])
            + "."
        )
    return (
        ". Templates with a candidate_queue ("
        + ", ".join(f"{template}: {path}" for template, path in sorted(queues.items()))
        + ") are enumerated, not scouted: do not search for other targets of them. Each "
        "template has its own queue and its own card rules; a target may appear under two "
        "templates (a single-target solution and a sample audit batch) - those are different "
        "topics, not duplicates. Draw the entries of a queue's `candidates` in `rank` order "
        "(the queue's draw order, e.g. score_v2). Each entry's `ledger_occupancy` says whether "
        "its target is free, reopenable or blocked: skip blocked and in-flight ones. Copy the "
        "entry's `card_fields` into the card unchanged - every key, including `reopens` and "
        "`reopen_basis` when present (a reopening card must declare both; the ledger refuses a "
        "reopen whose basis type the frozen topic did not allow) - and re-run the occupancy "
        "search only when its searched_at is empty or more than 30 days old (then record the "
        "new search). Write the rest of the card from that template's entry in "
        "research-lines.yaml: its `card_rules` (required_analysis, primary_endpoint_template, "
        "forbidden_conditions, reopening) where it has them, else its minimum_content, "
        "novelty_rule and the SOP; never add a condition its forbidden_conditions list. The "
        "control plane runs the line's admission_precheck on each card before review. Skip an "
        "entry whose data access fails and say so in the result" + held + state
    )


def held_queue_releases(
    paths: WorkspacePaths, settings: FactorySettings, line: str, queues: Mapping[str, str]
) -> dict[str, bool]:
    """``{release key: met}`` for the line-capability holds of the line's queued entries."""

    from .reopen import evaluate_condition

    lines_path = paths.data / settings.program.research_lines_path
    document = read_lines_or_none(lines_path)
    result: dict[str, bool] = {}
    for path in queues.values():
        try:
            queue = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for entry in queue.get("held_candidates") or [] if isinstance(queue, Mapping) else []:
            hold = (entry.get("draw_hold") or {}) if isinstance(entry, Mapping) else {}
            when = hold.get("release_when") if isinstance(hold, Mapping) else None
            if not isinstance(when, Mapping) or when.get("kind") != "line_capability":
                continue
            key = str(when.get("key") or "")
            if not key or key in result:
                continue
            result[key] = bool(evaluate_condition(
                {"kind": "line_capability", "key": key, "line": when.get("line") or line},
                topic={"research_line": line}, lines_document=document,
                lines_path=lines_path)["met"])
    return result


def _queue_instruction(paths: WorkspacePaths, settings: FactorySettings, line: str,
                       db: FactoryDB | None = None) -> str:
    queues = queued_templates(research_lines_document(paths, settings), line)
    taken = (ledger_queue_entries(open_topic_ledger(paths, settings.program).read(), line)
             if _queues_without_occupancy(queues) else {})
    supply = template_supply(queues, taken)
    if db is not None:
        counts = _supply_state(db, line).get("templates") or {}
        for template, item in supply.items():
            entry = counts.get(template) if isinstance(counts, Mapping) else None
            if isinstance(entry, Mapping) and int(entry.get("count") or 0):
                item["empty_draws"] = int(entry["count"])
    text = queue_scout_instruction(queues, held_queue_releases(paths, settings, line, queues),
                                   supply, taken=taken)
    if text and settings.program.supply.target_memory:
        failed = supply_screen.failed_targets(open_topic_ledger(paths, settings.program).read(),
                                              line, queues)
        if failed:
            # Target memory: the intake rejects these again without running the precheck.
            text += (" Targets that already failed and whose queue entry has not changed "
                     "since (do not draw them; a frozen one only with `reopens`): "
                     + ", ".join(f"{key} ({why})" for key, why in sorted(failed.items())[:60])
                     + ".")
    return text


def _queues_without_occupancy(queues: Mapping[str, str]) -> bool:
    """Whether any queue lists a candidate without the enumerator's ``ledger_occupancy``."""

    for path in queues.values():
        try:
            queue = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        candidates = queue.get("candidates") if isinstance(queue, Mapping) else None
        if any(isinstance(item, Mapping) and not isinstance(item.get("ledger_occupancy"), Mapping)
               for item in candidates or []):
            return True
    return False


# Ledger outcomes after which a queue entry is not drawn again by an ordinary card (a
# card rejected for its format or by the line's mechanical precheck may be drawn again).
_REDRAWABLE_REJECTIONS = frozenset({"card_invalid", "card_precheck_failed"})


def ledger_queue_entries(document: Mapping[str, Any], line: str | None) -> dict[str, str]:
    """``{queue entry id: topic status}`` of the line's ledger topics (from their cards).

    For queues whose entries carry no ``ledger_occupancy`` (only the astro enumerator
    writes it), this is what tells a scout which entries are already taken.
    """

    from .program import last_rejection_reason

    if not line:
        return {}
    taken: dict[str, str] = {}
    for topic in document.get("topics") or []:
        if not isinstance(topic, Mapping) or str(topic.get("research_line") or "") != line:
            continue
        status = str(topic.get("status") or "")
        if status == "rejected" and last_rejection_reason(topic) in _REDRAWABLE_REJECTIONS:
            continue
        try:
            card = _read_object(Path(str(topic.get("card_path") or "")))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
        entry_id = card_checks.entry_id_of(card)
        if entry_id and (entry_id not in taken or status != "rejected"):
            taken[entry_id] = status
    return taken


def _entry_template(item: Mapping[str, Any]) -> str | None:
    """The paper template a queue entry's card_fields name (None: not stated)."""

    fields = item.get("card_fields")
    value = fields.get("paper_template") if isinstance(fields, Mapping) else None
    return str(value) if value else None


def template_supply(queues: Mapping[str, str],
                    taken: Mapping[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """Per queued template: queue digest and drawable entries (free or reopenable).

    An entry without ``ledger_occupancy`` counts as drawable unless ``taken`` (see
    :func:`ledger_queue_entries`) names its ``entry_id``. A queue shared by several
    templates counts, for each, only the entries whose ``card_fields.paper_template`` is it.
    """

    taken = taken or {}
    result: dict[str, dict[str, Any]] = {}
    for template, path in sorted(queues.items()):
        entry: dict[str, Any] = {"digest": _file_digest(path)}
        try:
            queue = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            queue = None
        candidates = queue.get("candidates") if isinstance(queue, Mapping) else None
        if isinstance(candidates, list):
            entry["drawable"] = sum(
                1 for item in candidates if isinstance(item, Mapping)
                and _entry_template(item) in (None, template)
                and (str(item["ledger_occupancy"].get("state") or "free")
                     in {"free", "reopenable"}
                     if isinstance(item.get("ledger_occupancy"), Mapping)
                     else str(item.get("entry_id") or "") not in taken))
        result[template] = entry
    return result


# ----------------------------------------------------------- empty-draw backoff


def _file_digest(path: Any) -> str | None:
    try:
        return sha256_file(Path(str(path)))
    except (OSError, TypeError, ValueError):
        return None


def scout_supply_fingerprint(
    paths: WorkspacePaths,
    settings: FactorySettings,
    project: ProjectConfig,
    document: Mapping[str, Any],
) -> str:
    """Digest of what a scout of this line can draw from.

    Covers the line's entry in the direction file (templates, declared
    capabilities such as a spot configuration), the bytes of its candidate
    queues, which held queue entries are released, and the line's ledger topics
    (id and status). Any change means a new scout may find something new.
    """

    line = project.research_line
    lines_document = research_lines_document(paths, settings)
    queues = queued_templates(lines_document, line) if line else {}
    key = scout_key(project)
    parts = {
        "key": line or project.domain,
        "line": line_entry(lines_document, line) if line else None,
        "queues": {template: _file_digest(path) for template, path in sorted(queues.items())},
        "held": held_queue_releases(paths, settings, line, queues) if line and queues else {},
        "shared_reference_versions": {ref["id"]: line_facts.receipt_fingerprint(ref)
                                      for ref in line_facts.line_references(paths, settings, line)}
                                     if line else {},
        "ledger": sorted(
            [str(topic.get("topic_id") or ""), str(topic.get("status") or ""),
             last_rejection_reason(topic), str((topic.get("card_check") or {}).get("entry_digest") or "")]
            for topic in document.get("topics") or []
            if isinstance(topic, Mapping) and _topic_key(topic) == key
        ),
    }
    return hashlib.sha256(
        json.dumps(parts, sort_keys=True, default=str).encode()
    ).hexdigest()


def _supply_state(db: FactoryDB, key: str) -> dict[str, Any]:
    raw = db.meta_get(SCOUT_SUPPLY_PREFIX + key)
    if raw is None and key.startswith("domain/"):
        raw = db.meta_get(SCOUT_SUPPLY_PREFIX + key.removeprefix("domain/"))
    try:
        value = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        value = {}
    return value if isinstance(value, dict) else {}


def _scout_result_cards(task: Mapping[str, Any]) -> tuple[int | None, str]:
    """``(cards in the hash-bound result, summary)``; ``None`` when unreadable."""

    result_path = Path(str(task.get("result_path") or ""))
    expected = str(task.get("result_sha256") or "")
    try:
        if not result_path.is_file() or (expected and sha256_file(result_path) != expected):
            return None, ""
        payload = _read_object(result_path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None, ""
    cards = payload.get("topic_cards")
    return (len(cards) if isinstance(cards, list) else 0), str(payload.get("summary") or "")[:400]


def record_scout_outcomes(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    document: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Update each line's empty-draw streak from scouts finished since the last tick.

    A scout is empty when no card it returned stands in the ledger as anything but
    ``rejected`` (no card at all, or every card rejected at intake). An empty scout
    extends the streak when the supply fingerprint is the one of the previous empty
    draw, else restarts it at 1; a productive scout clears it. Runs after
    ``register_scout_results`` so the cards of a succeeded scout are in the ledger.
    """

    projects = {
        scout_workstream_id(project): project
        for project in program_projects(paths) if scout_workstream_id(project)
    }
    by_source: dict[str, int] = {}
    accepted_topics: dict[str, list[Mapping[str, Any]]] = {}
    for topic in document.get("topics") or []:
        if isinstance(topic, Mapping) and str(topic.get("status") or "") != "rejected":
            source = str(topic.get("source_task_id") or "")
            by_source[source] = by_source.get(source, 0) + 1
            accepted_topics.setdefault(source, []).append(topic)
    states: dict[str, dict[str, Any]] = {}
    changes: list[dict[str, Any]] = []
    fingerprints: dict[str, str] = {}
    queued: dict[str, bool] = {}
    for task in _program_tasks(db, statuses=SCOUT_FINISHED_STATUSES, where="AND task_type=?",
                               parameters=(SCOUT_TASK_TYPE,)):
        project = projects.get(str(task.get("campaign_id") or ""))
        if project is None:
            continue
        key = scout_key(project)
        state = states.setdefault(key, _supply_state(db, key))
        marker = (str(task.get("created_at") or ""), str(task["task_id"]))
        recent = [str(item) for item in state.get("recent_task_ids") or []]
        if marker[0] < str(state.get("last_created_at") or "") or marker[1] in recent:
            continue
        cards, summary = _scout_result_cards(task)
        accepted = by_source.get(str(task["task_id"]), 0)
        state["last_created_at"], state["last_task_id"] = marker
        state["recent_task_ids"] = [*recent, marker[1]][-20:]
        if str(task.get("status")) != "succeeded":
            # The control plane did not accept the result (needs_replan: an artifact outside
            # the staging area, a hash mismatch, a failed commit; needs_human): its cards never
            # reached intake, so it says nothing about the line's supply. Neither empty nor
            # productive; the minimum scout interval still spaces the next attempt.
            continue
        if project.research_line and (cards is not None or accepted):
            _record_template_draws(paths, settings, project.research_line, state,
                                   accepted_topics.get(str(task["task_id"]), []))
        if accepted:
            if int(state.get("count") or 0):
                changes.append({"key": key, "event": "topic_scout_productive",
                                "task_id": marker[1], "previous_empty_draws": state["count"]})
            state.update(count=0, fingerprint=None, reason=None, last_summary=None)
            continue
        if key not in fingerprints:
            fingerprints[key] = scout_supply_fingerprint(paths, settings, project, document)
            queued[key] = bool(project.research_line and queued_templates(
                research_lines_document(paths, settings), project.research_line))
        fingerprint = fingerprints[key]
        reason = "cards_rejected" if cards else "candidate_queue_exhausted" if queued[key] else "no_cards"
        same = state.get("fingerprint") == fingerprint and state.get("reason") == reason
        state.update(
            count=(int(state.get("count") or 0) + 1) if same else 1,
            fingerprint=fingerprint,
            last_at=str(task.get("updated_at") or utc_now()),
            last_summary=summary,
            reason=reason,
        )
        changes.append({"key": key, "event": "topic_scout_empty", "task_id": marker[1],
                         "empty_draws": state["count"], "reason": state["reason"]})
    if states:
        db.update_meta(
            {SCOUT_SUPPLY_PREFIX + key: json.dumps(state, sort_keys=True)
             for key, state in states.items()},
            events=[("program", item["key"], item["event"], item) for item in changes],
        )
    return changes


def _record_template_draws(
    paths: WorkspacePaths,
    settings: FactorySettings,
    line: str,
    state: dict[str, Any],
    accepted: list[Mapping[str, Any]],
) -> None:
    """Per-template empty-draw streaks of a multi-template line (``state["templates"]``).

    A template the scout drew a standing card from is reset; every other queued template
    counts one more empty draw while its queue file is unchanged (restart at 1 when it
    changed). Only reported (scout instruction, block detail); the line-level backoff
    above still decides whether the next scout runs.
    """

    queues = queued_templates(research_lines_document(paths, settings), line)
    if not queues:
        return
    drawn: set[str] = set()
    for topic in accepted:
        try:
            card = _read_object(Path(str(topic.get("card_path") or "")))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
        drawn.add(str(card.get("paper_template") or ""))
    previous = state.get("templates") if isinstance(state.get("templates"), dict) else {}
    templates: dict[str, Any] = {}
    # Templates sharing one queue file (power-market-backtest: one queue, entries carry
    # their own template): a draw from the shared queue is no empty draw for the others.
    drawn_queues = {queues.get(template) for template in drawn if queues.get(template)}
    for template, item in template_supply(queues).items():
        old = previous.get(template) if isinstance(previous.get(template), Mapping) else {}
        if template in drawn or queues.get(template) in drawn_queues:
            templates[template] = {"count": 0, "digest": item.get("digest")}
            continue
        same = old.get("digest") == item.get("digest")
        templates[template] = {"count": int(old.get("count") or 0) + 1 if same else 1,
                               "digest": item.get("digest")}
    state["templates"] = templates


def scout_supply_blocks(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    projects: list[ProjectConfig],
    document: Mapping[str, Any],
    *,
    moment: datetime,
) -> dict[str, dict[str, Any]]:
    """``{rotation key: block}`` for lines whose next scout must wait or not run.

    A block is ``scout_empty_backoff`` (with ``until``) or ``candidates_exhausted``.
    A line whose supply fingerprint changed since its last empty draw is released
    here at once (streak cleared, ``topic_scout_backoff_released`` event).
    """

    program = settings.program
    blocks: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for project in projects:
        key = scout_key(project)
        if key in seen:
            continue
        seen.add(key)
        state = _supply_state(db, key)
        count = int(state.get("count") or 0)
        if (program.supply.scout_skip_empty_queue and project.research_line
                and target_stage.stage_for(db, project.research_line, settings)
                != target_stage.NC_AIM):
            # Nothing drawable in the line's queues: no scout is spent on finding that out.
            # Not under the NC aim (2026-11-25 trial): its scouts read the literature and the
            # data catalogue broadly; the routine templates' queues are optional there.
            empty = queue_supply_empty(paths, settings, project.research_line, document)
            if empty is not None:
                blocks[key] = {
                    "research_line": project.research_line, "domain": project.domain,
                    "campaign_id": scout_workstream_id(project), "empty_draws": count,
                    "reason": "candidate_queue_empty", **empty,
                    "release_when": "an entry of the line's candidate queue becomes drawable "
                                    "(queue regenerated, a topic released, a held capability "
                                    "met)",
                }
                continue
        if count <= 0:
            continue
        fingerprint = scout_supply_fingerprint(paths, settings, project, document)
        if fingerprint != state.get("fingerprint"):
            detail = {"key": key, "empty_draws": count, "reason": "candidate_supply_changed"}
            state.update(count=0, fingerprint=None, reason=None, last_summary=None)
            db.update_meta(
                {SCOUT_SUPPLY_PREFIX + key: json.dumps(state, sort_keys=True)},
                events=[("program", key, "topic_scout_backoff_released", detail)],
            )
            continue
        base = {
            "research_line": project.research_line or None,
            "domain": project.domain,
            "campaign_id": scout_workstream_id(project),
            "empty_draws": count,
            "empty_reason": state.get("reason"),
            "last_empty_at": state.get("last_at"),
            "last_scout_task_id": state.get("last_task_id"),
            "last_summary": state.get("last_summary"),
            "release_when": "the line's candidate queue, its entry in research-lines.yaml, "
                            "a held-entry capability or its ledger topics change",
        }
        if isinstance(state.get("templates"), Mapping) and state["templates"]:
            base["templates"] = {template: int((item or {}).get("count") or 0)
                                 for template, item in state["templates"].items()}
        if program.scout_exhausted_after and count >= program.scout_exhausted_after:
            blocks[key] = {**base, "reason": "candidates_exhausted"}
            continue
        hours = program.scout_empty_backoff_hours
        delay = hours[min(count, len(hours)) - 1] if hours else 0.0
        if hours and count > len(hours) and delay > 0:
            # Past the configured steps the wait keeps doubling, up to the cap.
            delay = min(delay * 2 ** (count - len(hours)),
                        max(delay, program.supply.scout_backoff_max_hours))
        last = budget_control.parse_time(state.get("last_at"))
        if last is None or delay <= 0:
            continue
        until = last + timedelta(hours=delay)
        if moment < until:
            blocks[key] = {**base, "reason": "scout_empty_backoff", "until": _iso(until),
                           "backoff_hours": delay}
    return blocks


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
    max_cards: int,
    moment: datetime,
    preferred: Any = None,
) -> ScoutDecision:
    campaign = db.campaign(campaign_id) or {}
    stamp = _iso(moment)
    rotation = scout_key(project)
    line = project.research_line
    line_fields: dict[str, Any] = {}
    stage = target_stage.stage_for(db, line, settings)
    if line:
        line_fields = {
            "research_line": line,
            "target_stage": stage,
            "research_line_summary": line_summary(research_lines_document(paths, settings), line),
        }
        room = line_scout_room(status, document, line,
                               funnel_pool=funnel_pool(db, settings, line))
        if room is not None:
            # A line with its own slot limit asks for no more cards than it can admit.
            max_cards = max(1, min(max_cards, room))
            line_fields["line_free_slots"] = status.line_free_slots(line)
    # The campaign's task count keeps two scouts of one campaign scheduled within
    # the same second apart.
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
            "project_id": project.project_id,
            "domain": project.domain,
            "card_schema": "openlabs.topic_card.v1",
            **line_fields,
            "max_cards": max_cards,
            "free_slots": status.free_slots,
            "candidate_pool": len(_proposed_pool(document)),
            "ledger_snapshot": _ledger_snapshot(document),
            "read_resources": program_read_resources(paths, settings, ledger),
            **asset_library.packet_fields(paths, settings, domains=[project.domain]),
            **({budget_control.PREFERRED_RUNNER_FIELD: preferred.name,
                "preferred_family": preferred.family} if preferred is not None else {}),
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
        objective=(
            f"Scout research topics for the {project.domain} research program "
            f"({project.project_id})"
            + (
                f" within the research line `{line}` of registry/research-lines.yaml (read it "
                "first: positioning, minimum validation, venues with fee evidence, licence "
                "lists, avoided directions; each card needs research-line fields: "
                "feasibility_precheck, license_check, fee_check)"
                + (
                    ". Start from the line's paper_templates (packet research_line_summary."
                    "paper_templates; full entries in the direction file): pick a template, run "
                    "the occupancy search for a concrete system x property combination and record "
                    "it in `occupancy_search`; an unreported combination that meets the "
                    "template's minimum content is a valid card. Set `paper_template` to the "
                    "template id, and use `series` for a few adjacent systems sharing one "
                    "pipeline (one paper per card). Cite reusable assets of the template in "
                    "`reusable_assets` and lower the cost estimate accordingly"
                    + _queue_instruction(paths, settings, line, db)
                    + (". Under the NC aim these templates and queues are optional starting "
                       "points from the routine stage, not limits: a card that goes beyond them "
                       "(without paper_template) is welcome when it meets the NC bar"
                       if stage == target_stage.NC_AIM else "")
                    if line_templates(research_lines_document(paths, settings), line) else ""
                )
                if line else ""
            )
            + ". Read the packet at the input path: the topic ledger "
            "snapshot, the research-portfolio requirements, the team rejection ledger and the "
            "reusable-asset index when present. Return up to "
            f"{max_cards} topic cards in the result bundle field `topic_cards`, each following "
            "openlabs.topic_card.v1. Verify access to the decisive data yourself and add the "
            "access receipt as a hash-bound result artifact. Evidence files: the receipt and "
            "other small text notes (<= 5 MB) go in the campaign workspace; downloaded "
            "documents (PDF specifications, papers, data samples), logs and archives go under "
            "the task's transaction.artifact_staging_root, each declared in result.artifacts "
            "with its file:// URI and SHA-256 (a PDF in the workspace fails promotion). An "
            "empty `topic_cards` array is a "
            "valid outcome when nothing clears the bar. Do not start the research itself."
            + target_stage.scout_instruction(stage)
            + (nc_funnel.scout_floor_instruction(settings)
               if stage == target_stage.NC_AIM else "")
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
    meta = {LAST_SCOUT_KEY: stamp, f"{LAST_SCOUT_KEY}:{rotation}": stamp}
    if preferred is not None:
        meta[f"{SCOUT_FAMILY_KEY}:{rotation}@{preferred.family}"] = stamp
    db.update_meta(
        meta,
        events=[
            (
                "program",
                project.project_id,
                "topic_scout_scheduled",
                {"task_id": task_id, "domain": project.domain, "research_line": line,
                 "max_cards": max_cards, "free_slots": status.free_slots,
                 **({"preferred_runner": preferred.name, "preferred_family": preferred.family}
                    if preferred is not None else {})},
            )
        ],
    )
    return ScoutDecision(task_id=task_id, domain=project.domain, research_line=line)


@dataclass
class ScoutFamilies:
    """Model-family rotation of the scouts (``[program].scout_runners``, 2026-11-26).

    Each new scout asks for the configured runner whose family (1) no scout of the same line
    in flight uses, (2) the fewest scouts in flight use, (3) the line used least recently,
    (4) comes first in the list. Runners the router could not take now (quota, backoff) are
    passed over while another is usable. Without ``scout_runners`` nothing is preferred.
    """

    specs: list[Any]
    line_families: dict[str, Counter]
    flying: Counter
    stamps: dict[str, str]

    @classmethod
    def build(cls, db: FactoryDB, settings: FactorySettings, in_flight: list[dict[str, Any]],
              flight_keys: list[str], *, moment: datetime) -> "ScoutFamilies":
        names = [name for name in settings.program.scout_runners if name in settings.runners]
        specs = [settings.runners[name] for name in names]
        families = cls(specs=[], line_families={}, flying=Counter(), stamps={})
        if not specs:
            return families
        try:
            router = budget_control.QuotaRouter.build(db, settings, now=moment)
            usable = [spec for spec in specs if router.usable(spec, "ordinary")]
        except Exception:  # noqa: BLE001 - quota readings are advisory here
            usable = []
        families.specs = usable or specs
        families.stamps = db.meta_items(SCOUT_FAMILY_KEY + ":")
        for task, key in zip(in_flight, flight_keys):
            family = _scout_task_family(settings, task)
            if family:
                families.line_families.setdefault(key, Counter())[family] += 1
                families.flying[family] += 1
        return families

    def choose(self, key: str) -> Any:
        if not self.specs:
            return None
        line = self.line_families.get(key, Counter())
        order = {spec.name: index for index, spec in enumerate(self.specs)}
        return min(self.specs, key=lambda spec: (
            line[spec.family], self.flying[spec.family],
            self.stamps.get(f"{key}@{spec.family}", ""), order[spec.name]))

    def add(self, key: str, spec: Any) -> None:
        if spec is None:
            return
        self.line_families.setdefault(key, Counter())[spec.family] += 1
        self.flying[spec.family] += 1
        self.stamps[f"{key}@{spec.family}"] = _iso(_now_moment())


def _scout_task_family(settings: FactorySettings, task: Mapping[str, Any]) -> str | None:
    """Model family of an in-flight scout: its routed runner, else the one it asked for."""

    runner = str(task.get("runner") or "")
    if runner in settings.runners and task.get("runner_request") is not None:
        return settings.runners[runner].family
    try:
        packet = _read_object(Path(str(task.get("input_path") or "")))
    except (OSError, ValueError):
        return None
    preferred = str(packet.get(budget_control.PREFERRED_RUNNER_FIELD) or "")
    spec = settings.runners.get(preferred)
    return spec.family if spec is not None else None


def schedule_scouts(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    lead_short: bool,
    now: datetime | None = None,
) -> tuple[list[ScoutDecision], str | None]:
    """Schedule as many topic scouts as the program allows this tick.

    The worker ceiling is global. Each line gets at most one in-flight scout
    and uses its own interval, supply backoff and candidate coverage.
    """

    program = settings.program
    if not program.enabled:
        return [], "program_disabled"
    if program.polish_blocks_all():
        return [], POLISH_MODE_REASON
    if not budget_control.routing_enabled(settings):
        # Without provider routing the proposer and judge families cannot be
        # told apart, so the gate could not be independent.
        return [], "provider_routing_not_configured"
    ledger = open_topic_ledger(paths, program)
    document = ledger.read()
    status = slot_status(document, program, parked_program_projects(paths),
                         paused_topic_campaigns(db))
    if status.admission_paused:
        return [], "admission_paused"
    if status.free_slots <= 0:
        return [], "no_free_slot"
    if compute_backlogged(settings):
        return [], COMPUTE_BACKLOG_REASON
    all_projects = program_projects(paths)
    rotating = _rotation_projects(settings, all_projects)
    if program.polish_mode:
        # Polish mode with exempt (or supply-only) lines: only those lines scout.
        rotating = [project for project in rotating
                    if not program.polish_blocks_supply(project.research_line)]
        if not rotating:
            return [], POLISH_MODE_REASON
    blocked_lines = lines_not_ready(
        paths, settings, [project.research_line for project in rotating], db=db,
    )
    ready_projects = [project for project in rotating
                      if project.research_line not in blocked_lines]
    if rotating and not ready_projects:
        return [], "research_line_environment_not_ready"
    full_lines = lines_without_scout_room(status, document, {
        project.research_line: pool for project in ready_projects
        if (pool := funnel_pool(db, settings, project.research_line)) is not None})
    projects = [project for project in ready_projects if project.research_line not in full_lines]
    if ready_projects and not projects:
        return [], LINE_SLOTS_FULL_REASON
    if not projects:
        return [], "no_program_project"

    pool_by_key = Counter(_topic_key(topic) for topic in _proposed_pool(document))
    legacy_keys = {scout_key(project) for project in projects if not project.research_line}
    legacy_pool = sum(pool_by_key[key] for key in legacy_keys)
    low_water = program.candidate_pool_low_water
    needs = {
        scout_key(project): low_water - (pool_by_key[scout_key(project)]
                                        if project.research_line else legacy_pool)
        for project in projects
    }
    projects = [project for project in projects if needs[scout_key(project)] > 0]
    if not projects:
        return [], "candidate_pool_at_low_water"
    if lead_short:
        return [], "lead_quota_short"

    in_flight = _program_tasks(db, statuses=IN_FLIGHT_STATUSES, where="AND task_type=?",
                               parameters=(SCOUT_TASK_TYPE,))
    flight_keys = [scout_task_key(db, task) for task in in_flight]
    per_line = max(1, int(program.max_scouts_per_line))
    flight_count = Counter(flight_keys)
    # A line takes up to ``max_scouts_per_line`` scouts at once (one by default).
    busy = {key for key, count in flight_count.items() if count >= per_line}
    legacy_in_flight = sum(key in legacy_keys for key in flight_keys)
    moment = now or _now_moment()
    stamps = db.meta_items(LAST_SCOUT_KEY + ":")
    recent = set()
    for project in projects:
        key = scout_key(project)
        if flight_count.get(key):
            # A line with a scout in flight and room for another (max_scouts_per_line > 1):
            # the next one runs beside it on another model family, not after the interval.
            continue
        last_stamp = _scout_stamp(stamps, key)
        if not stamps and not project.research_line and program.max_concurrent_scouts == 1:
            last_stamp = db.meta_get(LAST_SCOUT_KEY)
        last = budget_control.parse_time(last_stamp)
        interval = program.line_scout_min_interval_hours.get(
            project.research_line or "", program.scout_min_interval_hours
        )
        if last is not None and moment - last < timedelta(hours=interval):
            recent.add(key)
    supply_blocks = scout_supply_blocks(db, paths, settings, projects, document, moment=moment)
    for key, block in nc_funnel.scout_blocks(db, paths, settings, projects, document,
                                             moment=moment).items():
        supply_blocks.setdefault(key, block)
    blocked_keys = frozenset(supply_blocks)
    expected = expected_cards_per_scout(db, settings, document) if legacy_keys else 1.0
    legacy_missing = low_water - legacy_pool - legacy_in_flight * expected
    if legacy_missing <= 0 and all(not project.research_line for project in projects):
        return [], "candidate_pool_covered_by_scouts"
    room = program.max_concurrent_scouts - len(in_flight)
    if room <= 0:
        return [], "scout_in_flight" if program.max_concurrent_scouts == 1 else "max_concurrent_scouts"
    legacy_wanted = max(0, min(room, math.ceil(legacy_missing / expected)))
    legacy_max_cards = max(1, math.ceil(legacy_missing / max(1, legacy_wanted)))
    legacy_scheduled = 0
    scheduled: list[ScoutDecision] = []
    reason: str | None = None
    families = ScoutFamilies.build(db, settings, in_flight, flight_keys, moment=moment)
    while len(scheduled) < room:
        if legacy_scheduled >= legacy_wanted:
            projects = [project for project in projects if project.research_line]
        # Breadth first: every line without a scout gets one before a line gets its second.
        doubled = frozenset(key for key, count in flight_count.items() if count > 0)
        chosen = _choose_scout_project(
            db, settings, projects, document,
            exclude=frozenset(busy | recent) | blocked_keys | doubled,
        ) or _choose_scout_project(
            db, settings, projects, document, exclude=frozenset(busy | recent) | blocked_keys
        )
        if chosen is None:
            if not projects:
                reason = "candidate_pool_covered_by_scouts"
            elif blocked_keys and _choose_scout_project(
                db, settings, projects, document, exclude=frozenset(busy | recent)
            ) is not None:
                reason = _supply_block_reason(supply_blocks)
            elif _choose_scout_project(db, settings, projects, document) is None:
                reason = "no_program_project"
            elif _choose_scout_project(db, settings, projects, document, exclude=frozenset(busy)) is None:
                reason = "scout_in_flight"
            else:
                reason = "scout_min_interval"
            break
        project, campaign_id = chosen
        key = scout_key(project)
        preferred = families.choose(key)
        decision = _schedule_one_scout(
            db, paths, settings, document=document, ledger=ledger, status=status,
            project=project, campaign_id=campaign_id,
            max_cards=needs[key] if project.research_line else legacy_max_cards,
            moment=moment, preferred=preferred,
        )
        scheduled.append(decision)
        flight_count[key] += 1
        families.add(key, preferred)
        if flight_count[key] >= per_line or not project.research_line:
            busy.add(key)
        if not project.research_line:
            legacy_scheduled += 1
    if len(scheduled) == room and program.max_concurrent_scouts > 1:
        reason = "max_concurrent_scouts"
    return scheduled, reason


def _supply_block_reason(blocks: Mapping[str, Mapping[str, Any]]) -> str:
    """``candidates_exhausted`` when every blocked line is exhausted, else the backoff."""

    if blocks and all(item.get("reason") in EXHAUSTED_REASONS for item in blocks.values()):
        if all(item.get("reason") == "candidate_queue_empty" for item in blocks.values()):
            return "candidate_queue_empty"
        return "candidates_exhausted"
    reasons = {str(item.get("reason")) for item in blocks.values()}
    if len(reasons) == 1 and reasons & {"funnel_stall_backoff", "scout_weekly_budget"}:
        return reasons.pop()
    return "scout_empty_backoff"


# A line whose supply is used up: reported as such (tick report program.line_supply).
EXHAUSTED_REASONS = frozenset({"candidates_exhausted", "candidate_queue_empty"})


def queue_supply_empty(
    paths: WorkspacePaths,
    settings: FactorySettings,
    line: str,
    document: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Why a line's enumerated queues offer a scout nothing to draw (None: they do).

    Only for a line whose every paper template draws from a candidate queue (a scout of a
    template without one may still search). An entry counts as drawable when its
    ``ledger_occupancy`` is free or reopenable (or, without one, the ledger has no topic
    of it), the target memory does not hold it (``supply_screen.failed_targets``), or it is a
    held entry whose capability is met this tick.
    """

    lines_document = research_lines_document(paths, settings)
    templates = [str(item.get("id") or "") for item in line_templates(lines_document, line)]
    queues = queued_templates(lines_document, line)
    if not queues or any(template not in queues for template in templates if template):
        return None
    if any(held_queue_releases(paths, settings, line, queues).values()):
        return None
    taken = ledger_queue_entries(document, line) if _queues_without_occupancy(queues) else {}
    failed = (supply_screen.failed_targets(document, line, queues)
              if settings.program.supply.target_memory else {})
    drawable = 0
    for path in sorted(set(queues.values())):
        try:
            queue = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None  # unreadable: let the scout find out
        for item in (queue.get("candidates") if isinstance(queue, Mapping) else None) or []:
            if not isinstance(item, Mapping):
                continue
            entry_id = str(item.get("entry_id") or item.get("batch_id") or "")
            occupancy = item.get("ledger_occupancy")
            free = (str(occupancy.get("state") or "free") in {"free", "reopenable"}
                    if isinstance(occupancy, Mapping) else entry_id not in taken)
            if free and entry_id.upper() not in failed:
                drawable += 1
    if drawable:
        return None
    return {"drawable": 0, "templates": sorted(queues), "failed_targets": len(failed),
            "queues": sorted(set(queues.values()))}


def maybe_schedule_scout(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    lead_short: bool,
    now: datetime | None = None,
) -> ScoutDecision:
    """The first scout scheduled this call, or the reason none was."""

    scheduled, reason = schedule_scouts(db, paths, settings, lead_short=lead_short, now=now)
    if scheduled:
        return scheduled[0]
    return ScoutDecision(reason=reason)


# --------------------------------------------------------------------------- card intake


def _card_metadata(
    project: ProjectConfig,
    card: Mapping[str, Any],
    *,
    source_task_id: str | None,
    provider: str,
    proposer_task_id: str | None = None,
) -> dict[str, Any]:
    venues = card.get("venues") if isinstance(card.get("venues"), Mapping) else {}
    line = str(card.get("research_line") or "").strip()
    author = proposer_task_id or source_task_id
    return {
        **({"research_line": line} if line else {}),
        "program_project_id": project.project_id,
        "source_task_id": source_task_id,
        "proposer_provider": provider,
        **({"proposer_task_id": author} if author else {}),
        "routine_fallback": venues.get("routine") if isinstance(venues, Mapping) else None,
        "cost_estimate": card.get("cost_estimate"),
    }


# Docker marks every container with this file; tests override it.
CONTAINER_MARKER = Path("/.dockerenv")


def available_compute_locations(settings: FactorySettings) -> tuple[str, ...]:
    """Configured experiment locations, minus WSL mathematics inside a container."""

    allowed = settings.program.compute_locations
    if CONTAINER_MARKER.exists():
        allowed = tuple(item for item in allowed if item != "wsl_math")
    return allowed


def compute_location_problem(settings: FactorySettings, card: Mapping[str, Any]) -> str | None:
    """Deterministic refusal reason for a card this instance cannot run, else None."""

    allowed = available_compute_locations(settings)
    missing = [
        item for item in compute_plan_locations(card.get("cost_estimate"))
        if item not in allowed
    ]
    if not missing:
        return None
    return (
        "compute_location_unavailable:" + ",".join(missing)
        + " (this instance runs " + (", ".join(allowed) or "no location") + "; "
        + ("mathematics runs on the WSL host, not in the container"
           if "wsl_math" in missing else "see [program].compute_locations")
        + ")"
    )


def _store_card(
    paths: WorkspacePaths, project: ProjectConfig, card: Mapping[str, Any], *, invalid: bool = False
) -> Path:
    """Content-addressed copy of a registered card (the ledger keeps its hash).

    Format-invalid cards are kept too (``cards/invalid``) so their repair can read them.
    """

    digest = card_sha256(card)
    folder = _control_root(paths) / _token(project.project_id) / "cards"
    if invalid:
        folder = folder / "invalid"
    path = folder / f"topic-{digest[:16]}.json"
    if not path.is_file():
        atomic_write_json(path, dict(card))
    return path


def card_problems(
    paths: WorkspacePaths,
    settings: FactorySettings,
    card: Mapping[str, Any],
    *,
    receipt_digests: set[str] | None,
    ledger_document: Mapping[str, Any] | None = None,
    warnings: list[str] | None = None,
    stage: str = target_stage.RUN_IN,
) -> list[str]:
    """Every machine check of a card: contract, asset references, compute plan, receipt.

    Returns the errors that reject the card (see ``validate_topic_card``); checks that
    do not change what admission can judge are appended to ``warnings`` instead.
    With the ledger, a revision card must also answer every reopen condition of
    the topic it revises (a fixable format problem, so it goes to repair).
    """

    validation = validate_topic_card(card)
    errors = [*validation.errors, *target_stage.card_errors(card, stage)]
    notes = warnings if warnings is not None else []
    notes.extend(validation.warnings)
    template = str(card.get("paper_template") or "").strip()
    line = str(card.get("research_line") or "").strip()
    if template and line:
        known = {str(item.get("id")) for item in line_templates(
            research_lines_document(paths, settings), line)}
        if template not in known:
            notes.append(
                f"paper_template {template!r} is not a paper_templates id of research line {line}"
                + (f" (known: {', '.join(sorted(known))})" if known else " (the line has none)")
            )
    if card.get("revises") and ledger_document is not None:
        from .program import _revision_problem

        problem = _revision_problem(ledger_document, str(card["revises"]),
                                    card.get("condition_responses"))
        if problem.startswith("revision_misses_conditions:"):
            errors.append(
                "condition_responses must answer reopen condition(s) "
                f"{problem.split(':', 1)[1]} of {card['revises']}"
            )
    # A wrong or archived asset id is a reference slip; the gate sees the warning.
    notes.extend(asset_library.card_reference_errors(paths, settings, card))
    location_problem = compute_location_problem(settings, card)
    if location_problem is not None:
        errors.append(location_problem)
    decisive = card.get("decisive_analysis")
    receipt = decisive.get("access_receipt") if isinstance(decisive, Mapping) else None
    if isinstance(receipt, Mapping) and receipt.get("sha256"):
        digest = str(receipt.get("sha256"))
        if receipt_digests is not None and digest not in receipt_digests:
            errors.append(
                "decisive_analysis.access_receipt is not a hash-bound artifact of the scout result"
            )
        if receipt_digests is None:
            receipt_path = Path(str(receipt.get("path") or ""))
            if not receipt_path.is_absolute():
                receipt_path = paths.data / receipt_path
            if not receipt_path.is_file() or sha256_file(receipt_path) != digest:
                errors.append("decisive_analysis.access_receipt file is missing or differs")
    return errors


def intake_card(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    project: ProjectConfig,
    raw_card: Any,
    *,
    decided_by: str,
    provider: str,
    source_task_id: str | None,
    receipt_digests: set[str] | None,
    repair_of: str | None = None,
    revises: str | None = None,
    proposer_task_id: str | None = None,
) -> dict[str, Any]:
    """Validate one card and register it; return ``{topic_id, status, reason, errors}``.

    ``proposer_task_id``: the task that wrote the card's content when it is not
    ``source_task_id`` (a repaired card keeps its scout as author, so admission
    independence is judged against the scout's model, not the repair model's).

    A format-invalid card from a scout or revision task is recorded with
    ``card_repair.status = pending`` (one automatic repair follows); a card that
    is itself a repair (``repair_of``) or was submitted by hand is not repaired
    again. ``repair_of`` and ``revises`` are set by the control plane, so they
    are part of the card and give the repaired or revised card its own identity.
    """

    ledger = open_topic_ledger(paths, settings.program)
    card: dict[str, Any] = dict(raw_card) if isinstance(raw_card, Mapping) else {
        "invalid_card": raw_card
    }
    # Topic identity is the control plane's (card hash), never agent-chosen.
    card.pop("topic_id", None)
    card.pop("repair_of", None)
    card.pop("target_stage", None)
    card["domain"] = project.domain
    if project.research_line:
        # A line project's cards belong to its line, never an agent-chosen one.
        card["research_line"] = project.research_line
    if repair_of:
        card["repair_of"] = repair_of
    if revises:
        card["revises"] = revises
    card, normalized = normalize_topic_card(card)
    lines_document = research_lines_document(paths, settings) if card.get(
        "research_line") else None
    line_entry, template_entry = card_checks.line_specs(lines_document, card)
    card, filled = card_checks.fill_precheck_budget(card, line_entry, template_entry)
    normalized = [*normalized, *filled]
    if settings.program.card_compute_floor:
        # The line knows its typical cost; a tighter card is corrected, not frozen later.
        card, raised = card_checks.apply_compute_floor(
            card, card_checks.compute_floor(line_entry, template_entry))
        normalized = [*normalized, *raised]
    stage = target_stage.stage_for(db, card.get("research_line"), settings)
    if stage in target_stage.GRADED_STAGES:
        card["target_stage"] = stage
    warnings: list[str] = []
    errors = card_problems(paths, settings, card, receipt_digests=receipt_digests,
                           ledger_document=ledger.read(), warnings=warnings, stage=stage)
    metadata = _card_metadata(project, card, source_task_id=source_task_id, provider=provider,
                              proposer_task_id=proposer_task_id)
    if normalized or warnings:
        # Mechanical fixes and non-blocking gaps travel with the card to the gate.
        metadata["card_check"] = {"normalized": normalized[:20], "warnings": warnings[:40]}
    if repair_of:
        metadata["repair_of"] = repair_of
    repairable = source_task_id is not None and not repair_of
    if errors:
        return _record_invalid(db, paths, ledger, project, card, errors=errors,
                               decided_by=decided_by, metadata=metadata, repairable=repairable)
    metadata["card_path"] = str(_store_card(paths, project, card))
    # Early screens (2026-11-20, W1): target memory, capability table, data coverage.
    rejection, screen_errors, screen_fields = supply_screen.screen_card(
        paths, settings, card, line_entry, template_entry, ledger.read())
    if screen_fields:
        metadata["card_check"] = {**metadata.get("card_check", {"normalized": [],
                                                               "warnings": []}),
                                  **screen_fields}
    if rejection is None:
        # NC funnel level 1 (2026-11-25): thresholds, data catalogue, capacity, near duplicates.
        rejection, screen_errors, nc_fields = nc_funnel.screen_card(
            settings, card, line_entry, ledger.read(), stage)
        if nc_fields:
            metadata["card_check"] = {**metadata.get("card_check", {"normalized": [],
                                                                   "warnings": []}),
                                      **nc_fields}
    if rejection is not None:
        outcome = _record_invalid(
            db, paths, ledger, project, card, errors=screen_errors, decided_by=decided_by,
            metadata=metadata, repairable=False, reason=rejection,
            not_repairable_reason=rejection,
        )
        return {**outcome, "screen": rejection}
    precheck = _run_card_precheck(paths, settings, project.project_id, card, line_entry,
                                  card_path=Path(metadata["card_path"]))
    if precheck is not None:
        precheck["attempts"] = 1
        metadata["card_check"] = {**metadata.get("card_check", {"normalized": [],
                                                               "warnings": []}),
                                  "precheck": precheck}
        if precheck["status"] == "fail":
            outcome = _record_invalid(
                db, paths, ledger, project, card,
                errors=["card_precheck_failed: " + card_checks.precheck_reasons(precheck)],
                decided_by=decided_by, metadata=metadata, repairable=False,
                reason="card_precheck_failed", not_repairable_reason="card_precheck_failed",
            )
            return {**outcome, "precheck": "fail"}
        # An erroring precheck (infrastructure) leaves the card proposed but held from the
        # admission review; schedule_topic_admission retries it and reports it each tick.
    pilot = supply_screen.pilot_spec(line_entry, template_entry,
                                     str(card.get("paper_template") or "")) if (
        settings.program.supply.pilot) else None
    if pilot is not None:
        # The card waits for its ailab pilot (advance_pilots) before the admission review.
        metadata["card_check"] = {**metadata.get("card_check", {"normalized": [],
                                                               "warnings": []}),
                                  "pilot": supply_screen.initial_pilot(pilot, settings)}
    try:
        decision = propose_topic(ledger, card, db=db, decided_by=decided_by, metadata=metadata)
    except TopicLedgerError as exc:
        return _record_invalid(db, paths, ledger, project, card, errors=[str(exc)],
                               decided_by=decided_by, metadata=metadata, repairable=repairable)
    result = {
        "topic_id": decision.topic_id,
        "status": decision.status,
        "reason": decision.reason,
        "errors": [],
        "duplicate_of": list(decision.duplicate_of),
    }
    if precheck is not None:
        result["precheck"] = precheck["status"]
        if precheck["status"] == "error":
            result["precheck_error"] = card_checks.precheck_reasons(precheck)
    return result


def _record_invalid(
    db: FactoryDB,
    paths: WorkspacePaths,
    ledger: TopicLedger,
    project: ProjectConfig,
    card: Mapping[str, Any],
    *,
    errors: list[str],
    decided_by: str,
    metadata: dict[str, Any],
    repairable: bool,
    reason: str = "card_invalid",
    not_repairable_reason: str | None = None,
) -> dict[str, Any]:
    values = dict(metadata)
    values["card_path"] = str(_store_card(paths, project, card, invalid=True))
    values["card_repair"] = (
        {"status": "pending", "errors": list(errors)} if repairable
        else {"status": "not_repairable",
              "reason": not_repairable_reason or (
                  "repair_failed" if card.get("repair_of") else "manual_or_unbound_card")}
    )
    decision = record_rejected_card(
        ledger, card, db=db, decided_by=decided_by, errors=errors, metadata=values,
        reason=reason,
    )
    return {"topic_id": decision.topic_id, "status": "rejected", "reason": reason,
            "errors": errors, "card_repair": values["card_repair"]["status"]}


def _run_card_precheck(
    paths: WorkspacePaths,
    settings: FactorySettings,
    project_id: str,
    card: Mapping[str, Any],
    line_entry: Mapping[str, Any],
    *,
    card_path: Path,
) -> dict[str, Any] | None:
    """The line's ``admission_precheck`` of one card (None when none is declared)."""

    if not settings.program.card_precheck:
        return None
    spec = card_checks.precheck_spec(line_entry, str(card.get("paper_template") or ""))
    if spec is None:
        return None
    digest = card_sha256(card)
    output_dir = (_control_root(paths) / _token(project_id) / "prechecks"
                  / f"topic-{digest[:16]}")
    return card_checks.run_precheck(
        spec, card=card, card_path=card_path, output_dir=output_dir, data_root=paths.data,
        max_seconds=settings.program.card_precheck_max_seconds,
    )


def precheck_statistics(document: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    """Per line: cards rejected by its admission precheck, and cards waiting on an error."""

    stats: dict[str, dict[str, int]] = {}
    for topic in document.get("topics") or []:
        if not isinstance(topic, Mapping):
            continue
        line = str(topic.get("research_line") or "")
        rejected = (topic.get("status") == "rejected"
                    and last_rejection_reason(topic) == "card_precheck_failed")
        waiting = topic.get("status") == "proposed" and precheck_held(topic)
        if rejected or waiting:
            entry = stats.setdefault(line, {"rejected": 0, "waiting_on_error": 0})
            entry["rejected" if rejected else "waiting_on_error"] += 1
    return stats


def precheck_held(topic: Mapping[str, Any]) -> bool:
    """A proposed card whose line precheck erred (infrastructure) waits, unreviewed."""

    check = topic.get("card_check") if isinstance(topic.get("card_check"), Mapping) else {}
    precheck = check.get("precheck") if isinstance(check.get("precheck"), Mapping) else {}
    return str(precheck.get("status") or "") == "error"


def retry_held_prechecks(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: Any,
) -> list[dict[str, Any]]:
    """Re-run the erred prechecks of waiting proposed cards (once per tick each).

    pass -> the card goes to the admission review as usual; fail -> it is rejected
    (``card_precheck_failed``); still an error -> it keeps waiting and the tick reports it.
    """

    ledger = open_topic_ledger(paths, settings.program)
    held = [topic for topic in ledger.read().get("topics") or []
            if isinstance(topic, Mapping) and topic.get("status") == "proposed"
            and precheck_held(topic)]
    if not held:
        return []
    document = research_lines_document(paths, settings)
    outcomes: list[dict[str, Any]] = []
    for topic in held:
        topic_id = str(topic["topic_id"])
        card_path = Path(str(topic.get("card_path") or ""))
        previous = dict(topic["card_check"]["precheck"])
        attempts = int(previous.get("attempts") or 1) + 1
        try:
            card = _read_object(card_path)
            line_entry, _template = card_checks.line_specs(document, card)
            result = _run_card_precheck(paths, settings,
                                        str(topic.get("program_project_id") or "program"),
                                        card, line_entry, card_path=card_path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            result = {"status": "error", "error": f"could not re-read the card: {exc}"}
        if result is None:
            # The line no longer declares a precheck (or it was switched off): release.
            result = {**previous, "status": "not_declared"}
        result["attempts"] = attempts
        check = {**dict(topic.get("card_check") or {}), "precheck": result}
        outcome = {"topic_id": topic_id, "status": result["status"], "attempts": attempts}
        record_topic_note(ledger, topic_id, db=db, event_type="card_precheck_recorded",
                          reason=f"card_precheck_{result['status']}",
                          decided_by="orchestrator:admission_precheck",
                          detail={"attempts": attempts,
                                  "reasons": card_checks.precheck_reasons(result)},
                          updates={"card_check": check},
                          key=f"card_precheck:{topic_id}:{attempts}")
        if result["status"] == "fail":
            reject_topic(ledger, topic_id, db=db, reason="card_precheck_failed",
                         decided_by="orchestrator:admission_precheck")
        if result["status"] == "error":
            report.errors.append(
                f"Admission precheck of {topic_id} failed to run (attempt {attempts}; the card "
                f"waits, not reviewed): {card_checks.precheck_reasons(result)}")
        outcomes.append(outcome)
    return outcomes


def register_scout_results(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
) -> list[dict[str, Any]]:
    """Register the cards of every succeeded, not yet registered scout result."""

    outcomes: list[dict[str, Any]] = []
    done = db.meta_items(SCOUT_REGISTERED_PREFIX)
    placeholders = ",".join("?" for _ in CARD_TASK_TYPES)
    for task in _program_tasks(db, statuses=("succeeded",),
                               where=f"AND task_type IN ({placeholders})",
                               parameters=CARD_TASK_TYPES):
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
            # Never register cards from bytes the result gate did not see.
            db.update_meta(
                {SCOUT_REGISTERED_PREFIX + task_id: utc_now()},
                events=[("program", project.project_id, "topic_cards_unverifiable",
                         {"task_id": task_id, "result_path": str(result_path)})],
            )
            outcomes.append({"source_task_id": task_id, "topic_id": None, "status": "rejected",
                             "reason": "scout_result_not_hash_bound", "errors": []})
            continue
        payload = _read_object(result_path)
        cards = payload.get("topic_cards")
        cards = cards if isinstance(cards, list) else []
        provider = budget_control.family_of(settings, task.get("runner"))
        digests = set(artifact_digests(payload).values())
        task_type = str(task.get("task_type") or "")
        follow_up: dict[str, Any] = {}
        author_task_id: str | None = None
        if task_type != SCOUT_TASK_TYPE:
            follow_up = _follow_up_packet(task)
            # A repair or revision returns one card; it may reuse the original receipt.
            cards = cards[:1]
            digests |= {str(item) for item in follow_up.get("receipt_digests") or []}
        if task_type == REPAIR_TASK_TYPE and follow_up.get("repair_of"):
            # A format repair (light tier, possibly the other family) does not make the
            # repair model the card's author: admission stays independent of the scout.
            original = find_topic(open_topic_ledger(paths, settings.program).read(),
                                  str(follow_up["repair_of"]))
            if original is not None:
                provider = str(original.get("proposer_provider") or provider)
                author_task_id = (str(original.get("proposer_task_id")
                                      or original.get("source_task_id") or "") or None)
        task_outcomes = [
            {"source_task_id": task_id, **intake_card(
                db, paths, settings, project, card, decided_by=task_id, provider=provider,
                source_task_id=task_id, receipt_digests=digests,
                repair_of=follow_up.get("repair_of") if task_type == REPAIR_TASK_TYPE else None,
                revises=(
                    follow_up.get("revision_of") if task_type == REVISION_TASK_TYPE
                    else follow_up.get("revises")
                ),
                proposer_task_id=author_task_id,
            )}
            for card in cards
        ]
        if task_type != SCOUT_TASK_TYPE:
            _close_follow_up(db, paths, settings, task, follow_up, task_outcomes)
        outcomes.extend(task_outcomes)
        db.update_meta(
            {SCOUT_REGISTERED_PREFIX + task_id: utc_now()},
            events=[
                (
                    "program",
                    project.project_id,
                    "topic_cards_registered",
                    {"task_id": task_id, "cards": len(cards), "outcomes": task_outcomes},
                )
            ],
        )
    return outcomes


def _follow_up_packet(task: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(str(task.get("input_path") or ""))
    try:
        packet = _read_object(path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {}
    if packet.get("schema_version") not in (REPAIR_PACKET_SCHEMA, REVISION_PACKET_SCHEMA):
        return {}
    return packet


def _close_follow_up(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    task: Mapping[str, Any],
    packet: Mapping[str, Any],
    outcomes: list[dict[str, Any]],
) -> None:
    """Record on the original topic what its repair or revision task produced."""

    task_id = str(task["task_id"])
    repair = str(task.get("task_type")) == REPAIR_TASK_TYPE
    original = str((packet.get("repair_of") if repair else packet.get("revision_of")) or "")
    if not original:
        return
    ledger = open_topic_ledger(paths, settings.program)
    if ledger.topic(original) is None:
        return
    outcome = outcomes[0] if outcomes else None
    if outcome is None:
        status = "failed" if repair else "declined"
    elif outcome.get("status") == "proposed":
        status = "resubmitted"
    elif not repair and outcome.get("card_repair") == "pending":
        status = "card_repair_pending"  # the revised card gets its own format repair
    else:
        status = "failed"
    field = "card_repair" if repair else "revision"
    current = dict((ledger.topic(original) or {}).get(field) or {})
    state = {**current, "status": status, "task_id": task_id,
             "topic_id": outcome.get("topic_id") if outcome else None,
             "finished_at": utc_now()}
    if outcome is not None and outcome.get("errors"):
        state["errors"] = list(outcome["errors"])[:20]
    record_topic_note(
        ledger, original, db=db, event_type=f"topic_{field}_{status}",
        reason=f"{field}_{status}", decided_by=task_id,
        detail={"task_id": task_id, "topic_id": state["topic_id"],
                "outcome_reason": outcome.get("reason") if outcome else "no_card_returned"},
        updates={field: state}, key=f"{field}:{original}:{task_id}",
    )


def submit_topic_card(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    project_path: Path,
    card: Mapping[str, Any],
    *,
    submitted_by: str,
) -> dict[str, Any]:
    """Register a human-written card; it then waits for the admission gate."""

    project = load_project(project_path)
    if not project.program:
        raise ValueError("cards are submitted to a research-program project (program: true)")
    return intake_card(
        db, paths, settings, project, card, decided_by=f"manual:{submitted_by}",
        provider=HUMAN_PROVIDER, source_task_id=None, receipt_digests=None,
    )


# --------------------------------------------------------------------------- repair, revision


def _digest_id(*parts: Any) -> str:
    return hashlib.sha256("\0".join(str(part) for part in parts).encode()).hexdigest()


def _project_of(paths: WorkspacePaths, topic: Mapping[str, Any]) -> ProjectConfig | None:
    wanted = str(topic.get("program_project_id") or "")
    for project in program_projects(paths):
        if project.project_id == wanted:
            return project
    return None


def _result_cards(db: FactoryDB, task_id: str) -> tuple[list[Any], set[str], dict[str, Any]]:
    """Cards and artifact digests of a hash-verified card-task result (else empty)."""

    task = db.task(task_id) if task_id else None
    if task is None:
        return [], set(), {}
    result_path = Path(str(task.get("result_path") or ""))
    expected = str(task.get("result_sha256") or "")
    if not result_path.is_file() or not expected or sha256_file(result_path) != expected:
        return [], set(), dict(task)
    try:
        payload = _read_object(result_path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return [], set(), dict(task)
    cards = payload.get("topic_cards")
    return (cards if isinstance(cards, list) else [],
            set(artifact_digests(payload).values()), dict(task))


def _original_card(
    db: FactoryDB, paths: WorkspacePaths, topic: Mapping[str, Any], project: ProjectConfig
) -> tuple[dict[str, Any] | None, set[str]]:
    """The topic's stored card (or the matching card of its source result) and receipt digests."""

    cards, digests, task = _result_cards(db, str(topic.get("source_task_id") or ""))
    packet = _follow_up_packet(task) if task else {}
    digests |= {str(item) for item in packet.get("receipt_digests") or []}
    card_path = Path(str(topic.get("card_path") or ""))
    if card_path.is_file():
        try:
            stored = _read_object(card_path)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            stored = None
        if stored is not None and card_sha256(stored) == topic.get("card_sha256"):
            return stored, digests
    for raw in cards:
        if not isinstance(raw, Mapping):
            continue
        card = dict(raw)
        card.pop("topic_id", None)
        card.pop("repair_of", None)
        card["domain"] = project.domain
        if project.research_line:
            card["research_line"] = project.research_line
        if packet.get("revision_of"):
            card["revises"] = packet["revision_of"]
        if card_sha256(card) == topic.get("card_sha256"):
            return card, digests
    return None, digests


def _note_state(
    db: FactoryDB, ledger: TopicLedger, topic_id: str, field: str, state: Mapping[str, Any],
    *, decided_by: str,
) -> None:
    status = str(state.get("status") or "")
    record_topic_note(
        ledger, topic_id, db=db, event_type=f"topic_{field}_{status}", reason=f"{field}_{status}",
        decided_by=decided_by,
        detail={key: state.get(key) for key in ("task_id", "topic_id", "mode", "reason")
                if state.get(key) is not None},
        updates={field: dict(state)},
        key=f"{field}:{topic_id}:{status}:{state.get('task_id') or state.get('topic_id') or ''}",
    )


def _settle_task_state(
    db: FactoryDB, ledger: TopicLedger, topic: Mapping[str, Any], field: str
) -> bool:
    """A scheduled repair/revision whose task ended without a result is recorded as failed.

    Returns True while the task is still pending (queued, running or succeeded but
    not yet registered).
    """

    state = dict(topic.get(field) or {})
    task = db.task(str(state.get("task_id") or ""))
    if task is not None and str(task.get("status")) not in TERMINAL_FAILED_STATUSES:
        return True
    _note_state(db, ledger, str(topic["topic_id"]), field,
                {**state, "status": "failed",
                 "reason": f"task_{task.get('status') if task else 'missing'}"},
                decided_by=f"program:{field}")
    return False


def schedule_card_repairs(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Give each format-invalid scout or revision card one repair.

    The card is first checked again under the current contract (a check that was
    relaxed may now pass it, at no model cost); otherwise a light repair task gets
    the card and its errors and returns one corrected card. A repaired card that is
    still invalid is final (``card_repair.status = not_repairable``).
    """

    if settings.program.polish_blocks_all():
        return []
    ledger = open_topic_ledger(paths, settings.program)
    moment = now or _now_moment()
    outcomes: list[dict[str, Any]] = []
    for topic in topics_by_status(ledger.read(), "rejected"):
        topic_id = str(topic["topic_id"])
        if last_rejection_reason(topic) != "card_invalid" or topic.get("repair_of"):
            continue
        if settings.program.polish_blocks_supply(topic.get("research_line")):
            continue
        state = topic.get("card_repair")
        if isinstance(state, Mapping):
            if state.get("status") == "scheduled":
                _settle_task_state(db, ledger, topic, "card_repair")
                continue
            if state.get("status") != "pending":
                continue
        else:
            # Recorded before automatic repair existed: repair recent scout cards once.
            proposed_at = budget_control.parse_time(_proposal_time(topic))
            if (not topic.get("source_task_id") or proposed_at is None
                    or moment - proposed_at > LEGACY_REPAIR_WINDOW):
                continue
        project = _project_of(paths, topic)
        card, digests = (None, set()) if project is None else _original_card(
            db, paths, topic, project)
        if project is None or card is None:
            _note_state(db, ledger, topic_id, "card_repair",
                        {"status": "unrecoverable",
                         "reason": "project_missing" if project is None else "card_not_found"},
                        decided_by="program:card_repair")
            outcomes.append({"topic_id": topic_id, "outcome": "unrecoverable"})
            continue
        provider = str(topic.get("proposer_provider") or HUMAN_PROVIDER)
        source_task_id = str(topic.get("source_task_id") or "") or None
        errors = card_problems(
            paths, settings, normalize_topic_card(card)[0],
            receipt_digests=digests, ledger_document=ledger.read(),
            stage=target_stage.stage_for(db, project.research_line, settings),
        )
        if not errors:
            # The card passes the current checks as it stands: register it again.
            outcome = intake_card(
                db, paths, settings, project, card, decided_by=f"card-repair:{topic_id}",
                provider=provider, source_task_id=source_task_id, receipt_digests=digests,
                repair_of=topic_id, revises=str(card.get("revises") or "") or None,
                proposer_task_id=str(topic.get("proposer_task_id") or "") or None,
            )
            status = "resubmitted" if outcome["status"] == "proposed" else "failed"
            _note_state(db, ledger, topic_id, "card_repair",
                        {"status": status, "mode": "revalidated", "topic_id": outcome["topic_id"],
                         "reason": outcome.get("reason")},
                        decided_by=f"card-repair:{topic_id}")
            outcomes.append({"topic_id": topic_id, "outcome": status, "mode": "revalidated",
                             "new_topic_id": outcome["topic_id"]})
            continue
        task_id = _enqueue_card_repair(db, paths, settings, topic=topic, project=project,
                                       card=card, errors=errors, digests=digests)
        if task_id is None:
            outcomes.append({"topic_id": topic_id, "outcome": "no_scout_campaign"})
            continue
        _note_state(db, ledger, topic_id, "card_repair",
                    {"status": "scheduled", "mode": "task", "task_id": task_id,
                     "errors": errors[:20]},
                    decided_by="program:card_repair")
        outcomes.append({"topic_id": topic_id, "outcome": "scheduled", "task_id": task_id})
    return outcomes


def _active_scout_campaign(db: FactoryDB, project: ProjectConfig) -> dict[str, Any] | None:
    scout_id = scout_workstream_id(project)
    campaign = db.campaign(scout_id) if scout_id else None
    if campaign is None or str(campaign.get("status") or "") != "active":
        return None
    return dict(campaign)


def _follow_up_policy(settings: FactorySettings, campaign: Mapping[str, Any]) -> dict[str, Any]:
    policy = workstream_policy(campaign)
    resources_value = policy.get("resources")
    resources = (
        ResourceVector.from_mapping(resources_value)
        if isinstance(resources_value, Mapping)
        else default_task_resources(settings)
    )
    return resources.to_dict()


def _enqueue_card_repair(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    topic: Mapping[str, Any],
    project: ProjectConfig,
    card: Mapping[str, Any],
    errors: list[str],
    digests: set[str],
) -> str | None:
    campaign = _active_scout_campaign(db, project)
    if campaign is None:
        return None
    topic_id = str(topic["topic_id"])
    task_id = f"card-repair:{_digest_id(topic_id)[:32]}"
    if db.task(task_id) is not None:
        return task_id
    line = project.research_line
    packet_path = (_control_root(paths) / _token(project.project_id) / "repair-packets"
                   / f"{_token(topic_id)}.json")
    ledger = open_topic_ledger(paths, settings.program)
    packet = _signed({
        "schema_version": REPAIR_PACKET_SCHEMA,
        "project_id": project.project_id,
        "domain": project.domain,
        "card_schema": "openlabs.topic_card.v1",
        **({"research_line": line,
            "research_line_summary": line_summary(research_lines_document(paths, settings), line)}
           if line else {}),
        "repair_of": topic_id,
        **({"revises": card.get("revises")} if card.get("revises") else {}),
        "card": dict(card),
        "errors": list(errors),
        "receipt_digests": sorted(digests),
        "read_resources": program_read_resources(paths, settings, ledger),
        "created_at": utc_now(),
    })
    atomic_write_json(packet_path, packet)
    db.enqueue_task(
        task_id=task_id,
        campaign_id=str(campaign["campaign_id"]),
        domain=project.domain,
        task_type=REPAIR_TASK_TYPE,
        objective=(
            f"A topic card returned by a scout of the {project.domain} research program failed "
            f"the control plane's format checks ({len(errors)} problem(s)). The packet at the "
            "input path has the card and the exact error list. Fix only those problems and "
            "return exactly one corrected card in the result field `topic_cards` "
            "(openlabs.topic_card.v1). Keep the question, data sources, primary endpoint and "
            "claims unchanged unless an error requires otherwise; do not invent citations, fee "
            "evidence or receipts (look them up, or drop the item an error points at when the "
            "card stays valid without it). The original data-access receipt still counts; a new "
            "one must be a hash-bound artifact of your result. If the card cannot be fixed "
            "without changing the topic, return `topic_cards: []` and say why. This is the "
            "card's only repair. Do not start the research."
            + target_stage.scout_instruction(target_stage.stage_for(
                db, project.research_line, settings))
        ),
        input_path=str(packet_path),
        skill_path=SCOUT_SKILL,
        runner=dispatch_runner(settings, REPAIR_TASK_TYPE, REPAIR_ROUTING_REASON, "cheap"),
        routing_reason=REPAIR_ROUTING_REASON,
        agent_role="researcher",
        session_mode="fresh",
        priority=int(campaign.get("priority") or 0) + 1,
        max_attempts=settings.max_attempts,
        max_wall_seconds=min(3_600, settings.max_task_wall_seconds),
        **_follow_up_policy(settings, campaign),
    )
    db.record_event_once("topic", topic_id, "topic_card_repair_scheduled",
                         {"task_id": task_id, "errors": errors[:20]}, event_key=task_id)
    return task_id


def schedule_revisions(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    lead_short: bool,
) -> tuple[list[dict[str, Any]], str | None]:
    """Queue one revision task per held or fixably rejected topic, while slots are free.

    At most ``max_concurrent_scouts`` revisions run at once. The revised card
    answers the recorded reopen conditions and goes to the gate, which checks
    only those conditions.
    """

    program = settings.program
    if not program.enabled:
        return [], "program_disabled"
    if program.polish_blocks_all():
        return [], POLISH_MODE_REASON
    if not budget_control.routing_enabled(settings):
        return [], "provider_routing_not_configured"
    ledger = open_topic_ledger(paths, program)
    document = ledger.read()
    pending: list[dict[str, Any]] = []
    for topic in topics_by_status(document, "rejected"):
        state = topic.get("revision") if isinstance(topic.get("revision"), Mapping) else {}
        if state.get("status") == "scheduled":
            _settle_task_state(db, ledger, topic, "revision")
            continue
        if state.get("status") not in (None, "eligible") or not revision_eligible(topic):
            continue
        if program.polish_blocks_supply(topic.get("research_line")):
            continue
        pending.append(topic)
    if not pending:
        return [], "no_revisable_topic"
    status = slot_status(document, program, parked_program_projects(paths),
                         paused_topic_campaigns(db))
    if status.admission_paused:
        return [], "admission_paused"
    if status.free_slots <= 0:
        return [], "no_free_slot"
    pending = [topic for topic in pending if not status.line_full(topic.get("research_line"))]
    if not pending:
        return [], LINE_SLOTS_FULL_REASON
    if lead_short:
        return [], "lead_quota_short"
    in_flight = _program_tasks(db, statuses=IN_FLIGHT_STATUSES, where="AND task_type=?",
                               parameters=(REVISION_TASK_TYPE,))
    room = max(1, program.max_concurrent_scouts) - len(in_flight)
    if room <= 0:
        return [], "max_concurrent_revisions"
    pending.sort(key=lambda item: (_proposal_time(item), str(item["topic_id"])))
    scheduled: list[dict[str, Any]] = []
    reason: str | None = None
    for topic in pending:
        if len(scheduled) >= room:
            reason = "max_concurrent_revisions"
            break
        project = _project_of(paths, topic)
        card, digests = (None, set()) if project is None else _original_card(
            db, paths, topic, project)
        campaign = _active_scout_campaign(db, project) if project is not None else None
        if project is None or card is None or campaign is None:
            _note_state(db, ledger, str(topic["topic_id"]), "revision",
                        {"status": "unavailable",
                         "reason": ("project_missing" if project is None else
                                    "card_not_found" if card is None else "no_scout_campaign")},
                        decided_by="program:revision")
            continue
        task_id = _enqueue_revision(db, paths, settings, ledger=ledger, topic=topic,
                                    project=project, campaign=campaign, card=card,
                                    digests=digests)
        _note_state(db, ledger, str(topic["topic_id"]), "revision",
                    {"status": "scheduled", "task_id": task_id},
                    decided_by="program:revision")
        scheduled.append({"topic_id": topic["topic_id"], "task_id": task_id})
    return scheduled, reason


def _numbered_conditions(topic: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {"condition": index, "type": item.get("type"), "description": item.get("description"),
         "answer_required": str(item.get("type")) not in AUTOMATIC_REOPEN_TYPES}
        for index, item in enumerate(topic.get("reopen_conditions") or [])
        if isinstance(item, Mapping)
    ]


def _enqueue_revision(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    ledger: TopicLedger,
    topic: Mapping[str, Any],
    project: ProjectConfig,
    campaign: Mapping[str, Any],
    card: Mapping[str, Any],
    digests: set[str],
) -> str:
    topic_id = str(topic["topic_id"])
    task_id = f"topic-revision:{_digest_id(topic_id)[:32]}"
    if db.task(task_id) is not None:
        return task_id
    line = project.research_line
    admission = topic.get("admission") if isinstance(topic.get("admission"), Mapping) else {}
    packet_path = (_control_root(paths) / _token(project.project_id) / "revision-packets"
                   / f"{_token(topic_id)}.json")
    packet = _signed({
        "schema_version": REVISION_PACKET_SCHEMA,
        "project_id": project.project_id,
        "domain": project.domain,
        "card_schema": "openlabs.topic_card.v1",
        "admission_policy": ADMISSION_POLICY_VERSION,
        **({"research_line": line,
            "research_line_summary": line_summary(research_lines_document(paths, settings), line)}
           if line else {}),
        "revision_of": topic_id,
        "target": {
            "topic_id": topic_id,
            "question": topic.get("question"),
            "rejection_reason": last_rejection_reason(topic),
            "card": dict(card),
            "reopen_conditions": _numbered_conditions(topic),
            "admission": {
                key: admission.get(key)
                for key in ("verdict", "strongest_rejection_reason", "closest_prior_work_checked",
                            "cost_judgement", "tier_rationale", "data_access_confirmed")
            },
            "revision_marker": topic.get("revision"),
        },
        "receipt_digests": sorted(digests),
        "ledger_snapshot": _ledger_snapshot(ledger.read()),
        "read_resources": program_read_resources(paths, settings, ledger),
        **asset_library.packet_fields(paths, settings, domains=[project.domain]),
        "created_at": utc_now(),
    })
    atomic_write_json(packet_path, packet)
    db.enqueue_task(
        task_id=task_id,
        campaign_id=str(campaign["campaign_id"]),
        domain=project.domain,
        task_type=REVISION_TASK_TYPE,
        objective=(
            f"Revise the topic card of {topic_id} ({project.domain} research program). The "
            "admission gate held it, or rejected it for a fixable reason, and recorded reopen "
            "conditions (packet `target.reopen_conditions`, numbered from 0). Do the cheap, "
            "outcome-blind work those conditions ask for (closest-work comparison, manifests, "
            "timing probes, fixed definitions, fee or ranking evidence; never compute the primary "
            "endpoint), then return exactly one revised card in `topic_cards` "
            "(openlabs.topic_card.v1) with `condition_responses`: one {condition: <index>, "
            "response: what changed and where the evidence is} for every condition whose "
            "answer_required is true. Keep the topic's question unless a condition requires "
            "narrowing it. The gate checks only whether these conditions are met, so answer each "
            "one concretely. When a condition cannot be met now (data not yet released, an "
            "external result pending), return `topic_cards: []` and say which and why. This is "
            "the topic's only revision. Do not start the research."
            + target_stage.scout_instruction(target_stage.stage_for(
                db, project.research_line, settings))
        ),
        input_path=str(packet_path),
        skill_path=SCOUT_SKILL,
        runner=dispatch_runner(settings, REVISION_TASK_TYPE, REVISION_ROUTING_REASON,
                               "balanced"),
        routing_reason=REVISION_ROUTING_REASON,
        agent_role="researcher",
        session_mode="fresh",
        priority=int(campaign.get("priority") or 0),
        max_attempts=settings.max_attempts,
        max_wall_seconds=settings.max_task_wall_seconds,
        **_follow_up_policy(settings, campaign),
    )
    db.record_event_once("topic", topic_id, "topic_revision_scheduled",
                         {"task_id": task_id}, event_key=task_id)
    return task_id


def mark_revisable(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    topic_id: str,
    *,
    decided_by: str,
    reason: str,
) -> bool:
    """Record that a judged rejection's defect is fixable: the topic may be revised once."""

    ledger = open_topic_ledger(paths, settings.program)
    topic = ledger.topic(topic_id)
    if topic is None:
        raise TopicLedgerError(f"unknown topic {topic_id}")
    if topic.get("status") != "rejected" or last_rejection_reason(topic) not in {
        "admission_rejected", "admission_hold", "cost_not_proportionate",
        "data_access_not_confirmed",
    }:
        raise TopicLedgerError(f"topic {topic_id} is not a judged rejection")
    return record_topic_note(
        ledger, topic_id, db=db, event_type="topic_marked_revisable", reason="fixable_defect",
        decided_by=decided_by, detail={"reason": reason},
        updates={"revision": {"eligible": True, "status": "eligible", "reason": reason,
                              "marked_by": decided_by, "marked_at": utc_now()}},
        key=f"marked_revisable:{topic_id}",
    )


def release_ready_holds(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
) -> list[dict[str, Any]]:
    """Release holds whose research line is now ``ready`` (no new card needed).

    A topic the gate admitted but the control plane held for the line's
    environment is admitted with the gate's recorded decision; a gate hold whose
    only reopen condition is the line's environment goes back to the gate. Holds
    with other open conditions wait for their revision card.

    Not under ``[program] polish_mode`` (2026-11-25, B3: P02): a released hold would go
    back to the gate or be admitted, i.e. new research, which polish mode stops.
    """

    if settings.program.polish_blocks_all():
        return []
    ledger = open_topic_ledger(paths, settings.program)
    lines_document = None
    outcomes: list[dict[str, Any]] = []
    for topic in topics_by_status(ledger.read(), "rejected"):
        if last_rejection_reason(topic) != "admission_hold":
            continue
        line = str(topic.get("research_line") or "").strip()
        if not line or settings.program.polish_blocks(line):
            continue
        if lines_document is None:
            lines_document = research_lines_document(paths, settings) or {}
        if environment_status(lines_document, line) != ENVIRONMENT_READY:
            continue
        if any(entry.get("reason") in {HOLD_RELEASE_ADMITTED, HOLD_RELEASE_FOR_REVIEW}
               for entry in topic.get("history") or []):
            continue
        topic_id = str(topic["topic_id"])
        admission = topic.get("admission") if isinstance(topic.get("admission"), Mapping) else {}
        kinds = {str(item.get("type")) for item in topic.get("reopen_conditions") or []
                 if isinstance(item, Mapping)}
        record_path = _admission_record_path(paths, topic_id)
        record = _read_object(record_path) if record_path.is_file() else {}
        preregistration = record.get("preregistration") if isinstance(
            record.get("preregistration"), Mapping) else {}
        decided_by = f"program:line-ready:{line}"
        gate_admitted = bool(admission.get("control_plane_hold")) and bool(
            preregistration.get("sha256"))
        own_conditions = kinds - AUTOMATIC_REOPEN_TYPES
        if gate_admitted and not set(_gate_condition_types(record)) - AUTOMATIC_REOPEN_TYPES:
            record_admission = record.get("admission") if isinstance(
                record.get("admission"), Mapping) else {}
            release_held_topic(
                ledger, topic_id, db=db, to_status="admitted", decided_by=decided_by,
                updates={"admission_task_id": record.get("review_task_id"),
                         "preregistration_sha256": str(preregistration["sha256"]),
                         "target_tier": record_admission.get("target_tier")},
            )
            outcomes.append({"topic_id": topic_id, "outcome": "admitted", "line": line})
        elif not own_conditions or admission.get("control_plane_hold"):
            release_held_topic(ledger, topic_id, db=db, to_status="proposed",
                               decided_by=decided_by)
            outcomes.append({"topic_id": topic_id, "outcome": "returned_to_gate", "line": line})
    return outcomes


def _gate_condition_types(record: Mapping[str, Any]) -> list[str]:
    admission = record.get("admission") if isinstance(record.get("admission"), Mapping) else {}
    return [str(item.get("type")) for item in admission.get("reopen_conditions") or []
            if isinstance(item, Mapping)]


# --------------------------------------------------------------------------- admission


def _source_id(topic: Mapping[str, Any]) -> str:
    return str(topic.get("source_task_id") or f"manual-card:{topic['topic_id']}")


def _proposal_time(topic: Mapping[str, Any]) -> str:
    history = topic.get("history") or []
    return str(history[0].get("at") or "") if history else ""


def schedule_topic_admission(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    campaign: Mapping[str, Any],
    *,
    epoch: int,
) -> ReviewSchedule:
    """Queue one admission review of this program's proposed topics.

    Worker tier by default (``portfolio_review:topic_admission``; user 2026-11-18),
    routed away from the proposer's model family.
    """

    if not settings.program.enabled:
        return ReviewSchedule(reason="program_disabled")
    if settings.program.polish_blocks_all():
        # Polish mode: proposed cards stay proposed; no admission review starts.
        return ReviewSchedule(reason=POLISH_MODE_REASON)
    if not budget_control.routing_enabled(settings):
        return ReviewSchedule(reason="admission_requires_provider_routing")
    if compute_backlogged(settings):
        # Admissions wait while the compute queues are backlogged (compute_backlog).
        return ReviewSchedule(reason=COMPUTE_BACKLOG_REASON)
    campaign_id = str(campaign["campaign_id"])
    project = load_project(str(campaign["project_config_path"]))
    if settings.program.polish_blocks_supply(project.research_line):
        # Polish mode with exempt (or supply-only) lines: only their cards are reviewed.
        return ReviewSchedule(reason=POLISH_MODE_REASON)
    ledger = open_topic_ledger(paths, settings.program)
    snapshot_document = ledger.read()
    proposed = [
        topic
        for topic in topics_by_status(snapshot_document, "proposed")
        if topic.get("program_project_id") == project.project_id
    ]
    # A card of a line whose environment is not ready stays proposed, unreviewed:
    # an admit could not start its precheck, so the review would only be held.
    blocked_lines = lines_not_ready(
        paths, settings, [topic.get("research_line") for topic in proposed], db=db)
    waiting_for_line = [topic for topic in proposed
                        if str(topic.get("research_line") or "") in blocked_lines]
    proposed = [topic for topic in proposed if topic not in waiting_for_line]
    # A card whose line admission precheck could not run waits for a retried precheck
    # (retry_held_prechecks); it is neither admitted unchecked nor rejected.
    waiting_for_precheck = [topic for topic in proposed if precheck_held(topic)]
    proposed = [topic for topic in proposed if topic not in waiting_for_precheck]
    # A card whose ailab pilot is pending or running waits for its verdict (advance_pilots).
    waiting_for_pilot = [topic for topic in proposed if supply_screen.pilot_held(topic)]
    proposed = [topic for topic in proposed if topic not in waiting_for_pilot]
    # An NC-aimed card waits for its prescreen (novelty + thresholds + kill test).
    waiting_for_prescreen = [topic for topic in proposed if nc_funnel.prescreen_held(topic)]
    proposed = [topic for topic in proposed if topic not in waiting_for_prescreen]
    in_flight = {
        str(task["task_id"]): task
        for task in _program_tasks(db, statuses=IN_FLIGHT_STATUSES,
                                   where="AND routing_reason=?",
                                   parameters=(ADMISSION_ROUTING_REASON,))
    }
    pending: list[dict[str, Any]] = []
    reviewing = 0
    for topic in proposed:
        attempts = list(topic.get("admission_attempts") or [])
        if attempts and _attempt_task_id(attempts[-1]) in in_flight:
            reviewing += 1  # already in a review that has not finished
            continue
        if len(attempts) >= MAX_ADMISSION_ATTEMPTS:
            reject_topic(
                ledger, str(topic["topic_id"]), db=db, reason="admission_undecided",
                decided_by=f"program:{campaign_id}",
            )
            continue
        pending.append(topic)
    if not pending:
        return ReviewSchedule(
            reason="admission_batches_in_flight" if reviewing
            else "research_line_environment_not_ready" if waiting_for_line
            else "admission_precheck_error" if waiting_for_precheck
            else "admission_pilot_pending" if waiting_for_pilot
            else "admission_prescreen_pending" if waiting_for_prescreen
            else "awaiting_topic_cards"
        )
    cap = settings.program.max_concurrent_admissions
    if cap > 0 and len(in_flight) >= cap:
        return ReviewSchedule(reason="max_concurrent_admissions")
    batch_counts = Counter(key for task in in_flight.values()
                           for key in admission_task_keys(db, task))
    slots = slot_status(snapshot_document, settings.program, parked_program_projects(paths),
                        paused_topic_campaigns(db))
    reservations = Counter(
        _topic_key(topic) for topic in _proposed_pool(snapshot_document)
        if (attempts := topic.get("admission_attempts"))
        and _attempt_task_id(attempts[-1]) in in_flight
    )
    below_batch_limit = [
        topic for topic in pending
        if batch_counts[_topic_key(topic)] < settings.program.max_admissions_per_line
    ]
    if not below_batch_limit:
        return ReviewSchedule(reason="max_admissions_per_line")
    pending = [
        topic for topic in below_batch_limit
        if (free := slots.line_free_slots(topic.get("research_line"))) is None
        or free > reservations[_topic_key(topic)]
    ]
    if not pending:
        return ReviewSchedule(reason=LINE_SLOTS_FULL_REASON)
    pending.sort(key=lambda item: (_proposal_time(item), str(item["topic_id"])))
    key = _topic_key(pending[0])
    line_free = slots.line_free_slots(pending[0].get("research_line"))
    pending = [topic for topic in pending if _topic_key(topic) == key]
    authors = {str(topic["topic_id"]): card_author(topic, snapshot_document)
               for topic in pending}
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
            raise ValueError(f"topic {topic['topic_id']} card file is missing: {card_path}")
        card = _read_object(card_path)
        if card_sha256(card) != topic.get("card_sha256"):
            raise ValueError(f"topic {topic['topic_id']} card file differs from the ledger")
        entry: dict[str, Any] = {
            "topic_id": topic["topic_id"],
            "source_result_id": _source_id(topic),
            "card_sha256": topic["card_sha256"],
            "proposer_provider": provider,
            "card": card,
            "target_stage": target_stage.stage_for(db, card.get("research_line"), settings),
        }
        if isinstance(topic.get("card_check"), Mapping):
            # Non-blocking gaps found at intake (audience evidence, licence notes, ...).
            entry["card_check"] = dict(topic["card_check"])
        revised = find_topic(snapshot_document, str(topic.get("revision_of") or ""))
        if revised is not None:
            # A revision card is checked against these conditions only.
            earlier = revised.get("admission") if isinstance(revised.get("admission"),
                                                             Mapping) else {}
            entry["revision_of"] = {
                "topic_id": revised["topic_id"],
                "rejection_reason": last_rejection_reason(revised),
                "reopen_conditions": _numbered_conditions(revised),
                "earlier_admission": {
                    key: earlier.get(key)
                    for key in ("verdict", "strongest_rejection_reason",
                                "closest_prior_work_checked", "review_task_id")
                },
            }
        if any(item.get("reason") in {HOLD_RELEASE_FOR_REVIEW}
               for item in topic.get("history") or []):
            entry["released_from_hold"] = {
                "reason": "research line environment became ready",
                "earlier_admission": topic.get("admission"),
            }
        entries.append(entry)
    asset_library.annotate_admission_entries(paths, settings, entries)
    line_ids = sorted({
        str(entry["card"].get("research_line"))
        for entry in entries if str(entry["card"].get("research_line") or "").strip()
    })
    lines_document = research_lines_document(paths, settings) if line_ids else None
    topic_ids = [str(entry["topic_id"]) for entry in entries]
    result_ids = sorted({str(entry["source_result_id"]) for entry in entries})
    digest = hashlib.sha256("\0".join(topic_ids + result_ids).encode()).hexdigest()
    latest = db.latest_task(campaign_id)
    task_id = _task_id(campaign_id, epoch, digest + (str(latest.get("task_id")) if latest else ""))
    if db.task(task_id) is not None:
        return ReviewSchedule(reason="review_already_scheduled")
    exclude = None if provider == HUMAN_PROVIDER else provider
    packet_path = _review_control_root(paths, campaign) / "review-packets" / f"{digest[:24]}.json"
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
            "topic_cards": entries,
            "proposer_provider": provider,
            "exclude_provider": exclude,
            # Read by the router when only one model family is configured.
            **_proposer_models_fields(
                db, settings, [authors[str(topic["topic_id"])][1] for topic in batch]),
            "admission_policy": ADMISSION_POLICY_VERSION,
            **(
                {"research_lines": {line: line_summary(lines_document, line)
                                    for line in line_ids}}
                if line_ids else {}
            ),
            "ledger_snapshot": _ledger_snapshot(ledger.read()),
            "read_resources": [
                *program_read_resources(paths, settings, ledger),
                # NC-aim cards are placed against the grading calibration set (one ruler).
                *[item for item in [nc_funnel.calibration_resource(paths)] if item and any(
                    entry["target_stage"] == target_stage.NC_AIM for entry in entries)],
            ],
            **asset_library.packet_fields(
                paths, settings, domains=[project.domain],
                data_sources=[
                    source for entry in entries
                    for source in data_source_identifiers(entry["card"].get("data_sources"))
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
        objective=(
            f"Act as the admission gate of the {project.domain} research program "
            f"({ADMISSION_POLICY_VERSION}; follow the skill). Judge every topic card in the "
            f"review packet ({len(entries)} card(s)) against the tier it targets. A routine "
            "(Zones 3-4) card is admitted when, after you check the closest prior work "
            "yourself, a stated incremental difference survives, the decisive data is confirmed "
            "accessible, the design can identify the claimed effect, and it fits its research "
            "line, avoid list and licence lists. Reject only for a fatal problem (prior work "
            "already did the comparison, data unobtainable, unidentifiable and not fixable by "
            "revision, blacklisted licence, beyond computational work); turn fixable gaps "
            "(pre-registration details, manifests, multiplicity, a missing baseline, itemized "
            "cost, venue fee or ranking evidence) into `admission.conditions` on an admit. "
            "Return exactly one candidate_branches entry per card with candidate_id and topic_id "
            "set to the card's topic_id, source_result_ids = [its source_result_id], title, "
            "objective, rationale and an `admission` object (verdict admit/reject/hold, "
            "target_tier, tier_rationale, strongest_rejection_reason, closest_prior_work_checked, "
            "data_access_confirmed, cost_judgement, preregistration with its sha256, "
            "conditions [{description, due: before_precheck|before_decisive_analysis|"
            "before_submission}], reopen_conditions, and revisable true on a reject whose defect "
            "a revision could fix). An entry with `revision_of` is a revision card: check only "
            "whether its condition_responses meet the listed reopen conditions, not the whole "
            "topic again. An idle slot has a cost; the feasibility precheck is the cheap stop. "
            "Do not start the research."
            + (
                " Research-line cards: read registry/research-lines.yaml (read_resources) and "
                "check the card against its line (minimum validation, feasibility precheck "
                "and pass criterion, fee and licence evidence, avoided directions, the "
                "ledger's earlier rejections). Judge a card of a line whose environment is not "
                "ready on its merits: the control plane holds an admitted one and admits it with "
                "your decision once the line is ready. A card with `paper_template` is a templated "
                "series paper (the line's paper_templates): admit it when its system x property "
                "combination is unreported (check its occupancy_search yourself), it meets the "
                "template's minimum content and validation, and the target venue published the "
                "same paradigm in the last two years (two examples); a parameter sweep across a "
                "family is the expected form, not a defect. Reject it only for an existing report "
                "of the same system and property, validation below the template's minimum, or "
                "one result split into several papers. A card with `candidate_queue_entry` was "
                "drawn from an enumerated target queue: admission is a checklist, not a debate. "
                "The line's mechanical admission_precheck has already run on it (card_check."
                "precheck in the packet; a failed one never reaches you). "
                "Check (1) the entry exists in that queue file (the template's own queue: a "
                "target may sit in two templates' queues, which are different topics) and the "
                "card copies its card_fields (occupancy_search may be newer when re-run); a "
                "template with `card_rules`: the card follows them and has none of its "
                "forbidden_conditions; the entry's novelty verdict is one the template's "
                "novelty_rule admits. Astro single-target entries: verdict "
                "`unreported` or `batch_only`; "
                "for `batch_only` the card cites every batch table of the entry in closest prior "
                "work and plans a parameter-by-parameter comparison with it - parameters in "
                "automated batch catalogues are not a published solution (owner decision "
                "2026-11-13) and are no reason to reject. Other lines use their own verdicts "
                "(e.g. `keep`, or `needs_differentiation`, where the card names its increment "
                "over every screened competitor in closest_prior_work); (2) re-run one of its "
                "queries yourself: a prior report of the same combination as the template's "
                "novelty_rule defines it is a reason to reject (astro: a dedicated photometric "
                "solution of this target - an individual or small-sample light-curve study - is, "
                "a batch table is not); (3) the plan "
                "covers the template's minimum_content and the line's minimum_validation; (4) the "
                "routine venues are the template's and their fee route is verified; (5) cost and "
                "compute plan match the template. Admit when all pass; otherwise reject or hold "
                "naming the failed item. A line whose `venues.tier_policy` fixes its own tiers "
                "(e.g. CAS major-category Zone 1 journals as the line's routine targets, Zone 2 "
                "journals only as a fee-free subscription-route fallback) is judged by that "
                "policy, not by the default Zones 3-4: its routine venues are the line's targets "
                "(target_tier routine) and its fallback venues stay the stated fallback."
                if line_ids else ""
            )
            + target_stage.admission_instruction(
                {entry["target_stage"] for entry in entries} - {target_stage.NC_AIM})
            + (nc_funnel.admission_instruction(settings) if any(
                entry["target_stage"] == target_stage.NC_AIM for entry in entries) else "")
        ),
        input_path=str(packet_path),
        skill_path=ADMISSION_SKILL,
        runner=dispatch_runner(settings, "portfolio_review", ADMISSION_ROUTING_REASON,
                               "frontier"),
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


def card_author(
    topic: Mapping[str, Any], document: Mapping[str, Any] | None = None
) -> tuple[str, str | None]:
    """``(provider, task_id)`` of the model that wrote a card's content.

    ``proposer_task_id`` when recorded; a repaired card registered before it
    existed is followed back through ``repair_of`` to its scout (a light-tier
    repair only fixes format errors and must not become the author whose
    family and model the admission review excludes).
    """

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
    """Packet fields naming the models that wrote a batch's cards (author task runners).

    ``producer_model``: the one model when every card's author is known and they
    agree, else None (read by older routers). ``producer_models``: every known
    author model, so a quota fallback inside the producer family avoids all of them.
    """

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


def parallel_admission_room(
    db: FactoryDB,
    settings: FactorySettings,
    campaign: Mapping[str, Any],
) -> bool:
    """Whether a program admission campaign may queue another batch beside its in-flight ones.

    The scheduling gate checks the count across all campaigns of the batch's line.
    """

    if not settings.program.enabled:
        return False
    if workstream_policy(campaign).get("continuation") != "review_on_new_results":
        return False
    project = campaign_project(campaign)
    if project is None or not project.program:
        return False
    campaign_id = str(campaign.get("campaign_id") or "")
    flights = _program_tasks(
        db, statuses=IN_FLIGHT_STATUSES, where="AND campaign_id=?",
        parameters=(campaign_id,),
    )
    return bool(flights) and all(
        task.get("routing_reason") == ADMISSION_ROUTING_REASON for task in flights
    )


def parallel_routing_reasons(settings: FactorySettings) -> tuple[str, ...]:
    """Routing reasons whose tasks may run beside a sibling of the same campaign."""

    if settings.program.enabled:
        # Prescreens (NC funnel) of one line share its scout campaign; their own cap is
        # [program.funnel].prescreen_max_concurrent (2026-11-25 trial: without this they ran
        # one at a time).
        return (ADMISSION_ROUTING_REASON, nc_funnel.PRESCREEN_ROUTING_REASON)
    return ()


def record_admission_deferral(
    db: FactoryDB,
    task: Mapping[str, Any],
    detail: Mapping[str, Any],
) -> list[str]:
    """Event per waiting topic when no independent lead runner can take the gate."""

    if str(task.get("routing_reason") or "") != ADMISSION_ROUTING_REASON:
        return []
    packet_path = Path(str(task.get("input_path") or ""))
    try:
        packet = _verified_review_packet(packet_path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return []
    topic_ids = [
        str(entry.get("topic_id"))
        for entry in packet.get("topic_cards") or []
        if isinstance(entry, Mapping)
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
    branch: Mapping[str, Any],
    admission: Mapping[str, Any],
    card: Mapping[str, Any],
    held_for_line: str | None = None,
) -> Path:
    """The gate's admit with everything a campaign needs (written once per review)."""

    record_path = _admission_record_path(paths, topic_id)
    if record_path.is_file():
        existing = _read_object(record_path)
        if existing.get("review_task_id") == review_task_id or not existing.get("held_for_line"):
            return record_path
    preregistration = admission["preregistration"]
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
            "branch": {
                key: branch.get(key)
                for key in ("title", "objective", "rationale", "resources", "wall_seconds")
                if branch.get(key) is not None
            },
            "admission": dict(admission),
            "target_stage": entry.get("target_stage", target_stage.RUN_IN),
            "conditions": admission_conditions(admission),
            "card": dict(card),
            "card_sha256": entry.get("card_sha256"),
            "preregistration": {
                "primary_endpoint": preregistration["primary_endpoint"],
                "sha256": preregistration["sha256"],
            },
            **({"held_for_line": held_for_line} if held_for_line else {}),
            "created_at": utc_now(),
        },
    )
    return record_path


def _summary(admission: Mapping[str, Any], review_task_id: str) -> dict[str, Any]:
    preregistration = admission.get("preregistration")
    return {
        "verdict": admission.get("verdict"),
        "target_tier": admission.get("target_tier"),
        "tier_rationale": admission.get("tier_rationale"),
        "strongest_rejection_reason": admission.get("strongest_rejection_reason"),
        "data_access_confirmed": admission.get("data_access_confirmed"),
        "cost_judgement": admission.get("cost_judgement"),
        "closest_prior_work_checked": admission.get("closest_prior_work_checked"),
        "reopen_conditions": admission.get("reopen_conditions") or [],
        "conditions": admission_conditions(admission),
        "revisable": admission.get("revisable") is True,
        "preregistration_sha256": (
            preregistration.get("sha256") if isinstance(preregistration, Mapping) else None
        ),
        "review_task_id": review_task_id,
        "policy": ADMISSION_POLICY_VERSION,
        **({"nc_assessment": dict(admission["nc_assessment"])}
           if isinstance(admission.get("nc_assessment"), Mapping) else {}),
        **({"novelty_search": {
            key: admission["novelty_search"].get(key)
            for key in ("window_years", "papers_screened", "increment", "closest")}}
           if isinstance(admission.get("novelty_search"), Mapping) else {}),
    }


def _decided_by(topic: Mapping[str, Any], review_task_id: str) -> bool:
    """Whether this review already admitted or rejected the topic (a replay)."""

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
    """Apply one admission review: record verdicts, then materialize in order."""

    if not settings.program.enabled:
        raise ValueError("research program is disabled; defer admission handling")
    packet_path = Path(str(task.get("input_path") or "")).resolve()
    if not packet_path.is_file():
        raise ValueError("admission reviewer has no immutable review packet")
    packet = _verified_review_packet(packet_path)
    if packet.get("program") is not True:
        raise ValueError("admission result does not come from a program review packet")
    cards = {
        str(entry.get("topic_id")): entry
        for entry in packet.get("topic_cards") or []
        if isinstance(entry, Mapping)
    }
    packet_results = {str(item) for item in packet.get("result_ids") or []}
    ledger = open_topic_ledger(paths, settings.program)
    review_task_id = str(task.get("task_id") or "")
    evidence = [{"path": str(result_path), "sha256": sha256_file(result_path)}]
    decisions: list[dict[str, Any]] = []
    decided: set[str] = set()
    branches = payload.get("candidate_branches")
    for branch in branches if isinstance(branches, list) else []:
        if not isinstance(branch, Mapping):
            continue
        topic_id = str(branch.get("topic_id") or "").strip()

        def note(outcome: str, reason: str, _topic: str = topic_id) -> None:
            decisions.append({"topic_id": _topic, "outcome": outcome, "reason": reason})

        entry = cards.get(topic_id)
        if entry is None:
            note("ignored", "topic_not_in_review_packet")
            continue
        sources = {str(item) for item in branch.get("source_result_ids") or [] if str(item)}
        if (
            not sources
            or not sources <= packet_results
            or str(entry.get("source_result_id")) not in sources
        ):
            note("ignored", "source_result_not_in_review_packet")
            continue
        topic = find_topic(ledger.read(), topic_id)
        if topic is None or topic.get("card_sha256") != entry.get("card_sha256"):
            note("ignored", "card_hash_mismatch")
            continue
        admission = branch.get("admission")
        validation = validate_topic_admission(admission)
        if not validation.valid:
            note("ignored", "admission_output_invalid: " + "; ".join(validation.errors))
            continue
        if topic_id in decided:
            note("ignored", "duplicate_decision")
            continue
        decided.add(topic_id)
        assert isinstance(admission, Mapping)
        card = entry.get("card") if isinstance(entry.get("card"), Mapping) else {}
        stage = entry.get("target_stage", target_stage.RUN_IN)
        summary = {**_summary(admission, review_task_id), "target_stage": stage}
        if stage == target_stage.TIER2_AIM:
            summary["tier2_contribution_supported"] = admission.get("tier2_contribution_supported")
        status = str(topic.get("status"))
        verdict = str(admission.get("verdict"))
        if status != "proposed" and not _decided_by(topic, review_task_id):
            # Decided elsewhere (another review, admission_undecided): leave it.
            note("unchanged", f"topic_already_{status}")
            continue
        if verdict == "admit" and status == "proposed":
            current = target_stage.stage_for(db, card.get("research_line"), settings)
            if stage != current and current in target_stage.GRADED_STAGES:
                note("undecided", "line_stage_changed_during_review")
                continue
            if stage == target_stage.NC_AIM:
                gaps = [*target_stage.card_errors(card, stage),
                        *nc_funnel.admission_problems(admission, settings)]
                if gaps:
                    reject_topic(ledger, topic_id, db=db, reason=nc_funnel.ADMISSION_REJECTION,
                                 decided_by=review_task_id, evidence=evidence,
                                 admission={**summary, "strongest_rejection_reason":
                                            "NC aim: " + "; ".join(gaps)})
                    note("rejected", nc_funnel.ADMISSION_REJECTION)
                    continue
            if stage == target_stage.TIER2_AIM:
                gaps = target_stage.card_errors(card, stage)
                if admission.get("tier2_contribution_supported") is not True:
                    gaps.append("Independent review must support the prospective Zone 1–2 contribution.")
                if gaps:
                    reject_topic(ledger, topic_id, db=db, reason="admission_rejected",
                                 decided_by=review_task_id, evidence=evidence,
                                 admission={**summary, "strongest_rejection_reason": " ".join(gaps)})
                    note("rejected", "tier2_aim_admission_requirements")
                    continue
        if verdict == "admit":
            problem = ""
            cost = admission.get("cost_judgement") or {}
            if admission.get("data_access_confirmed") is not True:
                problem = "data_access_not_confirmed"
            elif card.get("computational_only") is not True:
                problem = "not_computational_only"
            elif cost.get("proportionate") is not True:
                problem = "cost_not_proportionate"
            else:
                problem = compute_location_problem(settings, card) or ""
            line = str(card.get("research_line") or "").strip()
            if not problem and line:
                environment = environment_status(research_lines_document(paths, settings), line)
                if environment != ENVIRONMENT_READY:
                    # Its first research task (the feasibility precheck) could not run:
                    # hold until the line's environment is ready, whatever the verdict.
                    # The gate's admission is kept, so the topic is admitted without a new
                    # review once the line is ready (``release_ready_holds``).
                    reason = f"research_line_environment_not_ready:{line}:{environment}"
                    if status == "proposed":
                        _write_admission_record(
                            paths, topic_id, project=project, source_campaign=source_campaign,
                            review_task_id=review_task_id, result_path=result_path,
                            entry=entry, branch=branch, admission=admission, card=card,
                            held_for_line=line,
                        )
                        reject_topic(
                            ledger, topic_id, db=db, reason="admission_hold",
                            decided_by=review_task_id, evidence=evidence,
                            reopen_conditions=[
                                *(admission.get("reopen_conditions") or []),
                                {"type": "line_environment_ready",
                                 "description": (
                                     f"research line {line} has environment status ready in "
                                     f"registry/research-lines.yaml (was {environment})"
                                 )},
                            ],
                            admission={**summary, "control_plane_hold": reason},
                        )
                    note("held", reason)
                    continue
            if problem:
                if status == "proposed":
                    reject_topic(ledger, topic_id, db=db, reason=problem,
                                 decided_by=review_task_id, evidence=evidence, admission=summary)
                note("rejected", problem)
                continue
            if status == "proposed":
                preregistration = admission["preregistration"]
                _write_admission_record(
                    paths, topic_id, project=project, source_campaign=source_campaign,
                    review_task_id=review_task_id, result_path=result_path, entry=entry,
                    branch=branch, admission=admission, card=card,
                )
                admit_topic(
                    ledger, topic_id, db=db, settings=settings.program,
                    decided_by=review_task_id, admission_task_id=review_task_id,
                    preregistration_sha256=str(preregistration["sha256"]),
                    evidence=evidence, target_tier=admission.get("target_tier"),
                    admission=summary, queue_when_full=True,
                )
            note("admitted", str(admission.get("target_tier")))
            continue
        if status == "proposed":
            reject_topic(
                ledger, topic_id, db=db,
                reason="admission_hold" if verdict == "hold" else "admission_rejected",
                decided_by=review_task_id, evidence=evidence,
                reopen_conditions=admission.get("reopen_conditions") or [],
                admission=summary,
            )
        note("held" if verdict == "hold" else "rejected", str(
            admission.get("strongest_rejection_reason") or ""
        ))
    for topic_id in cards:
        if topic_id not in decided:
            decisions.append({"topic_id": topic_id, "outcome": "undecided",
                              "reason": "no_valid_decision_in_review"})
    spawned = materialize_waiting_topics(db, paths, settings)
    return CandidateSpawn(spawned.campaign_ids, spawned.task_ids, tuple(decisions))


def _research_state(
    record: Mapping[str, Any],
    topic: Mapping[str, Any],
    *,
    record_path: Path | None = None,
    agent_seconds_budget: int | None = None,
) -> dict[str, Any]:
    card = record.get("card") if isinstance(record.get("card"), Mapping) else {}
    venues = card.get("venues") if isinstance(card.get("venues"), Mapping) else {}
    admission = record.get("admission") if isinstance(record.get("admission"), Mapping) else {}
    extra: dict[str, Any] = {}
    if record_path is not None and record_path.is_file():
        # Writers record an escalation target as provisional with this record as
        # its strength evidence (path plus hash).
        extra["admission_record"] = {"path": str(record_path), "sha256": sha256_file(record_path)}
    if agent_seconds_budget is not None:
        extra["agent_seconds_budget"] = int(agent_seconds_budget)
    conditions = record_conditions(record)
    if conditions:
        extra["admission_conditions"] = conditions
    return {
        **extra,
        "program_role": "research",
        "topic_id": topic["topic_id"],
        "target_tier": admission.get("target_tier"),
        "target_stage": record.get("target_stage", target_stage.RUN_IN),
        "tier_rationale": admission.get("tier_rationale"),
        "routine_fallback": venues.get("routine"),
        "escalation_target": venues.get("escalation"),
        "cost_budget": card.get("cost_estimate"),
        "preregistration": dict(record["preregistration"]),
        "admission_task_id": record.get("review_task_id"),
        "card_sha256": record.get("card_sha256"),
        "reusable_assets": card.get("reusable_assets") or [],
        "question": card.get("question"),
        **{
            key: card.get(key)
            for key in ("research_line", "feasibility_precheck", "license_check", "fee_check")
            if card.get(key) is not None
        },
        **({"precheck_clock": PRECHECK_CLOCK}
           if isinstance(card.get("feasibility_precheck"), Mapping) else {}),
        **(nc_funnel.research_fields(record)
           if record.get("target_stage") == target_stage.NC_AIM else {}),
    }


# How a feasibility precheck's agent-time budget is measured. On 2026-11-13 the
# precheck of topic-6da8c0ba counted wall time spent waiting for a queued ailab
# solve against its 3600-agent-second card budget and froze as "inconclusive".
PRECHECK_CLOCK = {
    "counts": "active agent seconds charged to this campaign, plus the declared compute",
    "excludes": "time waiting for queued or running remote jobs (awaiting_remote is not "
                "charged), and wall time before the task started",
    "pending_remote_jobs": "end the attempt with awaiting_remote; a precheck whose jobs have "
                           "not finished is neither failed nor inconclusive",
}


def record_conditions(record: Mapping[str, Any]) -> list[dict[str, str]]:
    """Admission conditions of an admission record (v1 records: from its admission)."""

    if isinstance(record.get("conditions"), list):
        return admission_conditions({"verdict": "admit", "conditions": record["conditions"]})
    return admission_conditions(record.get("admission"))


CONDITION_STAGE_TEXT = {
    "before_precheck": "before the feasibility precheck (or, without one, before any analysis)",
    "before_decisive_analysis": "before the pre-registered decisive analysis",
    "before_submission": "before the paper can be handed for submission",
}


def conditions_instruction(conditions: list[Mapping[str, Any]]) -> str:
    """Task-prompt text for the gate's admission conditions (``""`` when there are none)."""

    if not conditions:
        return ""
    lines = "; ".join(
        f"[{item.get('due')}] {item.get('description')}" for item in conditions
    )
    return (
        f" The admission gate admitted this topic with {len(conditions)} condition(s) "
        "(research_state.json `admission_conditions`): " + lines + ". Meet each one at its stage "
        "(" + "; ".join(f"{due}: {text}" for due, text in CONDITION_STAGE_TEXT.items()) + "), "
        "fix the details in the pre-registration notes without changing the hash-bound primary "
        "endpoint, and report in the result bundle how each condition you reached was met. "
        "Conditions due before_submission stay open blockers of the handoff."
    )


def materialize_waiting_topics(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
) -> CandidateSpawn:
    """Turn admitted topics into campaigns, oldest admission first, while slots allow."""

    campaign_ids: list[str] = []
    task_ids: list[str] = []
    if settings.program.polish_blocks_all():
        # Polish mode: admitted topics keep their admission and wait for their campaign.
        return CandidateSpawn(campaign_ids=(), task_ids=())
    if compute_backlogged(settings):
        # Admitted topics wait for their campaign until the compute backlog falls.
        return CandidateSpawn(campaign_ids=(), task_ids=())
    ledger = open_topic_ledger(paths, settings.program)
    parked = parked_program_projects(paths)
    paused = paused_topic_campaigns(db)
    # Admitted topics of a line blocked on its shared reference wait for the block.
    skipped: set[str] = {
        str(topic["topic_id"]) for topic in topics_by_status(ledger.read(), "admitted")
        if str(topic.get("research_line") or "") in line_facts.blocked_lines(db)
    } if settings.program.supply.line_facts else set()
    while True:
        document = ledger.read()
        status = slot_status(document, settings.program, parked, paused)
        if not status.can_materialize:
            break
        # Admitted topics of a paused program project wait until it is active again;
        # those of a line at its own slot limit wait for that line's slot.
        queue = [topic for topic in waiting_admitted(document, admission_sequence(db))
                 if str(topic["topic_id"]) not in skipped
                 and str(topic.get("program_project_id") or "") not in parked
                 and not settings.program.polish_blocks(topic.get("research_line"))
                 and status.line_can_materialize(topic.get("research_line"))]
        if not queue:
            break
        topic = queue[0]
        topic_id = str(topic["topic_id"])
        record_path = _admission_record_path(paths, topic_id)
        if not record_path.is_file():
            # Admitted outside this pipeline (e.g. by hand): nothing to build.
            skipped.add(topic_id)
            continue
        record = _read_object(record_path)
        project = load_project(str(record["project_path"]))
        card = record.get("card") if isinstance(record.get("card"), Mapping) else {}
        budget = topic_budget_seconds(card.get("cost_estimate"), settings)
        source_campaign = db.campaign(str(record.get("source_campaign_id") or "")) or {
            "priority": 0
        }
        branch = dict(record.get("branch") or {})
        branch["candidate_id"] = topic_id
        branch.setdefault("title", str(topic.get("question") or topic_id))
        branch["objective"] = (
            str(branch.get("objective") or topic.get("question") or "")
            + " The admitted topic, its pre-registered primary endpoint (hash-bound), target "
            "tier, routine fallback venues and cost budget are in research_state.json; run the "
            "pre-registered analysis first and apply its stop rule honestly."
            + (
                " Before that, run the card's feasibility_precheck (research_state.json) as the "
                "first task and nothing else; if it misses its pass criterion, return gate_result "
                "{promotion_decision: freeze, freeze_reason_class: feasibility_precheck_failed} "
                "with the precheck evidence, and list each missed criterion in "
                "gate_result.failed_criteria [{name, delta, tolerance, uncertainty, reference: "
                "{id, job_id} when it is the line's shared reference}]. Its budget counts "
                "active agent time "
                "(research_state.json precheck_clock), not time waiting for queued remote jobs: "
                "while those are pending, end with awaiting_remote instead of declaring the "
                "precheck inconclusive. Follow the research line's SOP and environment "
                "in registry/research-lines.yaml."
                if isinstance(card.get("feasibility_precheck"), Mapping) else ""
            )
            + conditions_instruction(record_conditions(record))
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
            extra_policy={"topic_id": topic_id, "program_research": True,
                          "max_agent_seconds": budget,
                          **({"paper_profile": paper_profile} if paper_profile else {})},
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


# --------------------------------------------------------------------------- admission rule


def workstream_admitted(document: Mapping[str, Any], workstream_id: str) -> bool:
    topic = topic_for_campaign(document, workstream_id)
    return bool(topic and topic.get("status") in ADMITTED_WORK_STATUSES)


# --------------------------------------------------------------------------- backfill


def backfill_grandfathered(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    write: bool = False,
) -> dict[str, Any]:
    """Register existing active research campaigns as ``active`` grandfathered topics.

    Dry-run by default. Skips program scout/admission campaigns, reviewer
    workstreams and campaigns already linked to a topic.
    """

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
                "primary_endpoint": "grandfathered campaign (no pre-registered endpoint)",
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


# --------------------------------------------------------------------------- compute backlog

COMPUTE_BACKLOG_REASON = "compute_backlog"


def compute_backlogged(settings: FactorySettings) -> bool:
    """Whether the ``[program]`` compute backlog gate holds new topics this moment."""

    backlog = compute_backlog(settings)
    return bool(backlog and backlog["backlogged"])


# --------------------------------------------------------------------------- tick


def report_scheduling_counts(
    db: FactoryDB, paths: WorkspacePaths, settings: FactorySettings, report: Any,
) -> None:
    """Snapshot topic supply and queued/running work after all scheduling passes."""

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
            item["legacy_domains"] = sorted(key.removeprefix("domain/") for key in keys
                                            if key.startswith("domain/"))
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
    """Per-tick scout/admission bookkeeping. Disabled: touches nothing."""

    if not settings.program.enabled:
        return
    info = report.program
    if settings.program.polish_mode:
        exempt = settings.program.polish_exempt_lines
        supply_only = settings.program.polish_supply_only_lines
        scouting = (*exempt, *supply_only)
        info["polish_mode"] = {
            "on": True,
            "exempt_lines": list(exempt),
            # Scout, prescreen and admission only; no research start (2026-11-26).
            "supply_only_lines": list(supply_only),
            "paused": ["topic_scout", "topic_card_repair", "topic_revision",
                       "topic_admission", "admission_pilot", "auto_reopen",
                       "materialize"],
            "running": ["topics_in_research", "writing", "reviews", "delivery",
                        "delivered_revisions", "operator_reopen_grants", "journal_mail"],
            # Scouts queued before the switch never start (a leased one finishes).
            "cancelled": list(db.cancel_queued_tasks(
                [str(task["task_id"]) for task in _program_tasks(
                    db, statuses=("queued",), where="AND task_type=?",
                    parameters=(SCOUT_TASK_TYPE,))
                 if not scouting or _scout_task_line(db, task) not in scouting],
                reason=POLISH_MODE_REASON)),
        }
    backlog = compute_backlog(settings)
    if backlog is not None:
        info["compute_backlog"] = backlog
        if backlog["backlogged"]:
            # New scouts, admissions and materializations wait; topics in research run on.
            report.production_blocked.append({
                "campaign_id": "", "reason": COMPUTE_BACKLOG_REASON,
                "detail": str(backlog["detail"]),
            })
    try:
        stage_document = open_topic_ledger(paths, settings.program).read()
        lines = set(settings.program.research_lines)
        lines.update(project.research_line for project in program_projects(paths)
                     if project.research_line)
        lines.update(topic["research_line"] for topic in stage_document.get("topics", [])
                     if topic.get("research_line"))
        info["by_line"] = target_stage.refresh(db, stage_document, sorted(lines), settings)
        outcomes = register_scout_results(db, paths, settings)
        info["cards_registered"] = [item for item in outcomes if item["status"] == "proposed"]
        info["rejected_cards"] = [item for item in outcomes if item["status"] == "rejected"]
        for item in outcomes:
            if item.get("precheck") == "error":
                report.errors.append(
                    f"Admission precheck of {item['topic_id']} failed to run (the card waits, "
                    f"not reviewed; retried next tick): {item.get('precheck_error')}")
        info["card_prechecks"] = {
            "this_tick": [{"topic_id": item["topic_id"], "status": item["precheck"]}
                          for item in outcomes if item.get("precheck")],
            "retried": retry_held_prechecks(db, paths, settings, report),
            "pilots": supply_screen.advance_pilots(db, paths, settings, report),
            "prescreens": nc_funnel.advance_prescreens(db, paths, settings, report),
            "by_line": precheck_statistics(open_topic_ledger(paths, settings.program).read()),
        }
        if not any(info["card_prechecks"].values()):
            info.pop("card_prechecks")
        info["card_repairs"] = schedule_card_repairs(db, paths, settings)
        report.enqueued.extend(
            str(item["task_id"]) for item in info["card_repairs"] if item.get("task_id")
        )
        info["holds_released"] = release_ready_holds(db, paths, settings)
        # Line-level blocks: release on a changed receipt, expire long waits, report.
        line_facts.tick(db, paths, settings, report)
        info["scout_outcomes"] = record_scout_outcomes(
            db, paths, settings, open_topic_ledger(paths, settings.program).read()
        )
        # Frozen topics whose line-level reopen conditions came true take their slot
        # back before new admissions are materialized (reopen.py).
        from .reopen import reopen_ready_topics, repair_half_done_reopens

        from .reopen import advance_delivered_revisions

        info["delivered_revisions"] = advance_delivered_revisions(db, paths, settings, report)
        info["reopen_repaired"] = repair_half_done_reopens(db, paths, settings, report)
        info["auto_reopen"] = reopen_ready_topics(db, paths, settings, report)
        spawned = materialize_waiting_topics(db, paths, settings)
        report.enqueued.extend(spawned.task_ids)
        report.production_synced.extend(spawned.campaign_ids)
        info["materialized"] = list(spawned.campaign_ids)
        scheduled, blocked = schedule_scouts(
            db, paths, settings, lead_short=lead_quota_short(db, settings)
        )
        report.enqueued.extend(str(item.task_id) for item in scheduled)
        info["scouts_scheduled"] = [
            {"task_id": item.task_id, "domain": item.domain,
             **({"research_line": item.research_line} if item.research_line else {})}
            for item in scheduled
        ]
        info["scout_blocked"] = blocked
        supply = scout_supply_blocks(
            db, paths, settings, program_projects(paths),
            open_topic_ledger(paths, settings.program).read(), moment=_now_moment(),
        )
        info["scout_supply_blocked"] = list(supply.values())
        info["line_supply"] = [
            {**({"research_line": item["research_line"]} if item.get("research_line")
                else {"legacy_domain": item.get("domain")}),
             "signal": ("supply_exhausted" if item["reason"] in EXHAUSTED_REASONS
                        else "scout_backoff"),
             "reason": item["reason"], "empty_draws": item.get("empty_draws"),
             **({"drawable": item["drawable"]} if "drawable" in item else {}),
             **({"until": item["until"]} if item.get("until") else {}),
             "release_when": item.get("release_when")}
            for item in supply.values()
        ]
        for item in supply.values():
            if item["reason"] in EXHAUSTED_REASONS:
                report.production_blocked.append({
                    **{k: v for k, v in item.items() if v is not None},
                    "campaign_id": str(item.get("campaign_id") or ""),
                })
        info["lines_environment_not_ready"] = lines_not_ready(
            paths, settings, [project.research_line for project in program_projects(paths)],
            db=db)
        revisions, revision_blocked = schedule_revisions(
            db, paths, settings, lead_short=lead_quota_short(db, settings)
        )
        report.enqueued.extend(str(item["task_id"]) for item in revisions)
        info["revisions_scheduled"] = revisions
        info["revision_blocked"] = revision_blocked
        info["scouts_in_flight"] = len(_program_tasks(
            db, statuses=IN_FLIGHT_STATUSES, where="AND task_type=?",
            parameters=(SCOUT_TASK_TYPE,),
        ))
        document = open_topic_ledger(paths, settings.program).read()
        info["candidate_pool"] = len(_proposed_pool(document))
        info["candidate_pool_topics"] = [str(t["topic_id"]) for t in _proposed_pool(document)]
        info["waiting_admitted"] = [
            str(t["topic_id"]) for t in waiting_admitted(document, admission_sequence(db))
        ]
        info.update(slot_status(
            document, settings.program, parked_program_projects(paths),
            paused_topic_campaigns(db)).to_dict())
        info.setdefault("admissions_scheduled", [])
        info.setdefault("admission_decisions", [])
        info["nc_funnel"] = nc_funnel.metrics(document, settings)
        info["nc_funnel"]["scout_gates"] = list(nc_funnel.scout_blocks(
            db, paths, settings, program_projects(paths), document,
            moment=_now_moment()).values())
    except (OSError, TopicLedgerError, KeyError, TypeError, ValueError,
            json.JSONDecodeError) as exc:
        report.errors.append(f"program pipeline: {exc}")
        info["pipeline_error"] = str(exc)
