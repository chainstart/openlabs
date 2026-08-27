"""Fail-closed Agent connectivity preflight and proxy synchronization."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, MutableMapping
from pathlib import Path
from typing import Any

from .config import _environment_file_value


PROXY_NAMES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)
_URL_PROXY_NAMES = PROXY_NAMES[:3] + PROXY_NAMES[4:7]
_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
_DEFAULT_TARGET = "https://chatgpt.com/backend-api/codex"


class ProxyPreflightError(RuntimeError):
    """Raised when no configured Agent transport is reachable."""


def _flag(environment: Mapping[str, str], name: str, default: bool = True) -> bool:
    raw = environment.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _timeout(environment: Mapping[str, str]) -> float:
    try:
        value = float(environment.get("OPENLABS_AGENT_PREFLIGHT_TIMEOUT_SECONDS", "10"))
    except ValueError:
        return 10.0
    return value if value > 0 else 10.0


def _config_home(environment: Mapping[str, str], explicit: str | Path | None) -> Path:
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    configured = environment.get("XDG_CONFIG_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(environment.get("HOME") or Path.home()).expanduser().resolve() / ".config"


def proxy_environment_file(
    environment: Mapping[str, str],
    *,
    config_home: str | Path | None = None,
) -> Path:
    override = environment.get("OPENLABS_PROXY_ENV_FILE", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _config_home(environment, config_home) / "environment.d" / "90-openlabs-proxy.conf"


def _read_environment_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ProxyPreflightError(f"{path}:{line_number}: expected NAME=VALUE")
        name, raw_value = line.split("=", 1)
        name = name.strip()
        if name in PROXY_NAMES:
            values[name] = _environment_file_value(raw_value)
    return values


def _first(environment: Mapping[str, str], *names: str) -> str:
    for name in names:
        value = str(environment.get(name) or "").strip()
        if value:
            return value
    return ""


def _normalized_proxy_environment(environment: Mapping[str, str]) -> dict[str, str]:
    https = _first(environment, "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy")
    http = _first(environment, "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")
    all_proxy = _first(environment, "ALL_PROXY", "all_proxy")
    if not https and not http and not all_proxy:
        return {}
    https = https or all_proxy or http
    http = http or all_proxy or https
    all_proxy = all_proxy or https or http
    no_proxy = _first(environment, "NO_PROXY", "no_proxy")
    normalized = {
        "HTTP_PROXY": http,
        "HTTPS_PROXY": https,
        "ALL_PROXY": all_proxy,
        "http_proxy": http,
        "https_proxy": https,
        "all_proxy": all_proxy,
    }
    if no_proxy:
        normalized["NO_PROXY"] = no_proxy
        normalized["no_proxy"] = no_proxy
    return normalized


def _proxy_for_target(proxies: Mapping[str, str], target: str) -> str | None:
    scheme = urllib.parse.urlsplit(target).scheme.lower()
    if scheme == "https":
        return proxies.get("HTTPS_PROXY") or proxies.get("ALL_PROXY")
    return proxies.get("HTTP_PROXY") or proxies.get("ALL_PROXY")


def _origin(raw_url: str) -> str:
    parsed = urllib.parse.urlsplit(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ProxyPreflightError("Agent preflight URL must be a valid HTTP(S) endpoint")
    origin = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port is not None:
        origin += f":{parsed.port}"
    return origin


def _command_base_url(raw_command: str) -> str | None:
    try:
        command = json.loads(raw_command)
    except json.JSONDecodeError:
        return None
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        return None
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


def agent_preflight_target(environment: Mapping[str, str]) -> str:
    override = environment.get("OPENLABS_AGENT_PREFLIGHT_URL", "").strip()
    if override:
        _origin(override)
        return override
    for name in (
        "OPENLABS_AGENT_COMMAND_JSON",
        "OPENLABS_AGENT_COMMAND_FRONTIER_JSON",
        "OPENLABS_AGENT_COMMAND_BALANCED_JSON",
        "OPENLABS_AGENT_COMMAND_CHEAP_JSON",
    ):
        raw_command = environment.get(name, "").strip()
        if not raw_command:
            continue
        target = _command_base_url(raw_command)
        if target:
            _origin(target)
            return target
    return _DEFAULT_TARGET


def _probe(target: str, proxies: Mapping[str, str], timeout: float) -> None:
    handler_proxies: dict[str, str] = {}
    if proxies:
        handler_proxies = {
            "http": proxies["HTTP_PROXY"],
            "https": proxies["HTTPS_PROXY"],
        }
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(handler_proxies))
    request = urllib.request.Request(
        target,
        method="HEAD",
        headers={"User-Agent": "openlabs-proxy-preflight/1"},
    )
    try:
        with opener.open(request, timeout=timeout):
            return
    except urllib.error.HTTPError:
        # Authentication, policy, and method errors still prove proxy/DNS/TLS reachability.
        return


def _proxy_label(proxies: Mapping[str, str], target: str) -> str:
    raw_proxy = _proxy_for_target(proxies, target)
    if raw_proxy is None:
        return "direct"
    parsed = urllib.parse.urlsplit(raw_proxy)
    if not parsed.hostname:
        return "invalid-proxy"
    label = parsed.hostname
    if parsed.port is not None:
        label += f":{parsed.port}"
    return label


def _quoted_environment_value(value: str) -> str:
    if "\n" in value or "\r" in value or "\0" in value:
        raise ProxyPreflightError("Proxy environment values cannot contain control characters")
    return json.dumps(value, ensure_ascii=False)


def _write_proxy_environment(path: Path, values: Mapping[str, str]) -> bool:
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    remaining = dict(values)
    output: list[str] = []
    for line in existing.splitlines():
        match = _ASSIGNMENT.match(line)
        name = match.group(1) if match else ""
        if name in remaining:
            output.append(f"{name}={_quoted_environment_value(remaining.pop(name))}")
        else:
            output.append(line)
    if output and remaining:
        output.append("")
    for name in PROXY_NAMES:
        if name in remaining:
            output.append(f"{name}={_quoted_environment_value(remaining.pop(name))}")
    rendered = "\n".join(output).rstrip() + "\n"
    if rendered == existing:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return True


def _import_systemd_environment(environment: Mapping[str, str]) -> None:
    completed = subprocess.run(
        ["systemctl", "--user", "import-environment", *PROXY_NAMES],
        env=dict(environment),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        raise ProxyPreflightError(
            f"could not synchronize the systemd user environment (exit {completed.returncode})"
        )


def ensure_proxy_ready(
    *,
    environment: MutableMapping[str, str] | None = None,
    inherited_environment: Mapping[str, str] | None = None,
    config_home: str | Path | None = None,
    probe: Callable[[str, Mapping[str, str], float], None] | None = None,
    sync_systemd: bool | None = None,
) -> dict[str, Any]:
    """Select a reachable proxy, synchronize it, or fail before research starts."""

    target_environment = environment if environment is not None else os.environ
    inherited = inherited_environment if inherited_environment is not None else target_environment
    target = agent_preflight_target(target_environment)
    origin = _origin(target)
    timeout = _timeout(target_environment)
    config_path = proxy_environment_file(target_environment, config_home=config_home)
    configured = _read_environment_file(config_path)
    candidates: list[tuple[str, dict[str, str]]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for source, raw_candidate in (("process", inherited), ("configured", configured)):
        candidate = _normalized_proxy_environment(raw_candidate)
        if not candidate:
            continue
        identity = tuple(sorted(candidate.items()))
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append((source, candidate))

    selected_source = "direct"
    selected: dict[str, str] = {}
    errors: list[str] = []
    checker = probe or _probe
    if candidates:
        for source, candidate in candidates:
            try:
                checker(target, candidate, timeout)
            except (OSError, TimeoutError, urllib.error.URLError) as exc:
                errors.append(
                    f"{source} proxy {_proxy_label(candidate, target)}: {type(exc).__name__}"
                )
                continue
            selected_source = source
            selected = candidate
            break
        else:
            detail = "; ".join(errors) or "no usable proxy candidate"
            raise ProxyPreflightError(f"Agent provider {origin} is unreachable ({detail})")
    else:
        try:
            checker(target, {}, timeout)
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            raise ProxyPreflightError(
                f"Agent provider {origin} is unreachable without a proxy ({type(exc).__name__})"
            ) from exc

    file_changed = False
    systemd_synced = False
    if selected:
        target_environment.update(selected)
        if _flag(target_environment, "OPENLABS_PROXY_AUTO_SYNC", True):
            file_changed = _write_proxy_environment(config_path, selected)
        should_sync = (
            _flag(target_environment, "OPENLABS_PROXY_SYNC_SYSTEMD", True)
            if sync_systemd is None
            else sync_systemd
        )
        if should_sync:
            _import_systemd_environment(target_environment)
            systemd_synced = True

    return {
        "schema_version": "openlabs.proxy_preflight.v1",
        "status": "passed",
        "target": origin,
        "route": _proxy_label(selected, target),
        "source": selected_source,
        "proxy_file": str(config_path),
        "proxy_file_changed": file_changed,
        "systemd_environment_synced": systemd_synced,
    }
