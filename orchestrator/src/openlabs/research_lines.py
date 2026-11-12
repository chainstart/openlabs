"""Research lines: the direction file the research program scouts and admits within.

``registry/research-lines.yaml`` in the data repository (``[program].research_lines_path``)
lists the lines, each with an ``id``, a ``host_domain`` and an ``environment.status``.
The control plane reads only those fields: scouts and the admission gate read the rest
(venues and fee evidence, licence lists, minimum validation, avoided directions).

A line whose environment is not ``ready`` may be scouted, but an admitted card of that
line is held mechanically until the environment is ready (a ``line_environment_ready``
reopen condition), because its first research task could not run. The control plane
then admits it with the gate's recorded decision (``program_flow.release_ready_holds``).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ENVIRONMENT_READY = "ready"


class ResearchLinesError(ValueError):
    """The direction file cannot be read."""


def load_research_lines(path: Path) -> dict[str, Any]:
    """Parse the direction file (YAML, or JSON when PyYAML is unavailable)."""

    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:  # pragma: no cover - PyYAML is present wherever the loop runs
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ResearchLinesError(
                f"{path}: PyYAML is not installed and the file is not JSON"
            ) from exc
    else:
        try:
            document = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ResearchLinesError(f"{path}: {exc}") from exc
    if not isinstance(document, Mapping) or not isinstance(document.get("lines"), list):
        raise ResearchLinesError(f"{path}: expected a mapping with a `lines` list")
    return dict(document)


def line_entry(document: Mapping[str, Any] | None, line_id: str) -> dict[str, Any] | None:
    for item in (document or {}).get("lines") or []:
        if isinstance(item, Mapping) and str(item.get("id") or "") == line_id:
            return dict(item)
    return None


def environment_status(document: Mapping[str, Any] | None, line_id: str) -> str:
    """``ready``, another declared status, ``unknown_line`` or ``unreadable``."""

    if document is None:
        return "unreadable"
    entry = line_entry(document, line_id)
    if entry is None:
        return "unknown_line"
    environment = entry.get("environment")
    status = environment.get("status") if isinstance(environment, Mapping) else None
    return str(status or "unspecified")


def read_lines_or_none(path: Path) -> dict[str, Any] | None:
    """The parsed direction file, or ``None`` when it is missing or unreadable."""

    if not path.is_file():
        return None
    try:
        return load_research_lines(path)
    except (OSError, ResearchLinesError):
        return None


def line_summary(document: Mapping[str, Any] | None, line_id: str) -> dict[str, Any]:
    """What a scout or admission packet carries about its line (compact, no venues)."""

    entry = line_entry(document, line_id) or {}
    environment = entry.get("environment") if isinstance(entry.get("environment"), Mapping) else {}
    return {
        "id": line_id,
        "title": entry.get("title"),
        "host_domain": entry.get("host_domain"),
        "environment_status": environment_status(document, line_id),
        "sop": environment.get("sop"),
        "known_line": bool(entry),
    }
