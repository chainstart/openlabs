"""Line-level shared facts, kept apart from the topics that use them (2026-11-20, W1 item 1).

A research line's shared reference (the control reproduction every topic of the astro line
cites, ``environment.standard_solver.control_receipt``) belongs to the line, not to a topic.
On 2026-11-14/15 six topics were frozen one by one because the shared control's inclination
missed a 2-degree tolerance by 0.008 degrees (its posterior error was about 1.1 degrees), and
three more because that control job was still queued when their precheck budget ran out.

When a topic's owner asks for a ``feasibility_precheck_failed`` freeze this module decides,
before the freeze is applied (``program_autonomy._on_research_result``):

1. **Reference still running.** A compute job the result names is still queued or running
   and the primary endpoint was not judged ``failed``: the freeze is not applied; the topic
   parks on the job like an ``awaiting_remote`` yield (queue time never counts against the
   precheck budget) and resumes with the job's outcome. At most
   ``[program.supply].reference_wait_max`` times per topic.
2. **Borderline.** The failed criteria (declared ``gate_result.failed_criteria`` or the
   ``delta``/``tolerance`` objects of the result's JSON evidence) miss by less than the
   measurement's own uncertainty, or, without an uncertainty field, by at most
   ``borderline_relative_margin`` x the tolerance. Every failed criterion must be borderline.
3. **Shared.** The failed criterion cites the line's shared reference: the jobs, tag or path
   of the line's control receipt, an entry of the line's optional ``shared_references``, a
   ``line_reference`` the result declares, or a compute job another topic of the same line
   also cites in its recorded results.

Shared (borderline or not): the line is blocked (``program_line_block:<line>`` in the factory
database meta table: no scout, no admission review and no new campaign for the line), the
topic stays active and gets one direction decision (trigger ``line_reference_review``) that
chooses between one targeted re-run/review of the reference and a freeze; every other topic
that then reports a failure against the same reference waits (``program_line_wait:<campaign>``,
no new task) instead of being frozen. The block is released when the representative topic
reports progress past its precheck (owner ``phase`` solving/writing) after a targeted
analysis, when the line's control receipt changes, or by ``program line-block --clear``; the
waiting topics then get an owner seat that says so. A block whose representative was frozen
is ``confirmed`` and stays until the receipt changes or an operator clears it; after
``line_block_max_days`` each waiting topic gets its own direction decision.

Not shared but borderline: one direction decision (trigger ``criterion_borderline``) instead
of the freeze. Everything else freezes as before. The decision agents keep the final word
(another model family), and the pre-registered endpoint is never touched.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import FactorySettings, WorkspacePaths
from .db import FactoryDB, utc_now

BLOCK_PREFIX = "program_line_block:"
WAIT_PREFIX = "program_line_wait:"
REFERENCE_WAIT_PREFIX = "program_reference_wait:"
TRIGGER_LINE_REFERENCE = "line_reference_review"
TRIGGER_BORDERLINE = "criterion_borderline"
TRIGGER_BLOCK_EXPIRED = "line_block_expired"
TRIGGERS = (TRIGGER_LINE_REFERENCE, TRIGGER_BORDERLINE, TRIGGER_BLOCK_EXPIRED)
FREEZE_CLASS = "feasibility_precheck_failed"
RECEIPT_KEY = "environment.standard_solver.control_receipt"
ROUTING_RELEASED = "owner_line_block_released"
PROGRESS_PHASES = frozenset({"solving", "writing"})
JOB_ID = re.compile(r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])")
_QUEUED_TEXT = re.compile(
    r"\b(still|remained|remains|was|stayed) (queued|running|in the queue)\b",
    re.IGNORECASE)
# "difference 2.00837756 degrees exceeds 2 degrees", "|di| = 2.008 > 2 deg": a stated miss of
# a numeric limit (the text fallback when a result carries no structured criterion).
_MISS_TEXT = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?:deg(?:rees?)?|degree|per ?cent|%)?\s*"
    r"(?:exceeds?|exceeded|>|is beyond|beyond|above|over)\s*"
    r"(?:[A-Za-z'-]+\s*){0,4}?(?P<limit>\d+(?:\.\d+)?)",
    re.IGNORECASE)
_TOLERANCE_KEYS = ("tolerance_abs", "tolerance", "tol", "threshold_abs")
_SYMMETRIC_ERROR_KEYS = ("uncertainty", "sigma", "error", "err", "std", "stderr")
_SIDED_ERROR_KEYS = (("ours_plus", "ours_minus"), ("plus", "minus"), ("err_plus", "err_minus"),
                     ("sigma_plus", "sigma_minus"), ("upper_error", "lower_error"))
MAX_ARTIFACTS = 80
MAX_ARTIFACT_BYTES = 2_000_000


# --------------------------------------------------------------------------- helpers


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _uri_path(value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith("file://"):
        text = text[len("file://"):]
    path = Path(text)
    return path if path.is_absolute() else None


def _read_json(path: Path) -> Any:
    try:
        if not path.is_file() or path.stat().st_size > MAX_ARTIFACT_BYTES:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


DEFAULT_LINE_FACTS = True
DEFAULT_BORDERLINE_MARGIN = 0.05
DEFAULT_REFERENCE_WAIT_MAX = 2
DEFAULT_LINE_BLOCK_MAX_DAYS = 7.0


def supply_settings(settings: FactorySettings) -> Any:
    return settings.program.supply


def _line_facts_enabled(settings: FactorySettings) -> bool:
    return bool(getattr(supply_settings(settings), "line_facts", DEFAULT_LINE_FACTS))


def _reference_wait_max(settings: FactorySettings) -> int:
    return int(getattr(supply_settings(settings), "reference_wait_max", DEFAULT_REFERENCE_WAIT_MAX))


def _borderline_margin(settings: FactorySettings) -> float:
    return float(getattr(supply_settings(settings), "borderline_relative_margin",
                         DEFAULT_BORDERLINE_MARGIN))


def _line_block_max_days(settings: FactorySettings) -> float:
    return float(getattr(supply_settings(settings), "line_block_max_days",
                         DEFAULT_LINE_BLOCK_MAX_DAYS))


def result_view(payload: Mapping[str, Any]) -> dict[str, Any]:
    """The result with an owner packet's own fields folded in (owner-mode seats keep
    ``remote_compute``, ``failed_criteria``, ``claims`` and the like in ``owner_packet``)."""

    packet = payload.get("owner_packet")
    if not isinstance(packet, Mapping):
        return dict(payload)
    view = {**{key: value for key, value in packet.items() if key not in {"status"}},
            **{key: value for key, value in payload.items() if value not in (None, [], "")}}
    gate: dict[str, Any] = {}
    for source in (packet.get("gate_result"), payload.get("gate_result")):
        if isinstance(source, Mapping):
            gate.update(source)
    for key in ("failed_criteria", "line_reference"):
        if key in packet and key not in gate:
            gate[key] = packet[key]
    if gate:
        view["gate_result"] = gate
    return view


# --------------------------------------------------------------------------- criteria


def result_json_artifacts(payload: Mapping[str, Any], *, base: Path | None = None
                          ) -> list[tuple[str, Any]]:
    """``(path, parsed JSON)`` of the JSON evidence the result's gate decision cites.

    Only the artifacts ``gate_result.evidence`` names (by artifact id, file name or path)
    are read: a result usually carries many comparisons, and only the ones its gate rests
    on say why it stopped.
    """

    gate = payload.get("gate_result")
    evidence = gate.get("evidence") if isinstance(gate, Mapping) else None
    if isinstance(evidence, (str, Mapping)):
        evidence = [evidence]
    named: set[str] = set()
    candidates: list[Any] = []
    for item in evidence if isinstance(evidence, list) else []:
        if isinstance(item, Mapping):
            candidates.append(item.get("uri") or item.get("path"))
            for key in ("artifact_id", "id"):
                if item.get(key):
                    named.add(str(item[key]))
        elif isinstance(item, str) and item.strip():
            text = item.strip()
            named.update({text, Path(text).name, Path(text).stem})
            candidates.append(text)
    if named:
        for item in payload.get("artifacts") or []:
            if not isinstance(item, Mapping):
                continue
            uri = str(item.get("uri") or item.get("path") or "")
            if str(item.get("artifact_id") or "") in named or (uri and (
                    uri in named or Path(uri).name in named)):
                candidates.append(uri)
    seen: set[str] = set()
    found: list[tuple[str, Any]] = []
    for value in candidates:
        path = _uri_path(value)
        if path is None and base is not None and str(value or "").strip():
            path = base / str(value)
        if path is None or path.suffix.lower() != ".json" or str(path) in seen:
            continue
        seen.add(str(path))
        document = _read_json(path)
        if document is not None:
            found.append((str(path), document))
        if len(found) >= MAX_ARTIFACTS:
            break
    return found


def _uncertainty(item: Mapping[str, Any], delta: float) -> float | None:
    """The measurement error on the side that moves the value toward the tolerance."""

    for plus_key, minus_key in _SIDED_ERROR_KEYS:
        plus, minus = _number(item.get(plus_key)), _number(item.get(minus_key))
        if plus is None and minus is None:
            continue
        toward = minus if delta > 0 else plus
        value = toward if toward is not None else (plus if plus is not None else minus)
        return abs(value) if value is not None else None
    for key in _SYMMETRIC_ERROR_KEYS:
        value = _number(item.get(key))
        if value is not None:
            return abs(value)
    return None


def _first_number(item: Mapping[str, Any], exact: tuple[str, ...],
                  prefixes: tuple[str, ...] = ()) -> float | None:
    for key in exact:
        value = _number(item.get(key))
        if value is not None:
            return value
    for key, raw in item.items():
        if str(key).startswith(prefixes) and (value := _number(raw)) is not None:
            return value
    return None


_DELTA_KEYS = ("delta", "difference", "absolute_difference", "abs_difference", "abs_delta")
_DELTA_PREFIXES = ("absolute_difference", "abs_difference", "delta_")
_LIMIT_PREFIXES = ("tolerance", "maximum_allowed", "max_allowed", "threshold", "limit_")


def _criterion(name: str, item: Mapping[str, Any], source: str) -> dict[str, Any] | None:
    """A difference-and-tolerance (or ``value``/``limit``) object as a criterion, else None."""

    delta = _first_number(item, _DELTA_KEYS, _DELTA_PREFIXES)
    tolerance = _first_number(item, (*_TOLERANCE_KEYS, "maximum_allowed", "limit"),
                              _LIMIT_PREFIXES)
    excess: float | None = None
    if delta is not None and tolerance is not None:
        excess = abs(delta) - abs(tolerance)
    else:
        value, limit = _number(item.get("value")), _number(item.get("limit"))
        direction = str(item.get("direction") or "max").lower()
        if value is None or limit is None:
            return None
        delta = value - limit
        tolerance = abs(limit)
        excess = delta if direction != "min" else -delta
    passed = item.get("pass_tolerance", item.get("pass", item.get("passed")))
    failed = passed is False or (passed is not True and excess > 0)
    uncertainty = _number(item.get("uncertainty"))
    if uncertainty is None:
        uncertainty = _uncertainty(item, delta)
    label = str(item.get("parameter") or item.get("name") or name)
    return {"name": label, "delta": delta, "tolerance": tolerance, "excess": excess,
            "uncertainty": uncertainty, "failed": bool(failed), "source": source,
            **({"reference": item["reference"]} if isinstance(item.get("reference"), Mapping)
               else {})}


def _looks_like_criterion(item: Mapping[str, Any]) -> bool:
    keys = [str(key) for key in item]
    has_delta = any(key in _DELTA_KEYS or key.startswith(_DELTA_PREFIXES) for key in keys)
    has_limit = any(key in _TOLERANCE_KEYS or key in {"maximum_allowed", "limit"}
                    or key.startswith(_LIMIT_PREFIXES) for key in keys)
    return has_delta and has_limit


def _walk(document: Any, source: str, name: str = "", depth: int = 0
          ) -> Iterable[dict[str, Any]]:
    if depth > 8:
        return
    if isinstance(document, Mapping):
        if _looks_like_criterion(document):
            found = _criterion(name or "criterion", document, source)
            if found is not None:
                yield found
                return
        for key, value in document.items():
            yield from _walk(value, source, str(key), depth + 1)
    elif isinstance(document, list):
        for value in document[:200]:
            yield from _walk(value, source, name, depth + 1)


def criteria_of(payload: Mapping[str, Any],
                artifacts: list[tuple[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Every criterion a result states: declared ``failed_criteria`` first, then evidence."""

    found: list[dict[str, Any]] = []
    gate = payload.get("gate_result")
    declared = gate.get("failed_criteria") if isinstance(gate, Mapping) else None
    for index, item in enumerate(declared if isinstance(declared, list) else []):
        if isinstance(item, Mapping):
            criterion = _criterion(str(item.get("name") or f"criterion-{index}"), item,
                                   "gate_result.failed_criteria")
            if criterion is not None:
                criterion["failed"] = item.get("pass") is not True and item.get(
                    "passed") is not True
                found.append(criterion)
    if isinstance(gate, Mapping):
        found.extend(item for item in _walk({key: value for key, value in gate.items()
                                             if key != "failed_criteria"}, "gate_result")
                     if item["failed"])
    for path, document in artifacts if artifacts is not None else result_json_artifacts(payload):
        found.extend(_walk(document, path))
    if not found:
        found.extend(_text_criteria(payload))
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in found:
        key = (item["name"], round(float(item["delta"]), 9), round(float(item["tolerance"]), 9))
        unique.setdefault(key, item)
    return list(unique.values())


def _text_criteria(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Misses stated only in words (summary, gate reason): value, limit, no uncertainty."""

    gate = payload.get("gate_result") if isinstance(payload.get("gate_result"), Mapping) else {}
    texts = [str(payload.get("summary") or ""), str(gate.get("reason") or ""),
             str(gate.get("rationale") or "")]
    found: list[dict[str, Any]] = []
    for text in texts:
        for match in _MISS_TEXT.finditer(text):
            value, limit = float(match.group("value")), float(match.group("limit"))
            if limit <= 0 or value <= limit:
                continue
            found.append({"name": "stated_limit", "delta": value, "tolerance": limit,
                          "excess": value - limit, "uncertainty": None, "failed": True,
                          "source": "text", "quote": match.group(0)[:120]})
        if found:
            break
    return found


def classify(criteria: list[Mapping[str, Any]], margin: float) -> dict[str, Any]:
    """``verdict``: ``borderline`` (every failed criterion), ``failed`` or ``none``."""

    items: list[dict[str, Any]] = []
    for criterion in criteria:
        if not criterion.get("failed"):
            continue
        excess = float(criterion["excess"])
        uncertainty = criterion.get("uncertainty")
        if uncertainty is not None:
            borderline = excess < float(uncertainty)
            basis = "measurement_uncertainty"
        else:
            borderline = excess <= margin * abs(float(criterion["tolerance"]))
            basis = f"relative_margin_{margin:g}"
        items.append({**dict(criterion), "borderline": bool(borderline), "basis": basis})
    if not items:
        return {"verdict": "none", "items": []}
    verdict = "borderline" if all(item["borderline"] for item in items) else "failed"
    return {"verdict": verdict, "items": items}


# --------------------------------------------------------------------------- references


def _dotted(document: Any, key: str) -> Any:
    value = document
    for part in key.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def _aliases(tag: str) -> list[str]:
    text = tag.strip()
    if not text:
        return []
    match = re.fullmatch(r"([A-Za-z]+)\s*[-_ ]?\s*(\d+)", text)
    if match:
        prefix, digits = match.groups()
        return sorted({f"{prefix}{digits}", f"{prefix} {digits}", f"{prefix}-{digits}"})
    return [text]


def line_references(paths: WorkspacePaths, settings: FactorySettings,
                    line: str) -> list[dict[str, Any]]:
    """Shared references a line declares: its control receipt and ``shared_references``."""

    from .research_lines import line_entry, read_lines_or_none

    document = read_lines_or_none(paths.data / settings.program.research_lines_path)
    entry = line_entry(document, line) if document and line else None
    if not entry:
        return []
    references: list[dict[str, Any]] = []
    receipt = _dotted(entry, RECEIPT_KEY)
    if isinstance(receipt, str) and receipt.strip():
        reference = {"id": f"{line}:control_receipt", "receipt": receipt.strip(),
                     "job_ids": [], "aliases": []}
        body = _read_json(Path(receipt.strip()))
        if isinstance(body, Mapping):
            ids = [body.get("job_id"), *(body.get("all_job_ids") or [])]
            ids += [item.get("job_id") for item in body.get("history") or []
                    if isinstance(item, Mapping)]
            reference["job_ids"] = sorted({str(item) for item in ids
                                           if isinstance(item, str) and JOB_ID.fullmatch(item)})
            reference["aliases"] = _aliases(str(body.get("tag") or ""))
        references.append(reference)
    for index, item in enumerate(entry.get("shared_references") or []):
        if not isinstance(item, Mapping):
            continue
        references.append({
            "id": str(item.get("id") or f"{line}:shared-{index}"),
            "receipt": str(item.get("receipt") or "") or None,
            "job_ids": [str(job) for job in item.get("job_ids") or []
                        if JOB_ID.fullmatch(str(job))],
            "aliases": [str(alias) for alias in item.get("aliases") or [] if str(alias).strip()],
        })
    return references


def receipt_fingerprint(reference: Mapping[str, Any]) -> str | None:
    receipt = str(reference.get("receipt") or "")
    if not receipt:
        return None
    try:
        return hashlib.sha256(Path(receipt).read_bytes()).hexdigest()
    except OSError:
        return None


def _failure_texts(payload: Mapping[str, Any], classification: Mapping[str, Any],
                   artifacts: list[tuple[str, Any]]) -> str:
    """Text a failure is stated in: the gate, summary, claims and the failing evidence."""

    parts = [json.dumps(payload.get("gate_result"), default=str, ensure_ascii=False),
             str(payload.get("summary") or "")]
    for claim in payload.get("claims") or []:
        if isinstance(claim, Mapping):
            parts.append(str(claim.get("text") or ""))
    sources = {str(item.get("source")) for item in classification.get("items") or []}
    for path, document in artifacts:
        if path in sources:
            parts.append(json.dumps(document, default=str, ensure_ascii=False)[:200_000])
    return "\n".join(parts)


def other_topic_job_ids(document: Mapping[str, Any], line: str, topic_id: str) -> set[str]:
    """Compute job ids cited by the recorded results of the line's other topics."""

    found: set[str] = set()
    for topic in document.get("topics") or []:
        if (not isinstance(topic, Mapping) or str(topic.get("research_line") or "") != line
                or str(topic.get("topic_id") or "") == topic_id):
            continue
        for item in topic.get("freeze_evidence") or []:
            path = _uri_path(item.get("path") if isinstance(item, Mapping) else None)
            if path is None or path.suffix.lower() != ".json":
                continue
            try:
                if path.stat().st_size > MAX_ARTIFACT_BYTES:
                    continue
                found.update(JOB_ID.findall(path.read_text(encoding="utf-8")))
            except OSError:
                continue
    return found


def shared_reference(
    paths: WorkspacePaths,
    settings: FactorySettings,
    *,
    topic: Mapping[str, Any],
    payload: Mapping[str, Any],
    classification: Mapping[str, Any],
    artifacts: list[tuple[str, Any]],
    ledger_document: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """The line-level reference a failure rests on (None: the failure is the topic's own)."""

    line = str(topic.get("research_line") or "")
    gate = payload.get("gate_result") if isinstance(payload.get("gate_result"), Mapping) else {}
    declared = gate.get("line_reference")
    if isinstance(declared, Mapping) and JOB_ID.fullmatch(str(declared.get("job_id") or "")):
        job = str(declared.get("job_id") or "")
        return {"id": str(declared.get("id") or job), "source": "declared",
                "job_ids": [job] if JOB_ID.fullmatch(job) else []}
    for item in classification.get("items") or []:
        reference = item.get("reference")
        if isinstance(reference, Mapping) and reference.get("shared") is not False and (
                JOB_ID.fullmatch(str(reference.get("job_id") or ""))):
            job = str(reference.get("job_id") or "")
            return {"id": str(reference.get("id") or job), "source": "declared_criterion",
                    "job_ids": [job] if JOB_ID.fullmatch(job) else []}
    if not line:
        return None
    text = _failure_texts(payload, classification, artifacts)
    cited = set(JOB_ID.findall(text))
    for reference in line_references(paths, settings, line):
        hits = sorted(cited & set(reference["job_ids"]))
        alias_hit = next((alias for alias in reference["aliases"] if alias in text), None)
        receipt_hit = bool(reference.get("receipt")) and str(reference["receipt"]) in text
        if hits or alias_hit or receipt_hit:
            return {"id": reference["id"], "source": "line_reference",
                    "job_ids": hits or list(reference["job_ids"]),
                    "receipt": reference.get("receipt"),
                    "matched": hits or alias_hit or reference.get("receipt"),
                    "receipt_sha256": receipt_fingerprint(reference)}
    if ledger_document is not None and cited:
        shared = sorted(cited & other_topic_job_ids(ledger_document, line,
                                                    str(topic.get("topic_id") or "")))
        if shared:
            return {"id": f"{line}:job:{shared[0]}", "source": "cross_topic", "job_ids": shared}
    return None


# --------------------------------------------------------------------------- pending jobs


def named_job_ids(payload: Mapping[str, Any]) -> list[str]:
    """Compute job ids a result names (remote_compute, awaiting_remote, text fields)."""

    texts: list[str] = [str(payload.get("summary") or "")]
    block = payload.get("remote_compute")
    for item in block if isinstance(block, list) else [block]:
        if isinstance(item, Mapping):
            texts.append(str(item.get("job_id") or ""))
            texts.extend(str(job) for job in item.get("job_ids") or [])
    waiting = payload.get("awaiting_remote")
    if isinstance(waiting, Mapping):
        texts.extend(str(job) for job in waiting.get("job_ids") or [])
    for claim in payload.get("claims") or []:
        if isinstance(claim, Mapping):
            texts.append(str(claim.get("text") or ""))
    texts.append(json.dumps(payload.get("gate_result"), default=str))
    for action in payload.get("next_actions") or []:
        texts.append(json.dumps(action, default=str) if isinstance(action, Mapping)
                     else str(action))
    found: list[str] = []
    for text in texts:
        for job in JOB_ID.findall(text):
            if job not in found:
                found.append(job)
    return found


def pending_jobs(payload: Mapping[str, Any], queue_root: Path | None = None) -> list[str]:
    """The named jobs that are still queued or running."""

    from . import remote_wait

    root = queue_root or remote_wait.default_queue_root()
    pending: list[str] = []
    for job in named_job_ids(payload):
        if remote_wait.job_state(root, job)["state"] in {"queued", "running"}:
            pending.append(job)
    return pending


# --------------------------------------------------------------------------- state


def _load(raw: str | None) -> dict[str, Any] | None:
    try:
        value = json.loads(raw) if raw else None
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def blocks(db: FactoryDB) -> dict[str, dict[str, Any]]:
    return {line: value for line, raw in db.meta_items(BLOCK_PREFIX).items()
            if (value := _load(raw)) is not None}


def block_of(db: FactoryDB, line: str) -> dict[str, Any] | None:
    return _load(db.meta_get(BLOCK_PREFIX + line)) if line else None


def waits(db: FactoryDB) -> dict[str, dict[str, Any]]:
    return {campaign: value for campaign, raw in db.meta_items(WAIT_PREFIX).items()
            if (value := _load(raw)) is not None}


def campaign_waiting(db: FactoryDB, campaign_id: str) -> bool:
    return bool(campaign_id) and db.meta_get(WAIT_PREFIX + campaign_id) is not None


def blocked_lines(db: FactoryDB | None) -> dict[str, str]:
    """``{line: "line_blocked:<reason>"}`` of the lines a block currently holds."""

    if db is None:
        return {}
    try:
        current = blocks(db)
    except Exception:  # noqa: BLE001 - advisory: an unreadable view blocks nothing
        return {}
    return {line: f"line_blocked:{record.get('reason') or 'reference'}"
            for line, record in current.items()}


def _signature(criterion: Mapping[str, Any]) -> tuple[float, float]:
    return (round(abs(float(criterion["delta"])), 4), round(abs(float(criterion["tolerance"])), 4))


def _same_reference(record: Mapping[str, Any], reference: Mapping[str, Any]) -> bool:
    old_digest, new_digest = record.get("receipt_sha256"), reference.get("receipt_sha256")
    if old_digest and new_digest and old_digest != new_digest:
        return False
    if str(record.get("reference_id") or "") == str(reference.get("id") or ""):
        return True
    return bool(set(record.get("job_ids") or []) & set(reference.get("job_ids") or []))


# --------------------------------------------------------------------------- interception


def intercept_precheck_freeze(
    db: FactoryDB,
    paths: WorkspacePaths,
    settings: FactorySettings,
    report: Any,
    *,
    topic: Mapping[str, Any],
    task: Mapping[str, Any],
    payload: Mapping[str, Any],
    evidence: list[dict[str, str]],
    reason_class: str,
    result_path: Path | None = None,
    result_sha256: str | None = None,
) -> str | None:
    """``"handled"`` when a requested precheck freeze is replaced (see module doc), else None."""

    if not _line_facts_enabled(settings) or reason_class != FREEZE_CLASS:
        return None
    raw_payload = payload
    payload = result_view(payload)
    topic_id = str(topic["topic_id"])
    task_id = str(task.get("task_id") or "")
    info = report.program.setdefault("line_facts", []) if hasattr(report, "program") else []
    verdict = str(payload.get("primary_endpoint_verdict") or "").strip().lower()
    if verdict != "failed" and result_path is not None and result_sha256:
        jobs = pending_jobs(payload)
        count = int(db.meta_get(REFERENCE_WAIT_PREFIX + topic_id) or 0)
        if jobs and count < _reference_wait_max(settings) and _park(
            db, settings, report, task=task, payload=raw_payload, jobs=jobs,
            result_path=result_path, result_sha256=result_sha256,
        ):
            db.update_meta({REFERENCE_WAIT_PREFIX + topic_id: str(count + 1)})
            _note(paths, settings, db, topic_id, "freeze_deferred_job_pending", task_id,
                  {"job_ids": jobs, "wait": count + 1}, evidence)
            info.append({"topic_id": topic_id, "outcome": "parked_on_pending_job",
                         "job_ids": jobs})
            return "handled"
    from .program import open_topic_ledger

    artifacts = result_json_artifacts(payload)
    classification = classify(criteria_of(payload, artifacts), _borderline_margin(settings))
    if classification["verdict"] == "none":
        return None
    document = open_topic_ledger(paths, settings.program).read()
    reference = shared_reference(paths, settings, topic=topic, payload=payload,
                                 classification=classification, artifacts=artifacts,
                                 ledger_document=document)
    line = str(topic.get("research_line") or "")
    campaign_id = str(topic.get("campaign_id") or "")
    detail = {"classification": classification, "reference": reference}
    if reference is not None and line and campaign_id:
        record = block_of(db, line)
        if record is not None and _same_reference(record, reference) and (
                str(record.get("topic_id")) != topic_id):
            _start_wait(db, line=line, topic_id=topic_id, campaign_id=campaign_id,
                        task_id=task_id, record=record)
            _note(paths, settings, db, topic_id, "line_block_wait", task_id, detail, evidence)
            info.append({"topic_id": topic_id, "outcome": "waits_for_line_block", "line": line,
                         "reference": reference.get("id")})
            return "handled"
        if record is None:
            decision = _schedule(db, paths, settings, report, topic=topic,
                                 trigger=TRIGGER_LINE_REFERENCE, task_id=task_id,
                                 evidence=evidence, detail=detail)
            if decision is None:
                return None
            record = {
                "line": line, "reason": f"reference_{classification['verdict']}",
                "state": "decision_pending", "reference_id": reference.get("id"),
                "reference": reference, "job_ids": list(reference.get("job_ids") or []),
                "receipt_sha256": reference.get("receipt_sha256"), "topic_id": topic_id,
                "campaign_id": campaign_id, "decision_task_id": decision,
                "source_task_id": task_id, "since": utc_now(),
                "classification": classification,
            }
            db.update_meta({BLOCK_PREFIX + line: json.dumps(record, sort_keys=True, default=str)},
                           events=[("program", line, "line_blocked",
                                    {k: record[k] for k in ("reason", "reference_id",
                                                            "topic_id", "decision_task_id")})])
            _note(paths, settings, db, topic_id, "line_block_started", task_id, detail, evidence)
            info.append({"topic_id": topic_id, "outcome": "line_blocked", "line": line,
                         "decision_task_id": decision, "reason": record["reason"]})
            return "handled"
        # A block on another reference stands: this failure is judged on its own below.
    if classification["verdict"] == "borderline":
        decision = _schedule(db, paths, settings, report, topic=topic,
                             trigger=TRIGGER_BORDERLINE, task_id=task_id, evidence=evidence,
                             detail=detail)
        if decision is not None:
            info.append({"topic_id": topic_id, "outcome": "borderline_direction_decision",
                         "decision_task_id": decision})
            return "handled"
    return None


def _park(db: FactoryDB, settings: FactorySettings, report: Any, *, task: Mapping[str, Any],
          payload: Mapping[str, Any], jobs: list[str], result_path: Path,
          result_sha256: str) -> bool:
    from .engine import _park_for_remote_jobs

    objective = (
        "The orchestrator did not apply the feasibility-precheck freeze of the last attempt: "
        f"compute job(s) {', '.join(jobs)} named in its result were still queued or running. "
        "Time a job spends queued or running does not count against the precheck budget "
        "(research_state.json precheck_clock). Their outcomes are listed above; finish the "
        "precheck with them and decide again (pass, or freeze with the evidence)."
    )
    parked = {**dict(payload), "awaiting_remote": {"job_ids": jobs,
                                                   "resume_objective": objective}}
    try:
        return bool(_park_for_remote_jobs(
            db, settings, report, task=task, payload=parked,
            attempt_id=str(task.get("current_attempt_id") or ""), result_path=result_path,
            result_sha256=result_sha256, final_status="yielded", next_plan=None,
            has_room=True,
        ))
    except Exception as exc:  # noqa: BLE001 - fall back to the requested freeze
        if hasattr(report, "errors"):
            report.errors.append(f"Could not park {task.get('task_id')} on {jobs}: {exc}")
        return False


def _note(paths: WorkspacePaths, settings: FactorySettings, db: FactoryDB, topic_id: str,
          event: str, task_id: str, detail: Mapping[str, Any],
          evidence: list[dict[str, str]]) -> None:
    from .program import open_topic_ledger, record_topic_note

    record_topic_note(open_topic_ledger(paths, settings.program), topic_id, db=db,
                      event_type=event, reason=event, decided_by=f"orchestrator:{event}",
                      detail=json.loads(json.dumps(dict(detail), default=str)),
                      evidence=evidence, key=f"{event}:{task_id}")


def _reasons(detail: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    classification = detail.get("classification") or {}
    for item in classification.get("items") or []:
        reasons.append(
            f"Criterion {item.get('name')}: |delta| {abs(float(item['delta'])):.6g} against "
            f"tolerance {float(item['tolerance']):.6g} (excess {float(item['excess']):.6g}; "
            + (f"measurement uncertainty {float(item['uncertainty']):.6g}"
               if item.get("uncertainty") is not None else "no uncertainty stated")
            + f"; {'borderline' if item.get('borderline') else 'clear failure'})."
        )
    reference = detail.get("reference")
    if isinstance(reference, Mapping):
        jobs = ", ".join(reference.get("job_ids") or []) or "none named"
        reasons.append(
            f"The failed criterion rests on the line's shared reference {reference.get('id')} "
            f"(found by {reference.get('source')}; jobs {jobs}). It belongs to the research "
            "line, not to this topic: other topics of the line wait on this decision instead "
            "of being frozen one by one.")
    return reasons


def _schedule(db: FactoryDB, paths: WorkspacePaths, settings: FactorySettings, report: Any, *,
              topic: Mapping[str, Any], trigger: str, task_id: str,
              evidence: list[dict[str, str]], detail: Mapping[str, Any]) -> str | None:
    from .program_autonomy import schedule_direction_decision

    return schedule_direction_decision(
        db, paths, settings, report, topic=topic, trigger=trigger, source_task_id=task_id,
        evidence=evidence, reasons=_reasons(detail),
        detail=json.loads(json.dumps(dict(detail), default=str)),
    )


def _start_wait(db: FactoryDB, *, line: str, topic_id: str, campaign_id: str, task_id: str,
                record: Mapping[str, Any]) -> None:
    db.update_meta(
        {WAIT_PREFIX + campaign_id: json.dumps({
            "line": line, "topic_id": topic_id, "campaign_id": campaign_id,
            "source_task_id": task_id, "since": utc_now(),
            "reference_id": record.get("reference_id"),
        }, sort_keys=True)},
        events=[("topic", topic_id, "line_block_wait_started",
                 {"line": line, "reference_id": record.get("reference_id"),
                  "source_task_id": task_id})],
    )


# --------------------------------------------------------------------------- lifecycle


def trigger_reason_text(trigger: str, detail: Mapping[str, Any]) -> str | None:
    if trigger == TRIGGER_LINE_REFERENCE:
        return ("The topic's feasibility precheck failed on the research line's shared reference "
                "(not on the topic's own data). Decide whether one targeted re-run or review of "
                "that reference is warranted, or whether the topic must be frozen.")
    if trigger == TRIGGER_BORDERLINE:
        return ("The feasibility precheck missed its criterion by less than the measurement's own "
                "uncertainty (or within the configured relative margin): a borderline result. "
                "Decide whether one targeted re-run or review settles it, or freeze.")
    if trigger == TRIGGER_BLOCK_EXPIRED:
        return (f"The topic waited {detail.get('days')} days for the line-level block on "
                f"{detail.get('reference_id')} to clear. Decide how it continues or freeze it.")
    return None


def after_decision(db: FactoryDB, paths: WorkspacePaths, settings: FactorySettings, report: Any,
                   *, topic_id: str, trigger: str, outcome: str) -> None:
    """Move the line block whose representative a resolved decision concerned."""

    if trigger != TRIGGER_LINE_REFERENCE:
        return
    for line, record in blocks(db).items():
        if str(record.get("topic_id")) != topic_id:
            continue
        state = ("confirmed" if outcome in {"frozen", "rejected_frozen"}
                 else "under_review" if outcome == "executed" else str(record.get("state")))
        if state == record.get("state"):
            continue
        record = {**record, "state": state, "state_at": utc_now()}
        db.update_meta({BLOCK_PREFIX + line: json.dumps(record, sort_keys=True, default=str)},
                       events=[("program", line, "line_block_" + state,
                                {"topic_id": topic_id, "outcome": outcome})])


def on_progress(db: FactoryDB, paths: WorkspacePaths, settings: FactorySettings, report: Any,
                *, topic: Mapping[str, Any], payload: Mapping[str, Any]) -> bool:
    """Release a block whose representative now reports progress past its precheck."""

    if not _line_facts_enabled(settings):
        return False
    line = str(topic.get("research_line") or "")
    record = block_of(db, line)
    if record is None or str(record.get("topic_id")) != str(topic.get("topic_id")):
        return False
    if str(record.get("state")) != "under_review":
        return False
    packet = payload.get("owner_packet") if isinstance(payload.get("owner_packet"), Mapping) else {}
    phase = str(packet.get("phase") or payload.get("phase") or "").strip().lower()
    gate = payload.get("gate_result") if isinstance(payload.get("gate_result"), Mapping) else {}
    if phase not in PROGRESS_PHASES and str(gate.get("promotion_decision") or "").lower() not in {
            "promote", "pass", "continue"}:
        return False
    release(db, paths, settings, report, line=line,
            reason=f"representative {topic.get('topic_id')} passed its precheck (phase {phase})")
    return True


def release(db: FactoryDB, paths: WorkspacePaths, settings: FactorySettings, report: Any, *,
            line: str, reason: str, by: str = "orchestrator") -> dict[str, Any]:
    """Clear a line block and give each waiting topic its next seat."""

    from . import owner as owner_mode

    record = block_of(db, line) or {}
    released: list[str] = []
    for campaign_id, wait in waits(db).items():
        if str(wait.get("line")) != line:
            continue
        db.update_meta({WAIT_PREFIX + campaign_id: None},
                       events=[("topic", str(wait.get("topic_id")), "line_block_wait_released",
                                {"line": line, "reason": reason, "by": by})])
        released.append(str(wait.get("topic_id")))
        campaign = db.campaign(campaign_id)
        if (campaign is None or str(campaign.get("status") or "") != "active"
                or db.has_active_tasks(campaign_id) or db.has_queued_tasks(campaign_id)
                or not owner_mode.applies(settings, campaign)):
            continue  # ordinary replenishment takes it from here
        parent = db.task(str(wait.get("source_task_id") or "")) or db.latest_task(campaign_id)
        owner_mode.enqueue_seat(
            db, settings, report, campaign=campaign, parent=parent,
            note=(f"The line-level block on {record.get('reference_id') or 'the shared reference'}"
                  f" was cleared ({reason}). Your earlier feasibility-precheck freeze request "
                  f"({wait.get('source_task_id')}) was not applied because its failure rested on "
                  "that shared reference. Re-check the reference's current receipt, then finish "
                  "the precheck against the pre-registered criterion and decide again."),
            routing_reason=ROUTING_RELEASED,
            task_id=owner_mode.seat_id(campaign_id, f"line-release:{line}:{record.get('since')}"),
        )
    db.update_meta({BLOCK_PREFIX + line: None},
                   events=[("program", line, "line_block_released",
                            {"reason": reason, "by": by, "released_topics": released})])
    entry = {"line": line, "reason": reason, "by": by, "released_topics": released}
    if hasattr(report, "program"):
        report.program.setdefault("line_blocks_released", []).append(entry)
    return entry


def tick(db: FactoryDB, paths: WorkspacePaths, settings: FactorySettings, report: Any) -> None:
    """Per tick: release on receipt change, expire long waits, drop stale waits, report."""

    if not settings.program.enabled:
        return
    from .program import FREEZABLE_STATUSES, find_topic, open_topic_ledger

    document = open_topic_ledger(paths, settings.program).read()
    current_waits = waits(db)
    for campaign_id, wait in current_waits.items():
        topic = find_topic(document, str(wait.get("topic_id") or "")) or {}
        if topic.get("status") not in FREEZABLE_STATUSES:
            db.update_meta({WAIT_PREFIX + campaign_id: None},
                           events=[("topic", str(wait.get("topic_id")), "line_block_wait_dropped",
                                    {"status": topic.get("status")})])
    max_age = timedelta(days=_line_block_max_days(settings))
    for line, record in blocks(db).items():
        reference = record.get("reference") if isinstance(record.get("reference"), Mapping) else {}
        before = record.get("receipt_sha256")
        if before and reference.get("receipt"):
            now_sha = receipt_fingerprint(reference)
            if now_sha and now_sha != before:
                release(db, paths, settings, report, line=line,
                        reason="the line's reference receipt changed")
                continue
        since = _parse_time(record.get("since"))
        if since is None or _now() - since < max_age:
            continue
        for campaign_id, wait in waits(db).items():
            if str(wait.get("line")) != line:
                continue
            topic = find_topic(document, str(wait.get("topic_id") or ""))
            if topic is None or topic.get("status") not in FREEZABLE_STATUSES:
                continue
            db.update_meta({WAIT_PREFIX + campaign_id: None})
            _schedule(db, paths, settings, report, topic=topic, trigger=TRIGGER_BLOCK_EXPIRED,
                      task_id=f"line-block:{line}:{record.get('since')}", evidence=[],
                      detail={"days": round((_now() - since).total_seconds() / 86400, 1),
                              "reference_id": record.get("reference_id")})
    if hasattr(report, "program"):
        current = blocks(db)
        if current:
            report.program["line_blocks"] = [
                {"line": line, "reason": record.get("reason"), "state": record.get("state"),
                 "reference_id": record.get("reference_id"), "topic_id": record.get("topic_id"),
                 "since": record.get("since"),
                 "waiting_topics": [str(wait.get("topic_id")) for wait in waits(db).values()
                                    if str(wait.get("line")) == line],
                 "release_when": "the representative passes its precheck after the decision, "
                                 "the line's reference receipt changes, or "
                                 "`program line-block --clear`"}
                for line, record in current.items()
            ]


# --------------------------------------------------------------------------- dry-run report


def _result_payloads(topic: Mapping[str, Any]) -> list[tuple[Path, dict[str, Any]]]:
    found: list[tuple[Path, dict[str, Any]]] = []
    for item in topic.get("freeze_evidence") or []:
        path = _uri_path(item.get("path") if isinstance(item, Mapping) else None)
        if path is None or path.name != "result.json":
            continue
        body = _read_json(path)
        if isinstance(body, dict):
            found.append((path, result_view(body)))
    return found


def reopen_report(paths: WorkspacePaths, settings: FactorySettings) -> dict[str, Any]:
    """Read-only: which frozen topics the new rules would treat as line-level problems."""

    from .program import open_topic_ledger

    document = open_topic_ledger(paths, settings.program).read()
    margin = _borderline_margin(settings)
    frozen = [topic for topic in document.get("topics") or []
              if isinstance(topic, Mapping) and topic.get("status") == "frozen"]
    rows: list[dict[str, Any]] = []
    job_topics: dict[str, set[str]] = {}
    signature_topics: dict[tuple[float, float], set[str]] = {}
    analysed: list[tuple[Mapping[str, Any], dict[str, Any]]] = []
    for topic in frozen:
        payloads = _result_payloads(topic)
        cited: set[str] = set()
        queued_at_gate: list[str] = []
        queued_text = False
        criteria: list[dict[str, Any]] = []
        artifacts_all: list[tuple[str, Any]] = []
        texts: list[str] = []
        for _path, payload in payloads:
            artifacts = result_json_artifacts(payload)
            artifacts_all.extend(artifacts)
            criteria.extend(criteria_of(payload, artifacts))
            cited.update(named_job_ids(payload))
            block = payload.get("remote_compute")
            for item in block if isinstance(block, list) else [block]:
                if isinstance(item, Mapping) and str(item.get("state_at_gate") or "") in {
                        "queued", "running"}:
                    queued_at_gate.extend(str(job) for job in [item.get("job_id"),
                                                               *(item.get("job_ids") or [])]
                                          if job)
            text = str(payload.get("summary") or "")
            texts.append(text)
            if _QUEUED_TEXT.search(text):
                queued_text = True
                queued_at_gate.extend(JOB_ID.findall(text))
        classification = classify(criteria, margin)
        for job in cited:
            job_topics.setdefault(job, set()).add(str(topic["topic_id"]))
        for crit in classification["items"]:
            signature_topics.setdefault(_signature(crit), set()).add(str(topic["topic_id"]))
        analysed.append((topic, {"classification": classification, "cited": cited,
                                 "queued": sorted(set(queued_at_gate)),
                                 "queued_flag": bool(queued_at_gate) or queued_text,
                                 "payloads": payloads, "artifacts": artifacts_all}))
    referenced: set[str] = set()
    references: dict[str, Any] = {}
    for topic, item in analysed:
        for _path, payload in item["payloads"]:
            reference = shared_reference(paths, settings, topic=topic, payload=payload,
                                         classification=item["classification"],
                                         artifacts=item["artifacts"], ledger_document=None)
            if reference is not None:
                references[str(topic["topic_id"])] = reference
                referenced.add(str(topic["topic_id"]))
                break
    for topic, item in analysed:
        topic_id = str(topic["topic_id"])
        line = str(topic.get("research_line") or "")
        classification = item["classification"]
        shared_jobs = sorted(job for job in item["cited"]
                             if len(job_topics.get(job, ())) > 1)
        reference = references.get(topic_id)
        if reference is None:
            # The same miss (delta and tolerance) as a topic whose failure names the shared
            # reference is that reference's miss, even when this result does not name it.
            twins = set().union(*[signature_topics.get(_signature(crit), set())
                                  for crit in classification["items"]] or [set()])
            twin = next((other for other in sorted(twins - {topic_id}) if other in referenced),
                        None)
            if twin is not None:
                reference = {**references[twin], "source": f"same_miss_as:{twin}"}
        reason_class = str(topic.get("freeze_reason_class") or "")
        if reason_class != FREEZE_CLASS:
            category = "other_freeze_class"
        elif item["queued_flag"]:
            category = "reference_queued_at_precheck_end"
        elif (reference is not None or shared_jobs) and classification["verdict"] == "borderline":
            category = "line_reference_borderline"
        elif (reference is not None or shared_jobs) and classification["verdict"] == "failed":
            category = "line_reference_failed"
        elif classification["verdict"] == "borderline":
            category = "own_criterion_borderline"
        else:
            category = "topic_level"
        line_level = category in {"reference_queued_at_precheck_end",
                                  "line_reference_borderline", "line_reference_failed"}
        if category == "other_freeze_class" and not line_level:
            continue
        rows.append({
            "topic_id": topic_id, "research_line": line, "frozen_at": topic.get("frozen_at"),
            "freeze_reason_class": reason_class, "category": category,
            "line_level": line_level,
            "reopen_candidate": line_level or category == "own_criterion_borderline",
            "reference": reference, "shared_job_ids": shared_jobs,
            "queued_job_ids": item["queued"],
            "failed_criteria": [
                {key: crit.get(key) for key in ("name", "delta", "tolerance", "excess",
                                               "uncertainty", "borderline", "basis")}
                for crit in classification["items"]],
            "suggestion": (
                "line-level: re-check the shared reference once for the line, then reopen "
                "(program reopen-register with a control_receipt condition, or a reopening card)"
                if line_level else
                "borderline own criterion: a direction decision would have been asked"
                if category == "own_criterion_borderline" else "keep frozen"),
        })
    rows.sort(key=lambda row: (not row["line_level"], row["category"], row["topic_id"]))
    summary: dict[str, int] = {}
    for row in rows:
        summary[row["category"]] = summary.get(row["category"], 0) + 1
    return {"schema_version": "openlabs.line_reopen_report.v1", "generated_at": utc_now(),
            "dry_run": True, "frozen_topics": len(frozen),
            "precheck_freezes": sum(1 for t in frozen
                                    if t.get("freeze_reason_class") == FREEZE_CLASS),
            "by_category": summary, "topics": rows,
            "note": "Read-only. Nothing was reopened; the owner decides which topics to reopen."}


__all__ = [
    "BLOCK_PREFIX", "TRIGGERS", "TRIGGER_BLOCK_EXPIRED", "TRIGGER_BORDERLINE",
    "TRIGGER_LINE_REFERENCE", "WAIT_PREFIX", "after_decision", "block_of", "blocked_lines",
    "blocks", "campaign_waiting", "classify", "criteria_of", "intercept_precheck_freeze",
    "line_references", "named_job_ids", "on_progress", "pending_jobs", "release",
    "reopen_report", "shared_reference", "tick", "trigger_reason_text", "waits",
]
