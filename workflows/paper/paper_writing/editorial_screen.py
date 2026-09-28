"""Target-specific editorial screening after the scientific manuscript review."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


SCHEMA = "openlabs.paper_writing.editorial_screen.v1"


def _filled(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _source(value: Any) -> bool:
    return _filled(value) and str(value).startswith(("https://", "http://"))


def editorial_screen_blockers(
    paper_id: str,
    metadata: Mapping[str, Any],
    root: Path,
    snapshot_sha256: str,
) -> tuple[list[str], str | None]:
    """Validate a separate, manuscript-bound editorial screen; never infer acceptance."""

    prefix = "EDITORIAL-SCREEN"
    registration = metadata.get("editorial_screen")
    registration = registration if isinstance(registration, Mapping) else {}
    relative = registration.get("source")
    if not _filled(relative):
        return [f"{prefix}: target-specific editorial screen is missing"], None
    path = (root / str(relative)).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return [f"{prefix}: screen record escapes the data repository"], None
    if not path.is_file():
        return [f"{prefix}: screen record does not exist"], None
    try:
        raw = path.read_bytes()
    except OSError:
        return [f"{prefix}: screen record cannot be read"], None
    digest = hashlib.sha256(raw).hexdigest()
    try:
        item = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return [f"{prefix}: screen record is not valid JSON"], digest
    if not isinstance(item, Mapping):
        return [f"{prefix}: screen record must be an object"], digest

    errors: list[str] = []
    fit = metadata.get("target_journal_fit")
    if not isinstance(fit, Mapping) or fit.get("status") != "approved":
        errors.append(f"{prefix}: current target-journal fit has not been approved")
    if metadata.get("target_journal_ranking_year") != 2025 or metadata.get("target_journal_ranking_scope") != "major_category":
        errors.append(f"{prefix}: current target lacks verified 2025 CAS major-category classification")
    for key, expected in (
        ("schema_version", SCHEMA),
        ("paper_id", paper_id),
        ("manuscript_snapshot_sha256", snapshot_sha256),
        ("target_journal", metadata.get("target_journal")),
    ):
        if not expected or item.get(key) != expected:
            errors.append(f"{prefix}: {key} must match the current paper and target")
    if item.get("decision") != "pass":
        errors.append(f"{prefix}: target-specific contribution is not cleared for editorial screening")
    if item.get("independent_context") is not True:
        errors.append(f"{prefix}: screen must be assessed in an independent context")
    if item.get("prior_rejections_reviewed") is not True:
        errors.append(f"{prefix}: previous editorial decisions must be reviewed")
    if not _filled(item.get("reviewed_at_utc")) or not _filled(item.get("reviewer_model")):
        errors.append(f"{prefix}: reviewer provenance is incomplete")
    for key in ("contribution", "why_target_readers_care", "research_depth", "editorial_risk"):
        if not _filled(item.get(key)):
            errors.append(f"{prefix}: {key} needs a concrete assessment")
    if item.get("required_scientific_work") != []:
        errors.append(f"{prefix}: unresolved scientific work prevents editorial clearance")
    comparisons = item.get("closest_work")
    if not isinstance(comparisons, list) or len(comparisons) < 2 or any(
        not isinstance(row, Mapping)
        or not _source(row.get("source"))
        or not _filled(row.get("known_result"))
        or not _filled(row.get("advance"))
        for row in comparisons
    ) or len({str(row.get("source")) for row in comparisons if isinstance(row, Mapping)}) < 2:
        errors.append(f"{prefix}: compare at least two sourced closest results")
    articles = item.get("target_articles")
    if not isinstance(articles, list) or len(set(map(str, articles))) < 2 or any(
        not _source(source) for source in articles
    ):
        errors.append(f"{prefix}: cite at least two distinct recent target-journal articles")
    responses = item.get("rejection_responses")
    if not isinstance(responses, list) or not responses or any(
        not isinstance(row, Mapping)
        or not _filled(row.get("decision_source"))
        or not _filled(row.get("concern"))
        or not _filled(row.get("current_evidence"))
        or not _filled(row.get("remaining_limit"))
        for row in responses
    ):
        errors.append(f"{prefix}: address editorial-rejection concerns with current evidence")
    else:
        history = metadata.get("journal_rejections")
        history = history if isinstance(history, list) else []
        registered = {
            str(row.get("source")) for row in history
            if isinstance(row, Mapping) and _filled(row.get("source"))
        }
        addressed = {str(row["decision_source"]) for row in responses}
        if registered - addressed:
            errors.append(f"{prefix}: not every registered rejection source was addressed")
    return errors, digest


def require_editorial_screen(
    paper_id: str,
    metadata: Mapping[str, Any],
    root: Path,
    snapshot_sha256: str,
    gate: Mapping[str, Any],
) -> str | None:
    """Fail closed for alternate ready paths that do not use record_quality_gate."""

    if not gate.get("require_target_editorial_screen", False):
        return None
    blockers, digest = editorial_screen_blockers(paper_id, metadata, root, snapshot_sha256)
    if blockers:
        raise ValueError("; ".join(blockers))
    return digest
