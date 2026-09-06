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

GPT_ID = re.compile(r"\bgpt[- ]?\d+(?:\.\d+)*(?:-[a-z0-9]+)*\b", re.I)
MODEL_RECORD_EFFECTIVE_DATE = date(2026, 9, 6)


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
    return re.sub(r"^gpt[- ]?(?=\d)", "gpt-", value.strip().lower())


def model_disclosure_issues(
    text: str, model_usage: Any = None, *, root: Path | None = None
) -> list[tuple[str, str]]:
    """None denotes legacy metadata; an explicit empty list is unresolved."""
    issues: list[tuple[str, str]] = []
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
        if entry.get("provider") != "openai-codex" or entry.get("tool") != "Codex":
            issues.append(("MODEL-RECORD-INVALID", "record the actual Codex provider and tool consistently"))
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
    if mentioned - expected:
        issues.append(("MODEL-UNREGISTERED", "the declaration names a GPT model absent from the model-usage records"))
    return issues
