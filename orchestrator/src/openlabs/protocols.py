"""Execute trusted, lab-registered protocol validators."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .labs import LabManifest, ProtocolManifest


@dataclass(frozen=True)
class ProtocolValidation:
    valid: bool
    errors: tuple[str, ...]


def _command(
    lab: LabManifest,
    protocol: ProtocolManifest,
    *,
    project_path: Path,
    workstream_path: Path,
    mode: str,
) -> list[str]:
    replacements = {
        "{python}": sys.executable,
        "{project_config}": str(project_path.resolve()),
        "{workstream_state}": str(workstream_path.resolve()),
        "{lab_root}": str(lab.root.resolve()),
        "{validation_mode}": mode,
    }
    command: list[str] = []
    for index, raw in enumerate(protocol.validator_command):
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
) -> ProtocolValidation:
    if mode not in {"discovery", "commit"}:
        raise ValueError(f"unknown protocol validation mode: {mode}")
    completed = subprocess.run(
        _command(
            lab,
            protocol,
            project_path=project_path,
            workstream_path=workstream_path,
            mode=mode,
        ),
        cwd=lab.root,
        check=False,
        capture_output=True,
        text=True,
        timeout=max(1, timeout_seconds),
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
