"""Run one review role in a fresh process with an empty working directory.

The launcher is provider-neutral. It records the model the runtime actually
reports, never the requested name alone, and binds prompt, schema and output
by SHA-256. It does not judge anything; it only starts the process and checks
that a schema-conforming JSON object came back.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROVIDERS = {
    ("anthropic", "Claude Code"): "claude",
    ("openai-codex", "Codex"): "codex",
}


class LaunchError(RuntimeError):
    """Raised when a review process cannot be run or returns unusable output."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _executable(name: str) -> str:
    found = shutil.which(name) or str(Path.home() / ".local" / "bin" / name)
    if not Path(found).exists():
        raise LaunchError(f"{name} executable not found")
    return found


def role_runtime(role: Mapping[str, Any]) -> str:
    key = (str(role.get("provider") or ""), str(role.get("tool") or ""))
    if key not in PROVIDERS:
        raise LaunchError(f"Unsupported review provider/tool: {key}")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", str(role.get("model") or "")):
        raise LaunchError("Review role requires an exact model identifier")
    return PROVIDERS[key]


def _validate_against_schema(value: Any, schema: Mapping[str, Any], path: str = "$") -> None:
    """Minimal structural check of the subset of JSON Schema used by review prompts."""
    kind = schema.get("type")
    if "enum" in schema and value not in schema["enum"]:
        raise LaunchError(f"{path}: {value!r} not in {schema['enum']}")
    if kind == "object":
        if not isinstance(value, dict):
            raise LaunchError(f"{path}: expected object")
        for key in schema.get("required", []):
            if key not in value:
                raise LaunchError(f"{path}: missing {key}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(props)
            if extra:
                raise LaunchError(f"{path}: unexpected fields {sorted(extra)}")
        for key, sub in props.items():
            if key in value:
                _validate_against_schema(value[key], sub, f"{path}.{key}")
    elif kind == "array":
        if not isinstance(value, list):
            raise LaunchError(f"{path}: expected array")
        if len(value) < schema.get('minItems', 0) or len(value) > schema.get('maxItems', float('inf')):
            raise LaunchError(f"{path}: wrong item count")
        for index, item in enumerate(value):
            _validate_against_schema(item, schema.get("items", {}), f"{path}[{index}]")
    elif kind == "string":
        if not isinstance(value, str):
            raise LaunchError(f"{path}: expected string")
    elif kind == "integer":
        if type(value) is not int:
            raise LaunchError(f"{path}: expected integer")
        if "minimum" in schema and value < schema["minimum"] or "maximum" in schema and value > schema["maximum"]:
            raise LaunchError(f"{path}: out of range")
    elif kind == "boolean":
        if type(value) is not bool:
            raise LaunchError(f"{path}: expected boolean")


def run_role(
    *,
    role_name: str,
    role: Mapping[str, Any],
    system_prompt: str,
    user_prompt: str,
    schema: Mapping[str, Any],
    workdir: Path,
    timeout: int = 3600,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run one role and return (validated result, receipt). Files are kept in ``workdir``."""
    runtime = role_runtime(role)
    model = str(role["model"])
    workdir.mkdir(parents=True, exist_ok=False)
    sandbox = workdir / "empty-cwd"
    sandbox.mkdir()
    schema_text = json.dumps(schema, sort_keys=True)
    (workdir / "schema.json").write_text(schema_text + "\n")
    prompt = user_prompt if runtime == "claude" else f"{system_prompt}\n\n{user_prompt}"
    (workdir / "prompt.txt").write_text(prompt)
    (workdir / "system.txt").write_text(system_prompt)
    out_path = workdir / "output.json"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ARA_", "ZENODO_"))}

    if runtime == "claude":
        command = [_executable("claude"), "-p", "--setting-sources", "project", "--strict-mcp-config",
                   "--model", model, "--tools", "", "--no-session-persistence",
                   "--output-format", "json", "--json-schema", schema_text,
                   "--system-prompt", system_prompt]
    else:
        command = [_executable("codex"), "exec", "-m", model, "-s", "read-only", "--skip-git-repo-check",
                   "--ephemeral", "--output-schema", str(workdir / "schema.json"), "-o", str(out_path),
                   "-C", str(sandbox), "-"]
    started = _now()
    clock = time.monotonic()
    try:
        proc = subprocess.run(command, input=prompt, text=True, capture_output=True, cwd=sandbox,
                              env=env, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise LaunchError(f"{role_name}: timed out after {timeout}s") from exc
    (workdir / "stdout.txt").write_text(proc.stdout)
    (workdir / "stderr.txt").write_text(proc.stderr)
    if proc.returncode != 0:
        raise LaunchError(f"{role_name}: process exited {proc.returncode}; see {workdir / 'stderr.txt'}")

    if runtime == "claude":
        envelope = json.loads(proc.stdout)
        result = envelope.get("structured_output")
        if result is None:
            raise LaunchError(f"{role_name}: no structured output")
        reported = sorted((envelope.get("modelUsage") or {}).keys())
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    else:
        result = json.loads(out_path.read_text())
        reported = sorted(set(re.findall(r"^model:\s*(\S+)", proc.stdout + "\n" + proc.stderr, re.M)))
    if model not in reported:
        raise LaunchError(f"{role_name}: runtime reported models {reported}, expected {model}")
    _validate_against_schema(result, schema)

    receipt = {
        "role": role_name,
        "provider": role["provider"],
        "tool": role["tool"],
        "model": model,
        "runtime_reported_models": reported,
        "command": [part if len(part) < 200 else f"<{len(part)} chars>" for part in command],
        "started_at": started,
        "elapsed_seconds": round(time.monotonic() - clock, 1),
        "independent_context": True,
        # Claude explicitly receives --tools "". Codex uses its read-only runtime;
        # that sandbox does not disable tools, even when none are requested.
        "tools_enabled": runtime == 'codex',
        "tools_requested": False,
        "sandbox_mode": 'read-only' if runtime == 'codex' else 'tools-disabled',
        "author_conversation_supplied": False,
        "prior_scores_supplied": False,
        "system_prompt_sha256": _sha256(system_prompt.encode()),
        "prompt_sha256": _sha256(prompt.encode()),
        "schema_sha256": _sha256(schema_text.encode()),
        "output_sha256": _sha256(out_path.read_bytes()),
    }
    (workdir / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return result, receipt
