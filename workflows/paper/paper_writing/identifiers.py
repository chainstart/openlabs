"""Stable and human-readable identifiers for writing workspaces."""

from __future__ import annotations

import re


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


def work_id_from_paper_id(paper_id: str) -> str | None:
    """Return the semantic suffix carried by a descriptive paper ID."""

    if not DESCRIPTIVE_PAPER_ID_PATTERN.fullmatch(paper_id):
        return None
    return paper_id[9:]


def domain_scoped_parts(paper_id: str) -> dict[str, str] | None:
    """Parse YYYYMMDD-domain-subdomain-keywords identifiers."""

    match = DOMAIN_SCOPED_PAPER_ID_PATTERN.fullmatch(paper_id)
    return match.groupdict() if match else None
