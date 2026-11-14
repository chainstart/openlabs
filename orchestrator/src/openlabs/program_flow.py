"""Research-program pipeline: topic scouts, card intake and the admission gate.

Deterministic bookkeeping and routing only. A ``topic_scout`` agent proposes
topic cards, an independent lead-tier reviewer judges them in a
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
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import assets as asset_library
from . import budget as budget_control
from .config import FactorySettings, WorkspacePaths
from .contracts import (
    ADMISSION_POLICY_VERSION,
    admission_conditions,
    artifact_digests,
    atomic_write_json,
    canonical_json_bytes,
    compute_plan_locations,
    data_source_identifiers,
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
SCOUT_REGISTERED_PREFIX = "program_scout_registered:"
# A topic included in this many admission packets without a valid decision is
# rejected as ``admission_undecided`` (it may be resubmitted as a new card).
MAX_ADMISSION_ATTEMPTS = 3
HUMAN_PROVIDER = "human"
# awaiting_remote: parked on remote compute jobs (openlabs.remote_wait); still in flight.
IN_FLIGHT_STATUSES = ("queued", "leased", "running", "awaiting_remote")
POOL_STATUSES = ("proposed",)
DOMAIN_LOAD_STATUSES = ("proposed", "admitted", "active", "in_review")
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


def scout_key(project: ProjectConfig) -> str:
    """Rotation key of a program project: its research line, else its domain."""

    return project.research_line or project.domain


def _topic_key(topic: Mapping[str, Any]) -> str:
    return str(topic.get("research_line") or topic.get("domain") or "")


def research_lines_document(
    paths: WorkspacePaths, settings: FactorySettings
) -> dict[str, Any] | None:
    """The parsed direction file, or ``None`` when absent or unreadable."""

    return read_lines_or_none(paths.data / settings.program.research_lines_path)


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
            }
        )
    return snapshot


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
    if schema not in CARD_PACKET_SCHEMAS and not (
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


# --------------------------------------------------------------------------- scouts


@dataclass(frozen=True)
class ScoutDecision:
    task_id: str | None = None
    domain: str | None = None
    reason: str | None = None
    research_line: str | None = None


def _proposed_pool(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    return topics_by_status(document, *POOL_STATUSES)


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
    for project in projects:
        if lines:
            if project.research_line not in lines:
                continue
        elif configured and project.domain not in configured:
            continue
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
    for topic in topics_by_status(document, *DOMAIN_LOAD_STATUSES):
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
        return (load.get(rotation, 0), last.get(rotation, ""), order, project.project_id)

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


def queue_scout_instruction(queues: Mapping[str, str]) -> str:
    """Scout objective addition for templates with an enumerated candidate queue."""

    if not queues:
        return ""
    return (
        ". Templates with a candidate_queue ("
        + ", ".join(f"{template}: {path}" for template, path in sorted(queues.items()))
        + ") are enumerated, not scouted: do not search for other targets of them. Take the "
        "highest-ranked entries whose novelty verdict is `unreported` and whose target is in "
        "no ledger topic (compare its identifiers with ledger_snapshot); copy each entry's "
        "`card_fields` (research_line, paper_template, occupancy_search, "
        "candidate_queue_entry, series when present) into the card unchanged, re-running the "
        "occupancy search only when its searched_at is more than 30 days old (then record the "
        "new search), and fill the remaining card fields from the template and the SOP. Skip "
        "an entry whose data access fails and say so in the result"
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
    max_cards: int,
    moment: datetime,
) -> ScoutDecision:
    campaign = db.campaign(campaign_id) or {}
    stamp = _iso(moment)
    rotation = scout_key(project)
    line = project.research_line
    line_fields: dict[str, Any] = {}
    if line:
        line_fields = {
            "research_line": line,
            "research_line_summary": line_summary(research_lines_document(paths, settings), line),
        }
    # The campaign's task count keeps two scouts of one domain scheduled within
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
                    + queue_scout_instruction(
                        queued_templates(research_lines_document(paths, settings), line))
                    if line_templates(research_lines_document(paths, settings), line) else ""
                )
                if line else ""
            )
            + ". Read the packet at the input path: the topic ledger "
            "snapshot, the research-portfolio requirements, the team rejection ledger and the "
            "reusable-asset index when present. Return up to "
            f"{max_cards} topic cards in the result bundle field `topic_cards`, each following "
            "openlabs.topic_card.v1. Verify access to the decisive data yourself and add the "
            "access receipt as a hash-bound result artifact. An empty `topic_cards` array is a "
            "valid outcome when nothing clears the bar. Do not start the research itself."
        ),
        input_path=str(packet_path),
        skill_path=SCOUT_SKILL,
        runner="balanced",
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
                {"task_id": task_id, "domain": project.domain, "research_line": line,
                 "max_cards": max_cards, "free_slots": status.free_slots},
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
    """Schedule as many topic scouts as the program allows this tick.

    Returns the scheduled scouts and the reason no (further) scout was
    scheduled. With ``max_concurrent_scouts = 1`` this is the original single
    scout with a program-wide minimum interval. Above 1, at most one scout per
    domain runs, the interval applies per domain, and scouts are added only
    while ``candidate pool + in-flight scouts x expected cards`` stays below
    ``candidate_pool_low_water``; each new scout asks for its share of what is
    still missing.
    """

    program = settings.program
    if not program.enabled:
        return [], "program_disabled"
    if not budget_control.routing_enabled(settings):
        # Without provider routing the proposer and judge families cannot be
        # told apart, so the gate could not be independent.
        return [], "provider_routing_not_configured"
    ledger = open_topic_ledger(paths, program)
    document = ledger.read()
    status = slot_status(document, program, parked_program_projects(paths))
    if status.admission_paused:
        return [], "admission_paused"
    if status.free_slots <= 0:
        return [], "no_free_slot"
    pool = len(_proposed_pool(document))
    if pool >= program.candidate_pool_low_water:
        return [], "candidate_pool_at_low_water"
    if lead_short:
        return [], "lead_quota_short"
    in_flight = _program_tasks(db, statuses=IN_FLIGHT_STATUSES, where="AND task_type=?",
                               parameters=(SCOUT_TASK_TYPE,))
    moment = now or _now_moment()
    interval = timedelta(hours=program.scout_min_interval_hours)
    projects = program_projects(paths)
    if program.max_concurrent_scouts <= 1:
        if in_flight:
            return [], "scout_in_flight"
        last = budget_control.parse_time(db.meta_get(LAST_SCOUT_KEY))
        if last is not None and moment - last < interval:
            return [], "scout_min_interval"
        chosen = _choose_scout_project(db, settings, projects, document)
        if chosen is None:
            return [], "no_program_project"
        project, campaign_id = chosen
        decision = _schedule_one_scout(
            db, paths, settings, document=document, ledger=ledger, status=status,
            project=project, campaign_id=campaign_id,
            max_cards=max(1, program.candidate_pool_low_water - pool), moment=moment,
        )
        return [decision], None
    expected = expected_cards_per_scout(db, settings, document)
    keys_by_campaign = {
        scout_workstream_id(project): scout_key(project) for project in projects
    }
    busy = {
        keys_by_campaign.get(str(task.get("campaign_id") or ""))
        or str(task.get("domain") or "")
        for task in in_flight
    }
    recent = {
        domain
        for domain, stamp in db.meta_items(LAST_SCOUT_KEY + ":").items()
        if (at := budget_control.parse_time(stamp)) is not None and moment - at < interval
    }
    missing = program.candidate_pool_low_water - pool - len(in_flight) * expected
    if missing <= 0:
        return [], "candidate_pool_covered_by_scouts"
    room = program.max_concurrent_scouts - len(in_flight)
    if room <= 0:
        return [], "max_concurrent_scouts"
    wanted = min(room, math.ceil(missing / expected))
    max_cards = max(1, math.ceil(missing / wanted))
    scheduled: list[ScoutDecision] = []
    reason: str | None = None
    while len(scheduled) < wanted:
        chosen = _choose_scout_project(
            db, settings, projects, document, exclude=frozenset(busy | recent)
        )
        if chosen is None:
            if not projects:
                reason = "no_program_project"
            elif busy and not (recent - busy):
                reason = "scout_in_flight"
            else:
                reason = "scout_min_interval"
            break
        project, campaign_id = chosen
        decision = _schedule_one_scout(
            db, paths, settings, document=document, ledger=ledger, status=status,
            project=project, campaign_id=campaign_id, max_cards=max_cards, moment=moment,
        )
        scheduled.append(decision)
        busy.add(scout_key(project))
    if reason is None and len(scheduled) == wanted:
        reason = (
            "max_concurrent_scouts" if wanted == room
            else "candidate_pool_covered_by_scouts"
        )
    return scheduled, reason


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
) -> dict[str, Any]:
    venues = card.get("venues") if isinstance(card.get("venues"), Mapping) else {}
    line = str(card.get("research_line") or "").strip()
    return {
        **({"research_line": line} if line else {}),
        "program_project_id": project.project_id,
        "source_task_id": source_task_id,
        "proposer_provider": provider,
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
) -> list[str]:
    """Every machine check of a card: contract, asset references, compute plan, receipt.

    With the ledger, a revision card must also answer every reopen condition of
    the topic it revises (a fixable format problem, so it goes to repair).
    """

    errors = list(validate_topic_card(card).errors)
    template = str(card.get("paper_template") or "").strip()
    line = str(card.get("research_line") or "").strip()
    if template and line:
        known = {str(item.get("id")) for item in line_templates(
            research_lines_document(paths, settings), line)}
        if template not in known:
            errors.append(
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
    errors.extend(asset_library.card_reference_errors(paths, settings, card))
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
) -> dict[str, Any]:
    """Validate one card and register it; return ``{topic_id, status, reason, errors}``.

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
    card["domain"] = project.domain
    if project.research_line:
        # A line project's cards belong to its line, never an agent-chosen one.
        card["research_line"] = project.research_line
    if repair_of:
        card["repair_of"] = repair_of
    if revises:
        card["revises"] = revises
    errors = card_problems(paths, settings, card, receipt_digests=receipt_digests,
                           ledger_document=ledger.read())
    metadata = _card_metadata(project, card, source_task_id=source_task_id, provider=provider)
    if repair_of:
        metadata["repair_of"] = repair_of
    repairable = source_task_id is not None and not repair_of
    if errors:
        return _record_invalid(db, paths, ledger, project, card, errors=errors,
                               decided_by=decided_by, metadata=metadata, repairable=repairable)
    metadata["card_path"] = str(_store_card(paths, project, card))
    try:
        decision = propose_topic(ledger, card, db=db, decided_by=decided_by, metadata=metadata)
    except TopicLedgerError as exc:
        return _record_invalid(db, paths, ledger, project, card, errors=[str(exc)],
                               decided_by=decided_by, metadata=metadata, repairable=repairable)
    return {
        "topic_id": decision.topic_id,
        "status": decision.status,
        "reason": decision.reason,
        "errors": [],
        "duplicate_of": list(decision.duplicate_of),
    }


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
) -> dict[str, Any]:
    values = dict(metadata)
    values["card_path"] = str(_store_card(paths, project, card, invalid=True))
    values["card_repair"] = (
        {"status": "pending", "errors": list(errors)} if repairable
        else {"status": "not_repairable",
              "reason": "repair_failed" if card.get("repair_of") else "manual_or_unbound_card"}
    )
    decision = record_rejected_card(
        ledger, card, db=db, decided_by=decided_by, errors=errors, metadata=values
    )
    return {"topic_id": decision.topic_id, "status": "rejected", "reason": "card_invalid",
            "errors": errors, "card_repair": values["card_repair"]["status"]}


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
        provider = budget_control.provider_of(settings, task.get("runner"))
        digests = set(artifact_digests(payload).values())
        task_type = str(task.get("task_type") or "")
        follow_up: dict[str, Any] = {}
        if task_type != SCOUT_TASK_TYPE:
            follow_up = _follow_up_packet(task)
            # A repair or revision returns one card; it may reuse the original receipt.
            cards = cards[:1]
            digests |= {str(item) for item in follow_up.get("receipt_digests") or []}
        task_outcomes = [
            {"source_task_id": task_id, **intake_card(
                db, paths, settings, project, card, decided_by=task_id, provider=provider,
                source_task_id=task_id, receipt_digests=digests,
                repair_of=follow_up.get("repair_of") if task_type == REPAIR_TASK_TYPE else None,
                revises=(
                    follow_up.get("revision_of") if task_type == REVISION_TASK_TYPE
                    else follow_up.get("revises")
                ),
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

    ledger = open_topic_ledger(paths, settings.program)
    moment = now or _now_moment()
    outcomes: list[dict[str, Any]] = []
    for topic in topics_by_status(ledger.read(), "rejected"):
        topic_id = str(topic["topic_id"])
        if last_rejection_reason(topic) != "card_invalid" or topic.get("repair_of"):
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
        errors = card_problems(paths, settings, card, receipt_digests=digests,
                               ledger_document=ledger.read())
        if not errors:
            # The card passes the current checks as it stands: register it again.
            outcome = intake_card(
                db, paths, settings, project, card, decided_by=f"card-repair:{topic_id}",
                provider=provider, source_task_id=source_task_id, receipt_digests=digests,
                repair_of=topic_id, revises=str(card.get("revises") or "") or None,
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
        ),
        input_path=str(packet_path),
        skill_path=SCOUT_SKILL,
        runner="cheap",
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
        pending.append(topic)
    if not pending:
        return [], "no_revisable_topic"
    status = slot_status(document, program, parked_program_projects(paths))
    if status.admission_paused:
        return [], "admission_paused"
    if status.free_slots <= 0:
        return [], "no_free_slot"
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
        ),
        input_path=str(packet_path),
        skill_path=SCOUT_SKILL,
        runner="balanced",
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
    """

    ledger = open_topic_ledger(paths, settings.program)
    lines_document = None
    outcomes: list[dict[str, Any]] = []
    for topic in topics_by_status(ledger.read(), "rejected"):
        if last_rejection_reason(topic) != "admission_hold":
            continue
        line = str(topic.get("research_line") or "").strip()
        if not line:
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
    """Queue one lead-tier admission review of this program's proposed topics."""

    if not settings.program.enabled:
        return ReviewSchedule(reason="program_disabled")
    if not budget_control.routing_enabled(settings):
        return ReviewSchedule(reason="admission_requires_provider_routing")
    campaign_id = str(campaign["campaign_id"])
    project = load_project(str(campaign["project_config_path"]))
    ledger = open_topic_ledger(paths, settings.program)
    proposed = [
        topic
        for topic in topics_by_status(ledger.read(), "proposed")
        if topic.get("program_project_id") == project.project_id
    ]
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
            reason="admission_batches_in_flight" if reviewing else "awaiting_topic_cards"
        )
    cap = settings.program.max_concurrent_admissions
    if cap > 0 and len(in_flight) >= cap:
        return ReviewSchedule(reason="max_concurrent_admissions")
    pending.sort(key=lambda item: (_proposal_time(item), str(item["topic_id"])))
    provider = str(pending[0].get("proposer_provider") or HUMAN_PROVIDER)
    batch_size = max(1, int(workstream_policy(campaign).get("review_batch_size") or 8))
    batch = [
        topic for topic in pending
        if str(topic.get("proposer_provider") or HUMAN_PROVIDER) == provider
    ][:batch_size]
    entries: list[dict[str, Any]] = []
    snapshot_document = ledger.read()
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
        }
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
            "admission_policy": ADMISSION_POLICY_VERSION,
            **(
                {"research_lines": {line: line_summary(lines_document, line)
                                    for line in line_ids}}
                if line_ids else {}
            ),
            "ledger_snapshot": _ledger_snapshot(ledger.read()),
            "read_resources": program_read_resources(paths, settings, ledger),
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
                "Check (1) the entry exists in that queue file with the same target and verdict "
                "`unreported`, and the card's occupancy_search equals the entry's; (2) re-run one "
                "of its queries yourself; (3) the plan covers the template's minimum_content and "
                "the line's minimum_validation; (4) the routine venues are the template's and "
                "their fee route is verified; (5) cost and compute plan match the template. Admit "
                "when all pass; otherwise reject or hold naming the failed item."
                if line_ids else ""
            )
        ),
        input_path=str(packet_path),
        skill_path=ADMISSION_SKILL,
        runner="frontier",
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

    Only with ``[program].max_admissions_per_domain`` above 1, and only while
    the campaign has fewer admission reviews queued or running than that.
    """

    limit = settings.program.max_admissions_per_domain
    if not settings.program.enabled or limit <= 1:
        return False
    if workstream_policy(campaign).get("continuation") != "review_on_new_results":
        return False
    project = campaign_project(campaign)
    if project is None or not project.program:
        return False
    campaign_id = str(campaign.get("campaign_id") or "")
    flights = _program_tasks(
        db, statuses=IN_FLIGHT_STATUSES, where="AND campaign_id=? AND routing_reason=?",
        parameters=(campaign_id, ADMISSION_ROUTING_REASON),
    )
    others = _program_tasks(
        db, statuses=IN_FLIGHT_STATUSES,
        where="AND campaign_id=? AND COALESCE(routing_reason, '')<>?",
        parameters=(campaign_id, ADMISSION_ROUTING_REASON),
    )
    return not others and len(flights) < limit


def parallel_routing_reasons(settings: FactorySettings) -> tuple[str, ...]:
    """Routing reasons whose tasks may run beside a sibling of the same campaign."""

    if settings.program.enabled and settings.program.max_admissions_per_domain > 1:
        return (ADMISSION_ROUTING_REASON,)
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
        summary = _summary(admission, review_task_id)
        status = str(topic.get("status"))
        verdict = str(admission.get("verdict"))
        if status != "proposed" and not _decided_by(topic, review_task_id):
            # Decided elsewhere (another review, admission_undecided): leave it.
            note("unchanged", f"topic_already_{status}")
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
    ledger = open_topic_ledger(paths, settings.program)
    parked = parked_program_projects(paths)
    skipped: set[str] = set()
    while True:
        document = ledger.read()
        if not slot_status(document, settings.program, parked).can_materialize:
            break
        # Admitted topics of a paused program project wait until it is active again.
        queue = [topic for topic in waiting_admitted(document, admission_sequence(db))
                 if str(topic["topic_id"]) not in skipped
                 and str(topic.get("program_project_id") or "") not in parked]
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
                "with the precheck evidence. Follow the research line's SOP and environment "
                "in registry/research-lines.yaml."
                if isinstance(card.get("feasibility_precheck"), Mapping) else ""
            )
            + conditions_instruction(record_conditions(record))
        ).strip()
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
                          "max_agent_seconds": budget},
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


# --------------------------------------------------------------------------- tick


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
    try:
        outcomes = register_scout_results(db, paths, settings)
        info["cards_registered"] = [item for item in outcomes if item["status"] == "proposed"]
        info["rejected_cards"] = [item for item in outcomes if item["status"] == "rejected"]
        info["card_repairs"] = schedule_card_repairs(db, paths, settings)
        report.enqueued.extend(
            str(item["task_id"]) for item in info["card_repairs"] if item.get("task_id")
        )
        info["holds_released"] = release_ready_holds(db, paths, settings)
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
            document, settings.program, parked_program_projects(paths)).to_dict())
        info.setdefault("admissions_scheduled", [])
        info.setdefault("admission_decisions", [])
    except (OSError, TopicLedgerError, KeyError, TypeError, ValueError,
            json.JSONDecodeError) as exc:
        report.errors.append(f"program pipeline: {exc}")
        info["pipeline_error"] = str(exc)
