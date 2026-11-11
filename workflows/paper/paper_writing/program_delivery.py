"""Research-program delivery: provisional escalation, automatic handoff and handler assignment.

The orchestrator (stdlib only) calls these through ``paper-writing program ...``:

* ``register-escalation`` -- a writer registering the paper of a topic the admission
  gate judged ``escalation`` records ``target_escalation`` as ``provisional``
  (approved by the admission task, strength evidence = admission record path and
  hash, fallback = the card's routine venue). It may be reviewed on the escalation
  track but not delivered at that target until the unified review's score meets
  ``venue_eligibility.escalation.minimum_internal_score``.
* ``deliver`` -- the ordinary immutable handoff to the paper-management site. It
  never sends or records a submission handler; after a successful release the
  registry records ``delivery.awaiting_owner_review: true`` and a qualifying
  provisional escalation becomes ``approved``.
* ``assign-handler`` -- after the owner's review, record the default second author
  (``registry/settings.yaml#defaults.authors[1]``) as the paper's submission
  handler. It does not submit anything and does not authorize a journal submission.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from paper_writing import venue_policy
from paper_writing.registry import (
    load_paper_metadata,
    load_registry_settings,
    settings_path,
    write_paper_metadata,
)

HANDLER_ROLE = "submission_handler"
DEFAULT_HANDLER = "second_author"


class ProgramDeliveryError(RuntimeError):
    """A program delivery step cannot proceed."""


def _today() -> str:
    return date.today().isoformat()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _policy(root: Path) -> Mapping[str, Any]:
    settings = load_registry_settings(root) if settings_path(root).is_file() else {}
    policy = settings.get("journal_target_policy")
    return policy if isinstance(policy, Mapping) else {}


def register_provisional_escalation(
    paper_id: str,
    *,
    root: str | Path,
    venue: str,
    admission_task_id: str,
    admission_record: str | Path,
    fallback_venue: str,
) -> dict[str, Any]:
    """Record ``target_escalation: provisional`` from an admission-gate escalation verdict."""

    repo_root = Path(root).resolve()
    record_path = Path(admission_record)
    if not record_path.is_absolute():
        record_path = repo_root / record_path
    if not record_path.is_file():
        raise ProgramDeliveryError(f"admission record is missing: {record_path}")
    for name, value in (("venue", venue), ("admission_task_id", admission_task_id),
                        ("fallback_venue", fallback_venue)):
        if not str(value or "").strip():
            raise ProgramDeliveryError(f"{name} is required")
    digest = hashlib.sha256(record_path.read_bytes()).hexdigest()
    metadata = load_paper_metadata(paper_id, repo_root)
    existing = metadata.get("target_escalation")
    if isinstance(existing, Mapping) and existing.get("status") == "approved":
        raise ProgramDeliveryError(f"{paper_id} already has an approved target_escalation")
    record = {
        "status": "provisional",
        "venue": venue.strip(),
        "approved_by": f"admission:{admission_task_id.strip()}",
        "approved_at": _today(),
        "strength_evidence": f"{record_path} (sha256 {digest})",
        "strength_evidence_sha256": digest,
        "fallback_venue": fallback_venue.strip(),
    }
    metadata["target_escalation"] = record
    write_paper_metadata(paper_id, metadata, repo_root)
    return {"paper_id": paper_id, "target_escalation": record}


def confirm_escalation(paper_id: str, *, root: str | Path) -> dict[str, Any]:
    """Turn a qualifying provisional escalation into ``approved`` (score from the review)."""

    repo_root = Path(root).resolve()
    metadata = load_paper_metadata(paper_id, repo_root)
    record = metadata.get("target_escalation")
    if not isinstance(record, Mapping) or record.get("status") != "provisional":
        return {"paper_id": paper_id, "changed": False,
                "status": record.get("status") if isinstance(record, Mapping) else None}
    problems = venue_policy.provisional_escalation_blockers(
        metadata, _policy(repo_root), paper_id=paper_id
    )
    if problems:
        raise ProgramDeliveryError(problems[0])
    release = metadata.get("writing_release") or {}
    approved = dict(record)
    approved.update({
        "status": "approved",
        "approved_at": _today(),
        "internal_review_score": release.get("score"),
        "internal_review_source": str(release.get("decision_record") or ""),
        "provisional_approved_by": record.get("approved_by"),
    })
    metadata["target_escalation"] = approved
    write_paper_metadata(paper_id, metadata, repo_root)
    return {"paper_id": paper_id, "changed": True, "target_escalation": approved}


def deliver(
    paper_id: str,
    *,
    root: str | Path,
    client: Any,
    release: Callable[..., Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Immutable handoff without a submission handler; mark the paper for the owner's review."""

    from paper_writing.handoff import release_handoff

    repo_root = Path(root).resolve()
    result = dict((release or release_handoff)(paper_id, root=repo_root, client=client))
    escalation = confirm_escalation(paper_id, root=repo_root)
    metadata = load_paper_metadata(paper_id, repo_root)
    metadata["delivery"] = {
        "awaiting_owner_review": True,
        "delivered_at": _now(),
        "package_id": result.get("package_id"),
        "version": result.get("version"),
        "receipt": result.get("receipt"),
        "submission_handler": None,
        "delivered_by": "research_program_auto_handoff",
    }
    write_paper_metadata(paper_id, metadata, repo_root)
    return {
        "schema_version": "openlabs.program_delivery.v1",
        "status": "delivered",
        "paper_id": paper_id,
        "package_id": result.get("package_id"),
        "version": result.get("version"),
        "receipt": result.get("receipt"),
        "awaiting_owner_review": True,
        "submission_handler": None,
        "escalation_confirmed": bool(escalation.get("changed")),
    }


def default_handler(root: str | Path, handler: str = DEFAULT_HANDLER,
                    paper: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Resolve ``second_author`` (registry default roster) or a named author."""

    settings = load_registry_settings(Path(root).resolve())
    defaults = settings.get("defaults") if isinstance(settings.get("defaults"), Mapping) else {}
    roster = defaults.get("authors") if isinstance(defaults, Mapping) else None
    if not isinstance(roster, list) or not all(isinstance(item, Mapping) for item in roster):
        raise ProgramDeliveryError("registry/settings.yaml#defaults.authors is missing")
    if handler == DEFAULT_HANDLER:
        if len(roster) < 2:
            raise ProgramDeliveryError("the default author roster has no second author")
        person = roster[1]
    else:
        people = list(roster)
        authors = (paper or {}).get("authors")
        if isinstance(authors, Mapping) and isinstance(authors.get("people"), list):
            people = [*authors["people"], *people]
        matches = [item for item in people if isinstance(item, Mapping)
                   and handler.strip().casefold() in {
                       str(item.get("name") or "").casefold(),
                       str(item.get("name_zh") or "").casefold()}]
        if not matches:
            raise ProgramDeliveryError(f"no author named {handler!r} in the roster or byline")
        person = matches[0]
    if not str(person.get("name") or "").strip() or not str(person.get("email") or "").strip():
        raise ProgramDeliveryError("the selected handler needs a name and an email")
    return {"name": str(person["name"]), "email": str(person["email"])}


def assign_handler(paper_id: str, *, root: str | Path,
                   handler: str = DEFAULT_HANDLER) -> dict[str, Any]:
    """Record the submission handler after the owner's review (no submission, no payment)."""

    repo_root = Path(root).resolve()
    metadata = load_paper_metadata(paper_id, repo_root)
    person = default_handler(repo_root, handler, metadata)
    previous = metadata.get("submission_contact")
    metadata["submission_contact"] = {
        **person,
        "role": HANDLER_ROLE,
        "journal_submission_authorized": False,
        "assigned_at": _now(),
        "assigned_after": "owner_review",
        "rule": handler,
    }
    delivery = dict(metadata.get("delivery") or {})
    delivery.update({"awaiting_owner_review": False, "owner_reviewed_at": _now(),
                     "submission_handler": person["name"]})
    metadata["delivery"] = delivery
    write_paper_metadata(paper_id, metadata, repo_root)
    return {
        "schema_version": "openlabs.program_handler_assignment.v1",
        "status": "assigned",
        "paper_id": paper_id,
        "submission_handler": person["name"],
        "rule": handler,
        "previous": dict(previous) if isinstance(previous, Mapping) else None,
        "journal_submission_authorized": False,
    }
