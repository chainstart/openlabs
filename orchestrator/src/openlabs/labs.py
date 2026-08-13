"""Discovery of isolated domain labs through a small JSON manifest."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import IDENTIFIER

LAB_SCHEMA = "openlabs.lab.v1"


@dataclass(frozen=True)
class ProtocolManifest:
    protocol_id: str
    primary_skill: str
    validator_command: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeSetupManifest:
    setup_id: str
    command: tuple[str, ...]
    timeout_seconds: int


@dataclass(frozen=True)
class LabManifest:
    lab_id: str
    domain: str
    root: Path
    command: tuple[str, ...]
    skills: tuple[dict[str, str], ...]
    protocols: tuple[ProtocolManifest, ...]
    runtime_setups: tuple[RuntimeSetupManifest, ...]
    capabilities: tuple[str, ...]
    raw: dict[str, Any]

    def skill_path(self, requested: str | None = None) -> Path | None:
        candidates = self.skills
        if requested:
            candidates = tuple(item for item in candidates if item.get("skill_id") == requested)
        if not candidates:
            return None
        return (self.root / candidates[0]["path"]).resolve()

    def protocol(self, protocol_id: str) -> ProtocolManifest | None:
        return next(
            (item for item in self.protocols if item.protocol_id == protocol_id),
            None,
        )


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def load_lab(path: str | Path) -> LabManifest:
    manifest_path = Path(path).expanduser().resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise TypeError(f"Lab manifest must be a JSON object: {manifest_path}")
    if payload.get("schema_version") != LAB_SCHEMA:
        raise ValueError(f"Unsupported lab schema in {manifest_path}")
    lab_id = _text(payload.get("lab_id"))
    if not IDENTIFIER.fullmatch(lab_id):
        raise ValueError(f"Invalid lab_id in {manifest_path}: {lab_id!r}")
    domain = _text(payload.get("domain"))
    if not domain:
        raise ValueError(f"domain is required in {manifest_path}")
    runner = payload.get("runner")
    runner = runner if isinstance(runner, Mapping) else {}
    runner_command = runner.get("command")
    if (
        not isinstance(runner_command, list)
        or not runner_command
        or any(not _text(item) for item in runner_command)
    ):
        raise ValueError(f"runner.command must be a non-empty string array: {manifest_path}")
    skills: list[dict[str, str]] = []
    for item in payload.get("skills", []):
        if not isinstance(item, Mapping):
            raise TypeError(f"skills entries must be objects: {manifest_path}")
        skill_id = _text(item.get("skill_id"))
        skill_path = _text(item.get("path"))
        if not skill_id or not skill_path:
            raise ValueError(f"skills entries require skill_id and path: {manifest_path}")
        skills.append({"skill_id": skill_id, "path": skill_path})
    skill_ids = {item["skill_id"] for item in skills}
    protocols: list[ProtocolManifest] = []
    for item in payload.get("protocols", []):
        if not isinstance(item, Mapping):
            raise TypeError(f"protocol entries must be objects: {manifest_path}")
        protocol_id = _text(item.get("protocol_id"))
        primary_skill = _text(item.get("primary_skill"))
        validator = item.get("validator")
        validator_command = validator.get("command") if isinstance(validator, Mapping) else None
        if (
            not IDENTIFIER.fullmatch(protocol_id)
            or primary_skill not in skill_ids
            or not isinstance(validator_command, list)
            or not validator_command
            or any(not isinstance(token, str) or not token for token in validator_command)
        ):
            raise ValueError(f"invalid protocol registration in {manifest_path}: {item}")
        if any(existing.protocol_id == protocol_id for existing in protocols):
            raise ValueError(f"duplicate protocol_id {protocol_id!r} in {manifest_path}")
        protocols.append(
            ProtocolManifest(
                protocol_id=protocol_id,
                primary_skill=primary_skill,
                validator_command=tuple(validator_command),
            )
        )
    runtime_setups: list[RuntimeSetupManifest] = []
    for item in payload.get("runtime_setup", []):
        if not isinstance(item, Mapping):
            raise TypeError(f"runtime_setup entries must be objects: {manifest_path}")
        setup_id = _text(item.get("setup_id"))
        command = item.get("command")
        timeout = item.get("timeout_seconds", 1800)
        if (
            not IDENTIFIER.fullmatch(setup_id)
            or not isinstance(command, list)
            or not command
            or any(not _text(token) for token in command)
            or not isinstance(timeout, int)
            or isinstance(timeout, bool)
            or timeout < 1
        ):
            raise ValueError(f"invalid runtime_setup registration in {manifest_path}: {item}")
        if any(existing.setup_id == setup_id for existing in runtime_setups):
            raise ValueError(f"duplicate runtime setup {setup_id!r} in {manifest_path}")
        runtime_setups.append(
            RuntimeSetupManifest(
                setup_id=setup_id,
                command=tuple(str(token) for token in command),
                timeout_seconds=timeout,
            )
        )
    capabilities = tuple(_text(item) for item in payload.get("capabilities", []) if _text(item))
    return LabManifest(
        lab_id=lab_id,
        domain=domain,
        root=manifest_path.parent,
        command=tuple(str(item) for item in runner_command),
        skills=tuple(skills),
        protocols=tuple(protocols),
        runtime_setups=tuple(runtime_setups),
        capabilities=capabilities,
        raw=dict(payload),
    )


def discover_labs(code_root: str | Path) -> dict[str, LabManifest]:
    labs: dict[str, LabManifest] = {}
    for path in sorted((Path(code_root) / "labs").glob("*/lab.json")):
        manifest = load_lab(path)
        if manifest.lab_id in labs:
            raise ValueError(f"Duplicate lab_id: {manifest.lab_id}")
        labs[manifest.lab_id] = manifest
    return labs


def lab_for_domain(labs: Mapping[str, LabManifest], domain: str) -> LabManifest:
    matches = [lab for lab in labs.values() if lab.domain == domain]
    if len(matches) != 1:
        raise ValueError(f"Expected one lab for domain {domain!r}; found {len(matches)}")
    return matches[0]
