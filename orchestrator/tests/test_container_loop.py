"""bin/openlabs-container-loop: start/stop/status, one loop per instance, graceful stop."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

LOOP = Path(__file__).resolve().parents[2] / "bin" / "openlabs-container-loop"

FAKE_PYTHON = """#!/usr/bin/env bash
# Fake interpreter: `-m openlabs tick` writes a TickReport-shaped JSON after a
# short "tick"; everything else runs the real interpreter.
if [[ ${1-} == -m && ${2-} == openlabs && ${3-} == tick ]]; then
  n=$(cat "$FAKE_DIR/count" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" >"$FAKE_DIR/count"
  echo "start $n $OPENLABS_INSTANCE $OPENLABS_CONFIG_FILE" >>"$FAKE_DIR/ticks.log"
  echo "proxy $n ${HTTPS_PROXY-} ${http_proxy-} ${NO_PROXY-}" >>"$FAKE_DIR/proxy.log"
  if ((n <= ${FAKE_FAIL_TICKS:-0})); then
    # Like a failed network preflight: exit 69 before ingesting any receipt.
    echo '{"schema_version": "openlabs.proxy_preflight.v1", "status": "failed"}' >&2
    exit 69
  fi
  [[ -n ${FAKE_KEEP_RECEIPTS-} ]] || rm -f "$OPENLABS_DATABASE_ROOT"/inbox/results/*.json
  sleep "${FAKE_TICK_SECONDS:-0.2}"
  echo "end $n" >>"$FAKE_DIR/ticks.log"
  printf '{"launched": ["t%s"], "enqueued": [], "ingested": [], "errors": []}\\n' "$n"
  exit 0
fi
exec "$REAL_PYTHON" "$@"
"""


@pytest.fixture()
def instance(tmp_path: Path) -> dict[str, object]:
    root = tmp_path / "inst"
    (root / "database" / "inbox" / "results").mkdir(parents=True)
    (root / "openlabs.toml").write_text("[program]\nenabled = false\n", encoding="utf-8")
    (root / "instance.env").write_text(
        f"OPENLABS_WORKSPACE={tmp_path}\nOPENLABS_INSTANCE=test-loop\n"
        f"OPENLABS_DATABASE_ROOT={root / 'database'}\n"
        f"OPENLABS_CONFIG_FILE={root / 'openlabs.toml'}\n"
        "OPENLABS_LOOP_POLL_SECONDS=1\n",
        encoding="utf-8",
    )
    fake = tmp_path / "fake-python"
    fake.write_text(FAKE_PYTHON, encoding="utf-8")
    fake.chmod(0o755)
    environment = {
        key: value for key, value in os.environ.items()
        if not key.startswith("OPENLABS_")
    }
    environment.update({
        "OPENLABS_LOOP_GUARDED": "1",  # the test process itself is the guard
        "OPENLABS_LOOP_PYTHON": str(fake),
        "OPENLABS_TEXENV": str(tmp_path / "missing-texenv.sh"),
        "REAL_PYTHON": sys.executable,
        "FAKE_DIR": str(tmp_path),
    })
    return {"root": root, "env": environment, "tmp": tmp_path}


def _loop(instance, *args: str, env: dict[str, str] | None = None, timeout: float = 30):
    return subprocess.run(
        [str(LOOP), "--instance-dir", str(instance["root"]), *args],
        env={**instance["env"], **(env or {})},
        capture_output=True, text=True, timeout=timeout, check=False,
    )


def _wait(predicate, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError("condition not reached")


def _ticks(instance) -> list[dict]:
    path = Path(instance["root"]) / "state" / "ticks.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_start_status_early_wake_single_instance_and_graceful_stop(instance) -> None:
    long_interval = {"OPENLABS_LOOP_INTERVAL_SECONDS": "120", "FAKE_TICK_SECONDS": "0.2"}
    started = _loop(instance, "start", env=long_interval)
    assert started.returncode == 0, started.stderr
    assert "started: pid" in started.stdout
    try:
        _wait(lambda: len(_ticks(instance)) >= 1)
        first = _ticks(instance)[0]
        assert first["exit_code"] == 0 and first["report"]["launched"] == ["t1"]
        log = (Path(instance["tmp"]) / "ticks.log").read_text(encoding="utf-8")
        assert "test-loop" in log and str(instance["root"] / "openlabs.toml") in log

        status = _loop(instance, "status")
        assert "running: pid" in status.stdout and "last tick:" in status.stdout
        assert "'launched': 1" in status.stdout
        # Already running: start is a no-op, a second foreground loop is refused.
        assert "already running" in _loop(instance, "start").stdout
        second = _loop(instance, "run")
        assert second.returncode == 75 and "already has a running loop" in second.stderr

        # A result receipt ends the 120 s sleep early.
        receipt = Path(instance["root"]) / "database" / "inbox" / "results" / "r.json"
        receipt.write_text("{}", encoding="utf-8")
        _wait(lambda: len(_ticks(instance)) >= 2, timeout=10)

        # Stop during a (slow) tick: the tick finishes, then the loop exits.
        (Path(instance["tmp"]) / "count").write_text("10", encoding="utf-8")
        receipt.write_text("{}", encoding="utf-8")
        _wait(lambda: "start 11" in (Path(instance["tmp"]) / "ticks.log").read_text())
    finally:
        stopped = _loop(instance, "stop", "--timeout", "20",
                        env={"FAKE_TICK_SECONDS": "0"})
    assert stopped.returncode == 0, stopped.stderr
    assert "stopped" in stopped.stdout
    log = (Path(instance["tmp"]) / "ticks.log").read_text(encoding="utf-8")
    if "start 11" in log:
        assert "end 11" in log
    assert "stopped" in _loop(instance, "status").stdout
    loop_log = (Path(instance["root"]) / "state" / "loop.log").read_text(encoding="utf-8")
    assert "LaTeX environment" in loop_log and "loop stopped" in loop_log


def test_signal_during_a_tick_lets_the_tick_finish(instance) -> None:
    process = subprocess.Popen(
        [str(LOOP), "--instance-dir", str(instance["root"]), "run"],
        env={**instance["env"], "FAKE_TICK_SECONDS": "2", "OPENLABS_LOOP_INTERVAL_SECONDS": "60"},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    log = Path(instance["tmp"]) / "ticks.log"
    _wait(lambda: log.is_file() and "start 1" in log.read_text())
    process.terminate()  # SIGTERM to the loop only, mid-tick
    process.wait(timeout=20)
    assert process.returncode == 0
    assert "end 1" in log.read_text(encoding="utf-8")
    assert [row["report"]["launched"] for row in _ticks(instance)] == [["t1"]]


def test_missing_instance_env_and_cli_passthrough(instance, tmp_path) -> None:
    missing = subprocess.run(
        [str(LOOP), "--instance-dir", str(tmp_path / "nowhere"), "status"],
        env=instance["env"], capture_output=True, text=True, timeout=30, check=False,
    )
    assert missing.returncode == 78 and "init-instance" in missing.stderr
    probe = _loop(instance, "cli", "--", "--version", env={
        # cli runs `python -m openlabs ARGS`; the fake interpreter passes it through.
        "OPENLABS_LOOP_PYTHON": str(Path(instance["tmp"]) / "fake-python")})
    # The real `python -m openlabs --version` is not a valid command: argparse exits 2,
    # after the instance variables were exported (no 78/65 refusal from the wrapper).
    assert probe.returncode == 2


def _run_foreground(instance, env: dict[str, str], timeout: float = 60) -> tuple[float, str]:
    started = time.monotonic()
    completed = _loop(instance, "run", env=env, timeout=timeout)
    assert completed.returncode == 0, completed.stderr
    elapsed = time.monotonic() - started
    return elapsed, (Path(instance["root"]) / "state" / "loop.log").read_text(encoding="utf-8")


def test_failed_ticks_back_off_exponentially_despite_waiting_receipts(instance) -> None:
    # A receipt waits the whole time; failed ticks (rc 69) never consume it.
    receipt = Path(instance["root"]) / "database" / "inbox" / "results" / "r.json"
    receipt.write_text("{}", encoding="utf-8")
    elapsed, log = _run_foreground(instance, {
        "FAKE_FAIL_TICKS": "3", "FAKE_TICK_SECONDS": "0",
        "OPENLABS_LOOP_BACKOFF_BASE_SECONDS": "1", "OPENLABS_LOOP_BACKOFF_MAX_SECONDS": "2",
        "OPENLABS_LOOP_INTERVAL_SECONDS": "1", "OPENLABS_LOOP_MAX_TICKS": "5",
    })
    assert [row["exit_code"] for row in _ticks(instance)] == [69, 69, 69, 0, 0]
    # 1 s, then 2 s, then 2 s (capped) between the failed ticks: no busy loop.
    assert elapsed >= 5
    assert "rc=69 failures=1; backing off 1s" in log
    assert "rc=69 failures=2; backing off 2s" in log
    assert "rc=69 failures=3; backing off 2s" in log
    assert "tick succeeded after 3 failed tick(s); backoff reset" in log
    # The receipt woke nothing while ticks failed; the 4th (successful) tick consumed it.
    assert "ticking early" not in log
    assert not receipt.exists()
    err = (Path(instance["root"]) / "state" / "tick.err").read_text(encoding="utf-8")
    assert err.count("openlabs.proxy_preflight.v1") == 3


def test_backoff_wait_still_honours_stop(instance) -> None:
    process = subprocess.Popen(
        [str(LOOP), "--instance-dir", str(instance["root"]), "run"],
        env={**instance["env"], "FAKE_FAIL_TICKS": "100", "FAKE_TICK_SECONDS": "0",
             "OPENLABS_LOOP_BACKOFF_BASE_SECONDS": "600"},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    log = Path(instance["root"]) / "state" / "loop.log"
    _wait(lambda: log.is_file() and "backing off 600s" in log.read_text())
    started = time.monotonic()
    process.terminate()
    process.wait(timeout=20)
    assert process.returncode == 0 and time.monotonic() - started < 10
    assert len(_ticks(instance)) == 1
    assert "loop stopped" in log.read_text(encoding="utf-8")


def test_unconsumed_receipt_wakes_a_successful_loop_only_once(instance) -> None:
    receipt = Path(instance["root"]) / "database" / "inbox" / "results" / "r.json"
    receipt.write_text("{}", encoding="utf-8")
    elapsed, log = _run_foreground(instance, {
        "FAKE_KEEP_RECEIPTS": "1", "FAKE_TICK_SECONDS": "0",
        "OPENLABS_LOOP_INTERVAL_SECONDS": "3", "OPENLABS_LOOP_MAX_TICKS": "3",
    })
    assert [row["exit_code"] for row in _ticks(instance)] == [0, 0, 0]
    assert log.count("ticking early") == 1  # tick 2 early, tick 3 after the interval
    assert elapsed >= 3


def test_agent_proxy_setting_overrides_the_inherited_proxy(instance) -> None:
    env_file = Path(instance["root"]) / "instance.env"
    inherited = {"HTTPS_PROXY": "http://127.0.0.1:18081", "http_proxy": "http://127.0.0.1:18081",
                 "NO_PROXY": "example.invalid", "FAKE_TICK_SECONDS": "0",
                 "OPENLABS_LOOP_MAX_TICKS": "1"}
    _run_foreground(instance, inherited)
    proxy_log = Path(instance["tmp"]) / "proxy.log"
    assert proxy_log.read_text().splitlines()[-1] == (
        "proxy 1 http://127.0.0.1:18081 http://127.0.0.1:18081 example.invalid")

    env_file.write_text(env_file.read_text() + "OPENLABS_LOOP_AGENT_PROXY=http://127.0.0.1:18080\n")
    (Path(instance["tmp"]) / "count").write_text("1")
    _, log = _run_foreground(instance, inherited)
    assert proxy_log.read_text().splitlines()[-1] == (
        "proxy 2 http://127.0.0.1:18080 http://127.0.0.1:18080 localhost,127.0.0.1,::1")
    assert "agent_proxy=127.0.0.1:18080" in log

    # The caller's environment wins over instance.env for this setting too.
    refused = _loop(instance, "run", env={**inherited, "OPENLABS_LOOP_AGENT_PROXY": "socks5://h:1"})
    assert refused.returncode == 65 and "OPENLABS_LOOP_AGENT_PROXY" in refused.stderr


def test_state_logs_rotate_past_the_size_cap(instance) -> None:
    _run_foreground(instance, {"FAKE_FAIL_TICKS": "4", "FAKE_TICK_SECONDS": "0",
                               "OPENLABS_LOOP_BACKOFF_BASE_SECONDS": "1",
                               "OPENLABS_LOOP_BACKOFF_MAX_SECONDS": "1",
                               "OPENLABS_LOOP_LOG_MAX_BYTES": "150",
                               "OPENLABS_LOOP_MAX_TICKS": "4"})
    state = Path(instance["root"]) / "state"
    for name in ("loop.log", "tick.err", "ticks.jsonl"):
        assert (state / f"{name}.1").is_file(), name
        assert (state / name).stat().st_size < 1000, name
