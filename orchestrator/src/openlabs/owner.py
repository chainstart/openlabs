"""Owner mode: one owner agent carries an admitted topic to review or a freeze.

Owner decision 2026-11-14: after admission a single main agent session owns the
topic end to end and decides itself what to do next, including whether to start
sub-agents or ask another model; the control plane no longer splits the work
into maturation, replan, continuation, readiness, writing, remediation and
revision tasks. What stays is: the admission gate (unchanged, before this
module), the hash-bound pre-registered primary endpoint, the cross-family
pre-submission review (``paper_review``, whose comments return to the same
owner session), the cross-family direction decision as a circuit breaker, and
the human confirmation of a submission.

Mechanics, all keyed on ``[program].owner_mode``:

* a ``topic_owner`` task is one *seat* (one agent process, a few hours). It is
  pinned to a concrete runner chosen from ``[program.owner].runners`` (Fable,
  then Opus 5.5, then gpt-astra; configurable) and keeps that runner seat after seat (the session
  only within the limits below);
* the owner ends a seat with a small packet (``continuing``, ``awaiting_remote``
  with job ids, ``ready_for_review``, ``frozen`` or ``blocked_human``) that
  :func:`normalize_packet` turns into an ordinary result bundle, filling what the
  control plane knows (identity, hashes of staged files, the ledger's
  pre-registration hash);
* ``awaiting_remote`` parks the seat through the existing remote-wait machinery;
  every other outcome is followed by :func:`ensure_seat` (next seat), a
  ``paper_review`` or nothing (frozen, ready, needs a human);
* :func:`record_seat` computes a mechanical progress fingerprint; after
  ``no_progress_seats`` seats without progress a direction decision is scheduled;
* :func:`supervise` moves a seat whose runner cannot start it for
  ``switch_after_minutes`` to the next usable runner.

Owner through minor revision (2026-11-16):

* ``ready_for_review`` first goes to a *recompute review* (``paper_review`` routed
  ``owner_recompute_review``, skill ``openlabs-recompute-review``, fresh session,
  parented to the seat so the router excludes the owner's family): the reviewer
  recomputes the core results from the data along the line's ``review_checklist`` and
  returns ``recompute_review.verdict``. major -> the owner revises and the next round
  starts with a fresh reviewer that reads the earlier rounds and the author's answer;
  minor -> the owner fixes and self-checks, then the unified review; accept -> the
  unified review; reject or major in round ``review_max_rounds`` -> direction decision.
  The unified review (``_enqueue_review``) stays the formal gate before delivery and is
  told not to repeat the recomputation (:func:`_after_recompute` is the state machine);
* a successor seat resumes its session only while :func:`keep_session` allows it
  (``session_max_seats``, ``session_max_tokens_read``); otherwise it is a fresh session
  that starts from the owner's own ``OWNER_HANDOVER.md`` (:func:`handover_text`).

Writer hand-over (2026-11-19, ``[program.owner].writing_runner``): the owner solves; from
the first seat whose packet says the research is done (:func:`writing_switch_due`) one
writer runner writes the manuscript and every revision (:func:`start_writing`); reviews
avoid the writer's family (:func:`writer_provider`); writer seats have their own slot
limit and wait for the writer before falling back to the owner (:func:`supervise_writing`).

With ``owner_mode = "off"`` none of this runs and every path is unchanged.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import budget as budget_control
from . import spin_guard
from .config import OWNER_TASK_TYPE, FactorySettings, WorkspacePaths, dispatch_runner
from .contracts import (
    IDENTIFIER,
    PRIMARY_ENDPOINT_VERDICTS,
    REMOTE_JOB_ID,
    RESULT_SCHEMA,
    SHA256,
    atomic_write_json,
    sha256_file,
)
from .db import FactoryDB, utc_now
from .projects import load_project, workstream_policy
from .resources import default_task_resources, task_resources

PACKET_SCHEMA = "openlabs.owner_packet.v1"
OWNER_STATUSES = ("continuing", "awaiting_remote", "ready_for_review", "frozen", "blocked_human")
# A manuscript goes to review only with an evaluated endpoint (pending stays in research).
EVALUATED_VERDICTS = frozenset({"met", "failed", "inconclusive"})
WORK_LOG_NAME = "OWNER_LOG.md"
BRIEF_NAME = "OWNER_BRIEF.md"
# Written by the owner at the end of every seat: the next (fresh) session starts from it.
HANDOVER_NAME = "OWNER_HANDOVER.md"
# The owner's answer to the last review round, read by the next round's reviewer.
RESPONSE_NAME = "REVIEW_RESPONSE.md"
STATE_META_PREFIX = "owner_state:"
BLOCKED_META_PREFIX = "owner_blocked:"
TRIGGER_NO_PROGRESS = "owner_no_progress"
TRIGGER_REVIEW_REJECTED = "owner_review_rejected"
TRIGGER_REVIEW_ROUNDS = "owner_review_rounds_exhausted"
ROUTING_FIRST = "owner_first_seat"
ROUTING_CONTINUE = "owner_continue"
ROUTING_CONVERTED = "owner_converted"
ROUTING_REVIEW = "owner_review"
ROUTING_REVIEWED = "owner_review_returned"
ROUTING_RECOMPUTE = "owner_recompute_review"
ROUTING_RECOMPUTED = "owner_recompute_returned"
ROUTING_RETRY = "owner_retry"
# The first seat of the manuscript writer (``[program.owner].writing_runner``).
ROUTING_WRITING = "owner_writing_handover"
WRITING_ACTIVE = "active"
WRITING_FALLBACK = "fallback"
# The owner writes the manuscript itself (recorded once, see ``settle_owner_writing``).
WRITING_OWNER = "owner"
# A writing seat over the writer's slot limit is re-checked this often.
_WRITING_SLOT_RECHECK_MINUTES = 15
RECOMPUTE_PACKET_SCHEMA = "openlabs.recompute_review_packet.v1"
RECOMPUTE_SKILL = "openlabs-recompute-review"
RECOMPUTE_VERDICTS = ("accept", "minor", "major", "reject")
# Review stages kept in the owner state (``review_stage``).
STAGE_RECOMPUTE = "recompute_review"
STAGE_MAJOR = "major_revision"
STAGE_MINOR = "minor_revision"
STAGE_PASSED = "recompute_passed"
STAGE_UNIFIED = "unified_review"
# Phases an owner may declare in its packet (``phase``); reported per topic.
OWNER_PHASES = ("precheck", "solving", "writing")
# Directory names never part of the progress fingerprint: runtime and outputs.
_DIGEST_SKIP_DIRS = frozenset({".agents", ".codex", ".claude", "attempts", "__pycache__"})
_DIGEST_SKIP_FILES = frozenset({WORK_LOG_NAME, BRIEF_NAME, HANDOVER_NAME})
# Bookkeeping never counts as progress (2026-11-17: 75 seats each only refreshed the
# log, the handover and a quota receipt and were all scored ``workspace_changed``).
# research_state.json also carries control-plane fields (clocks, holds).
_BOOKKEEPING_FILES = frozenset({*_DIGEST_SKIP_FILES, "research_state.json"})
_BOOKKEEPING_WORDS = ("quota", "utilization", "utilisation", "pacing", "checkpoint",
                      "heartbeat", "provider_receipt", "provider_check")
_BOOKKEEPING_SUFFIXES = frozenset({".json", ".md", ".txt", ".log", ".yaml", ".yml"})
# Packet statuses that are themselves a step forward.
_ADVANCING_STATUSES = frozenset({"awaiting_remote", "ready_for_review", "frozen"})


def is_bookkeeping(name: str) -> bool:
    """Owner log/brief/handover, research_state.json, logs and quota/checkpoint receipts."""

    base = Path(str(name)).name
    lower = base.lower()
    suffix = Path(lower).suffix
    if base in _BOOKKEEPING_FILES or suffix == ".log":
        return True
    return suffix in _BOOKKEEPING_SUFFIXES and any(word in lower for word in _BOOKKEEPING_WORDS)
_MAX_REMEMBERED_ARTIFACTS = 2000
# Version of the workspace-digest definition (2: bookkeeping excluded).
DIGEST_VERSION = 2
_LINEAGE_LIMIT = 500
# Last seats kept in the owner state for a stall diagnosis.
_RECENT_SEATS = 6


# --------------------------------------------------------------------------- switch


def mode_enabled(settings: FactorySettings) -> bool:
    return settings.program.enabled and settings.program.owner_mode != "off"


def campaign_line(campaign: Mapping[str, Any]) -> str | None:
    path = str(campaign.get("project_config_path") or "").strip()
    if not path:
        return None
    try:
        return load_project(path).research_line
    except (OSError, ValueError, TypeError, KeyError):
        return None


def applies(settings: FactorySettings, campaign: Mapping[str, Any] | None) -> bool:
    """Whether a research-program topic campaign runs in owner mode."""

    if campaign is None or not mode_enabled(settings):
        return False
    if workstream_policy(campaign).get("program_research") is not True:
        return False
    mode = settings.program.owner_mode
    if mode == "all":
        return True
    return campaign_line(campaign) in tuple(mode)


def is_owner_task(task: Mapping[str, Any] | None) -> bool:
    return bool(task) and str(task.get("task_type") or "") == OWNER_TASK_TYPE


# --------------------------------------------------------------------------- packet


def _owner_status(payload: Mapping[str, Any]) -> str | None:
    for key in ("owner_status", "status"):
        value = str(payload.get(key) or "").strip().lower()
        if value in OWNER_STATUSES:
            return value
    packet = payload.get("owner_packet")
    if isinstance(packet, Mapping):
        value = str(packet.get("status") or "").strip().lower()
        if value in OWNER_STATUSES:
            return value
    return None


def _as_uri(value: Any, base: Path | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("file:"):
        return text
    path = Path(text).expanduser()
    if not path.is_absolute():
        if base is None:
            return None
        path = base / path
    return path.resolve().as_uri()


def _uri_path(uri: str) -> Path | None:
    from urllib.parse import unquote, urlparse

    parsed = urlparse(uri)
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        return None
    return Path(unquote(parsed.path)).resolve()


def _artifacts(
    declared: Any,
    *,
    workspace: Path | None,
    staging_root: Path | None,
) -> list[dict[str, Any]]:
    """Declared artifacts with ids, URIs and hashes completed; staged files added."""

    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_paths: set[Path] = set()
    for index, item in enumerate(declared if isinstance(declared, list) else []):
        if isinstance(item, str):
            item = {"uri": item}
        if not isinstance(item, Mapping):
            continue
        entry = dict(item)
        uri = _as_uri(entry.get("uri") or entry.get("path"), workspace)
        if uri is None:
            continue
        entry.pop("path", None)
        entry["uri"] = uri
        path = _uri_path(uri)
        digest = str(entry.get("sha256") or "").strip().lower()
        if not SHA256.fullmatch(digest):
            if path is None or not path.is_file():
                continue
            entry["sha256"] = sha256_file(path)
        artifact_id = str(entry.get("artifact_id") or "").strip()
        if not IDENTIFIER.fullmatch(artifact_id) or artifact_id in seen_ids:
            artifact_id = f"owner-{index:03d}-{str(entry['sha256'])[:12]}"
        entry["artifact_id"] = artifact_id
        entry.setdefault("kind", "data")
        seen_ids.add(artifact_id)
        if path is not None:
            seen_paths.add(path)
        result.append(entry)
    return _with_staged(result, staging_root, seen_ids=seen_ids, seen_paths=seen_paths)


def _with_staged(
    artifacts: list[dict[str, Any]],
    staging_root: Path | None,
    *,
    seen_ids: set[str] | None = None,
    seen_paths: set[Path] | None = None,
) -> list[dict[str, Any]]:
    """``artifacts`` plus each staged file the control plane registers one by one.

    The commit rejects staged files absent from ``result.artifacts``; owners staged
    logs and forgot to list them (2026-11-14), so the control plane lists them. Which
    files are listed singly is :func:`attempts.classify_unlisted_staging`'s rule; job
    bundles, caches, scripts and over-limit files are left for the ingest
    (:func:`attempts.settle_unlisted_staging`) to collapse into manifests.
    """

    from .attempts import classify_unlisted_staging, unlisted_artifact

    result = list(artifacts)
    ids = set(seen_ids or ()) | {str(item.get("artifact_id") or "") for item in result
                                 if isinstance(item, Mapping)}
    if staging_root is None or not staging_root.is_dir():
        return result
    declared = [item for item in result if isinstance(item, Mapping)]
    declared += [{"uri": path.as_uri()} for path in seen_paths or ()]
    plan = classify_unlisted_staging(staging_root, declared)
    # Two files with the same bytes (empty logs) are still two staged files and get
    # distinct ids; skipping the second left it undeclared and the commit refused it.
    for path, digest in plan["individual"]:
        result.append(unlisted_artifact(path, digest, ids))
    return result


def settle_staged_artifacts(
    payload: Mapping[str, Any],
    staging_root: Path | None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Freeze each declared file in attempt staging and bind it to its frozen hash.

    A staged file is new output of this attempt; its hash is the control plane's to
    compute, not the owner's. Each one is replaced by a read-only copy (a process
    still writing to the old inode no longer changes it) and the copy's hash is
    recorded. A declared hash that differs is corrected, never refused; the pair is
    returned so the caller can record it. Artifacts outside staging (existing,
    committed objects) are left alone and stay strictly hash-checked by the gate.
    """

    import os
    import tempfile

    result = dict(payload)
    artifacts = payload.get("artifacts")
    if staging_root is None or not staging_root.is_dir() or not isinstance(artifacts, list):
        return result, []
    staging = staging_root.resolve()
    frozen: dict[Path, str] = {}
    corrections: list[dict[str, str]] = []
    settled: list[Any] = []
    for item in artifacts:
        if not isinstance(item, Mapping) or not str(item.get("uri") or "").startswith("file:"):
            settled.append(item)
            continue
        path = _uri_path(str(item["uri"]))
        if (path is None or not path.is_relative_to(staging) or path.is_symlink()
                or not path.is_file()):
            settled.append(item)
            continue
        if path not in frozen:
            handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            try:
                with os.fdopen(handle, "wb") as target, path.open("rb") as source:
                    while chunk := source.read(1 << 20):
                        target.write(chunk)
                Path(temporary).chmod(0o444)
                os.replace(temporary, path)
            except BaseException:
                Path(temporary).unlink(missing_ok=True)
                raise
            frozen[path] = sha256_file(path)
        entry = dict(item)
        declared = str(entry.get("sha256") or "")
        if declared != frozen[path]:
            corrections.append({"artifact_id": str(entry.get("artifact_id") or ""),
                                "path": path.relative_to(staging).as_posix(),
                                "declared": declared, "actual": frozen[path]})
            entry["sha256"] = frozen[path]
        settled.append(entry)
    result["artifacts"] = settled
    return result, corrections


def relocate_bulk_files(
    workspace: Path | None,
    staging_root: Path | None,
    canonical: Path | None,
) -> list[tuple[str, Path, Path]]:
    """Move new log/bulk files out of the writable workspace into artifact staging.

    The campaign workspace may only gain small text files: the commit rejects files
    above the data-file limit and artifact-only formats (``.log``, ``.npz``, ``.out``,
    ...). Owners kept writing solver logs there (2026-11-14), and each rejection
    cost a seat. A new or changed such file is moved to ``staging/workspace/<path>``;
    when the canonical campaign already has the file, its canonical bytes are put
    back so the promotion does not delete it. Returns ``(relative, old, new)`` per file.

    Only files the data boundary checks are moved: ``results/`` (the runner's own
    agent-stdout.log, agent-stderr.log and worker.log, still open for writing when the
    Stop hook runs) and the runtime directories are not campaign state. Moving those
    open logs made their hash change after registration (2026-11-14, 26 seats refused).
    """

    from .attempts import (
        _ARTIFACT_ONLY_SUFFIXES,
        _ATTEMPT_RUNTIME_DIRS,
        DEFAULT_MAX_DATA_FILE_BYTES,
        _generated_cache,
    )

    if workspace is None or staging_root is None or not workspace.is_dir():
        return []
    root = workspace.resolve()
    staging = staging_root.resolve()
    if staging == root or staging.is_relative_to(root):
        return []
    skipped = _DIGEST_SKIP_DIRS | _ATTEMPT_RUNTIME_DIRS | {"results"}
    moved: list[tuple[str, Path, Path]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] in skipped or _generated_cache(relative):
            continue
        lowered = relative.as_posix().lower()
        bulky = path.stat().st_size > DEFAULT_MAX_DATA_FILE_BYTES
        if not bulky and not any(lowered.endswith(suffix) for suffix in _ARTIFACT_ONLY_SUFFIXES):
            continue
        original = (canonical / relative) if canonical is not None else None
        if original is not None and original.is_file() and sha256_file(original) == sha256_file(
                path):
            continue  # unchanged from the canonical campaign
        target = staging / "workspace" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target = target.with_name(f"{target.name}.{sha256_file(path)[:8]}")
        path.replace(target)
        if original is not None and original.is_file():
            path.write_bytes(original.read_bytes())
        moved.append((relative.as_posix(), path, target))
    return moved


def _repoint(declared: Any, moved: list[tuple[str, Path, Path]], workspace: Path) -> Any:
    """Declared artifacts that named a moved file now name its staged copy."""

    if not isinstance(declared, list) or not moved:
        return declared
    targets = {old.resolve(): new for _relative, old, new in moved}
    result = []
    for item in declared:
        entry = {"uri": item} if isinstance(item, str) else item
        if isinstance(entry, Mapping):
            uri = _as_uri(entry.get("uri") or entry.get("path"), workspace)
            old = _uri_path(uri) if uri else None
            if old is not None and old in targets:
                entry = {key: value for key, value in entry.items() if key != "path"}
                entry["uri"] = targets[old].resolve().as_uri()
                entry.pop("sha256", None)
            elif isinstance(item, str):
                entry = item
        result.append(entry)
    return result


def normalize_packet(
    raw: Mapping[str, Any],
    *,
    expected: Mapping[str, Any],
    preregistration_sha256: str | None = None,
    workspace: Path | None = None,
    staging_root: Path | None = None,
) -> dict[str, Any]:
    """Turn an owner packet into a result bundle; complete what the control plane knows.

    A payload that is not an owner packet (a full bundle, or the lab runner's own
    failure bundle) only gets its identity fields filled. Nothing the owner
    decided is changed: an explicit wrong pre-registration hash stays wrong so the
    result gate still refuses it.
    """

    status = _owner_status(raw)
    identity = {key: value for key, value in expected.items() if value is not None}
    if status is None or raw.get("schema_version") == RESULT_SCHEMA and isinstance(
        raw.get("owner_packet"), Mapping
    ):
        bundle = dict(raw)
        for key, value in identity.items():
            bundle.setdefault(key, value)
        if staging_root is not None and isinstance(bundle.get("artifacts"), list):
            bundle["artifacts"] = _with_staged(bundle["artifacts"], staging_root)
        return bundle
    packet = {
        key: value for key, value in raw.items()
        if key not in {"schema_version", *identity}
    }
    packet["schema_version"] = PACKET_SCHEMA
    packet["status"] = status
    summary = str(raw.get("summary") or raw.get("reason") or "").strip()
    bundle: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA,
        **identity,
        "summary": summary or f"Owner seat ended: {status}",
        "artifacts": _artifacts(raw.get("artifacts"), workspace=workspace,
                                staging_root=staging_root),
        "claims": [],
        "next_actions": [],
        "paper_candidate": False,
        "owner_packet": packet,
    }
    declared_verdict = str(raw.get("primary_endpoint_verdict") or "").strip().lower()
    declared_sha = str(raw.get("preregistration_sha256") or "").strip().lower()
    if declared_verdict in PRIMARY_ENDPOINT_VERDICTS:
        bundle["primary_endpoint_verdict"] = declared_verdict
    if declared_sha:
        bundle["preregistration_sha256"] = declared_sha
    if raw.get("paper_id"):
        bundle["paper_id"] = str(raw["paper_id"])
    reason = str(raw.get("reason") or "").strip()
    if status == "awaiting_remote":
        block = raw.get("awaiting_remote") if isinstance(raw.get("awaiting_remote"), Mapping) else {}
        ids = raw.get("job_ids") or block.get("job_ids") or []
        job_ids = [str(item).strip().lower() for item in ids if isinstance(item, str)]
        job_ids = [item for item in dict.fromkeys(job_ids) if REMOTE_JOB_ID.fullmatch(item)]
        if job_ids:
            wait: dict[str, Any] = {
                "job_ids": job_ids,
                "resume_objective": str(
                    raw.get("resume_note") or block.get("resume_objective")
                    or "Continue the topic with the finished jobs' outputs."
                ),
            }
            max_wait = raw.get("max_wait_seconds", block.get("max_wait_seconds"))
            if isinstance(max_wait, int) and not isinstance(max_wait, bool) and max_wait > 0:
                wait["max_wait_seconds"] = max_wait
            bundle["status"] = "awaiting_remote"
            bundle["awaiting_remote"] = wait
        else:
            # No usable job id: nothing to wait for, so the topic simply continues.
            packet["status"] = "continuing"
            packet["control_note"] = "awaiting_remote without a valid 32-hex job id"
            bundle["status"] = "completed"
    elif status == "frozen":
        gate: dict[str, Any] = {"promotion_decision": "freeze", "reason": reason or summary}
        # Owners often nest the freeze fields in their own gate_result block; read both.
        nested = raw.get("gate_result") if isinstance(raw.get("gate_result"), Mapping) else {}
        reason_class = str(raw.get("freeze_reason_class") or raw.get("reason_class")
                           or nested.get("freeze_reason_class") or nested.get("reason_class")
                           or "")
        if reason_class:
            gate["freeze_reason_class"] = reason_class
        for key in ("evidence", "reopen_conditions", "reopen_when"):
            value = raw.get(key) if raw.get(key) is not None else nested.get(key)
            if value is not None:
                gate[key] = value
        bundle["status"] = "completed"
        bundle["gate_result"] = gate
        # A freeze is a promotion: an unstated verdict is "pending" (never
        # evaluated) and the ledger's hash is used when the owner gave none.
        bundle.setdefault("primary_endpoint_verdict", "pending")
        if preregistration_sha256 and not declared_sha:
            bundle["preregistration_sha256"] = preregistration_sha256
    elif status == "blocked_human":
        bundle["status"] = "needs_human"
        bundle["human_intervention"] = {"reason": reason or summary}
        bundle["stop_reason"] = reason or summary
    else:  # continuing, ready_for_review
        bundle["status"] = "completed"
    return bundle


def packet_of(payload: Mapping[str, Any]) -> dict[str, Any]:
    packet = payload.get("owner_packet")
    return dict(packet) if isinstance(packet, Mapping) else {}


# --------------------------------------------------------------------------- venue evidence
#
# 2026-11-19/20: owner seats of four topics stopped eight times for a human because a
# publisher refused the evidence page (HTTP 403/406) for a journal's CAS 2025 zone or
# its charges. That is not a human stop (user requirement 2026-11-20): the journal is
# recorded pending verification in registry/verified-venues.yaml and the owner continues
# with it pending, or picks a verified alternative from that registry. A seat's
# blocked_human of that kind becomes ``continuing`` with these instructions, at most
# VENUE_PENDING_LIMIT times per topic; after that the ordinary needs_human path applies.

VENUE_PENDING_LIMIT = 2
VENUE_PENDING_EVENT = "owner_venue_pending"
_REFUSAL = re.compile(r"\b(?:http\s*)?(?:401|403|406|407|429|451)\b|forbidden|not acceptable|"
                      r"access denied|captcha|challenge page", re.IGNORECASE)
_VENUE_WORDS = re.compile(r"journal|venue|\bcas\b|partition|\bzone\b|fee|charge|\bapc\b|"
                          r"colou?r|guide for authors|author guide|publisher|fenqubiao|"
                          r"\bscie\b|indexing|中科院|分区|版面费", re.IGNORECASE)


def venue_access_block(payload: Mapping[str, Any]) -> str | None:
    """The stop reason when an owner seat stopped for a human over unreadable venue evidence."""

    packet = packet_of(payload)
    if str(payload.get("status") or "") != "needs_human" or str(
            packet.get("status") or "") != "blocked_human":
        return None
    intervention = payload.get("human_intervention")
    texts = [str(packet.get("reason") or ""), str(payload.get("summary") or ""),
             str(payload.get("stop_reason") or ""),
             str(intervention.get("reason") or "") if isinstance(intervention, Mapping) else ""]
    text = " ".join(item for item in dict.fromkeys(texts) if item.strip())
    if packet.get("venue_pending_verification") or (_REFUSAL.search(text)
                                                     and _VENUE_WORDS.search(text)):
        return text.strip() or "venue evidence could not be read"
    return None


def venue_pending_note(reason: str) -> str:
    return (
        "The last seat stopped for a human because venue evidence could not be read "
        f"({reason[:600]}). A publisher refusing a page (HTTP 403/406, a challenge page) is "
        "not a human stop (user requirement 2026-11-20). Check the local registry first: "
        "`paper-writing venue lookup --journal <name>`. Record the refusal with `paper-writing "
        "venue mark-pending --journal <name> --url <url> --http-status <code> --reason <what "
        "could not be read> --by <your model>`, then either continue with the journal pending "
        "verification (its open items are completed before submission, which a person "
        "confirms anyway) or switch to a verified alternative from `paper-writing venue "
        "alternatives [--zone N] [--category <CAS major category>]` and register it with that "
        "entry's evidence. If your stop was about something other than journal-eligibility "
        "evidence, return blocked_human again with that reason."
    )


def venue_pending_instead_of_human(db: FactoryDB, task: Mapping[str, Any],
                                   payload: Mapping[str, Any], *, key: str) -> dict[str, Any]:
    """An owner seat's venue-evidence stop becomes ``continuing`` (bounded per topic)."""

    if not is_owner_task(task):
        return dict(payload)
    reason = venue_access_block(payload)
    if reason is None:
        return dict(payload)
    campaign_id = str(task.get("campaign_id") or "")
    used = db.count_events("campaign", campaign_id, VENUE_PENDING_EVENT)
    if used >= VENUE_PENDING_LIMIT:
        return dict(payload)
    packet = packet_of(payload)
    packet.update({"status": "continuing", "control_note": "venue_pending_verification",
                   "venue_pending_verification": {"reason": reason[:1000],
                                                  "conversion": used + 1,
                                                  "limit": VENUE_PENDING_LIMIT},
                   "resume_note": venue_pending_note(reason)})
    bundle = {key_: value for key_, value in payload.items()
              if key_ not in {"human_intervention", "stop_reason"}}
    bundle.update({"status": "completed", "owner_packet": packet})
    db.record_event_once("campaign", campaign_id, VENUE_PENDING_EVENT,
                         {"task_id": str(task.get("task_id") or ""), "reason": reason[:1000],
                          "conversion": used + 1, "limit": VENUE_PENDING_LIMIT},
                         event_key=key)
    return bundle


# --------------------------------------------------------------------------- lineage


def session_seat(db: FactoryDB, task_id: str | None) -> dict[str, Any] | None:
    """Nearest owner seat with a recorded session in a task's lineage."""

    current = db.task(task_id) if task_id else None
    for _ in range(_LINEAGE_LIMIT):
        if current is None:
            return None
        if is_owner_task(current) and current.get("agent_session_id"):
            return current
        parent = current.get("parent_task_id")
        current = db.task(str(parent)) if parent else None
    return None


def session_tasks(db: FactoryDB, source: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Owner seats of ``source``'s agent session in its lineage, newest first."""

    session = str(source.get("agent_session_id") or "")
    if not session:
        return []
    found: list[dict[str, Any]] = []
    current: dict[str, Any] | None = dict(source)
    for _ in range(_LINEAGE_LIMIT):
        if current is None:
            break
        if is_owner_task(current):
            if str(current.get("agent_session_id") or "") != session:
                break
            found.append(current)
        parent = current.get("parent_task_id")
        current = db.task(str(parent)) if parent else None
    return found


def keep_session(
    db: FactoryDB, settings: FactorySettings, source: Mapping[str, Any]
) -> tuple[bool, str]:
    """Whether the next seat resumes ``source``'s session, and why (not).

    ``[program.owner].session_max_seats`` seats per session (0: no limit) and, when set,
    ``session_max_tokens_read`` input tokens read by the session; past either the next
    seat is a fresh session that starts from the owner's handover.
    """

    owner = settings.program.owner
    chain = session_tasks(db, source)
    if not chain:
        return False, "no_session"
    if owner.session_max_seats and len(chain) >= owner.session_max_seats:
        return False, f"session_max_seats:{len(chain)}"
    if owner.session_max_tokens_read:
        from .usage import normalized_attempts, tokens_read

        ids = {str(item["task_id"]) for item in chain}
        read = sum(
            tokens_read(item["runtime"])
            for item in normalized_attempts(db, campaign_ids=[str(source["campaign_id"])])
            if str(item["task_id"]) in ids
        )
        if read >= owner.session_max_tokens_read:
            return False, f"session_max_tokens_read:{read}"
    return True, "resume"


def park_session_mode(
    db: FactoryDB, settings: FactorySettings, current: Mapping[str, Any]
) -> str:
    """Session mode of the seat that wakes after a remote/local-job wait."""

    if not is_owner_task(current) or not current.get("agent_session_id"):
        return "fresh"
    return "resume" if keep_session(db, settings, current)[0] else "fresh"


def last_seat(
    db: FactoryDB, campaign_id: str, *, before: str | None = None
) -> dict[str, Any] | None:
    """Latest owner seat of a topic other than ``before`` (the seat being launched)."""

    with db.connect() as connection:
        row = connection.execute(
            """
            SELECT * FROM tasks WHERE campaign_id=? AND task_type=? AND task_id != ?
              AND attempt > 0
            ORDER BY created_at DESC, rowid DESC LIMIT 1
            """,
            (campaign_id, OWNER_TASK_TYPE, before or ""),
        ).fetchone()
    return dict(row) if row else None


def current_owners(db: FactoryDB, *, exclude_campaign: str | None = None) -> dict[str, set[str]]:
    """Runner -> active campaigns whose latest owner seat is pinned to it."""

    owners: dict[str, set[str]] = {}
    with db.connect() as connection:
        rows = connection.execute(
            """
            SELECT tasks.campaign_id, tasks.runner FROM tasks
            JOIN campaigns USING(campaign_id)
            WHERE tasks.task_type=? AND campaigns.status='active'
            ORDER BY tasks.created_at, tasks.rowid
            """,
            (OWNER_TASK_TYPE,),
        ).fetchall()
    latest: dict[str, str] = {}
    for row in rows:
        latest[str(row["campaign_id"])] = str(row["runner"] or "")
    for campaign_id, runner in latest.items():
        if campaign_id == exclude_campaign or not runner:
            continue
        writing = writing_state(db, campaign_id)
        if writing.get("status") == WRITING_ACTIVE and writing.get("runner") == runner:
            # A writer's seat is not an owner's: max_topics_per_runner does not count it
            # (the writer has its own limit, max_writing_topics).
            continue
        owners.setdefault(runner, set()).add(campaign_id)
    return owners


# --------------------------------------------------------------------------- runner choice


def _router(db: FactoryDB, settings: FactorySettings,
            router: budget_control.QuotaRouter | None) -> budget_control.QuotaRouter | None:
    if router is not None:
        return router
    if not budget_control.routing_enabled(settings):
        return None
    return budget_control.QuotaRouter.build(db, settings)


def runner_usable(
    settings: FactorySettings,
    router: budget_control.QuotaRouter | None,
    name: str,
) -> bool:
    spec = settings.runners.get(name)
    if spec is None:
        return False
    if router is None:
        return True
    return router.usable(spec, budget_control.OWNER_CLASS)


def _under_cap(settings: FactorySettings, owners: Mapping[str, set[str]], name: str) -> bool:
    limit = settings.program.owner.max_topics_per_runner.get(name)
    return limit is None or len(owners.get(name, set())) < int(limit)


def choose_runner(
    db: FactoryDB,
    settings: FactorySettings,
    *,
    campaign_id: str,
    exclude: Iterable[str] = (),
    router: budget_control.QuotaRouter | None = None,
    require_usable: bool = False,
) -> str | None:
    """First owner runner (preference order) under its topic cap and usable now.

    Without ``require_usable`` a runner that is only over its quota allowance is
    still returned when none is usable (the seat waits and may switch later);
    ``None`` without a ``[runners]`` table (the legacy ``frontier`` alias is used).
    """

    if not settings.runners:
        return None
    current = _router(db, settings, router)
    owners = current_owners(db, exclude_campaign=campaign_id)
    skipped = set(exclude)
    candidates = [
        name for name in settings.program.owner.runners
        if name in settings.runners and name not in skipped and _under_cap(settings, owners, name)
    ]
    for name in candidates:
        if runner_usable(settings, current, name):
            return name
    if require_usable or not candidates:
        return None
    return candidates[0]


# --------------------------------------------------------------------------- writer


def writing_state(db: FactoryDB, campaign_id: str) -> dict[str, Any]:
    """The topic's writer record (``owner_state.writing``), empty before any hand-over."""

    value = owner_state(db, campaign_id).get("writing")
    return dict(value) if isinstance(value, Mapping) else {}


def active_writer(db: FactoryDB, settings: FactorySettings, campaign_id: str) -> str | None:
    """Runner that writes this topic's manuscript now, or None (the owner writes)."""

    writing = writing_state(db, campaign_id)
    runner = str(writing.get("runner") or "")
    if writing.get("status") != WRITING_ACTIVE or not runner:
        return None
    if settings.runners and runner not in settings.runners:
        return None
    return runner


def writer_provider(db: FactoryDB, settings: FactorySettings, campaign_id: str) -> str | None:
    """Model family a review of this topic's manuscript must avoid (the active writer's)."""

    spec = settings.runners.get(active_writer(db, settings, campaign_id) or "")
    return spec.provider if spec is not None else None


# Plans of :func:`writing_plan` (who writes this topic's manuscript).
PLAN_WRITER = "writer"
PLAN_FALLBACK = "fallback"
PLAN_HANDOVER = "handover"
PLAN_OWNER = "owner"
# Owner-writes reasons that need no word in the brief (the owner writes as before 11-19,
# or a writer holds the topic and this is another seat, e.g. a direction step).
_SILENT_OWNER_REASONS = frozenset({"writer_is_owner", "writer_unknown", "writer_seat_elsewhere"})


def writing_plan(settings: FactorySettings, state: Mapping[str, Any],
                 runner: str) -> tuple[str | None, str]:
    """Who writes the manuscript of a topic whose seat runs on ``runner``: (plan, why).

    The one place both the brief and the hand-over read (2026-11-20: they disagreed, so a
    topic with review history was told to hand over while no writer seat was ever
    created). ``None`` when no writer is configured (the owner writes, as before
    2026-11-19). ``handover``: the owner solves and hands over once the research is done;
    ``owner``: the owner writes itself - the topic was handed to the owner explicitly, a
    manuscript is already in review or revision, the owner began writing before, the
    writer is this seat's own runner or not a configured runner. It depends only on the
    configured runner names, never on the model family.
    """

    writer = settings.program.owner.writing_runner
    writing = state.get("writing") if isinstance(state.get("writing"), Mapping) else {}
    status = str(writing.get("status") or "")
    if status == WRITING_ACTIVE:
        if settings.runners and str(writing.get("runner") or "") not in settings.runners:
            # The writer runner was removed from the configuration: the seat's runner writes.
            return PLAN_OWNER, "writer_removed"
        if runner == str(writing.get("runner") or ""):
            return PLAN_WRITER, "handed_over"
        return PLAN_OWNER, "writer_seat_elsewhere"
    if status == WRITING_FALLBACK:
        return PLAN_FALLBACK, str(writing.get("fallback_reason") or "writer_unavailable")
    if status == WRITING_OWNER:
        return PLAN_OWNER, str(writing.get("reason") or "recorded")
    if not writer:
        return None, "no_writer"
    if writer not in settings.runners:
        return PLAN_OWNER, "writer_unknown"
    if runner == writer:
        return PLAN_OWNER, "writer_is_owner"
    if _history(state) or state.get("review_round") or state.get("review_stage"):
        return PLAN_OWNER, "review_history"
    if str(state.get("phase") or "") == "writing":
        return PLAN_OWNER, "already_writing"
    return PLAN_HANDOVER, "research_not_done"


def writing_switch_due(
    settings: FactorySettings,
    before: Mapping[str, Any],
    packet: Mapping[str, Any],
    task: Mapping[str, Any],
    *,
    successful: bool,
) -> str | None:
    """Why this finished seat hands the topic to the writer, or None.

    The switch point is the first promoted seat whose packet says the research is done:
    ``phase: writing`` (status ``continuing``), or a ``ready_for_review`` before any
    review - and only while :func:`writing_plan` says ``handover``. Every other plan
    keeps the current writer (the owner writes, see :func:`owner_writes_note`).
    """

    if not successful:
        return None
    plan, _why = writing_plan(settings, before, str(task.get("runner") or ""))
    if plan != PLAN_HANDOVER:
        return None
    status = str(packet.get("status") or "").strip().lower()
    phase = str(packet.get("phase") or "").strip().lower()
    if status not in {"continuing", "ready_for_review"}:
        return None
    if phase != "writing" and status != "ready_for_review":
        return None
    return "phase_writing" if phase == "writing" else "ready_for_review"


_OWNER_WRITES_WHY = {
    "review_history": "a manuscript of this topic is already in review or revision",
    "already_writing": "you began the manuscript before the writer setting",
    "writer_is_owner": "the configured writer is your own runner",
    "writer_unknown": "the configured writer is not a known runner",
    "writer_seat_elsewhere": "the writer holds the topic",
    "writer_removed": "the writer this topic was handed to is no longer configured",
    "recorded": "recorded earlier",
}


def owner_writes_note(why: str) -> str:
    return (f"You write this topic's manuscript and every revision yourself "
            f"({_OWNER_WRITES_WHY.get(why, why)}); no writer seat will take it over. Do not "
            "end a seat waiting for a hand-over.")


def settle_owner_writing(
    db: FactoryDB, paths: WorkspacePaths | None, settings: FactorySettings,
    *, task: Mapping[str, Any], state: Mapping[str, Any],
) -> str | None:
    """Record once that the owner writes (plan ``owner`` without a record); the reason.

    ``state`` is the owner state before the seat (the same view the hand-over decides on).
    Silent reasons (the writer is this seat's own runner, unknown, or holds the topic) are
    not recorded: a later configuration may still hand the topic over.

    Makes the decision explicit and sticky: the owner state says ``writing.status =
    owner`` and the topic's ledger history has a note, so neither the brief nor a later
    seat can expect a hand-over that will not come.
    """

    runner = str(task.get("runner") or "")
    plan, why = writing_plan(settings, state, runner)
    if plan != PLAN_OWNER or why == "recorded" or why in _SILENT_OWNER_REASONS:
        return None
    campaign_id = str(task["campaign_id"])
    record = {"status": WRITING_OWNER, "runner": runner, "reason": why,
              "writer_configured": settings.program.owner.writing_runner,
              "decided_by": str(task.get("task_id") or ""), "at": utc_now()}
    if isinstance(state.get("writing"), Mapping) and state.get("writing"):
        record["previous"] = dict(state["writing"])
    update_state(db, campaign_id, "owner_writes_manuscript", record, writing=record)
    _topic_note(paths, settings, db, campaign_id, event_type="writing_owner",
                reason=f"the owner {runner} writes the manuscript ({why})",
                decided_by=str(task.get("task_id") or ""), detail=record)
    return why


def _topic_note(paths: WorkspacePaths | None, settings: FactorySettings, db: FactoryDB,
                campaign_id: str, *, event_type: str, reason: str, decided_by: str,
                detail: Mapping[str, Any]) -> None:
    """Note a writer change on the topic's ledger entry (best effort, never blocking)."""

    if paths is None:
        return
    try:
        from .program import record_topic_note
        from .program_autonomy import _ledger

        topic = _topic(paths, settings, campaign_id)
        if topic is None:
            return
        record_topic_note(_ledger(paths, settings), str(topic["topic_id"]), db=db,
                          event_type=event_type, reason=reason, decided_by=decided_by,
                          detail=detail)
    except Exception:  # noqa: BLE001 - the owner state and the event keep the record.
        return


def _writer_note(solver: str, trigger: str) -> str:
    return (
        "You are the writer of this topic from now on (user decision 2026-11-19): the research "
        f"is done (owner {solver}, {trigger.replace('_', ' ')}). Start from OWNER_HANDOVER.md, "
        "research_state.json and OWNER_LOG.md. Write the whole manuscript yourself, from the "
        "story line to the last section; do not split the writing among models or sub-agents "
        "(sub-agents may check numbers, citations or builds). Any earlier draft in the "
        "workspace is material, not a text to polish. Do not redo the research: run only what "
        "you need to report it correctly. You also own every revision after the recompute "
        "and unified reviews until delivery. Record writer_model/writer_provider in the paper "
        "record."
    )


def start_writing(
    db: FactoryDB,
    paths: WorkspacePaths | None,
    settings: FactorySettings,
    report: Any,
    *,
    task: Mapping[str, Any],
    campaign: Mapping[str, Any],
    trigger: str,
    result_path: Path,
) -> str | None:
    """Hand the topic to the writer: record it, then queue the writer's first seat."""

    campaign_id = str(campaign["campaign_id"])
    writer = str(settings.program.owner.writing_runner)
    solver = str(task.get("runner") or "")
    record = {"status": WRITING_ACTIVE, "runner": writer, "solver_runner": solver,
              "trigger": trigger, "trigger_task_id": str(task["task_id"]),
              "started_at": utc_now()}
    update_state(db, campaign_id, "owner_writing_handover", record, writing=record)
    reset_streak(db, campaign_id, reason="writing_handover")
    seat = enqueue_seat(db, settings, report, campaign=campaign, parent=task,
                        note=_writer_note(solver, trigger), routing_reason=ROUTING_WRITING,
                        input_path=str(result_path), runner_override=writer)
    _topic_note(paths, settings, db, campaign_id, event_type="writing_handover",
                reason=f"research done ({trigger}); {writer} writes the manuscript",
                decided_by=str(task["task_id"]), detail=record)
    if report is not None:
        report.program.setdefault("owner_writing", []).append(
            {"campaign_id": campaign_id, "kind": "handover", "seat": seat, **record})
    return seat


# --------------------------------------------------------------------------- seats


def _seat_id(campaign_id: str, source: str) -> str:
    digest = hashlib.sha256(f"{campaign_id}\0{source}".encode()).hexdigest()
    return f"owner:{digest[:40]}"


seat_id = _seat_id


def enqueue_seat(
    db: FactoryDB,
    settings: FactorySettings,
    report: Any,
    *,
    campaign: Mapping[str, Any],
    parent: Mapping[str, Any] | None,
    note: str,
    routing_reason: str,
    input_path: str | None = None,
    task_id: str | None = None,
    initial_status: str = "queued",
    last_error: str | None = None,
    not_before: str | None = None,
    router: budget_control.QuotaRouter | None = None,
    runner_override: str | None = None,
) -> str | None:
    """Queue the next seat of a topic: same runner; same session while ``keep_session``.

    While a writer holds the topic (:func:`active_writer`) every seat goes to it, and
    ``runner_override`` pins one seat explicitly; a change of runner starts a fresh
    session from the hand-over file.
    """

    campaign_id = str(campaign["campaign_id"])
    identifier = task_id or _seat_id(campaign_id, str((parent or {}).get("task_id") or "seed"))
    if db.task(identifier) is not None:
        return None
    parent_id = str(parent["task_id"]) if parent else None
    source = session_seat(db, parent_id) if parent_id else None
    runner: str | None = None
    session_mode = "fresh"
    session_source: str | None = None
    session_reason = "no_session"
    if source is not None:
        runner = str(source.get("runner") or "") or None
        keep, session_reason = keep_session(db, settings, source)
        if keep:
            session_mode = "resume"
            session_source = str(source["task_id"])
    elif is_owner_task(parent):
        # No recorded session (the CLI reported none): same owner, fresh session.
        runner = str((parent or {}).get("runner") or "") or None
    pinned = runner_override or active_writer(db, settings, campaign_id)
    if pinned is not None:
        if runner != pinned:
            runner = pinned
            session_mode, session_source, session_reason = "fresh", None, "writing_handover"
    elif runner is not None and settings.runners and runner not in settings.program.owner.runners:
        # The owner list changed (e.g. owners moved to the worker tier): the next seat goes to
        # a listed runner with a fresh session and the hand-over file.
        runner = None
        session_mode, session_source, session_reason = "fresh", None, "owner_runner_not_listed"
    if runner is None:
        runner = choose_runner(db, settings, campaign_id=campaign_id, router=router) or "frontier"
    resources = task_resources(source) if source else default_task_resources(settings)
    db.enqueue_task(
        task_id=identifier,
        campaign_id=campaign_id,
        domain=str(campaign["domain"]),
        task_type=OWNER_TASK_TYPE,
        objective=note.strip() or "Continue owning this topic.",
        input_path=input_path or (str(parent.get("result_path")) if parent and parent.get(
            "result_path") else None),
        skill_path=str(campaign.get("primary_skill") or "") or None,
        runner=runner,
        routing_reason=routing_reason,
        parent_task_id=parent_id,
        agent_role="researcher",
        session_mode=session_mode,
        session_source_task_id=session_source,
        priority=int(campaign.get("priority") or 0),
        max_attempts=settings.max_attempts,
        max_wall_seconds=min(settings.program.owner.seat_wall_seconds,
                             settings.max_task_wall_seconds),
        initial_status=initial_status,
        last_error=last_error,
        not_before=not_before,
        **resources.to_dict(),
    )
    if report is None:
        return identifier
    report.enqueued.append(identifier)
    report.program.setdefault("owner_seats", []).append(
        {"task_id": identifier, "campaign_id": campaign_id, "runner": runner,
         "session_mode": session_mode, "session_reason": session_reason,
         "routing_reason": routing_reason}
    )
    return identifier


def first_seat(
    db: FactoryDB,
    settings: FactorySettings,
    *,
    campaign_id: str,
    task_id: str,
    objective: str,
    input_path: str | None,
    priority: int,
    resources: Any,
) -> str:
    """The first seat of a freshly materialized topic (replaces candidate_maturation)."""

    campaign = db.campaign(campaign_id) or {}
    runner = choose_runner(db, settings, campaign_id=campaign_id) or "frontier"
    db.enqueue_task(
        task_id=task_id,
        campaign_id=campaign_id,
        domain=str(campaign["domain"]),
        task_type=OWNER_TASK_TYPE,
        objective=objective,
        input_path=input_path,
        skill_path=str(campaign.get("primary_skill") or "") or None,
        runner=runner,
        routing_reason=ROUTING_FIRST,
        agent_role="researcher",
        session_mode="fresh",
        priority=priority,
        max_attempts=settings.max_attempts,
        max_wall_seconds=min(settings.program.owner.seat_wall_seconds,
                             settings.max_task_wall_seconds),
        **resources.to_dict(),
    )
    return task_id


# --------------------------------------------------------------------------- progress


def workspace_digest(root: Path | None) -> str | None:
    """Fingerprint of a campaign workspace's research files.

    Bookkeeping (:func:`is_bookkeeping`: owner log, brief, handover, research_state.json,
    logs, quota/utilization/checkpoint receipts) and runtime/output dirs are excluded.
    """

    if root is None or not root.is_dir():
        return None
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in _DIGEST_SKIP_DIRS for part in relative.parts):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        if is_bookkeeping(path.name) or path.name.endswith(".pending"):
            continue
        digest.update(relative.as_posix().encode())
        digest.update(b"\0")
        digest.update(sha256_file(path).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def owner_state(db: FactoryDB, campaign_id: str) -> dict[str, Any]:
    raw = db.meta_get(STATE_META_PREFIX + campaign_id)
    try:
        value = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        value = {}
    return value if isinstance(value, dict) else {}


def _store_state(db: FactoryDB, campaign_id: str, state: Mapping[str, Any],
                 event: tuple[str, Mapping[str, Any]] | None = None) -> None:
    events = [("campaign", campaign_id, event[0], dict(event[1]))] if event else []
    db.update_meta({STATE_META_PREFIX + campaign_id: json.dumps(dict(state), sort_keys=True)},
                   events=events)


def record_seat(
    db: FactoryDB,
    *,
    task: Mapping[str, Any],
    payload: Mapping[str, Any],
    final_status: str,
    workspace_root: Path | None,
    promoted: bool,
    handover_max_bytes: int = 8_192,
    short_seat_seconds: int = 0,
    ledger_status: str | None = None,
) -> dict[str, Any]:
    """Update the no-progress streak and the state signature after one finished seat.

    The state signature (:func:`spin_guard.state_signature`) and its streak
    (``signature_streak``: consecutive seats with the same signature) are reset only by a
    different signature, never by a direction decision or a review request.

    Progress (the streak resets) only through substantive output: the promoted
    workspace's research files changed (bookkeeping excluded, :func:`is_bookkeeping`),
    a declared non-bookkeeping artifact hash not seen before, a start after
    remote/local jobs finished (``remote_wait``), a yield on new jobs, a declared phase
    later than the recorded one, or an advancing packet status (``awaiting_remote``,
    ``ready_for_review``, ``frozen``). A seat shorter than ``short_seat_seconds`` never
    counts through the workspace change alone. Updating OWNER_LOG/OWNER_HANDOVER or a
    quota/utilization receipt is not progress. A seat whose work was not promoted
    (timeout, failed gate) never counts as progress. The seat's handover file is only
    checked (present, size); a missing or oversized one is noted, never refused.
    """

    campaign_id = str(task["campaign_id"])
    state = owner_state(db, campaign_id)
    packet = packet_of(payload)
    phase = str(packet.get("phase") or "").strip().lower()
    packet_status = str(packet.get("status") or "").strip().lower()
    run_seconds = _seat_run_seconds(db, str(task["task_id"]))
    handover = dict(state.get("handover") or {})
    handover_root = workspace_root
    if handover_root is None:
        canonical = (db.campaign(campaign_id) or {}).get("state_path")
        handover_root = Path(str(canonical)) if canonical else None
    if promoted and handover_root is not None:
        path = handover_root / HANDOVER_NAME
        size = path.stat().st_size if path.is_file() else 0
        handover = {"present": path.is_file(), "bytes": size,
                    "over_limit": size > handover_max_bytes, "task_id": str(task["task_id"])}
    known = set(state.get("artifact_hashes") or [])
    digest = workspace_digest(workspace_root) if promoted else None
    new_hashes = [
        str(item.get("sha256")) for item in payload.get("artifacts") or []
        if isinstance(item, Mapping) and SHA256.fullmatch(str(item.get("sha256") or ""))
        and str(item.get("sha256")) not in known
        and not is_bookkeeping(str(item.get("uri") or item.get("path") or ""))
    ] if promoted else []
    short = (run_seconds is not None and short_seat_seconds > 0
             and run_seconds < short_seat_seconds)
    reasons: list[str] = []
    # A digest of an older definition is a baseline only, never a difference.
    comparable = state.get("digest_version") == DIGEST_VERSION
    if (promoted and digest is not None and comparable and digest != state.get("digest")
            and not short):
        reasons.append("workspace_changed")
    if new_hashes:
        reasons.append("new_artifacts")
    if str(task.get("routing_reason") or "") == "remote_wait":
        reasons.append("jobs_finished")
    if final_status == "yielded":
        reasons.append("jobs_submitted")
    previous_phase = str(state.get("phase") or "")
    if (promoted and phase in OWNER_PHASES and previous_phase in OWNER_PHASES
            and OWNER_PHASES.index(phase) > OWNER_PHASES.index(previous_phase)):
        reasons.append("phase_advanced")
    if promoted and packet_status in _ADVANCING_STATUSES:
        reasons.append(f"status_{packet_status}")
    streak = 0 if reasons else int(state.get("no_progress_streak") or 0) + 1
    remembered = list(dict.fromkeys([*(state.get("artifact_hashes") or []), *new_hashes]))
    writing = state.get("writing") if isinstance(state.get("writing"), Mapping) else {}
    jobs = [str(item) for item in packet.get("job_ids") or []
            if isinstance(item, (str, int))] if isinstance(packet.get("job_ids"), list) else []
    signature, fields = spin_guard.state_signature({
        "task_class": OWNER_TASK_TYPE,
        "phase": phase if promoted and phase in OWNER_PHASES else state.get("phase"),
        "status": packet_status if promoted and packet_status else final_status,
        "digest": digest if digest is not None else state.get("digest"),
        "jobs": jobs,
        "review_stage": state.get("review_stage"),
        "review_round": state.get("review_round"),
        "writing": writing.get("status"),
        "ledger": ledger_status,
    })
    # A seat with substantive output (new artifact outside the workspace, finished or new
    # jobs, ...) is never "the same state", even when the fields above did not change.
    same = signature == state.get("signature") and not reasons
    signature_streak = int(state.get("signature_streak") or 0) + 1 if same else 1
    recent = [*(state.get("recent_seats") or [])[-(_RECENT_SEATS - 1):], {
        "task_id": str(task["task_id"]), "status": packet_status or final_status,
        "phase": phase or None, "progress": reasons,
        "note": _short(packet.get("next_step") or packet.get("resume_note")
                       or payload.get("summary") or "", 300) or None,
    }]
    updated = {
        **state,
        "digest": digest if digest is not None else state.get("digest"),
        "digest_version": DIGEST_VERSION if digest is not None else state.get("digest_version"),
        "last_run_seconds": run_seconds,
        "last_short_seat": short,
        "no_progress_streak": streak,
        "seats": int(state.get("seats") or 0) + 1,
        "last_task_id": str(task["task_id"]),
        "last_runner": str(task.get("runner") or ""),
        "last_progress": reasons,
        "artifact_hashes": remembered[-_MAX_REMEMBERED_ARTIFACTS:],
        # Only a promoted seat moves the phase (an unaccepted "writing" would otherwise
        # count as "already writing" and block the writer hand-over).
        "phase": phase if promoted and phase in OWNER_PHASES else state.get("phase"),
        "handover": handover,
        "signature": signature,
        "signature_fields": fields,
        "signature_streak": signature_streak,
        "recent_seats": recent,
        "updated_at": utc_now(),
    }
    _store_state(db, campaign_id, updated, ("owner_seat_recorded", {
        "task_id": str(task["task_id"]), "final_status": final_status,
        "progress": reasons, "no_progress_streak": streak,
        "signature": signature, "signature_streak": signature_streak,
        "run_seconds": run_seconds, "short_seat": short,
        "handover": handover or None,
    }))
    return updated


def _seat_run_seconds(db: FactoryDB, task_id: str) -> float | None:
    """Run time of the seat's latest finished attempt (None when not recorded)."""

    try:
        with db.connect() as connection:
            row = connection.execute(
                "SELECT run_seconds FROM task_attempts WHERE task_id=? AND finished_at IS NOT "
                "NULL ORDER BY rowid DESC LIMIT 1", (task_id,),
            ).fetchone()
    except Exception:  # noqa: BLE001 - the duration only sharpens the progress rule.
        return None
    if row is None or row[0] is None:
        return None
    return float(row[0])


def backoff_not_before(settings: FactorySettings, state: Mapping[str, Any], *,
                       now: datetime | None = None) -> str | None:
    """``not_before`` of the next seat on a no-progress streak (None: start now).

    From the second consecutive no-progress seat on the next seat waits
    ``no_progress_backoff_minutes`` (10, 30, 120 by default; the last repeats).
    """

    streak = int(state.get("no_progress_streak") or 0)
    steps = settings.program.owner.no_progress_backoff_minutes
    if streak < 2 or not steps:
        return None
    minutes = int(steps[min(streak - 2, len(steps) - 1)])
    moment = (now or datetime.now(UTC)) + timedelta(minutes=minutes)
    return budget_control._iso(moment)


def update_state(db: FactoryDB, campaign_id: str, event: str | None = None,
                 detail: Mapping[str, Any] | None = None, **changes: Any) -> dict[str, Any]:
    state = {**owner_state(db, campaign_id), **changes, "updated_at": utc_now()}
    _store_state(db, campaign_id, state, (event, detail or {}) if event else None)
    return state


def reset_review_cycle(db: FactoryDB, campaign_id: str, *, reason: str,
                       keep_passed: bool = False) -> None:
    """A direction decision kept the topic alive: the recompute rounds start again.

    ``keep_passed`` (a retarget: the evidence is unchanged) keeps a recompute review
    that already passed, so the retargeted manuscript goes to the unified review only.
    """

    state = owner_state(db, campaign_id)
    if not state.get("review_round") and not state.get("review_stage"):
        return
    if keep_passed and state.get("review_stage") in {STAGE_PASSED, STAGE_MINOR, STAGE_UNIFIED}:
        return
    update_state(db, campaign_id, "owner_review_cycle_reset",
                 {"reason": reason, "previous_round": state.get("review_round")},
                 review_round=0, review_stage=None,
                 review_cycle=int(state.get("review_cycle") or 0) + 1)


def topic_phase(db: FactoryDB, campaign_id: str, *, topic: Mapping[str, Any] | None = None
                ) -> str:
    """Where a topic stands: precheck/solving/writing (owner-declared), review rounds, ...

    ``awaiting_confirmation`` (ready queue: a human confirms delivery), ``frozen``,
    ``direction_decision``, ``recompute_review_N`` / ``unified_review`` (in flight),
    ``revision_after_round_N`` / ``minor_revision`` (back with the owner), else the
    owner's declared phase or ``research``.
    """

    status = str((topic or {}).get("status") or "")
    if status in {"ready_queue", "submitted"}:
        return "awaiting_confirmation"
    if status == "frozen":
        return "frozen"
    from .program_autonomy import pending_decision

    if pending_decision(db, campaign_id) is not None:
        return "direction_decision"
    state = owner_state(db, campaign_id)
    with db.connect() as connection:
        live = [dict(row) for row in connection.execute(
            "SELECT task_type, routing_reason FROM tasks WHERE campaign_id=? AND status IN "
            "('queued','leased','running') AND task_type='paper_review'", (campaign_id,),
        ).fetchall()]
    if any(row.get("routing_reason") == ROUTING_RECOMPUTE for row in live):
        return f"recompute_review_{int(state.get('review_round') or 0) + 1}"
    if live:
        return "unified_review"
    stage = str(state.get("review_stage") or "")
    if stage == STAGE_MAJOR:
        return f"revision_after_round_{int(state.get('review_round') or 0)}"
    if stage == STAGE_MINOR:
        return "minor_revision"
    if stage == STAGE_UNIFIED:
        return "revision_after_unified_review"
    return str(state.get("phase") or "research")


def reset_streak(db: FactoryDB, campaign_id: str, *, reason: str) -> None:
    state = owner_state(db, campaign_id)
    if int(state.get("no_progress_streak") or 0) == 0:
        return
    _store_state(db, campaign_id, {**state, "no_progress_streak": 0, "reset_reason": reason})


# --------------------------------------------------------------------------- after a result


def _topic(paths: WorkspacePaths, settings: FactorySettings, campaign_id: str) -> dict | None:
    from .program_autonomy import campaign_topic

    return campaign_topic(paths, settings, campaign_id)


def _breaker(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: Any,
    *,
    task: Mapping[str, Any],
    state: Mapping[str, Any],
    result_path: Path,
    result_sha256: str,
) -> bool:
    """Schedule the direction decision once the no-progress streak is long enough."""

    from .program_autonomy import schedule_direction_decision

    if int(state.get("no_progress_streak") or 0) < settings.program.owner.no_progress_seats:
        return False
    topic = _topic(paths, settings, str(task["campaign_id"]))
    if topic is None:
        return False
    scheduled = schedule_direction_decision(
        db, paths, settings, report, topic=topic, trigger=TRIGGER_NO_PROGRESS,
        source_task_id=str(task["task_id"]),
        evidence=[{"path": str(result_path), "sha256": result_sha256}],
        reasons=[str(state.get("summary") or "")] if state.get("summary") else None,
        detail={"no_progress_streak": int(state.get("no_progress_streak") or 0),
                "seats": int(state.get("seats") or 0),
                "threshold": settings.program.owner.no_progress_seats},
    )
    return scheduled is not None


TRIGGER_STALLED = "owner_stalled"


def _ledger_status(paths: WorkspacePaths | None, settings: FactorySettings,
                   campaign_id: str) -> str | None:
    if paths is None:
        return None
    try:
        topic = _topic(paths, settings, campaign_id)
    except Exception:  # noqa: BLE001 - the signature then lacks the ledger status.
        return None
    return str(topic.get("status") or "") or None if topic else None


def stall_diagnosis(settings: FactorySettings, state: Mapping[str, Any],
                    task: Mapping[str, Any]) -> dict[str, Any]:
    """What a direction decision (or a human) needs to see about a same-state stall."""

    plan, why = writing_plan(settings, state, str(task.get("runner") or ""))
    return {
        "signature": state.get("signature"),
        "signature_streak": int(state.get("signature_streak") or 0),
        "state": dict(state.get("signature_fields") or {}),
        "no_progress_streak": int(state.get("no_progress_streak") or 0),
        "recent_seats": list(state.get("recent_seats") or []),
        "writing_plan": {"plan": plan, "why": why,
                         "writer_configured": settings.program.owner.writing_runner},
        "last_runner": str(task.get("runner") or ""),
    }


def _diagnosis_text(diagnosis: Mapping[str, Any]) -> str:
    fields = diagnosis.get("state") or {}
    notes = [str(item.get("note")) for item in diagnosis.get("recent_seats") or []
             if isinstance(item, Mapping) and item.get("note")]
    plan = diagnosis.get("writing_plan") or {}
    return _short(
        f"The topic stayed in the same state for {diagnosis.get('signature_streak')} owner "
        f"seats in a row (phase {fields.get('phase')}, status {fields.get('status')}, ledger "
        f"{fields.get('ledger')}, review stage {fields.get('review_stage')}, writer "
        f"{fields.get('writing')}; research files unchanged, no new jobs), across earlier "
        f"decisions. Writing plan: {plan.get('plan')} ({plan.get('why')}). The seats kept "
        f"saying: {' | '.join(dict.fromkeys(notes)) or 'nothing'}. Decide a step that changes "
        "the state (who acts next and on what), or freeze.", 1_800)


def stalled(state: Mapping[str, Any]) -> dict[str, Any] | None:
    """The stall record when the topic gets no further seat, else None."""

    stall = state.get("stall")
    if isinstance(stall, Mapping) and stall.get("stopped") and (
        stall.get("signature") == state.get("signature")
    ):
        return dict(stall)
    return None


def _stall(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: Any,
    *,
    task: Mapping[str, Any],
    state: Mapping[str, Any],
    result_path: Path,
    result_sha256: str,
) -> bool:
    """Same-state stall: one direction decision with a diagnosis, then no more seats.

    True when the next seat must not be queued (a decision was scheduled, or the topic
    stopped); False leaves the ordinary path (breaker, backoff, next seat) in charge.
    """

    from .program_autonomy import pending_decision, schedule_direction_decision

    repeats = settings.stall_signature_repeats
    streak = int(state.get("signature_streak") or 0)
    if repeats <= 0 or streak < repeats:
        return False
    campaign_id = str(task["campaign_id"])
    signature = str(state.get("signature") or "")
    stall = dict(state.get("stall") or {}) if isinstance(state.get("stall"), Mapping) else {}
    diagnosis = stall_diagnosis(settings, state, task)
    entry = {"campaign_id": campaign_id, "source": "same_state", "task_id": str(task["task_id"]),
             "signature_streak": streak, "state": diagnosis["state"]}
    if stall.get("signature") != signature or not stall.get("decision_task"):
        if pending_decision(db, campaign_id) is not None:
            return False
        topic = _topic(paths, settings, campaign_id)
        scheduled = None
        if topic is not None:
            scheduled = schedule_direction_decision(
                db, paths, settings, report, topic=topic, trigger=TRIGGER_STALLED,
                source_task_id=str(task["task_id"]),
                evidence=[{"path": str(result_path), "sha256": result_sha256}],
                reasons=[_diagnosis_text(diagnosis)], detail=diagnosis)
        if scheduled is not None:
            update_state(db, campaign_id, "owner_stall_decision",
                         {"task_id": str(task["task_id"]), "decision": scheduled,
                          "signature_streak": streak},
                         stall={"signature": signature, "decision_task": scheduled,
                                "decided_at_streak": streak, "at": utc_now()})
            report.program.setdefault("stuck_topics", []).append(
                {**entry, "action": "direction_decision", "decision": scheduled})
            return True
        stall = {"signature": signature, "decided_at_streak": streak}
    if streak < int(stall.get("decided_at_streak") or 0) + settings.stall_seats_after_decision \
            and stall.get("decision_task"):
        return False
    campaign = db.campaign(campaign_id) or {}
    root = Path(str(campaign["state_path"])) if campaign.get("state_path") else None
    record = {**stall, "signature": signature, "stopped": True, "stopped_at": utc_now(),
              "diagnosis": diagnosis, "ledger": diagnosis["state"].get("ledger"),
              # The canonical workspace as it stood: any change there lifts the stop.
              "canonical_digest": workspace_digest(root)}
    update_state(db, campaign_id, "owner_stalled",
                 {"task_id": str(task["task_id"]), "signature_streak": streak}, stall=record)
    _topic_note(paths, settings, db, campaign_id, event_type="owner_stalled",
                reason=_diagnosis_text(diagnosis), decided_by=str(task["task_id"]),
                detail={"signature": signature, "signature_streak": streak,
                        "decision_task": stall.get("decision_task")})
    report.program.setdefault("stuck_topics", []).append({**entry, "action": "stopped"})
    return True


def _recompute_context(state: Mapping[str, Any]) -> str:
    """What the unified review is told about the recompute rounds (no repeated work)."""

    history = [item for item in state.get("review_history") or [] if isinstance(item, Mapping)]
    if not history:
        return ""
    last = history[-1]
    records = ", ".join(str(item.get("result_path")) for item in history[-3:])
    scripts = ", ".join(str(item) for item in (last.get("scripts") or [])[:5])
    return (
        f"An independent recompute review already recomputed the core results from the data "
        f"({len(history)} round(s), last verdict {last.get('verdict')}; records: {records}; "
        f"recompute scripts: {scripts or 'see the records'}). "
        "Do not repeat that recomputation: give its records to the referees as context (in the "
        "response letter of a re-review), and check only that its required items are resolved. "
    )


def _review_objective(packet: Mapping[str, Any], topic: Mapping[str, Any] | None,
                      state: Mapping[str, Any] | None = None) -> str:
    paper = str(packet.get("paper_id") or "").strip()
    sha = str((topic or {}).get("preregistration_sha256") or "")
    return (
        _recompute_context(state or {})
        + (f"The owner names paper ID {paper}. " if paper else
           "Resolve the paper ID from the owner's registered artifacts. ")
        + "Run `paper-writing review unified-run --paper-id <id>` (add --response for a "
        "re-review). It runs the preflight, the target-journal editor screen, two blind "
        "referees and the conservative decision; do not reproduce its stages or edit the "
        "manuscript. Also compare the pre-registered primary endpoint (research_state.json "
        f"`preregistration`, sha256 {sha or 'n/a'}) word for word with the manuscript: quote "
        "the registered endpoint and decision rule, quote the reported outcome, and check the "
        "verdict follows from the registered text read literally; a handling added later is "
        "only a supplementary analysis and the result judged by the original text must also be "
        "reported (a mismatch is a scientific blocker). Check that no simulated or synthetic "
        "data is presented as observation. Return "
        "paper_candidate=true only for outcome ready; otherwise return exactly one structured "
        "text_revision or evidence_remediation action, or none for retarget_required/blocked. "
        "Always copy the paper's registered writing_release into the result field "
        "`review_outcome` (next_action, status, review_stalled, rounds_for_target, "
        "max_rounds_per_target, direction_context, decision_record, decision_record_sha256, "
        "paper_id); the orchestrator decides what follows."
    )


def _enqueue_review(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: Any,
    *,
    task: Mapping[str, Any],
    packet: Mapping[str, Any],
    result_path: Path,
) -> str | None:
    from . import program_autonomy

    review_id = _seat_id(str(task["campaign_id"]), "review:" + str(task["task_id"]))
    review_id = "owner-review:" + review_id.split(":", 1)[1]
    if db.task(review_id) is not None:
        return None
    campaign = db.campaign(str(task["campaign_id"])) or {}
    topic = _topic(paths, settings, str(task["campaign_id"]))
    state = owner_state(db, str(task["campaign_id"]))
    db.enqueue_task(
        task_id=review_id,
        campaign_id=str(task["campaign_id"]),
        domain=str(task["domain"]),
        task_type="paper_review",
        objective=_review_objective(packet, topic, state),
        input_path=str(result_path),
        skill_path="openlabs-paper-review",
        exclude_provider=writer_provider(db, settings, str(task["campaign_id"])),
        runner=dispatch_runner(settings, "paper_review", ROUTING_REVIEW, "frontier"),
        routing_reason=ROUTING_REVIEW,
        parent_task_id=str(task["task_id"]),
        agent_role="reviewer",
        session_mode="fresh",
        priority=int(campaign.get("priority") or 0) + 1,
        max_attempts=settings.max_attempts,
        max_wall_seconds=settings.max_task_wall_seconds,
        **default_task_resources(settings).to_dict(),
    )
    report.enqueued.append(review_id)
    update_state(db, str(task["campaign_id"]), "owner_unified_review_scheduled",
                 {"task_id": review_id}, review_stage=STAGE_UNIFIED)
    try:
        program_autonomy.on_review_scheduled(
            db, paths, settings, campaign_id=str(task["campaign_id"]), review_task_id=review_id
        )
    except (OSError, ValueError) as exc:
        report.errors.append(f"Could not mark topic of {task['campaign_id']} in review: {exc}")
    return review_id


# The writing rules every seat reads (user decision 2026-11-19): one writer, one session, held
# to the readability skill and the narrative check rather than to extra tasks.
WRITING_RULES = (
    "Writing rules (binding): read CODE/workflows/paper/skills/openlabs-paper-readability/"
    "SKILL.md before each draft and revision; story line first, checks to appendix; "
    "`paper-writing narrative-check`, `reader-check` before ready_for_review; figures: "
    "openlabs-paper-figures."
)
REVISION_RULE = (
    " Placement (readability skill, section 5): put added qualifications, checks and explanations "
    "in the appendix or supplement and answer in the response letter; change the main text by at "
    "most one sentence per item, do the requested cuts, and do not let the main text grow unless "
    "the reviewer placed the item in the main text. Rerun `paper-writing narrative-check`."
)


def _review_note(payload: Mapping[str, Any], result_path: Path) -> str:
    outcome = payload.get("review_outcome") if isinstance(payload.get("review_outcome"),
                                                         Mapping) else {}
    action = payload.get("next_actions") or []
    first = action[0] if isinstance(action, list) and action else None
    requested = (
        first.get("objective") if isinstance(first, Mapping) else first
    ) if first else None
    return (
        "The independent pre-submission review returned "
        f"status {outcome.get('status') or 'unknown'}, next action "
        f"{outcome.get('next_action') or 'none'} (round {outcome.get('rounds_for_target')}"
        f" of {outcome.get('max_rounds_per_target')}). Review result: {result_path}; decision "
        f"record: {outcome.get('decision_record') or 'see the result'}."
        + (f" Requested: {str(requested)[:1500]}" if requested else "")
        + " Address it in the manuscript or the evidence as you judge right, keep contrary "
        "results, and return ready_for_review when it is ready for the re-review."
        + REVISION_RULE
    )


# --------------------------------------------------------------------------- recompute review

# Used when the research line declares no ``review_checklist``.
GENERIC_RECOMPUTE_CHECKLIST = (
    "Key numbers: recompute the headline values (abstract, main table, main figure) from the "
    "data and result files the manuscript cites, with your own script.",
    "Data, time and unit systems: check provenance, versions, time standards, units and "
    "conversions the analysis relies on.",
    "Error budget and sensitivity: recompute the stated uncertainties, vary the main analysis "
    "choices, look for double-counted or missing terms.",
    "Literature: spot-check 3-5 references (they exist, metadata right, they say what is cited).",
    "Consistency: numbers agree across abstract, text, tables and figures.",
    "Wording: no internal process words; no claim stronger than the evidence.",
)
_CHECKLIST_TEXT_LIMIT = 6_000


def _section(text: str, section: str) -> str | None:
    import re

    lines = text.splitlines()
    pattern = re.compile(r"^(#+)\s*" + re.escape(section) + r"(?:\b|\s|\.|$)")
    for index, line in enumerate(lines):
        match = pattern.match(line.strip())
        if not match:
            continue
        level = len(match.group(1))
        body = [line]
        for following in lines[index + 1:]:
            heading = re.match(r"^(#+)\s", following.strip())
            if heading and len(heading.group(1)) <= level:
                break
            body.append(following)
        return "\n".join(body).strip()
    return None


def recompute_checklist(paths: WorkspacePaths, settings: FactorySettings,
                        line: str | None) -> dict[str, Any]:
    """The line's ``review_checklist`` (items, or a document section), else the generic one."""

    from .research_lines import line_entry, read_lines_or_none

    entry = line_entry(read_lines_or_none(paths.data / settings.program.research_lines_path),
                       line or "") or {} if line else {}
    spec = entry.get("review_checklist")
    if isinstance(spec, list) and any(isinstance(item, str) and item.strip() for item in spec):
        return {"source": f"line {line} review_checklist",
                "items": [str(item).strip() for item in spec if str(item).strip()]}
    if isinstance(spec, Mapping) and str(spec.get("path") or "").strip():
        path = Path(str(spec["path"]))
        if not path.is_absolute():
            path = paths.data / path
        section = str(spec.get("section") or "").strip()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        body = _section(text, section) if section and text else text
        if body:
            return {"source": f"line {line} review_checklist",
                    "reference": f"{path}" + (f" section {section}" if section else ""),
                    "text": body[:_CHECKLIST_TEXT_LIMIT]}
    return {"source": "generic", "items": list(GENERIC_RECOMPUTE_CHECKLIST)}


def _history(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in state.get("review_history") or [] if isinstance(item, Mapping)]


def _response_of(campaign: Mapping[str, Any], packet: Mapping[str, Any]) -> dict[str, Any] | None:
    """The owner's answer to the last round: REVIEW_RESPONSE.md and/or the packet note."""

    root = Path(str(campaign.get("state_path") or ""))
    path = root / RESPONSE_NAME
    note = str(packet.get("response") or packet.get("review_response") or "").strip()
    result: dict[str, Any] = {}
    if campaign.get("state_path") and path.is_file():
        result = {"path": str(path), "sha256": sha256_file(path)}
    if note:
        result["note"] = note[:2_000]
    return result or None


def _recompute_objective(round_number: int, max_rounds: int) -> str:
    return (
        f"Recompute review, round {round_number} of {max_rounds}, of a topic owner's manuscript "
        "(you are independent of the author; this is not the unified review: do not run "
        "`paper-writing review unified-run` and do not edit the manuscript or the campaign). "
        "Read the packet at the input path. Recompute the core results yourself from the data "
        "and result files the manuscript cites, item by item along packet.checklist: reproduced "
        "/ not reproduced (by how much) / could not reproduce (what is missing). Keep your "
        "scripts and their outputs in your large-outputs directory and list them. For a later "
        "round check each required item of packet.previous_rounds against the author's "
        "response. Return the result field `recompute_review`: {verdict: accept|minor|major|"
        "reject, required: [...], optional: [...], unverified: [...], checks: [{item, outcome, "
        "detail}], scripts: [paths], summary}. major: a core number or conclusion does not "
        "hold as stated; minor: core results reproduce, fixes are local; reject: the main "
        "conclusion fails and no revision of this topic can rescue it. paper_candidate=false."
    )


def _enqueue_recompute_review(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: Any,
    *,
    task: Mapping[str, Any],
    packet: Mapping[str, Any],
    result_path: Path,
    retry_of: str | None = None,
) -> str | None:
    """Queue one recompute review round of the manuscript an owner seat returned."""

    campaign_id = str(task["campaign_id"])
    campaign = db.campaign(campaign_id) or {}
    state = owner_state(db, campaign_id)
    history = _history(state)
    round_number = int(state.get("review_round") or 0) + 1
    max_rounds = settings.program.owner.review_max_rounds
    source = "recompute:" + str(task["task_id"]) + (f":retry:{retry_of}" if retry_of else "")
    review_id = "owner-recompute:" + _seat_id(campaign_id, source).split(":", 1)[1]
    if db.task(review_id) is not None:
        return None
    topic = _topic(paths, settings, campaign_id)
    line = campaign_line(campaign)
    root = Path(str(campaign.get("state_path") or ""))
    body = {
        "schema_version": RECOMPUTE_PACKET_SCHEMA,
        "topic_id": (topic or {}).get("topic_id"),
        "campaign_id": campaign_id,
        "research_line": line,
        "round": round_number,
        "max_rounds": max_rounds,
        "paper_id": packet.get("paper_id") or state.get("paper_id"),
        "owner_seat": str(task["task_id"]),
        "owner_result": str(result_path),
        "canonical_workspace": str(root) if campaign.get("state_path") else None,
        "research_state": campaign.get("workstream_state_path"),
        "work_log": str(root / WORK_LOG_NAME) if campaign.get("state_path") else None,
        "preregistration_sha256": (topic or {}).get("preregistration_sha256"),
        "line_spec": (f"{paths.data / settings.program.research_lines_path} (line {line}: "
                      "owner_requirements, analysis_package)") if line else None,
        "checklist": recompute_checklist(paths, settings, line),
        "previous_rounds": history[-max_rounds:],
        "not_in_scope": "The literal pre-registration check and the venue/editor screen are "
                        "done by the unified review afterwards; do not repeat them here.",
        "created_at": utc_now(),
    }
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
    packet_path = (paths.program_control / "recompute-reviews" / campaign_id.replace(":", "-")
                   / f"round-{round_number}-{digest[:16]}.json")
    atomic_write_json(packet_path, body)
    db.enqueue_task(
        task_id=review_id,
        campaign_id=campaign_id,
        domain=str(task["domain"]),
        task_type="paper_review",
        objective=_recompute_objective(round_number, max_rounds),
        input_path=str(packet_path),
        skill_path=RECOMPUTE_SKILL,
        runner=dispatch_runner(settings, "paper_review", ROUTING_RECOMPUTE, "frontier"),
        routing_reason=ROUTING_RECOMPUTE,
        parent_task_id=str(task["task_id"]),
        # Never the writer's family (the parent seat's family otherwise, as before).
        exclude_provider=writer_provider(db, settings, campaign_id),
        agent_role="reviewer",
        session_mode="fresh",
        priority=int(campaign.get("priority") or 0) + 1,
        max_attempts=settings.max_attempts,
        max_wall_seconds=settings.max_task_wall_seconds,
        **default_task_resources(settings).to_dict(),
    )
    report.enqueued.append(review_id)
    update_state(db, campaign_id, "owner_recompute_review_scheduled",
                 {"task_id": review_id, "round": round_number, "packet": str(packet_path)},
                 review_stage=STAGE_RECOMPUTE, review_in_flight=review_id,
                 paper_id=packet.get("paper_id") or state.get("paper_id"),
                 last_ready_seat=str(task["task_id"]))
    report.program.setdefault("owner_reviews", []).append(
        {"campaign_id": campaign_id, "task_id": review_id, "kind": "recompute",
         "round": round_number})
    return review_id


def recompute_block(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """The reviewer's structured verdict, or None when it is missing or unusable."""

    block = payload.get("recompute_review")
    if not isinstance(block, Mapping):
        return None
    verdict = str(block.get("verdict") or "").strip().lower()
    aliases = {"minor_revision": "minor", "major_revision": "major", "accepted": "accept"}
    verdict = aliases.get(verdict, verdict)
    if verdict not in RECOMPUTE_VERDICTS:
        return None

    def items(name: str) -> list[str]:
        value = block.get(name)
        values = value if isinstance(value, list) else [value] if value else []
        return [_short(item, 600) for item in values if str(item or "").strip()][:20]

    return {"verdict": verdict, "required": items("required"), "optional": items("optional"),
            "unverified": items("unverified"), "scripts": items("scripts"),
            "summary": _short(block.get("summary") or "", 800)}


def _seat_after_review(
    db: FactoryDB, settings: FactorySettings, report: Any, *, campaign: Mapping[str, Any],
    review: Mapping[str, Any], result_path: Path, note: str,
) -> None:
    enqueue_seat(db, settings, report, campaign=campaign, parent=review, note=note,
                 routing_reason=ROUTING_RECOMPUTED, input_path=str(result_path))


def _items_text(values: list[str], limit: int = 1_500) -> str:
    return _short("; ".join(values), limit) if values else "none listed"


def _after_recompute(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: Any,
    *,
    task: Mapping[str, Any],
    campaign: Mapping[str, Any],
    payload: Mapping[str, Any],
    successful: bool,
    final_status: str,
    result_path: Path,
    result_sha256: str,
) -> bool:
    """Next step after one recompute review round (the state machine of the loop)."""

    from .program_autonomy import schedule_direction_decision

    campaign_id = str(campaign["campaign_id"])
    state = owner_state(db, campaign_id)
    block = recompute_block(payload) if successful else None
    seat = db.task(str(task.get("parent_task_id") or "")) or {}
    if block is None:
        retries = list(state.get("recompute_retries") or [])
        if str(task.get("task_id")) not in retries and seat:
            # One fresh re-run before the owner hears about it: a missing verdict is
            # the reviewer's slip, not the manuscript's.
            new = _enqueue_recompute_review(
                db, paths, settings, report, task=seat,
                packet=packet_of(_read_json(Path(str(seat.get("result_path") or "")))),
                result_path=Path(str(seat.get("result_path") or result_path)),
                retry_of=str(task["task_id"]))
            if new is not None:
                update_state(db, campaign_id, "owner_recompute_review_unusable",
                             {"task_id": str(task["task_id"]), "final_status": final_status,
                              "retry": new},
                             recompute_retries=[*retries, new][-20:])
                return True
        _seat_after_review(db, settings, report, campaign=campaign, review=task,
                           result_path=result_path, note=(
                               f"The recompute review {task['task_id']} ended {final_status} "
                               "without a usable verdict. Return ready_for_review again when "
                               "you want it re-run."))
        update_state(db, campaign_id, review_stage=None, review_in_flight=None)
        return True
    round_number = int(state.get("review_round") or 0) + 1
    max_rounds = settings.program.owner.review_max_rounds
    entry = {"round": round_number, "cycle": int(state.get("review_cycle") or 0),
             "task_id": str(task["task_id"]), "runner": str(task.get("runner") or ""),
             "result_path": str(result_path), "result_sha256": result_sha256,
             **{key: block[key] for key in ("verdict", "required", "optional", "unverified",
                                            "scripts", "summary")}}
    history = [*_history(state), entry][-12:]
    verdict = block["verdict"]
    stage = {"accept": STAGE_PASSED, "minor": STAGE_MINOR, "major": STAGE_MAJOR,
             "reject": None}[verdict]
    state = update_state(db, campaign_id, "owner_recompute_review_returned",
                         {"task_id": str(task["task_id"]), "round": round_number,
                          "verdict": verdict, "required": len(block["required"])},
                         review_round=round_number, review_history=history,
                         review_stage=stage, review_in_flight=None)
    report.program.setdefault("owner_reviews", []).append(
        {"campaign_id": campaign_id, "task_id": str(task["task_id"]), "kind": "recompute",
         "round": round_number, "verdict": verdict})
    reset_streak(db, campaign_id, reason="recompute_review_returned")
    reference = (f"Review result: {result_path} (round {round_number} of {max_rounds}). "
                 f"Required: {_items_text(block['required'])}. Optional: "
                 f"{_items_text(block['optional'], 600)}. Not verifiable by the reviewer: "
                 f"{_items_text(block['unverified'], 600)}. Reviewer scripts: "
                 f"{_items_text(block['scripts'], 400)}.")
    if verdict == "accept":
        packet = packet_of(_read_json(Path(str(seat.get("result_path") or "")))) if seat else {}
        _enqueue_review(db, paths, settings, report, task=seat or task,
                        packet={"paper_id": state.get("paper_id"), **packet},
                        result_path=Path(str(seat.get("result_path") or result_path)))
        return True
    if verdict == "minor":
        _seat_after_review(db, settings, report, campaign=campaign, review=task,
                           result_path=result_path, note=(
                               "The independent recompute review judged the manuscript minor "
                               f"revision. {reference} Make the minor changes, then check the "
                               "whole manuscript for consistency yourself (numbers against the "
                               "scripts that produce them, abstract/text/tables/figures), write "
                               f"{RESPONSE_NAME} (item -> change) and return ready_for_review: "
                               "it then goes to the unified review." + REVISION_RULE))
        return True
    trigger = TRIGGER_REVIEW_REJECTED if verdict == "reject" else (
        TRIGGER_REVIEW_ROUNDS if round_number >= max_rounds else None)
    if trigger is None:
        _seat_after_review(db, settings, report, campaign=campaign, review=task,
                           result_path=result_path, note=(
                               "The independent recompute review judged the manuscript major "
                               f"revision. {reference} Fix the science first (rerun what is "
                               "needed; you may submit compute jobs and end the seat "
                               f"awaiting_remote), answer every required item in {RESPONSE_NAME} "
                               "(item -> what changed or why not, with evidence), then return "
                               f"ready_for_review for round {round_number + 1} with a fresh "
                               "reviewer." + REVISION_RULE))
        return True
    topic = _topic(paths, settings, campaign_id)
    scheduled = None
    if topic is not None:
        scheduled = schedule_direction_decision(
            db, paths, settings, report, topic=topic, trigger=trigger,
            source_task_id=str(task["task_id"]),
            evidence=[{"path": str(result_path), "sha256": result_sha256}],
            reasons=[block["summary"]] if block["summary"] else None,
            detail={"verdict": verdict, "round": round_number, "max_rounds": max_rounds,
                    "required": block["required"][:10]},
        )
    if scheduled is None:
        # No decision could be scheduled (one is pending, or the topic left research):
        # the owner hears the verdict instead of the topic stalling.
        _seat_after_review(db, settings, report, campaign=campaign, review=task,
                           result_path=result_path, note=(
                               f"The recompute review returned {verdict} in round "
                               f"{round_number} of {max_rounds}. {reference} Decide whether the "
                               "topic can still reach minor revision; otherwise freeze it."))
    return True


def after_result(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: Any,
    *,
    task: Mapping[str, Any],
    payload: Mapping[str, Any],
    final_status: str,
    successful: bool,
    program_disposition: str | None,
    result_path: Path,
    result_sha256: str,
    workspace_root: Path | None,
    has_room: bool,
) -> bool:
    """Successor of any result of an owner-mode topic; True when it was handled.

    Handles owner seats, the owner's paper review, and (conversion) every legacy
    research task of an owner-mode topic. A ``yielded`` result is left to the
    remote-wait parking, which creates the next owner seat itself.
    """

    limit = settings.program.owner.handover_max_bytes
    short_limit = settings.program.owner.short_seat_seconds
    if final_status == "yielded":
        if is_owner_task(task):
            record_seat(db, task=task, payload=payload, final_status=final_status,
                        workspace_root=workspace_root, promoted=True, handover_max_bytes=limit,
                        short_seat_seconds=short_limit)
        return False
    campaign = db.campaign(str(task["campaign_id"]))
    if campaign is None:
        return True
    task_type = str(task.get("task_type") or "")
    if program_disposition == "handled":
        if is_owner_task(task):
            record_seat(db, task=task, payload=payload, final_status=final_status,
                        workspace_root=workspace_root, promoted=successful,
                        handover_max_bytes=limit, short_seat_seconds=short_limit)
        return True
    if final_status == "failed" and is_owner_task(task):
        # Out of attempts: a seat without progress; replenishment starts the next one
        # unless the breaker sends the topic to a direction decision.
        state = record_seat(db, task=task, payload=payload, final_status=final_status,
                            workspace_root=workspace_root, promoted=False,
                            handover_max_bytes=limit, short_seat_seconds=short_limit,
                            ledger_status=_ledger_status(paths, settings, str(task["campaign_id"])))
        if not _stall(db, paths, settings, report, task=task, state=state,
                      result_path=result_path, result_sha256=result_sha256):
            _breaker(db, paths, settings, report, task=task, state=state,
                     result_path=result_path, result_sha256=result_sha256)
        return True
    if final_status in {"queued", "needs_human", "quarantined", "failed", "cancelled"}:
        # Retried as is, or stopped: the direction decision (needs_human) or the
        # infrastructure triage takes it from here.
        return True
    if str(campaign.get("status") or "") != "active":
        return True
    if not has_room:
        report.errors.append(f"Campaign {campaign['campaign_id']} reached its automatic-task "
                             "safety limit (owner seat deferred to replenishment)")
        return True
    if task_type == "paper_review" and str(task.get("routing_reason") or "") == ROUTING_RECOMPUTE:
        return _after_recompute(db, paths, settings, report, task=task, campaign=campaign,
                                payload=payload, successful=successful,
                                final_status=final_status, result_path=result_path,
                                result_sha256=result_sha256)
    if task_type == "paper_review":
        if successful:
            note = _review_note(payload, result_path)
            routing = ROUTING_REVIEWED
        else:
            note = (f"The pre-submission review task {task['task_id']} ended {final_status} "
                    f"without a decision ({str(task.get('last_error') or '')[:300]}). Return "
                    "ready_for_review again when you want it re-run.")
            routing = ROUTING_RETRY
        enqueue_seat(db, settings, report, campaign=campaign, parent=task, note=note,
                     routing_reason=routing, input_path=str(result_path))
        return True
    if not is_owner_task(task):
        # Conversion of an in-flight topic: its next step is an owner seat.
        note = (
            "You take over this admitted topic, which ran so far as separate staged tasks; "
            f"the last one ({task_type}, {task['task_id']}) ended {final_status} with the "
            f"result at the input path. Its state is in research_state.json and the campaign "
            "workspace; earlier remote job ids are in its results."
        )
        enqueue_seat(db, settings, report, campaign=campaign, parent=task, note=note,
                     routing_reason=ROUTING_CONVERTED, input_path=str(result_path))
        return True
    packet = packet_of(payload)
    before = owner_state(db, str(task["campaign_id"]))
    state = record_seat(db, task=task, payload=payload, final_status=final_status,
                        workspace_root=workspace_root, promoted=successful,
                        handover_max_bytes=limit, short_seat_seconds=short_limit,
                        ledger_status=_ledger_status(paths, settings, str(task["campaign_id"])))
    trigger = writing_switch_due(settings, before, packet, task, successful=successful)
    if trigger is not None:
        start_writing(db, paths, settings, report, task=task, campaign=campaign,
                      trigger=trigger, result_path=result_path)
        return True
    # No hand-over: when the owner writes, say so once and for good (never both unset).
    owner_writes = settle_owner_writing(db, paths, settings, task=task,
                                        state=before) if successful else None
    if owner_writes is not None:
        state = owner_state(db, str(task["campaign_id"]))
    status = str(packet.get("status") or "")
    if successful and status == "ready_for_review":
        verdict = str(packet.get("primary_endpoint_verdict") or "").strip().lower()
        if verdict not in EVALUATED_VERDICTS:
            enqueue_seat(
                db, settings, report, campaign=campaign, parent=task, routing_reason=ROUTING_RETRY,
                note=("ready_for_review needs primary_endpoint_verdict met, failed or "
                      "inconclusive (the manuscript reports the pre-registered endpoint); state "
                      "it and return ready_for_review again."),
            )
            return True
        campaign_id = str(task["campaign_id"])
        reset_streak(db, campaign_id, reason="review_requested")
        history = _history(state)
        response = _response_of(campaign, packet)
        if history and response and not history[-1].get("owner_response"):
            history[-1]["owner_response"] = response
            state = update_state(db, campaign_id, review_history=history)
        stage = str(state.get("review_stage") or "")
        if settings.program.owner.recompute_review and stage not in {
            STAGE_MINOR, STAGE_PASSED, STAGE_UNIFIED,
        }:
            # Recompute review first; the unified review once it says minor or accept.
            _enqueue_recompute_review(db, paths, settings, report, task=task, packet=packet,
                                      result_path=result_path)
            return True
        _enqueue_review(db, paths, settings, report, task=task, packet=packet,
                        result_path=result_path)
        return True
    if _stall(db, paths, settings, report, task=task, state=state,
              result_path=result_path, result_sha256=result_sha256):
        return True
    if _breaker(db, paths, settings, report, task=task,
                state={**state, "summary": payload.get("summary")},
                result_path=result_path, result_sha256=result_sha256):
        return True
    # No progress twice in a row: the next seat waits (no immediate redispatch).
    wait = backoff_not_before(settings, state)
    if wait is not None:
        report.program.setdefault("owner_backoffs", []).append(
            {"campaign_id": str(task["campaign_id"]), "after_task_id": str(task["task_id"]),
             "no_progress_streak": int(state.get("no_progress_streak") or 0),
             "not_before": wait})
    if successful:
        note = str(packet.get("resume_note") or packet.get("next_step") or "").strip() or (
            "Continue owning the topic from where the last seat stopped (your work log).")
        plan, why = writing_plan(settings, state, str(task.get("runner") or ""))
        if plan == PLAN_OWNER and why not in _SILENT_OWNER_REASONS and (
            str(packet.get("phase") or "").strip().lower() == "writing"
        ):
            # The seat may still expect a hand-over (an older brief): it will not come.
            note = owner_writes_note(why) + " " + note
        enqueue_seat(db, settings, report, campaign=campaign, parent=task, note=note,
                     routing_reason=ROUTING_CONTINUE, input_path=str(result_path),
                     not_before=wait)
        return True
    errors = "; ".join(
        str(item) for item in (payload.get("blockers") or [])
    ) or str(task.get("last_error") or payload.get("summary") or final_status)
    enqueue_seat(
        db, settings, report, campaign=campaign, parent=task, routing_reason=ROUTING_RETRY,
        note=(f"The last seat's result was not accepted ({final_status}: {errors[:1500]}); its "
              "workspace changes were not promoted. Fix what the message names and continue; "
              "leave the status JSON before the seat deadline."),
        not_before=wait,
    )
    return True


def replenish(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: Any,
    *,
    campaign: Mapping[str, Any],
    latest: Mapping[str, Any] | None,
) -> None:
    """An owner-mode topic with nothing queued or running gets its next seat.

    Not while the topic is stopped on a same-state stall (:func:`stalled`): it waits until
    its research files or its ledger status change (a human or another process acted).
    """

    campaign_id = str(campaign["campaign_id"])
    stall = stalled(owner_state(db, campaign_id))
    if stall is not None:
        root = Path(str(campaign.get("state_path") or "")) if campaign.get("state_path") else None
        current = workspace_digest(root)
        ledger = _ledger_status(paths, settings, campaign_id)
        changed = current is not None and current != stall.get("canonical_digest")
        if not changed and ledger == stall.get("ledger"):
            report.production_blocked.append(
                {"campaign_id": campaign_id, "reason": "owner_stalled",
                 "since": str(stall.get("stopped_at") or "")})
            return
        update_state(db, campaign_id, "owner_stall_cleared",
                     {"digest_changed": changed, "ledger": ledger, "was": stall.get("ledger")},
                     stall=None, signature_streak=0)
    if latest is None:
        note = "Start owning this admitted topic."
        routing = ROUTING_FIRST
    elif is_owner_task(latest) and str(latest.get("status")) == "succeeded":
        note = "Continue owning the topic from where the last seat stopped (your work log)."
        routing = ROUTING_CONTINUE
    else:
        note = (f"Continue the topic after task {latest['task_id']} "
                f"({latest.get('task_type')}) ended {latest.get('status')}; its result, if any, "
                "is at the input path.")
        routing = ROUTING_CONVERTED if not is_owner_task(latest) else ROUTING_RETRY
    wait = backoff_not_before(settings, owner_state(db, str(campaign["campaign_id"])))
    if wait is not None and latest is not None:
        # Keep the streak's backoff, counted from the last seat's end, not from now.
        ended = budget_control.parse_time(latest.get("updated_at"))
        if ended is not None:
            wait = backoff_not_before(settings, owner_state(db, str(campaign["campaign_id"])),
                                      now=ended)
            if (budget_control.parse_time(wait) or ended) <= datetime.now(UTC):
                wait = None
    seat = enqueue_seat(db, settings, report, campaign=campaign, parent=latest, note=note,
                        routing_reason=routing, not_before=wait,
                        task_id=_seat_id(str(campaign["campaign_id"]), "replenish:" + str(
                            (latest or {}).get("task_id") or "seed")))
    if seat is not None:
        report.production_reseeded.append(str(campaign["campaign_id"]))


# --------------------------------------------------------------------------- switching


def _blocked_since(db: FactoryDB, task_id: str) -> datetime | None:
    return budget_control.parse_time(db.meta_get(BLOCKED_META_PREFIX + task_id))


def _writing_seats(db: FactoryDB, writer: str, statuses: tuple[str, ...]) -> list[dict[str, Any]]:
    marks = ",".join("?" for _ in statuses)
    with db.connect() as connection:
        rows = [dict(row) for row in connection.execute(
            f"SELECT * FROM tasks WHERE task_type=? AND runner=? AND status IN ({marks}) "
            "ORDER BY created_at, rowid", (OWNER_TASK_TYPE, writer, *statuses),
        ).fetchall()]
    return [row for row in rows if active_writer_seat(db, row)]


def active_writer_seat(db: FactoryDB, task: Mapping[str, Any]) -> bool:
    """Whether a seat is a writer's seat (its topic is handed to exactly this runner)."""

    writing = writing_state(db, str(task.get("campaign_id") or ""))
    return writing.get("status") == WRITING_ACTIVE and writing.get("runner") == task.get("runner")


def supervise_writing(
    db: FactoryDB,
    settings: FactorySettings,
    report: Any,
    router: budget_control.QuotaRouter | None,
    *,
    now: datetime | None = None,
    paths: WorkspacePaths | None = None,
) -> list[dict[str, Any]]:
    """Writer seats wait for their writer; after ``writing_wait_hours`` the owner writes.

    A queued writer seat starts when the writer is usable (quota, pacing) and fewer than
    ``max_writing_topics`` writer seats run; otherwise it waits (over the slot limit it is
    held with ``not_before``). It never moves to another runner before the wait is over:
    then it goes back to the topic's original owner, fresh session, and the fallback is
    recorded in the owner state and on the topic.
    """

    owner = settings.program.owner
    writer = owner.writing_runner
    if not writer or writer not in settings.runners:
        return []
    moment = now or datetime.now(UTC)
    admitted = len(_writing_seats(db, writer, ("leased", "running")))
    moves: list[dict[str, Any]] = []
    for task in _writing_seats(db, writer, ("queued",)):
        task_id = str(task["task_id"])
        not_before = budget_control.parse_time(task.get("not_before"))
        if not_before is not None and not_before > moment:
            continue
        usable = router is None or runner_usable(settings, router, writer)
        slot = admitted < owner.max_writing_topics
        if usable and slot:
            admitted += 1
            if db.meta_get(BLOCKED_META_PREFIX + task_id) is not None:
                db.update_meta({BLOCKED_META_PREFIX + task_id: None})
            continue
        since = _blocked_since(db, task_id)
        if since is None:
            db.update_meta({BLOCKED_META_PREFIX + task_id: budget_control._iso(moment)})
            since = moment
        reason = "writer_slots_full" if usable else "writer_unavailable"
        campaign_id = str(task["campaign_id"])
        if moment - since < timedelta(hours=owner.writing_wait_hours):
            if not slot:
                db.hold_queued_task(
                    task_id, not_before=budget_control._iso(
                        moment + timedelta(minutes=_WRITING_SLOT_RECHECK_MINUTES)),
                    event_type="owner_writing_slot_wait",
                    detail={"runner": writer, "running": admitted,
                            "max_writing_topics": owner.max_writing_topics})
            continue
        writing = writing_state(db, campaign_id)
        target = str(writing.get("solver_runner") or "")
        if target not in settings.runners:
            target = choose_runner(db, settings, campaign_id=campaign_id, exclude=[writer],
                                   router=router) or ""
        if not target:
            continue
        detail = {"from_runner": writer, "to_runner": target, "reason": reason,
                  "blocked_since": budget_control._iso(since),
                  "waited_hours": round((moment - since).total_seconds() / 3600, 2)}
        if not db.reassign_queued_task(task_id, runner=target, fresh_session=True,
                                       event="owner_writing_fallback", detail=detail):
            continue
        db.update_meta({BLOCKED_META_PREFIX + task_id: None})
        record = {**writing, "status": WRITING_FALLBACK, "fallback_at": budget_control._iso(moment),
                  "fallback_runner": target, "fallback_reason": reason}
        update_state(db, campaign_id, "owner_writing_fallback", detail, writing=record)
        _topic_note(paths, settings, db, campaign_id, event_type="writing_fallback",
                    reason=(f"writer {writer} could not start for {owner.writing_wait_hours:g} h "
                            f"({reason}); the owner {target} writes"),
                    decided_by=task_id, detail=detail)
        moves.append({"task_id": task_id, **detail})
    if moves and report is not None:
        report.program.setdefault("owner_writing", []).extend(
            {"kind": "fallback", **move} for move in moves)
    return moves


def supervise(
    db: FactoryDB,
    settings: FactorySettings,
    report: Any,
    router: budget_control.QuotaRouter | None,
    *,
    now: datetime | None = None,
    paths: WorkspacePaths | None = None,
) -> list[dict[str, Any]]:
    """Move a queued seat to the next usable runner once its own is blocked too long.

    Writer seats are handled by :func:`supervise_writing` (they wait for the writer).
    """

    if not mode_enabled(settings):
        return []
    writing_moves = supervise_writing(db, settings, report, router, now=now, paths=paths)
    if router is None:
        return writing_moves
    moment = now or datetime.now(UTC)
    owner = settings.program.owner
    moves: list[dict[str, Any]] = []
    with db.connect() as connection:
        rows = [dict(row) for row in connection.execute(
            "SELECT * FROM tasks WHERE task_type=? AND status='queued'", (OWNER_TASK_TYPE,)
        ).fetchall()]
    for task in rows:
        task_id = str(task["task_id"])
        not_before = budget_control.parse_time(task.get("not_before"))
        if not_before is not None and not_before > moment:
            continue
        if active_writer_seat(db, task):
            continue
        runner = str(task.get("runner") or "")
        owners = current_owners(db, exclude_campaign=str(task["campaign_id"]))
        listed = runner in settings.program.owner.runners
        if listed and runner in settings.runners and runner_usable(settings, router, runner) and (
            _under_cap(settings, owners, runner)
        ):
            if db.meta_get(BLOCKED_META_PREFIX + task_id) is not None:
                db.update_meta({BLOCKED_META_PREFIX + task_id: None})
            continue
        since = _blocked_since(db, task_id)
        if since is None:
            db.update_meta({BLOCKED_META_PREFIX + task_id: budget_control._iso(moment)})
            since = moment
        if listed and runner in settings.runners and moment - since < timedelta(
            minutes=owner.switch_after_minutes
        ):
            continue
        target = choose_runner(db, settings, campaign_id=str(task["campaign_id"]),
                               exclude=[runner], router=router, require_usable=True)
        if target is None:
            continue
        old = settings.runners.get(runner)
        new = settings.runners[target]
        keep = bool(
            owner.keep_session_within_provider and old is not None
            and old.provider == new.provider and task.get("session_mode") == "resume"
            and task.get("agent_session_id")
        )
        detail = {"from_runner": runner, "to_runner": target, "keep_session": keep,
                  "blocked_since": budget_control._iso(since),
                  "reason": "owner runner unavailable"}
        if db.reassign_queued_task(task_id, runner=target, fresh_session=not keep,
                                   event="owner_runner_switched", detail=detail):
            db.update_meta({BLOCKED_META_PREFIX + task_id: None})
            moves.append({"task_id": task_id, **detail})
    if moves:
        report.program.setdefault("owner_switches", []).extend(moves)
    return writing_moves + moves


# --------------------------------------------------------------------------- the brief


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _short(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False,
                                                           sort_keys=True)
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _venue_names(value: Any) -> list[str]:
    names: list[str] = []
    for item in value if isinstance(value, list) else [value] if value else []:
        name = item.get("name") if isinstance(item, Mapping) else item
        if str(name or "").strip():
            names.append(str(name).strip())
    return names


def _line_tools(paths: WorkspacePaths, settings: FactorySettings, line: str | None) -> list[str]:
    """Pointers into the research line's own definition (never a copy of its rules)."""

    if not line:
        return []
    from .research_lines import line_entry, line_resources, read_lines_or_none

    entry = line_entry(read_lines_or_none(paths.data / settings.program.research_lines_path),
                       line) or {}
    resources = line_resources(entry)
    items: list[str] = []
    for key, label, limit in _LINE_RESOURCE_LABELS:
        if key in resources:
            items.append(f"{label}: {_short(resources[key], limit)}")
    if entry.get("review_checklist"):
        items.append("independent recompute checklist: `review_checklist` (run it on your own "
                     "results before ready_for_review)")
    venues = entry.get("venues") if isinstance(entry.get("venues"), Mapping) else {}
    rules = venues.get("tier_rules")
    if isinstance(rules, Mapping):
        items.append(
            f"venue tiers: set `research_line: {line}` in the paper's registry record; the line's "
            f"venues.tier_rules make CAS zones {rules.get('routine_tiers')} routine targets and "
            f"{rules.get('fallback_tiers')} fee-free fallbacks for it (not the escalation track)")
    return items


# (line_resources key, brief label, character limit): the line's own pointers, in order.
_LINE_RESOURCE_LABELS: tuple[tuple[str, str, int], ...] = (
    ("standard_entry", "standard entry (shared; do not fork)", 140),
    ("analysis_library", "analysis library", 120),
    ("activate", "environment", 140),
    ("analysis_package", "analysis package (use it)", 170),
    ("control_receipt", "control receipt (cite it, never rerun)", 140),
    ("data", "data", 130),
    ("sop", "sop", 140),
    ("gpu", "GPU (this line)", 170),
)


def _line_gpu(paths: WorkspacePaths, settings: FactorySettings, line: str | None) -> bool:
    if not line:
        return False
    from .research_lines import line_entry, line_uses_gpu, read_lines_or_none

    return line_uses_gpu(line_entry(
        read_lines_or_none(paths.data / settings.program.research_lines_path), line))


def brief_paths(task: Mapping[str, Any]) -> dict[str, str]:
    transaction = task.get("transaction") if isinstance(task.get("transaction"), Mapping) else {}
    staged = Path(str(transaction.get("staged_campaign_workspace") or task.get(
        "agent_workspace") or "."))
    return {
        "staged": str(staged),
        "staging": str(transaction.get("artifact_staging_root") or ""),
        "canonical": str(transaction.get("canonical_campaign_workspace") or ""),
        "work_log": str(staged / WORK_LOG_NAME),
        "brief": str(staged / BRIEF_NAME),
        "result": str(task.get("output_path") or ""),
    }


def _owner_ceiling_text(settings: FactorySettings) -> str:
    """Owner-seat (ordinary) ceiling: one percentage, or one per provider when they differ."""

    routing = settings.routing
    providers = sorted({spec.provider for spec in settings.runners.values()})
    values = {
        provider: budget_control.class_ceiling(routing, budget_control.OWNER_CLASS, provider)
        for provider in providers
    }
    distinct = set(values.values())
    if len(distinct) <= 1:
        value = distinct.pop() if distinct else budget_control.class_ceiling(
            routing, budget_control.OWNER_CLASS
        )
        return f"{value:.0%}"
    return " / ".join(f"{value:.0%} ({provider})" for provider, value in values.items())


# ailab since its 2026-11-20 CPU upgrade: i7-14700K, 20 cores / 28 threads, about 61 GiB RAM
# (the earlier 4-core / 8-thread host ran two 4-process jobs about 1.6x slower each). One
# topic still holds at most campaign_compute_threads (8) queued + running threads.
AILAB_HOST_NOTE = "i7-14700K, 28 threads"


# Brief lines for a line that declares GPU work (``environment.gpu``): the host has one GPU,
# shared by every line and agent; the guard's lock admits one reservation at a time.
GPU_BRIEF_LINES = (
    "  - GPU: one device for every line and agent, one job at a time (a second reservation "
    "fails at once: \"GPU already reserved\", no retry loop). Runs over a few minutes: "
    "`CODE/bin/openlabs-local submit --gpu-memory-mib N --source DIR --cpus N --memory-mib M "
    "--timeout-seconds S -- CMD` (queued, one GPU job at a time), then end the seat "
    "awaiting_remote with its job id.",
)


def compute_brief_lines(settings: FactorySettings, campaign_id: str) -> list[str]:
    """Capacity, the queue snapshot at seat start, and the per-topic thread limit."""

    from . import local_compute, remote_compute
    from .utilization import compute_backlog

    limit = settings.program.campaign_compute_threads
    try:
        caps = json.loads(local_compute.REMOTE_CONFIG_PATH.read_text(encoding="utf-8"))
        local = local_compute.load_settings()
        remote_root = remote_compute.default_queue_root()
        ailab = local_compute.ailab_load(remote_root, caps)
        here = local_compute.local_load()
        mine = remote_compute.campaign_queue_load(
            campaign_id, (remote_root, local_compute.default_queue_root()), infer=True)
    except Exception:  # noqa: BLE001 - the snapshot is advisory
        return []
    memory_gb = round(int(caps.get("memory_mib") or 0) / 1024)
    lines = [
        f"  - Capacity: ailab {caps.get('cpu_threads')} thr/{memory_gb} GB ({AILAB_HOST_NOTE});"
        f" local {local.get('max_jobs')} jobs/{local.get('max_cpus')} thr, shared with agents."
        f" Queued jobs/thr: ailab {ailab.get('queued')}/{ailab.get('queued_cpus')} "
        f"(+{ailab.get('running_cpus')} running), local {here.get('queued')}/"
        f"{here.get('queued_cpus')} (+{here.get('running_cpus')}); this topic "
        f"{mine['jobs']}/{mine['cpu_threads']}"
        + (f" ({mine['inferred']} untagged, inferred)" if mine["inferred"] else "")
        + ".",
    ]
    if limit > 0:
        lines.append(
            f"  - Limit: this topic's queued+running jobs <= {limit} thr; submit refuses more. "
            "Batches, coarse first; `openlabs-remote list --mine`, `withdraw ID`.")
        if mine["cpu_threads"] > limit:
            lines.append(
                f"  - Over the limit now: this topic has {mine['queued']} job(s) queued, "
                f"{mine['running']} running, {mine['cpu_threads']} thr (limit {limit}). First "
                "run `CODE/bin/openlabs-remote list --mine` and withdraw the less important queued jobs "
                "(keep those most decisive for the current verdict, coarse before fine), then "
                "continue; resubmit withdrawn batches later within the limit.")
    backlog = compute_backlog(settings)
    if backlog and backlog.get("backlogged"):
        lines.append("  - The queues are backlogged; no new topics start until they drain.")
    return lines


def render_brief(
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    task: Mapping[str, Any],
    campaign: Mapping[str, Any],
    topic: Mapping[str, Any] | None,
    adapter_family: str | None,
    deadline: datetime,
    handover: str | None = None,
    writing: Mapping[str, Any] | None = None,
    state: Mapping[str, Any] | None = None,
) -> str:
    """The owner's whole brief: goal, resources, tools, hard limits (about 4 KB)."""

    owner = settings.program.owner
    window = settings.proxy_download
    state = _read_json(Path(str(campaign.get("workstream_state_path") or "")))
    prereg = state.get("preregistration") if isinstance(state.get("preregistration"),
                                                        Mapping) else {}
    line = str(state.get("research_line") or campaign_line(campaign) or "")
    where = brief_paths(task)
    code = paths.code
    sha = str((topic or {}).get("preregistration_sha256") or prereg.get("sha256") or "n/a")
    routine = ", ".join(_venue_names(state.get("routine_fallback"))[:4]) or "see research_state.json"
    escalation = ", ".join(_venue_names(state.get("escalation_target"))[:2])
    conditions = state.get("admission_conditions") or []
    used = int(float(campaign.get("agent_seconds_used") or 0))
    maximum = int(campaign.get("max_agent_seconds") or 0)
    tools = _line_tools(paths, settings, line)
    sub = owner.claude_subagent_model or "the session model"
    if adapter_family == "openai-codex":
        models = (
            f"  - You are explicitly authorized to start sub-agents with spawn_agent; set "
            f"`model` to \"{owner.codex_helper_model}\" (or \"{owner.codex_light_model}\" for "
            "simple work) unless the step needs your own model."
        )
    else:
        models = (
            "  - Claude sub-agents: the Agent tool, `model` \"haiku\", \"sonnet\" or \"opus\" "
            f"(default {sub}).\n"
            f"  - GPT through Codex: `codex exec -m {owner.codex_helper_model} -c "
            "approval_policy='\"never\"' --sandbox danger-full-access --skip-git-repo-check "
            "-C DIR -o ANSWER.md - < PROMPT.md` (cheaper: "
            f"`-m {owner.codex_light_model}`; long runs in the background)."
        )
    precheck = (" The card's feasibility_precheck (research_state.json) decides first whether "
                "the topic goes on." if state.get("feasibility_precheck") else "")
    lines = [
        f"# Topic owner: {(topic or {}).get('topic_id') or state.get('topic_id') or campaign['campaign_id']}",
        "",
        "You own this admitted topic end to end; how to get there is your decision.",
        "",
        "## Goal",
        ("One manuscript, on the line's paper template, that an independent recompute review "
         "(another model, fresh session, recomputing your core numbers from your data) judges "
         "minor or accept - or an early, honest verdict that it cannot be done, and why. Major "
         f"verdicts return to you (at most {owner.review_max_rounds} rounds), then the unified "
         "review and a human decide. Run the recompute checklist on your results first."
         if owner.recompute_review else
         "One manuscript, on the research line's paper template, that a venue on the line's "
         "list would publish - or an early, honest verdict that it cannot be done, and why.")
        + precheck,
        f"- Question: {_short(state.get('question') or campaign.get('title') or '', 220)}",
        f"- Pre-registered primary endpoint (sha256 {sha}): "
        f"{_short(prereg.get('primary_endpoint') or prereg, 240)} (full: research_state.json "
        "`preregistration`).",
        f"- Target: {state.get('target_tier') or 'routine'}; venues: {routine}"
        + (f"; escalation: {escalation}" if escalation else "") + f". Admission conditions: "
        f"{len(conditions) if isinstance(conditions, list) else 0} (`admission_conditions`).",
        f"- Budget: {used}/{maximum} Agent seconds used; this seat ends by "
        f"{deadline.strftime('%Y-%m-%d %H:%M')} UTC.",
        "",
        "## Resources",
        f"CODE={code}, DATA={paths.data}.",
        "- Compute: `CODE/bin/openlabs-remote submit --source DIR --cpus N --memory-mib M "
        "--timeout-seconds S -- CMD` (ailab first; CODE/docs/REMOTE_COMPUTE.md). GPU, no "
        "approval: `CODE/bin/openlabs-resource-guard "
        "--task-type gpu --gpu-memory-mib N --gpu-device 0 -- CMD`. Do not wait in the session "
        "for long jobs: end the seat awaiting_remote; it resumes when they finish.",
        *(GPU_BRIEF_LINES if _line_gpu(paths, settings, line) else ()),
        *compute_brief_lines(settings, str(campaign.get("campaign_id") or "")),
        "- Models: use sub-agents or another model whenever it is worth it.",
        models,
        "- Quota: a dispatched seat is authorized; the control plane manages quota. Work "
        "normally; never stop or idle on pace/over signals. Only before calling another model "
        "or many sub-sessions: `providers.*.dispatch_allowed` in `python3 -m openlabs program "
        "utilization --no-gpu` (PYTHONPATH=CODE/orchestrator/src); \"no\" -> a cheaper model.",
        "",
        "## Tools",
        f"- Line `{line or 'n/a'}`: DATA/{settings.program.research_lines_path} -> "
        "`environment`; use its shared entries, do not fork them:",
        *[f"  - {item}" for item in tools],
        f"- Reusable assets: DATA/{settings.program.asset_index_path}. Downloads: "
        "`/workspace/.download-bridge/download-submit --url URL --output /workspace/... "
        "--route auto --wait`.",
        "- Manuscripts: `paper-writing` CLI (CODE/workflows/paper/skills/openlabs-paper-writing/"
        "SKILL.md). Other skills and CODE/AGENTS.md are optional references and checklists.",
        f"- {WRITING_RULES}",
        "",
        "## Hard limits",
        "1. Downloads: bridge only, always `--route auto` (`--route proxy` needs user approval; "
        f"slow is not failed); large proxy downloads (>= {window.large_file_mib} MB file or "
        f"{window.large_batch_mib} MB batch) only {window.start}-{window.end} {window.timezone}, "
        "never split. Never change network, proxy or firewall settings.",
        "2. Never print, copy or send credentials.",
        "3. Heavy work on ailab/the queue or in the resource guard; GPU only through its lock.",
        "4. Never fabricate data, results, citations or reviews; never pass simulated or "
        "synthetic data off as observations or results; report negative results as they are.",
        "5. The pre-registered primary endpoint is fixed; never rewrite it (verdict may stay "
        "pending).",
        "6. Paid publication only in a 2025 CAS zone-1 journal; otherwise a verified fee-free "
        "route (`paper-writing venue lookup` first).",
        "7. Submission, payment, authorship, external publication: stop and leave it to a human.",
        "8. Never approve your own manuscript: return ready_for_review; another model family "
        "reviews it and its comments come back to you.",
        "",
        "## Ending a seat",
        f"Keep {WORK_LOG_NAME} (writable workspace) current. A seat normally starts a fresh "
        f"session: end each with {HANDOVER_NAME} there (<= {owner.handover_max_bytes // 1024} KB:"
        f" state, open items, key paths, pending jobs, last review); answer review items in "
        f"{RESPONSE_NAME}. Then write JSON to the result path: "
        "`{\"status\": \"continuing|awaiting_remote|ready_for_review|frozen|blocked_human\", "
        "\"summary\", \"job_ids\", \"paper_id\", \"primary_endpoint_verdict\": "
        "\"met|failed|inconclusive|pending\", \"phase\": \"precheck|solving|writing\", "
        "\"reason\"}`. Only status is required (job_ids, reason where they apply); the control "
        "plane fills the rest.",
        "- Files: workspace = small text (<= 5 MB: notes, JSON, CSV, scripts, figures); logs, "
        "chains, archives, PDFs, big files -> large-outputs dir (footer, declared for you; "
        "strays are moved there).",
        "- Frozen for a line-level fact? Add `reopen_when` (CODE/orchestrator/src/openlabs/"
        "reopen.py): all true -> reopened once, same pre-registration.",
    ]
    role = writing_brief_lines(settings, task=task, writing=writing, state=state)
    if role:
        lines += ["", "## Writing", *role]
    if handover:
        lines += ["", "## This seat", handover]
    return "\n".join(lines) + "\n"


def writing_brief_lines(settings: FactorySettings, *, task: Mapping[str, Any],
                        writing: Mapping[str, Any] | None,
                        state: Mapping[str, Any] | None = None) -> list[str]:
    """Who writes the manuscript, and what the owner hands over (writing_runner set).

    Reads :func:`writing_plan`, the same decision the hand-over uses, so the brief never
    promises a writer seat the control plane will not create. ``state`` is the owner
    state (review history, declared phase); without it only ``writing`` is known.
    """

    owner = settings.program.owner
    writer = owner.writing_runner
    writing = writing or {}
    runner = str(task.get("runner") or "")
    plan, why = writing_plan(settings, {**dict(state or {}), "writing": writing}, runner)
    if plan == PLAN_WRITER:
        return [f"You are this topic's writer (research by {writing.get('solver_runner')}): write "
                "the whole manuscript yourself and every revision after review, until delivery. "
                "Do not split the writing among models. Plan the figures in the story line and "
                "draw them with `paper-writing figures`."]
    if plan == PLAN_FALLBACK:
        return [f"The writer {writing.get('runner')} could not start for "
                f"{owner.writing_wait_hours:g} h; you write the manuscript and its revisions."]
    if plan == PLAN_OWNER:
        # A writer runner equal to this seat's, or unknown: the owner writes as before.
        return [] if why in _SILENT_OWNER_REASONS else [owner_writes_note(why)]
    if plan != PLAN_HANDOVER:
        return []
    return [
        f"{writer} writes this topic's manuscript (user decision 2026-11-19). When the research "
        f"is complete, do not draft the paper: write {HANDOVER_NAME} for the writer - every "
        "result to report with its value and the file or script that produces it, the figures "
        "and tables available, schematics to draw, the endpoint verdict, negative results, "
        "known limitations, open items, paper_id and venue (files for detail) - then end the "
        "seat with status "
        "continuing and phase writing. The writer takes over from there."
    ]


def handover_text(
    db: FactoryDB,
    settings: FactorySettings,
    campaign: Mapping[str, Any],
    *,
    canonical: str | None = None,
) -> str:
    """The fresh session's start: the owner's own handover (cut to the limit) and pointers.

    The control plane adds only what it knows for certain (file paths, the last review
    round and the owner's recorded answer); the summary itself is the owner's.
    """

    limit = settings.program.owner.handover_max_bytes
    root = Path(canonical) if canonical and Path(canonical).is_dir() else Path(
        str(campaign.get("state_path") or ""))
    path = root / HANDOVER_NAME
    state = owner_state(db, str(campaign["campaign_id"]))
    lines = ["### Handover"]
    if path.is_file():
        data = path.read_bytes()
        text = data[:limit].decode("utf-8", errors="ignore").strip()
        lines.append(f"From {HANDOVER_NAME} (written by the last seat):")
        lines.append(text)
        if len(data) > limit:
            lines.append(f"[cut at {limit} bytes of {len(data)}: keep {HANDOVER_NAME} shorter]")
    else:
        lines.append(f"The last seat left no {HANDOVER_NAME}; start from {WORK_LOG_NAME} and "
                     "research_state.json, and write the handover at the end of this seat.")
    lines.append(f"Work log: {root / WORK_LOG_NAME}; research state: "
                 f"{campaign.get('workstream_state_path') or 'research_state.json'}.")
    history = _history(state)
    if history:
        last = history[-1]
        answer = last.get("owner_response") if isinstance(last.get("owner_response"),
                                                          Mapping) else {}
        lines.append(
            f"Last review: recompute round {last.get('round')}, verdict {last.get('verdict')}, "
            f"result {last.get('result_path')}; required: "
            f"{_items_text(list(last.get('required') or []), 800)}"
            + (f"; your recorded answer: {answer.get('path') or answer.get('note')}"
               if answer else "") + ".")
    return "\n".join(lines)


def render_seat_footer(task: Mapping[str, Any], *, deadline: datetime) -> str:
    where = brief_paths(task)
    return (
        "\n---\n"
        f"Seat {task.get('task_id')} (attempt {task.get('attempt_id')}), ends by "
        f"{deadline.strftime('%Y-%m-%d %H:%M')} UTC.\n"
        f"- result path (the status JSON): `{where['result']}`\n"
        f"- writable campaign workspace: `{where['staged']}` (promoted when the result passes)\n"
        f"- large outputs (datasets, chains, archives): `{where['staging']}`\n"
        f"- canonical campaign, read-only: `{where['canonical']}`\n"
        f"- input of this seat: `{task.get('input_path')}`\n"
    )


def spec_block(
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    task: Mapping[str, Any],
    spec: Mapping[str, Any],
    campaign: Mapping[str, Any],
    wall_seconds: int,
    db: FactoryDB,
) -> dict[str, Any]:
    """``owner`` block of a seat's task spec: the rendered request and runtime facts."""

    spec_view = dict(spec)
    deadline = datetime.now(UTC) + timedelta(seconds=max(60, int(wall_seconds)))
    topic = _topic(paths, settings, str(campaign["campaign_id"]))
    spec_runner = settings.runners.get(str(task.get("runner") or ""))
    family = spec_runner.provider if spec_runner is not None else None
    resumed = bool(
        str(task.get("session_mode") or "") == "resume" and task.get("agent_session_id")
    )
    note = str(spec.get("objective") or task.get("objective") or "").strip()
    where = brief_paths(spec_view)
    if resumed:
        request = (
            f"# Topic owner: next seat\n\n{note}\n\nYour brief is unchanged ({BRIEF_NAME} in "
            f"the writable workspace); the paths below are new for this seat. Update "
            f"{WORK_LOG_NAME} and {HANDOVER_NAME} there, then write the status JSON.\n"
        )
    else:
        previous = last_seat(db, str(campaign["campaign_id"]), before=str(task["task_id"]))
        handover = note
        if previous is not None:
            handover = (
                f"A previous owner session ({previous.get('runner')}, seat "
                f"{previous['task_id']}) ran this topic. {note}\n\n"
                + handover_text(db, settings, campaign, canonical=where["canonical"])
            )
        request = render_brief(paths, settings, task={**spec_view, "runner": task.get("runner")},
                               campaign=campaign, topic=topic, adapter_family=family,
                               deadline=deadline, handover=handover,
                               writing=writing_state(db, str(campaign["campaign_id"])),
                               state=owner_state(db, str(campaign["campaign_id"])))
        brief_file = Path(where["brief"])
        if brief_file.parent.is_dir():
            brief_file.write_text(request, encoding="utf-8")
    request += render_seat_footer(spec_view, deadline=deadline)
    sha = str((topic or {}).get("preregistration_sha256") or "")
    return {
        "schema_version": PACKET_SCHEMA,
        "request": request,
        "fresh": not resumed,
        "work_log": where["work_log"],
        "preregistration_sha256": sha if SHA256.fullmatch(sha) else None,
        "artifact_staging_root": where["staging"] or None,
        "claude_subagent_model": settings.program.owner.claude_subagent_model,
        "campaign_compute_threads": settings.program.campaign_compute_threads,
        "deadline": deadline.isoformat().replace("+00:00", "Z"),
    }


def hook_normalize(context: Mapping[str, Any]) -> None:
    """Stop-hook side: rewrite the owner's packet at the result path into a bundle."""

    block = context.get("owner")
    if not isinstance(block, Mapping):
        return
    path = Path(str(context.get("result_path") or "")).expanduser()
    if not path.is_file():
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(raw, Mapping):
        return
    staging = str(block.get("artifact_staging_root") or "").strip()
    canonical = str(context.get("canonical_campaign_workspace") or "").strip()
    moved = relocate_bulk_files(
        Path(str(context.get("agent_workspace") or "")).expanduser() if context.get(
            "agent_workspace") else None,
        Path(staging) if staging else None,
        Path(canonical) if canonical else None,
    )
    if moved:
        work = Path(str(context.get("agent_workspace") or ".")).expanduser()
        raw = {**raw, "artifacts": _repoint(raw.get("artifacts"), moved, work)}
        if raw.get("schema_version") != RESULT_SCHEMA:
            raw["control_note"] = (
                "moved to artifact staging (logs/bulk are not allowed in the campaign "
                "workspace): " + ", ".join(item[0] for item in moved[:20]))
        if raw.get("artifacts") is None:
            raw.pop("artifacts")
    bundle = normalize_packet(
        raw,
        expected=dict(context.get("expected_result") or {}),
        preregistration_sha256=block.get("preregistration_sha256"),
        workspace=Path(str(context.get("agent_workspace") or ".")),
        staging_root=Path(staging) if staging else None,
    )
    if bundle != raw or moved:
        atomic_write_json(path, bundle)


__all__ = [
    "OWNER_STATUSES",
    "PACKET_SCHEMA",
    "RECOMPUTE_VERDICTS",
    "TRIGGER_NO_PROGRESS",
    "TRIGGER_REVIEW_REJECTED",
    "TRIGGER_REVIEW_ROUNDS",
    "after_result",
    "applies",
    "choose_runner",
    "enqueue_seat",
    "first_seat",
    "handover_text",
    "hook_normalize",
    "keep_session",
    "normalize_packet",
    "park_session_mode",
    "recompute_block",
    "recompute_checklist",
    "record_seat",
    "render_brief",
    "replenish",
    "reset_review_cycle",
    "spec_block",
    "supervise",
    "topic_phase",
    "workspace_digest",
]
