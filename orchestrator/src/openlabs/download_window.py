"""Off-peak window for large downloads through the proxy node (user rule 2026-11-18).

User (2026-11-18): "通过代理节点下载较大的数据时候，在闲时进行，是2：00-14：00这个时段，这个
规则既落到整个容器里，也特别加到产线上". Larger data downloaded through the proxy node
(download bridge ``--route proxy``, or a batch known to fall back to the proxy for
all of it) runs only inside the window, 02:00-14:00 Asia/Shanghai by default.
"Larger": a single file of at least ``large_file_mib`` or a batch of at least
``large_batch_mib`` together. ``--route auto`` tries the direct route first and
is not limited by the window.

Configured in ``[factory]`` (``proxy_download_window``, ``proxy_download_timezone``,
``proxy_download_large_file_mib``, ``proxy_download_large_batch_mib``,
``proxy_download_codex_hook``). The production sessions get a PreToolUse hook
(``python -m openlabs.download_window pre-tool-use``) that refuses a
``download-submit ... --route proxy`` command outside the window unless the
command declares itself small with ``PROXY_SMALL_OK=1``; scripts that call the
bridge themselves use ``in_window``/``window_status`` (or the CLI ``status``).
This module imports nothing heavy: it runs before every shell command.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_WINDOW = ("02:00", "14:00")
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_LARGE_FILE_MIB = 200
DEFAULT_LARGE_BATCH_MIB = 1024
SMALL_MARKER = "PROXY_SMALL_OK=1"
_CLOCK = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")
_PROXY_ROUTE = re.compile(r"--route(?:=|\s+)['\"]?proxy\b")


@dataclass(frozen=True)
class ProxyDownloadWindow:
    start: str = DEFAULT_WINDOW[0]
    end: str = DEFAULT_WINDOW[1]
    timezone: str = DEFAULT_TIMEZONE
    large_file_mib: int = DEFAULT_LARGE_FILE_MIB
    large_batch_mib: int = DEFAULT_LARGE_BATCH_MIB
    # Codex sessions get the PreToolUse hook only when this is on: Codex's
    # PreToolUse support has not been checked in a live production session yet,
    # and a hooks.json Codex rejects would also lose the result-gate Stop hook.
    codex_hook: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "window": [self.start, self.end], "timezone": self.timezone,
            "large_file_mib": self.large_file_mib, "large_batch_mib": self.large_batch_mib,
            "codex_hook": self.codex_hook,
        }


def _minutes(value: str) -> int:
    match = _CLOCK.fullmatch(str(value).strip())
    if match is None:
        raise ValueError(f"proxy_download_window time {value!r} must be HH:MM (00:00-23:59)")
    return int(match.group(1)) * 60 + int(match.group(2))


def parse_window(
    window: Any = None,
    timezone: Any = None,
    *,
    large_file_mib: Any = None,
    large_batch_mib: Any = None,
    codex_hook: Any = None,
) -> ProxyDownloadWindow:
    """Validated settings; ``window`` is ``["HH:MM", "HH:MM"]`` (start inclusive, end exclusive)."""

    raw = DEFAULT_WINDOW if window is None else window
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise ValueError('proxy_download_window must be ["HH:MM", "HH:MM"]')
    start, end = (str(item).strip() for item in raw)
    if _minutes(start) == _minutes(end):
        raise ValueError("proxy_download_window start and end must differ")
    zone = str(timezone or DEFAULT_TIMEZONE)
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"proxy_download_timezone {zone!r} is not a known time zone") from exc

    def positive(value: Any, default: int, name: str) -> int:
        if value is None:
            return default
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a positive integer (MiB)") from exc
        if number <= 0:
            raise ValueError(f"{name} must be a positive integer (MiB)")
        return number

    return ProxyDownloadWindow(
        start=start, end=end, timezone=zone,
        large_file_mib=positive(large_file_mib, DEFAULT_LARGE_FILE_MIB,
                                "proxy_download_large_file_mib"),
        large_batch_mib=positive(large_batch_mib, DEFAULT_LARGE_BATCH_MIB,
                                 "proxy_download_large_batch_mib"),
        codex_hook=bool(codex_hook) if codex_hook is not None else False,
    )


def load_window(factory: Mapping[str, Any] | None) -> ProxyDownloadWindow:
    """``[factory]`` keys -> settings (defaults when absent)."""

    table = factory or {}
    return parse_window(
        table.get("proxy_download_window"),
        table.get("proxy_download_timezone"),
        large_file_mib=table.get("proxy_download_large_file_mib"),
        large_batch_mib=table.get("proxy_download_large_batch_mib"),
        codex_hook=table.get("proxy_download_codex_hook"),
    )


def _local(now: datetime | None, policy: ProxyDownloadWindow) -> datetime:
    zone = ZoneInfo(policy.timezone)
    if now is None:
        return datetime.now(zone)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(zone)


def in_window(now: datetime | None = None,
              policy: ProxyDownloadWindow | None = None) -> bool:
    """Whether ``now`` is inside the off-peak window (a window may wrap midnight)."""

    rule = policy or ProxyDownloadWindow()
    local = _local(now, rule)
    minute = local.hour * 60 + local.minute
    start, end = _minutes(rule.start), _minutes(rule.end)
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end


def next_window_start(now: datetime | None = None,
                      policy: ProxyDownloadWindow | None = None) -> datetime:
    """The next moment the window opens (``now`` itself when it is inside)."""

    rule = policy or ProxyDownloadWindow()
    local = _local(now, rule)
    if in_window(local, rule):
        return local
    start = _minutes(rule.start)
    candidate = local.replace(hour=start // 60, minute=start % 60, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate


def is_large(*, file_bytes: int | None = None, batch_bytes: int | None = None,
             policy: ProxyDownloadWindow | None = None) -> bool:
    rule = policy or ProxyDownloadWindow()
    mib = 1024 * 1024
    return bool(
        (file_bytes is not None and file_bytes >= rule.large_file_mib * mib)
        or (batch_bytes is not None and batch_bytes >= rule.large_batch_mib * mib)
    )


def window_status(now: datetime | None = None,
                  policy: ProxyDownloadWindow | None = None) -> dict[str, Any]:
    rule = policy or ProxyDownloadWindow()
    local = _local(now, rule)
    return {
        "in_window": in_window(local, rule),
        "now": local.isoformat(timespec="minutes"),
        "next_window_start": next_window_start(local, rule).isoformat(timespec="minutes"),
        **rule.to_dict(),
    }


def rule_text(policy: ProxyDownloadWindow | None = None) -> str:
    """One-sentence rule for briefs and skills."""

    rule = policy or ProxyDownloadWindow()
    return (
        f"Large downloads through the proxy route (`--route proxy`, or a batch you know falls "
        f"back to the proxy; a file >= {rule.large_file_mib} MB or a batch >= "
        f"{rule.large_batch_mib} MB) run only {rule.start}-{rule.end} {rule.timezone}: "
        "outside it, schedule them for the window start and keep working on what does not need "
        f"the data; never split a download to dodge the window; prefix a genuinely small proxy "
        f"download with `{SMALL_MARKER}`; `--route auto` is not limited."
    )


def command_refusal(command: str, now: datetime | None = None,
                    policy: ProxyDownloadWindow | None = None) -> str | None:
    """Why a shell command must not run now, or None.

    Refused: a ``download-submit`` call with ``--route proxy`` outside the window
    that does not carry the ``PROXY_SMALL_OK=1`` marker. Status, cancel and
    ``--route auto/direct`` calls pass.
    """

    text = str(command or "")
    if "download-submit" not in text or not _PROXY_ROUTE.search(text):
        return None
    if re.search(r"\b" + re.escape(SMALL_MARKER) + r"\b", text):
        return None
    rule = policy or ProxyDownloadWindow()
    local = _local(now, rule)
    if in_window(local, rule):
        return None
    return (
        "OpenLabs rule (user 2026-11-18): large downloads through the proxy route run only "
        f"{rule.start}-{rule.end} {rule.timezone}; it is now {local:%H:%M}. Schedule the "
        f"submission for {next_window_start(local, rule):%Y-%m-%d %H:%M} (or end the seat and "
        "say so), keep working on what does not need the data, and use `--route auto` where "
        f"the direct route is acceptable. If every file is under {rule.large_file_mib} MB and "
        f"the batch under {rule.large_batch_mib} MB, prefix the command with `{SMALL_MARKER} `. "
        "Do not split a large download to get around the window."
    )


def _event_command(event: Mapping[str, Any]) -> str:
    tool_call = event.get("toolCall")
    if isinstance(tool_call, Mapping):
        # Antigravity CLI (agy): ``{"toolCall": {"name": "run_command", "args":
        # {"CommandLine": ...}}}`` in camelCase.
        args = tool_call.get("args")
        if isinstance(args, Mapping):
            value = args.get("CommandLine", args.get("command"))
            return str(value) if value is not None else json.dumps(args, ensure_ascii=False)
        return ""
    tool_input = event.get("tool_input")
    if isinstance(tool_input, Mapping):
        value = tool_input.get("command", tool_input.get("cmd"))
        if isinstance(value, list):
            return " ".join(str(item) for item in value)
        if value is not None:
            return str(value)
        return json.dumps(tool_input, ensure_ascii=False)
    return str(tool_input or "")


def pre_tool_use(event: Mapping[str, Any], policy: ProxyDownloadWindow, *, adapter: str,
                 now: datetime | None = None) -> tuple[int, str, str]:
    """``(exit code, stdout, stderr)`` of the PreToolUse hook for one event."""

    reason = command_refusal(_event_command(event), now, policy)
    if adapter == "agy":
        # Antigravity reads a decision object on stdout for every PreToolUse hook.
        decision = {"decision": "allow"} if reason is None else {
            "decision": "deny", "reason": reason}
        return 0, json.dumps(decision, ensure_ascii=False), ""
    if reason is None:
        return 0, "", ""
    if adapter == "claude":
        return 0, json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }}), ""
    # Codex: a blocking exit status with the reason on stderr.
    return 2, "", reason


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m openlabs.download_window")
    sub = parser.add_subparsers(dest="command", required=True)
    hook = sub.add_parser("pre-tool-use")
    hook.add_argument("--adapter", choices=("codex", "claude", "agy"), default="codex")
    hook.add_argument("--policy", required=True, help="JSON of ProxyDownloadWindow.to_dict()")
    status = sub.add_parser("status")
    status.add_argument("--policy", default=None)
    args = parser.parse_args(argv)
    try:
        raw = json.loads(args.policy) if args.policy else {}
        policy = parse_window(raw.get("window"), raw.get("timezone"),
                              large_file_mib=raw.get("large_file_mib"),
                              large_batch_mib=raw.get("large_batch_mib"))
    except (ValueError, AttributeError) as exc:
        print(f"invalid proxy download window policy: {exc}", file=sys.stderr)
        # A broken policy must not stop every shell command of a session.
        return 0
    if args.command == "status":
        payload = window_status(policy=policy)
        print(json.dumps(payload, ensure_ascii=False))
        return 0 if payload["in_window"] else 3
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    code, out, err = pre_tool_use(event if isinstance(event, Mapping) else {}, policy,
                                  adapter=args.adapter)
    if out:
        print(out)
    if err:
        print(err, file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
