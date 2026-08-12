"""Materialize and independently replay declared artifact dependency closures."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .contracts import executable_artifact, sha256_file

REPLAY_SCHEMA = "openlabs.reproduction_replay.v1"


def _artifact_path(uri: object) -> Path:
    parsed = urlparse(str(uri or ""))
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        raise ValueError(f"Reproduction artifact is not a local file URI: {uri}")
    return Path(unquote(parsed.path)).resolve()


def _inside(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    base = root.resolve()
    return resolved == base or resolved.is_relative_to(base)


def _copy_bound_file(source: Path, target: Path, digest: str) -> None:
    if not source.is_file() or sha256_file(source) != digest:
        raise ValueError(f"Reproduction input changed or is missing: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        if sha256_file(target) != digest:
            raise ValueError(f"Reproduction closure path collision: {target}")
        return
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    os.close(descriptor)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _replay(workspace: Path, command: list[str], *, timeout_seconds: int) -> dict[str, Any]:
    bubblewrap = shutil.which("bwrap")
    if bubblewrap is None:
        return {
            "schema_version": REPLAY_SCHEMA,
            "status": "unavailable",
            "reason": "bubblewrap is unavailable",
        }
    with tempfile.TemporaryDirectory(prefix="openlabs-replay-") as temporary:
        replay_workspace = Path(temporary) / "workspace"
        shutil.copytree(workspace, replay_workspace)
        sandbox = [bubblewrap, "--die-with-parent", "--unshare-net", "--clearenv"]
        for system_root in ("/usr", "/bin", "/lib", "/lib64", "/etc"):
            path = Path(system_root)
            if path.exists():
                sandbox.extend(["--ro-bind", system_root, system_root])
        sandbox.extend(
            [
                "--dev",
                "/dev",
                "--proc",
                "/proc",
                "--tmpfs",
                "/tmp",
                "--bind",
                str(replay_workspace),
                "/work",
                "--chdir",
                "/work",
                "--setenv",
                "HOME",
                "/tmp",
                "--setenv",
                "PATH",
                "/usr/local/bin:/usr/bin:/bin",
                "--setenv",
                "PYTHONPATH",
                "",
                "--setenv",
                "PYTHONHASHSEED",
                "0",
                "--",
                *command,
            ]
        )
        started = time.monotonic()
        try:
            completed = subprocess.run(
                sandbox,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "schema_version": REPLAY_SCHEMA,
                "status": "timed_out",
                "duration_seconds": max(0.0, time.monotonic() - started),
                "stdout_sha256": _digest_text(str(exc.stdout or "")),
                "stderr_sha256": _digest_text(str(exc.stderr or "")),
                "sandbox": "bubblewrap-readonly-system-unshared-network",
            }
    return {
        "schema_version": REPLAY_SCHEMA,
        "status": "passed" if completed.returncode == 0 else "failed",
        "exit_code": completed.returncode,
        "duration_seconds": max(0.0, time.monotonic() - started),
        "stdout_sha256": _digest_text(completed.stdout),
        "stderr_sha256": _digest_text(completed.stderr),
        "sandbox": "bubblewrap-readonly-system-unshared-network",
    }


def materialize_reproduction(
    artifact: Mapping[str, Any],
    *,
    workspace_root: Path,
    closure_root: Path,
) -> dict[str, Any]:
    """Copy one declared closure preserving workspace-relative paths, then replay it."""

    reproduction = artifact.get("reproduction")
    if not isinstance(reproduction, Mapping):
        raise TypeError(f"Artifact {artifact.get('artifact_id')} has no reproduction closure")
    source_workspace = workspace_root.expanduser().resolve()
    source_artifact = _artifact_path(artifact.get("uri"))
    if not _inside(source_artifact, source_workspace):
        raise ValueError(
            f"Reproduction artifact is outside the attempt workspace: {source_artifact}"
        )
    artifact_relative = source_artifact.relative_to(source_workspace)
    workspace = closure_root.expanduser().resolve() / "workspace"
    _copy_bound_file(
        source_artifact,
        workspace / artifact_relative,
        str(artifact.get("sha256") or ""),
    )
    frozen_inputs: list[dict[str, Any]] = []
    for declared in reproduction.get("inputs", []):
        if not isinstance(declared, Mapping):
            continue
        relative = Path(str(declared.get("path") or ""))
        source = (source_workspace / relative).resolve()
        if not _inside(source, source_workspace):
            raise ValueError(f"Reproduction input escapes the workspace: {relative}")
        digest = str(declared.get("sha256") or "")
        target = workspace / relative
        _copy_bound_file(source, target, digest)
        frozen_inputs.append(
            {
                "path": relative.as_posix(),
                "sha256": digest,
                "uri": target.as_uri(),
            }
        )
    raw_command = [str(item) for item in reproduction.get("command", [])]
    command = [
        item.replace("{artifact}", artifact_relative.as_posix()).replace("{workspace}", "/work")
        for item in raw_command
    ]
    replay = _replay(
        workspace,
        command,
        timeout_seconds=int(reproduction.get("timeout_seconds", 120)),
    )
    return {
        "command": raw_command,
        "inputs": frozen_inputs,
        "timeout_seconds": int(reproduction.get("timeout_seconds", 120)),
        "artifact_path": artifact_relative.as_posix(),
        "workspace_uri": workspace.as_uri(),
        "replay": replay,
    }


def preflight_reproductions(
    payload: Mapping[str, Any],
    *,
    workspace_root: Path,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Run declared closures before Codex stops so it can repair failures in-turn."""

    errors: list[str] = []
    receipts: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="openlabs-preflight-") as temporary:
        root = Path(temporary)
        for index, artifact in enumerate(payload.get("artifacts", [])):
            if not isinstance(artifact, Mapping) or not executable_artifact(artifact):
                continue
            artifact_id = str(artifact.get("artifact_id") or f"artifact-{index}")
            try:
                frozen = materialize_reproduction(
                    artifact,
                    workspace_root=workspace_root,
                    closure_root=root / f"{index:03d}",
                )
            except Exception as exc:  # noqa: BLE001 - converted to a gate issue.
                errors.append(f"{artifact_id}: {exc}")
                continue
            replay = frozen["replay"]
            receipts.append({"artifact_id": artifact_id, **replay})
            if replay.get("status") != "passed":
                errors.append(
                    f"{artifact_id}: isolated reproduction replay status is {replay.get('status')}"
                )
    return errors, receipts
