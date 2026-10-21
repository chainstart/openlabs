"""Launch and supervise exactly two bounded day-one research processes."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODE = HERE.parents[3]
ARTIFACT = CODE.parent / "openlabs-artifacts/artifact-stage/biomed/day1-workers-20261021"
DEADLINE = datetime(2026, 10, 22, 0, 10, tzinfo=UTC)
LANES = ("functional_genomics", "drug_response")


def write(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def unit(lane):
    return f"openlabs-biomed-day1-{lane.replace('_', '-')}-20261021.service"


def supervise(lane):
    cgroup = Path("/proc/self/cgroup").read_text()
    if "openlabs-workers.slice" not in cgroup:
        raise RuntimeError("Research supervisor must inherit the repository resource slice")
    root = ARTIFACT / lane
    root.mkdir(parents=True, exist_ok=True)
    if (root / "process-status.json").exists():
        raise RuntimeError("Refusing duplicate research launch")
    remaining = (DEADLINE - datetime.now(UTC)).total_seconds()
    if remaining <= 0:
        raise RuntimeError("Campaign deadline already reached")
    stop_at = time.monotonic() + remaining
    command = [
        str(CODE / "bin/openlabs-codex"),
        "exec",
        "--json",
        "--color",
        "never",
        "--output-last-message",
        str(root / "agent-final-message.md"),
        "-",
    ]
    state = {
        "lane": lane,
        "unit": unit(lane),
        "started_at_utc": datetime.now(UTC).isoformat(),
        "deadline_utc": DEADLINE.isoformat(),
        "cgroup": cgroup.strip(),
        "supervisor_pid": os.getpid(),
        "status": "starting",
        "scientific_goal_achieved": False,
    }
    write(root / "process-status.json", state)
    stop_requested = False

    def request_stop(_signum, _frame):
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    with (
        (HERE / f"{lane}.prompt.txt").open("rb") as prompt,
        (root / "events.jsonl").open("wb") as events,
        (root / "agent.stderr").open("wb") as errors,
    ):
        child = subprocess.Popen(
            command, cwd=CODE, stdin=prompt, stdout=events, stderr=errors, start_new_session=True
        )
        state.update(status="running", child_pid=child.pid)
        write(root / "process-status.json", state)
        reason = "agent_exited"
        while child.poll() is None:
            if stop_requested or time.monotonic() >= stop_at:
                reason = "stop_requested" if stop_requested else "deadline"
                break
            if (root / "events.jsonl").stat().st_size > 128 * 1024**2:
                reason = "event_log_budget"
                break
            state["supervisor_heartbeat_utc"] = datetime.now(UTC).isoformat()
            write(root / "process-status.json", state)
            time.sleep(5)
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=10)
        state.update(
            status="finished" if child.returncode == 0 else "stopped",
            stop_reason=reason,
            exit_code=child.returncode,
            ended_at_utc=datetime.now(UTC).isoformat(),
        )
        write(root / "process-status.json", state)
    # The service's KillMode=control-group also removes any lingering descendants.
    return 0 if child.returncode == 0 else 1


def launch():
    if "openlabs-workers.slice" not in Path("/proc/self/cgroup").read_text():
        raise RuntimeError("Run launcher through bin/openlabs-resource-guard")
    remaining = int((DEADLINE - datetime.now(UTC)).total_seconds())
    if remaining <= 0:
        raise RuntimeError("Campaign deadline already reached")
    for lane in LANES:
        root = ARTIFACT / lane
        root.mkdir(parents=True, exist_ok=True)
        if (root / "process-status.json").exists():
            raise RuntimeError(f"Refusing duplicate launch: {lane}")
        command = [
            "systemd-run",
            "--user",
            "--quiet",
            f"--unit={unit(lane)}",
            "--slice=openlabs-workers.slice",
            f"--working-directory={CODE}",
            f"--setenv=PATH={os.environ['PATH']}",
            "--setenv=OMP_NUM_THREADS=2",
            "--setenv=OPENBLAS_NUM_THREADS=2",
            "--setenv=MKL_NUM_THREADS=2",
            "--setenv=NUMEXPR_NUM_THREADS=2",
            "--property=MemoryAccounting=yes",
            "--property=CPUAccounting=yes",
            "--property=MemoryHigh=1536M",
            "--property=MemoryMax=2048M",
            "--property=MemorySwapMax=512M",
            "--property=CPUQuota=200%",
            "--property=TasksMax=96",
            f"--property=RuntimeMaxSec={remaining}s",
            "--property=KillMode=control-group",
            "--property=TimeoutStopSec=35s",
            f"--property=StandardOutput=append:{root / 'supervisor.log'}",
            f"--property=StandardError=append:{root / 'supervisor.log'}",
            str(CODE / "bin/openlabs-resource-guard"),
            "--task-type",
            "cpu",
            "--",
            str(CODE / "labs/biomed/.venv/bin/python"),
            str(Path(__file__).resolve()),
            "run",
            "--lane",
            lane,
        ]
        subprocess.run(command, check=True)
        print(json.dumps({"launched": lane, "unit": unit(lane), "deadline": DEADLINE.isoformat()}))


def status():
    for lane in LANES:
        path = ARTIFACT / lane / "process-status.json"
        process = json.loads(path.read_text()) if path.exists() else {"status": "not_launched"}
        properties = subprocess.run(
            [
                "systemctl",
                "--user",
                "show",
                unit(lane),
                "-p",
                "ActiveState",
                "-p",
                "SubState",
                "-p",
                "MainPID",
                "-p",
                "ControlGroup",
                "-p",
                "MemoryCurrent",
                "-p",
                "MemoryMax",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        print(json.dumps({"lane": lane, "process": process, "systemd": properties.stdout}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["launch", "run", "status"])
    parser.add_argument("--lane", choices=LANES)
    args = parser.parse_args()
    if args.action == "run":
        if not args.lane:
            parser.error("run requires --lane")
        raise SystemExit(supervise(args.lane))
    if args.action == "launch":
        launch()
    else:
        status()
