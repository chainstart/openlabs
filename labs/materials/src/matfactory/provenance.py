"""Small, dependency-free primitives for immutable scientific artefacts."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any


def canonical_json(value: Any) -> str:
    """Stable JSON representation used for fingerprints."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_manifest(paths: Any, *, root: Path | str = ".") -> dict[str, str]:
    """Content hashes keyed by stable paths relative to ``root`` when possible."""
    base = Path(root).resolve()
    output: dict[str, str] = {}
    for item in sorted((Path(path).resolve() for path in paths), key=str):
        try:
            name = str(item.relative_to(base))
        except ValueError:
            name = str(item)
        output[name] = sha256_file(item)
    return output


def fingerprint(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def atomic_write_text(path: Path | str, text: str) -> None:
    """Write and fsync a file before an atomic replace in the same directory."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: Path | str, value: Any, *, indent: int = 2) -> None:
    atomic_write_text(
        path,
        json.dumps(value, indent=indent, ensure_ascii=False, allow_nan=False) + "\n",
    )


def git_state(root: Path | str = ".") -> dict[str, Any]:
    """Commit and dirty flag without failing outside a Git checkout."""
    directory = str(Path(root).resolve())

    def run(*args: str) -> str | None:
        try:
            return subprocess.run(
                ["git", *args],
                cwd=directory,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    commit = run("rev-parse", "HEAD")
    status = run("status", "--porcelain=v1", "--untracked-files=normal")
    diff = run("diff", "--binary", "HEAD", "--", ".")
    return {
        "commit": commit,
        "dirty": bool(status) if status is not None else None,
        "status_sha256": sha256_bytes(status.encode()) if status else None,
        "tracked_diff_sha256": sha256_bytes(diff.encode()) if diff else None,
    }


def environment_versions(packages: tuple[str, ...]) -> dict[str, Any]:
    installed: dict[str, str | None] = {}
    for package in packages:
        try:
            installed[package] = version(package)
        except PackageNotFoundError:
            installed[package] = None
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": installed,
    }
