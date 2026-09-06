"""Namespaced, audited catalog ingestion; never schedules mathematical research.

Source files own the scientific assertions.  Importing their status is not a
proof review, and no status promotion or task creation happens in this module.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .db import FactoryDB, utc_now

BUNDLE_SCHEMA = "openlabs.math_problem_catalog_bundle.v1"
NAMESPACE = "math-problem-catalog"
RECORD_PREFIX = "math-catalog:"
KINDS = frozenset({
    "math_source", "math_problem", "math_statement", "math_relation",
    "math_progress", "math_snapshot", "math_review",
})
MAX_BUNDLE_BYTES = 128 * 1024 * 1024
ALLOWED_ROOTS = ("registry/math-problems", "workspaces/math/problem-catalog")
_COLUMNS = "record_id, kind, domain, title, status, source_path, metadata_json, created_at, updated_at"
_FIELDS = ("kind", "domain", "title", "status", "source_path", "metadata_json")
_SCALAR_REFERENCES = ("problem_id", "source_record_id", "source_id", "from_id", "to_id")
_LIST_REFERENCES = ("statement_ids", "source_ids")


class CatalogValidationError(ValueError):
    """An import or query violates the catalog's narrow authority boundary."""


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise CatalogValidationError(f"{label} must be a nonempty string without NUL")
    return value


def _identifier(value: Any, label: str) -> str:
    value = _text(value, label)
    if not value.startswith(RECORD_PREFIX) or not value[len(RECORD_PREFIX):] or any(c.isspace() for c in value):
        raise CatalogValidationError(f"{label} must start with {RECORD_PREFIX} and contain no whitespace")
    return value


def _allowed_path(data_root: Path, value: str) -> Path:
    _text(value, "source_path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or "\\" in value or relative.as_posix() != value:
        raise CatalogValidationError(f"catalog path must be canonical and data-relative: {value}")
    if not any(value.startswith(prefix + "/") for prefix in ALLOWED_ROOTS):
        raise CatalogValidationError(f"catalog path is outside allowed roots: {value}")
    root = data_root.resolve()
    target = (root / value).resolve()
    # Compare to the lexical allowed roots: resolving the roots themselves
    # would inadvertently permit a catalog directory symlinked outside data.
    if not any(target.is_relative_to(root / prefix) for prefix in ALLOWED_ROOTS):
        raise CatalogValidationError(f"catalog path escapes allowed roots through a symlink: {value}")
    return target


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CatalogValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise CatalogValidationError(f"nonfinite JSON value: {value}")


def catalog_receipt_path(data_root: Path, value: str | Path) -> Path:
    """Validate a requested receipt destination before any database changes.

    A user-selected existing receipt may be refreshed, but a bundle, source
    registry, or other scientific file must never be replaced by a receipt.
    """
    root = Path(data_root).resolve()
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        relative = candidate.relative_to(root).as_posix()
    except ValueError as exc:
        raise CatalogValidationError("receipt must be inside the data catalog roots") from exc
    target = _allowed_path(root, relative)
    if target.exists():
        if not target.is_file() or target.stat().st_size > MAX_BUNDLE_BYTES:
            raise CatalogValidationError("receipt destination is not an existing bounded receipt file")
        try:
            previous = json.loads(target.read_bytes(), object_pairs_hook=_json_object, parse_constant=_reject_constant)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CatalogValidationError("refusing to overwrite a non-receipt file") from exc
        if not isinstance(previous, dict) or previous.get("schema_version") != "openlabs.math_problem_catalog_receipt.v1" or previous.get("namespace") != NAMESPACE:
            raise CatalogValidationError("refusing to overwrite a non-receipt scientific file")
    return target


def _references(metadata: dict[str, Any]) -> set[str]:
    explicit = metadata.get("record_references", [])
    if not isinstance(explicit, list):
        raise CatalogValidationError("metadata.record_references must be an array")
    references = {_identifier(value, "metadata.record_references item") for value in explicit}
    # URLs, DOI references, source slugs and historic file paths are not IDs.
    for key in _SCALAR_REFERENCES:
        value = metadata.get(key)
        if isinstance(value, str) and value.startswith(RECORD_PREFIX):
            references.add(_identifier(value, f"metadata.{key}"))
    for key in _LIST_REFERENCES:
        values = metadata.get(key, [])
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str) and value.startswith(RECORD_PREFIX):
                    references.add(_identifier(value, f"metadata.{key} item"))
    return references


def load_bundle(bundle: str | Path, *, data_root: Path, expected_sha256: str) -> dict[str, Any]:
    """Read once, hash those exact bytes, and validate all file-owned records."""
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise CatalogValidationError("expected_sha256 must be 64 hexadecimal characters")
    root = Path(data_root).resolve()
    candidate = Path(bundle)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        relative = candidate.relative_to(root).as_posix()
    except ValueError as exc:
        raise CatalogValidationError("bundle must be inside the data catalog roots") from exc
    target = _allowed_path(root, relative)
    if not target.is_file():
        raise CatalogValidationError(f"bundle is not a regular file: {relative}")
    with target.open("rb") as handle:
        raw = handle.read(MAX_BUNDLE_BYTES + 1)
    if len(raw) > MAX_BUNDLE_BYTES:
        raise CatalogValidationError(f"bundle exceeds {MAX_BUNDLE_BYTES} bytes")
    digest = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(digest, expected_sha256.lower()):
        raise CatalogValidationError("bundle SHA256 does not match expected_sha256")
    try:
        payload = json.loads(raw, object_pairs_hook=_json_object, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogValidationError(f"invalid bundle JSON: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != BUNDLE_SCHEMA:
        raise CatalogValidationError(f"bundle schema_version must be {BUNDLE_SCHEMA}")
    if payload.get("namespace") != NAMESPACE:
        raise CatalogValidationError(f"bundle namespace must be {NAMESPACE}")
    generated_at = _text(payload.get("generated_at"), "generated_at")
    try:
        timestamp = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CatalogValidationError("generated_at must be an ISO 8601 timestamp") from exc
    if timestamp.tzinfo is None:
        raise CatalogValidationError("generated_at must include a timezone")
    records = payload.get("records")
    if not isinstance(records, list):
        raise CatalogValidationError("records must be an array")
    seen: set[str] = set()
    normalized = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise CatalogValidationError(f"records[{index}] must be an object")
        record_id = _identifier(record.get("record_id"), "record_id")
        if record_id in seen:
            raise CatalogValidationError(f"duplicate record_id: {record_id}")
        seen.add(record_id)
        if not isinstance(record.get("kind"), str) or record["kind"] not in KINDS or record.get("domain") != "math":
            raise CatalogValidationError(f"{record_id}: unsupported kind or domain")
        item = {key: _text(record.get(key), f"{record_id}.{key}") for key in ("record_id", "kind", "domain", "title", "status", "source_path")}
        _allowed_path(root, item["source_path"])
        metadata = record.get("metadata")
        if not isinstance(metadata, dict):
            raise CatalogValidationError(f"{record_id}: metadata must be an object")
        _references(metadata)
        item["metadata_json"] = json.dumps(metadata, ensure_ascii=False, sort_keys=True, allow_nan=False)
        item["metadata"] = metadata
        normalized.append(item)
    return {"records": normalized, "sha256": digest, "source_path": relative, "generated_at": generated_at}


def _decoded(row: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result["metadata"] = json.loads(result.pop("metadata_json"))
    return result


def _catalog_row(row: Mapping[str, Any], data_root: Path) -> bool:
    if not str(row["record_id"]).startswith(RECORD_PREFIX) or row["kind"] not in KINDS or row["domain"] != "math":
        return False
    try:
        _allowed_path(data_root, row["source_path"])
    except CatalogValidationError:
        return False
    return True


def ingest_bundle(db: FactoryDB, *, data_root: Path, bundle: str | Path, expected_sha256: str) -> dict[str, Any]:
    """Atomically upsert a validated bundle, preserving every overwritten row in events."""
    validated = load_bundle(bundle, data_root=data_root, expected_sha256=expected_sha256)
    if not db.path.is_file():
        raise CatalogValidationError("catalog ingestion requires an existing initialized database")
    records = validated["records"]
    by_id = {item["record_id"]: item for item in records}
    counts = {"inserted": 0, "updated": 0, "unchanged": 0}
    now = utc_now()
    provenance = {key: validated[key] for key in ("sha256", "source_path", "generated_at")}
    with db.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        # One scoped scan avoids SQLite bind limits and N lookups for large bundles.
        existing = {row["record_id"]: dict(row) for row in connection.execute(
            f"SELECT {_COLUMNS} FROM research_records WHERE record_id GLOB ?", (RECORD_PREFIX + "*",)
        )}
        for record in records:
            record_id = record["record_id"]
            prior = existing.get(record_id)
            if prior is not None and (not _catalog_row(prior, data_root) or prior["kind"] != record["kind"]):
                raise CatalogValidationError(f"refusing to overwrite a foreign record or change kind: {record_id}")
            for reference in _references(record["metadata"]):
                if reference not in by_id and (reference not in existing or not _catalog_row(existing[reference], data_root)):
                    raise CatalogValidationError(f"{record_id}: unresolved catalog reference: {reference}")
        # Validation above completes before the first row is modified.
        for record in records:
            record_id = record["record_id"]
            prior = existing.get(record_id)
            if prior is not None and all(prior[key] == record[key] for key in _FIELDS):
                counts["unchanged"] += 1
                continue
            connection.execute(
                """INSERT INTO research_records(
                    record_id, kind, domain, title, status, source_path, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(record_id) DO UPDATE SET
                    title=excluded.title, status=excluded.status, source_path=excluded.source_path,
                    metadata_json=excluded.metadata_json, updated_at=excluded.updated_at""",
                (record_id, *(record[key] for key in _FIELDS), now, now),
            )
            action = "inserted" if prior is None else "updated"
            counts[action] += 1
            db._event(connection, record["kind"], record_id, f"math_catalog_record_{action}", {
                "bundle": provenance,
                "previous": _decoded(prior) if prior is not None else None,
                "current": {key: record[key] for key in ("record_id", "kind", "domain", "title", "status", "source_path", "metadata")},
            })
        receipt = {
            "schema_version": "openlabs.math_problem_catalog_receipt.v1",
            "namespace": NAMESPACE, "imported_at": now, "bundle": provenance,
            "counts": counts, "record_count": len(records), "record_ids": list(by_id),
        }
        db._event(connection, "math_catalog", validated["sha256"], "math_catalog_ingested", receipt)
    return receipt


def parse_metadata_filters(values: list[str] | None) -> dict[str, Any]:
    """Parse repeated KEY=JSON expressions; strings may be written unquoted."""
    result = {}
    for expression in values or []:
        key, separator, value = expression.partition("=")
        if not separator or not key or any(not part for part in key.split(".")):
            raise CatalogValidationError("metadata filters must be KEY=JSON with a nonempty dot path")
        if key in result:
            raise CatalogValidationError(f"duplicate metadata filter: {key}")
        try:
            result[key] = json.loads(value, parse_constant=_reject_constant)
        except json.JSONDecodeError:
            result[key] = value
    return result


def _matches(metadata: Any, filters: Mapping[str, Any]) -> bool:
    for key, expected in filters.items():
        value = metadata
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return False
            value = value[part]
        # Keep JSON true distinct from 1 (Python otherwise equates the two).
        if json.dumps(value, sort_keys=True) != json.dumps(expected, sort_keys=True):
            return False
    return True


def _rows(db: FactoryDB, *, kind: str | None = None, status: str | None = None,
          record_id: str | None = None, metadata_filters: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    if kind is not None and kind not in KINDS:
        raise CatalogValidationError(f"unsupported catalog kind: {kind}")
    if record_id is not None:
        _identifier(record_id, "record_id")
    if not db.path.is_file():
        raise CatalogValidationError("catalog queries require an existing initialized database")
    clauses = ["record_id GLOB ?", "domain='math'", "kind IN (" + ",".join("?" for _ in KINDS) + ")"]
    params = [RECORD_PREFIX + "*", *sorted(KINDS)]
    for column, value in (("kind", kind), ("status", status), ("record_id", record_id)):
        if value is not None:
            clauses.append(f"{column}=?")
            params.append(value)
    # mode=ro cannot accidentally bootstrap an empty runtime database.
    connection = sqlite3.connect(db.path.as_uri() + "?mode=ro", uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(f"SELECT {_COLUMNS} FROM research_records WHERE " + " AND ".join(clauses) + " ORDER BY kind, record_id", params)
        return [item for row in rows if _matches((item := _decoded(row))["metadata"], metadata_filters or {})]
    finally:
        connection.close()


def show_catalog(db: FactoryDB, *, limit: int = 100, offset: int = 0, **filters: Any) -> dict[str, Any]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10_000:
        raise CatalogValidationError("limit must be between 1 and 10000")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise CatalogValidationError("offset must be a nonnegative integer")
    rows = _rows(db, **filters)
    return {"namespace": NAMESPACE, "total": len(rows), "offset": offset, "limit": limit, "records": rows[offset:offset + limit]}


def catalog_stats(db: FactoryDB, **filters: Any) -> dict[str, Any]:
    rows = _rows(db, **filters)
    by_kind: dict[str, dict[str, int]] = {}
    for row in rows:
        statuses = by_kind.setdefault(row["kind"], {})
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1
    return {"namespace": NAMESPACE, "total": len(rows),
            "by_kind": dict(sorted(Counter(row["kind"] for row in rows).items())),
            "by_status": dict(sorted(Counter(row["status"] for row in rows).items())),
            "by_kind_status": by_kind}
