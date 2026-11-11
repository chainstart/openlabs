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
  materializes admitted topics, in admission order, as research campaigns.

Whether a topic is worth doing is never decided here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import assets as asset_library
from . import budget as budget_control
from .config import FactorySettings, WorkspacePaths
from .contracts import (
    artifact_digests,
    atomic_write_json,
    canonical_json_bytes,
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
    TopicLedger,
    TopicLedgerError,
    activate_topic,
    admit_topic,
    card_sha256,
    find_topic,
    note_admission_attempt,
    open_topic_ledger,
    propose_topic,
    record_rejected_card,
    reject_topic,
    slot_status,
    topic_for_campaign,
    topics_by_status,
)
from .program_autonomy import topic_budget_seconds
from .projects import ProjectConfig, load_project, workstream_policy
from .resources import ResourceVector, default_task_resources

SCOUT_TASK_TYPE = "topic_scout"
ADMISSION_ROUTING_REASON = "topic_admission"
SCOUT_ROUTING_REASON = "program_slot_open"
SCOUT_PACKET_SCHEMA = "openlabs.topic_scout_packet.v1"
ADMISSION_RECORD_SCHEMA = "openlabs.topic_admission_record.v1"
SCOUT_SKILL = "openlabs-empirical-topic-scout"
ADMISSION_SKILL = "openlabs-topic-admission"
LAST_SCOUT_KEY = "program_last_scout_at"
SCOUT_REGISTERED_PREFIX = "program_scout_registered:"
# A topic included in this many admission packets without a valid decision is
# rejected as ``admission_undecided`` (it may be resubmitted as a new card).
MAX_ADMISSION_ATTEMPTS = 3
HUMAN_PROVIDER = "human"
IN_FLIGHT_STATUSES = ("queued", "leased", "running")
POOL_STATUSES = ("proposed",)
DOMAIN_LOAD_STATUSES = ("proposed", "admitted", "active", "in_review")
# Research campaigns may continue in these ledger states (enforce_admission).
ADMITTED_WORK_STATUSES = ("admitted", "active", "in_review", "ready_queue", "submitted")


# --------------------------------------------------------------------------- helpers


def _control_root(paths: WorkspacePaths) -> Path:
    return paths.artifacts / "program-control"


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


def program_projects(paths: WorkspacePaths) -> list[ProjectConfig]:
    """Active research-program projects (invalid configs are reported elsewhere)."""

    root = paths.data / "workspaces"
    found: list[ProjectConfig] = []
    candidates = {
        *root.glob("*/projects/*/project.json"),
        *root.glob("*/production/*/project.json"),
    }
    for path in sorted(candidates):
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
                "question": topic.get("question"),
                "fingerprint": topic.get("fingerprint"),
                "status": topic.get("status"),
                "rejection_reason": (
                    last_rejection_reason(topic) if topic.get("status") == "rejected" else None
                ),
                "freeze_reason_class": topic.get("freeze_reason_class"),
                "reopen_conditions": topic.get("reopen_conditions") or [],
                "supersedes": topic.get("supersedes"),
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
) -> tuple[ProjectConfig, str] | None:
    """Domain with the fewest topics in flight; ties go to the least recently scouted.

    ``[program].domains`` restricts the rotation and breaks remaining ties by
    its order.
    """

    configured = list(settings.program.domains)
    usable: list[tuple[ProjectConfig, str]] = []
    for project in projects:
        if configured and project.domain not in configured:
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
        domain = str(topic.get("domain") or "")
        load[domain] = load.get(domain, 0) + 1
    last = db.meta_items(LAST_SCOUT_KEY + ":")

    def key(item: tuple[ProjectConfig, str]) -> tuple[int, str, int, str]:
        project = item[0]
        order = configured.index(project.domain) if project.domain in configured else 0
        return (load.get(project.domain, 0), last.get(project.domain, ""), order,
                project.project_id)

    return min(usable, key=key)


def maybe_schedule_scout(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    lead_short: bool,
    now: datetime | None = None,
) -> ScoutDecision:
    program = settings.program
    if not program.enabled:
        return ScoutDecision(reason="program_disabled")
    if not budget_control.routing_enabled(settings):
        # Without provider routing the proposer and judge families cannot be
        # told apart, so the gate could not be independent.
        return ScoutDecision(reason="provider_routing_not_configured")
    ledger = open_topic_ledger(paths, program)
    document = ledger.read()
    status = slot_status(document, program)
    if status.admission_paused:
        return ScoutDecision(reason="admission_paused")
    if status.free_slots <= 0:
        return ScoutDecision(reason="no_free_slot")
    if len(_proposed_pool(document)) >= program.candidate_pool_low_water:
        return ScoutDecision(reason="candidate_pool_at_low_water")
    if lead_short:
        return ScoutDecision(reason="lead_quota_short")
    if _program_tasks(db, statuses=IN_FLIGHT_STATUSES, where="AND task_type=?",
                      parameters=(SCOUT_TASK_TYPE,)):
        return ScoutDecision(reason="scout_in_flight")
    moment = now or _now_moment()
    last = budget_control.parse_time(db.meta_get(LAST_SCOUT_KEY))
    if last is not None and moment - last < timedelta(hours=program.scout_min_interval_hours):
        return ScoutDecision(reason="scout_min_interval")
    chosen = _choose_scout_project(db, settings, program_projects(paths), document)
    if chosen is None:
        return ScoutDecision(reason="no_program_project")
    project, campaign_id = chosen
    campaign = db.campaign(campaign_id) or {}
    stamp = _iso(moment)
    digest = hashlib.sha256(f"{campaign_id}\0{stamp}".encode()).hexdigest()
    task_id = f"topic-scout:{digest[:32]}"
    max_cards = max(1, program.candidate_pool_low_water - len(_proposed_pool(document)))
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
            f"({project.project_id}). Read the packet at the input path: the topic ledger "
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
        {LAST_SCOUT_KEY: stamp, f"{LAST_SCOUT_KEY}:{project.domain}": stamp},
        events=[
            (
                "program",
                project.project_id,
                "topic_scout_scheduled",
                {"task_id": task_id, "domain": project.domain, "max_cards": max_cards,
                 "free_slots": status.free_slots},
            )
        ],
    )
    return ScoutDecision(task_id=task_id, domain=project.domain)


# --------------------------------------------------------------------------- card intake


def _card_metadata(
    project: ProjectConfig,
    card: Mapping[str, Any],
    *,
    source_task_id: str | None,
    provider: str,
) -> dict[str, Any]:
    venues = card.get("venues") if isinstance(card.get("venues"), Mapping) else {}
    return {
        "program_project_id": project.project_id,
        "source_task_id": source_task_id,
        "proposer_provider": provider,
        "routine_fallback": venues.get("routine") if isinstance(venues, Mapping) else None,
        "cost_estimate": card.get("cost_estimate"),
    }


def _store_card(paths: WorkspacePaths, project: ProjectConfig, card: Mapping[str, Any]) -> Path:
    """Content-addressed copy of a registered card (the ledger keeps its hash)."""

    digest = card_sha256(card)
    path = _control_root(paths) / _token(project.project_id) / "cards" / f"topic-{digest[:16]}.json"
    if not path.is_file():
        atomic_write_json(path, dict(card))
    return path


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
) -> dict[str, Any]:
    """Validate one card and register it; return ``{topic_id, status, reason, errors}``."""

    ledger = open_topic_ledger(paths, settings.program)
    card: dict[str, Any] = dict(raw_card) if isinstance(raw_card, Mapping) else {
        "invalid_card": raw_card
    }
    # Topic identity is the control plane's (card hash), never agent-chosen.
    card.pop("topic_id", None)
    card["domain"] = project.domain
    errors = list(validate_topic_card(card).errors)
    errors.extend(asset_library.card_reference_errors(paths, settings, card))
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
    metadata = _card_metadata(project, card, source_task_id=source_task_id, provider=provider)
    if errors:
        decision = record_rejected_card(
            ledger, card, db=db, decided_by=decided_by, errors=errors, metadata=metadata
        )
        return {"topic_id": decision.topic_id, "status": "rejected", "reason": "card_invalid",
                "errors": errors}
    metadata["card_path"] = str(_store_card(paths, project, card))
    try:
        decision = propose_topic(ledger, card, db=db, decided_by=decided_by, metadata=metadata)
    except TopicLedgerError as exc:
        decision = record_rejected_card(
            ledger, card, db=db, decided_by=decided_by, errors=[str(exc)], metadata=metadata
        )
        return {"topic_id": decision.topic_id, "status": "rejected", "reason": "card_invalid",
                "errors": [str(exc)]}
    return {
        "topic_id": decision.topic_id,
        "status": decision.status,
        "reason": decision.reason,
        "errors": [],
        "duplicate_of": list(decision.duplicate_of),
    }


def register_scout_results(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
) -> list[dict[str, Any]]:
    """Register the cards of every succeeded, not yet registered scout result."""

    outcomes: list[dict[str, Any]] = []
    done = db.meta_items(SCOUT_REGISTERED_PREFIX)
    for task in _program_tasks(db, statuses=("succeeded",), where="AND task_type=?",
                               parameters=(SCOUT_TASK_TYPE,)):
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
        task_outcomes = [
            {"source_task_id": task_id, **intake_card(
                db, paths, settings, project, card, decided_by=task_id, provider=provider,
                source_task_id=task_id, receipt_digests=digests,
            )}
            for card in cards
        ]
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
    pending: list[dict[str, Any]] = []
    for topic in proposed:
        if len(topic.get("admission_attempts") or []) >= MAX_ADMISSION_ATTEMPTS:
            reject_topic(
                ledger, str(topic["topic_id"]), db=db, reason="admission_undecided",
                decided_by=f"program:{campaign_id}",
            )
            continue
        pending.append(topic)
    if not pending:
        return ReviewSchedule(reason="awaiting_topic_cards")
    pending.sort(key=lambda item: (_proposal_time(item), str(item["topic_id"])))
    provider = str(pending[0].get("proposer_provider") or HUMAN_PROVIDER)
    batch_size = max(1, int(workstream_policy(campaign).get("review_batch_size") or 8))
    batch = [
        topic for topic in pending
        if str(topic.get("proposer_provider") or HUMAN_PROVIDER) == provider
    ][:batch_size]
    entries: list[dict[str, Any]] = []
    for topic in batch:
        card_path = Path(str(topic.get("card_path") or ""))
        if not card_path.is_file():
            raise ValueError(f"topic {topic['topic_id']} card file is missing: {card_path}")
        card = _read_object(card_path)
        if card_sha256(card) != topic.get("card_sha256"):
            raise ValueError(f"topic {topic['topic_id']} card file differs from the ledger")
        entries.append(
            {
                "topic_id": topic["topic_id"],
                "source_result_id": _source_id(topic),
                "card_sha256": topic["card_sha256"],
                "proposer_provider": provider,
                "card": card,
            }
        )
    asset_library.annotate_admission_entries(paths, settings, entries)
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
            f"Act as the admission gate of the {project.domain} research program. Judge every "
            f"topic card in the review packet ({len(entries)} card(s)) the way a journal editor "
            "would: find the strongest reason to reject first, check each closest prior work "
            "yourself, confirm the decisive data is really accessible, and weigh the estimated "
            "cost against the tier the result could reach. Return exactly one "
            "candidate_branches entry per card with candidate_id and topic_id set to the card's "
            "topic_id, source_result_ids = [its source_result_id], title, objective, rationale "
            "and an `admission` object (verdict admit/reject/hold, target_tier, tier_rationale, "
            "strongest_rejection_reason, closest_prior_work_checked, data_access_confirmed, "
            "cost_judgement, preregistration with its sha256, reopen_conditions). Rejecting "
            "every card is a valid outcome. Do not start the research."
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
        "preregistration_sha256": (
            preregistration.get("sha256") if isinstance(preregistration, Mapping) else None
        ),
        "review_task_id": review_task_id,
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
            if problem:
                if status == "proposed":
                    reject_topic(ledger, topic_id, db=db, reason=problem,
                                 decided_by=review_task_id, evidence=evidence, admission=summary)
                note("rejected", problem)
                continue
            if status == "proposed":
                preregistration = admission["preregistration"]
                record_path = _admission_record_path(paths, topic_id)
                if not record_path.is_file():
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
                                for key in ("title", "objective", "rationale", "resources",
                                            "wall_seconds")
                                if branch.get(key) is not None
                            },
                            "admission": dict(admission),
                            "card": dict(card),
                            "card_sha256": entry.get("card_sha256"),
                            "preregistration": {
                                "primary_endpoint": preregistration["primary_endpoint"],
                                "sha256": preregistration["sha256"],
                            },
                            "created_at": utc_now(),
                        },
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
    }


def materialize_waiting_topics(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
) -> CandidateSpawn:
    """Turn admitted topics into campaigns, oldest admission first, while slots allow."""

    campaign_ids: list[str] = []
    task_ids: list[str] = []
    ledger = open_topic_ledger(paths, settings.program)
    skipped: set[str] = set()
    while True:
        document = ledger.read()
        if not slot_status(document, settings.program).can_materialize:
            break
        queue = [topic for topic in waiting_admitted(document, admission_sequence(db))
                 if str(topic["topic_id"]) not in skipped]
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
        spawned = materialize_waiting_topics(db, paths, settings)
        report.enqueued.extend(spawned.task_ids)
        report.production_synced.extend(spawned.campaign_ids)
        info["materialized"] = list(spawned.campaign_ids)
        decision = maybe_schedule_scout(
            db, paths, settings, lead_short=lead_quota_short(db, settings)
        )
        if decision.task_id is not None:
            report.enqueued.append(decision.task_id)
        info["scouts_scheduled"] = (
            [{"task_id": decision.task_id, "domain": decision.domain}]
            if decision.task_id else []
        )
        info["scout_blocked"] = decision.reason
        document = open_topic_ledger(paths, settings.program).read()
        info["candidate_pool"] = len(_proposed_pool(document))
        info["candidate_pool_topics"] = [str(t["topic_id"]) for t in _proposed_pool(document)]
        info["waiting_admitted"] = [
            str(t["topic_id"]) for t in waiting_admitted(document, admission_sequence(db))
        ]
        info.update(slot_status(document, settings.program).to_dict())
        info.setdefault("admissions_scheduled", [])
        info.setdefault("admission_decisions", [])
    except (OSError, TopicLedgerError, KeyError, TypeError, ValueError,
            json.JSONDecodeError) as exc:
        report.errors.append(f"program pipeline: {exc}")
        info["pipeline_error"] = str(exc)
