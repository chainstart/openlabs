# OpenLabs aggregate resource guard

## cc-sg container support (2026-11-11)

`bin/openlabs-resource-guard` also supports the cc-sg Docker workspace without
an in-container systemd manager. The wrapper verifies the actual cgroup v2
CPU quota (at most 75% of visible CPUs), memory hard limit (34 GiB), swap limit
(4 GiB) and task limit (512). It also requires the host GPU lock directory to
be bind-mounted at `$XDG_RUNTIME_DIR/openlabs-gpu-guard` (default
`/run/user/1000/openlabs-gpu-guard`). Missing limits or the mount fail closed.
CPU and GPU command syntax is unchanged. GPU admission, allocator caps,
telemetry supervision and descendant cleanup still use `gpu_guard.py`.

The cc-sg workspace has 15 CPUs, a 34 GiB hard memory limit, a 30 GiB Docker
memory reservation, 4 GiB swap and 512 tasks. A Docker memory reservation is
not the WSL guard's `memory.high` soft throttle. These are aggregate limits
for processes **inside that container**, not a combined host-and-container
CPU/RAM budget. WSL research remains in its own systemd slice; do not assume
the combined RAM usage is capped at 34 GiB or run simultaneous large host and
container workloads on that assumption. Separate `cc-sg open` containers also
have separate CPU/RAM limits. GPU leases, by contrast, are shared with WSL and
the cc-sg containers through the same host lock inodes.

In the container, factory workers are detached children of the tick, not
systemd units, and `gpu_guard.py` (behind the wrapper) is a child subreaper that
kills every descendant when its command exits. Do not run a single tick as
`openlabs-resource-guard -- python -m openlabs tick`: its workers would die
about a second after launch, so `tick` refuses that (exit 78). Run the tick
loop inside one long-lived guard; workers then live as long as the loop.
`bin/openlabs-container-loop` does exactly that (`docs/operations.zh.md`, "容器实例").

The current container is configured live; Compose and `cc-sg open` persist the
limits and mount for subsequent launches. Container tasks do not need root,
privileged mode, Docker socket access or a writable cgroup filesystem. Installing
model dependencies and preparing model weights remain separate steps.

On the WSL host, interactive Codex research, worker services and heavy local commands share
`openlabs-workers.slice`. The guard limits the aggregate research workload; it
does not reduce Codex filesystem or network permissions.

On this 20-thread WSL host the limits are:

- CPU: 15 logical CPUs (75% of the CPUs visible to OpenLabs)
- memory soft throttle: 30 GiB
- memory hard limit: 34 GiB
- swap: 4 GiB
- tasks: 512
- GPU: one declared research job per device, 90% total VRAM ceiling, at least
  1024 MiB free, stop at 85 C; default declared job budget below is 8192 MiB.

The memory, swap and task limits match the installed OpenMath guard. OpenMath
does not currently define a CPU quota; OpenLabs retains its pre-existing 75%
CPU policy and applies it at the aggregate slice as well as scheduler admission.

## What must run inside the guard

The guard is placed once, by the launcher, around the whole agent session; it is
not re-applied per command.

- **Launcher responsibility (hard rule).** Factory workers start inside
  `openlabs-workers.slice` (systemd) or, in Docker, inside a container whose
  CPU, memory, swap and task limits `container_guard.py` has verified; math
  workers additionally need the 16/18 GiB no-swap math budget. When it cannot
  do either, the launcher refuses to start the worker (and therefore the
  agent) instead of running it unbounded.
- **Inside a guarded session** (factory worker, `bin/openlabs-codex`, verified
  container) run commands directly. Every child inherits the session's cgroup,
  so wrapping each interpreter call adds no protection, only friction. To
  check, `/proc/self/cgroup` contains `openlabs-workers.slice`, or
  `/.dockerenv` exists and `python3 orchestrator/src/openlabs/container_guard.py`
  exits 0.
- **GPU work always reserves its device explicitly**, even inside a guarded
  session: `bin/openlabs-resource-guard --task-type gpu --gpu-memory-mib N
  --gpu-device N -- <command>`. The cgroup does not arbitrate GPUs; the shared
  GPU lease does, and a CPU label never authorizes CUDA work. Do not unset the
  allocator cap, launch parallel GPU children inside one lease, or bypass the
  supervisor. Solve GPU pressure by reducing batch/context/model memory,
  offloading or queueing, never by disabling CUDA or raising ceilings.
- **Ad-hoc sessions outside the guard** (an operator shell, an unguarded
  assistant session): small scripts, probes and inspection run directly.
  Parallel or multi-process work, large-memory jobs, long-running jobs, test
  suites that fan out, builds, package installation, model inference or
  training, and nested agent invocations go through `bin/openlabs-codex` or
  `bin/openlabs-resource-guard -- <command>`; put a whole pipeline inside one
  guard (`bin/openlabs-resource-guard -- bash -lc '<producer> | <consumer>'`).
  When resource use is uncertain, use the guard.
- Background jobs, `nohup`, `tmux`, resumed campaigns and child processes
  started from an unguarded shell do not become guarded later; start them
  inside the guard.
- If the guard, the systemd user manager or cgroup v2 controllers (or, in a
  container, the verified cgroup limits) are unavailable, heavy work fails
  closed: repair or install the guard first.

## Install and verify

```bash
bin/install-resource-guard
systemctl --user show openlabs-workers.slice \
  -p ActiveState -p CPUQuotaPerSecUSec -p MemoryHigh -p MemoryMax \
  -p MemorySwapMax -p TasksMax
```

The installer recalculates 75% from the CPU count visible on the current host.
It installs only the slice; it does not enable the factory timer.

Result ingestion is a separate, lightweight event service. Install it once so
an atomically published worker receipt immediately runs an idempotent tick and
updates SQLite, even when the periodic factory timer is disabled:

```bash
bin/install-completion-watcher
systemctl --user status openlabs-results.path
journalctl --user -u openlabs-tick.service
```

This watcher performs control-plane ingestion and the already-declared
continuation actions. It does not inject messages into an active Codex TUI.

## Run work inside the guard

```bash
bin/openlabs-codex
bin/openlabs-resource-guard -- uv run pytest -q
bin/openlabs-resource-guard --task-type cpu -- python path/to/heavy_search.py
bin/openlabs-resource-guard --task-type gpu --gpu-memory-mib 8192 --gpu-device 0 -- python train.py
```

Nested calls reuse the current cgroup, so scripts may invoke the wrapper safely.
`bin/openlabs-codex` also fixes the interactive runtime to
`approval_policy=never` and `danger-full-access`; the aggregate cgroup is the
resource boundary, not a filesystem sandbox.
If systemd, cgroup v2 controllers or the slice are unavailable, the wrapper
fails closed instead of starting an unbounded workload.

Use `systemd-cgtop --user` or the following command while work is active:

```bash
systemctl --user status openlabs-workers.slice
```

Do not raise these limits without reviewing both WSL and Windows host budgets.

## Task classification

All types retain the aggregate CPU, memory, swap and task limits above.

| Task type | Examples | GPU constraints |
| --- | --- | --- |
| `cpu` | Mathematical solvers, exact arithmetic, CPU simulations, tests, builds, factory controllers | No GPU telemetry, admission or allocator changes; external VRAM pressure does not stop the task |
| `gpu` | CUDA inference/training and GPU simulations | Explicit budget, exclusive device reservation, allocator cap, VRAM and temperature monitoring |
| `auto` (default) | Existing wrapper calls | GPU if `--gpu-memory-mib` is supplied, CPU otherwise |

Classification is declared, not inferred from filenames or executable names.
`gpu` requires a budget; `cpu` rejects GPU options. Existing budget arguments
continue to select GPU protection without requiring a new type argument.
CPU commands retain the caller's CUDA visibility and allocator settings; the
guard does not inject GPU settings for them. A CPU declaration does not authorize
undeclared CUDA work. A controller running CPU and GPU phases should launch each
GPU phase through its own budgeted guard invocation. Factory controllers and the
math wrapper explicitly select CPU protection.

An existing GPU supervisor still owns its entire descendant workload, including
CPU children. A nested CPU invocation cannot escape that outer watchdog. Launch
independent CPU research outside the GPU job when it should survive external GPU
pressure. New CPU invocations also work without NVIDIA hardware or telemetry.

## GPU admission and supervision

GPU remains enabled. Declare a budget for every GPU workload, including work
launched by an already guarded Codex/factory worker. A private advisory `flock`
under `$XDG_RUNTIME_DIR/openlabs-gpu-guard/` allows one declared job per GPU UUID.
Admission fails promptly when occupied; queue/retry after the current job ends.
The budget includes allocator memory, contexts, and other CUDA allocations.
CPU commands and downloads can run alongside the reserved GPU job.

On this RTX 5070 (12227 MiB), the global used-memory ceiling is **9170 MiB**,
leaving at least **3057 MiB** for the display/host and transient pressure. An
8192 MiB job is admitted only when current usage plus 8192 fits below that ceiling.
Its PyTorch native allocator receives **7424 MiB** (768 MiB context reserve).
The allocator environment key is verified against installed PyTorch 2.10; other
frameworks/older versions need their own allocator cap before allocation.
`HF_DEACTIVATE_ASYNC_LOAD=1` makes Transformers 5.3 load and quantize weights
sequentially, preventing queued full-precision GPU copies from consuming the
budget before conversion. GPU inference remains enabled.

For GPU tasks, the stdlib supervisor `orchestrator/src/openlabs/gpu_guard.py` checks GPU memory
and temperature every 0.5 s (each telemetry call has a 2 s timeout). Excess global
usage, job-attributed global growth above the reservation, 85 C, inventory change,
or telemetry failure stops the owned process tree: SIGINT, then SIGTERM, then
SIGKILL if necessary. Normal exit also cleans up remaining descendants and
releases the lock. It does not kill unrelated processes or alter driver clocks,
power settings, compute modes, or display configuration. WSL lacks reliable
per-process VRAM telemetry, so external GPU pressure may also stop our job.

Only the reserved device is monitored; pressure or temperature on a different
GPU does not terminate the job. CPU tasks do not run this monitor. Explicit
GPU reservations remain mandatory: advisory locks
cannot prevent uncooperative/unmarked code from using CUDA. Nested calls reuse
an actual ancestor supervisor; an inherited cgroup alone does not bypass GPU
protection. Nested explicit reservations must match the outer budget/device.

This is **not a kernel VRAM quota**: non-PyTorch/driver allocation can overshoot
between samples, and non-interruptible GPU kernels may take time to exit. Keep
headroom and use framework allocator caps. GPU compute utilization can still
reach 100% during useful work; WSL offers no cgroup percentage throttle for GPU
compute. High utilization alone is not VRAM exhaustion. Do not run concurrent GPU
children under one reservation or override the supplied allocator environment.

No service installation is needed for this GPU change; new wrapper invocations
and newly launched factory workers use it immediately. Existing processes need
a checkpoint and guarded restart. Monitor with `nvidia-smi` and check the job's
stderr for admission or stop reasons. A watchdog stop exits 75; forwarded signals
return 128 plus signal number. Preserve interrupted outputs before restarting.

## Mathematics allocation alongside physics (2026-09-06)

The user reserves 16 GiB for physics. Mathematics receives the remainder of the
existing 34 GiB aggregate research ceiling: **18 GiB shared hard limit, 16 GiB
soft throttle, no swap, 512 tasks**. The observed WSL physical memory is about
39.2 GiB, leaving about 5.2 GiB outside the aggregate ceiling for other WSL work.
This is a cap, not preallocated RAM or a guarantee that unrelated workloads cannot
consume the remaining system memory. Physics limits and running jobs are not changed.

```bash
bin/openlabs-resource-guard -- bin/install-math-resource-guard
bin/openlabs-math-resource-guard -- <command> [args...]
```

`openlabs-workers-math.slice` is a child of `openlabs-workers.slice`. All math
workers, checks, builds and their subprocesses must start through the math wrapper
or inherit that math cgroup. Five research processes do **not** each receive 18 GiB.
The wrapper first enters the ordinary `openlabs-resource-guard`, then the shared
math slice, and refuses to launch if the installed math limits have drifted.
Nested ordinary guard calls preserve the inherited math cap. The installer only
installs the math child slice; it neither changes physics nor starts researchers,
factory workers, timers or campaigns.

On 2026-10-02 the user authorized increasing independent research processes
while retaining aggregate CPU and memory protection. The mathematical child
task ceiling now matches the existing 512-task parent ceiling, allowing helper
threads for eight independent Codex contexts. The global task ceiling, CPU
quota and all RAM/swap ceilings remain unchanged. Threads count toward this
task ceiling as well as processes; it is not the number of research directions.
