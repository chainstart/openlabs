"""Stable and human-readable identifiers for writing workspaces."""

from __future__ import annotations

import re
from datetime import date


LEGACY_PAPER_ID_PATTERN = re.compile(r"^[0-9]{8}[a-z]+[0-9]{4}$")
# Compatibility pattern for immutable v2 IDs in the former
# YYYYMMDD-source-goal form. New workspaces must use the domain-scoped pattern
# below, but already-created identifiers remain valid forever.
DESCRIPTIVE_PAPER_ID_PATTERN = re.compile(
    r"^(?=.{12,80}$)[0-9]{8}-[a-z0-9]+(?:-[a-z0-9]+){1,6}$"
)
DOMAIN_SCOPED_PAPER_ID_PATTERN = re.compile(
    r"^(?=.{16,80}$)(?P<date>[0-9]{8})-"
    r"(?P<domain>[a-z][a-z0-9]*)-"
    r"(?P<subdomain>[a-z][a-z0-9]*)-"
    r"(?P<keywords>[a-z0-9]+(?:-[a-z0-9]+){0,4})$"
)
PAPER_ID_PATTERN = re.compile(
    r"^(?:[0-9]{8}[a-z]+[0-9]{4}|(?=.{12,80}$)[0-9]{8}-[a-z0-9]+(?:-[a-z0-9]+){1,6})$"
)
WORK_ID_PATTERN = re.compile(r"^(?=.{3,71}$)[a-z0-9]+(?:-[a-z0-9]+){1,6}$")
SEMANTIC_VERSION_PATTERN = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$"
)

# Repository-local research labels belong in provenance metadata, never in a new
# paper ID or public display ID. Recognised external catalogue namespaces such as
# ``erdos-866`` and ``opg1757`` are intentionally not included here.
_INTERNAL_TRACKING_PREFIXES = {
    "campaign",
    "issue",
    "problem",
    "question",
    "round",
    "task",
    "tp",
    "workstream",
}
_INTERNAL_TRACKING_TOKEN_PATTERN = re.compile(
    r"^(?:campaign|issue|problem|question|round|task|tp|workstream)[0-9]+$"
)


def work_id_from_paper_id(paper_id: str) -> str | None:
    """Return the semantic suffix carried by a descriptive paper ID."""

    if not DESCRIPTIVE_PAPER_ID_PATTERN.fullmatch(paper_id):
        return None
    return paper_id[9:]


def domain_scoped_parts(paper_id: str) -> dict[str, str] | None:
    """Parse YYYYMMDD-domain-subdomain-keywords identifiers."""

    match = DOMAIN_SCOPED_PAPER_ID_PATTERN.fullmatch(paper_id)
    return match.groupdict() if match else None


def internal_tracking_reference(identifier: str) -> str | None:
    """Return a repository-local tracking fragment embedded in an identifier."""

    parts = domain_scoped_parts(identifier)
    if not parts:
        return None
    tokens = parts["keywords"].split("-")
    for token in tokens:
        if _INTERNAL_TRACKING_TOKEN_PATTERN.fullmatch(token):
            return token
    for prefix, number in zip(tokens, tokens[1:]):
        if prefix in _INTERNAL_TRACKING_PREFIXES and number.isdigit():
            return f"{prefix}-{number}"
    return None


def validate_new_paper_id(
    paper_id: str,
    *,
    created_at: str,
    domain: str,
    subdomain: str,
) -> dict[str, str]:
    """Validate the immutable identifier assigned when a workspace is created."""

    parts = domain_scoped_parts(paper_id)
    if parts is None:
        raise ValueError(
            "New paper_id must use YYYYMMDD-domain-subdomain-keywords, for "
            "example 20260802-math-graph-opg1757-active-newton"
        )
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", created_at):
        raise ValueError("created_at must be a valid YYYY-MM-DD date")
    try:
        created = date.fromisoformat(created_at)
    except ValueError as exc:
        raise ValueError("created_at must be a valid YYYY-MM-DD date") from exc
    expected_date = created.strftime("%Y%m%d")
    if parts["date"] != expected_date:
        raise ValueError(f"paper_id must start with {expected_date}-")
    if parts["domain"] != domain:
        raise ValueError(
            f"paper_id domain segment {parts['domain']!r} must match domain {domain!r}"
        )
    if parts["subdomain"] != subdomain:
        raise ValueError(
            "paper_id subdomain segment "
            f"{parts['subdomain']!r} must match subdomain {subdomain!r}"
        )
    tracking_reference = internal_tracking_reference(paper_id)
    if tracking_reference:
        raise ValueError(
            "paper_id keywords must describe the scientific subject, not the "
            f"repository-local tracking label {tracking_reference!r}"
        )
    return parts


def public_manuscript_filename(display_id: str, version: str) -> str:
    """Return the canonical reader-facing PDF filename for one paper version."""

    if not domain_scoped_parts(display_id):
        raise ValueError(
            "display_id must use YYYYMMDD-domain-subdomain-keywords"
        )
    tracking_reference = internal_tracking_reference(display_id)
    if tracking_reference:
        raise ValueError(
            "display_id keywords must not expose repository-local tracking label "
            f"{tracking_reference!r}"
        )
    if not SEMANTIC_VERSION_PATTERN.fullmatch(version):
        raise ValueError("paper version must use MAJOR.MINOR.PATCH")
    return f"{display_id}-v{version}.pdf"
