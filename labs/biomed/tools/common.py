"""Streaming hashes, confined paths and atomic metadata for biomed pilots."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]
CODE_ROOT = LAB_ROOT.parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value):
        raise ValueError("invalid identifier or filename")
    return value


def read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def confined(root: Path, raw: str) -> Path:
    if not isinstance(raw, str) or not raw or Path(raw).is_absolute():
        raise ValueError("nonempty relative evidence path required")
    path = (root / raw).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("missing evidence file or path escape")
    return path


def file_record(root: Path, record: dict) -> Path:
    if not isinstance(record, dict):
        raise ValueError("hash-bound file record required")
    path = confined(root, record.get("path"))
    if not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", ""))):
        raise ValueError("lowercase SHA-256 required")
    if sha256(path) != record["sha256"]:
        raise ValueError("SHA-256 mismatch")
    return path
