"""Check disclosed model identities against recorded use, never a preferred model.

Legacy declarations without structured model usage retain their textual check.
New usage records bind each model to a local, hash-bound JSON runtime record.
This checks provenance and consistency, not authorship or scientific validation.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Mapping

GPT_ID = re.compile(
    r"\bgpt[- ]?\d+(?:\.\d+)*(?:-[a-z0-9]+| (?:astra|sol|luna|terra))*\b",
    re.I,
)
MODEL_RECORD_EFFECTIVE_DATE = date(2026, 9, 6)
RECORDED_TOOLS = {("openai-codex", "Codex"), ("anthropic", "Claude Code")}


def model_usage_for_record(metadata: Mapping[str, Any]) -> Any:
    """Only genuinely old records with no usage field qualify for legacy checks."""
    declarations = metadata.get("declarations")
    ai = declarations.get("ai_use") if isinstance(declarations, Mapping) else None
    if isinstance(ai, Mapping) and "model_usage" in ai:
        return ai["model_usage"] if ai["model_usage"] is not None else []
    candidates = [str(metadata.get("created_at") or "")[:10]]
    match = re.match(r"^(\d{4})(\d{2})(\d{2})", str(metadata.get("paper_id") or ""))
    if match:
        candidates.append("-".join(match.groups()))
    for candidate in candidates:
        try:
            if date.fromisoformat(candidate) >= MODEL_RECORD_EFFECTIVE_DATE:
                return []
        except ValueError:
            continue
    return None


def normalized_model(value: str) -> str:
    return re.sub(r"^gpt[- ]?(?=\d)", "gpt-", value.strip().lower()).replace(" ", "-")


def configured_attempts_for_record(metadata: Mapping[str, Any]) -> Any:
    declarations = metadata.get("declarations")
    ai = declarations.get("ai_use") if isinstance(declarations, Mapping) else None
    return ai.get("configured_attempts") if isinstance(ai, Mapping) else None


def _configured_models(text: str, attempts: Any, root: Path | None) -> tuple[set[str], list[tuple[str, str]]]:
    """Verify failed configurations separately; they never count as runtime use."""
    if attempts is None:
        return set(), []
    accepted: set[str] = set()
    issues: list[tuple[str, str]] = []
    if not isinstance(attempts, list):
        return accepted, [("CONFIGURATION-INVALID", "configured attempts must be structured records")]
    normalized_text = GPT_ID.sub(lambda m: normalized_model(m.group()), text.lower())
    for entry in attempts:
        try:
            if not isinstance(entry, Mapping) or root is None:
                raise ValueError()
            model = entry.get("configured_model")
            if (not isinstance(model, str)
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", model)
                    or (entry.get("provider"), entry.get("tool")) not in RECORDED_TOOLS
                    or "actual_runtime_model" not in entry
                    or entry["actual_runtime_model"] is not None
                    or entry.get("completed_contribution") != "unverified"):
                raise ValueError()
            model = normalized_model(model)
            evidence = entry.get("evidence")
            if not isinstance(evidence, Mapping):
                raise ValueError()
            source, checksum, pointer = (evidence.get(k) for k in ("path", "sha256", "json_pointer"))
            if (not isinstance(source, str) or not source or Path(source).is_absolute()
                    or not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum)
                    or not isinstance(pointer, str) or not pointer.startswith("/")):
                raise ValueError()
            path = (root / source).resolve()
            if not path.is_relative_to(root.resolve()) or path.stat().st_size > 4 * 1024 * 1024:
                raise ValueError()
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != checksum:
                raise ValueError()
            value = json.loads(raw)
            parent = None
            for token in pointer[1:].split("/"):
                token = token.replace("~1", "/").replace("~0", "~")
                parent = value
                value = value[int(token)] if isinstance(value, list) else value[token]
            if not isinstance(value, str) or normalized_model(value) != model or not isinstance(parent, Mapping):
                raise ValueError()
            if (parent.get("state", parent.get("status")) not in {
                    "timeout", "timed_out_revision_attempt", "failed", "cancelled",
                    "configuration_only_not_confirmed_use"}
                    or parent.get("actual_runtime_model") is not None
                    or parent.get("completed_contribution", "unverified") != "unverified"):
                raise ValueError()
            # Every occurrence must qualify the name as configuration with
            # unknown runtime, rather than assert that the configured model ran.
            sentences = re.split(r"[.!?](?=\s|$)", normalized_text)
            occurrences = [s for s in sentences if re.search(
                r"(?<![\w.-])" + re.escape(model) + r"(?![\w-]|\.\w)", s)]
            if not occurrences or any(not (
                    re.search(r"\bconfigured\b", s)
                    and re.search(r"\bruntime\b", s)
                    and re.search(r"\b(?:unknown|unverified|unconfirmed)\b|not (?:established|confirmed)", s)
            ) for s in occurrences):
                issues.append(("CONFIGURATION-DISCLOSURE", "disclose each configured model only as an unconfirmed runtime attempt"))
                continue
            accepted.add(model)
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            issues.append(("CONFIGURATION-EVIDENCE", "configuration evidence is missing, changed, unsafe, or does not establish an unconfirmed failed attempt"))
    return accepted, issues


def model_disclosure_issues(
    text: str, model_usage: Any = None, *, root: Path | None = None,
    configured_attempts: Any = None,
) -> list[tuple[str, str]]:
    """None denotes legacy metadata; an explicit empty list is unresolved."""
    configured, issues = _configured_models(text, configured_attempts, root)
    mentioned = {normalized_model(m.group()) for m in GPT_ID.finditer(text)}
    if model_usage is None:
        if not mentioned:
            issues.append(("MODEL-MISSING", "identify the model actually used; do not infer a version from a template"))
        return issues
    if not isinstance(model_usage, list) or not model_usage:
        return [("MODEL-UNRECORDED", "record actual model usage and its runtime evidence before final review")]
    expected: set[str] = set()
    for entry in model_usage:
        if not isinstance(entry, Mapping):
            issues.append(("MODEL-RECORD-INVALID", "model usage must contain structured records"))
            continue
        model = entry.get("model")
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", model):
            issues.append(("MODEL-RECORD-INVALID", "record an exact runtime model identifier"))
            continue
        model = normalized_model(model)
        expected.add(model)
        normalized_text = GPT_ID.sub(lambda m: normalized_model(m.group()), text.lower())
        if not re.search(r"(?<![\w.-])" + re.escape(model) + r"(?![\w-]|\.\w)", normalized_text):
            issues.append(("MODEL-MISMATCH", f"the declaration must disclose the registered model {model}"))
        if (entry.get("provider"), entry.get("tool")) not in RECORDED_TOOLS:
            issues.append(("MODEL-RECORD-INVALID", "record the actual provider and tool consistently"))
        if not isinstance(entry.get("purpose"), str) or not entry["purpose"].strip():
            issues.append(("MODEL-RECORD-INVALID", "record the actual purpose of each model use"))
        evidence = entry.get("evidence")
        if not isinstance(evidence, Mapping):
            issues.append(("MODEL-EVIDENCE-MISSING", "model usage requires hash-bound runtime evidence"))
            continue
        source, checksum, pointer = (evidence.get(k) for k in ("path", "sha256", "json_pointer"))
        if (not isinstance(source, str) or not source or Path(source).is_absolute()
                or not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum)
                or not isinstance(pointer, str) or not pointer.startswith("/")):
            issues.append(("MODEL-EVIDENCE-INVALID", "model evidence requires a relative path, SHA-256 and JSON pointer"))
            continue
        if root is None:
            issues.append(("MODEL-EVIDENCE-UNCHECKED", "a data root is required to verify structured runtime evidence"))
            continue
        try:
            source_path = (root / source).resolve()
            if not source_path.is_relative_to(root.resolve()):
                raise ValueError("outside data root")
            if source_path.stat().st_size > 4 * 1024 * 1024:
                raise ValueError("runtime record exceeds bounded checker size")
            raw = source_path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != checksum:
                raise ValueError("runtime evidence hash mismatch")
            value = json.loads(raw)
            for token in pointer[1:].split("/"):
                token = token.replace("~1", "/").replace("~0", "~")
                value = value[int(token)] if isinstance(value, list) else value[token]
            if not isinstance(value, str) or normalized_model(value) != model:
                raise ValueError("runtime model differs from registered model")
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            # Do not expose record contents or exception strings (possibly private).
            issues.append(("MODEL-EVIDENCE-MISMATCH", "runtime model evidence is missing, changed, unsafe, or inconsistent"))
    # An explicitly labelled generation family is descriptive, not an exact
    # runtime identifier. It can accompany a separately disclosed, evidenced
    # variant of that same family; every exact variant remains mandatory above.
    families = {normalized_model(m.group(1)) for m in re.finditer(
        r'\b(gpt[- ]?\d+(?:\.\d+)*)\s+family\b', text, re.I)}
    supported_families = {family for family in families
                          if any(model.startswith(family + '-') for model in expected)}
    if mentioned - expected - supported_families - configured:
        issues.append(("MODEL-UNREGISTERED", "the declaration names a GPT model absent from the model-usage records"))
    return issues
