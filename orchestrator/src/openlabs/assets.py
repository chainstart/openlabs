"""Reusable-asset library: index, registration, check-before-build views, retrospectives.

Deterministic bookkeeping only. Which scripts, procedures and lessons are worth
keeping is judged by an agent in a ``topic_retrospective`` task (or by an
operator registering a draft); this module

* keeps the index (``[program] asset_index_path``, default
  ``registry/reusable-assets.json``) with one locked, atomic, idempotent write
  per change, in the manner of the topic ledger,
* registers proposals: checks their fields, that their files lie in the
  topic's workspace (or are hash-bound artifacts of the retrospective result),
  that a tool asset carries the receipt of its minimal verification run,
  hashes, de-duplicates (same content, or a near-identical tool or note that
  becomes a new version), copies the body into ``<assets root>/<kind>/<id>/``
  and writes ``events`` rows,
* offers a one-line-per-asset summary of active assets, ranked by relevance to
  the task's domain and data sources and capped in count and size, to scouts,
  the admission gate, direction decisions and research tasks,
* counts declared uses (``assets_used``) and reports (``assets_broken``),
* archives on a schedule (never deletes): unused tools after N days, assets
  reported broken twice in a row, and the oldest lessons above a cap.

The orchestrator never runs an asset's command. The retrospective agent runs
the minimal verification inside its own workspace and resource guard and
returns the output as a hash-bound result artifact; registration only checks
that this receipt exists, matches its hash and records the declared command
with exit code 0.
"""

from __future__ import annotations

import ast
import copy
import difflib
import fcntl
import hashlib
import json
import re
import shutil
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from . import budget as budget_control
from .config import FactorySettings, WorkspacePaths
from .contracts import (
    ASSET_KINDS,
    IDENTIFIER,
    TOOL_ASSET_KINDS,
    atomic_write_json,
    canonical_json_bytes,
    data_source_identifiers,
    sha256_file,
    validate_asset_proposal,
)
from .db import FactoryDB
from .program import normalize_text, open_topic_ledger, topic_for_campaign
from .resources import default_task_resources

INDEX_SCHEMA = "openlabs.reusable_assets.v1"
RETROSPECTIVE_TASK_TYPE = "topic_retrospective"
RETROSPECTIVE_SKILL = "openlabs-asset-retrospective"
RETROSPECTIVE_PACKET_SCHEMA = "openlabs.topic_retrospective_packet.v1"
RETROSPECTIVE_ROUTING_REASON = "topic_retrospective"
RETRO_META_PREFIX = "asset_retrospective:"
RETRO_SINCE_KEY = "asset_retrospective_since"
MAINTENANCE_KEY = "asset_maintenance_at"
USAGE_META_PREFIX = "asset_usage:"
TERMINAL_STATES = ("ready_queue", "frozen")
MAX_RETROSPECTIVE_ATTEMPTS = 2
IN_FLIGHT = ("queued", "leased", "running")
FAILED_STATUSES = ("failed", "needs_human", "needs_replan", "quarantined", "cancelled")
RESEARCH_ROLES = frozenset({"researcher", "experimenter"})
SUMMARY_FIELDS = ("asset_id", "kind", "title", "summary", "domains", "data_sources",
                  "use_count", "last_verified_at")
ASSET_FIELDS = (
    "asset_id", "kind", "title", "summary", "domains", "data_sources", "methods", "path",
    "body", "negative", "entrypoint", "usage", "requirements", "origin", "sha256",
    "created_at", "last_verified_at", "last_used_at", "verification", "use_count", "used_by",
    "broken_reports", "broken_streak", "status", "superseded_by", "supersedes", "version",
    "archived_at", "archive_reason", "files",
)
MAX_BODY_BYTES = 20 * 1024 * 1024
MAX_BODY_FILES = 200
MAX_BROKEN_REPORTS_KEPT = 10
SIMILAR_TITLE_RATIO = 0.8
SKIPPED_PARTS = frozenset({"__pycache__", ".git", ".pytest_cache", "node_modules"})
SEED_SUFFIXES = frozenset({".py", ".R", ".r", ".sh"})


class AssetIndexError(ValueError):
    """The asset index or a requested change is invalid."""


# --------------------------------------------------------------------------- helpers


def _now() -> datetime:
    return budget_control.current_time()


def _iso(moment: datetime | None = None) -> str:
    return (moment or _now()).isoformat(timespec="seconds").replace("+00:00", "Z")


def _token(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in value).strip("-._")
    return cleaned or "asset"


def _digest(*parts: Any) -> str:
    return hashlib.sha256("\0".join(str(part) for part in parts).encode()).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected an object: {path}")
    return value


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def source_key(value: Any) -> str:
    """Data-source identifier in the topic-card form (DOI or URL), normalized for matching."""

    text = str(value or "").strip().casefold()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text.rstrip("/")


def _keys(values: Iterable[Any]) -> set[str]:
    return {key for key in (source_key(value) for value in values or []) if key}


def _norm_set(values: Iterable[Any]) -> set[str]:
    return {key for key in (normalize_text(value) for value in values or []) if key}


def _enabled(settings: FactorySettings) -> bool:
    return bool(settings.program.enabled and settings.assets.enabled)


def _retro_enabled(settings: FactorySettings) -> bool:
    return bool(settings.program.enabled and settings.assets.retrospective_enabled)


def _artifact_file(uri: Any) -> Path | None:
    text = str(uri or "")
    parsed = urlparse(text)
    if parsed.scheme == "file" and parsed.netloc in {"", "localhost"}:
        return Path(unquote(parsed.path))
    if text and not parsed.scheme and Path(text).is_absolute():
        return Path(text)
    return None


def _bound_artifacts(payload: Mapping[str, Any]) -> dict[str, tuple[Path, str]]:
    """artifact_id -> (file, sha256) for the hash-bound artifacts of a result bundle."""

    found: dict[str, tuple[Path, str]] = {}
    for item in payload.get("artifacts") or []:
        if not isinstance(item, Mapping):
            continue
        path = _artifact_file(item.get("uri") or item.get("path"))
        digest = str(item.get("sha256") or "")
        artifact_id = str(item.get("artifact_id") or "")
        if artifact_id and path is not None and digest:
            found[artifact_id] = (path, digest)
    return found


# --------------------------------------------------------------------------- index


def empty_index() -> dict[str, Any]:
    return {"schema_version": INDEX_SCHEMA, "updated_at": None, "assets": []}


def validate_index(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AssetIndexError("asset index must be a JSON object")
    schema = payload.get("schema_version")
    if schema not in (None, INDEX_SCHEMA):
        raise AssetIndexError(f"asset index schema_version must be {INDEX_SCHEMA}")
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise AssetIndexError("asset index assets must be a list")
    seen: set[str] = set()
    for asset in assets:
        if not isinstance(asset, dict):
            raise AssetIndexError("asset index entries must be objects")
        asset_id = str(asset.get("asset_id") or "")
        if not asset_id or asset_id in seen:
            raise AssetIndexError(f"asset index has a missing or duplicate asset_id {asset_id!r}")
        seen.add(asset_id)
        if asset.get("kind") not in ASSET_KINDS:
            raise AssetIndexError(f"asset {asset_id} has unknown kind {asset.get('kind')!r}")
        if asset.get("status") not in {"active", "archived"}:
            raise AssetIndexError(f"asset {asset_id} has unknown status {asset.get('status')!r}")
    return payload


@dataclass(frozen=True)
class AssetIndex:
    """Locked, atomic access to the reusable-asset index document."""

    path: Path
    lock_path: Path

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return empty_index()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AssetIndexError(f"asset index {self.path} is not valid JSON: {exc}") from exc
        return validate_index(payload)

    @contextmanager
    def transaction(self) -> Iterator[dict[str, Any]]:
        """Yield a mutable index; write it back atomically only if it changed."""

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                document = self.read()
                before = copy.deepcopy(document)
                yield document
                if document != before:
                    document["schema_version"] = INDEX_SCHEMA
                    validate_index(document)
                    document["updated_at"] = _iso()
                    atomic_write_json(self.path, document)
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def index_path(paths: WorkspacePaths, settings: FactorySettings) -> Path:
    relative = Path(settings.program.asset_index_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise AssetIndexError("asset_index_path must be relative to the data repository")
    return paths.data / relative


def open_asset_index(paths: WorkspacePaths, settings: FactorySettings) -> AssetIndex:
    return AssetIndex(path=index_path(paths, settings),
                      lock_path=paths.database / "live" / "reusable-assets.lock")


def asset_root(paths: WorkspacePaths, settings: FactorySettings) -> Path:
    return paths.data / settings.assets.root


def find_asset(document: Mapping[str, Any], asset_id: str) -> dict[str, Any] | None:
    for asset in document.get("assets") or []:
        if asset.get("asset_id") == asset_id:
            return asset
    return None


def _event(db: FactoryDB | None, asset_id: str, event_type: str, payload: Mapping[str, Any],
           key: str) -> None:
    if db is not None:
        db.record_event_once("asset", asset_id, event_type, dict(payload), event_key=key)


# --------------------------------------------------------------------------- archive


def _archive(asset: dict[str, Any], paths: WorkspacePaths, settings: FactorySettings,
             reason: str) -> None:
    """Mark archived and move the body under ``<root>/archive``; nothing is deleted."""

    if asset.get("status") == "archived":
        return
    relative = str(asset.get("path") or "")
    if relative:
        source = paths.data / relative
        target_rel = Path(settings.assets.root) / "archive" / str(asset["kind"]) / str(
            asset["asset_id"]
        )
        target = paths.data / target_rel
        if source.exists() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
        if target.exists():
            asset["path"] = target_rel.as_posix()
    asset["status"] = "archived"
    asset["archived_at"] = _iso()
    asset["archive_reason"] = reason


def archive_asset(db: FactoryDB | None, paths: WorkspacePaths, settings: FactorySettings,
                  asset_id: str, *, reason: str, decided_by: str) -> dict[str, Any]:
    index = open_asset_index(paths, settings)
    with index.transaction() as document:
        asset = find_asset(document, asset_id)
        if asset is None:
            raise AssetIndexError(f"unknown asset {asset_id}")
        changed = asset.get("status") == "active"
        _archive(asset, paths, settings, reason)
        snapshot = copy.deepcopy(asset)
    if changed:
        _event(db, asset_id, "asset_archived", {"reason": reason, "decided_by": decided_by},
               f"archived:{asset_id}")
    return {"asset_id": asset_id, "status": snapshot["status"], "changed": changed,
            "path": snapshot.get("path"), "archive_reason": snapshot.get("archive_reason")}


# --------------------------------------------------------------------------- registration


def _resolve_source(raw: str, *, base: Path | None, roots: tuple[Path, ...],
                    artifacts: Mapping[str, tuple[Path, str]] | None) -> tuple[Path | None, str]:
    """(file or directory, problem). ``artifact:<id>`` names a hash-bound result artifact."""

    text = raw.strip()
    if text.startswith("artifact:"):
        found = (artifacts or {}).get(text[len("artifact:"):])
        if found is None:
            return None, f"{text} is not an artifact of the result"
        path, digest = found
        if not path.is_file() or sha256_file(path) != digest:
            return None, f"{text} is missing or differs from its recorded sha256"
        return path, ""
    candidate = Path(text)
    if not candidate.is_absolute():
        if base is None:
            return None, f"{text} must be absolute"
        candidate = base / candidate
    if any(part == ".." for part in Path(text).parts):
        return None, f"{text} must not contain '..'"
    if candidate.is_symlink():
        return None, f"{text} is a symlink"
    if not candidate.exists():
        return None, f"{text} does not exist"
    if not any(_inside(candidate, root) for root in roots):
        return None, f"{text} is outside the topic workspace"
    return candidate.resolve(), ""


def _manifest(sources: list[Path]) -> tuple[dict[str, str], list[tuple[Path, str]], str]:
    """{relative name: sha256}, copy plan, problem (size, count, symlink, name clash)."""

    manifest: dict[str, str] = {}
    plan: list[tuple[Path, str]] = []
    total = 0
    for source in sources:
        files = [(source, source.name)] if source.is_file() else [
            (item, f"{source.name}/{item.relative_to(source).as_posix()}")
            for item in sorted(source.rglob("*"))
            if not (set(item.relative_to(source).parts) & SKIPPED_PARTS)
            and item.suffix != ".pyc" and (item.is_file() or item.is_symlink())
        ]
        for path, name in files:
            if path.is_symlink():
                return {}, [], f"{name} is a symlink"
            if name in manifest:
                return {}, [], f"two sources share the name {name}"
            total += path.stat().st_size
            manifest[name] = sha256_file(path)
            plan.append((path, name))
    if not manifest:
        return {}, [], "no files to register"
    if len(manifest) > MAX_BODY_FILES:
        return {}, [], f"more than {MAX_BODY_FILES} files"
    if total > MAX_BODY_BYTES:
        return {}, [], f"body exceeds {MAX_BODY_BYTES // (1024 * 1024)} MiB (data is not an asset)"
    return manifest, plan, ""


def _verification(proposal: Mapping[str, Any], *, base: Path | None,
                  artifacts: Mapping[str, tuple[Path, str]] | None,
                  receipts_root: Path) -> tuple[dict[str, Any] | None, str]:
    block = proposal.get("verification")
    if not isinstance(block, Mapping):
        return None, "verification_receipt_missing"
    command = " ".join(str(block.get("command") or "").split())
    receipt = block.get("receipt") if isinstance(block.get("receipt"), Mapping) else {}
    digest = str(receipt.get("sha256") or "")
    if artifacts is not None:
        # Retrospective: the receipt must be a hash-bound artifact of the result.
        matches = [path for path, sha in artifacts.values() if sha == digest]
        if not matches:
            return None, "verification_receipt_not_a_result_artifact"
        path = matches[0]
    else:
        path = Path(str(receipt.get("path") or ""))
        if not path.is_absolute() and base is not None:
            path = base / path
    if not path.is_file() or sha256_file(path) != digest:
        return None, "verification_receipt_missing_or_changed"
    try:
        content = _read_object(path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None, "verification_receipt_not_json"
    if " ".join(str(content.get("command") or "").split()) != command:
        return None, "verification_receipt_command_differs"
    if content.get("exit_code") != 0:
        return None, "verification_failed"
    stored = receipts_root / f"{digest}.json"
    if not stored.is_file():
        stored.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, stored)
    return {"command": command, "exit_code": 0, "status": "passed", "receipt_sha256": digest,
            "receipt_path": None, "verified_at": _iso()}, ""


def _asset_id(kind: str, title: str, digest: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")[:48].strip("-")
    asset_id = f"{slug or kind}-{digest[:8]}"
    return asset_id if IDENTIFIER.match(asset_id) else f"{kind}-{digest[:12]}"


def _similar(asset: Mapping[str, Any], proposal: Mapping[str, Any]) -> bool:
    if asset.get("kind") != proposal.get("kind"):
        return False
    if _keys(asset.get("data_sources") or []) != _keys(proposal.get("data_sources") or []):
        return False
    if _norm_set(asset.get("methods") or []) != _norm_set(proposal.get("methods") or []):
        return False
    ratio = difflib.SequenceMatcher(
        None, normalize_text(asset.get("title")), normalize_text(proposal.get("title"))
    ).ratio()
    return ratio >= SIMILAR_TITLE_RATIO


def register_asset(
    db: FactoryDB | None,
    paths: WorkspacePaths,
    settings: FactorySettings,
    proposal: Any,
    *,
    origin: Mapping[str, Any],
    source_roots: tuple[Path, ...],
    base: Path | None,
    artifacts: Mapping[str, tuple[Path, str]] | None,
    decided_by: str,
) -> dict[str, Any]:
    """Register one proposal; return ``{outcome, asset_id, errors, supersedes}``.

    ``artifacts`` (a retrospective's hash-bound result artifacts) makes the
    verification receipt and ``artifact:<id>`` sources come from that result;
    ``None`` (operator draft) checks the receipt file's hash only.
    Outcomes: ``registered``, ``new_version``, ``duplicate`` or ``rejected``.
    """

    validation = validate_asset_proposal(proposal)
    if not validation.valid:
        return {"outcome": "rejected", "asset_id": None, "errors": list(validation.errors)}
    assert isinstance(proposal, Mapping)
    kind = str(proposal["kind"]).strip()
    sources: list[Path] = []
    for raw in proposal.get("source_paths") or []:
        resolved, problem = _resolve_source(str(raw), base=base, roots=source_roots,
                                            artifacts=artifacts)
        if problem:
            return {"outcome": "rejected", "asset_id": None,
                    "errors": [f"source_paths: {problem}"]}
        assert resolved is not None
        sources.append(resolved)
    manifest: dict[str, str] = {}
    plan: list[tuple[Path, str]] = []
    if sources:
        manifest, plan, problem = _manifest(sources)
        if problem:
            return {"outcome": "rejected", "asset_id": None, "errors": [f"source_paths: {problem}"]}
        content_sha = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    else:
        content_sha = hashlib.sha256(canonical_json_bytes({
            "kind": kind, "body": proposal.get("body"), "negative": proposal.get("negative"),
        })).hexdigest()
    verification: dict[str, Any] | None = None
    if kind in TOOL_ASSET_KINDS:
        root = asset_root(paths, settings)
        verification, problem = _verification(proposal, base=base, artifacts=artifacts,
                                               receipts_root=root / "receipts")
        if problem:
            return {"outcome": "rejected", "asset_id": None, "errors": [problem]}
        assert verification is not None
        verification["receipt_path"] = (
            Path(settings.assets.root) / "receipts" / f"{verification['receipt_sha256']}.json"
        ).as_posix()
    now = _iso()
    index = open_asset_index(paths, settings)
    superseded: dict[str, Any] | None = None
    with index.transaction() as document:
        active = [item for item in document["assets"] if item.get("status") == "active"]
        duplicate = next((item for item in active if item.get("sha256") == content_sha), None)
        if duplicate is not None:
            return {"outcome": "duplicate", "asset_id": duplicate["asset_id"], "errors": []}
        wanted = str(proposal.get("supersedes") or "").strip()
        previous = None
        if wanted:
            previous = next((item for item in active if item.get("asset_id") == wanted
                             and item.get("kind") == kind), None)
        if previous is None:
            previous = next((item for item in active if _similar(item, proposal)), None)
        asset_id = _asset_id(kind, str(proposal["title"]), _digest(content_sha, kind))
        if find_asset(document, asset_id) is not None:
            asset_id = _asset_id(kind, str(proposal["title"]), _digest(content_sha, kind, now))
        relative: str | None = None
        if plan:
            body_rel = Path(settings.assets.root) / kind / asset_id
            target = paths.data / body_rel
            staging = target.parent / f".{asset_id}.partial"
            if staging.exists():
                shutil.rmtree(staging)
            for source, name in plan:
                destination = staging / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            if target.exists():
                shutil.rmtree(target)
            staging.rename(target)
            relative = body_rel.as_posix()
        asset: dict[str, Any] = {name: None for name in ASSET_FIELDS}
        asset.update({
            "asset_id": asset_id,
            "kind": kind,
            "title": str(proposal["title"]).strip(),
            "summary": str(proposal["summary"]).strip(),
            "domains": [str(item).strip() for item in proposal.get("domains") or []],
            "data_sources": [str(item).strip() for item in proposal.get("data_sources") or []],
            "methods": [str(item).strip() for item in proposal.get("methods") or []],
            "path": relative,
            "body": (str(proposal.get("body")).strip() or None) if proposal.get("body") else None,
            "negative": copy.deepcopy(proposal.get("negative")) if kind == "negative_result"
            else None,
            "entrypoint": str(proposal.get("entrypoint") or "").strip() or None,
            "usage": str(proposal.get("usage") or "").strip() or None,
            "requirements": copy.deepcopy(proposal.get("requirements")),
            "origin": dict(origin),
            "sha256": content_sha,
            "files": manifest or None,
            "created_at": now,
            "last_verified_at": now if verification else None,
            "verification": verification,
            "use_count": 0,
            "used_by": [],
            "broken_reports": [],
            "broken_streak": 0,
            "status": "active",
            "superseded_by": None,
            "supersedes": None,
            "version": 1,
        })
        if previous is not None:
            asset["supersedes"] = previous["asset_id"]
            asset["version"] = int(previous.get("version") or 1) + 1
            asset["use_count"] = int(previous.get("use_count") or 0)
            asset["used_by"] = list(previous.get("used_by") or [])
            asset["last_used_at"] = previous.get("last_used_at")
            previous["superseded_by"] = asset_id
            _archive(previous, paths, settings, "superseded")
            superseded = copy.deepcopy(previous)
        document["assets"].append(asset)
    _event(db, asset_id, "asset_registered",
           {"kind": kind, "title": asset["title"], "sha256": content_sha, "origin": dict(origin),
            "decided_by": decided_by, "supersedes": asset["supersedes"]},
           f"registered:{asset_id}")
    if superseded is not None:
        _event(db, superseded["asset_id"], "asset_superseded",
               {"superseded_by": asset_id, "decided_by": decided_by},
               f"superseded:{superseded['asset_id']}")
    return {"outcome": "new_version" if superseded else "registered", "asset_id": asset_id,
            "errors": [], "supersedes": superseded["asset_id"] if superseded else None}


# --------------------------------------------------------------------------- views


def summary_line(asset: Mapping[str, Any]) -> dict[str, Any]:
    return {name: asset.get(name) for name in SUMMARY_FIELDS}


def summary_view(
    document: Mapping[str, Any],
    settings: FactorySettings,
    *,
    domains: Iterable[str] = (),
    data_sources: Iterable[str] = (),
    limit: int | None = None,
    max_chars: int | None = None,
) -> dict[str, Any]:
    """Active assets, one line each, most relevant to the domains/data sources first."""

    wanted_domains = _norm_set(domains)
    wanted_sources = _keys(data_sources)
    active = [asset for asset in document.get("assets") or [] if asset.get("status") == "active"]

    def score(asset: Mapping[str, Any]) -> int:
        domain_hit = bool(_norm_set(asset.get("domains") or []) & wanted_domains)
        overlap = len(_keys(asset.get("data_sources") or []) & wanted_sources)
        return 3 * overlap + 2 * int(domain_hit)

    ranked = sorted(active, key=lambda item: str(item.get("asset_id")))
    ranked.sort(key=lambda item: str(item.get("last_verified_at") or ""), reverse=True)
    ranked.sort(key=lambda item: int(item.get("use_count") or 0), reverse=True)
    ranked.sort(key=score, reverse=True)
    cap = settings.assets.summary_limit if limit is None else limit
    budget = settings.assets.summary_max_chars if max_chars is None else max_chars
    lines: list[dict[str, Any]] = []
    used = 0
    for asset in ranked[: max(0, cap)]:
        line = summary_line(asset)
        size = len(json.dumps(line, ensure_ascii=False, sort_keys=True))
        if lines and used + size > budget:
            break
        lines.append(line)
        used += size
    return {
        "active_assets": len(active),
        "shown": len(lines),
        "truncated": len(lines) < len(active),
        "ranked_for": {"domains": sorted(wanted_domains), "data_sources": sorted(wanted_sources)},
        "assets": lines,
    }


def _card(topic: Mapping[str, Any] | None) -> dict[str, Any]:
    path = Path(str((topic or {}).get("card_path") or ""))
    if not path.is_file():
        return {}
    try:
        return _read_object(path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {}


def card_asset_ids(card: Mapping[str, Any]) -> list[str]:
    ids: list[str] = []
    for item in card.get("reusable_assets") or [] if isinstance(card, Mapping) else []:
        value = item.get("asset_id") if isinstance(item, Mapping) else item
        text = str(value or "").strip()
        if text and text not in ids:
            ids.append(text)
    return ids


def packet_fields(
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    domains: Iterable[str] = (),
    data_sources: Iterable[str] = (),
    topic: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """``{"reusable_assets_summary": view}`` for a control packet; ``{}`` when disabled."""

    if not _enabled(settings):
        return {}
    sources = list(data_sources)
    if topic is not None:
        sources.extend(data_source_identifiers(_card(topic).get("data_sources")))
    try:
        document = open_asset_index(paths, settings).read()
    except (OSError, AssetIndexError) as exc:
        return {"reusable_assets_summary": {"error": str(exc), "assets": []}}
    view = summary_view(document, settings, domains=domains, data_sources=sources)
    view["index_path"] = str(index_path(paths, settings))
    return {"reusable_assets_summary": view}


def card_reference_errors(paths: WorkspacePaths, settings: FactorySettings,
                          card: Mapping[str, Any]) -> list[str]:
    """Admission check: every ``reusable_assets`` entry names an active indexed asset."""

    if not _enabled(settings):
        return []
    ids = card_asset_ids(card)
    if not ids:
        return []
    try:
        document = open_asset_index(paths, settings).read()
    except (OSError, AssetIndexError) as exc:
        return [f"reusable_assets cannot be checked: {exc}"]
    errors: list[str] = []
    for asset_id in ids:
        asset = find_asset(document, asset_id)
        if asset is None:
            errors.append(f"reusable_assets: {asset_id!r} is not in the reusable-asset index")
        elif asset.get("status") != "active":
            successor = asset.get("superseded_by")
            errors.append(
                f"reusable_assets: {asset_id!r} is archived"
                + (f" (superseded by {successor!r})" if successor else "")
            )
    return errors


def annotate_admission_entries(paths: WorkspacePaths, settings: FactorySettings,
                               entries: list[dict[str, Any]]) -> None:
    """Add ``asset_reuse`` to each admission entry: what existing assets the card relies on."""

    if not _enabled(settings):
        return
    try:
        document = open_asset_index(paths, settings).read()
    except (OSError, AssetIndexError):
        return
    for entry in entries:
        card = entry.get("card") if isinstance(entry.get("card"), Mapping) else {}
        referenced = []
        for asset_id in card_asset_ids(card):
            asset = find_asset(document, asset_id)
            referenced.append({**summary_line(asset), "status": asset.get("status")}
                              if asset else {"asset_id": asset_id, "status": "unknown"})
        entry["asset_reuse"] = {
            "referenced": referenced,
            "reuses_pipeline_or_data_loader": any(
                item.get("status") == "active" and item.get("kind") in {"pipeline", "data_loader"}
                for item in referenced
            ),
        }


def research_read_resources(
    paths: WorkspacePaths,
    settings: FactorySettings,
    task: Mapping[str, Any],
    campaign: Mapping[str, Any] | None,
) -> list[dict[str, str]]:
    """Read resources for a research task of a program topic: summary + referenced bodies."""

    if not _enabled(settings) or str(task.get("agent_role") or "") not in RESEARCH_ROLES:
        return []
    try:
        return _research_read_resources(paths, settings, task)
    except (OSError, AssetIndexError, TypeError, ValueError, json.JSONDecodeError):
        # Advisory input: a broken index never blocks a research launch.
        return []


def _research_read_resources(paths: WorkspacePaths, settings: FactorySettings,
                             task: Mapping[str, Any]) -> list[dict[str, str]]:
    campaign_id = str(task.get("campaign_id") or "")
    topic = topic_for_campaign(open_topic_ledger(paths, settings.program).read(), campaign_id)
    if topic is None:
        return []
    card = _card(topic)
    document = open_asset_index(paths, settings).read()
    view = summary_view(
        document, settings, domains=[str(topic.get("domain") or task.get("domain") or "")],
        data_sources=data_source_identifiers(card.get("data_sources")),
    )
    referenced: list[dict[str, Any]] = []
    resources: list[dict[str, str]] = []
    for asset_id in card_asset_ids(card):
        asset = find_asset(document, asset_id)
        if asset is None:
            continue
        body = paths.data / str(asset.get("path") or "") if asset.get("path") else None
        referenced.append({**summary_line(asset), "status": asset.get("status"),
                           "entrypoint": asset.get("entrypoint"), "usage": asset.get("usage"),
                           "path": str(body) if body is not None else None})
        if asset.get("status") == "active" and body is not None and body.exists():
            resources.append({"label": f"reusable-asset:{asset_id}", "path": str(body.resolve())})
    content = {
        "schema_version": "openlabs.reusable_assets_view.v1",
        "topic_id": topic["topic_id"],
        "note": "Read-only. Declare what you use in assets_used[]; report a broken one in "
                "assets_broken[] ({asset_id, reason}).",
        "referenced_by_card": referenced,
        "reusable_assets_summary": view,
    }
    digest = hashlib.sha256(canonical_json_bytes(content)).hexdigest()
    view_path = (paths.artifacts / "program-control" / "asset-views"
                 / f"{_token(str(topic['topic_id']))}-{digest[:16]}.json")
    if not view_path.is_file():
        atomic_write_json(view_path, content)
    return [{"label": "reusable-asset-summary", "path": str(view_path.resolve())}, *resources]


# --------------------------------------------------------------------------- usage


def _ids(value: Any) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for item in value if isinstance(value, list) else []:
        asset_id = item.get("asset_id") if isinstance(item, Mapping) else item
        reason = item.get("reason") if isinstance(item, Mapping) else ""
        text = str(asset_id or "").strip()
        if text and text not in {entry[0] for entry in result}:
            result.append((text, str(reason or "").strip()[:500]))
    return result


def record_result_usage(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: Any,
    *,
    task: Mapping[str, Any],
    attempt_id: str,
    payload: Mapping[str, Any],
    successful: bool,
) -> dict[str, Any] | None:
    """Count ``assets_used`` and ``assets_broken`` of one ingested result (idempotent)."""

    if not _enabled(settings):
        return None
    used = _ids(payload.get("assets_used"))
    broken = _ids(payload.get("assets_broken"))
    if not used and not broken:
        return None
    task_id = str(task.get("task_id") or "")
    key = f"{task_id}:{attempt_id}"
    if db.meta_get(USAGE_META_PREFIX + key):
        return None
    campaign_id = str(task.get("campaign_id") or "")
    topic = topic_for_campaign(open_topic_ledger(paths, settings.program).read(), campaign_id)
    user = str(topic["topic_id"]) if topic else f"campaign:{campaign_id}"
    broken_ids = {asset_id for asset_id, _ in broken}
    now = _iso()
    outcome: dict[str, Any] = {"task_id": task_id, "used": [], "broken": [], "archived": [],
                               "unknown": []}
    threshold = settings.assets.broken_reports_to_archive
    with open_asset_index(paths, settings).transaction() as document:
        for asset_id, _ in used:
            if asset_id in broken_ids:
                continue
            asset = find_asset(document, asset_id)
            if asset is None:
                outcome["unknown"].append(asset_id)
                continue
            asset["use_count"] = int(asset.get("use_count") or 0) + 1
            users = list(asset.get("used_by") or [])
            if user not in users:
                users.append(user)
            asset["used_by"] = users
            asset["last_used_at"] = now
            if successful:
                asset["last_verified_at"] = now
                asset["broken_streak"] = 0
                verification = dict(asset.get("verification") or {})
                if verification.get("status") == "needs_verification":
                    verification["status"] = "passed"
                verification["last_successful_use"] = task_id
                asset["verification"] = verification
            outcome["used"].append(asset_id)
        for asset_id, reason in broken:
            asset = find_asset(document, asset_id)
            if asset is None:
                outcome["unknown"].append(asset_id)
                continue
            reports = list(asset.get("broken_reports") or [])
            reports.append({"task_id": task_id, "topic_id": user, "reason": reason, "at": now})
            asset["broken_reports"] = reports[-MAX_BROKEN_REPORTS_KEPT:]
            asset["broken_streak"] = int(asset.get("broken_streak") or 0) + 1
            verification = dict(asset.get("verification") or {})
            verification["status"] = "needs_verification"
            asset["verification"] = verification
            outcome["broken"].append(asset_id)
            if asset.get("status") == "active" and asset["broken_streak"] >= threshold:
                _archive(asset, paths, settings, "reported_broken")
                outcome["archived"].append(asset_id)
    db.update_meta({USAGE_META_PREFIX + key: now})
    for asset_id in outcome["used"]:
        _event(db, asset_id, "asset_used", {"task_id": task_id, "topic_id": user,
                                            "successful": successful}, f"used:{key}:{asset_id}")
    for asset_id, reason in broken:
        if asset_id in outcome["broken"]:
            _event(db, asset_id, "asset_reported_broken",
                   {"task_id": task_id, "topic_id": user, "reason": reason},
                   f"broken:{key}:{asset_id}")
    for asset_id in outcome["archived"]:
        _event(db, asset_id, "asset_archived", {"reason": "reported_broken",
                                                "decided_by": task_id}, f"archived:{asset_id}")
    report.program.setdefault("assets", {}).setdefault("usage", []).append(outcome)
    return outcome


# --------------------------------------------------------------------------- maintenance


def maintain(db: FactoryDB | None, paths: WorkspacePaths, settings: FactorySettings,
             *, now: datetime | None = None) -> list[dict[str, str]]:
    """Apply the archive rules once; return ``[{asset_id, reason}]``."""

    moment = now or _now()
    unused_before = _iso(moment - timedelta(days=settings.assets.unused_archive_days))
    archived: list[dict[str, str]] = []
    with open_asset_index(paths, settings).transaction() as document:
        for asset in document["assets"]:
            if asset.get("status") != "active":
                continue
            reason = ""
            if int(asset.get("broken_streak") or 0) >= settings.assets.broken_reports_to_archive:
                reason = "reported_broken"
            elif (
                asset.get("kind") in TOOL_ASSET_KINDS
                and int(asset.get("use_count") or 0) == 0
                and str(asset.get("created_at") or "") < unused_before
            ):
                reason = "unused"
            if reason:
                _archive(asset, paths, settings, reason)
                archived.append({"asset_id": str(asset["asset_id"]), "reason": reason})
        lessons = [asset for asset in document["assets"]
                   if asset.get("kind") == "lesson" and asset.get("status") == "active"]
        excess = len(lessons) - settings.assets.max_lessons
        if excess > 0:
            lessons.sort(key=lambda item: (str(item.get("last_used_at") or item.get("created_at")
                                               or ""), str(item.get("asset_id"))))
            for asset in lessons[:excess]:
                _archive(asset, paths, settings, "lesson_cap")
                archived.append({"asset_id": str(asset["asset_id"]), "reason": "lesson_cap"})
    for item in archived:
        _event(db, item["asset_id"], "asset_archived",
               {"reason": item["reason"], "decided_by": "orchestrator:asset_maintenance"},
               f"archived:{item['asset_id']}")
    return archived


def _maybe_maintain(db: FactoryDB, paths: WorkspacePaths, settings: FactorySettings,
                    info: dict[str, Any]) -> None:
    moment = _now()
    last = budget_control.parse_time(db.meta_get(MAINTENANCE_KEY))
    if last is not None and moment - last < timedelta(
        hours=settings.assets.maintenance_interval_hours
    ):
        return
    info["archived"] = maintain(db, paths, settings, now=moment)
    db.update_meta({MAINTENANCE_KEY: _iso(moment)})


# --------------------------------------------------------------------------- retrospectives


def topic_workspace(db: FactoryDB, paths: WorkspacePaths, topic: Mapping[str, Any]) -> Path | None:
    campaign_id = str(topic.get("campaign_id") or "")
    if not campaign_id:
        return None
    campaign = db.campaign(campaign_id) or {}
    configured = str(campaign.get("state_path") or "").strip()
    domain = str(campaign.get("domain") or topic.get("domain") or "")
    return (Path(configured).expanduser() if configured
            else paths.data / "workspaces" / domain / campaign_id).resolve()


def _control_campaign(db: FactoryDB, settings: FactorySettings, domain: str) -> str:
    campaign_id = f"{domain}-program-assets"
    campaign = db.campaign(campaign_id)
    if campaign is not None:
        used = float(campaign.get("agent_seconds_used") or 0)
        current = int(campaign.get("max_agent_seconds") or 0)
        status = str(campaign.get("status") or "")
        if status not in {"active", "budget_exhausted"} or (
            status == "active" and used + settings.max_task_wall_seconds + 1 <= current
        ):
            return campaign_id
        budget = max(current, int(used) + settings.max_campaign_agent_seconds)
    else:
        budget = settings.max_campaign_agent_seconds
    db.register_campaign(campaign_id, domain=domain,
                         title=f"{domain} research-program asset retrospectives", priority=0,
                         source="program:asset_retrospectives", max_agent_seconds=budget)
    return campaign_id


def _signed(packet: dict[str, Any]) -> dict[str, Any]:
    packet["content_sha256"] = hashlib.sha256(canonical_json_bytes(packet)).hexdigest()
    return packet


def _campaign_results(db: FactoryDB, campaign_id: str) -> list[dict[str, Any]]:
    with db.connect() as connection:
        rows = connection.execute(
            "SELECT task_id, task_type, agent_role, result_path, result_sha256 FROM tasks "
            "WHERE campaign_id=? AND status='succeeded' AND result_path IS NOT NULL "
            "ORDER BY created_at DESC, rowid DESC LIMIT 40",
            (campaign_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _records(topic: Mapping[str, Any]) -> list[dict[str, str]]:
    seen: dict[str, dict[str, str]] = {}
    for entry in topic.get("history") or []:
        for item in entry.get("evidence") or []:
            if isinstance(item, Mapping) and item.get("path"):
                seen.setdefault(str(item["path"]), {"path": str(item["path"]),
                                                    "sha256": str(item.get("sha256") or ""),
                                                    "recorded_for": str(entry.get("to")
                                                                        or entry.get("kind"))})
    return list(seen.values())


def _schedule_retrospective(db: FactoryDB, paths: WorkspacePaths, settings: FactorySettings,
                            report: Any, *, topic: Mapping[str, Any], state: str,
                            attempt: int) -> str | None:
    topic_id = str(topic["topic_id"])
    domain = str(topic.get("domain") or "")
    if not domain:
        return None
    task_id = f"retrospective:{_digest(topic_id, state, attempt)[:32]}"
    if db.task(task_id) is not None:
        return None
    workspace = topic_workspace(db, paths, topic)
    campaign_id = str(topic.get("campaign_id") or "")
    card = _card(topic)
    document = open_asset_index(paths, settings).read()
    packet = _signed({
        "schema_version": RETROSPECTIVE_PACKET_SCHEMA,
        "topic_id": topic_id,
        "terminal_state": state,
        "attempt": attempt,
        "ledger_entry": {key: topic.get(key) for key in (
            "topic_id", "domain", "question", "status", "target_tier", "campaign_id", "paper_id",
            "admitted_at", "frozen_at", "freeze_reason_class", "reopen_conditions",
            "cost_estimate", "history")},
        "card_path": topic.get("card_path"),
        "data_sources": data_source_identifiers(card.get("data_sources")),
        "campaign_id": campaign_id or None,
        "topic_workspace": str(workspace) if workspace is not None else None,
        "results": _campaign_results(db, campaign_id) if campaign_id else [],
        "decision_records": _records(topic),
        "negative_result_required": state == "frozen",
        "asset_kinds": list(ASSET_KINDS),
        "index_path": str(index_path(paths, settings)),
        "reusable_assets_summary": summary_view(
            document, settings, domains=[domain],
            data_sources=data_source_identifiers(card.get("data_sources")),
        ),
        "created_at": _iso(),
    })
    packet_path = (paths.artifacts / "program-control" / "retrospective-packets"
                   / _token(topic_id) / f"{state}-{attempt}-{task_id.split(':', 1)[1][:16]}.json")
    atomic_write_json(packet_path, packet)
    control = _control_campaign(db, settings, domain)
    db.enqueue_task(
        task_id=task_id,
        campaign_id=control,
        domain=domain,
        task_type=RETROSPECTIVE_TASK_TYPE,
        objective=(
            f"Retrospective of research-program topic {topic_id} ({state}). Read the packet at "
            "the input path. Return `asset_proposals` in the result bundle: scripts, pipelines "
            "and short lessons that would save the next topic time, each with a one-line "
            "summary; tool assets need source_paths in the topic workspace (or "
            "artifact:<id> of this result) and a minimal verification command you ran, with "
            "its output saved as a JSON receipt {command, exit_code, output_tail} added as a "
            "hash-bound artifact."
            + (" The topic was frozen: include at least one negative_result (question, what "
               "was attempted, why it did not work, retry_when conditions)."
               if state == "frozen" else "")
            + " An empty list is a valid outcome. Do not modify the topic workspace."
        ),
        input_path=str(packet_path),
        skill_path=RETROSPECTIVE_SKILL,
        runner="cheap",
        routing_reason=RETROSPECTIVE_ROUTING_REASON,
        agent_role="researcher",
        session_mode="fresh",
        priority=0,
        max_attempts=settings.max_attempts,
        max_wall_seconds=min(3_600, settings.max_task_wall_seconds),
        **default_task_resources(settings).to_dict(),
    )
    record = {"status": "pending", "task_id": task_id, "topic_id": topic_id, "state": state,
              "attempt": attempt, "packet_path": str(packet_path), "scheduled_at": _iso()}
    db.update_meta(
        {RETRO_META_PREFIX + f"{topic_id}:{state}": json.dumps(record, sort_keys=True)},
        events=[("topic", topic_id, "asset_retrospective_scheduled",
                 {"task_id": task_id, "state": state, "attempt": attempt})],
    )
    report.enqueued.append(task_id)
    report.program.setdefault("assets", {}).setdefault("retrospectives_scheduled", []).append(
        {"topic_id": topic_id, "state": state, "task_id": task_id, "attempt": attempt}
    )
    return task_id


def schedule_retrospectives(db: FactoryDB, paths: WorkspacePaths, settings: FactorySettings,
                            report: Any) -> list[str]:
    """One retrospective per topic and terminal state reached after the switch was turned on."""

    since = db.meta_get(RETRO_SINCE_KEY)
    if since is None:
        since = _iso()
        db.update_meta({RETRO_SINCE_KEY: since})
    scheduled: list[str] = []
    done = db.meta_items(RETRO_META_PREFIX)
    for topic in open_topic_ledger(paths, settings.program).read().get("topics") or []:
        for state in TERMINAL_STATES:
            entry = next((item for item in topic.get("history") or []
                          if item.get("to") == state), None)
            if entry is None or str(entry.get("at") or "") < since:
                continue
            if f"{topic['topic_id']}:{state}" in done:
                continue
            task_id = _schedule_retrospective(db, paths, settings, report, topic=topic,
                                              state=state, attempt=1)
            if task_id:
                scheduled.append(task_id)
    return scheduled


def _ledger_negative_result(topic: Mapping[str, Any]) -> dict[str, Any]:
    """Factual fallback when the retrospective returned no usable negative_result."""

    conditions = [
        {"type": str(item.get("type")), "description": str(item.get("description"))}
        for item in topic.get("reopen_conditions") or [] if isinstance(item, Mapping)
    ] or [{"type": "external_result",
           "description": "No reopen condition was recorded when the topic was frozen."}]
    question = str(topic.get("question") or topic["topic_id"])
    reason = str(topic.get("freeze_reason_class") or "unknown")
    return {
        "kind": "negative_result",
        "title": f"Frozen topic: {question}"[:120],
        "summary": f"Topic {topic['topic_id']} was frozen ({reason}); see its ledger entry."[:240],
        "domains": [str(topic.get("domain") or "unknown")],
        "data_sources": data_source_identifiers(_card(topic).get("data_sources")),
        "methods": [],
        "negative": {
            "question": question[:1500],
            "attempted": "The admitted, pre-registered analysis of this topic (see origin).",
            "why_failed": f"Freeze reason class recorded in the topic ledger: {reason}.",
            "retry_when": conditions,
        },
    }


def _register_retrospective(db: FactoryDB, paths: WorkspacePaths, settings: FactorySettings,
                            *, topic: Mapping[str, Any], task: Mapping[str, Any],
                            payload: Mapping[str, Any], result_path: Path,
                            result_sha256: str) -> list[dict[str, Any]]:
    workspace = topic_workspace(db, paths, topic)
    roots = (workspace,) if workspace is not None else ()
    artifacts = _bound_artifacts(payload)
    origin = {"topic_id": topic["topic_id"], "campaign_id": topic.get("campaign_id"),
              "task_id": task["task_id"], "result_path": str(result_path),
              "result_sha256": result_sha256}
    outcomes: list[dict[str, Any]] = []
    proposals = payload.get("asset_proposals")
    for index, proposal in enumerate(proposals if isinstance(proposals, list) else []):
        outcome = register_asset(
            db, paths, settings, proposal, origin=origin, source_roots=roots, base=workspace,
            artifacts=artifacts, decided_by=str(task["task_id"]),
        )
        kind = proposal.get("kind") if isinstance(proposal, Mapping) else None
        outcomes.append({"index": index, "kind": kind, **outcome})
    return outcomes


def register_retrospectives(db: FactoryDB, paths: WorkspacePaths, settings: FactorySettings,
                            report: Any) -> None:
    """Register finished retrospectives; retry once, then fall back for frozen topics."""

    ledger = open_topic_ledger(paths, settings.program).read()
    info = report.program.setdefault("assets", {})
    for key, raw in sorted(db.meta_items(RETRO_META_PREFIX).items()):
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict) or record.get("status") != "pending":
            continue
        task = db.task(str(record.get("task_id")))
        if task is None or str(task.get("status")) in IN_FLIGHT:
            continue
        topic = next((item for item in ledger.get("topics") or []
                      if item.get("topic_id") == record.get("topic_id")), None)
        if topic is None:
            continue
        state = str(record.get("state"))
        attempt = int(record.get("attempt") or 1)
        status = str(task.get("status"))
        outcomes: list[dict[str, Any]] = []
        problem = ""
        if status == "succeeded":
            result_path = Path(str(task.get("result_path") or ""))
            expected = str(task.get("result_sha256") or "")
            if not result_path.is_file() or not expected or sha256_file(result_path) != expected:
                problem = "result_not_hash_bound"
            else:
                outcomes = _register_retrospective(
                    db, paths, settings, topic=topic, task=task,
                    payload=_read_object(result_path), result_path=result_path,
                    result_sha256=expected,
                )
                if state == "frozen" and not any(
                    item.get("kind") == "negative_result"
                    and item.get("outcome") in {"registered", "new_version", "duplicate"}
                    for item in outcomes
                ):
                    problem = "negative_result_missing"
        elif status in FAILED_STATUSES:
            problem = f"task_{status}"
        else:
            continue
        resolved = {**record, "status": "resolved", "outcome": problem or "registered",
                    "proposals": outcomes, "resolved_at": _iso()}
        db.update_meta({RETRO_META_PREFIX + key: json.dumps(resolved, sort_keys=True)},
                       events=[("topic", str(topic["topic_id"]), "asset_retrospective_registered",
                                {"task_id": task["task_id"], "state": state,
                                 "outcome": problem or "registered", "proposals": outcomes})])
        info.setdefault("retrospectives_registered", []).append(
            {"topic_id": topic["topic_id"], "state": state, "task_id": task["task_id"],
             "outcome": problem or "registered", "proposals": outcomes})
        if not problem:
            continue
        if attempt < MAX_RETROSPECTIVE_ATTEMPTS:
            _schedule_retrospective(db, paths, settings, report, topic=topic, state=state,
                                    attempt=attempt + 1)
        elif state == "frozen":
            fallback = register_asset(
                db, paths, settings, _ledger_negative_result(topic),
                origin={"topic_id": topic["topic_id"], "campaign_id": topic.get("campaign_id"),
                        "generated_from": "topic_ledger", "task_id": task["task_id"]},
                source_roots=(), base=None, artifacts={}, decided_by="orchestrator:retrospective",
            )
            info.setdefault("retrospective_fallbacks", []).append(
                {"topic_id": topic["topic_id"], **fallback})


# --------------------------------------------------------------------------- tick


def run_assets_tick(db: FactoryDB, paths: WorkspacePaths, settings: FactorySettings,
                    report: Any) -> None:
    """Retrospective scheduling/registration and periodic archiving. Disabled: no-op."""

    if not (_enabled(settings) or _retro_enabled(settings)):
        return
    info = report.program.setdefault("assets", {})
    try:
        if _retro_enabled(settings):
            register_retrospectives(db, paths, settings, report)
            schedule_retrospectives(db, paths, settings, report)
        if _enabled(settings):
            _maybe_maintain(db, paths, settings, info)
    except (OSError, AssetIndexError, KeyError, TypeError, ValueError,
            json.JSONDecodeError) as exc:
        report.errors.append(f"reusable assets: {exc}")
        info["error"] = str(exc)


# --------------------------------------------------------------------------- reuse vs cost


TOKEN_KEYS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")


def reuse_cost_comparison(db: FactoryDB, paths: WorkspacePaths,
                          settings: FactorySettings) -> dict[str, Any]:
    """Tasks, tokens and Agent time of topics that reused assets vs topics that did not.

    A topic counts as reusing when its card referenced an indexed asset or a
    result of its campaign declared one in ``assets_used``.
    """

    ledger = open_topic_ledger(paths, settings.program).read()
    try:
        document = open_asset_index(paths, settings).read()
    except AssetIndexError:
        document = empty_index()
    users: dict[str, set[str]] = {}
    for asset in document.get("assets") or []:
        for user in asset.get("used_by") or []:
            users.setdefault(str(user), set()).add(str(asset["asset_id"]))
    with db.connect() as connection:
        rows = connection.execute(
            "SELECT tasks.campaign_id, tasks.task_id, task_attempts.run_seconds, "
            "task_attempts.runtime_json, task_attempts.status FROM task_attempts "
            "JOIN tasks USING(task_id) WHERE task_attempts.finished_at IS NOT NULL"
        ).fetchall()
    per_campaign: dict[str, dict[str, Any]] = {}
    for row in rows:
        stats = per_campaign.setdefault(str(row["campaign_id"]), {
            "tasks": set(), "attempts": 0, "run_seconds": 0.0,
            **{name: 0 for name in TOKEN_KEYS}})
        if str(row["status"]) == "quota_deferred":
            continue
        stats["tasks"].add(str(row["task_id"]))
        stats["attempts"] += 1
        stats["run_seconds"] += float(row["run_seconds"] or 0.0)
        try:
            runtime = json.loads(str(row["runtime_json"] or "{}"))
        except json.JSONDecodeError:
            runtime = {}
        for name in TOKEN_KEYS:
            value = runtime.get(name) if isinstance(runtime, dict) else None
            if isinstance(value, int) and not isinstance(value, bool):
                stats[name] += value
    groups = {flag: {"topics": 0, "tasks": 0, "attempts": 0, "run_seconds": 0.0,
                     **{name: 0 for name in TOKEN_KEYS}} for flag in ("with_assets",
                                                                       "without_assets")}
    topics: list[dict[str, Any]] = []
    for topic in ledger.get("topics") or []:
        campaign_id = str(topic.get("campaign_id") or "")
        if not campaign_id:
            continue
        referenced = set(card_asset_ids(_card(topic))) | users.get(str(topic["topic_id"]), set())
        flag = "with_assets" if referenced else "without_assets"
        stats = per_campaign.get(campaign_id, {"tasks": set(), "attempts": 0, "run_seconds": 0.0,
                                               **{name: 0 for name in TOKEN_KEYS}})
        group = groups[flag]
        group["topics"] += 1
        group["tasks"] += len(stats["tasks"])
        group["attempts"] += stats["attempts"]
        group["run_seconds"] += stats["run_seconds"]
        for name in TOKEN_KEYS:
            group[name] += stats[name]
        topics.append({"topic_id": topic["topic_id"], "status": topic.get("status"),
                       "campaign_id": campaign_id, "group": flag, "assets": sorted(referenced),
                       "tasks": len(stats["tasks"]), "run_seconds": stats["run_seconds"],
                       "tokens": sum(stats[name] for name in TOKEN_KEYS)})
    for group in groups.values():
        count = group["topics"]
        group["tokens"] = sum(group[name] for name in TOKEN_KEYS)
        group["mean_tasks_per_topic"] = group["tasks"] / count if count else None
        group["mean_run_seconds_per_topic"] = group["run_seconds"] / count if count else None
        group["mean_tokens_per_topic"] = group["tokens"] / count if count else None
    return {"schema_version": "openlabs.asset_reuse_cost.v1", **groups, "topics": topics}


# --------------------------------------------------------------------------- operator commands


def _first_doc_line(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    if path.suffix == ".py":
        try:
            doc = ast.get_docstring(ast.parse(text))
        except (SyntaxError, ValueError):
            doc = None
        return (doc or "").strip().splitlines()[0].strip() if doc and doc.strip() else ""
    for line in text.splitlines()[:15]:
        stripped = line.strip()
        if stripped.startswith("#") and not stripped.startswith("#!"):
            comment = stripped.lstrip("#").strip()
            if comment:
                return comment
    return ""


def _standalone(path: Path) -> bool:
    if path.suffix != ".py":
        return True
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return "__name__" in text and "__main__" in text


def _guess_kind(name: str) -> str:
    lowered = name.casefold()
    if any(word in lowered for word in ("intake", "loader", "download", "dataset", "fetch")):
        return "data_loader"
    if any(word in lowered for word in ("plot", "figure", "chart")):
        return "figure"
    if any(word in lowered for word in ("pipeline", "runner", "workflow")):
        return "pipeline"
    return "analysis"


def _lab_domain(code: Path, path: Path) -> str | None:
    relative = path.relative_to(code)
    if relative.parts[:1] == ("labs",) and len(relative.parts) > 1:
        manifest = code / "labs" / relative.parts[1] / "lab.json"
        try:
            return str(_read_object(manifest).get("domain") or relative.parts[1])
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return relative.parts[1]
    return None


def seed_candidates(paths: WorkspacePaths, settings: FactorySettings) -> dict[str, Any]:
    """Read-only scan of existing code for standalone tools; returns registration drafts."""

    code = paths.code.resolve()
    found: dict[Path, None] = {}
    for pattern in settings.assets.seed_paths:
        for root in sorted(code.glob(pattern)):
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                parts = set(path.relative_to(code).parts)
                if (path.suffix not in SEED_SUFFIXES or not path.is_file() or path.is_symlink()
                        or parts & SKIPPED_PARTS or "tests" in parts or path.name.startswith("_")
                        or path.name.startswith("test_")):
                    continue
                if _standalone(path):
                    found[path] = None
    drafts: list[dict[str, Any]] = []
    for path in found:
        relative = path.relative_to(code).as_posix()
        runner = {".py": "python", ".sh": "bash"}.get(path.suffix, "Rscript")
        domain = _lab_domain(code, path)
        drafts.append({
            "kind": _guess_kind(path.stem),
            "title": path.stem.replace("_", " "),
            "summary": _first_doc_line(path) or f"{path.name} (no docstring; describe it)",
            "domains": [domain] if domain else [],
            "data_sources": [],
            "methods": [],
            "source_paths": [relative],
            "entrypoint": f"{runner} {relative}",
            "usage": f"{runner} {relative} --help",
            "requirements": None,
            "verification": {"command": f"{runner} {relative} --help",
                             "receipt": {"path": "", "sha256": ""}},
        })
    return {"schema_version": "openlabs.asset_seed.v1", "dry_run": True,
            "scanned": list(settings.assets.seed_paths), "candidates": len(drafts),
            "note": "Nothing was registered. Edit a draft (kind, summary, domains, data_sources, "
                    "a minimal verification command and its JSON receipt {command, exit_code}), "
                    "then run `program assets register <draft>`.",
            "asset_proposals": drafts}


def register_draft(db: FactoryDB | None, paths: WorkspacePaths, settings: FactorySettings,
                   draft_path: Path, *, by: str) -> dict[str, Any]:
    """Register an operator-confirmed draft (one proposal, a list, or ``asset_proposals``)."""

    raw = json.loads(draft_path.read_text(encoding="utf-8"))
    if isinstance(raw, Mapping) and isinstance(raw.get("asset_proposals"), list):
        proposals = list(raw["asset_proposals"])
    elif isinstance(raw, list):
        proposals = raw
    else:
        proposals = [raw]
    origin = {"registered_by": f"manual:{by}", "draft_path": str(draft_path.resolve()),
              "draft_sha256": sha256_file(draft_path)}
    outcomes = [
        {"index": index, **register_asset(
            db, paths, settings, proposal, origin=origin,
            source_roots=(paths.code.resolve(), paths.data.resolve()), base=paths.code,
            artifacts=None, decided_by=f"manual:{by}",
        )}
        for index, proposal in enumerate(proposals)
    ]
    return {"schema_version": "openlabs.asset_registration.v1", "outcomes": outcomes}


def list_assets(paths: WorkspacePaths, settings: FactorySettings, *,
                include_archived: bool = False) -> dict[str, Any]:
    document = open_asset_index(paths, settings).read()
    rows = [
        {**summary_line(asset), "status": asset.get("status")}
        for asset in document.get("assets") or []
        if include_archived or asset.get("status") == "active"
    ]
    return {"schema_version": "openlabs.asset_list.v1", "index_path": str(index_path(paths,
                                                                                    settings)),
            "assets": rows}


def show_asset(paths: WorkspacePaths, settings: FactorySettings, asset_id: str) -> dict[str, Any]:
    asset = find_asset(open_asset_index(paths, settings).read(), asset_id)
    if asset is None:
        raise AssetIndexError(f"unknown asset {asset_id}")
    return dict(asset)
