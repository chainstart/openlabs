"""Research-program controller: topic ledger, active-topic slots and freezes.

This module is deterministic bookkeeping and routing only. Every scientific
judgement (whether a topic is worth admitting, whether a result failed, which
reopen condition was met) is made by an independent agent task; the functions
here record such decisions, enforce the topic lifecycle, count slots and stop
the campaigns of frozen topics.

Canonical state lives in the data repository's topic ledger
(``registry/topic-ledger.json`` by default). Every write takes an exclusive
file lock, rewrites the whole document atomically (temporary file + replace)
and is idempotent: applying the same decision twice yields one history entry
and one ``events`` row.

Lifecycle::

    proposed -> rejected | admitted -> active -> in_review -> ready_queue -> submitted
                                       active | in_review -> frozen
                                       ready_queue -> in_review   (release pipeline: a post-ready
                                                                   change needs a full review)

Reopening a frozen topic, or one the admission gate rejected or held, is a new
proposal with a new ``topic_id`` whose card declares ``reopens``; the new topic
records ``supersedes``. A held topic, or one rejected for a fixable reason, may
instead come back once as a revision card (``revises``; the new topic records
``revision_of`` and ``supersedes``) that the gate checks only against the
recorded reopen conditions.

Two guarded moves leave ``rejected`` (ledger schema v2): a hold whose only
blocker was its research line's environment returns to ``proposed`` for the
gate, or straight to ``admitted`` when the gate had already admitted it, once
the line is ready (``release_held_topic``).
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import ProgramSettings, WorkspacePaths
from .contracts import FREEZE_REASON_CLASSES as CONTRACT_FREEZE_REASON_CLASSES
from .contracts import REOPEN_BASIS_TYPES as CONTRACT_REOPEN_BASIS_TYPES
from .contracts import atomic_write_json, canonical_json_bytes
from .db import FactoryDB, utc_now

LEDGER_SCHEMA = "openlabs.topic_ledger.v2"
# v1 ledgers (no revision, repair or hold-release fields) are read unchanged and
# written back as v2 on their next change.
READABLE_LEDGER_SCHEMAS = frozenset({"openlabs.topic_ledger.v1", LEDGER_SCHEMA})

TOPIC_STATUSES = (
    "proposed",
    "rejected",
    "admitted",
    "active",
    "in_review",
    "ready_queue",
    "submitted",
    "frozen",
)
TRANSITIONS: dict[str | None, frozenset[str]] = {
    None: frozenset({"proposed"}),
    "proposed": frozenset({"rejected", "admitted"}),
    "admitted": frozenset({"active"}),
    "active": frozenset({"in_review", "frozen"}),
    "in_review": frozenset({"ready_queue", "frozen"}),
    # ready_queue -> in_review: the release pipeline found that a post-ready change
    # (formal fix, support citation) is beyond the delta review and needs a full one.
    "ready_queue": frozenset({"submitted", "in_review"}),
    "submitted": frozenset(),
    # Only the guarded hold releases below leave ``rejected``.
    "rejected": frozenset({"proposed", "admitted"}),
    "frozen": frozenset(),
}
# Transitions allowed only with these reasons (see ``release_held_topic``).
HOLD_RELEASE_FOR_REVIEW = "hold_released_for_review"
HOLD_RELEASE_ADMITTED = "hold_released_admitted"
GUARDED_TRANSITIONS: dict[tuple[str, str], frozenset[str]] = {
    ("rejected", "proposed"): frozenset({HOLD_RELEASE_FOR_REVIEW}),
    ("rejected", "admitted"): frozenset({HOLD_RELEASE_ADMITTED}),
}
# Statuses that hold one of the ``max_active_topics`` research slots.
# ``admitted`` is a reservation: the topic passed the admission gate but its
# campaign is not materialized yet, so it must already count against capacity.
SLOT_STATUSES = ("admitted", "active", "in_review")
FREEZABLE_STATUSES = ("active", "in_review")
# Shared with the direction-decision contract (``contracts.FREEZE_REASON_CLASSES``).
FREEZE_REASON_CLASSES = CONTRACT_FREEZE_REASON_CLASSES
# Shared with the topic-card and admission contracts (``contracts.REOPEN_BASIS_TYPES``).
REOPEN_CONDITION_TYPES = CONTRACT_REOPEN_BASIS_TYPES
TOPIC_EVENT_TYPES = {
    "proposed": "topic_proposed",
    "rejected": "topic_rejected",
    "admitted": "topic_admitted",
    "active": "topic_activated",
    "in_review": "topic_in_review",
    "ready_queue": "topic_ready",
    "submitted": "topic_submitted",
    "frozen": "topic_frozen",
}
TOPIC_FIELDS = (
    "topic_id",
    "domain",
    "question",
    "fingerprint",
    "status",
    "target_tier",
    "campaign_id",
    "paper_id",
    "card_sha256",
    "preregistration_sha256",
    "admission_task_id",
    "admitted_at",
    "frozen_at",
    "freeze_reason_class",
    "freeze_evidence",
    "decided_by",
    "reopen_conditions",
    "supersedes",
    # Research-program pipeline metadata (absent from ledgers written before it).
    "program_project_id",
    "source_task_id",
    "proposer_provider",
    "card_path",
    "card_errors",
    "routine_fallback",
    "cost_estimate",
    "admission",
    "admission_attempts",
    # Autonomous back half (absent from ledgers written before it).
    "awaiting_owner_review",
    "handoff",
    # Release pipeline state between ready and delivery (stage, attempts, last error).
    "release",
    # Admission policy v2 (absent from older ledgers): one automatic repair of a
    # format-invalid card, and one revision of a held or fixably rejected topic.
    "card_repair",
    "repair_of",
    "revision",
    "revision_of",
    "history",
)
# Rejections that judged the topic on its merits. A card with the same
# fingerprint is a duplicate of such a topic and may only come back through a
# card that declares ``reopens``. Format or bookkeeping rejections
# (``card_invalid``, ``duplicate_fingerprint``, ``admission_undecided``, ...)
# do not block a corrected resubmission.
JUDGED_REJECTION_REASONS = frozenset(
    {
        "admission_rejected",
        "admission_hold",
        "data_access_not_confirmed",
        "not_computational_only",
        "cost_not_proportionate",
    }
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_TOPIC_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


class TopicLedgerError(ValueError):
    """The ledger or a requested decision is invalid."""


class IllegalTopicTransition(TopicLedgerError):
    """A lifecycle transition that the state machine does not allow."""


class TopicSlotUnavailable(TopicLedgerError):
    """Admission requested while no slot is free or admissions are paused."""


# --------------------------------------------------------------------------- helpers


def normalize_text(value: Any) -> str:
    """Case/width/punctuation-insensitive normal form used by fingerprints."""

    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def _source_list(value: Any) -> list[str]:
    if value is None:
        return []
    items = [value] if isinstance(value, str | Mapping) else list(value)
    normalized: set[str] = set()
    for item in items:
        if isinstance(item, Mapping):
            item = (
                item.get("source_id")
                or item.get("id")
                or item.get("doi")
                or item.get("url")
                or item.get("name")
            )
        text = normalize_text(item)
        if text:
            normalized.add(text)
    return sorted(normalized)


def topic_fingerprint(question: Any, data_sources: Any, primary_endpoint: Any) -> str:
    """Hash of normalized question text, data-source identifiers and primary endpoint."""

    question_text = normalize_text(question)
    if isinstance(primary_endpoint, Mapping):
        # Key order of a structured endpoint block must not change the identity.
        primary_endpoint = json.dumps(primary_endpoint, sort_keys=True, ensure_ascii=False)
    endpoint_text = normalize_text(primary_endpoint)
    if not question_text:
        raise TopicLedgerError("topic question is required for a fingerprint")
    if not endpoint_text:
        raise TopicLedgerError("topic primary_endpoint is required for a fingerprint")
    sources = _source_list(data_sources)
    if not sources:
        raise TopicLedgerError("topic data source identifiers are required for a fingerprint")
    payload = {"question": question_text, "data_sources": sources, "endpoint": endpoint_text}
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def card_sha256(card: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(card))).hexdigest()


def _evidence_list(evidence: Any, *, required: bool, label: str) -> list[dict[str, str]]:
    if evidence is None:
        items: list[Any] = []
    elif isinstance(evidence, Mapping):
        items = [evidence]
    else:
        items = list(evidence)
    result: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise TopicLedgerError(f"{label} items must be objects with path and sha256")
        path = str(item.get("path") or "").strip()
        digest = str(item.get("sha256") or "").strip().lower()
        if not path or not _SHA256.fullmatch(digest):
            raise TopicLedgerError(f"{label} items need a path and a 64-hex sha256")
        result.append({"path": path, "sha256": digest})
    if required and not result:
        raise TopicLedgerError(f"{label} is required")
    return result


def _reopen_conditions(value: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in list(value or []):
        if not isinstance(item, Mapping):
            raise TopicLedgerError("reopen_conditions items must be objects")
        kind = str(item.get("type") or "").strip()
        description = str(item.get("description") or "").strip()
        if kind not in REOPEN_CONDITION_TYPES:
            raise TopicLedgerError(f"unsupported reopen condition type {kind!r}")
        if not description:
            raise TopicLedgerError("reopen condition description is required")
        result.append({"type": kind, "description": description})
    return result


def _event_key(topic_id: str, from_status: str | None, to_status: str, payload: Any) -> str:
    body = {"topic_id": topic_id, "from": from_status, "to": to_status, "payload": payload}
    return hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def empty_ledger() -> dict[str, Any]:
    return {"schema_version": LEDGER_SCHEMA, "updated_at": None, "topics": []}


def validate_ledger(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TopicLedgerError("topic ledger must be a JSON object")
    if payload.get("schema_version") not in READABLE_LEDGER_SCHEMAS:
        raise TopicLedgerError(
            f"topic ledger schema_version must be one of {sorted(READABLE_LEDGER_SCHEMAS)}"
        )
    topics = payload.get("topics")
    if not isinstance(topics, list):
        raise TopicLedgerError("topic ledger topics must be a list")
    seen: set[str] = set()
    for topic in topics:
        if not isinstance(topic, dict):
            raise TopicLedgerError("topic ledger entries must be objects")
        topic_id = str(topic.get("topic_id") or "")
        if not topic_id or topic_id in seen:
            raise TopicLedgerError(f"topic ledger has a missing or duplicate topic_id {topic_id!r}")
        seen.add(topic_id)
        if topic.get("status") not in TOPIC_STATUSES:
            raise TopicLedgerError(f"topic {topic_id} has unknown status {topic.get('status')!r}")
        if not isinstance(topic.get("history"), list):
            raise TopicLedgerError(f"topic {topic_id} history must be a list")
    return payload


def _new_topic(topic_id: str) -> dict[str, Any]:
    topic: dict[str, Any] = {name: None for name in TOPIC_FIELDS}
    topic.update(
        {
            "topic_id": topic_id,
            "freeze_evidence": [],
            "reopen_conditions": [],
            "history": [],
        }
    )
    return topic


# --------------------------------------------------------------------------- ledger


@dataclass(frozen=True)
class TopicLedger:
    """Locked, atomic access to one topic-ledger JSON document."""

    path: Path
    lock_path: Path

    def read(self) -> dict[str, Any]:
        """Return the ledger, or an empty one if the file does not exist yet."""

        if not self.path.exists():
            return empty_ledger()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise TopicLedgerError(f"topic ledger {self.path} is not valid JSON: {exc}") from exc
        return validate_ledger(payload)

    def topic(self, topic_id: str) -> dict[str, Any] | None:
        return find_topic(self.read(), topic_id)

    @contextmanager
    def transaction(self) -> Iterator[dict[str, Any]]:
        """Yield a mutable ledger; write it back atomically only if it changed."""

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                document = self.read()
                before = copy.deepcopy(document)
                yield document
                if document != before:
                    document["schema_version"] = LEDGER_SCHEMA
                    validate_ledger(document)
                    document["updated_at"] = utc_now()
                    atomic_write_json(self.path, document)
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def resolve_ledger_path(paths: WorkspacePaths, settings: ProgramSettings) -> Path:
    relative = Path(settings.ledger_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise TopicLedgerError("program ledger_path must be relative to the data repository")
    return paths.data / relative


def open_topic_ledger(paths: WorkspacePaths, settings: ProgramSettings) -> TopicLedger:
    """Ledger in the data repository, locked through the runtime database directory."""

    return TopicLedger(
        path=resolve_ledger_path(paths, settings),
        lock_path=paths.database / "live" / "topic-ledger.lock",
    )


def find_topic(ledger: Mapping[str, Any], topic_id: str) -> dict[str, Any] | None:
    for topic in ledger.get("topics") or []:
        if topic.get("topic_id") == topic_id:
            return topic
    return None


def topics_by_status(ledger: Mapping[str, Any], *statuses: str) -> list[dict[str, Any]]:
    wanted = set(statuses)
    return [topic for topic in ledger.get("topics") or [] if topic.get("status") in wanted]


def topic_for_campaign(ledger: Mapping[str, Any], campaign_id: str) -> dict[str, Any] | None:
    for topic in ledger.get("topics") or []:
        if topic.get("campaign_id") == campaign_id:
            return topic
    return None


# --------------------------------------------------------------------------- slots


@dataclass(frozen=True)
class SlotStatus:
    max_active_topics: int
    max_ready_unsubmitted: int
    admitted: int
    active: int
    in_review: int
    ready_unsubmitted: int
    status_counts: dict[str, int] = field(default_factory=dict)

    @property
    def occupied(self) -> int:
        return self.admitted + self.active + self.in_review

    @property
    def free_slots(self) -> int:
        return max(0, self.max_active_topics - self.occupied)

    @property
    def admission_paused(self) -> bool:
        return self.ready_unsubmitted > self.max_ready_unsubmitted

    @property
    def pause_reasons(self) -> list[str]:
        return ["ready_queue_over_limit"] if self.admission_paused else []

    @property
    def can_admit(self) -> bool:
        return self.free_slots > 0 and not self.admission_paused

    @property
    def research_free_slots(self) -> int:
        """Slots a waiting admitted topic may take now (admitted topics excluded)."""

        return max(0, self.max_active_topics - self.active - self.in_review)

    @property
    def can_materialize(self) -> bool:
        return self.research_free_slots > 0 and not self.admission_paused

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_active_topics": self.max_active_topics,
            "admitted": self.admitted,
            "active": self.active,
            "in_review": self.in_review,
            "occupied": self.occupied,
            "free_slots": self.free_slots,
            "ready_unsubmitted": self.ready_unsubmitted,
            "max_ready_unsubmitted": self.max_ready_unsubmitted,
            "admission_paused": self.admission_paused,
            "pause_reasons": self.pause_reasons,
            "can_admit": self.can_admit,
            "research_free_slots": self.research_free_slots,
            "status_counts": dict(self.status_counts),
        }


def slot_status(ledger: Mapping[str, Any], settings: ProgramSettings) -> SlotStatus:
    """Count research slots from a ledger document (pure; no I/O)."""

    counts = {status: 0 for status in TOPIC_STATUSES}
    for topic in ledger.get("topics") or []:
        status = str(topic.get("status"))
        counts[status] = counts.get(status, 0) + 1
    return SlotStatus(
        max_active_topics=settings.max_active_topics,
        max_ready_unsubmitted=settings.max_ready_unsubmitted,
        admitted=counts["admitted"],
        active=counts["active"],
        in_review=counts["in_review"],
        ready_unsubmitted=counts["ready_queue"],
        status_counts={key: value for key, value in counts.items() if value},
    )


def program_slots(paths: WorkspacePaths, settings: ProgramSettings) -> SlotStatus:
    """Read the configured ledger and return current slot occupancy."""

    return slot_status(open_topic_ledger(paths, settings).read(), settings)


# --------------------------------------------------------------------------- decisions


@dataclass(frozen=True)
class TopicDecision:
    topic_id: str
    status: str
    changed: bool
    reason: str = ""
    supersedes: str | None = None
    duplicate_of: tuple[str, ...] = ()
    cancelled_tasks: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "status": self.status,
            "changed": self.changed,
            "reason": self.reason,
            "supersedes": self.supersedes,
            "duplicate_of": list(self.duplicate_of),
            "cancelled_tasks": list(self.cancelled_tasks),
        }


def _apply_transition(
    topic: dict[str, Any],
    to_status: str,
    *,
    reason: str,
    decided_by: str,
    evidence: list[dict[str, str]],
    updates: Mapping[str, Any],
    at: str,
) -> tuple[bool, dict[str, Any]]:
    """Mutate ``topic``; return (changed, history entry). Raises on illegal moves."""

    topic_id = str(topic["topic_id"])
    if to_status not in TOPIC_STATUSES:
        raise IllegalTopicTransition(f"unknown topic status {to_status!r}")
    history = topic.setdefault("history", [])
    from_status = topic.get("status") if history else None
    key_payload = {
        "reason": reason,
        "decided_by": decided_by,
        "evidence": evidence,
        # Decision timestamps differ between replays and are not part of identity.
        "updates": {name: value for name, value in updates.items() if not name.endswith("_at")},
    }
    # A replay is recognized even after later moves (stale duplicate delivery).
    for entry in history:
        if entry.get("to") == to_status and entry.get("event_key") == _event_key(
            topic_id, entry.get("from"), to_status, key_payload
        ):
            return False, entry
    if to_status not in TRANSITIONS.get(from_status, frozenset()):
        raise IllegalTopicTransition(
            f"topic {topic_id}: transition {from_status or '(new)'} -> {to_status} is not allowed"
        )
    guarded = GUARDED_TRANSITIONS.get((str(from_status), to_status))
    if guarded is not None and reason not in guarded:
        raise IllegalTopicTransition(
            f"topic {topic_id}: {from_status} -> {to_status} needs reason {sorted(guarded)}"
        )
    entry = {
        "at": at,
        "from": from_status,
        "to": to_status,
        "reason": reason,
        "evidence": evidence,
        "decided_by": decided_by,
        "event_key": _event_key(topic_id, from_status, to_status, key_payload),
    }
    for name, value in updates.items():
        if name not in TOPIC_FIELDS or name in {"topic_id", "status", "history"}:
            raise TopicLedgerError(f"field {name!r} cannot be set by a transition")
        topic[name] = value
    topic["status"] = to_status
    topic["decided_by"] = decided_by
    history.append(entry)
    return True, entry


def _record_topic_event(
    db: FactoryDB,
    topic: Mapping[str, Any],
    entry: Mapping[str, Any],
    extra: Mapping[str, Any] | None = None,
) -> None:
    payload = {
        "from": entry.get("from"),
        "to": entry.get("to"),
        "reason": entry.get("reason"),
        "evidence": entry.get("evidence"),
        "decided_by": entry.get("decided_by"),
        "domain": topic.get("domain"),
        "campaign_id": topic.get("campaign_id"),
        "fingerprint": topic.get("fingerprint"),
    }
    payload.update(dict(extra or {}))
    db.record_event_once(
        "topic",
        str(topic["topic_id"]),
        TOPIC_EVENT_TYPES[str(entry["to"])],
        payload,
        event_key=str(entry["event_key"]),
    )


def transition_topic(
    ledger: TopicLedger,
    topic_id: str,
    to_status: str,
    *,
    db: FactoryDB,
    reason: str,
    decided_by: str,
    evidence: Any = None,
    updates: Mapping[str, Any] | None = None,
) -> TopicDecision:
    """Apply one validated lifecycle transition and record its event (idempotent)."""

    if not decided_by:
        raise TopicLedgerError("decided_by (deciding task id) is required")
    evidence_items = _evidence_list(evidence, required=False, label="evidence")
    with ledger.transaction() as document:
        topic = find_topic(document, topic_id)
        if topic is None:
            raise TopicLedgerError(f"unknown topic {topic_id}")
        changed, entry = _apply_transition(
            topic,
            to_status,
            reason=reason,
            decided_by=decided_by,
            evidence=evidence_items,
            updates=dict(updates or {}),
            at=utc_now(),
        )
        snapshot = copy.deepcopy(topic)
    _record_topic_event(db, snapshot, entry)
    return TopicDecision(
        topic_id=topic_id,
        status=str(snapshot["status"]),
        changed=changed,
        reason=reason,
        supersedes=snapshot.get("supersedes"),
    )


# Fields an automatic decision may set on a topic without changing its status.
NOTE_FIELDS = frozenset(
    {"awaiting_owner_review", "handoff", "paper_id", "release", "card_repair", "revision"}
)


def record_topic_note(
    ledger: TopicLedger,
    topic_id: str,
    *,
    db: FactoryDB,
    event_type: str,
    reason: str,
    decided_by: str,
    detail: Mapping[str, Any] | None = None,
    evidence: Any = None,
    updates: Mapping[str, Any] | None = None,
    key: str | None = None,
) -> bool:
    """Append a non-transition decision to a topic's history and write its event.

    Used for automatic decisions that leave the lifecycle status unchanged
    (direction decisions, deliveries, handler assignment). Notes carry ``kind``
    instead of ``from``/``to``, so lifecycle replay detection never sees them.
    Idempotent by ``key`` (default: the decision's content); returns True when a
    new history entry was written.
    """

    if not decided_by:
        raise TopicLedgerError("decided_by (deciding task id) is required")
    evidence_items = _evidence_list(evidence, required=False, label="evidence")
    values = dict(updates or {})
    unknown = set(values) - NOTE_FIELDS
    if unknown:
        raise TopicLedgerError(f"fields {sorted(unknown)} cannot be set by a note")
    body = {"kind": event_type, "reason": reason, "decided_by": decided_by,
            "detail": dict(detail or {}), "evidence": evidence_items}
    event_key = key or hashlib.sha256(
        canonical_json_bytes({"topic_id": topic_id, **body})
    ).hexdigest()
    with ledger.transaction() as document:
        topic = find_topic(document, topic_id)
        if topic is None:
            raise TopicLedgerError(f"unknown topic {topic_id}")
        history = topic.setdefault("history", [])
        written = not any(
            entry.get("kind") == event_type and entry.get("event_key") == event_key
            for entry in history
        )
        if written:
            history.append({"at": utc_now(), "status": topic.get("status"), **body,
                            "event_key": event_key})
            topic.update(copy.deepcopy(values))
        snapshot = copy.deepcopy(topic)
    db.record_event_once(
        "topic",
        topic_id,
        event_type,
        {
            "status": snapshot.get("status"),
            "reason": reason,
            "decided_by": decided_by,
            "detail": dict(detail or {}),
            "evidence": evidence_items,
            "domain": snapshot.get("domain"),
            "campaign_id": snapshot.get("campaign_id"),
        },
        event_key=event_key,
    )
    return written


def propose_topic(
    ledger: TopicLedger,
    card: Mapping[str, Any],
    *,
    db: FactoryDB,
    decided_by: str,
    metadata: Mapping[str, Any] | None = None,
) -> TopicDecision:
    """Register a topic card as ``proposed``, or record it as ``rejected``.

    Card fields: ``domain``, ``question``, ``data_sources`` (or ``data_source``),
    ``primary_endpoint``; optional ``topic_id``, ``target_tier``, ``reopens`` (the
    frozen topic id being reopened) and ``reopen_basis`` ({type, description}).
    A card whose fingerprint equals an existing topic's (including a topic the
    admission gate rejected or held) is rejected as a duplicate unless it
    validly reopens that frozen or judged-rejected topic. ``metadata`` sets
    pipeline fields (``source_task_id``, ``proposer_provider``, ...) on a new
    topic.
    """

    if not decided_by:
        raise TopicLedgerError("decided_by (deciding task id) is required")
    domain = str(card.get("domain") or "").strip()
    if not domain:
        raise TopicLedgerError("topic card domain is required")
    question = str(card.get("question") or "").strip()
    fingerprint = topic_fingerprint(
        question,
        card.get("data_sources", card.get("data_source")),
        card.get("primary_endpoint"),
    )
    digest = card_sha256(card)
    topic_id = str(card.get("topic_id") or f"topic-{digest[:16]}")
    if not _TOPIC_ID.fullmatch(topic_id):
        raise TopicLedgerError(f"invalid topic_id {topic_id!r}")
    reopens = str(card.get("reopens") or "").strip() or None
    revises = str(card.get("revises") or "").strip() or None
    now = utc_now()
    entries: list[dict[str, Any]] = []
    with ledger.transaction() as document:
        existing = find_topic(document, topic_id)
        if existing is not None:
            if existing.get("card_sha256") != digest:
                raise TopicLedgerError(
                    f"topic {topic_id} already exists with a different card"
                )
            snapshot = copy.deepcopy(existing)
            # Lifecycle entries only: notes (``kind``) are not transitions.
            entries = [entry for entry in snapshot.get("history") or [] if "to" in entry]
            changed = False
        else:
            rejection = ""
            duplicates: list[str] = []
            if reopens is not None:
                rejection = _reopen_problem(document, reopens, card.get("reopen_basis"))
            if not rejection and revises is not None:
                rejection = _revision_problem(document, revises, card.get("condition_responses"))
            if not rejection:
                for other in document["topics"]:
                    if other.get("fingerprint") != fingerprint:
                        continue
                    if other.get("status") == "rejected" and not judged_rejection(other):
                        continue
                    if other.get("topic_id") in {reopens, revises}:
                        continue
                    if other.get("status") in {"frozen", "rejected"} and _superseded(
                        document, other
                    ):
                        continue
                    duplicates.append(str(other["topic_id"]))
                if duplicates:
                    rejection = "duplicate_fingerprint"
            topic = _new_topic(topic_id)
            topic.update(
                {
                    "domain": domain,
                    "question": question,
                    "fingerprint": fingerprint,
                    "target_tier": card.get("target_tier"),
                    "card_sha256": digest,
                    "supersedes": (reopens or revises) if not rejection else None,
                    "revision_of": revises if not rejection else None,
                }
            )
            topic.update(_metadata_fields(metadata))
            document["topics"].append(topic)
            _, proposed = _apply_transition(
                topic,
                "proposed",
                reason="topic_card_submitted",
                decided_by=decided_by,
                evidence=[],
                updates={},
                at=now,
            )
            entries.append(proposed)
            if rejection:
                _, rejected = _apply_transition(
                    topic,
                    "rejected",
                    reason=rejection,
                    decided_by=decided_by,
                    evidence=[],
                    updates={},
                    at=now,
                )
                entries.append(rejected)
            snapshot = copy.deepcopy(topic)
            changed = True
    duplicate_of: tuple[str, ...] = ()
    for entry in entries:
        extra: dict[str, Any] = {"card_sha256": digest, "supersedes": snapshot.get("supersedes")}
        if entry.get("to") == "rejected" and entry.get("reason") == "duplicate_fingerprint":
            duplicate_of = tuple(
                str(topic["topic_id"])
                for topic in ledger.read()["topics"]
                if topic.get("fingerprint") == fingerprint and topic.get("topic_id") != topic_id
            )
            extra["duplicate_of"] = list(duplicate_of)
        _record_topic_event(db, snapshot, entry, extra)
    last = entries[-1] if entries else {}
    return TopicDecision(
        topic_id=topic_id,
        status=str(snapshot["status"]),
        changed=changed,
        reason=str(last.get("reason") or ""),
        supersedes=snapshot.get("supersedes"),
        duplicate_of=duplicate_of,
    )


_METADATA_FIELDS = frozenset(
    {
        "program_project_id",
        "research_line",
        "source_task_id",
        "proposer_provider",
        "card_path",
        "card_errors",
        "routine_fallback",
        "cost_estimate",
        "admission",
        "card_repair",
        "repair_of",
    }
)


def _metadata_fields(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    values = dict(metadata or {})
    unknown = set(values) - _METADATA_FIELDS
    if unknown:
        raise TopicLedgerError(f"unsupported topic metadata fields: {sorted(unknown)}")
    return copy.deepcopy(values)


def last_rejection_reason(topic: Mapping[str, Any]) -> str:
    for entry in reversed(list(topic.get("history") or [])):
        if entry.get("to") == "rejected":
            return str(entry.get("reason") or "")
    return ""


def judged_rejection(topic: Mapping[str, Any]) -> bool:
    """A rejected topic whose rejection was a decision on the topic itself."""

    return topic.get("status") == "rejected" and (
        last_rejection_reason(topic) in JUDGED_REJECTION_REASONS
    )


def record_rejected_card(
    ledger: TopicLedger,
    card: Mapping[str, Any],
    *,
    db: FactoryDB,
    decided_by: str,
    errors: Iterable[str],
    metadata: Mapping[str, Any] | None = None,
) -> TopicDecision:
    """Record a structurally invalid card as ``proposed -> rejected (card_invalid)``.

    The topic keeps the list of failed checks in ``card_errors``. Its fingerprint
    is stored when it can be computed, but an invalid card never blocks a
    corrected resubmission.
    """

    if not decided_by:
        raise TopicLedgerError("decided_by (deciding task id) is required")
    problems = [str(item) for item in errors if str(item).strip()]
    if not problems:
        raise TopicLedgerError("an invalid card needs at least one error")
    digest = card_sha256(card)
    topic_id = f"topic-{digest[:16]}"
    try:
        fingerprint: str | None = topic_fingerprint(
            card.get("question"),
            card.get("data_sources", card.get("data_source")),
            card.get("primary_endpoint"),
        )
    except TopicLedgerError:
        fingerprint = None
    now = utc_now()
    entries: list[dict[str, Any]] = []
    with ledger.transaction() as document:
        existing = find_topic(document, topic_id)
        if existing is not None:
            snapshot = copy.deepcopy(existing)
            changed = False
        else:
            topic = _new_topic(topic_id)
            topic.update(
                {
                    "domain": str(card.get("domain") or "").strip() or None,
                    "question": str(card.get("question") or "").strip() or None,
                    "fingerprint": fingerprint,
                    "card_sha256": digest,
                }
            )
            topic.update(_metadata_fields(metadata))
            topic["card_errors"] = problems
            document["topics"].append(topic)
            for status, reason in (("proposed", "topic_card_submitted"),
                                   ("rejected", "card_invalid")):
                _, entry = _apply_transition(
                    topic, status, reason=reason, decided_by=decided_by, evidence=[],
                    updates={}, at=now,
                )
                entries.append(entry)
            snapshot = copy.deepcopy(topic)
            changed = True
    for entry in entries:
        _record_topic_event(db, snapshot, entry, {"card_sha256": digest, "card_errors": problems})
    return TopicDecision(
        topic_id=topic_id,
        status=str(snapshot["status"]),
        changed=changed,
        reason="card_invalid",
    )


def note_admission_attempt(ledger: TopicLedger, topic_id: str, task_id: str) -> int:
    """Remember that ``task_id`` reviewed ``topic_id``; return the attempt count."""

    with ledger.transaction() as document:
        topic = find_topic(document, topic_id)
        if topic is None:
            raise TopicLedgerError(f"unknown topic {topic_id}")
        attempts = list(topic.get("admission_attempts") or [])
        if task_id not in attempts:
            attempts.append(task_id)
            topic["admission_attempts"] = attempts
        return len(attempts)


def _superseded(document: Mapping[str, Any], topic: Mapping[str, Any]) -> bool:
    return any(
        other.get("supersedes") == topic.get("topic_id") and other.get("status") != "rejected"
        for other in document.get("topics") or []
    )


def _reopen_problem(document: Mapping[str, Any], reopens: str, basis: Any) -> str:
    target = find_topic(document, reopens)
    if target is None:
        return "reopens_unknown_topic"
    if target.get("status") != "frozen" and not judged_rejection(target):
        return "reopens_topic_not_frozen"
    if _superseded(document, target):
        return "reopens_topic_already_superseded"
    if not isinstance(basis, Mapping):
        return "reopen_basis_missing"
    kind = str(basis.get("type") or "")
    if kind not in REOPEN_CONDITION_TYPES or not str(basis.get("description") or "").strip():
        return "reopen_basis_invalid"
    declared = {str(item.get("type")) for item in target.get("reopen_conditions") or []}
    if declared and kind not in declared:
        return "reopen_basis_not_declared_by_frozen_topic"
    return ""


# Reopen-condition types that a revision card cannot answer: the control plane
# releases these holds itself once the line's environment is ready.
AUTOMATIC_REOPEN_TYPES = frozenset({"line_environment_ready"})


def revision_eligible(topic: Mapping[str, Any]) -> bool:
    """Whether a judged topic may come back once as a revision card (``revises``).

    Holds qualify unless every recorded condition is one the control plane
    releases itself; a rejection qualifies when the gate (``admission.revisable``)
    or a recorded decision (``revision.eligible``) called its defect fixable. A
    revision card's own hold or rejection does not open a second revision.
    """

    if topic.get("status") != "rejected" or topic.get("revision_of"):
        return False
    marker = topic.get("revision") if isinstance(topic.get("revision"), Mapping) else {}
    if marker.get("eligible") is False:
        return False
    reason = last_rejection_reason(topic)
    if reason == "admission_hold":
        kinds = {str(item.get("type")) for item in topic.get("reopen_conditions") or []
                 if isinstance(item, Mapping)}
        return bool(kinds - AUTOMATIC_REOPEN_TYPES)
    if reason in JUDGED_REJECTION_REASONS:
        admission = topic.get("admission") if isinstance(topic.get("admission"), Mapping) else {}
        return marker.get("eligible") is True or admission.get("revisable") is True
    return False


def _revision_problem(document: Mapping[str, Any], revises: str, responses: Any) -> str:
    target = find_topic(document, revises)
    if target is None:
        return "revises_unknown_topic"
    if not revision_eligible(target):
        return "revises_topic_not_revisable"
    for other in document.get("topics") or []:
        if other.get("revision_of") == revises and other.get("topic_id") != revises:
            return "revises_topic_already_revised"
    conditions = list(target.get("reopen_conditions") or [])
    answered = {
        item.get("condition") for item in responses or [] if isinstance(item, Mapping)
    }
    wanted = {
        index for index, item in enumerate(conditions)
        if str((item or {}).get("type")) not in AUTOMATIC_REOPEN_TYPES
    }
    if wanted - answered:
        return "revision_misses_conditions:" + ",".join(str(i) for i in sorted(wanted - answered))
    return ""


def release_held_topic(
    ledger: TopicLedger,
    topic_id: str,
    *,
    db: FactoryDB,
    to_status: str,
    decided_by: str,
    evidence: Any = None,
    updates: Mapping[str, Any] | None = None,
) -> TopicDecision:
    """``rejected (admission_hold) -> proposed | admitted`` once the hold's blocker is gone.

    ``proposed`` sends the topic back to the gate (its attempts restart);
    ``admitted`` applies an admission the gate had already made. Each topic is
    released at most once.
    """

    topic = ledger.topic(topic_id)
    if topic is None:
        raise TopicLedgerError(f"unknown topic {topic_id}")
    if last_rejection_reason(topic) != "admission_hold":
        raise TopicLedgerError(f"topic {topic_id} is not held")
    if any(entry.get("reason") in {HOLD_RELEASE_FOR_REVIEW, HOLD_RELEASE_ADMITTED}
           for entry in topic.get("history") or []):
        raise TopicLedgerError(f"topic {topic_id} was already released from a hold")
    reason = HOLD_RELEASE_ADMITTED if to_status == "admitted" else HOLD_RELEASE_FOR_REVIEW
    values = dict(updates or {})
    if to_status == "proposed":
        values.setdefault("admission_attempts", [])
    else:
        values.setdefault("admitted_at", utc_now())
    return transition_topic(
        ledger, topic_id, to_status, db=db, reason=reason, decided_by=decided_by,
        evidence=evidence, updates=values,
    )


def admit_topic(
    ledger: TopicLedger,
    topic_id: str,
    *,
    db: FactoryDB,
    settings: ProgramSettings,
    decided_by: str,
    admission_task_id: str,
    preregistration_sha256: str | None = None,
    evidence: Any = None,
    target_tier: Any = None,
    admission: Any = None,
    queue_when_full: bool = False,
) -> TopicDecision:
    """``proposed -> admitted`` if a slot is free and admissions are not paused.

    With ``queue_when_full`` the admission is recorded even without a free
    slot: the topic then waits as ``admitted`` and is materialized in admission
    order once a research slot opens (see ``SlotStatus.can_materialize``).
    """

    if preregistration_sha256 is not None and not _SHA256.fullmatch(preregistration_sha256):
        raise TopicLedgerError("preregistration_sha256 must be a 64-hex digest")
    current = ledger.read()
    topic = find_topic(current, topic_id)
    if not queue_when_full and topic is not None and topic.get("status") == "proposed":
        status = slot_status(current, settings)
        if not status.can_admit:
            reasons = ["no_free_slot"] if status.free_slots <= 0 else []
            raise TopicSlotUnavailable(
                f"cannot admit {topic_id}: " + ", ".join(reasons + status.pause_reasons)
            )
    return transition_topic(
        ledger,
        topic_id,
        "admitted",
        db=db,
        reason="admission_gate_passed",
        decided_by=decided_by,
        evidence=evidence,
        updates={
            "admission_task_id": admission_task_id,
            "preregistration_sha256": preregistration_sha256,
            "admitted_at": utc_now(),
            **({"target_tier": target_tier} if target_tier is not None else {}),
            **({"admission": copy.deepcopy(admission)} if admission is not None else {}),
        },
    )


def reject_topic(
    ledger: TopicLedger,
    topic_id: str,
    *,
    db: FactoryDB,
    reason: str,
    decided_by: str,
    evidence: Any = None,
    reopen_conditions: Iterable[Mapping[str, Any]] = (),
    admission: Any = None,
) -> TopicDecision:
    """``proposed -> rejected``; a hold records its ``reopen_conditions``."""

    updates: dict[str, Any] = {}
    conditions = _reopen_conditions(reopen_conditions)
    if conditions:
        updates["reopen_conditions"] = conditions
    if admission is not None:
        updates["admission"] = copy.deepcopy(admission)
    return transition_topic(
        ledger, topic_id, "rejected", db=db, reason=reason, decided_by=decided_by,
        evidence=evidence, updates=updates,
    )


def activate_topic(
    ledger: TopicLedger,
    topic_id: str,
    *,
    db: FactoryDB,
    campaign_id: str,
    decided_by: str,
    evidence: Any = None,
) -> TopicDecision:
    """``admitted -> active`` once its campaign exists in the factory database."""

    if db.campaign(campaign_id) is None:
        raise TopicLedgerError(f"campaign {campaign_id} does not exist")
    owner = topic_for_campaign(ledger.read(), campaign_id)
    if owner is not None and owner.get("topic_id") != topic_id:
        raise TopicLedgerError(
            f"campaign {campaign_id} already belongs to topic {owner.get('topic_id')}"
        )
    return transition_topic(
        ledger, topic_id, "active", db=db, reason="campaign_materialized",
        decided_by=decided_by, evidence=evidence, updates={"campaign_id": campaign_id},
    )


def mark_topic_in_review(
    ledger: TopicLedger,
    topic_id: str,
    *,
    db: FactoryDB,
    decided_by: str,
    paper_id: str | None = None,
    evidence: Any = None,
) -> TopicDecision:
    updates = {"paper_id": paper_id} if paper_id else {}
    return transition_topic(
        ledger, topic_id, "in_review", db=db, reason="manuscript_entered_review",
        decided_by=decided_by, evidence=evidence, updates=updates,
    )


def mark_topic_ready(
    ledger: TopicLedger,
    topic_id: str,
    *,
    db: FactoryDB,
    decided_by: str,
    paper_id: str | None = None,
    evidence: Any = None,
) -> TopicDecision:
    updates = {"paper_id": paper_id} if paper_id else {}
    return transition_topic(
        ledger, topic_id, "ready_queue", db=db, reason="review_passed",
        decided_by=decided_by, evidence=evidence, updates=updates,
    )


def return_topic_to_review(
    ledger: TopicLedger,
    topic_id: str,
    *,
    db: FactoryDB,
    decided_by: str,
    evidence: Any = None,
    updates: Mapping[str, Any] | None = None,
) -> TopicDecision:
    """``ready_queue -> in_review``: a post-ready change needs a full unified review."""

    return transition_topic(
        ledger, topic_id, "in_review", db=db, reason="release_full_review_required",
        decided_by=decided_by, evidence=evidence, updates=updates,
    )


def mark_topic_submitted(
    ledger: TopicLedger,
    topic_id: str,
    *,
    db: FactoryDB,
    decided_by: str,
    evidence: Any = None,
) -> TopicDecision:
    return transition_topic(
        ledger, topic_id, "submitted", db=db, reason="manuscript_submitted",
        decided_by=decided_by, evidence=evidence,
    )


def freeze_topic(
    ledger: TopicLedger,
    topic_id: str,
    *,
    db: FactoryDB,
    reason_class: str,
    evidence: Any,
    decided_by: str,
    reopen_conditions: Iterable[Mapping[str, Any]] = (),
) -> TopicDecision:
    """``active|in_review -> frozen``: record the freeze, then stop its campaign.

    The ledger is written first (canonical); if the process dies before the
    campaign is frozen, :func:`reconcile_frozen_campaigns` finishes it on the next
    tick.
    """

    if reason_class not in FREEZE_REASON_CLASSES:
        raise TopicLedgerError(f"unsupported freeze reason class {reason_class!r}")
    evidence_items = _evidence_list(evidence, required=True, label="freeze_evidence")
    conditions = _reopen_conditions(reopen_conditions)
    decision = transition_topic(
        ledger,
        topic_id,
        "frozen",
        db=db,
        reason=reason_class,
        decided_by=decided_by,
        evidence=evidence_items,
        updates={
            "frozen_at": utc_now(),
            "freeze_reason_class": reason_class,
            "freeze_evidence": evidence_items,
            "reopen_conditions": conditions,
        },
    )
    topic = ledger.topic(topic_id) or {}
    cancelled: tuple[str, ...] = ()
    campaign_id = topic.get("campaign_id")
    if campaign_id and db.campaign(str(campaign_id)) is not None:
        cancelled = db.freeze_campaign(
            str(campaign_id),
            reason=f"topic_frozen:{reason_class}",
            topic_id=topic_id,
            evidence=evidence_items,
        )
    return TopicDecision(
        topic_id=topic_id,
        status=decision.status,
        changed=decision.changed,
        reason=reason_class,
        supersedes=decision.supersedes,
        cancelled_tasks=cancelled,
    )


# --------------------------------------------------------------------------- tick


def reconcile_frozen_campaigns(
    db: FactoryDB,
    ledger: Mapping[str, Any],
) -> tuple[list[str], list[str]]:
    """Freeze campaigns of frozen topics; return (frozen campaign ids, cancelled tasks)."""

    frozen: list[str] = []
    cancelled: list[str] = []
    for topic in topics_by_status(ledger, "frozen"):
        campaign_id = topic.get("campaign_id")
        if not campaign_id:
            continue
        campaign = db.campaign(str(campaign_id))
        if campaign is None or str(campaign.get("status")) == "frozen":
            continue
        cancelled.extend(
            db.freeze_campaign(
                str(campaign_id),
                reason=f"topic_frozen:{topic.get('freeze_reason_class')}",
                topic_id=str(topic["topic_id"]),
                evidence=topic.get("freeze_evidence"),
            )
        )
        frozen.append(str(campaign_id))
    return frozen, cancelled


def _consistency_warnings(db: FactoryDB, ledger: Mapping[str, Any]) -> list[str]:
    warnings: list[str] = []
    for topic in topics_by_status(ledger, "active", "in_review"):
        topic_id = str(topic["topic_id"])
        campaign_id = topic.get("campaign_id")
        if not campaign_id:
            warnings.append(f"topic {topic_id} is {topic['status']} without a campaign_id")
            continue
        campaign = db.campaign(str(campaign_id))
        if campaign is None:
            warnings.append(f"topic {topic_id} campaign {campaign_id} is missing")
        elif str(campaign.get("status")) == "frozen":
            warnings.append(
                f"topic {topic_id} is {topic['status']} but campaign {campaign_id} is frozen"
            )
    return warnings


def run_program_controller(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: ProgramSettings,
    report: Any,
) -> None:
    """Per-tick bookkeeping. Disabled: touches nothing and leaves ``report.program`` empty."""

    if not settings.enabled:
        return
    try:
        ledger = open_topic_ledger(paths, settings)
        document = ledger.read()
        frozen, cancelled = reconcile_frozen_campaigns(db, document)
        report.cancelled.extend(cancelled)
        status = slot_status(document, settings)
        report.program.update({
            "enabled": True,
            "ledger_path": str(ledger.path),
            "ledger_exists": ledger.path.exists(),
            **status.to_dict(),
            "campaigns_frozen": frozen,
            "warnings": _consistency_warnings(db, document),
        })
    except (OSError, TopicLedgerError, KeyError, ValueError) as exc:
        report.errors.append(f"program controller: {exc}")
        report.program.update({"enabled": True, "error": str(exc)})
