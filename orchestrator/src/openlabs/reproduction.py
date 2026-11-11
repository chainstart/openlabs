"""Materialize and independently replay declared artifact dependency closures."""

from __future__ import annotations

import functools
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


# Explicit, default-off operator switch read from the tick/worker environment (the
# container's env file, never the shared config/openlabs.toml). Honoured only when
# bubblewrap cannot create a namespace and container_guard accepts the cgroup.
REPLAY_CONTAINER_FALLBACK_ENV = "OPENLABS_REPLAY_WITHOUT_BWRAP_IN_VERIFIED_CONTAINER"
_SANDBOX = "bubblewrap-readonly-system-unshared-network"
_FALLBACK_SANDBOX = "none-verified-container"
# Same marker engine.py and bin/openlabs-resource-guard use for the container path.
_CONTAINER_MARKER = Path("/.dockerenv")


@functools.lru_cache(maxsize=4)
def _bubblewrap_problem(bubblewrap: str | None) -> str | None:
    """Why bubblewrap cannot create a namespace here (None when it can).

    Docker's default seccomp profile lets ``bwrap`` exist but fail every launch
    with "No permissions to create new namespace"; report that as an unavailable
    sandbox rather than as a failed reproduction of the agent's script.
    """

    if bubblewrap is None:
        return "bubblewrap is unavailable"
    try:
        completed = subprocess.run(
            [bubblewrap, "--die-with-parent", "--unshare-net", "--ro-bind", "/", "/", "--", "true"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"bubblewrap cannot start: {exc}"
    if completed.returncode == 0:
        return None
    detail = completed.stderr.strip() or f"exit code {completed.returncode}"
    return f"bubblewrap cannot create a namespace on this host ({detail})"


def _container_fallback_allowed() -> tuple[bool, str | None]:
    raw = os.environ.get(REPLAY_CONTAINER_FALLBACK_ENV, "").strip().lower()
    if raw not in {"1", "true", "yes", "on"}:
        return False, None
    if not _CONTAINER_MARKER.exists():
        return False, f"{REPLAY_CONTAINER_FALLBACK_ENV} applies only inside a Docker container"
    from .container_guard import validate

    try:
        validate()
    except (OSError, ValueError) as exc:
        return False, f"{REPLAY_CONTAINER_FALLBACK_ENV} is set but the container guard refused: {exc}"
    return True, None


def _replay(workspace: Path, command: list[str], *, timeout_seconds: int) -> dict[str, Any]:
    """Replay ``command`` on a private copy of ``workspace``.

    ``{workspace}`` tokens in ``command`` name the copied closure root.
    """

    bubblewrap = shutil.which("bwrap")
    problem = _bubblewrap_problem(bubblewrap)
    fallback = False
    if problem is not None:
        fallback, refusal = _container_fallback_allowed()
        if not fallback:
            return {
                "schema_version": REPLAY_SCHEMA,
                "status": "unavailable",
                "reason": refusal or problem,
            }
    with tempfile.TemporaryDirectory(prefix="openlabs-replay-") as temporary:
        replay_workspace = Path(temporary) / "workspace"
        shutil.copytree(workspace, replay_workspace)
        if fallback:
            return _replay_in_verified_container(
                replay_workspace,
                [item.replace("{workspace}", str(replay_workspace)) for item in command],
                home=Path(temporary),
                timeout_seconds=timeout_seconds,
                reason=str(problem),
            )
        command = [item.replace("{workspace}", "/work") for item in command]
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
                "sandbox": _SANDBOX,
            }
    return {
        "schema_version": REPLAY_SCHEMA,
        "status": "passed" if completed.returncode == 0 else "failed",
        "exit_code": completed.returncode,
        "duration_seconds": max(0.0, time.monotonic() - started),
        "stdout_sha256": _digest_text(completed.stdout),
        "stderr_sha256": _digest_text(completed.stderr),
        "sandbox": _SANDBOX,
    }


def _replay_in_verified_container(
    replay_workspace: Path,
    command: list[str],
    *,
    home: Path,
    timeout_seconds: int,
    reason: str,
) -> dict[str, Any]:
    """Weaker replay: private copy and clean environment, no namespace isolation.

    It still catches undeclared workspace-relative inputs, but not absolute-path
    reads of the live repositories or network access; the receipt says so.
    """

    environment = {
        "HOME": str(home),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "PYTHONPATH": "",
        "PYTHONHASHSEED": "0",
        "LANG": "C.UTF-8",
    }
    started = time.monotonic()
    base = {
        "schema_version": REPLAY_SCHEMA,
        "sandbox": _FALLBACK_SANDBOX,
        "sandbox_reason": reason,
    }
    try:
        completed = subprocess.run(
            command,
            cwd=replay_workspace,
            env=environment,
            stdin=subprocess.DEVNULL,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            start_new_session=True,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            **base,
            "status": "timed_out",
            "duration_seconds": max(0.0, time.monotonic() - started),
            "stdout_sha256": _digest_text(str(exc.stdout or "")),
            "stderr_sha256": _digest_text(str(exc.stderr or "")),
        }
    except OSError as exc:
        return {**base, "status": "failed", "error": str(exc)}
    return {
        **base,
        "status": "passed" if completed.returncode == 0 else "failed",
        "exit_code": completed.returncode,
        "duration_seconds": max(0.0, time.monotonic() - started),
        "stdout_sha256": _digest_text(completed.stdout),
        "stderr_sha256": _digest_text(completed.stderr),
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
    command = [item.replace("{artifact}", artifact_relative.as_posix()) for item in raw_command]
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
                reason = f" ({replay['reason']})" if replay.get("reason") else ""
                errors.append(
                    f"{artifact_id}: isolated reproduction replay status is "
                    f"{replay.get('status')}{reason}"
                )
    return errors, receipts
