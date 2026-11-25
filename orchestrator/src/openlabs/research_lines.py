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

from .data_catalog import catalog_summary

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
        **({"field": entry["field"]} if entry.get("field") else {}),
        "environment_status": environment_status(document, line_id),
        "sop": environment.get("sop"),
        "known_line": bool(entry),
        "paper_templates": template_summaries(entry),
        **({"data_catalog": catalog} if (catalog := catalog_summary(
            environment.get("data_catalog"))) else {}),
    }


# ``candidate_queue``: path of a ranked target file an enumerator wrote for the template
# (targets already screened against the template and checked for occupancy). Scouts of a
# queued template copy entries from it instead of searching for targets themselves.
TEMPLATE_SUMMARY_FIELDS = (
    "id", "version", "name", "paradigm", "feasible", "per_paper_cost", "candidate_queue",
)


def line_templates(document: Mapping[str, Any] | None, line_id: str) -> list[dict[str, Any]]:
    """The line's ``paper_templates`` (templated paper series), ``[]`` when none."""

    entry = line_entry(document, line_id) or {}
    templates = entry.get("paper_templates")
    return [dict(item) for item in templates if isinstance(item, Mapping)] if isinstance(
        templates, list) else []


def template_summaries(entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One compact item per paper template (the full entries are in the direction file)."""

    templates = entry.get("paper_templates")
    if not isinstance(templates, list):
        return []
    return [
        {key: item.get(key) for key in TEMPLATE_SUMMARY_FIELDS if item.get(key) is not None}
        for item in templates if isinstance(item, Mapping) and item.get("id")
    ]


def _dig(entry: Mapping[str, Any], *keys: str) -> Any:
    value: Any = entry
    for key in keys:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _first_text(entry: Mapping[str, Any], *paths: tuple[str, ...]) -> str | None:
    for keys in paths:
        value = _dig(entry, *keys)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, Mapping):
            for key in ("path", "entry", "receipt"):
                if isinstance(value.get(key), str) and value[key].strip():
                    return value[key].strip()
    return None


def line_resources(entry: Mapping[str, Any] | None) -> dict[str, str]:
    """The line's own working resources, read from its entry (for the owner brief).

    Keys (each only when the entry declares it): ``standard_entry`` (the shared entry
    point: ``environment.standard_solver.entry``, ``environment.tools``,
    ``standard_tools.path``), ``analysis_library``, ``activate``, ``analysis_package``
    (path; its ``entry`` appended), ``control_receipt`` (``environment.standard_solver.
    control_receipt``, ``environment.control_receipt``, ``control.receipt``), ``data``
    (``environment.data``, else ``environment.data_access``), ``data_catalog`` (the line's
    data capability catalogue, ``environment.data_catalog``; see ``data_catalog``), ``sop``,
    ``compute_placement`` and ``gpu`` (``environment.gpu``: text, or an object with
    ``usage``/``memory_mib``/``rule``). Every value is a pointer or a short rule written
    by the line, never a copy of its SOP.
    """

    if not isinstance(entry, Mapping):
        return {}
    result: dict[str, str] = {}
    found = _first_text(entry, ("environment", "standard_solver", "entry"),
                        ("environment", "tools"), ("environment", "standard_tools"),
                        ("standard_tools",))
    if found:
        result["standard_entry"] = found
    found = _first_text(entry, ("environment", "standard_solver", "analysis_library"))
    if found:
        result["analysis_library"] = found
    found = _first_text(entry, ("environment", "activate"))
    if found:
        result["activate"] = found
    package = entry.get("analysis_package")
    if isinstance(package, Mapping) and isinstance(package.get("path"), str):
        text = str(package["path"]).strip()
        if result.get("standard_entry", "").split(" ")[0].rstrip("/") == text.rstrip("/"):
            result.pop("standard_entry")  # the same tools: name them once
        if isinstance(package.get("entry"), str) and package["entry"].strip():
            text += f"; {package['entry'].strip()}"
        result["analysis_package"] = text
    found = _first_text(entry, ("environment", "standard_solver", "control_receipt"),
                        ("environment", "control_receipt"), ("control", "receipt"))
    if found:
        result["control_receipt"] = found
    found = _first_text(entry, ("environment", "data"), ("environment", "data_access"))
    if found:
        result["data"] = found
    found = _first_text(entry, ("environment", "data_catalog"))
    if found:
        result["data_catalog"] = found
    found = _first_text(entry, ("environment", "sop"))
    if found:
        result["sop"] = found
    found = _first_text(entry, ("environment", "compute_placement"))
    if found:
        result["compute_placement"] = found
    gpu = _dig(entry, "environment", "gpu")
    if not line_uses_gpu(entry):
        return result
    if isinstance(gpu, str) and gpu.strip():
        result["gpu"] = gpu.strip()
    elif isinstance(gpu, Mapping):
        parts = [str(gpu[key]).strip() for key in ("usage", "rule") if str(
            gpu.get(key) or "").strip()]
        if gpu.get("memory_mib"):
            parts.append(f"declare --gpu-memory-mib {gpu['memory_mib']}")
        if parts:
            result["gpu"] = "; ".join(parts)
    return result


def line_uses_gpu(entry: Mapping[str, Any] | None) -> bool:
    """Whether the line declares GPU work (``environment.gpu`` other than none/0)."""

    gpu = _dig(entry or {}, "environment", "gpu")
    if isinstance(gpu, Mapping):
        return gpu.get("required", True) is not False
    text = str(gpu or "").strip().lower()
    return bool(text) and text not in {"none", "no", "0", "false"}


def queued_templates(document: Mapping[str, Any] | None, line_id: str) -> dict[str, str]:
    """``{template id: candidate_queue path}`` for the line's templates that name a queue."""

    return {
        str(item["id"]): str(item["candidate_queue"]).strip()
        for item in line_templates(document, line_id)
        if item.get("id") and isinstance(item.get("candidate_queue"), str)
        and str(item["candidate_queue"]).strip()
    }
