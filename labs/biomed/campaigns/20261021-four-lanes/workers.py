"""Start four isolated research services with a fixed campaign deadline."""

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
WORKSPACE = CODE.parent
ARTIFACT = WORKSPACE / "openlabs-artifacts/artifact-stage/biomed/four-lanes-20261021"
CONFIG = HERE / "campaign.json"
LANES = ("promoter_transfer", "drug_support", "perturbation_context", "disease_cell_state")


def now():
    return datetime.now(UTC)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def unit(lane):
    return f"openlabs-biomed-four-{lane.replace('_', '-')}-20261021.service"


def settings():
    return json.loads(CONFIG.read_text())


def require_guard():
    cgroup = Path("/proc/self/cgroup").read_text()
    if "openlabs-workers.slice" not in cgroup:
        raise RuntimeError("Run through bin/openlabs-resource-guard")
    return cgroup.strip()


def remaining_seconds(config):
    remaining = int((datetime.fromisoformat(config["deadline_utc"]) - now()).total_seconds())
    if remaining <= 0:
        raise RuntimeError("Campaign deadline already reached")
    return remaining


def supervise(lane):
    cgroup = require_guard()
    config = settings()
    remaining = remaining_seconds(config)
    root = ARTIFACT / lane
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / "process-status.json"
    # Exclusive reservation prevents an accidental second process in this lane.
    with state_path.open("x") as stream:
        json.dump({"status": "starting", "lane": lane}, stream)
    state = dict(
        lane=lane,
        unit=unit(lane),
        status="starting",
        cgroup=cgroup,
        supervisor_pid=os.getpid(),
        started_at_utc=now().isoformat(),
        deadline_utc=config["deadline_utc"],
        scientific_goal_achieved=False,
    )
    write(state_path, state)
    stop_requested = False

    def request_stop(_signum, _frame):
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    prompt = (
        (HERE / "common.prompt.txt").read_text() + "\n" + (HERE / f"{lane}.prompt.txt").read_text()
    )
    (root / "launch-prompt.txt").write_text(prompt)
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
    stop_at = time.monotonic() + remaining
    child = None
    try:
        with (
            (root / "events.jsonl").open("xb") as events,
            (root / "agent.stderr").open("xb") as errors,
        ):
            child = subprocess.Popen(
                command,
                cwd=CODE,
                stdin=subprocess.PIPE,
                stdout=events,
                stderr=errors,
                start_new_session=True,
            )
            state.update(status="running", child_pid=child.pid)
            write(state_path, state)
            child.stdin.write(prompt.encode())
            child.stdin.close()
            reason = "agent_exited"
            while child.poll() is None:
                if stop_requested or time.monotonic() >= stop_at:
                    reason = "stop_requested" if stop_requested else "deadline"
                    break
                if (root / "events.jsonl").stat().st_size > 128 * 1024**2:
                    reason = "event_log_budget"
                    break
                state["supervisor_heartbeat_utc"] = now().isoformat()
                write(state_path, state)
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
                ended_at_utc=now().isoformat(),
            )
            write(state_path, state)
    except Exception as exc:
        state.update(
            status="failed", error=f"{type(exc).__name__}: {exc}", ended_at_utc=now().isoformat()
        )
        write(state_path, state)
        raise
    finally:
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
    return 0 if child.returncode == 0 else 1


def launch_command(lane, seconds):
    root = ARTIFACT / lane
    # A long-lived systemd manager can retain a stale workstation proxy. Pass
    # this invocation's network route explicitly; keep connectivity preflight.
    proxy_keys = (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    )
    network_environment = [
        f"--setenv={key}={os.environ[key]}" for key in proxy_keys if key in os.environ
    ]
    return [
        "systemd-run",
        "--user",
        "--quiet",
        f"--unit={unit(lane)}",
        "--slice=openlabs-workers.slice",
        f"--working-directory={CODE}",
        f"--setenv=PATH={os.environ['PATH']}",
        *network_environment,
        "--setenv=OPENLABS_PROXY_AUTO_SYNC=0",
        "--setenv=OPENLABS_PROXY_SYNC_SYSTEMD=0",
        *[
            f"--setenv={key}=2"
            for key in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
                "BLIS_NUM_THREADS",
            )
        ],
        "--property=MemoryAccounting=yes",
        "--property=CPUAccounting=yes",
        "--property=MemoryHigh=4G",
        "--property=MemoryMax=5G",
        "--property=MemorySwapMax=512M",
        "--property=CPUQuota=200%",
        "--property=TasksMax=96",
        "--property=OOMPolicy=kill",
        f"--property=RuntimeMaxSec={seconds}s",
        "--property=KillMode=control-group",
        "--property=TimeoutStopSec=35s",
        "--property=Restart=no",
        f"--property=StandardOutput=append:{root / 'supervisor.log'}",
        f"--property=StandardError=append:{root / 'supervisor.log'}",
        str(CODE / "bin/openlabs-resource-guard"),
        "--task-type",
        "cpu",
        "--",
        "/usr/bin/python3",
        str(Path(__file__).resolve()),
        "run",
        "--lane",
        lane,
    ]


def launch():
    require_guard()
    config = settings()
    seconds = remaining_seconds(config)
    if not (CODE / "labs/biomed/.venv/bin/python").exists():
        raise RuntimeError("Base scientific environment missing")
    if not (CODE / "labs/biomed/environments/singlecell/.venv/bin/python").exists():
        raise RuntimeError("Single-cell environment missing")
    for lane in LANES:
        if (ARTIFACT / lane / "process-status.json").exists():
            raise RuntimeError(f"Refusing duplicate launch: {lane}")
        if not (HERE / f"{lane}.prompt.txt").is_file():
            raise RuntimeError(f"Missing lane instructions: {lane}")
    started = []
    try:
        for lane in LANES:
            (ARTIFACT / lane).mkdir(parents=True, exist_ok=True)
            subprocess.run(launch_command(lane, seconds), check=True)
            started.append(lane)
            print(
                json.dumps(
                    {"launched": lane, "unit": unit(lane), "deadline_utc": config["deadline_utc"]}
                ),
                flush=True,
            )
    except Exception:
        # Record a partial launch accurately; keep successfully started research running.
        write(ARTIFACT / "partial-launch.json", {"started": started, "time_utc": now().isoformat()})
        raise


def status():
    for lane in LANES:
        path = ARTIFACT / lane / "process-status.json"
        research = ARTIFACT / lane / "research_status.json"
        result = subprocess.run(
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
                "-p",
                "CPUQuotaPerSecUSec",
                "-p",
                "TasksCurrent",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        print(
            json.dumps(
                {
                    "lane": lane,
                    "process": json.loads(path.read_text()) if path.exists() else None,
                    "research": json.loads(research.read_text()) if research.exists() else None,
                    "systemd": result.stdout,
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["launch", "run", "status"])
    parser.add_argument("--lane", choices=LANES)
    args = parser.parse_args()
    if args.action == "run":
        if args.lane is None:
            parser.error("run requires --lane")
        raise SystemExit(supervise(args.lane))
    if args.action == "launch":
        launch()
    else:
        status()
