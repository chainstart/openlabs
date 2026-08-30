"""Execute trusted, lab-registered protocol validators."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .labs import LabManifest, ProtocolManifest

PROTOCOL_VALIDATION_CONTEXT_ENV = "OPENLABS_PROTOCOL_VALIDATION_CONTEXT"


@dataclass(frozen=True)
class ProtocolValidation:
    valid: bool
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ProtocolHookResult:
    """Structured output from an optional lab-owned lifecycle hook."""

    valid: bool
    payload: dict[str, Any]
    errors: tuple[str, ...]


def _render_command(
    lab: LabManifest,
    raw_command: tuple[str, ...],
    *,
    project_path: Path,
    workstream_path: Path,
    mode: str,
    hook_event: str = "",
) -> list[str]:
    replacements = {
        "{python}": sys.executable,
        "{project_config}": str(project_path.resolve()),
        "{workstream_state}": str(workstream_path.resolve()),
        "{lab_root}": str(lab.root.resolve()),
        "{validation_mode}": mode,
        "{hook_event}": hook_event,
    }
    command: list[str] = []
    for index, raw in enumerate(raw_command):
        token = replacements.get(raw, raw)
        if index > 0 and token.endswith(".py") and not Path(token).is_absolute():
            token = str((lab.root / token).resolve())
        command.append(token)
    return command


def validate_protocol_state(
    lab: LabManifest,
    protocol: ProtocolManifest,
    *,
    project_path: Path,
    workstream_path: Path,
    timeout_seconds: int = 60,
    mode: str = "commit",
    validation_context: Mapping[str, Any] | None = None,
) -> ProtocolValidation:
    if mode not in {"discovery", "commit"}:
        raise ValueError(f"unknown protocol validation mode: {mode}")
    environment = os.environ.copy()
    environment.pop(PROTOCOL_VALIDATION_CONTEXT_ENV, None)
    if validation_context is not None:
        environment[PROTOCOL_VALIDATION_CONTEXT_ENV] = json.dumps(
            dict(validation_context),
            ensure_ascii=False,
            sort_keys=True,
        )
    completed = subprocess.run(
        _render_command(
            lab,
            protocol.validator_command,
            project_path=project_path,
            workstream_path=workstream_path,
            mode=mode,
        ),
        cwd=lab.root,
        check=False,
        capture_output=True,
        text=True,
        timeout=max(1, timeout_seconds),
        env=environment,
    )
    if completed.returncode not in {0, 1}:
        detail = completed.stderr.strip() or completed.stdout.strip()
        return ProtocolValidation(
            False,
            (f"protocol validator exited {completed.returncode}: {detail[:1000]}",),
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return ProtocolValidation(False, (f"protocol validator emitted invalid JSON: {exc}",))
    if not isinstance(payload, dict):
        return ProtocolValidation(False, ("protocol validator result must be an object",))
    errors = payload.get("errors", [])
    if not isinstance(errors, list) or any(not isinstance(item, str) for item in errors):
        return ProtocolValidation(False, ("protocol validator errors must be a string array",))
    valid = payload.get("valid") is True and not errors and completed.returncode == 0
    if payload.get("valid") is not True and not errors:
        errors = ["protocol validator rejected state without a reason"]
    return ProtocolValidation(valid, tuple(errors))


def run_protocol_hook(
    lab: LabManifest,
    protocol: ProtocolManifest,
    hook_id: str,
    *,
    project_path: Path,
    workstream_path: Path,
    context: Mapping[str, Any],
) -> ProtocolHookResult | None:
    """Run a trusted, lab-registered hook without importing domain code.

    The control plane understands the scheduling envelope returned by a hook,
    but the lab owns every domain-specific state name, gate, and policy file.
    """

    hook = protocol.hook(hook_id)
    if hook is None:
        return None
    command = _render_command(
        lab,
        hook.command,
        project_path=project_path,
        workstream_path=workstream_path,
        mode="hook",
        hook_event=hook_id,
    )
    try:
        completed = subprocess.run(
            command,
            cwd=lab.root,
            input=json.dumps(dict(context), ensure_ascii=False, sort_keys=True),
            check=False,
            capture_output=True,
            text=True,
            timeout=hook.timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return ProtocolHookResult(
            False,
            {},
            (f"protocol hook {hook_id!r} exceeded {hook.timeout_seconds} seconds",),
        )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        return ProtocolHookResult(
            False,
            {},
            (f"protocol hook {hook_id!r} exited {completed.returncode}: {detail[:1000]}",),
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return ProtocolHookResult(
            False,
            {},
            (f"protocol hook {hook_id!r} emitted invalid JSON: {exc}",),
        )
    if not isinstance(payload, Mapping):
        return ProtocolHookResult(
            False,
            {},
            (f"protocol hook {hook_id!r} result must be an object",),
        )
    return ProtocolHookResult(True, dict(payload), ())
