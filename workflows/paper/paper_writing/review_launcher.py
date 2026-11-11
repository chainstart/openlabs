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


QUOTA_SCHEMA = "openlabs.quota_snapshot.v1"
QUOTA_FILE = "quota.json"
_NAMED_WINDOW_MINUTES = {"five_hour": 300, "seven_day": 10_080, "one_day": 1_440}


def _window_minutes(name: str) -> int | None:
    if name in _NAMED_WINDOW_MINUTES:
        return _NAMED_WINDOW_MINUTES[name]
    match = re.match(r"^(\d+|one|five|seven)_(hour|day|minute)", name)
    if not match:
        return None
    count = int(match.group(1)) if match.group(1).isdigit() else {"one": 1, "five": 5, "seven": 7}[match.group(1)]
    return count * {"minute": 1, "hour": 60, "day": 1_440}[match.group(2)]


def _epoch_iso(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    seconds = float(value) / 1000 if value > 10**11 else float(value)
    try:
        return datetime.fromtimestamp(seconds, timezone.utc).isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def claude_quota_windows(event: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Windows of one Claude ``rate_limit_event`` (same reading as the lab runner's)."""
    info = event.get("rate_limit_info")
    if not isinstance(info, Mapping):
        return []
    raw_windows: list[tuple[str, Mapping[str, Any]]] = []
    if isinstance(info.get("unifiedWindows"), Mapping):
        raw_windows = [(str(k), v) for k, v in info["unifiedWindows"].items() if isinstance(v, Mapping)]
    elif info.get("rateLimitType") and info.get("utilization") is not None:
        raw_windows = [(str(info["rateLimitType"]), info)]
    windows = []
    for name, raw in raw_windows:
        used = raw.get("utilization")
        if isinstance(used, bool) or not isinstance(used, (int, float)):
            continue
        windows.append({"name": name, "window_minutes": _window_minutes(name),
                        "used_fraction": max(0.0, min(1.0, float(used))),
                        "resets_at": _epoch_iso(raw.get("resetsAt")), "status": raw.get("status")})
    return windows


def parse_claude_stream(stdout: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """(final ``result`` event, last rate-limit reading) of a ``stream-json`` run.

    A single JSON object (``--output-format json``, kept by older fakes and
    callers) is accepted as the result envelope with no reading.
    """
    text = stdout.strip()
    try:
        whole = json.loads(text)
    except json.JSONDecodeError:
        whole = None
    if isinstance(whole, dict):
        return whole, None
    events = []
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    if result is None:
        raise LaunchError("Claude stream-json output has no final result event")
    model = next((e["model"] for e in events if e.get("type") == "system" and isinstance(e.get("model"), str)),
                 None)
    rate = next((e for e in reversed(events) if e.get("type") == "rate_limit_event"), None)
    windows = claude_quota_windows(rate) if rate is not None else []
    reading = ({"schema_version": QUOTA_SCHEMA, "provider": "anthropic", "observed_at": _now(),
                "model": model, "source": "unified_review_claude_stream_json", "windows": windows}
               if windows else None)
    return result, reading


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
    if 'anyOf' in schema:
        for alternative in schema['anyOf']:
            try:
                _validate_against_schema(value, alternative, path)
                break
            except LaunchError:
                pass
        else:
            raise LaunchError(f"{path}: no allowed schema alternative matches")
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
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", float("inf")):
            raise LaunchError(f"{path}: wrong string length")
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
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ARA_", "ZENODO_", "SDJU_", "IMAP_", "SMTP_"))}

    if runtime == "claude":
        command = [_executable("claude"), "-p", "--setting-sources", "project", "--strict-mcp-config",
                   "--model", model, "--tools", "", "--no-session-persistence",
                   # stream-json: the final ``result`` event is the former json envelope;
                   # the ``rate_limit_event`` lines give the reviewer's quota reading.
                   "--output-format", "stream-json", "--verbose", "--json-schema", schema_text,
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
        envelope, reading = parse_claude_stream(proc.stdout)
        if reading is not None:
            # Read by the orchestrator into its quota snapshot; not part of the receipt.
            (workdir / QUOTA_FILE).write_text(json.dumps({**reading, "role": role_name}, indent=2) + "\n")
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
