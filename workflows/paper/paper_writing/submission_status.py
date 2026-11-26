"""The registry follows the management site's submission status (2026-11-26).

Submissions, rejections and revision requests are registered on the management site (by the
submitter, by hand, or by ``journal_mail`` from the journal's letters). The paper registry kept
its pre-submission fields (``submission_preparation.portal_status: not_submitted``,
``submission_package.not_submitted: true``, no ``external_submission``) after the site already
listed the paper as submitted or rejected. :func:`reconcile` writes the site's latest attempt
back:

- ``external_submission`` (status, journal, manuscript number, attempt id, submission and
  decision dates) is set from the site's latest attempt that left ``preparing``; the block it
  replaces goes to ``external_submission.history``;
- ``submission_preparation.portal_status`` and ``submission_package.not_submitted`` are
  corrected when they still say "not submitted" for the attempt's journal / package version.

Nothing else in the record changes. The site is only read (GET). :func:`record_correspondence`
keeps a journal letter that ``journal_mail`` matched to a paper without a topic in the topic
ledger (papers older than the research program) in ``journal_correspondence``.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paper_writing.registry import load_paper_metadata, paper_metadata_path, write_paper_metadata

SCHEMA = "openlabs.submission_status_sync.v1"
# Site attempt status -> registry external status (the site's own vocabulary, except that the
# site's ``revision_preparing`` is the journal's revision request).
EXTERNAL_STATUS = {"revision_preparing": "revision_requested"}
CLOSED = frozenset({"accepted", "rejected", "withdrawn", "published", "closed"})
COMPARED = ("status", "journal", "manuscript_number", "submission_attempt_id")
DECISIONS = frozenset({"revision_requested", "submitted", "accepted", "rejected", "proofs"})


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _journal_key(name: Any) -> str:
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", text.casefold()).removeprefix("the")


def _attempt_no(attempt: Mapping[str, Any]) -> int:
    try:
        return int(attempt.get("attempt_no") or 0)
    except (TypeError, ValueError):
        return 0


def latest_attempt(site: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The site's latest attempt that left ``preparing`` (by attempt number, not by clock)."""
    attempts = [a for a in site.get("submission_attempts") or []
                if isinstance(a, Mapping) and str(a.get("status") or "preparing") != "preparing"]
    return max(attempts, key=_attempt_no) if attempts else None


def _closing_decision(site: Mapping[str, Any], attempt: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The decision event an attempt the site later set to ``closed`` carried (site order)."""
    return next((event for event in site.get("submission_events") or []
                 if event.get("attempt_id") == attempt.get("id")
                 and event.get("to_status") in CLOSED - {"closed"}), None)


def site_block(site: Mapping[str, Any], attempt: Mapping[str, Any]) -> dict[str, Any]:
    status = str(attempt.get("status"))
    decided_at = attempt.get("closed_at") if status in CLOSED else None
    site_status = None
    if status == "closed":
        # Archived after a decision (status_corrected rejected -> closed): keep the decision.
        decision = _closing_decision(site, attempt)
        if decision is not None:
            site_status, status = status, str(decision["to_status"])
            decided_at = decision.get("occurred_at") or decided_at
    block = {
        "status": EXTERNAL_STATUS.get(status, status),
        "site_status": site_status,
        "journal": attempt.get("journal_name"),
        "manuscript_number": attempt.get("manuscript_number") or None,
        "submission_attempt_id": attempt.get("id"),
        "submitted_at": attempt.get("submitted_at"),
        "decision_at": decided_at,
        "source": f"management:papers/{site.get('paper_id')}/submission-attempts/{attempt.get('id')}",
    }
    package = next((p for p in site.get("packages") or []
                    if p.get("id") == attempt.get("package_id")), {})
    if package.get("version"):
        block["package_version"] = str(package["version"])
    return {key: value for key, value in block.items() if value is not None}


def _same(current: Mapping[str, Any], wanted: Mapping[str, Any]) -> bool:
    for key in COMPARED:
        if key == "manuscript_number" and not wanted.get(key):
            continue  # the site has none yet: keep the registry's
        if key == "journal":
            if _journal_key(current.get(key)) != _journal_key(wanted.get(key)):
                return False
        elif str(current.get(key) or "").casefold() != str(wanted.get(key) or "").casefold():
            return False
    return True


def plan(metadata: Mapping[str, Any], site: Mapping[str, Any]) -> dict[str, Any]:
    """The registry fields that disagree with the site (empty when the record is current)."""
    attempt = latest_attempt(site)
    if attempt is None:
        return {}
    wanted = site_block(site, attempt)
    changes: dict[str, Any] = {}
    current = metadata.get("external_submission")
    current = dict(current) if isinstance(current, Mapping) else {}
    if not _same(current, wanted):
        block = {**{k: v for k, v in current.items() if k not in {"history"}}, **wanted}
        for key in ("decision_at", "site_status"):
            if key not in wanted:
                block.pop(key, None)
        if current.get("status"):
            previous = {k: v for k, v in current.items() if k != "history"}
            block["history"] = [*list(current.get("history") or []), previous]
        changes["external_submission"] = block
    else:
        # Same attempt and status: only fill what the registry lacks.
        missing = {k: v for k, v in wanted.items() if k != "source" and not current.get(k)}
        if missing:
            changes["external_submission"] = {**current, **missing}
    journal = _journal_key(wanted.get("journal"))
    preparation = metadata.get("submission_preparation")
    if (isinstance(preparation, Mapping) and preparation.get("portal_status") == "not_submitted"
            and _journal_key(preparation.get("journal")) in {journal, ""}):
        changes["submission_preparation.portal_status"] = wanted["status"]
    package = metadata.get("submission_package")
    if isinstance(package, Mapping) and package.get("not_submitted") is True:
        version = str(package.get("version") or "")
        if (version and version == wanted.get("package_version")) or (
                not version and wanted["status"] not in CLOSED):
            changes["submission_package.not_submitted"] = False
    return changes


def apply_plan(metadata: dict[str, Any], site: Mapping[str, Any],
               changes: Mapping[str, Any]) -> dict[str, Any]:
    attempt = latest_attempt(site) or {}
    stamp = _now()
    if "external_submission" in changes:
        metadata["external_submission"] = {**changes["external_submission"], "checked_at": stamp}
    if "submission_preparation.portal_status" in changes:
        preparation = dict(metadata["submission_preparation"])
        history = list(preparation.get("portal_status_history") or [])
        history.append({"status": changes["submission_preparation.portal_status"],
                        "at": attempt.get("closed_at") or attempt.get("submitted_at") or stamp,
                        "source": f"management website attempt {attempt.get('id')}"})
        preparation.update(portal_status=changes["submission_preparation.portal_status"],
                           portal_status_history=history)
        metadata["submission_preparation"] = preparation
    if "submission_package.not_submitted" in changes:
        package = dict(metadata["submission_package"])
        package.update(not_submitted=False, submitted_to=attempt.get("journal_name"),
                       submitted_at=str(attempt.get("submitted_at") or "")[:10] or None)
        metadata["submission_package"] = {k: v for k, v in package.items() if v is not None}
    return metadata


def reconcile(root: str | Path, site_papers: Iterable[Mapping[str, Any]], *,
              paper_ids: Iterable[str] = (), apply: bool = False) -> dict[str, Any]:
    """Compare (and with ``apply`` write) each registry record with its site paper."""
    wanted_ids = set(paper_ids)
    changed, current, missing = [], 0, []
    for site in site_papers:
        if not isinstance(site, Mapping) or not site.get("paper_id"):
            continue
        paper_id = str(site["paper_id"])
        if wanted_ids and paper_id not in wanted_ids:
            continue
        if not paper_metadata_path(paper_id, root).is_file():
            if latest_attempt(site) is not None:
                missing.append(paper_id)
            continue
        metadata = load_paper_metadata(paper_id, root)
        changes = plan(metadata, site)
        if not changes:
            current += 1
            continue
        before = metadata.get("external_submission") or {}
        entry = {"paper_id": paper_id, "fields": sorted(changes),
                 "from": before.get("status") if isinstance(before, Mapping) else None,
                 "to": (changes.get("external_submission") or {}).get("status")
                 or (latest_attempt(site) or {}).get("status"),
                 "path": paper_metadata_path(paper_id, root).resolve().relative_to(Path(root).resolve()).as_posix()}
        if apply:
            write_paper_metadata(paper_id, apply_plan(dict(metadata), site, changes), root)
        changed.append(entry)
    return {"schema_version": SCHEMA, "applied": apply, "changed": changed,
            "current": current, "site_only": missing}


def record_correspondence(root: str | Path, paper_id: str, *, message_key: str, status: str,
                          manuscript_id: str = "", due: str | None = None,
                          round_no: int | None = None) -> dict[str, Any]:
    """Keep one matched journal letter in the paper's registry record (idempotent by key)."""
    if not re.fullmatch("[a-f0-9]{64}", message_key):
        raise ValueError("invalid message digest")
    if status not in DECISIONS:
        raise ValueError(f"unknown journal decision {status}")
    path = paper_metadata_path(paper_id, root)
    if not path.is_file():
        raise ValueError(f"{paper_id}: no registry record")
    metadata = load_paper_metadata(paper_id, root)
    items = list(metadata.get("journal_correspondence") or [])
    key = "mail:" + message_key
    relative = path.resolve().relative_to(Path(root).resolve()).as_posix()
    if any(isinstance(item, Mapping) and item.get("event_key") == key for item in items):
        return {"status": "already_recorded", "paper_id": paper_id, "path": relative}
    entry = {"event_key": key, "recorded_at": _now(), "decision": status,
             "manuscript_id": manuscript_id or None, "due": due, "round": round_no,
             "recorded_by": "journal-mail",
             "original": "private journal-mail store (events.sqlite originals)"}
    items.append({k: v for k, v in entry.items() if v is not None})
    metadata["journal_correspondence"] = items
    write_paper_metadata(paper_id, metadata, root)
    return {"status": "recorded", "paper_id": paper_id, "path": relative}
