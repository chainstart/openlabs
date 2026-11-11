#!/usr/bin/env python3
"""File-only runner shared by labs without importing the OpenLabs control plane."""

from __future__ import annotations

import argparse
import hashlib
import re
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any

TASK_SCHEMA = "openlabs.task.v3"
RESULT_SCHEMA = "openlabs.result_bundle.v1"
HOOK_RECEIPT_SCHEMA = "openlabs.codex_hook_receipt.v1"
HOOK_RUNTIME_SCHEMA = "openlabs.hook_runtime.v1"
LAB_RUNTIME_SCHEMA = "openlabs.lab_runtime_setup.v1"
# Agent CLIs that receive the trusted lab runtime, the generated result-gate hooks
# and the hook-receipt check.  Any other executable is a deterministic transport
# test double.
RUNTIME_ADAPTERS = frozenset({"codex", "claude"})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _terminate_process_group(process: subprocess.Popen[str], *, grace_seconds: int = 30) -> None:
    """Terminate one session leader and all of its descendants, then reap it."""

    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=max(1, grace_seconds))
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def _smoke(task: dict[str, Any], manifest: dict[str, Any], output: Path) -> None:
    artifact = output.parent / "smoke-capabilities.json"
    write_json(
        artifact,
        {
            "lab_id": manifest["lab_id"],
            "domain": manifest["domain"],
            "capabilities": manifest.get("capabilities", []),
            "manifest_schema": manifest.get("schema_version"),
        },
    )
    write_json(
        output,
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": task["task_id"],
            "campaign_id": task["campaign_id"],
            "lab_id": manifest["lab_id"],
            "domain": manifest["domain"],
            "status": "completed",
            "summary": f"{manifest['lab_id']} file-contract smoke task completed.",
            "artifacts": [
                {
                    "artifact_id": "smoke-capabilities",
                    "uri": artifact.resolve().as_uri(),
                    "sha256": sha256_file(artifact),
                    "kind": "capability_manifest",
                }
            ],
            "claims": [
                {
                    "claim_id": "lab-file-contract-smoke",
                    "text": (
                        "The lab accepted a versioned task and emitted a hash-bound result bundle."
                    ),
                    "status": "verified",
                    "evidence": ["smoke-capabilities"],
                    "limitations": ["This smoke task makes no scientific claim."],
                }
            ],
            "next_actions": [],
            "paper_candidate": False,
        },
    )


def _agent_request(
    task: dict[str, Any],
    manifest: dict[str, Any],
    output: Path,
    adapter: str | None = None,
) -> str:
    factory_skill = (
        Path(str(task["lab_manifest"])).resolve().parents[2]
        / "orchestrator"
        / "skills"
        / "openlabs-research-factory"
        / "SKILL.md"
    )
    agent = task["agent"]
    independence = (
        "Start from the frozen evidence only. Do not seek or read a creator's conversation or "
        "another reviewer's draft before submitting this review."
        if agent["role"] == "reviewer"
        else "Keep conclusions inside this role; do not review or approve your own work."
    )
    transaction = task.get("transaction") if isinstance(task.get("transaction"), Mapping) else {}
    transaction_notice = ""
    if transaction.get("mode") == "isolated_attempt_workspace":
        transaction_notice = f"""
This task runs in an isolated transaction workspace:

- writable staged campaign: `{transaction.get("staged_campaign_workspace")}`
- writable artifact staging: `{transaction.get("artifact_staging_root")}`
- canonical campaign (do not write): `{transaction.get("canonical_campaign_workspace")}`
- promotion rule: `{transaction.get("promotion_policy")}`

Keep human-readable state, proof text, small source files, summaries and manifests in the staged
campaign. Put raw datasets, solver transcripts, archives, large generated JSON/JSONL, arrays,
models and bulk outputs in artifact staging. Every staged payload must appear in result.artifacts
with its exact file URI and SHA-256; undeclared payloads fail closed. The control plane publishes
those bytes to content-addressed objects and promotes only a small reference into campaign data.
The control plane promotes the staged tree after a completed result or a valid `needs_replan`
checkpoint passes all gates. A failed, cancelled, interrupted, or invalid attempt is quarantined
automatically. Never copy staged changes to the canonical campaign yourself.
"""
    runtime_policy = (
        task.get("runtime_policy") if isinstance(task.get("runtime_policy"), Mapping) else {}
    )
    configured_skills = runtime_policy.get("skills")
    optional_methods = runtime_policy.get("optional_methods")
    if adapter == "claude" and isinstance(configured_skills, list) and configured_skills:
        # Claude Code invokes project Skills by bare name with its Skill tool.
        skill_instruction = (
            "Invoke and follow the Skills "
            + ", ".join(str(item).removeprefix("$") for item in configured_skills)
            + " with the Skill tool; their trusted project copies are under `.claude/skills/` "
            "(the same sources as `.agents/skills/`), so read a SKILL.md directly if the tool "
            "does not list one."
        )
    else:
        skill_instruction = (
            "Invoke and follow "
            + ", ".join(str(item) for item in configured_skills)
            + "; read their trusted project copies under `.agents/skills/`."
            if isinstance(configured_skills, list) and configured_skills
            else (
                f"Read and follow the factory coordinator at `{factory_skill}` and the domain "
                f"Skill at `{task.get('skill_path')}`."
            )
        )
    optional_skill_instruction = (
        " Other laboratory method guides are readable but not registered as active Skills: "
        + json.dumps(optional_methods, ensure_ascii=False, sort_keys=True)
        + ". They are optional references, not active constraints; inspect one only when you "
        "decide it helps this research."
        if isinstance(optional_methods, list) and optional_methods
        else ""
    )
    continuity_notice = """
Continue inside this {process} process across as many same-role protocol phases and ordinary
checkpoints as the scientific work and wall budget allow. Protocol phases are durable state
records, not process boundaries. Do not stop merely because a phase advanced. Stop only at an
epistemic-role boundary, an explicitly fresh boundary, a terminal scientific result, a genuine
blocker, or when the remaining wall budget is needed to persist a safe result bundle. Other
workers run independently; do not terminate this process merely to make room for them.
""".replace("{process}", "Claude Code" if adapter == "claude" else "Codex")
    project = task.get("project") if isinstance(task.get("project"), Mapping) else {}
    read_resources = project.get("read_resources", [])
    read_resource_notice = ""
    if isinstance(read_resources, list) and read_resources:
        read_resource_notice = (
            "\nCanonical read-only project resources (inspect freely; never write to them):\n\n"
            + json.dumps(read_resources, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        )
    lab_runtime = task.get("lab_runtime")
    runtime_notice = ""
    if isinstance(lab_runtime, Mapping) and lab_runtime.get("setups"):
        runtime_notice = (
            "\nTrusted laboratory runtimes prepared for this attempt:\n\n"
            + json.dumps(lab_runtime, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        )
    return f"""# OpenLabs autonomous research task

{skill_instruction}{optional_skill_instruction}

Own the analysis, decomposition, tool use, milestones, and scientific decisions needed to reach the
task objective or its declared quality gate. Perform as many safe intermediate research operations
as are useful within the declared budget. An intermediate evidence advance is a reason to persist
and continue, not a reason to stop. Durable evidence and the result contract, rather than
conversational narration, define completion.

No outer script is authorized to choose your scientific route, rank prospective ideas, or turn a
configured method into a mandatory sequence. Treat project routes, stages, and prior plans as
recoverable context only unless the objective itself logically requires one. Freely create, combine,
switch, pause, revive, or abandon approaches and use any installed laboratory capability that helps.

- task file: `{task.get("_task_file")}`
- task id: `{task["task_id"]}`
- attempt id: `{task["attempt_id"]}`
- campaign id: `{task["campaign_id"]}`
- domain: `{manifest["domain"]}`
- agent role: `{agent["role"]}`
- session policy: `{agent["session_mode"]}`
- runner tier: `{task.get("runner") or "balanced"}`
- reserved resources: `{json.dumps(task["resources"], sort_keys=True)}`
- objective: {task["objective"]}
- input state: `{task.get("input_path")}`
- required result path: `{output}`
- project config: `{project.get("config_path")}`
- domain policy/config: `{project.get("domain_config_path")}`
- workstream state: `{project.get("workstream_state_path")}`

{independence}
{continuity_notice}
{runtime_notice}
{read_resource_notice}
{transaction_notice}

Before stopping, atomically write one `openlabs.result_bundle.v1` JSON object to the required
result path. Do not write to SQLite. Preserve unsupported, negative, and inconclusive outcomes. Do
not submit, publish, spend unbounded resources, or perform another irreversible external action.
For a portfolio-review task, include `candidate_branches` (possibly empty); the control plane will
mechanically start each branch in a separate researcher campaign without altering your judgment.
"""


def _lab_runtime_setup(
    task: dict[str, Any],
    manifest: Mapping[str, Any],
    *,
    workspace: Path,
    agent_workspace: Path,
) -> dict[str, Any]:
    """Run trusted lab-declared setup commands before the Agent starts."""

    configured = manifest.get("runtime_setup", [])
    if not isinstance(configured, list):
        raise TypeError("lab runtime_setup must be an array")
    project = task.get("project")
    protocol_id = project.get("protocol_id") if isinstance(project, Mapping) else None
    for protocol in manifest.get("protocols", []):
        if protocol.get("protocol_id") != protocol_id or "runtime_setup_ids" not in protocol:
            continue
        selected = protocol["runtime_setup_ids"]
        known = {item.get("setup_id") for item in configured if isinstance(item, Mapping)}
        if (not isinstance(selected, list) or any(not isinstance(x, str) for x in selected)
                or len(set(selected)) != len(selected) or set(selected) - known):
            raise ValueError("protocol runtime_setup_ids must select unique registered setups")
        configured = [item for item in configured if item.get("setup_id") in selected]
        break
    manifest_path = Path(str(task["lab_manifest"])).expanduser().resolve()
    lab_root = manifest_path.parent
    attempt_root = str(
        (task.get("transaction") or {}).get("attempt_root") or agent_workspace
    )
    replacements = {
        "{python}": sys.executable,
        "{workspace}": str(workspace),
        "{artifacts_root}": str((workspace / "openlabs-artifacts").resolve()),
        "{lab_root}": str(lab_root),
        "{agent_workspace}": str(agent_workspace),
        "{attempt_root}": attempt_root,
        "{artifact_staging_root}": str(
            (task.get("transaction") or {}).get("artifact_staging_root")
            or (Path(attempt_root) / "artifact-stage")
        ),
        "{task_file}": str(task.get("_task_file") or ""),
    }
    results: list[dict[str, Any]] = []
    for index, item in enumerate(configured):
        if not isinstance(item, Mapping):
            raise TypeError(f"lab runtime_setup[{index}] must be an object")
        setup_id = str(item.get("setup_id") or "").strip()
        raw_command = item.get("command")
        if (
            not setup_id
            or not isinstance(raw_command, list)
            or not raw_command
            or any(not isinstance(token, str) or not token for token in raw_command)
        ):
            raise ValueError(f"invalid lab runtime setup entry {index}")
        command: list[str] = []
        for command_index, raw in enumerate(raw_command):
            token = replacements.get(raw, raw)
            if command_index > 0 and token.endswith(".py") and not Path(token).is_absolute():
                token = str((lab_root / token).resolve())
            command.append(token)
        timeout = item.get("timeout_seconds", 1800)
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1:
            raise ValueError(f"runtime setup {setup_id} timeout must be positive")
        completed = subprocess.run(
            command,
            cwd=lab_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(
                f"runtime setup {setup_id} emitted invalid JSON: {detail[:1000]}"
            ) from exc
        if (
            completed.returncode != 0
            or not isinstance(payload, Mapping)
            or payload.get("valid") is not True
        ):
            detail = (
                payload.get("errors") if isinstance(payload, Mapping) else completed.stderr.strip()
            )
            raise RuntimeError(f"runtime setup {setup_id} failed: {detail}")
        results.append({"setup_id": setup_id, **dict(payload)})
    return {"schema_version": LAB_RUNTIME_SCHEMA, "setups": results}


def _command_template(raw_command: str) -> list[str]:
    try:
        template = json.loads(raw_command)
    except json.JSONDecodeError:
        template = shlex.split(raw_command)
    if (
        not isinstance(template, list)
        or not template
        or any(not isinstance(item, str) for item in template)
    ):
        raise ValueError("Agent command must be a JSON array of argv strings")
    return template


def _configured_agent_adapter(task: Mapping[str, Any]) -> str | None:
    """Return the configured executable name without starting or preparing the agent."""

    runner = str(task.get("runner") or "balanced")
    runner_key = "".join(
        character if character.isalnum() else "_" for character in runner
    ).upper()
    agent = task.get("agent") if isinstance(task.get("agent"), Mapping) else {}
    session_id = (
        str(agent.get("session_id") or "").strip()
        if agent.get("role") != "reviewer" and agent.get("session_mode") == "resume"
        else ""
    )
    command_kind = "RESUME_COMMAND" if session_id else "COMMAND"
    raw_command = os.environ.get(f"OPENLABS_AGENT_{command_kind}_{runner_key}_JSON", "").strip()
    raw_command = raw_command or os.environ.get(f"OPENLABS_AGENT_{command_kind}_JSON", "").strip()
    if not raw_command:
        return None
    return Path(_command_template(raw_command)[0]).name


def _command_option(command: list[str], *names: str) -> str | None:
    for index, token in enumerate(command):
        if token in names and index + 1 < len(command):
            return command[index + 1]
        for name in names:
            prefix = f"{name}="
            if token.startswith(prefix):
                return token[len(prefix) :]
    return None


def _positive_environment_number(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _environment_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _codex_base_url(command: list[str]) -> str | None:
    override = os.environ.get("OPENLABS_AGENT_PREFLIGHT_URL", "").strip()
    if override:
        return override
    assignments: list[str] = []
    for index, token in enumerate(command):
        if token == "-c" and index + 1 < len(command):
            assignments.append(command[index + 1])
        elif token.startswith("-c="):
            assignments.append(token[3:])
    for assignment in assignments:
        key, separator, raw_value = assignment.partition("=")
        if not separator or not key.strip().endswith(".base_url"):
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value or None
    return None


def _agent_connectivity_preflight(command: list[str]) -> str | None:
    """Return a redacted connectivity error, or None when reachable/not applicable."""

    if Path(command[0]).name != "codex":
        return None
    target = _codex_base_url(command)
    if target is None:
        return None
    parsed = urllib.parse.urlsplit(target)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return "configured Agent provider URL is not a valid HTTP(S) endpoint"
    endpoint = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port is not None:
        endpoint += f":{parsed.port}"
    request = urllib.request.Request(
        target,
        method="HEAD",
        headers={"User-Agent": "openlabs-agent-preflight/1"},
    )
    timeout = _positive_environment_number(
        "OPENLABS_AGENT_PREFLIGHT_TIMEOUT_SECONDS",
        10.0,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            return None
    except urllib.error.HTTPError:
        # Authentication and method errors still prove DNS, proxy, TLS, and the
        # configured provider endpoint are reachable. Codex owns auth details.
        return None
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        error = f"Agent provider {endpoint} is unreachable: {type(exc).__name__}: {exc}"
        if _environment_flag("OPENLABS_AGENT_PREFLIGHT_STRICT"):
            return error
        # urllib and Codex do not necessarily share a transport stack (for
        # example, Codex may use its own proxy or authenticated transport).
        # Treat this lightweight HEAD failure as advisory by default and let
        # the bounded JSONL startup watchdog judge the real Agent process.
        return None


# --------------------------------------------------------------------------
# Provider quota / rate-limit classification (failure_class "agent_quota").
#
# One table, easy to extend. Each entry is (kind, regex, provenance). Matching is
# applied ONLY to provider-error channels -- Codex ``error``/``turn.failed`` JSONL
# events, Claude ``result`` events with ``is_error`` or an ``apiError`` field, and
# the tail of non-JSON stdout/stderr -- never to the agent's own tool output or
# research prose, which routinely mention "rate-limited" third-party APIs.
# Provenance: "sample" = seen verbatim in a local run log/transcript;
# "cli-string" = message template embedded in the installed CLI binary;
# "unverified" = conservative rule without a local sample.
AGENT_QUOTA_MARKERS: tuple[tuple[str, str, str], ...] = (
    # Claude Code: "You've hit your 5-hour limit · resets 12:40am (Asia/Singapore)";
    # Codex: "You've hit your usage limit. ... try again at 3:05 PM."
    ("usage_limit", r"you(?:'|’)?ve hit your (?:[\w-]+ )?limit", "sample"),
    ("usage_limit", r"\busage_limit_(?:reached|exceeded)\b", "sample"),
    ("usage_limit", r"\b(?:workspace_(?:owner|member)_)?usage_limit_reached\b", "cli-string"),
    ("usage_limit", r"\bworkspace_member_credits_depleted\b", "cli-string"),
    ("usage_limit", r"quota exceeded\. check your plan and billing", "cli-string"),
    ("usage_limit", r"\bquota_exceeded\b", "cli-string"),
    ("usage_limit", r"\binsufficient_quota\b", "unverified"),
    ("usage_limit", r"\bclaude ai usage limit reached\b", "unverified"),
    ("rate_limit", r"error type rate_limit\b", "sample"),
    ("rate_limit", r"\brate_limit_(?:exceeded|reached|error)\b", "cli-string"),
    ("rate_limit", r"exceeded retry limit, last status: 429\b", "cli-string"),
    ("rate_limit", r"unexpected status 429\b", "unverified"),
    ("rate_limit", r"\bAPI Error: 429\b", "unverified"),
    ("capacity", r"selected model is at capacity", "sample"),
    ("capacity", r"\bserver_overloaded\b", "cli-string"),
    ("capacity", r"\boverloaded_error\b", "unverified"),
    ("capacity", r"\bAPI Error: 529\b", "unverified"),
)
_QUOTA_PATTERNS = tuple(
    (kind, re.compile(pattern, re.IGNORECASE), provenance)
    for kind, pattern, provenance in AGENT_QUOTA_MARKERS
)
_PROVIDER_ERROR_EVENT_TYPES = frozenset({"error", "turn.failed", "stream_error"})
_QUOTA_TAIL_BYTES = 64 * 1024
_MONTHS = {
    name: index
    for index, names in enumerate(
        (
            ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
            ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
            ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
            ("dec", "december"),
        ),
        start=1,
    )
    for name in names
}
_RESET_CLOCK = re.compile(
    r"(?:resets?(?: at)?|try again at)\s+"
    r"(?:(?P<month>[a-z]{3,9})\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+"
    r"(?:(?P<year>\d{4}),?\s+)?(?:at\s+)?)?"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>[ap]\.?m\.?)?"
    r"(?:\s*\((?P<zone>[A-Za-z_]+(?:/[A-Za-z_+-]+)*)\))?",
    re.IGNORECASE,
)
_RESET_DURATION = re.compile(
    r"(?:resets?|try again) in\s+(?P<spec>(?:\d+\s*(?:days?|d|hours?|hrs?|h|minutes?|mins?|m|"
    r"seconds?|secs?|s)\b[\s,]*(?:and\s+)?)+)",
    re.IGNORECASE,
)
_DURATION_PART = re.compile(
    r"(\d+)\s*(days?|d|hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b", re.IGNORECASE
)
_EPOCH_RESET_KEYS = ("resetsAt", "resets_at", "reset_at", "resetAt")


def _local_zone() -> tzinfo:
    return datetime.now().astimezone().tzinfo or UTC


def _named_zone(name: str | None) -> tzinfo | None:
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - unknown zone names fall back to local time
        return None


def _iso_z(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_quota_reset(
    text: str,
    *,
    now: datetime | None = None,
    local_zone: tzinfo | None = None,
) -> str | None:
    """Return the provider's quota reset time as an ISO UTC string, if stated.

    Understands "resets 12:40am (Asia/Singapore)", "try again at 3:05 PM",
    "try again at Nov 12th, 2026 3:05 PM", "resets in 2h 5m" and epoch-second
    ``resetsAt`` fields. Clock times without a zone use ``local_zone`` (default:
    this host's zone) and roll to the next occurrence after ``now``.
    """

    current = (now or datetime.now(UTC)).astimezone(UTC)
    for key in _EPOCH_RESET_KEYS:
        match = re.search(rf'"{key}"\s*:\s*(\d{{9,13}})', text)
        if match:
            value = int(match.group(1))
            if value > 10**11:
                value //= 1000
            return _iso_z(datetime.fromtimestamp(value, UTC))
    match = _RESET_DURATION.search(text)
    if match:
        seconds = 0
        for amount, unit in _DURATION_PART.findall(match.group("spec")):
            unit = unit.lower()
            factor = (
                86_400 if unit.startswith("d")
                else 3_600 if unit.startswith("h")
                else 60 if unit.startswith("m")
                else 1
            )
            seconds += int(amount) * factor
        if seconds > 0:
            return _iso_z(current + timedelta(seconds=seconds))
    match = _RESET_CLOCK.search(text)
    if match:
        hour = int(match.group("hour"))
        minute = int(match.group("minute") or 0)
        ampm = (match.group("ampm") or "").replace(".", "").lower()
        if not ampm and match.group("minute") is None:
            return None  # a bare number is too ambiguous to be a clock time
        if ampm:
            if not 1 <= hour <= 12:
                return None
            hour = hour % 12 + (12 if ampm == "pm" else 0)
        if hour > 23 or minute > 59:
            return None
        zone = _named_zone(match.group("zone")) or local_zone or _local_zone()
        local_now = current.astimezone(zone)
        month_name = (match.group("month") or "").lower()
        if month_name:
            month = _MONTHS.get(month_name)
            if month is None:
                return None
            year = int(match.group("year") or local_now.year)
            try:
                day = int(match.group("day"))
                candidate = datetime(year, month, day, hour, minute, tzinfo=zone)
            except ValueError:
                return None
            if match.group("year") is None and candidate < local_now - timedelta(days=1):
                candidate = candidate.replace(year=year + 1)
            return _iso_z(candidate)
        candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= local_now:
            candidate += timedelta(days=1)
        return _iso_z(candidate)
    return None


def _read_tail(path: Path | None, limit: int = _QUOTA_TAIL_BYTES) -> str:
    if path is None or not path.is_file():
        return ""
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - limit))
        return handle.read().decode("utf-8", errors="replace")


def _provider_error_texts(event: Mapping[str, Any]) -> list[str]:
    """Extract provider/CLI error text from one JSONL event (never tool output)."""

    texts: list[str] = []
    event_type = str(event.get("type") or "")
    if event_type in _PROVIDER_ERROR_EVENT_TYPES:
        texts.append(json.dumps(event, ensure_ascii=False))
    elif event_type == "result" and event.get("is_error") is True:
        texts.append(json.dumps(event, ensure_ascii=False))
    elif "apiError" in event or isinstance(event.get("error"), (str, Mapping)):
        # Claude transcripts/stream events mark failed API turns with apiError/error.
        texts.append(json.dumps(event, ensure_ascii=False))
    return texts


def classify_agent_quota(
    *,
    stdout_text: str = "",
    stderr_text: str = "",
    now: datetime | None = None,
    local_zone: tzinfo | None = None,
) -> dict[str, Any] | None:
    """Detect provider quota exhaustion or rate limiting in agent process output.

    Returns ``{"kind", "marker", "provenance", "source", "excerpt",
    "quota_reset_at"}`` for the first match, or None. Only provider-error
    channels are inspected (see ``AGENT_QUOTA_MARKERS``).
    """

    candidates: list[tuple[str, str]] = []
    for line in stdout_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            candidates.append(("stdout", stripped))
            continue
        if isinstance(event, Mapping):
            candidates.extend(("stdout_jsonl", text) for text in _provider_error_texts(event))
    for line in stderr_text.splitlines():
        stripped = line.strip()
        if stripped:
            candidates.append(("stderr", stripped))
    # Later messages are the decisive ones; scan newest first.
    for source, text in reversed(candidates):
        for kind, pattern, provenance in _QUOTA_PATTERNS:
            match = pattern.search(text)
            if match is None:
                continue
            start = max(0, match.start() - 120)
            return {
                "kind": kind,
                "marker": pattern.pattern,
                "provenance": provenance,
                "source": source,
                "excerpt": text[start : match.end() + 180],
                "quota_reset_at": parse_quota_reset(text, now=now, local_zone=local_zone),
            }
    return None


def _agent_quota_failure(stdout_path: Path, stderr_path: Path) -> dict[str, Any] | None:
    return classify_agent_quota(
        stdout_text=_read_tail(stdout_path),
        stderr_text=_read_tail(stderr_path),
    )


# --------------------------------------------------------------------------
# Subscription quota readings (runtime.quota_snapshot).
#
# Claude Code (`-p --output-format stream-json --verbose`) emits one
# ``rate_limit_event`` per call whose ``rate_limit_info.unifiedWindows`` maps a
# window name (five_hour, seven_day, and model-specific ones such as
# seven_day_overage_included) to ``utilization`` in 0..1. Codex writes
# ``rate_limits`` (``primary``/``secondary`` slots, ``used_percent`` 0..100,
# ``window_minutes``) into ``$CODEX_HOME/sessions/YYYY/MM/DD/rollout-*-<thread>.jsonl``;
# ``codex exec --json`` (0.166.0) does not repeat it on stdout, so the session file
# is read when the stream has none. Every reading is normalised to
# ``{"provider", "observed_at", "model", "windows": [{"name", "window_minutes",
# "used_fraction", "resets_at"}], "credits_balance"}``.
QUOTA_SNAPSHOT_SCHEMA = "openlabs.quota_snapshot.v1"
ADAPTER_PROVIDERS = {"claude": "anthropic", "codex": "openai-codex"}
_NAMED_WINDOW_MINUTES = {"five_hour": 300, "seven_day": 10_080, "one_day": 1_440}
_WINDOW_NAME_PATTERN = re.compile(r"^(?P<count>\d+|one|five|seven)_(?P<unit>hour|day|minute)")
_WORD_NUMBERS = {"one": 1, "five": 5, "seven": 7}
_CODEX_SESSION_TAIL_BYTES = 512 * 1024
_CODEX_SESSION_DAY_LOOKBACK = 3


def _window_minutes_from_name(name: str) -> int | None:
    """``five_hour`` -> 300, ``seven_day_overage_included`` -> 10080, else None."""

    if name in _NAMED_WINDOW_MINUTES:
        return _NAMED_WINDOW_MINUTES[name]
    match = _WINDOW_NAME_PATTERN.match(name)
    if match is None:
        return None
    raw = match.group("count")
    count = int(raw) if raw.isdigit() else _WORD_NUMBERS[raw]
    return count * {"minute": 1, "hour": 60, "day": 1_440}[match.group("unit")]


def _window_name_from_minutes(minutes: int | None) -> str:
    for name, value in _NAMED_WINDOW_MINUTES.items():
        if minutes == value:
            return name
    return f"{minutes}_minute" if minutes else "unknown_window"


def _epoch_iso(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    seconds = float(value) / 1000 if value > 10**11 else float(value)
    try:
        return _iso_z(datetime.fromtimestamp(seconds, UTC))
    except (OverflowError, OSError, ValueError):
        return None


def _fraction(value: Any, *, percent: bool) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    fraction = float(value) / 100.0 if percent else float(value)
    return max(0.0, min(1.0, fraction))


def claude_quota_windows(event: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Windows of one Claude ``rate_limit_event`` (all names kept, unknown ones too)."""

    info = event.get("rate_limit_info")
    if not isinstance(info, Mapping):
        return []
    windows: list[dict[str, Any]] = []
    unified = info.get("unifiedWindows")
    if isinstance(unified, Mapping):
        for name, raw in unified.items():
            if not isinstance(raw, Mapping):
                continue
            used = _fraction(raw.get("utilization"), percent=False)
            if used is None:
                continue
            windows.append(
                {
                    "name": str(name),
                    "window_minutes": _window_minutes_from_name(str(name)),
                    "used_fraction": used,
                    "resets_at": _epoch_iso(raw.get("resetsAt")),
                    "status": raw.get("status"),
                }
            )
    elif info.get("rateLimitType") and info.get("utilization") is not None:
        name = str(info["rateLimitType"])
        used = _fraction(info.get("utilization"), percent=False)
        if used is not None:
            windows.append(
                {
                    "name": name,
                    "window_minutes": _window_minutes_from_name(name),
                    "used_fraction": used,
                    "resets_at": _epoch_iso(info.get("resetsAt")),
                    "status": info.get("status"),
                }
            )
    return windows


def codex_quota_windows(rate_limits: Mapping[str, Any]) -> tuple[list[dict[str, Any]], Any]:
    """Windows and credit balance of one Codex ``rate_limits`` object.

    Slots are named by ``window_minutes`` (a weekly-only plan has just a 10080-minute
    ``primary``; ``secondary`` may be null). A non-default ``limit_id`` prefixes the name.
    """

    windows: list[dict[str, Any]] = []
    limit_id = str(rate_limits.get("limit_id") or "codex")
    for slot in ("primary", "secondary"):
        raw = rate_limits.get(slot)
        if not isinstance(raw, Mapping):
            continue
        used = _fraction(raw.get("used_percent"), percent=True)
        if used is None:
            continue
        minutes = raw.get("window_minutes")
        minutes = int(minutes) if isinstance(minutes, (int, float)) and minutes > 0 else None
        name = _window_name_from_minutes(minutes)
        if limit_id != "codex":
            name = f"{limit_id}:{name}"
        windows.append(
            {
                "name": name,
                "window_minutes": minutes,
                "used_fraction": used,
                "resets_at": _epoch_iso(raw.get("resets_at")),
                "slot": slot,
            }
        )
    credits = rate_limits.get("credits")
    balance = credits.get("balance") if isinstance(credits, Mapping) else None
    return windows, balance


def _find_rate_limits(value: Any, depth: int = 0) -> Mapping[str, Any] | None:
    if depth > 4 or not isinstance(value, Mapping):
        return None
    candidate = value.get("rate_limits")
    if isinstance(candidate, Mapping):
        return candidate
    for child in value.values():
        if isinstance(child, Mapping):
            found = _find_rate_limits(child, depth + 1)
            if found is not None:
                return found
    return None


def _jsonl_events(text: str) -> list[Mapping[str, Any]]:
    events: list[Mapping[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(event, Mapping):
            events.append(event)
    return events


def _snapshot(
    provider: str,
    windows: list[dict[str, Any]],
    *,
    observed_at: str,
    model: str | None,
    source: str,
    credits_balance: Any = None,
) -> dict[str, Any] | None:
    if not windows:
        return None
    snapshot: dict[str, Any] = {
        "schema_version": QUOTA_SNAPSHOT_SCHEMA,
        "provider": provider,
        "observed_at": observed_at,
        "model": model,
        "source": source,
        "windows": windows,
    }
    if credits_balance is not None:
        try:
            snapshot["credits_balance"] = float(credits_balance)
        except (TypeError, ValueError):
            snapshot["credits_balance"] = str(credits_balance)
    return snapshot


def codex_sessions_root() -> Path:
    configured = os.environ.get("CODEX_HOME", "").strip()
    home = Path(configured).expanduser() if configured else Path.home() / ".codex"
    return home / "sessions"


def find_codex_session_file(
    thread_id: str,
    *,
    sessions_root: Path | None = None,
    now: datetime | None = None,
) -> Path | None:
    """Locate ``rollout-*-<thread_id>.jsonl`` in the last few day directories only."""

    if not thread_id or "/" in thread_id or not re.fullmatch(r"[A-Za-z0-9-]+", thread_id):
        return None
    root = sessions_root or codex_sessions_root()
    current = (now or datetime.now(UTC)).astimezone()
    for offset in range(_CODEX_SESSION_DAY_LOOKBACK):
        day = current - timedelta(days=offset)
        directory = root / f"{day.year:04d}" / f"{day.month:02d}" / f"{day.day:02d}"
        if not directory.is_dir():
            continue
        matches = sorted(directory.glob(f"rollout-*{thread_id}.jsonl"))
        if matches:
            return matches[-1]
    return None


def codex_session_quota(path: Path, *, model: str | None = None) -> dict[str, Any] | None:
    """The newest ``rate_limits`` reading in the tail of one Codex session file."""

    text = _read_tail(path, _CODEX_SESSION_TAIL_BYTES)
    for event in reversed(_jsonl_events(text)):
        rate_limits = _find_rate_limits(event)
        if rate_limits is None:
            continue
        windows, balance = codex_quota_windows(rate_limits)
        observed = event.get("timestamp")
        observed_at = (
            observed if isinstance(observed, str) and observed else _iso_z(datetime.now(UTC))
        )
        return _snapshot(
            "openai-codex",
            windows,
            observed_at=observed_at,
            model=model,
            source="codex_session_file",
            credits_balance=balance,
        )
    return None


def extract_quota_snapshot(
    stdout_text: str,
    *,
    adapter: str,
    model: str | None = None,
    now: datetime | None = None,
    sessions_root: Path | None = None,
) -> dict[str, Any] | None:
    """Return the run's last quota reading, or None when the run reported none."""

    observed_at = _iso_z((now or datetime.now(UTC)).astimezone(UTC))
    events = _jsonl_events(stdout_text)
    if adapter == "claude":
        reported_model = model
        for event in events:
            if event.get("type") == "system" and isinstance(event.get("model"), str):
                reported_model = event["model"]
        for event in reversed(events):
            if event.get("type") == "rate_limit_event":
                return _snapshot(
                    "anthropic",
                    claude_quota_windows(event),
                    observed_at=observed_at,
                    model=reported_model,
                    source="claude_stream_json",
                )
        return None
    if adapter == "codex":
        thread_id = ""
        for event in reversed(events):
            rate_limits = _find_rate_limits(event)
            if rate_limits is not None:
                windows, balance = codex_quota_windows(rate_limits)
                return _snapshot(
                    "openai-codex",
                    windows,
                    observed_at=observed_at,
                    model=model,
                    source="codex_exec_json",
                    credits_balance=balance,
                )
        for event in events:
            candidate = event.get("thread_id") or event.get("session_id")
            if isinstance(candidate, str) and candidate:
                thread_id = candidate
                break
        session_file = find_codex_session_file(
            thread_id, sessions_root=sessions_root, now=now
        )
        if session_file is None:
            return None
        return codex_session_quota(session_file, model=model)
    return None


def _agent_quota_snapshot(
    stdout_path: Path,
    *,
    adapter: str,
    model: str | None,
) -> dict[str, Any] | None:
    try:
        text = stdout_path.read_text(encoding="utf-8", errors="replace")
        return extract_quota_snapshot(text, adapter=adapter, model=model)
    except (OSError, ValueError):
        return None


_TRANSPORT_FAILURE_MARKERS = (
    "connection failed",
    "error sending request",
    "waiting for network",
    "connection reset",
    "connection refused",
)


def _jsonl_startup_health(path: Path) -> tuple[int, bool]:
    """Count transport failures and detect any meaningful Codex progress."""

    failures = 0
    meaningful_progress = False
    if not path.is_file():
        return failures, meaningful_progress
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, Mapping):
            continue
        serialized = json.dumps(event, ensure_ascii=False).lower()
        if any(marker in serialized for marker in _TRANSPORT_FAILURE_MARKERS):
            failures += 1
        event_type = str(event.get("type") or "")
        item = event.get("item") if isinstance(event.get("item"), Mapping) else {}
        item_type = str(item.get("type") or "")
        if event_type == "turn.completed" or (
            event_type == "item.completed" and item_type not in {"", "error"}
        ):
            meaningful_progress = True
    return failures, meaningful_progress


def _claude_startup_health(path: Path) -> tuple[int, bool, bool]:
    """Count Claude transport retries, detect model progress and any stream event.

    ``claude -p --output-format stream-json --verbose`` writes a ``system``/``init``
    event before its first API request, ``system``/``api_retry`` events while a
    request is being retried, and ``assistant``/``user``/``result`` events once the
    model answers.  A retry without an HTTP status (``error_status`` null) or with a
    network error text is a transport failure; 429/529 retries are quota/capacity
    and are left to the quota classifier.
    """

    failures = 0
    meaningful_progress = False
    any_event = False
    if not path.is_file():
        return failures, meaningful_progress, any_event
    for event in _jsonl_events(path.read_text(encoding="utf-8", errors="replace")):
        any_event = True
        event_type = str(event.get("type") or "")
        if event_type in {"assistant", "user", "result"}:
            meaningful_progress = True
        elif event_type == "system" and event.get("subtype") == "api_retry":
            error_text = str(event.get("error") or "").lower()
            if event.get("error_status") is None or any(
                marker in error_text for marker in _TRANSPORT_FAILURE_MARKERS
            ):
                failures += 1
    return failures, meaningful_progress, any_event


def _jsonl_runtime(path: Path) -> dict[str, Any]:
    runtime: dict[str, Any] = {}
    if not path.is_file():
        return runtime
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, Mapping):
            continue
        thread_id = event.get("thread_id") or event.get("session_id")
        if isinstance(thread_id, str) and thread_id:
            runtime["session_id"] = thread_id
        for key in ("model", "provider", "effort", "cost_usd"):
            value = event.get(key)
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                runtime[key] = value
        usage = event.get("usage")
        if isinstance(usage, Mapping):
            for key in (
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "reasoning_output_tokens",
            ):
                value = usage.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    runtime[key] = value
            # Claude stream-json ``result`` usage names its cache reads differently.
            cache_read = usage.get("cache_read_input_tokens")
            if (
                "cached_input_tokens" not in usage
                and isinstance(cache_read, int)
                and not isinstance(cache_read, bool)
                and cache_read >= 0
            ):
                runtime["cached_input_tokens"] = cache_read
        total_cost = event.get("total_cost_usd")
        if isinstance(total_cost, (int, float)) and not isinstance(total_cost, bool):
            runtime["cost_usd"] = total_cost
    return runtime


def _hook_runtime(path: Path, *, agent_workspace: Path) -> dict[str, Any]:
    """Collect generated lifecycle-hook receipts without interpreting research content."""

    expected = (agent_workspace / ".codex" / "hook-receipts.jsonl").resolve()
    if path.expanduser().resolve() != expected:
        raise ValueError("Generated hook receipt path does not match the attempt runtime")
    events: list[dict[str, Any]] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, Mapping) or event.get("schema_version") != (
                HOOK_RECEIPT_SCHEMA
            ):
                continue
            events.append(dict(event))
    starts = [item for item in events if item.get("hook_event_name") == "SessionStart"]
    stops = [item for item in events if item.get("hook_event_name") == "Stop"]
    return {
        "schema_version": HOOK_RUNTIME_SCHEMA,
        "receipt_path": str(path.resolve()),
        "events": events,
        "session_start_count": len(starts),
        "stop_count": len(stops),
        "stop_passed": any(item.get("outcome") == "result_gate_passed" for item in stops),
        "stop_blocked": sum(item.get("outcome") == "result_gate_blocked" for item in stops),
        "stop_failed_final": sum(
            item.get("outcome") == "result_gate_failed_final" for item in stops
        ),
    }


def _adapter_version(command: list[str]) -> str | None:
    if Path(command[0]).name not in RUNTIME_ADAPTERS:
        return None
    try:
        completed = subprocess.run(
            [command[0], "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    version = completed.stdout.strip()
    return version or None


def _configuration_result(
    task: dict[str, Any],
    manifest: dict[str, Any],
    output: Path,
    summary: str,
) -> None:
    write_json(
        output,
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": task["task_id"],
            "campaign_id": task["campaign_id"],
            "lab_id": manifest["lab_id"],
            "domain": manifest["domain"],
            "status": "needs_human",
            "summary": summary,
            "artifacts": [],
            "claims": [],
            "next_actions": ["Repair the local Agent command configuration, then retry."],
            "paper_candidate": False,
        },
    )


def _remove_flags(command: list[str], names: set[str]) -> list[str]:
    return [
        token
        for token in command
        if token not in names and not any(token.startswith(f"{name}=") for name in names)
    ]


def _remove_value_options(command: list[str], names: set[str]) -> list[str]:
    filtered: list[str] = []
    skip_next = False
    for token in command:
        if skip_next:
            skip_next = False
            continue
        if token in names:
            skip_next = True
            continue
        if any(token.startswith(f"{name}=") for name in names):
            continue
        filtered.append(token)
    if skip_next:
        raise ValueError("Codex command ends with an option that requires a value")
    return filtered


def _config_override_keys(command: list[str]) -> set[str]:
    keys: set[str] = set()
    for index, token in enumerate(command):
        value: str | None = None
        if token in {"-c", "--config"} and index + 1 < len(command):
            value = command[index + 1]
        elif token.startswith(("-c=", "--config=")):
            value = token.split("=", 1)[1]
        if value:
            keys.add(value.split("=", 1)[0].strip())
    return keys


def _remove_config_overrides(command: list[str], keys: set[str]) -> list[str]:
    """Remove selected Codex config overrides so factory policy stays authoritative."""

    filtered: list[str] = []
    index = 0
    while index < len(command):
        token = command[index]
        if token in {"-c", "--config"}:
            if index + 1 >= len(command):
                raise ValueError("Codex command ends with an option that requires a value")
            value = command[index + 1]
            if value.split("=", 1)[0].strip() not in keys:
                filtered.extend((token, value))
            index += 2
            continue
        if token.startswith(("-c=", "--config=")):
            value = token.split("=", 1)[1]
            if value.split("=", 1)[0].strip() not in keys:
                filtered.append(token)
            index += 1
            continue
        filtered.append(token)
        index += 1
    return filtered


def _prepare_codex_command(
    command: list[str],
    *,
    agent_workspace: Path,
    trust_generated_hooks: bool,
) -> list[str]:
    """Apply the factory's invariant Codex policy without wrapping Codex itself."""

    if Path(command[0]).name != "codex":
        return command
    if len(command) < 2 or command[1] != "exec":
        raise ValueError("The Codex adapter must use `codex exec`")
    forbidden = {
        "--dangerously-bypass-approvals-and-sandbox",
        "--yolo",
    }
    if any(
        token in forbidden or any(token.startswith(f"{name}=") for name in forbidden)
        for token in command
    ):
        raise ValueError("The Codex adapter may not override the factory's full-access policy")
    if any(token == "--add-dir" or token.startswith("--add-dir=") for token in command):
        raise ValueError("OpenLabs Codex tasks do not need extra writable roots in full-access mode")
    if any(
        (token == "--disable" and index + 1 < len(command) and command[index + 1] == "hooks")
        or token == "--disable=hooks"
        for index, token in enumerate(command)
    ):
        raise ValueError("OpenLabs Codex tasks require lifecycle hooks")
    protected_config = {
        "approval_policy",
        "features.hooks",
        "sandbox_mode",
        "sandbox_permissions",
        "sandbox_workspace_write.writable_roots",
        "sandbox_workspace_write.network_access",
    }
    if _config_override_keys(command) & protected_config:
        raise ValueError("The Codex adapter may not override factory runtime policy")
    configured_sandbox = _command_option(command, "--sandbox", "-s")
    if configured_sandbox not in {None, "danger-full-access"}:
        raise ValueError("OpenLabs Codex tasks require the danger-full-access runtime")

    tail = _remove_config_overrides(command[2:], {"web_search"})
    tail = _remove_value_options(tail, {"--sandbox", "-s", "--cd", "-C"})
    tail = _remove_flags(
        tail,
        {
            "--approve-for-me",
            "--full-auto",
            "--json",
            "--search",
            "--skip-git-repo-check",
            "--dangerously-bypass-hook-trust",
        },
    )
    policy = [
        "-c",
        'approval_policy="never"',
        "-c",
        'web_search="live"',
        "--enable",
        "hooks",
        "--sandbox",
        "danger-full-access",
        "--json",
        "--skip-git-repo-check",
        "-C",
        str(agent_workspace),
    ]
    if trust_generated_hooks:
        policy.append("--dangerously-bypass-hook-trust")
    return [command[0], "exec", *policy, *tail]


# Claude Code tool permissions for unattended research.  ``dontAsk`` denies every
# call that is not pre-approved (no prompt can hang a headless run) and the list
# below pre-approves the ordinary research tools.  The filesystem boundary is the
# bubblewrap transaction sandbox, not this list; ``--dangerously-skip-permissions``
# / ``bypassPermissions`` are refused because they are not needed for that.
CLAUDE_PERMISSION_MODE = "dontAsk"
CLAUDE_ALLOWED_TOOLS = (
    "Bash",
    "Read",
    "Edit",
    "Write",
    "MultiEdit",
    "NotebookEdit",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
    "Skill",
    "TodoWrite",
)
# Sub-agent tools, by tier (cost control: five parallel sub-agents once used a whole
# five-hour window in ten minutes). The orchestrator writes the decision into the
# task's ``agent_tools.allow_subagents``: lead tier yes, worker and light tiers no,
# ``[runners.<name>].allow_subagents`` overrides. Task files written before that
# field fall back to the legacy runner name (``frontier``/``lead`` only).
CLAUDE_SUBAGENT_TOOLS = ("Task", "Agent")
LEGACY_SUBAGENT_RUNNERS = frozenset({"frontier", "lead"})


def claude_allowed_tools(*, allow_subagents: bool) -> tuple[str, ...]:
    return CLAUDE_ALLOWED_TOOLS + (CLAUDE_SUBAGENT_TOOLS if allow_subagents else ())


def task_allows_subagents(task: Mapping[str, Any]) -> bool:
    tools = task.get("agent_tools")
    if isinstance(tools, Mapping) and isinstance(tools.get("allow_subagents"), bool):
        return tools["allow_subagents"]
    return str(task.get("runner") or "") in LEGACY_SUBAGENT_RUNNERS
# Project sources only: the attempt workspace's own ``.claude`` (generated, never
# promoted).  The operator's user-level settings -- which may carry another default
# permission mode, model, hooks or a relay endpoint -- are not loaded; the factory
# hooks arrive through ``--settings``.
CLAUDE_SETTING_SOURCES = "project"


def _remove_variadic_options(command: list[str], names: set[str]) -> list[str]:
    """Remove options whose values run until the next ``-`` token (Claude's ``<x...>``)."""

    filtered: list[str] = []
    skipping = False
    for token in command:
        if skipping and not token.startswith("-"):
            continue
        skipping = False
        if token in names:
            skipping = True
            continue
        if any(token.startswith(f"{name}=") for name in names):
            continue
        filtered.append(token)
    return filtered


def _prepare_claude_command(
    command: list[str],
    *,
    settings_path: Path,
    attempt_root: Path,
    allow_subagents: bool = False,
) -> list[str]:
    """Apply the factory's invariant Claude Code policy to a configured argv."""

    if Path(command[0]).name != "claude":
        return command
    forbidden = {
        "--dangerously-skip-permissions",
        "--allow-dangerously-skip-permissions",
        # These disable the generated result-gate hooks or the project Skills.
        "--bare",
        "--safe-mode",
        "--disable-slash-commands",
    }
    if any(
        token in forbidden or any(token.startswith(f"{name}=") for name in forbidden)
        for token in command
    ):
        raise ValueError("The Claude adapter may not bypass the factory permission or hook policy")
    configured_mode = _command_option(command, "--permission-mode")
    if configured_mode not in {None, CLAUDE_PERMISSION_MODE}:
        raise ValueError(
            f"OpenLabs Claude tasks require --permission-mode {CLAUDE_PERMISSION_MODE}"
        )
    if any(token in {"--settings", "--setting-sources"} or token.startswith(
        ("--settings=", "--setting-sources=")
    ) for token in command):
        raise ValueError("The Claude adapter may not override the factory settings")
    output_format = _command_option(command, "--output-format")
    if output_format not in {None, "stream-json"}:
        raise ValueError("OpenLabs Claude tasks require --output-format stream-json")
    if any(token in {"--input-format"} or token.startswith("--input-format=") for token in command):
        raise ValueError("OpenLabs Claude tasks read a plain-text request from stdin")
    if not settings_path.is_file():
        raise ValueError("Generated Claude settings with the result-gate hooks are missing")

    tail = _remove_value_options(
        command[1:], {"--permission-mode", "--output-format"}
    )
    tail = _remove_variadic_options(
        tail, {"--allowedTools", "--allowed-tools", "--add-dir"}
    )
    tail = _remove_flags(tail, {"-p", "--print", "--verbose"})
    policy = [
        "-p",
        # Variadic options are each followed by another option so they cannot
        # swallow a later argv token.
        "--add-dir",
        str(attempt_root),
        "--allowedTools",
        ",".join(claude_allowed_tools(allow_subagents=allow_subagents)),
        "--permission-mode",
        CLAUDE_PERMISSION_MODE,
        "--setting-sources",
        CLAUDE_SETTING_SOURCES,
        "--settings",
        str(settings_path),
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    return [command[0], *policy, *tail]


def _apply_claude_policy(
    command: list[str],
    *,
    task: Mapping[str, Any],
    runtime_policy: Mapping[str, Any],
    agent_workspace: Path,
) -> list[str]:
    """Bind a Claude argv to this attempt's generated settings and transaction root."""

    # The Claude analogue of Codex's trusted ``.codex/hooks.json``: the generated
    # settings file that carries the same SessionStart/Stop result-gate hooks.
    raw_settings = str(runtime_policy.get("claude_settings") or "").strip()
    settings_path = Path(raw_settings).expanduser()
    expected = (agent_workspace / ".claude" / "openlabs-settings.json").resolve()
    if (
        runtime_policy.get("schema_version") != "openlabs.codex_runtime.v1"
        or runtime_policy.get("hook_trust") != "orchestrator-generated"
        or not raw_settings
        or settings_path.resolve() != expected
    ):
        raise ValueError("Claude research tasks require the generated result-gate settings")
    transaction = task.get("transaction")
    attempt_root = (
        transaction.get("attempt_root") if isinstance(transaction, Mapping) else None
    )
    if not attempt_root:
        raise ValueError("Claude research tasks require an isolated attempt transaction")
    return _prepare_claude_command(
        command,
        settings_path=settings_path,
        attempt_root=Path(str(attempt_root)).expanduser().resolve(),
        allow_subagents=task_allows_subagents(task),
    )


def _claude_endpoint() -> dict[str, Any]:
    """Describe (never reveal) the Anthropic endpoint/credential the run inherits."""

    base_url = os.environ.get("ANTHROPIC_BASE_URL", "").strip()
    host = urllib.parse.urlsplit(base_url).hostname if base_url else None
    return {
        "mode": "custom_base_url" if base_url else "default_login",
        "host": host,
        "api_key_env": bool(
            os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        ),
    }


def _validate_codex_transaction(
    task: Mapping[str, Any],
    *,
    workspace: Path,
    agent_workspace: Path,
    agent_label: str = "Codex",
) -> None:
    """Validate the staged transaction layout before an unrestricted agent run."""

    transaction = task.get("transaction")
    if not isinstance(transaction, Mapping) or transaction.get("mode") != (
        "isolated_attempt_workspace"
    ):
        raise ValueError(f"{agent_label} research tasks require an isolated attempt transaction")
    attempt_root = Path(str(transaction.get("attempt_root") or "")).expanduser().resolve()
    staged = Path(str(transaction.get("staged_campaign_workspace") or "")).expanduser().resolve()
    canonical = (
        Path(str(transaction.get("canonical_campaign_workspace") or "")).expanduser().resolve()
    )
    expected_attempts = (workspace / "openlabs-artifacts" / "attempt-workspaces").resolve()
    expected_data = (workspace / "openlabs-data").resolve()
    if not attempt_root.is_relative_to(expected_attempts):
        raise ValueError("Codex attempt root is outside the artifact transaction store")
    if staged != agent_workspace or not staged.is_relative_to(attempt_root):
        raise ValueError("Codex writable root is not the declared private campaign")
    if not canonical.is_relative_to(expected_data):
        raise ValueError("Canonical campaign is outside the authoritative data store")
    if canonical == staged or canonical.is_relative_to(staged) or staged.is_relative_to(canonical):
        raise ValueError("Canonical and private campaign roots overlap")
    artifact_policy = transaction.get("artifact_policy")
    if isinstance(artifact_policy, Mapping):
        artifact_staging = (
            Path(str(transaction.get("artifact_staging_root") or "")).expanduser().resolve()
        )
        if artifact_staging != attempt_root / "artifact-stage":
            raise ValueError("Artifact staging is not the declared attempt-private payload root")
    temporary_roots = {
        Path(tempfile.gettempdir()).resolve(),
        Path("/tmp").resolve(),
        Path("/var/tmp").resolve(),
        Path("/dev/shm").resolve(),
    }
    for root in temporary_roots:
        if workspace == root or workspace.is_relative_to(root):
            raise ValueError("Codex factory workspace may not live under a system temporary root")
        if canonical == root or canonical.is_relative_to(root):
            raise ValueError("Canonical campaign may not live under a system temporary root")


def _seal_result_envelope(
    task: Mapping[str, Any],
    manifest: Mapping[str, Any],
    output: Path,
) -> tuple[bool, str | None]:
    """Bind transport identity while leaving every scientific field agent-owned."""

    try:
        raw = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"Agent result is not readable JSON: {exc}"
    if not isinstance(raw, dict):
        return False, "Agent result must be a JSON object"
    expected = {
        "schema_version": RESULT_SCHEMA,
        "task_id": task.get("task_id"),
        "campaign_id": task.get("campaign_id"),
        "lab_id": task.get("lab_id") or manifest.get("lab_id"),
        "domain": task.get("domain") or manifest.get("domain"),
    }
    repaired = False
    for key, value in expected.items():
        if value is None:
            continue
        current = raw.get(key)
        if current is None or current == "":
            raw[key] = value
            repaired = True
        elif current != value:
            return False, f"Agent result {key} conflicts with the task identity"
    if repaired:
        write_json(output, raw)
    return repaired, None


def _replace_rejected_result(
    task: dict[str, Any],
    manifest: dict[str, Any],
    output: Path,
    reason: str,
) -> None:
    rejected = output.parent / "agent-result-rejected.json"
    if output.exists():
        os.replace(output, rejected)
    write_json(
        output,
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": task["task_id"],
            "campaign_id": task["campaign_id"],
            "lab_id": task.get("lab_id") or manifest["lab_id"],
            "domain": task.get("domain") or manifest["domain"],
            "status": "failed",
            "summary": reason,
            "artifacts": [],
            "claims": [],
            "next_actions": ["Retry from the quarantined checkpoint with a valid result bundle."],
            "paper_candidate": False,
        },
    )


def _transaction_sandbox(
    command: list[str],
    task: Mapping[str, Any],
    workspace: Path,
) -> tuple[list[str], str | None]:
    """Apply the configured filesystem policy for a transactional research agent."""

    if Path(command[0]).name == "codex":
        return command, "codex-native-danger-full-access"
    transaction = task.get("transaction")
    if not isinstance(transaction, Mapping) or transaction.get("mode") != (
        "isolated_attempt_workspace"
    ):
        return command, None
    bubblewrap = shutil.which("bwrap")
    if bubblewrap is None:
        raise RuntimeError("bubblewrap is required for isolated attempt workspaces")
    attempt_root = Path(str(transaction["attempt_root"])).expanduser().resolve()
    if not attempt_root.is_dir() or not attempt_root.is_relative_to(workspace):
        raise ValueError("Transaction attempt_root is missing or outside OPENLABS_WORKSPACE")
    sandbox = [bubblewrap, "--die-with-parent", "--bind", "/", "/"]
    for relative in ("openlabs", "openlabs-data", "openlabs-artifacts", "openlabs-database"):
        root = (workspace / relative).resolve()
        if root.exists():
            sandbox.extend(["--ro-bind", str(root), str(root)])
    # A nested writable bind overrides the read-only artifact-store mount.
    sandbox.extend(["--bind", str(attempt_root), str(attempt_root), "--"])
    sandbox.extend(command)
    return sandbox, "bubblewrap"


def _run_agent(
    task: dict[str, Any],
    manifest: dict[str, Any],
    output: Path,
) -> dict[str, Any]:
    runner = str(task.get("runner") or "balanced")
    runner_key = "".join(character if character.isalnum() else "_" for character in runner).upper()
    agent = task["agent"]
    session_id = (
        str(agent.get("session_id") or "").strip()
        if agent["role"] != "reviewer" and agent["session_mode"] == "resume"
        else ""
    )
    command_kind = "RESUME_COMMAND" if session_id else "COMMAND"
    raw_command = os.environ.get(f"OPENLABS_AGENT_{command_kind}_{runner_key}_JSON", "").strip()
    raw_command = raw_command or os.environ.get(f"OPENLABS_AGENT_{command_kind}_JSON", "").strip()
    output.parent.mkdir(parents=True, exist_ok=True)
    request_path = output.parent / "agent-request.md"
    template = _command_template(raw_command) if raw_command else None
    adapter_name = Path(template[0]).name if template else None
    request = _agent_request(task, manifest, output, adapter=adapter_name)
    request_path.write_text(request, encoding="utf-8")
    if template is None:
        label = "resume command" if session_id else "command"
        _configuration_result(
            task,
            manifest,
            output,
            f"No approved Agent {label} is configured for the {runner!r} runner tier.",
        )
        return {"adapter": "unconfigured", "runner": runner}
    if session_id and "{session_id}" not in template:
        raise ValueError("Agent resume command must contain a {session_id} argv token")
    if (
        not session_id
        and agent["session_mode"] == "resume"
        and agent["role"] != "reviewer"
        and ("--ephemeral" in template or "--no-session-persistence" in template)
    ):
        _configuration_result(
            task,
            manifest,
            output,
            "The configured Agent command is ephemeral and cannot preserve this role's context.",
        )
        return {"adapter": "ephemeral", "runner": runner}
    configured_workspace = os.environ.get("OPENLABS_WORKSPACE", "").strip()
    workspace = (
        Path(configured_workspace).expanduser().resolve()
        if configured_workspace
        else Path(str(task["lab_manifest"])).resolve().parents[3]
    )
    if not (output == workspace or output.is_relative_to(workspace)):
        raise ValueError("Task output is outside OPENLABS_WORKSPACE")
    agent_workspace = Path(str(task["agent_workspace"])).expanduser().resolve()
    if not (agent_workspace == workspace or agent_workspace.is_relative_to(workspace)):
        raise ValueError("Agent workspace is outside OPENLABS_WORKSPACE")
    agent_workspace.mkdir(parents=True, exist_ok=True)
    replacements = {
        "{workspace}": str(workspace),
        "{agent_workspace}": str(agent_workspace),
        "{prompt_file}": str(request_path),
        "{output_file}": str(output),
        "{output_dir}": str(output.parent),
        "{skill_path}": str(task.get("skill_path") or ""),
        "{task_file}": str(task.get("_task_file") or ""),
        "{session_id}": session_id,
    }
    agent_command = [replacements.get(token, token) for token in template]
    if adapter_name in RUNTIME_ADAPTERS:
        _validate_codex_transaction(
            task,
            workspace=workspace,
            agent_workspace=agent_workspace,
            agent_label="Claude Code" if adapter_name == "claude" else "Codex",
        )
    runtime_policy = (
        task.get("runtime_policy") if isinstance(task.get("runtime_policy"), Mapping) else {}
    )
    hooks_path = Path(str(runtime_policy.get("hooks") or "")).expanduser()
    trust_generated_hooks = (
        runtime_policy.get("schema_version") == "openlabs.codex_runtime.v1"
        and runtime_policy.get("hook_trust") == "orchestrator-generated"
        and hooks_path.resolve() == (agent_workspace / ".codex" / "hooks.json").resolve()
        and hooks_path.is_file()
    )
    agent_command = _prepare_codex_command(
        agent_command,
        agent_workspace=agent_workspace,
        trust_generated_hooks=trust_generated_hooks,
    )
    if adapter_name == "claude":
        agent_command = _apply_claude_policy(
            agent_command,
            task=task,
            runtime_policy=runtime_policy,
            agent_workspace=agent_workspace,
        )
    preflight_error = _agent_connectivity_preflight(agent_command)
    if preflight_error is not None:
        _configuration_result(
            task,
            manifest,
            output,
            "Agent connectivity preflight failed closed: " + preflight_error,
        )
        return {
            "adapter": Path(agent_command[0]).name,
            "runner": runner,
            "failure_class": "agent_connectivity_preflight",
            "connectivity_preflight": {"passed": False, "error": preflight_error},
        }
    command, sandbox = _transaction_sandbox(agent_command, task, workspace)
    environment_timeout = max(
        1,
        int(os.environ.get("OPENLABS_AGENT_TIMEOUT_SECONDS", "43200")),
    )
    timeout = min(environment_timeout, int(task["budget"]["wall_seconds"]))
    stdout_path = output.parent / "agent-stdout.log"
    stderr_path = output.parent / "agent-stderr.log"
    with (
        stdout_path.open("w", encoding="utf-8") as stdout_handle,
        stderr_path.open("w", encoding="utf-8") as stderr_handle,
    ):
        process = subprocess.Popen(
            command,
            text=True,
            cwd=agent_workspace,
            stdin=subprocess.PIPE,
            stdout=stdout_handle,
            stderr=stderr_handle,
            start_new_session=True,
        )
        previous_handlers: dict[int, Any] = {}
        termination_signal: int | None = None

        def forward_termination(signum: int, _frame: Any) -> None:
            nonlocal termination_signal
            if termination_signal is None:
                termination_signal = signum
            _terminate_process_group(process)
            # Return to _run_agent so it can atomically persist a retryable bundle and
            # runtime metadata; raising here recreates an opaque exit-143 attempt.

        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, forward_termination)
        timed_out = False
        transport_failed = False
        transport_failure_count = 0
        try:
            try:
                assert process.stdin is not None
                process.stdin.write(request)
                process.stdin.close()
                process.stdin = None
            except BrokenPipeError:
                process.stdin = None
            deadline = time.monotonic() + timeout
            startup_grace = min(
                float(timeout),
                _positive_environment_number(
                    "OPENLABS_AGENT_STARTUP_GRACE_SECONDS",
                    120.0,
                ),
            )
            failure_threshold = max(
                1,
                int(
                    _positive_environment_number(
                        "OPENLABS_AGENT_TRANSPORT_FAILURE_THRESHOLD",
                        3.0,
                    )
                ),
            )
            process_started = time.monotonic()
            startup_monitoring = adapter_name in RUNTIME_ADAPTERS
            stream_started = True
            while process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    _terminate_process_group(process, grace_seconds=1)
                    break
                try:
                    process.wait(timeout=min(0.5, remaining))
                except subprocess.TimeoutExpired:
                    pass
                if startup_monitoring:
                    stdout_handle.flush()
                    if adapter_name == "claude":
                        transport_failure_count, meaningful_progress, stream_started = (
                            _claude_startup_health(stdout_path)
                        )
                    else:
                        transport_failure_count, meaningful_progress = _jsonl_startup_health(
                            stdout_path
                        )
                    startup_elapsed = time.monotonic() - process_started
                    if output.is_file() or meaningful_progress:
                        startup_monitoring = False
                    elif transport_failure_count >= failure_threshold or (
                        (transport_failure_count > 0 or not stream_started)
                        and startup_elapsed >= startup_grace
                    ):
                        transport_failed = True
                        _terminate_process_group(process, grace_seconds=1)
                        break
                    elif startup_elapsed >= startup_grace:
                        # Bound the startup scan itself. A later generic hang is
                        # still covered by the task wall timeout.
                        startup_monitoring = False
        finally:
            for signum, previous in previous_handlers.items():
                signal.signal(signum, previous)
    runtime = _jsonl_runtime(stdout_path)
    raw_hook_receipts = str(runtime_policy.get("hook_receipts") or "").strip()
    if raw_hook_receipts:
        runtime["hooks"] = _hook_runtime(
            Path(raw_hook_receipts),
            agent_workspace=agent_workspace,
        )
    runtime.update(
        {
            "adapter": Path(agent_command[0]).name,
            "adapter_version": _adapter_version(agent_command),
            "runner": runner,
            # Claude's ``-p`` is --print, not a profile.
            "profile": (
                _command_option(agent_command, "--profile", "-p")
                if Path(agent_command[0]).name == "codex"
                else None
            ),
            "configured_model": _command_option(agent_command, "--model", "-m"),
            "filesystem_sandbox": sandbox,
            "resumed_from": session_id or None,
            "timed_out": timed_out,
            "transport_watchdog_triggered": transport_failed,
            "startup_transport_failure_count": transport_failure_count,
            "startup_stream_silent": transport_failed and not stream_started,
            "agent_exit_code": process.returncode,
            "interrupted": termination_signal is not None,
            "termination_signal": termination_signal,
            "agent_request_path": str(request_path.resolve()),
            "agent_request_sha256": sha256_file(request_path),
        }
    )
    if adapter_name == "claude":
        runtime["claude_endpoint"] = _claude_endpoint()
        if session_id and not output.is_file() and "No conversation found with session ID" in (
            _read_tail(stdout_path) + _read_tail(stderr_path)
        ):
            # Claude stores transcripts per working directory; surface a failed
            # lookup instead of an anonymous process failure.
            runtime["resume_error"] = "session_not_found"
    if adapter_name in ADAPTER_PROVIDERS:
        runtime["provider_family"] = ADAPTER_PROVIDERS[adapter_name]
        snapshot = _agent_quota_snapshot(
            stdout_path,
            adapter=adapter_name,
            model=str(runtime.get("model") or runtime.get("configured_model") or "") or None,
        )
        if snapshot is not None:
            runtime["quota_snapshot"] = snapshot
    quota = (
        None
        if termination_signal is not None or output.is_file()
        else _agent_quota_failure(stdout_path, stderr_path)
    )
    if quota is not None:
        runtime["quota"] = {key: value for key, value in quota.items() if key != "quota_reset_at"}
        runtime["quota_reset_at"] = quota.get("quota_reset_at")
    if termination_signal is not None:
        runtime["failure_class"] = "agent_interrupted"
    elif transport_failed:
        runtime["failure_class"] = "agent_transport"
    elif timed_out:
        runtime["failure_class"] = "agent_timeout"
    elif process.returncode != 0:
        runtime["failure_class"] = "agent_process"
    if output.is_file():
        repaired, envelope_error = _seal_result_envelope(task, manifest, output)
        runtime["result_envelope_repaired"] = repaired
        runtime["result_envelope_error"] = envelope_error
        if envelope_error:
            runtime["failure_class"] = "result_contract"
            _replace_rejected_result(task, manifest, output, envelope_error)
        return runtime
    runtime["failure_class"] = "agent_quota" if quota is not None else "agent_transport"
    if quota is not None:
        reset_note = (
            f" Provider reset time: {quota['quota_reset_at']}."
            if quota.get("quota_reset_at")
            else ""
        )
        summary = (
            f"Agent provider quota or rate limit ({quota['kind']}) stopped the run before a "
            f"result bundle was written.{reset_note}"
        )
        # Keep the status the timeout/exit-code branches below would produce, so the
        # orchestrator's ordinary handling applies once quota retries are exhausted.
        # (The transport watchdog's needs_human is deliberately not reproduced.)
        status = "needs_replan" if timed_out or process.returncode == 0 else "failed"
        next_action = (
            "Wait for the provider quota to reset; the orchestrator requeues this "
            "unchanged task automatically."
        )
    elif termination_signal is not None:
        summary = (
            f"Agent was interrupted by signal {termination_signal} before writing a result bundle."
        )
        status = "failed"
        next_action = "Resume this task from its persisted checkpoint and bounded agent session."
    elif transport_failed:
        summary = (
            "Agent transport remained unavailable without meaningful progress; "
            "the bounded startup watchdog stopped the process."
        )
        status = "needs_human"
        next_action = "Repair Agent network/proxy connectivity, then explicitly retry the task."
    elif timed_out:
        summary = f"Agent exceeded its bounded {timeout} second timeout."
        status = "needs_replan"
        next_action = "Inspect the bounded agent logs and replan the task within its budget."
    else:
        summary = f"Agent exited with code {process.returncode} without a result bundle."
        status = "needs_replan" if process.returncode == 0 else "failed"
        next_action = "Inspect the bounded agent logs and repair the runner or task prompt."
    write_json(
        output,
        {
            "schema_version": RESULT_SCHEMA,
            "task_id": task["task_id"],
            "campaign_id": task["campaign_id"],
            "lab_id": manifest["lab_id"],
            "domain": manifest["domain"],
            "status": status,
            "summary": summary,
            "artifacts": [],
            "claims": [],
            "next_actions": [next_action],
            "paper_candidate": False,
        },
    )
    return runtime


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    task_path = Path(args.task).resolve()
    task = json.loads(task_path.read_text(encoding="utf-8"))
    task["_task_file"] = str(task_path)
    if task.get("schema_version") != TASK_SCHEMA:
        raise ValueError(f"Unsupported task schema: {task.get('schema_version')}")
    manifest_path = Path(str(task["lab_manifest"])).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if task.get("lab_id") != manifest.get("lab_id"):
        raise ValueError("Task and manifest lab_id differ")
    if task.get("domain") != manifest.get("domain"):
        raise ValueError("Task and manifest domain differ")
    output = Path(args.output).resolve()
    started = time.monotonic()
    configured_workspace = os.environ.get("OPENLABS_WORKSPACE", "").strip()
    workspace = (
        Path(configured_workspace).expanduser().resolve()
        if configured_workspace
        else manifest_path.parents[3]
    )
    agent_workspace = Path(str(task["agent_workspace"])).expanduser().resolve()
    try:
        task_type = task.get("task_type")
        adapter = _configured_agent_adapter(task)
        if task_type == "smoke":
            lab_runtime = {
                "schema_version": LAB_RUNTIME_SCHEMA,
                "setups": [],
                "skipped": "deterministic smoke task",
            }
            _smoke(task, manifest, output)
            runtime: dict[str, Any] = {"adapter": "deterministic", "runner": "none"}
        elif adapter not in RUNTIME_ADAPTERS:
            # Other commands are retained solely for deterministic transport tests. Production
            # research uses a native agent adapter (Codex or Claude Code) and receives every
            # trusted lab runtime.
            lab_runtime = {
                "schema_version": LAB_RUNTIME_SCHEMA,
                "setups": [],
                "skipped": "non-Codex adapter",
            }
            task["lab_runtime"] = lab_runtime
            runtime = _run_agent(task, manifest, output)
        else:
            lab_runtime = _lab_runtime_setup(
                task,
                manifest,
                workspace=workspace,
                agent_workspace=agent_workspace,
            )
            task["lab_runtime"] = lab_runtime
            runtime = _run_agent(task, manifest, output)
        runtime["lab_runtime"] = lab_runtime
    except (OSError, RuntimeError, subprocess.TimeoutExpired, TypeError, ValueError) as exc:
        _configuration_result(
            task,
            manifest,
            output,
            f"Laboratory runtime setup failed closed: {exc}",
        )
        runtime = {
            "adapter": "runtime_setup_failed",
            "runner": "none",
            "failure_class": "lab_runtime_setup",
            "error": str(exc),
        }
    runtime["lab_runner_seconds"] = max(0.0, time.monotonic() - started)
    metadata_path = Path(str(task["run_metadata_path"])).resolve()
    if metadata_path.parent != output.parent:
        raise ValueError("Run metadata must be adjacent to the result")
    write_json(
        metadata_path,
        {
            "task_id": task["task_id"],
            "attempt_id": task["attempt_id"],
            "runtime": runtime,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
