"""Quota/rate-limit classification in packages/research-core/lab_runner.py.

Positive texts are copied from real local samples (see AGENT_QUOTA_MARKERS
provenance); negatives are real agent/tool outputs that mention quotas or rate
limits without being a provider quota stop.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

CODE_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "openlabs_test_lab_runner", CODE_ROOT / "packages" / "research-core" / "lab_runner.py"
)
assert _SPEC is not None and _SPEC.loader is not None
lab_runner = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(lab_runner)

NOW = datetime(2026, 11, 9, 14, 55, 50, tzinfo=UTC)

# ~/.claude/projects/-workspace/327421f5-....jsonl (Claude Code subagent transcript).
CLAUDE_TRANSCRIPT_EVENT = json.dumps(
    {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "text",
                    "text": "You've hit your 5-hour limit · resets 12:40am (Asia/Singapore)",
                }
            ]
        },
        "requestId": "req_011CgsYk14p49sxatdeFCmpv",
        "apiError": "usage_limit_reached",
        "apiErrorParams": {
            "rate_limit_info": {
                "status": "rejected",
                "resetsAt": 1794242400,
                "rateLimitType": "five_hour",
            }
        },
    },
    ensure_ascii=False,
)
# Same session, task-notification summary (plain text, as a CLI prints it).
CLAUDE_NOTIFICATION = (
    "Agent terminated early due to an API error: You've hit your 5-hour limit · resets "
    "12:40am (Asia/Singapore) (error type rate_limit, HTTP 429, request id "
    "req_011CgsYk14p49sxatdeFCmpv, model sent to the API: claude-fable-5-1)"
)
# maintenance/20261028-physics-sixhour/de.g3.events.jsonl (codex exec --json).
CODEX_CAPACITY = (
    '{"type":"error","message":"Selected model is at capacity. Please try a different model."}\n'
    '{"type":"turn.failed","error":{"message":"Selected model is at capacity. '
    'Please try a different model."}}'
)
# Message template embedded in codex-cli 0.166.0 (no local run log hit this one).
CODEX_USAGE_LIMIT = (
    '{"type":"turn.failed","error":{"message":"You’ve hit your usage limit. Upgrade to '
    "Pro (https://chatgpt.com/explore/pro), visit https://chatgpt.com/settings/usage to "
    'purchase more credits or try again at 3:05 PM."}}'
)

# maintenance/20261028-physics-sixhour/nu.events.jsonl: the agent's own urllib call.
NEGATIVE_TOOL_OUTPUT = json.dumps(
    {
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "aggregated_output": (
                'File "/usr/lib/python3.12/urllib/request.py", line 639, in '
                "http_error_default\n    raise HTTPError(req.full_url, code, msg, hdrs, fp)\n"
                "urllib.error.HTTPError: HTTP Error 429: Too Many Requests\n"
            ),
            "exit_code": 1,
            "status": "failed",
        },
    }
)
NEGATIVE_PROSE = [
    # openlabs-database/exports/current/research-records.json
    "OpenAlex exhausted its anonymous budget and one Semantic Scholar endpoint was rate-limited.",
    "This is not a global novelty certificate; one arXiv query was rate-limited.",
    # openlabs-artifacts/.../stderr.log (systemd resource wrapper)
    'systemctl --user set-property --runtime "$SLICE" CPUAccounting=yes CPUQuota="$cpu_quota"',
    "Do not require a downloaded article, original PDF, OCR, or proof-text quotation",
    # maintenance/20261108-realdata-six-hour/health/units/h17-schema-only-v1.log
    '"x-usage-tokens": "65", "x-ratelimit-limit": "20, 20;w=60", "x-ratelimit-remaining": "19"',
    "If you get HTTP 429 (rate limit), wait briefly and retry once.",
    "The GPU quota is a backstop; the user's disk quota is not exceeded.",
]


@pytest.mark.parametrize(
    ("stdout", "stderr", "kind"),
    [
        (CLAUDE_TRANSCRIPT_EVENT, "", "usage_limit"),
        ("", CLAUDE_NOTIFICATION, "usage_limit"),
        (CODEX_CAPACITY, "", "capacity"),
        (CODEX_USAGE_LIMIT, "", "usage_limit"),
    ],
)
def test_real_quota_samples_are_classified(stdout: str, stderr: str, kind: str) -> None:
    match = lab_runner.classify_agent_quota(stdout_text=stdout, stderr_text=stderr, now=NOW)
    assert match is not None
    assert match["kind"] == kind
    assert match["excerpt"]


def test_reset_time_is_parsed_from_real_samples() -> None:
    expected = "2026-11-09T16:40:00Z"  # 12:40am Asia/Singapore == resetsAt 1794242400
    transcript = lab_runner.classify_agent_quota(stdout_text=CLAUDE_TRANSCRIPT_EVENT, now=NOW)
    notification = lab_runner.classify_agent_quota(stderr_text=CLAUDE_NOTIFICATION, now=NOW)
    assert transcript is not None and transcript["quota_reset_at"] == expected
    assert notification is not None and notification["quota_reset_at"] == expected
    codex = lab_runner.classify_agent_quota(
        stdout_text=CODEX_USAGE_LIMIT, now=NOW, local_zone=UTC
    )
    assert codex is not None and codex["quota_reset_at"] == "2026-11-09T15:05:00Z"
    capacity = lab_runner.classify_agent_quota(stdout_text=CODEX_CAPACITY, now=NOW)
    assert capacity is not None and capacity["quota_reset_at"] is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("try again at 1:00 PM", "2026-11-10T13:00:00Z"),  # already past today -> tomorrow
        ("try again at Nov 12th, 2026 3:05 PM.", "2026-11-12T15:05:00Z"),
        ("Rate limited; try again in 2 hours 5 minutes", "2026-11-09T17:00:50Z"),
        ("limit resets in 45m", "2026-11-09T15:40:50Z"),
        ("resets 5-hour", None),
        ("no time here", None),
    ],
)
def test_parse_quota_reset_formats(text: str, expected: str | None) -> None:
    assert lab_runner.parse_quota_reset(text, now=NOW, local_zone=UTC) == expected


def test_quota_words_in_tool_output_and_prose_are_not_quota_failures() -> None:
    assert lab_runner.classify_agent_quota(stdout_text=NEGATIVE_TOOL_OUTPUT, now=NOW) is None
    for text in NEGATIVE_PROSE:
        assert lab_runner.classify_agent_quota(stdout_text=text, stderr_text=text) is None
    # Ordinary transport failures stay agent_transport.
    transport = (
        '{"type":"error","message":"Reconnecting... 2/5 (stream disconnected before '
        'completion: tls handshake eof)"}'
    )
    assert lab_runner.classify_agent_quota(stdout_text=transport) is None
    unauthorized = (
        '{"type":"turn.failed","error":{"message":"unexpected status 401 Unauthorized: '
        'Missing bearer or basic authentication in header"}}'
    )
    assert lab_runner.classify_agent_quota(stdout_text=unauthorized) is None


def test_markers_live_in_one_table() -> None:
    kinds = {kind for kind, _pattern, _provenance in lab_runner.AGENT_QUOTA_MARKERS}
    provenance = {item for _kind, _pattern, item in lab_runner.AGENT_QUOTA_MARKERS}
    assert kinds == {"usage_limit", "rate_limit", "capacity"}
    assert provenance <= {"sample", "cli-string", "unverified"}


def _agent_task(tmp_path: Path, output: Path) -> dict:
    manifest = tmp_path / "openlabs" / "labs" / "math" / "lab.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"lab_id": "math", "domain": "math"}), encoding="utf-8")
    return {
        "task_id": "task-q",
        "attempt_id": "attempt-q",
        "campaign_id": "campaign-q",
        "lab_manifest": str(manifest),
        "runner": "balanced",
        "objective": "Run one fake agent step.",
        "resources": {"cpu_threads": 1},
        "budget": {"wall_seconds": 30},
        "agent": {"role": "researcher", "session_mode": "fresh"},
        "agent_workspace": str(tmp_path / "agent"),
        "run_metadata_path": str(output.parent / "run-metadata.json"),
    }


@pytest.mark.parametrize(
    ("emitted", "exit_code", "failure_class", "status"),
    [
        (CODEX_USAGE_LIMIT, 1, "agent_quota", "failed"),
        (CLAUDE_TRANSCRIPT_EVENT, 0, "agent_quota", "needs_replan"),
        (NEGATIVE_TOOL_OUTPUT, 1, "agent_transport", "failed"),
    ],
)
def test_run_agent_marks_quota_stop_without_bundle(
    tmp_path, monkeypatch, emitted: str, exit_code: int, failure_class: str, status: str
) -> None:
    output = tmp_path / "out" / "result.json"
    task = _agent_task(tmp_path, output)
    lines = tmp_path / "emitted.txt"
    lines.write_text(emitted, encoding="utf-8")
    code = (
        "import sys; from pathlib import Path; "
        f"print(Path({str(lines)!r}).read_text()); sys.exit({exit_code})"
    )
    monkeypatch.setenv("OPENLABS_WORKSPACE", str(tmp_path))
    monkeypatch.setenv(
        "OPENLABS_AGENT_COMMAND_BALANCED_JSON", json.dumps([sys.executable, "-c", code])
    )
    runtime = lab_runner._run_agent(task, {"lab_id": "math", "domain": "math"}, output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert runtime["failure_class"] == failure_class
    assert payload["status"] == status
    assert payload["artifacts"] == [] and payload["claims"] == []
    if failure_class == "agent_quota":
        assert runtime["quota"]["kind"] == "usage_limit"
        assert "quota_reset_at" in runtime
    else:
        assert "quota" not in runtime
