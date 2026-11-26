"""The paper registry follows the management site's submission status (2026-11-26).

A submission, rejection or revision request lands on the management site (registered by the
submitter, by hand, or by ``journal_mail`` from the journal's letter), but the registry kept
``not_submitted``. Every :data:`REFRESH_SECONDS` the tick runs ``paper-writing program
sync-submission-status --apply`` (site read-only, registry written; see
``paper_writing/submission_status.py``) and commits the changed registry records in one local
commit of exactly those files. ``[program] submission_status_sync = false`` turns it off.

:func:`record_registry_correspondence` is ``program journal-event`` for a paper that has no
topic in the topic ledger (papers older than the research program): the letter is kept in the
paper's registry record and committed, instead of the event staying pending for ever.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from typing import Any

from .config import FactorySettings, WorkspacePaths
from .contracts import atomic_write_json
from .db import FactoryDB, utc_now

REFRESH_SECONDS = 1_800
COMMIT_TRAILER = "\n\nLocal commit by the OpenLabs tick (registry follows the management site; not pushed)."


class SubmissionStatusError(ValueError):
    """The step could not run (credentials, command failure)."""


def commit_registry_files(paths: WorkspacePaths, settings: FactorySettings,
                          files: Iterable[str], subject: str, body: str = "") -> str | None:
    """One local commit of exactly ``files`` (registry records); None when they are clean."""

    from .program_autonomy import ReleaseError, _git, git_identity

    root = paths.data
    scope = []
    for raw in files:
        relative = str(raw).strip().strip("/")
        letter = (relative.startswith("papers/") and "/journal-letters/" in relative
                  and relative.endswith(".txt"))  # a rejection's kept letter (C8)
        if ".." in relative or not letter and (not relative.startswith("registry/papers/")
                                               or not relative.endswith(".yaml")):
            raise ReleaseError(f"refusing to commit a path outside registry/papers: {raw}")
        if relative not in scope:
            scope.append(relative)
    if not scope or not _git(root, "status", "--porcelain=v1", "--", *scope).strip():
        return None
    identity = git_identity(paths, settings)
    _git(root, "add", "--", *scope)
    _git(root, "commit", "-q", "--only", "-m", subject + ("\n\n" + body if body else "")
         + COMMIT_TRAILER, "--", *scope, identity=identity)
    return _git(root, "rev-parse", "HEAD").strip()


def run_sync(paths: WorkspacePaths, settings: FactorySettings, *,
             paper_ids: Iterable[str] = (), apply: bool = True) -> dict[str, Any]:
    from .program_autonomy import (DELIVERY_ENVIRONMENT, DeliveryError, _run_paper_command,
                                   pipeline_credentials)

    credentials, refused = pipeline_credentials(settings, DELIVERY_ENVIRONMENT)
    missing = [name for name in DELIVERY_ENVIRONMENT if name not in credentials]
    if missing:
        raise SubmissionStatusError(f"credentials missing: {missing}"
                                    + (f" ({refused})" if refused else ""))
    arguments = ["program", "sync-submission-status"]
    for paper_id in paper_ids:
        arguments += ["--paper-id", str(paper_id)]
    if apply:
        arguments.append("--apply")
    try:
        result = _run_paper_command(paths, settings, arguments, environment=credentials,
                                    timeout=600)
    except DeliveryError as exc:
        raise SubmissionStatusError(str(exc)) from exc
    changed = list(result.get("changed") or [])
    # Records written by a run whose commit failed (a held index.lock): the registry is
    # already current for them, so only this list brings them into a commit.
    pending_file = paths.database / "submission-status-pending.json"
    try:
        pending = [str(item) for item in json.loads(pending_file.read_text(encoding="utf-8"))]
    except (OSError, ValueError, TypeError):
        pending = []
    files = [str(item.get("path")) for item in changed] + pending
    if apply and files:
        lines = [f"{item.get('paper_id')}: {item.get('from') or '-'} -> {item.get('to')} "
                 f"({', '.join(item.get('fields') or [])})" for item in changed]
        lines += [f"{item}: written by an earlier run" for item in pending]
        try:
            result["commit"] = commit_registry_files(
                paths, settings, files,
                f"registry: submission status from the management site ({len(files)} papers)",
                "\n".join(lines))
        except Exception:
            atomic_write_json(pending_file, sorted(set(files)))
            raise
        if pending:
            atomic_write_json(pending_file, [])
    return result


def sync_tick(db: FactoryDB, paths: WorkspacePaths, settings: FactorySettings,
              report: Any) -> None:
    """Per tick, at most every :data:`REFRESH_SECONDS`; never a tick error by itself."""

    info = report.program.setdefault("submission_status", {})
    if not getattr(settings.program, "submission_status_sync", True):
        info["outcome"] = "skipped_submission_status_sync_off"
        return
    cache = paths.database / "submission-status.json"
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
        age = time.time() - float(cached.get("checked_epoch") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        cached, age = None, None
    if cached is not None and age is not None and 0 <= age < REFRESH_SECONDS:
        info.update({key: cached.get(key) for key in ("outcome", "changed", "commit", "checked_at")},
                    cached=True)
        return
    try:
        result = run_sync(paths, settings)
    except (SubmissionStatusError, OSError) as exc:
        info.update(outcome="failed", error=str(exc)[:400], checked_at=utc_now())
    except Exception as exc:  # a git failure (ReleaseError) waits for the next refresh
        info.update(outcome="failed", error=f"{type(exc).__name__}: {str(exc)[:300]}",
                    checked_at=utc_now())
    else:
        changed = [{key: item.get(key) for key in ("paper_id", "from", "to", "fields")}
                   for item in result.get("changed") or []]
        info.update(outcome="ok", changed=changed, commit=result.get("commit"),
                    current=result.get("current"), checked_at=utc_now())
        for item in changed:
            db.record_event_once(
                "paper", str(item["paper_id"]), "registry_submission_status",
                {"from": item.get("from"), "to": item.get("to"), "fields": item.get("fields"),
                 "commit": result.get("commit")},
                event_key=f"submission_status:{item['paper_id']}:{item.get('to')}:{result.get('commit')}")
        try:  # only a completed run waits for the refresh; a failure retries next tick
            atomic_write_json(cache, {**info, "checked_epoch": time.time()})
        except OSError:
            pass


def record_registry_correspondence(db: FactoryDB, paths: WorkspacePaths,
                                   settings: FactorySettings, *, paper_id: str,
                                   message_key: str, status: str, manuscript_id: str = "",
                                   due: str | None = None,
                                   round_no: int | None = None,
                                   letter_file: str | None = None) -> dict[str, Any]:
    """``program journal-event`` for a paper without a topic: its registry record keeps it
    (a rejection with its verbatim letter, which the paper's next review reads)."""

    from .program_autonomy import DeliveryError, _run_paper_command

    arguments = ["program", "journal-correspondence", "--paper-id", paper_id,
                 "--message-key", message_key, "--status", status]
    if manuscript_id:
        arguments += ["--manuscript-id", manuscript_id]
    if due:
        arguments += ["--due", due]
    if round_no:
        arguments += ["--round", str(round_no)]
    if letter_file:
        arguments += ["--letter-file", letter_file]
    try:
        result = _run_paper_command(paths, settings, arguments, timeout=120)
    except DeliveryError as exc:
        raise SubmissionStatusError(str(exc)) from exc
    commit = commit_registry_files(
        paths, settings, [str(result.get("path")), *([result["letter_path"]]
                                                     if result.get("letter_path") else [])],
        f"registry: journal letter for {paper_id} ({status})",
        f"Matched by journal_mail; message key {message_key[:12]}. The paper has no topic in "
        "the topic ledger, so the registry record keeps the letter.")
    db.record_event_once("paper", paper_id, "journal_correspondence",
                         {"decision": status, "manuscript_id": manuscript_id, "due": due,
                          "round": round_no, "registry": result.get("status"), "commit": commit},
                         event_key="mail:" + message_key)
    return {"status": result.get("status"), "paper_id": paper_id, "commit": commit,
            "recorded_in": "registry"}
