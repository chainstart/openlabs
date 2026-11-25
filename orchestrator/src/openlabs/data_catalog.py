"""Per-line data capability catalogues (2026-11-25 data onboarding).

A research line may declare ``environment.data_catalog`` in ``registry/research-lines.yaml``:
the absolute path of a YAML file (schema ``openlabs.data_catalog.v1``) that lists every data
source the line can use - already ingested ones, free registration-free sources onboarded with a
fetch tool and a tested sample, sources only catalogued (no sample yet), and sources that need an
account or an application (``needs_registration``; the owner's list is
``maintenance/20261125-data-onboarding/REGISTER-LIST.md``).

Scouts and the admission gate receive a compact form of the catalogue in the packet's
``research_line_summary.data_catalog`` (:func:`catalog_summary`), and the owner brief points to
the file (``research_lines.line_resources`` key ``data_catalog``). The full entries - endpoints,
licence, citation, tool commands, sample checks, source selection - stay in the file.

The control plane never fetches data from here; it only reads the file.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCHEMA = "openlabs.data_catalog.v1"
STATUSES = ("ingested", "onboarded", "catalogued", "needs_registration", "blocked")
# ``ingested``: full data on disk and registered by the line (its own manifest).
# ``onboarded``: free, no registration; fetch tool written and a small sample verified.
# ``catalogued``: free, no registration; access documented, no sample tested yet.
# ``needs_registration``: free but needs an account, token, course or data-use agreement.
# ``blocked``: not usable now (licence, jurisdiction, site refusal); the reason is recorded.
ACCESS_KINDS = ("query_api", "bulk_download", "bucket", "mixed", "web")
MAX_SUMMARY_SOURCES = 60
MAX_SUMMARY_TEXT = 160
MAX_FILE_BYTES = 1_000_000


class DataCatalogError(ValueError):
    """The catalogue cannot be read or breaks the schema."""


def load_catalog(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise DataCatalogError(f"{path}: missing")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise DataCatalogError(f"{path}: larger than {MAX_FILE_BYTES} bytes")
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - PyYAML is present wherever the loop runs
        raise DataCatalogError("PyYAML is not installed") from exc
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DataCatalogError(f"{path}: {exc}") from exc
    if not isinstance(document, Mapping):
        raise DataCatalogError(f"{path}: expected a mapping")
    return dict(document)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_catalog(document: Mapping[str, Any]) -> list[str]:
    """Schema problems of a catalogue (``[]`` when valid)."""

    problems: list[str] = []
    if document.get("schema_version") != SCHEMA:
        problems.append(f"schema_version must be {SCHEMA}")
    if not _text(document.get("line")):
        problems.append("line is required")
    sources = document.get("sources")
    if not isinstance(sources, list) or not sources:
        return [*problems, "sources must be a non-empty list"]
    seen: set[str] = set()
    for index, source in enumerate(sources):
        where = f"sources[{index}]"
        if not isinstance(source, Mapping):
            problems.append(f"{where}: expected a mapping")
            continue
        source_id = str(source.get("id") or "")
        where = f"sources[{index}] {source_id or '?'}"
        if not source_id:
            problems.append(f"{where}: id is required")
        elif source_id in seen:
            problems.append(f"{where}: duplicate id")
        seen.add(source_id)
        for key in ("name", "summary", "licence"):
            if not _text(source.get(key)):
                problems.append(f"{where}: {key} is required")
        status = source.get("status")
        if status not in STATUSES:
            problems.append(f"{where}: status must be one of {', '.join(STATUSES)}")
        access = source.get("access")
        if not isinstance(access, Mapping) or access.get("kind") not in ACCESS_KINDS:
            problems.append(f"{where}: access.kind must be one of {', '.join(ACCESS_KINDS)}")
        if status == "onboarded":
            if not _text(source.get("tool")):
                problems.append(f"{where}: an onboarded source names its fetch tool")
            sample = source.get("sample")
            if not isinstance(sample, Mapping) or not _text(sample.get("path")) or not _text(
                    sample.get("check")):
                problems.append(f"{where}: an onboarded source records sample.path and sample.check")
            selection = source.get("source_selection")
            if not isinstance(selection, Mapping) or not _text(selection.get("chosen")):
                problems.append(f"{where}: an onboarded source records source_selection.chosen")
        if status == "needs_registration" and not _text(source.get("registration")):
            problems.append(f"{where}: needs_registration names what to register (registration)")
        if status == "blocked" and not _text(source.get("blocked_reason")):
            problems.append(f"{where}: blocked sources record blocked_reason")
        if source.get("large") and not _text(source.get("offpeak_rule")):
            problems.append(f"{where}: large sources state offpeak_rule")
    return problems


def _clip(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = " ".join(value.split())
    return text if len(text) <= MAX_SUMMARY_TEXT else text[:MAX_SUMMARY_TEXT - 1] + "\u2026"


def catalog_summary(path_text: Any) -> dict[str, Any] | None:
    """Compact form for scout/admission packets: path, counts and one line per source.

    ``None`` when no catalogue is declared; ``{"path", "error"}`` when it cannot be read.
    """

    if not isinstance(path_text, str) or not path_text.strip():
        return None
    path = Path(path_text.strip())
    summary: dict[str, Any] = {"path": str(path)}
    try:
        document = load_catalog(path)
    except (OSError, DataCatalogError) as exc:
        summary["error"] = str(exc)
        return summary
    sources = [item for item in document.get("sources") or [] if isinstance(item, Mapping)]
    counts: dict[str, int] = {}
    for item in sources:
        status = str(item.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    summary["counts"] = counts
    summary["sources"] = [
        {key: value for key, value in (
            ("id", item.get("id")), ("status", item.get("status")), ("name", item.get("name")),
            ("summary", _clip(item.get("summary"))), ("tool", _clip(item.get("tool"))),
            ("large", bool(item.get("large")) or None)) if value not in (None, "")}
        for item in sources[:MAX_SUMMARY_SOURCES]
    ]
    if len(sources) > MAX_SUMMARY_SOURCES:
        summary["truncated"] = len(sources) - MAX_SUMMARY_SOURCES
    return summary


def main(argv: list[str] | None = None) -> int:
    """``python -m openlabs.data_catalog FILE...``: print schema problems; exit 1 if any."""

    import sys

    failed = 0
    for name in (argv if argv is not None else sys.argv[1:]):
        try:
            problems = validate_catalog(load_catalog(Path(name)))
        except DataCatalogError as exc:
            problems = [str(exc)]
        for problem in problems:
            print(f"{name}: {problem}")
        failed += bool(problems)
        if not problems:
            print(f"{name}: ok")
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
