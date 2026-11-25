"""One hold record for every way production is held on purpose (2026-11-25, B3).

Before this module a hold had at least eight forms (architecture report 2026-11-24, problem
2): ``program pause-topic``'s ``operator_pause``, the hand-written ``operator_hold`` of
2026-11-19, a bare ``paused`` research state, a ``production_paused`` campaign (whose reason
lived only in an event and in its cancelled tasks), a paper's ``manual_assignment.hold``,
and switches such as ``polish_mode``. Every reader now goes through this module:

* :func:`topic_hold` -- a campaign's ``research_state.json`` (topic_pause, program_reconcile,
  the slot count of :func:`openlabs.program.paused_topic_campaigns`);
* :func:`assignment_hold` -- a paper's ``manual_assignment`` (paper_writing.site_assignments);
* :func:`production_pause_kind` -- the reason enum of a ``production_paused`` campaign
  (``FactoryDB.pause_production_campaign`` records it with the pause event).

Each returns the same record (:data:`HOLD_FIELDS`): ``kind``, ``scope``, ``by``, ``date``,
``quote`` (the user's words, when there are any), ``reason``, ``until`` or ``condition`` (when
the hold ends), ``restore`` (how to lift it), plus ``source`` (the form it was read from) and
``detail`` (the original record, unchanged). Older forms are read as they are: nothing is
rewritten, and :func:`hold_record` builds a new record in the unified form.

Pure functions, standard library only: ``paper_writing`` imports this file too.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

SCHEMA = "openlabs.hold.v1"
HOLD_FIELDS = ("kind", "scope", "by", "date", "quote", "reason", "until", "condition", "restore")
HOLD_KINDS = frozenset({"topic_pause", "submitter_hold", "campaign_pause", "switch"})

# Why a campaign is ``production_paused`` (the enum the pause event records as ``reason_kind``).
# Only ``operator_pause`` and ``owner_hold`` hold a topic on purpose (no research slot); the
# others are the control plane's own stops.
PRODUCTION_PAUSE_REASONS: dict[str, str] = {
    "operator_pause": "a person paused the topic (program pause-topic)",
    "owner_hold": "the research state was set to paused by hand or by the owner agent",
    "workstream_state": "the agent's research state is not active (blocked, waiting, done ...)",
    "ready_queue": "the paper is ready or delivered; research has nothing left to do",
    "release_retry": "a release retry took over the paper",
    "rounds_exhausted": "the review rounds at the target journal are used up",
    "binding_invalid": "the campaign's dynamic binding is invalid",
    "lane_inactive": "the production lane is not in the active desired state",
    "protocol_hook": "a protocol hook stopped continuation",
    "control": "an operator control receipt",
    "other": "unclassified (older pause without a known reason)",
}
_PREFIXES = (
    ("operator_pause", "operator_pause"),
    ("agent_workstream_paused", "owner_hold"),
    ("agent_workstream_", "workstream_state"),
    ("topic_ready_queue", "ready_queue"),
    ("release_retry_ready", "release_retry"),
    ("review_rounds_exhausted", "rounds_exhausted"),
    ("dynamic_binding_invalid", "binding_invalid"),
    ("lane_not_in_active_production", "lane_inactive"),
    ("protocol_hook", "protocol_hook"),
    ("control", "control"),
)


class HoldError(ValueError):
    """A hold record is incomplete."""


def production_pause_kind(reason: Any) -> str:
    """The :data:`PRODUCTION_PAUSE_REASONS` key of a ``pause_production_campaign`` reason."""

    text = str(reason or "").strip()
    for prefix, kind in _PREFIXES:
        if text.startswith(prefix):
            return kind
    return "other"


def _date(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _expired(until: Any, now: datetime | None = None) -> bool:
    text = str(until or "").strip()
    if not text:
        return False
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return (now or datetime.now(UTC)) >= moment


def _finish(record: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    record = {"schema_version": SCHEMA, **{key: record.get(key) for key in HOLD_FIELDS},
              **{key: value for key, value in record.items() if key not in HOLD_FIELDS}}
    record["expired"] = _expired(record.get("until"), now)
    return record


def hold_record(kind: str, scope: str, *, by: str, reason: str, restore: str,
                date: str | None = None, quote: str | None = None, until: str | None = None,
                condition: str | None = None) -> dict[str, Any]:
    """A new hold in the unified form; ``until`` or ``condition`` says when it ends."""

    if kind not in HOLD_KINDS:
        raise HoldError(f"unknown hold kind {kind!r}")
    for name, value in (("scope", scope), ("by", by), ("reason", reason), ("restore", restore)):
        if not str(value or "").strip():
            raise HoldError(f"a hold needs {name}")
    if not (str(until or "").strip() or str(condition or "").strip()):
        raise HoldError("a hold needs until or condition (when it ends)")
    if until is not None and _date(until) and not _parse_ok(until):
        raise HoldError(f"until is not an ISO date: {until}")
    return {"kind": kind, "scope": scope, "by": by,
            "date": date or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "quote": quote or None, "reason": reason, "until": until or None,
            "condition": condition or None, "restore": restore}


def _parse_ok(value: Any) -> bool:
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


TOPIC_RESTORE = ("program pause-topic --topic-id {scope} --resume --reason ... --by ... "
                 "(preview with --dry-run)")
TOPIC_RECORD_FIRST = ("record it first: program pause-topic --topic-id {scope} --reason ... "
                      "--by ... (an older form without an operator_pause record); then --resume")


def topic_hold(state: Mapping[str, Any] | None, *, scope: str = "",
               since: str | None = None, now: datetime | None = None) -> dict[str, Any] | None:
    """The hold on a topic's research, read from its ``research_state.json``, or None.

    ``status`` ``paused`` is a hold whatever the form: ``operator_pause`` (pause-topic, also
    the records made from older holds), ``operator_hold`` (hand-written, 2026-11-19), or no
    record at all (``since`` is then the best known start, e.g. the file's mtime).
    """

    if not isinstance(state, Mapping) or state.get("status") != "paused":
        return None
    pause = state.get("operator_pause")
    if isinstance(pause, Mapping):
        hold = pause.get("operator_hold") if isinstance(pause.get("operator_hold"), Mapping) else {}
        return _finish({
            "kind": "topic_pause", "scope": scope, "by": pause.get("by"),
            "date": _date(pause.get("date") or pause.get("at")),
            "quote": pause.get("quote") or hold.get("quote"),
            "reason": pause.get("reason"),
            "until": pause.get("until"),
            "condition": pause.get("condition") or hold.get("resume"),
            "restore": pause.get("restore") or TOPIC_RESTORE.format(scope=scope or "ID"),
            "source": "operator_pause", "resumable": True,
            "prior_status": str(pause.get("prior_status") or "active"),
            "detail": dict(pause)}, now)
    hold = state.get("operator_hold")
    if isinstance(hold, Mapping):
        return _finish({
            "kind": "topic_pause", "scope": scope, "by": hold.get("set_by") or hold.get("by"),
            "date": _date(hold.get("set_at") or hold.get("at")), "quote": hold.get("quote"),
            "reason": hold.get("reason"), "until": hold.get("until"),
            "condition": hold.get("resume") or hold.get("condition"),
            "restore": TOPIC_RECORD_FIRST.format(scope=scope or "ID"),
            "source": "operator_hold", "resumable": False,
            "prior_status": str(state.get("previous_status") or "active"),
            "detail": dict(hold)}, now)
    return _finish({
        "kind": "topic_pause", "scope": scope, "by": None, "date": _date(since),
        "quote": None, "reason": None, "until": None, "condition": None,
        "restore": TOPIC_RECORD_FIRST.format(scope=scope or "ID"),
        "source": "unrecorded", "resumable": False,
        "prior_status": str(state.get("previous_status") or "active"), "detail": None}, now)


ASSIGNMENT_NOTE = "manual_assignment=hold"
ASSIGNMENT_RESTORE = ("a person assigns the submitter on the site, then removes "
                      "manual_assignment from the paper record (or sets hold to false)")


def assignment_hold(registry: Mapping[str, Any] | None,
                    site_assignments: list[Mapping[str, Any]] | None = None, *,
                    scope: str = "", now: datetime | None = None) -> dict[str, Any] | None:
    """The manual-assignment hold on a paper's site submitter, or None.

    The registry field ``manual_assignment: {hold: true, ...}``; should the shared data
    checkout lag, an active site assignment whose notes carry ``manual_assignment=hold``.
    """

    record = (registry or {}).get("manual_assignment")
    if isinstance(record, Mapping) and record.get("hold") is True:
        return _finish({
            "kind": "submitter_hold", "scope": scope or str((registry or {}).get("paper_id") or ""),
            "by": record.get("by"), "date": _date(record.get("date")),
            "quote": record.get("quote"), "reason": record.get("reason"),
            "until": record.get("until"),
            "condition": record.get("condition") or "a person picks the submitter on the site",
            "restore": record.get("restore") or ASSIGNMENT_RESTORE,
            "source": "registry", "site_receipt": record.get("site_receipt"),
            "detail": None}, now)
    for row in site_assignments or []:
        if row.get("active") and ASSIGNMENT_NOTE in str(row.get("notes") or ""):
            return _finish({
                "kind": "submitter_hold", "scope": scope, "by": None,
                "date": _date(row.get("assigned_at")), "quote": None,
                "reason": "site assignment notes carry manual_assignment=hold",
                "until": None, "condition": "a person picks the submitter on the site",
                "restore": ASSIGNMENT_RESTORE, "source": "site_assignment_notes",
                "assignment_id": row.get("id"), "detail": None}, now)
    return None


def campaign_pause(status: Any, reason: Any, *, scope: str = "", at: Any = None,
                   now: datetime | None = None) -> dict[str, Any] | None:
    """A ``production_paused`` campaign as a hold record (reason from its pause event)."""

    if str(status or "") != "production_paused":
        return None
    kind = production_pause_kind(reason)
    return _finish({
        "kind": "campaign_pause", "scope": scope, "by": "orchestrator", "date": _date(at),
        "quote": None, "reason": str(reason or "") or None, "until": None,
        "condition": PRODUCTION_PAUSE_REASONS[kind],
        "restore": "lifts by itself when its cause ends (project synchronization)",
        "source": "campaign", "reason_kind": kind, "detail": None}, now)
