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
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from paper_writing import review_sandbox

if TYPE_CHECKING:
    from paper_writing.review_sandbox import ReviewMaterials

PROVIDERS = {
    ("anthropic", "Claude Code"): "claude",
    ("openai-codex", "Codex"): "codex",
    # Antigravity CLI (agy): Gemini models, a third model family for cross-family panels.
    ("google-antigravity", "Antigravity"): "agy",
}
AGY_PROVIDER = "google-antigravity"
# Providers whose roles are independent tool-using processes over a read-only view of
# the materials: they may run the formal (reference/formula) verification.
FORMAL_PROVIDERS = frozenset({"openai-codex", AGY_PROVIDER})
_AGY_WINDOW_MINUTES = {"weekly": 10_080, "5h": 300, "daily": 1_440}


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


def parse_agy_stream(stdout: str) -> tuple[dict[str, Any], str | None]:
    """(final ``result`` payload, model named by the ``init`` event) of an agy run."""
    init_model: str | None = None
    result: dict[str, Any] | None = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("event") == "init" and isinstance(event.get("init"), dict):
            model = event["init"].get("model")
            init_model = model if isinstance(model, str) else init_model
        elif event.get("event") == "result" and isinstance(event.get("result"), dict):
            result = event["result"]
    if result is None:
        raise LaunchError("Antigravity stream-json output has no final result event")
    return result, init_model


def agy_quota_reading(text: str, *, model: str | None) -> dict[str, Any] | None:
    """Quota reading from ``agy -p /usage --output-format json`` (no model call)."""
    try:
        payload = json.loads(text.strip() or "null")
    except json.JSONDecodeError:
        return None
    command = payload.get("command") if isinstance(payload, dict) else None
    data = command.get("data") if isinstance(command, dict) else None
    windows = []
    for group in (data or {}).get("groups") or []:
        for bucket in (group or {}).get("buckets") or []:
            remaining = bucket.get("remaining_fraction") if isinstance(bucket, dict) else None
            if not bucket.get("id") or isinstance(remaining, bool) or not isinstance(remaining, (int, float)):
                continue
            windows.append({"name": str(bucket["id"]),
                            "window_minutes": _AGY_WINDOW_MINUTES.get(str(bucket.get("window") or "")),
                            "used_fraction": max(0.0, min(1.0, 1.0 - float(remaining))),
                            "resets_at": bucket.get("reset_time") or None})
    if not windows:
        return None
    return {"schema_version": QUOTA_SCHEMA, "provider": AGY_PROVIDER, "observed_at": _now(),
            "model": model, "source": "unified_review_agy_usage", "windows": windows}


def agy_message(text: str) -> str:
    """The prompt as the one NDJSON user message ``agy --input-format stream-json`` reads."""
    return json.dumps({"event": "user", "message": {
        "role": "user", "content": [{"type": "text", "text": text}]}}) + "\n"


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


IMAGE_MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def claude_image_message(text: str, images: list[Path]) -> str:
    """One stream-json user message: the prompt text followed by base64 image blocks."""
    import base64

    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for path in images:
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": IMAGE_MEDIA_TYPES[path.suffix.lower()],
            "data": base64.b64encode(path.read_bytes()).decode("ascii")}})
    return json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"


def run_role(
    *,
    role_name: str,
    role: Mapping[str, Any],
    system_prompt: str,
    user_prompt: str,
    schema: Mapping[str, Any],
    workdir: Path,
    timeout: int = 3600,
    images: list[Path] | None = None,
    materials: "ReviewMaterials | None" = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run one role and return (validated result, receipt). Files are kept in ``workdir``.

    ``images`` (PNG/JPEG figure renderings) are attached to the prompt: Codex takes
    them with ``--image``; Claude, whose tools stay disabled, receives one
    stream-json user message whose content holds the text and the images.

    An Antigravity (``agy``) role always runs like the Codex read-only-copy fallback:
    the materials (and image files) are copied write-protected, the role works there
    with ``--dangerously-skip-permissions`` (headless agy denies every shell call
    otherwise), the copy and originals are hashed before and after, and the answer is
    the ``--json-schema`` structured output. Its quota comes from ``agy -p /usage``.

    ``materials`` (the registered files a Codex role may inspect, see
    :mod:`paper_writing.review_sandbox`) select the isolation: the native ``-s read-only``
    sandbox when bubblewrap works, otherwise a write-protected copy outside the workspace
    that is hashed before and after the run (a change raises ``LaunchError``). Inline-only Codex roles use the same selection and retain their exact prompt bytes.
    """
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

    attached = [Path(p).resolve() for p in images or []]  # the process runs in an empty cwd
    for path in attached:
        if path.suffix.lower() not in IMAGE_MEDIA_TYPES or not path.is_file():
            raise LaunchError(f"{role_name}: unsupported or missing image {path}")
    stdin_text = prompt
    copy: review_sandbox.ReadonlyCopy | None = None
    copy_record: dict[str, Any] | None = None
    copy_record_sha: str | None = None
    copy_violation: review_sandbox.ReadonlyCopyViolation | None = None
    sandbox_probe: dict[str, Any] | None = None
    if runtime == "agy":
        agy = _executable("agy")
        inputs = materials or review_sandbox.ReviewMaterials(workdir, {}, {})
        image_files = {f"review-images/{i}/{path.name}": path for i, path in enumerate(attached)}
        if image_files:
            if set(image_files) & (set(inputs.files) | set(inputs.relative.values())):
                raise LaunchError(f"{role_name}: attachment collides with registered materials")
            inputs = replace(inputs, files={**inputs.files, **image_files},
                             relative={**inputs.relative, **{name: name for name in image_files}},
                             extras=inputs.extras.union(image_files))
        try:
            copy = review_sandbox.ReadonlyCopy(inputs, role_name)
        except (review_sandbox.ReadonlyCopyViolation, OSError) as exc:
            raise LaunchError(f"{role_name}: read-only copy unavailable: {exc}") from exc
        try:
            copy.create()
        except (review_sandbox.ReadonlyCopyViolation, OSError) as exc:
            copy.write_record(workdir)
            copy.release()
            raise LaunchError(f"{role_name}: {exc}") from exc
        if materials is not None:
            prompt = copy.prompt(prompt, agent="Antigravity")
        if image_files:
            prompt += ("\n\nFigure renderings to inspect (open each image file with your file "
                       "viewer):\n" + "\n".join(f"- {copy.inputs / name}" for name in image_files)
                       + "\n")
        (workdir / "prompt.txt").write_text(prompt)
        stdin_text = agy_message(prompt)
        env = copy.env(env)
        sandbox = copy.inputs
        command = [agy, "-p=", "--input-format", "stream-json", "--output-format", "stream-json",
                   "--model", model, "--json-schema", schema_text, "--dangerously-skip-permissions",
                   "--print-timeout", f"{int(timeout)}s"]
    elif runtime == "claude":
        # One request per role, no session: the default 1-hour cache write (2x input)
        # is rarely read back (Fable referees: 37 runs, 14 % hits, 2.33 M tokens written).
        # Claude Code 2.1.329 honours FORCE_PROMPT_CACHING_5M (checked 2026-11-20: the
        # write moved from ephemeral_1h to ephemeral_5m), 1.25x, and a second request of
        # the same role (structured-output retry) still reads it.
        env.setdefault("FORCE_PROMPT_CACHING_5M", "1")
        command = [_executable("claude"), "-p", "--setting-sources", "project", "--strict-mcp-config",
                   "--model", model, "--tools", "", "--no-session-persistence",
                   # stream-json: the final ``result`` event is the former json envelope;
                   # the ``rate_limit_event`` lines give the reviewer's quota reading.
                   "--output-format", "stream-json", "--verbose", "--json-schema", schema_text,
                   "--system-prompt", system_prompt]
        if attached:
            command[2:2] = ["--input-format", "stream-json"]
            stdin_text = claude_image_message(prompt, attached)
    else:
        codex = _executable("codex")
        sandbox_mode, sandbox_probe = review_sandbox.select_mode(codex)
        if sandbox_mode == review_sandbox.READONLY_COPY:
            inputs = materials or review_sandbox.ReviewMaterials(workdir, {}, {})
            image_files = {f"review-images/{i}/{path.name}": path for i, path in enumerate(attached)}
            if image_files:
                if set(image_files) & (set(inputs.files) | set(inputs.relative.values())):
                    raise LaunchError(f"{role_name}: attachment collides with registered materials")
                inputs = replace(inputs, files={**inputs.files, **image_files},
                                 relative={**inputs.relative, **{name: name for name in image_files}},
                                 extras=inputs.extras.union(image_files))
            try:
                copy = review_sandbox.ReadonlyCopy(inputs, role_name)
            except (review_sandbox.ReadonlyCopyViolation, OSError) as exc:
                raise LaunchError(f"{role_name}: read-only copy unavailable: {exc}") from exc
            try:
                copy.create()
            except (review_sandbox.ReadonlyCopyViolation, OSError) as exc:
                copy.write_record(workdir)
                copy.release()
                raise LaunchError(f"{role_name}: {exc}") from exc
            # Inline verifier packets are reconstructed byte-for-byte during adoption.
            if materials is not None:
                prompt = copy.prompt(prompt)
            (workdir / "prompt.txt").write_text(prompt)
            stdin_text = prompt
            env = copy.env(env)
            sandbox = copy.inputs
        command = [codex, "exec"]
        image_paths = [copy.inputs / name for name in image_files] if copy else attached
        for path in image_paths:
            command += ["--image", str(path)]
        command += ["-m", model, "-s",
                    "danger-full-access" if copy is not None else "read-only",
                    "--skip-git-repo-check",
                    "--ephemeral", "--output-schema", str(workdir / "schema.json"), "-o", str(out_path),
                    "-C", str(sandbox), "-"]
    started = _now()
    clock = time.monotonic()
    proc = None
    try:
        proc = subprocess.run(command, input=stdin_text, text=True, capture_output=True, cwd=sandbox,
                              env=env, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        timed_out: Exception | None = exc
    else:
        timed_out = None
    finally:
        if copy is not None:
            # Hash check before anything else is trusted; the copy is discarded either way.
            try:
                copy_record = copy.verify()
            except review_sandbox.ReadonlyCopyViolation as exc:
                copy_violation = exc
            copy_record_sha = copy.write_record(workdir)
            copy.release()
    if proc is not None:
        (workdir / "stdout.txt").write_text(proc.stdout)
        (workdir / "stderr.txt").write_text(proc.stderr)
    if copy_violation is not None:
        raise LaunchError(f"{role_name}: {copy_violation}") from copy_violation
    if timed_out is not None or proc is None:
        raise LaunchError(f"{role_name}: timed out after {timeout}s") from timed_out
    if proc.returncode != 0:
        raise LaunchError(f"{role_name}: process exited {proc.returncode}; see {workdir / 'stderr.txt'}")

    if runtime == "agy":
        envelope, init_model = parse_agy_stream(proc.stdout)
        if str(envelope.get("status") or "") != "SUCCESS":
            raise LaunchError(f"{role_name}: agy result status {envelope.get('status')}: "
                              f"{str(envelope.get('error') or '')[:300]}")
        result = envelope.get("structured_output")
        if result is None:
            raise LaunchError(f"{role_name}: no structured output")
        reported = sorted({init_model} if init_model else set())
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        try:
            usage = subprocess.run([command[0], "-p", "/usage", "--output-format", "json"],
                                   text=True, capture_output=True, timeout=60, env=env,
                                   stdin=subprocess.DEVNULL)
            reading = agy_quota_reading(usage.stdout, model=init_model)
        except (OSError, subprocess.TimeoutExpired):
            reading = None
        if reading is not None:
            (workdir / QUOTA_FILE).write_text(json.dumps({**reading, "role": role_name}, indent=2) + "\n")
    elif runtime == "claude":
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
        "tools_enabled": runtime in {'codex', 'agy'},
        "tools_requested": False,
        "sandbox_mode": ((review_sandbox.READONLY_COPY if copy is not None else 'read-only')
                         if runtime in {'codex', 'agy'} else 'tools-disabled'),
        "author_conversation_supplied": False,
        "prior_scores_supplied": False,
        "system_prompt_sha256": _sha256(system_prompt.encode()),
        "prompt_sha256": _sha256(prompt.encode()),
        "schema_sha256": _sha256(schema_text.encode()),
        "output_sha256": _sha256(out_path.read_bytes()),
    }
    if runtime == "agy":
        receipt["isolation"] = "readonly_copy_agy_skip_permissions"
    if runtime == "codex":
        # "readonly-copy": bubblewrap was unavailable; the role ran with danger-full-access
        # inside a write-protected copy, hashed before and after (see review_sandbox).
        receipt["isolation"] = ("readonly_copy_danger_full_access" if copy is not None
                                else "codex_bwrap_read_only")
        receipt["native_sandbox_probe"] = sandbox_probe
    if copy_record is not None:
        receipt["readonly_copy"] = {
            "record": review_sandbox.MANIFEST_FILE, "record_sha256": copy_record_sha,
            "file_count": copy_record["file_count"], "valid": copy_record["valid"],
            "registered_sources": copy_record["post_run"]["registered_sources"],
            "outputs": len(copy_record.get("outputs") or []),
        }
    if attached:
        receipt["images"] = [{"file": path.name, "sha256": _sha256(path.read_bytes())} for path in attached]
        receipt["image_transport"] = {"codex": "codex --image", "agy": "agy read-only copy files"}.get(
            runtime, "claude stream-json image blocks")
    (workdir / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return result, receipt
