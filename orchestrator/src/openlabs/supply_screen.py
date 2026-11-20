"""Early screens of topic supply at card intake (2026-11-20, pipeline overhaul W1 items 2-4).

All three are mechanical (no model call) and read fields a research line declares in
registry/research-lines.yaml; a line that declares none of them is unaffected.

Capability table (item 2)
    The line entry's ``capabilities`` maps a capability id to whether the line's shared
    environment provides it::

        capabilities:
          spot_model: {key: environment.standard_solver.spot_config}  # dotted key, truthy
          third_light_prior: {available: true}
          flux_calibration: false

    A card (or its template) lists ``required_capabilities`` (ids, or dotted keys of the
    line entry). A required capability that is missing from the table or unavailable
    rejects the card (``card_capability_missing``; mechanical, not a judgement of the
    topic). A card drawn from a queue's ``held_candidates`` whose ``draw_hold.release_when``
    (``line_capability``) is not met is rejected the same way.

Data availability (item 2)
    A card or its template lists ``data_requirements``::

        data_requirements:
          - name: DISPATCHLOAD unit-level UIGF
            glob: /abs/path/data/nem/mmsdm/DISPATCHLOAD/*.zip   # or relative to the data repo
            columns: [UIGF]
            header: aemo_mms          # csv (first row) | aemo_mms (``I,`` rows) | none
            nonblank: true            # optional: the columns also carry a value in the sample
            months: {from: "2021-01", to: "2024-12"}   # optional: YYYYMM in the file name
            min_fraction: 1.0         # share of the matched files that must have the columns
            min_files: 105            # optional: fewer matched files fail the requirement

    Only the first lines of each file are read (zip members included), cached by path,
    size and mtime; ``header: none`` reads nothing and counts matched files (binary data
    such as .mat or .h5). ``nonblank`` counts a file only when every listed column has a
    non-empty value in at least one sampled data row (an AEMO table can carry a column
    whose values start months later, e.g. DISPATCHLOAD.UIGF from 2023-09). The line's
    candidate queue entry may list its own ``data_requirements`` (at the top level or in
    ``card_fields``); they are merged with the line's, the template's and the card's by
    ``name``. Too little coverage rejects the card (``card_data_unavailable``).

Pilot gate (item 3)
    A template (or the line) declares ``admission_pilot``::

        admission_pilot:
          stage: /abs/venv/bin/python /abs/pilot_stage.py {entry_id} --card {card} --out {out}
          cpus: 8                  # capped by [program.supply].pilot_max_threads (<= 8)
          memory_mib: 9216
          timeout_seconds: 7200    # capped so cpus x hours <= pilot_core_hours_max
          core_hours: 12           # the budget the pilot may use (recorded on the card)
          verdict_file: pilot.json # in the job's $OPENLABS_OUTPUT_DIR: {verdict, metrics, reasons}

    ``stage`` runs locally (seconds, no network) and writes the job directory ``{out}``; it
    may print ``{"argv": [...]}`` (default ``["bash", "run.sh"]``). The card waits as
    proposed (``card_check.pilot.status`` pending/submitted), is not sent to the admission
    review and holds no owner seat; the control plane submits the job to ailab, reads its
    verdict and records budget, use and conclusion in ``card_check.pilot``. pass -> the
    admission review; fail -> rejected ``card_pilot_failed``; a job that cannot run
    ``pilot_max_attempts`` times -> rejected ``card_pilot_unavailable``.

Target memory (item 4)
    Every topic is registered by (research line, ``candidate_queue_entry.entry_id``). A new
    card for a target that was rejected for a mechanical reason while its queue entry is
    unchanged (``card_check.entry_digest``; for older records: the queue file has not
    changed since), or that has a frozen topic the card does not ``reopens``, is rejected
    as ``card_target_repeat_failure`` without running the precheck again.
"""

from __future__ import annotations

import copy
import functools
import glob as globbing
import gzip
import hashlib
import io
import json
import re
import shlex
import subprocess
import zipfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import FactorySettings, WorkspacePaths
from .db import FactoryDB, utc_now

CAPABILITY_REJECTION = "card_capability_missing"
DATA_REJECTION = "card_data_unavailable"
PILOT_REJECTION = "card_pilot_failed"
PILOT_UNAVAILABLE = "card_pilot_unavailable"
REPEAT_REJECTION = "card_target_repeat_failure"
# Rejections that say nothing about the topic and repeat while the input is unchanged.
MECHANICAL_REJECTIONS = frozenset({
    "card_precheck_failed", PILOT_REJECTION, CAPABILITY_REJECTION, DATA_REJECTION,
})
SCREEN_REJECTIONS = frozenset({*MECHANICAL_REJECTIONS, PILOT_UNAVAILABLE, REPEAT_REJECTION})
AVAILABLE_WORDS = frozenset({"available", "ready", "validated", "yes", "true", "on"})
PILOT_WAITING = frozenset({"pending", "submitted"})
STAGE_TIMEOUT_SECONDS = 300
HEADER_LINES = 64
# A header line longer than this is not a text header (binary file read as csv).
HEADER_LINE_CHARS = 1 << 16
HEADER_KINDS = frozenset({"csv", "aemo_mms", "none"})
_MONTH = re.compile(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(?!\d)")
_VOLATILE_ENTRY_KEYS = frozenset({"ledger_occupancy", "rank", "draw_order", "score_rank"})


def _supply(settings: FactorySettings) -> Any:
    return settings.program.supply


def _dotted(document: Any, key: str) -> tuple[bool, Any]:
    value = document
    for part in key.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return False, None
        value = value[part]
    return True, value


def _truthy(value: Any) -> bool:
    if isinstance(value, Mapping):
        return value.get("validated") is not False and value.get("available") is not False
    if isinstance(value, str):
        return value.strip().lower() in AVAILABLE_WORDS or (
            bool(value.strip()) and value.strip().lower() not in {
                "false", "no", "off", "unavailable", "missing", "none", "not_validated"})
    return bool(value)


# --------------------------------------------------------------------------- capabilities


def capability_status(line_entry: Mapping[str, Any], capability: str) -> tuple[bool, str]:
    """``(available, detail)`` of one capability id (or dotted key) of a line."""

    table = line_entry.get("capabilities")
    table = table if isinstance(table, Mapping) else {}
    if capability in table:
        spec = table[capability]
        if isinstance(spec, Mapping):
            if spec.get("key"):
                present, value = _dotted(line_entry, str(spec["key"]))
                ok = present and _truthy(value)
                return ok, (f"{capability}: {spec['key']} "
                            + ("present" if ok else "absent or not validated"))
            if "available" in spec:
                available = spec["available"] is True
                return available, f"{capability}: available={spec['available']}"
            if "status" in spec:
                status = str(spec["status"]).strip().lower()
                return status in AVAILABLE_WORDS, f"{capability}: status {status}"
            return False, f"{capability}: entry states no availability"
        if isinstance(spec, bool):
            return spec, f"{capability}: {spec}"
        text = str(spec).strip().lower()
        return text in AVAILABLE_WORDS, f"{capability}: {text}"
    if "." in capability:
        present, value = _dotted(line_entry, capability)
        ok = present and _truthy(value)
        return ok, f"{capability} " + ("present" if ok else "absent or not validated")
    return False, f"{capability}: not in the line's capability table"


def _required(card: Mapping[str, Any], template_entry: Mapping[str, Any]) -> list[str]:
    wanted: list[str] = []
    for source in (template_entry.get("required_capabilities"), card.get("required_capabilities")):
        for item in source if isinstance(source, list) else []:
            name = str(item.get("id") or item.get("key") or "") if isinstance(item, Mapping) \
                else str(item or "")
            if name.strip() and name.strip() not in wanted:
                wanted.append(name.strip())
    return wanted


@functools.lru_cache(maxsize=16)
def _queue_index(path: str, mtime_ns: int, size: int) -> dict[str, tuple[str, str]]:
    """``{entry id: (list name, entry JSON)}`` of a queue file (cached by mtime and size)."""

    try:
        queue = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    index: dict[str, tuple[str, str]] = {}
    if not isinstance(queue, Mapping):
        return index
    for name, items in queue.items():
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, Mapping):
                entry = str(item.get("entry_id") or item.get("batch_id") or "").strip()
                if entry and entry not in index:
                    index[entry] = (str(name), json.dumps(item, sort_keys=True, default=str))
    return index


def _queue_entry(queue_path: Any, entry_id: str) -> tuple[str | None, dict[str, Any] | None]:
    """``(list name, entry)`` of ``entry_id`` in a candidate queue file."""

    if not queue_path or not entry_id:
        return None, None
    try:
        stat = Path(str(queue_path)).stat()
    except OSError:
        return None, None
    index = _queue_index(str(queue_path), stat.st_mtime_ns, stat.st_size)
    found = index.get(entry_id) or next(
        (value for key, value in index.items() if key.upper() == entry_id.upper()), None)
    if found is None:
        return None, None
    return found[0], json.loads(found[1])


def capability_problems(
    paths: WorkspacePaths,
    settings: FactorySettings,
    card: Mapping[str, Any],
    line_entry: Mapping[str, Any],
    template_entry: Mapping[str, Any],
) -> list[str]:
    """Why the line cannot provide what the card needs (empty: nothing missing)."""

    from .card_precheck import entry_id_of

    problems: list[str] = []
    for capability in _required(card, template_entry):
        ok, detail = capability_status(line_entry, capability)
        if not ok:
            problems.append(f"required capability unavailable: {detail}")
    listed, entry = _queue_entry(template_entry.get("candidate_queue"), entry_id_of(card))
    hold = (entry or {}).get("draw_hold") if listed == "held_candidates" else None
    when = hold.get("release_when") if isinstance(hold, Mapping) else None
    if isinstance(when, Mapping) and when.get("kind") == "line_capability" and when.get("key"):
        # Same reading as reopen.evaluate_condition(kind line_capability) on this line.
        present, value = _dotted(line_entry, str(when["key"]))
        met = (present and value == when["equals"]) if "equals" in when else (
            present and bool(value) and not (isinstance(value, Mapping)
                                             and value.get("validated") is False))
        if not met:
            problems.append(
                f"queue entry {entry_id_of(card)} is held ({hold.get('reason') or 'draw_hold'}) "
                f"until {when['key']} is available")
    return problems


# --------------------------------------------------------------------------- data coverage


def _header_lines(path: Path) -> list[str]:
    def first(stream: io.BufferedIOBase) -> list[str]:
        text = io.TextIOWrapper(stream, encoding="utf-8", errors="replace")
        lines = []
        for _ in range(HEADER_LINES):
            line = text.readline(HEADER_LINE_CHARS)
            if not line:
                break
            lines.append(line.rstrip("\r\n"))
            if len(line) >= HEADER_LINE_CHARS and not line.endswith("\n"):
                break  # no line break in sight: not a text table
        return lines

    name = path.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(path) as archive:
            members = [item for item in archive.namelist() if item.lower().endswith(".csv")]
            if not members:
                return []
            with archive.open(members[0]) as stream:
                return first(stream)  # type: ignore[arg-type]
    if name.endswith(".gz"):
        with gzip.open(path, "rb") as stream:
            return first(stream)  # type: ignore[arg-type]
    with path.open("rb") as stream:
        return first(stream)  # type: ignore[arg-type]


def file_profile(path: Path, header: str) -> dict[str, list[str]]:
    """``{columns, valued}`` of a file: declared column names and those with a value in
    at least one sampled data row (``csv``: first row then data rows; ``aemo_mms``:
    ``I,`` rows declare, ``D,`` rows of the same table carry values)."""

    lines = _header_lines(path)
    columns: list[str] = []
    valued: set[str] = set()
    current: list[str] = []
    for index, line in enumerate(lines):
        fields = [field.strip().strip('"') for field in line.split(",")]
        if header == "aemo_mms":
            if fields and fields[0] == "I":
                current = [field.upper() for field in fields[4:]]
                columns.extend(current)
            elif fields and fields[0] == "D" and current:
                valued.update(name for name, value in zip(current, fields[4:]) if value)
        elif index == 0:
            current = [field.upper() for field in fields]
            columns = list(current)
        else:
            valued.update(name for name, value in zip(current, fields) if value)
    return {"columns": columns, "valued": sorted(valued)}


def file_columns(path: Path, header: str) -> list[str]:
    """Column names a file declares (``csv``: first row; ``aemo_mms``: ``I,`` rows)."""

    return file_profile(path, header)["columns"]


class HeaderCache:
    """Column profiles by (path, size, mtime), persisted between ticks."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.changed = False
        self.data: dict[str, list[str]] = {}
        if path is not None:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                self.data = value if isinstance(value, dict) else {}
            except (OSError, ValueError):
                self.data = {}

    def profile(self, path: Path, header: str) -> dict[str, list[str]] | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        key = f"{path}|{stat.st_size}|{int(stat.st_mtime)}|{header}|v2"
        value = self.data.get(key)
        if not isinstance(value, dict):
            try:
                value = file_profile(path, header)
            except (OSError, zipfile.BadZipFile, EOFError, ValueError):
                return None
            self.data[key] = value
            self.changed = True
        return {"columns": list(value.get("columns") or []),
                "valued": list(value.get("valued") or [])}

    def columns(self, path: Path, header: str) -> list[str] | None:
        found = self.profile(path, header)
        return None if found is None else found["columns"]

    def save(self) -> None:
        if self.path is None or not self.changed:
            return
        from .contracts import atomic_write_json

        atomic_write_json(self.path, self.data)


def _in_months(path: Path, months: Any) -> bool:
    if not isinstance(months, Mapping):
        return True
    match = _MONTH.search(path.name)
    if match is None:
        return True
    stamp = f"{match.group(1)}-{match.group(2)}"
    low = str(months.get("from") or "0000-00")
    high = str(months.get("to") or "9999-99")
    return low <= stamp <= high


def requirement_coverage(requirement: Mapping[str, Any], *, data_root: Path,
                         cache: HeaderCache) -> dict[str, Any]:
    """Coverage of one ``data_requirements`` item: matched files, files with the columns."""

    pattern = str(requirement.get("glob") or "").strip()
    if not pattern:
        return {"name": requirement.get("name"), "ok": False, "error": "no glob"}
    if not Path(pattern).is_absolute():
        pattern = str(data_root / pattern)
    columns = [str(item).strip().upper() for item in requirement.get("columns") or []
               if str(item).strip()]
    header = str(requirement.get("header") or "csv").strip().lower()
    if header not in HEADER_KINDS:
        return {"name": requirement.get("name") or pattern, "glob": pattern, "ok": False,
                "files": 0, "covered": 0, "columns": columns,
                "error": f"header must be one of {sorted(HEADER_KINDS)}"}
    nonblank = requirement.get("nonblank") is True
    files = sorted(Path(item) for item in globbing.glob(pattern)
                   if _in_months(Path(item), requirement.get("months")))
    missing: list[str] = []
    unreadable: list[str] = []
    for path in files:
        if header == "none":
            if not path.is_file():
                unreadable.append(path.name)
            continue
        found = cache.profile(path, header)
        if found is None:
            unreadable.append(path.name)
            continue
        present = found["valued"] if nonblank else found["columns"]
        if any(column not in present for column in columns):
            missing.append(path.name)
    try:
        wanted = float(requirement.get("min_fraction", 1.0))
    except (TypeError, ValueError):
        wanted = 1.0
    try:
        min_files = max(1, int(requirement.get("min_files", 1)))
    except (TypeError, ValueError):
        min_files = 1
    covered = len(files) - len(missing) - len(unreadable)
    fraction = covered / len(files) if files else 0.0
    row = {
        "name": requirement.get("name") or pattern, "glob": pattern, "columns": columns,
        "files": len(files), "covered": covered, "fraction": round(fraction, 4),
        "min_fraction": wanted, "min_files": min_files,
        "ok": len(files) >= min_files and fraction + 1e-9 >= wanted,
        "files_missing_columns": missing[:20], "unreadable": unreadable[:20],
    }
    if nonblank:
        row["nonblank"] = True
    if len(files) < min_files:
        row["error"] = f"{len(files)} files match, {min_files} required"
    return row


def _entry_requirements(template_entry: Mapping[str, Any], card: Mapping[str, Any]
                        ) -> list[Any]:
    """The ``data_requirements`` the card's candidate queue entry declares."""

    from .card_precheck import entry_id_of

    _name, entry = _queue_entry(template_entry.get("candidate_queue"), entry_id_of(card))
    if not isinstance(entry, Mapping):
        return []
    fields = entry.get("card_fields") if isinstance(entry.get("card_fields"), Mapping) else {}
    found: list[Any] = []
    for source in (entry.get("data_requirements"), fields.get("data_requirements")):
        found.extend(source if isinstance(source, list) else [])
    return found


def _requirements(card: Mapping[str, Any], template_entry: Mapping[str, Any],
                  line_entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for source in (line_entry.get("data_requirements"), template_entry.get("data_requirements"),
                   _entry_requirements(template_entry, card), card.get("data_requirements")):
        for index, item in enumerate(source if isinstance(source, list) else []):
            if isinstance(item, Mapping):
                key = str(item.get("name") or item.get("glob") or index)
                merged[key] = {**merged.get(key, {}), **dict(item)}
    return list(merged.values())


def data_problems(paths: WorkspacePaths, settings: FactorySettings, card: Mapping[str, Any],
                  line_entry: Mapping[str, Any], template_entry: Mapping[str, Any]
                  ) -> tuple[list[str], list[dict[str, Any]]]:
    """``(problems, coverage rows)`` of the card's declared data requirements."""

    requirements = _requirements(card, template_entry, line_entry)
    if not requirements:
        return [], []
    cache = HeaderCache(paths.program_control / "supply-screen" / "headers.json")
    rows = [requirement_coverage(item, data_root=paths.data, cache=cache)
            for item in requirements]
    cache.save()
    problems = [
        f"data requirement {row['name']}: {row['covered']}/{row['files']} files carry "
        f"{', '.join(row.get('columns') or []) or 'the files'} "
        f"(need {row.get('min_fraction', 1.0):g}"
        + (f"; e.g. missing in {', '.join(row['files_missing_columns'][:3])}"
           if row.get("files_missing_columns") else "")
        + (f"; {row['error']}" if row.get("error") else "") + ")"
        for row in rows if not row.get("ok")
    ]
    return problems, rows


# --------------------------------------------------------------------------- target memory


def target_key(card: Mapping[str, Any]) -> str:
    from .card_precheck import entry_id_of

    return entry_id_of(card).strip().upper()


def entry_digest(queue_path: Any, entry_id: str) -> str | None:
    """Digest of a queue entry's content (draw-order and ledger fields left out)."""

    _name, entry = _queue_entry(queue_path, entry_id)
    if entry is None:
        return None
    body = {key: value for key, value in entry.items() if key not in _VOLATILE_ENTRY_KEYS}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def _last_at(topic: Mapping[str, Any]) -> str:
    history = topic.get("history") or []
    return str(history[-1].get("at") or "") if history and isinstance(history[-1], Mapping) else ""


def _card(topic: Mapping[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(Path(str(topic.get("card_path") or "")).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def target_registry(document: Mapping[str, Any], line: str | None = None
                    ) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """``{(line, target): [outcome, ...]}`` over the whole ledger (oldest first)."""

    from .program import last_rejection_reason

    registry: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for topic in document.get("topics") or []:
        if not isinstance(topic, Mapping):
            continue
        topic_line = str(topic.get("research_line") or "")
        if line is not None and topic_line != line:
            continue
        check = topic.get("card_check") if isinstance(topic.get("card_check"), Mapping) else {}
        key = str(check.get("target") or "").upper() or target_key(_card(topic))
        if not key:
            continue
        status = str(topic.get("status") or "")
        registry.setdefault((topic_line, key), []).append({
            "topic_id": str(topic.get("topic_id") or ""), "status": status,
            "reason": (last_rejection_reason(topic) if status == "rejected"
                       else str(topic.get("freeze_reason_class") or "") if status == "frozen"
                       else ""),
            "at": _last_at(topic), "entry_digest": check.get("entry_digest"),
        })
    for outcomes in registry.values():
        outcomes.sort(key=lambda item: item["at"])
    return registry


def _file_mtime_iso(path: Any) -> str | None:
    try:
        moment = datetime.fromtimestamp(Path(str(path)).stat().st_mtime, UTC)
    except (OSError, TypeError, ValueError):
        return None
    return moment.isoformat().replace("+00:00", "Z")


def _repeat(document: Mapping[str, Any], card: Mapping[str, Any],
            template_entry: Mapping[str, Any],
            registry: Mapping[tuple[str, str], list[dict[str, Any]]] | None = None,
            ) -> tuple[str, dict[str, Any]] | None:
    line = str(card.get("research_line") or "")
    key = target_key(card)
    if not line or not key:
        return None
    registry = registry if registry is not None else target_registry(document, line)
    outcomes = registry.get((line, key)) or []
    queue = template_entry.get("candidate_queue")
    current = entry_digest(queue, key) if queue else None
    queue_changed_at = _file_mtime_iso(queue) if queue else None
    reopens = str(card.get("reopens") or "")
    for prior in reversed(outcomes):
        if prior["status"] == "frozen" and prior["topic_id"] != reopens:
            return (f"target {key} has frozen topic {prior['topic_id']} "
                    f"({prior['reason']}, {prior['at']}); a new card must declare "
                    f"reopens: {prior['topic_id']} with its reopen basis"), prior
        if prior["status"] != "rejected" or prior["reason"] not in MECHANICAL_REJECTIONS:
            continue
        if prior.get("entry_digest") and current:
            same = prior["entry_digest"] == current
        else:
            same = queue_changed_at is None or queue_changed_at <= prior["at"]
        if same:
            return (f"target {key} was rejected {prior['reason']} as {prior['topic_id']} "
                    f"({prior['at']}) and its queue entry has not changed since"), prior
    return None


def repeat_failure(document: Mapping[str, Any], card: Mapping[str, Any],
                   template_entry: Mapping[str, Any]) -> str | None:
    """Why a card's target must not get another card now (None: it may)."""

    found = _repeat(document, card, template_entry)
    return found[0] if found is not None else None


def failed_targets(document: Mapping[str, Any], line: str,
                   queues: Mapping[str, str]) -> dict[str, str]:
    """``{target: status:reason}`` the line's scouts should not draw again."""

    result: dict[str, str] = {}
    paths = sorted(set(queues.values()))
    registry = target_registry(document, line)
    for (topic_line, key), outcomes in registry.items():
        if topic_line != line or not outcomes:
            continue
        queue = next((path for path in paths if _queue_entry(path, key)[1] is not None),
                     paths[0] if paths else None)
        found = _repeat(document, {"research_line": line,
                                   "candidate_queue_entry": {"entry_id": key}},
                        {"candidate_queue": queue}, registry)
        if found is not None:
            prior = found[1]
            result[key] = f"{prior['status']}:{prior['reason'] or '?'}"
    return result


# --------------------------------------------------------------------------- pilot


def pilot_spec(line_entry: Mapping[str, Any], template_entry: Mapping[str, Any],
               template_id: str) -> dict[str, Any] | None:
    for source in (template_entry, line_entry):
        block = source.get("admission_pilot")
        if not isinstance(block, Mapping):
            continue
        per = block.get("per_template")
        spec = per.get(template_id) if isinstance(per, Mapping) else None
        spec = spec if isinstance(spec, Mapping) else (block if block.get("stage") else None)
        if isinstance(spec, Mapping) and spec.get("stage"):
            return dict(spec)
    return None


def pilot_budget(spec: Mapping[str, Any], settings: FactorySettings) -> dict[str, Any]:
    """CPUs, wall seconds and core-hour budget of a pilot within ``[program.supply]``."""

    supply = _supply(settings)

    def number(key: str, default: float) -> float:
        try:
            value = float(spec.get(key, default))
        except (TypeError, ValueError):
            value = default
        return value if value > 0 else default

    cpus = max(1, min(int(number("cpus", supply.pilot_max_threads)), supply.pilot_max_threads))
    core_hours = min(number("core_hours", supply.pilot_core_hours_max),
                     supply.pilot_core_hours_max)
    wall = int(min(number("timeout_seconds", core_hours / cpus * 3600),
                   core_hours / cpus * 3600))
    memory = int(number("memory_mib", 1024 * cpus + 1024))
    return {"cpus": cpus, "memory_mib": memory, "wall_seconds": max(60, wall),
            "core_hours_budget": round(cpus * max(60, wall) / 3600, 2),
            "core_hours_cap": supply.pilot_core_hours_max,
            "verdict_file": str(spec.get("verdict_file") or "pilot.json")}


def pilot_held(topic: Mapping[str, Any]) -> bool:
    check = topic.get("card_check") if isinstance(topic.get("card_check"), Mapping) else {}
    pilot = check.get("pilot") if isinstance(check.get("pilot"), Mapping) else {}
    return str(pilot.get("status") or "") in PILOT_WAITING


def initial_pilot(spec: Mapping[str, Any], settings: FactorySettings) -> dict[str, Any]:
    return {"status": "pending", "attempts": 0, "budget": pilot_budget(spec, settings),
            "stage": spec.get("stage"), "registered_at": utc_now()}


def _stage(spec: Mapping[str, Any], *, card: Mapping[str, Any], card_path: Path, out: Path,
           data_root: Path) -> dict[str, Any]:
    from .card_precheck import entry_id_of

    entry_id = entry_id_of(card)
    values = {"entry_id": entry_id, "tic": entry_id[3:] if entry_id.upper().startswith("TIC")
              else entry_id, "card": str(card_path), "out": str(out),
              "line": str(card.get("research_line") or ""),
              "template": str(card.get("paper_template") or ""), "data": str(data_root)}
    raw = spec.get("stage")
    argv = [str(item) for item in raw] if isinstance(raw, list) else shlex.split(str(raw or ""))
    command = [item.format(**values) for item in argv]
    out.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(  # noqa: S603 - the line's own declared command, no shell
        command, cwd=str(spec.get("cwd") or out), capture_output=True, text=True,
        timeout=STAGE_TIMEOUT_SECONDS, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"stage exited {completed.returncode}: {completed.stderr[-400:]}")
    text = completed.stdout.strip()
    try:
        printed = json.loads(text[text.rfind("\n{") + 1:] if "\n{" in text else text) if text \
            else {}
    except ValueError:
        printed = {}
    printed = printed if isinstance(printed, dict) else {}
    source = Path(str(printed.get("source") or out))
    job_argv = printed.get("argv") if isinstance(printed.get("argv"), list) else ["bash", "run.sh"]
    return {"source": source, "argv": [str(item) for item in job_argv]}


def _read_verdict(view: Mapping[str, Any], verdict_file: str) -> dict[str, Any] | None:
    result_dir = Path(str(view.get("result_dir") or ""))
    for candidate in (result_dir / "outputs" / verdict_file, result_dir / verdict_file):
        try:
            value = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    return None


def _used_core_hours(view: Mapping[str, Any], pilot: Mapping[str, Any]) -> float | None:
    from .remote_wait import _parse

    started = _parse(pilot.get("submitted_at"))
    ended = _parse(view.get("updated_at"))
    cpus = int((pilot.get("budget") or {}).get("cpus") or 0)
    if started is None or ended is None or cpus <= 0:
        return None
    return round(max(0.0, (ended - started).total_seconds()) / 3600 * cpus, 2)


def advance_pilots(db: FactoryDB, paths: WorkspacePaths, settings: FactorySettings,
                   report: Any, *, queue_root: Path | None = None,
                   submit: Any = None) -> list[dict[str, Any]]:
    """Submit pending pilots (within the concurrency cap) and judge finished ones."""

    from . import remote_wait
    from .program import open_topic_ledger, record_topic_note, reject_topic
    from .research_lines import read_lines_or_none

    supply = _supply(settings)
    if not supply.pilot:
        return []
    ledger = open_topic_ledger(paths, settings.program)
    waiting = [topic for topic in ledger.read().get("topics") or []
               if isinstance(topic, Mapping) and topic.get("status") == "proposed"
               and pilot_held(topic)]
    if not waiting:
        return []
    root = queue_root or remote_wait.default_queue_root()
    if submit is None:
        from .remote_compute import submit as remote_submit

        def submit(source: Path, argv: list[str], **kwargs: Any) -> Any:
            return remote_submit(source, argv, backend="ailab", queue_root=root, **kwargs)

    document = read_lines_or_none(paths.data / settings.program.research_lines_path)
    outcomes: list[dict[str, Any]] = []
    running = sum(1 for topic in waiting
                  if topic["card_check"]["pilot"].get("status") == "submitted")

    def record(topic: Mapping[str, Any], pilot: dict[str, Any], event: str) -> None:
        check = {**dict(topic.get("card_check") or {}), "pilot": pilot}
        record_topic_note(ledger, str(topic["topic_id"]), db=db, event_type="card_pilot_recorded",
                          reason=event, decided_by="orchestrator:admission_pilot",
                          detail={key: pilot.get(key) for key in (
                              "status", "job_id", "attempts", "verdict", "used_core_hours",
                              "reasons", "error")},
                          updates={"card_check": check},
                          key=f"card_pilot:{topic['topic_id']}:{event}:{pilot.get('attempts')}:"
                              f"{pilot.get('job_id')}")

    for topic in waiting:
        topic_id = str(topic["topic_id"])
        pilot = copy.deepcopy(dict(topic["card_check"]["pilot"]))
        if pilot.get("status") == "submitted":
            view = remote_wait.job_state(root, str(pilot.get("job_id") or ""))
            if not remote_wait.is_terminal(view):
                outcomes.append({"topic_id": topic_id, "status": "running",
                                 "job_id": pilot.get("job_id")})
                continue
            running -= 1
            verdict = _read_verdict(view, str(pilot["budget"].get("verdict_file")))
            pilot["finished_at"] = utc_now()
            pilot["job_state"] = view.get("state")
            pilot["used_core_hours"] = _used_core_hours(view, pilot)
            decided = str((verdict or {}).get("verdict") or "").strip().lower()
            if view.get("state") == "succeeded" and decided in {"pass", "fail", "failed"}:
                pilot.update(status="pass" if decided == "pass" else "fail", verdict=decided,
                             metrics=(verdict or {}).get("metrics"),
                             reasons=[str(item)[:300] for item in
                                      ((verdict or {}).get("reasons") or [])][:10])
                record(topic, pilot, f"card_pilot_{pilot['status']}")
                if pilot["status"] == "fail":
                    reject_topic(ledger, topic_id, db=db, reason=PILOT_REJECTION,
                                 decided_by="orchestrator:admission_pilot")
                outcomes.append({"topic_id": topic_id, "status": pilot["status"],
                                 "job_id": pilot.get("job_id")})
                continue
            pilot["error"] = (f"job {pilot.get('job_id')} ended {view.get('state')}"
                              + ("" if verdict is not None else "; no readable verdict file"))
            pilot["status"] = "pending"
            if int(pilot.get("attempts") or 0) >= supply.pilot_max_attempts:
                pilot["status"] = "unavailable"
                record(topic, pilot, "card_pilot_unavailable")
                reject_topic(ledger, topic_id, db=db, reason=PILOT_UNAVAILABLE,
                             decided_by="orchestrator:admission_pilot")
                outcomes.append({"topic_id": topic_id, "status": "unavailable",
                                 "error": pilot["error"]})
                continue
            record(topic, pilot, "card_pilot_retry")
        if running >= supply.pilot_max_concurrent:
            outcomes.append({"topic_id": topic_id, "status": "pending",
                             "reason": "pilot_max_concurrent"})
            continue
        from .card_precheck import line_specs

        card_path = Path(str(topic.get("card_path") or ""))
        try:
            card = json.loads(card_path.read_text(encoding="utf-8"))
            line_entry, template_entry = line_specs(document, card)
            spec = pilot_spec(line_entry, template_entry, str(card.get("paper_template") or ""))
            if spec is None:
                raise RuntimeError("the line no longer declares an admission_pilot")
            budget = pilot_budget(spec, settings)
            attempt = int(pilot.get("attempts") or 0) + 1
            out = (paths.program_control / "pilots" / topic_id / f"attempt-{attempt}")
            staged = _stage(spec, card=card, card_path=card_path, out=out, data_root=paths.data)
            submission = submit(staged["source"], staged["argv"], cpu_threads=budget["cpus"],
                                memory_mib=budget["memory_mib"],
                                wall_seconds=budget["wall_seconds"])
            pilot.update(status="submitted", attempts=attempt, budget=budget,
                         job_id=str(getattr(submission, "job_id", submission)),
                         submitted_at=utc_now(), backend="ailab")
            pilot.pop("error", None)
            running += 1
            record(topic, pilot, "card_pilot_submitted")
            outcomes.append({"topic_id": topic_id, "status": "submitted",
                             "job_id": pilot["job_id"], "cpus": budget["cpus"],
                             "core_hours_budget": budget["core_hours_budget"]})
        except Exception as exc:  # noqa: BLE001 - reported; retried on later ticks
            attempt = int(pilot.get("attempts") or 0) + 1
            pilot.update(attempts=attempt, error=f"could not stage or submit: {exc}"[:500])
            if attempt >= supply.pilot_max_attempts:
                pilot["status"] = "unavailable"
                record(topic, pilot, "card_pilot_unavailable")
                reject_topic(ledger, topic_id, db=db, reason=PILOT_UNAVAILABLE,
                             decided_by="orchestrator:admission_pilot")
            else:
                record(topic, pilot, "card_pilot_error")
            if hasattr(report, "errors"):
                report.errors.append(f"Admission pilot of {topic_id}: {pilot['error']}")
            outcomes.append({"topic_id": topic_id, "status": pilot["status"],
                             "error": pilot["error"]})
    return outcomes


# --------------------------------------------------------------------------- intake


def screen_card(
    paths: WorkspacePaths,
    settings: FactorySettings,
    card: Mapping[str, Any],
    line_entry: Mapping[str, Any],
    template_entry: Mapping[str, Any],
    ledger_document: Mapping[str, Any],
) -> tuple[str | None, list[str], dict[str, Any]]:
    """``(rejection reason, errors, card_check additions)`` of the intake screens."""

    supply = _supply(settings)
    extra: dict[str, Any] = {}
    key = target_key(card)
    queue = template_entry.get("candidate_queue")
    if key:
        extra["target"] = key
        digest = entry_digest(queue, key) if queue else None
        if digest:
            extra["entry_digest"] = digest
    if supply.target_memory:
        repeat = repeat_failure(ledger_document, card, template_entry)
        if repeat is not None:
            return REPEAT_REJECTION, [f"{REPEAT_REJECTION}: {repeat}"], extra
    if supply.capability_screen:
        problems = capability_problems(paths, settings, card, line_entry, template_entry)
        if problems:
            return CAPABILITY_REJECTION, [f"{CAPABILITY_REJECTION}: {item}"
                                          for item in problems], extra
    if supply.data_screen:
        problems, rows = data_problems(paths, settings, card, line_entry, template_entry)
        if rows:
            extra["data_coverage"] = rows
        if problems:
            return DATA_REJECTION, [f"{DATA_REJECTION}: {item}" for item in problems], extra
    return None, [], extra


__all__ = [
    "CAPABILITY_REJECTION", "DATA_REJECTION", "MECHANICAL_REJECTIONS", "PILOT_REJECTION",
    "PILOT_UNAVAILABLE", "REPEAT_REJECTION", "SCREEN_REJECTIONS", "advance_pilots",
    "capability_problems", "capability_status", "data_problems", "entry_digest",
    "failed_targets", "file_columns", "file_profile", "initial_pilot", "pilot_budget",
    "pilot_held", "pilot_spec", "repeat_failure", "requirement_coverage", "screen_card", "target_key",
    "target_registry",
]
