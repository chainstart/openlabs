"""Audited, version-scoped exceptions to the revision-round budget only.

These records preserve a human authorization; they cannot authenticate a human.
Creating one without that authorization remains prohibited. Neither an exception
nor its authorization is a review, a scientific waiver, or permission to publish.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from paper_writing.identifiers import PAPER_ID_PATTERN


EXCEPTION_FIELD = "quality_gate_revision_exception"
EXCEPTION_SCHEMA = "ara.paper_writing.revision_round_exception.v1"
AUTHORIZATION_SCHEMA = "ara.paper_writing.revision_round_authorization.v1"
EXCEPTION_SCOPE = "revision_round_budget_only"
_EXCEPTION_KEYS = {
    "schema_version", "paper_id", "manuscript_version", "active", "scope",
    "maximum_revision_rounds", "authorization",
}
_AUTHORIZATION_KEYS = {
    "actor", "confirmed", "confirmed_at", "source", "quote", "record", "sha256",
}
_RECORD_KEYS = {
    "schema_version", "paper_ids", "scope", "maximum_revision_rounds",
    "actor", "confirmed", "confirmed_at", "source", "quote",
}


def _error(message: str) -> ValueError:
    return ValueError(f"{EXCEPTION_FIELD}: {message}")


def _exact_keys(value: Any, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise _error(f"{label} must contain exactly {', '.join(sorted(keys))}")
    return value


def _positive_integer(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise _error(f"{label} must be a positive integer")
    return value


def revision_round_policy(
    paper_id: str,
    metadata: Mapping[str, Any],
    gate: Mapping[str, Any],
    *,
    root: str | Path,
) -> tuple[int, dict[str, Any] | None]:
    """Return the effective cap and a verified, immutable-ready exception copy.

    Missing or explicitly inactive exceptions never increase the normal budget.
    Active exceptions require exact paper/version scope and a digest-bound local
    authorization record that independently lists the authorized paper IDs.
    """

    baseline = _positive_integer(gate.get("maximum_revision_rounds", 3), "configured cap")
    if EXCEPTION_FIELD not in metadata:
        return baseline, None
    exception = _exact_keys(metadata[EXCEPTION_FIELD], _EXCEPTION_KEYS, "exception")
    if exception.get("schema_version") != EXCEPTION_SCHEMA:
        raise _error("unsupported exception schema")
    if type(exception.get("active")) is not bool:
        raise _error("active must be a boolean")
    if exception["active"] is False:
        return baseline, None
    if exception.get("paper_id") != paper_id or metadata.get("paper_id") != paper_id:
        raise _error("paper_id must match the exact current paper")
    version = exception.get("manuscript_version")
    if (
        not isinstance(version, str)
        or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version)
        or version != metadata.get("version")
    ):
        raise _error("manuscript_version must match the exact current version")
    if exception.get("scope") != EXCEPTION_SCOPE:
        raise _error("only the revision-round budget may be excepted")
    maximum = _positive_integer(exception.get("maximum_revision_rounds"), "exception cap")
    if maximum <= baseline:
        raise _error("exception cap must exceed the configured cap")
    authorization = _exact_keys(
        exception.get("authorization"), _AUTHORIZATION_KEYS, "authorization"
    )
    if authorization.get("actor") != "user" or authorization.get("confirmed") is not True:
        raise _error("explicit confirmed user authorization is required")
    for key in ("source", "quote", "confirmed_at"):
        value = authorization.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 4096:
            raise _error(f"authorization {key} must be a bounded nonempty string")
    try:
        confirmed_at = datetime.fromisoformat(authorization["confirmed_at"])
    except ValueError as exc:
        raise _error("authorization confirmed_at must be an ISO-8601 timestamp") from exc
    if confirmed_at.tzinfo is None or confirmed_at > datetime.now(UTC):
        raise _error("authorization confirmed_at must be timezone-aware and not future-dated")
    record_name = authorization.get("record")
    if not isinstance(record_name, str):
        raise _error("authorization record must be a repository-relative JSON path")
    relative = PurePosixPath(record_name)
    if (
        relative.is_absolute()
        or relative.parts[:2] != ("registry", "quality-gate-exceptions")
        or len(relative.parts) != 3
        or relative.suffix != ".json"
        or record_name != relative.as_posix()
        or ".." in relative.parts
    ):
        raise _error("authorization record must be directly under registry/quality-gate-exceptions")
    repo_root = Path(root).resolve()
    path = repo_root / record_name
    if path.resolve() != path or not path.is_file() or path.stat().st_size > 65536:
        raise _error("authorization record must be an existing bounded, non-symlink file")
    raw = path.read_bytes()
    digest = authorization.get("sha256")
    if not isinstance(digest, str) or hashlib.sha256(raw).hexdigest() != digest:
        raise _error("authorization record SHA256 does not match")
    try:
        record = _exact_keys(json.loads(raw), _RECORD_KEYS, "authorization record")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _error("authorization record must be valid JSON") from exc
    if record.get("schema_version") != AUTHORIZATION_SCHEMA:
        raise _error("unsupported authorization record schema")
    paper_ids = record.get("paper_ids")
    if (
        not isinstance(paper_ids, list)
        or not paper_ids
        or any(not isinstance(item, str) or not PAPER_ID_PATTERN.fullmatch(item) for item in paper_ids)
        or len(set(paper_ids)) != len(paper_ids)
        or paper_id not in paper_ids
    ):
        raise _error("authorization record must explicitly list this paper_id, without wildcards")
    if (
        record.get("scope") != EXCEPTION_SCOPE
        or type(record.get("maximum_revision_rounds")) is not int
        or record["maximum_revision_rounds"] != maximum
        or record.get("confirmed") is not True
        or any(record.get(key) != authorization[key] for key in (
            "actor", "confirmed_at", "source", "quote"
        ))
    ):
        raise _error("authorization record and exception must agree exactly")
    return maximum, deepcopy(dict(exception))


def validate_release_revision_policy(
    paper_id: str,
    metadata: Mapping[str, Any],
    gate: Mapping[str, Any],
    *,
    root: str | Path,
) -> dict[str, Any] | None:
    """Revalidate a release's round cap and authorization before external writes."""

    maximum, exception = revision_round_policy(paper_id, metadata, gate, root=root)
    release = metadata.get("writing_release")
    release = release if isinstance(release, Mapping) else {}
    recorded_exception = release.get(EXCEPTION_FIELD)
    # Old release records did not all store rounds. Keep only that legacy case;
    # any claimed round budget or exception must be complete and revalidated.
    if (
        exception is None
        and recorded_exception is None
        and "revision_rounds_completed" not in release
        and "max_revision_rounds" not in release
    ):
        return None
    rounds = release.get("revision_rounds_completed")
    recorded_maximum = release.get("max_revision_rounds")
    if (
        type(rounds) is not int or rounds < 0 or rounds > maximum
        or type(recorded_maximum) is not int or recorded_maximum != maximum
        or recorded_exception != exception
    ):
        raise _error("release round budget or authorization is stale; rerun quality-gate")
    return exception
