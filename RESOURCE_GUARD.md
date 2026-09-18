# OpenLabs aggregate resource guard

All interactive Codex research, worker services and heavy local commands share
`openlabs-workers.slice`. The guard limits the aggregate research workload; it
does not reduce Codex filesystem or network permissions.

On this 20-thread WSL host the limits are:

- CPU: 15 logical CPUs (75% of the CPUs visible to OpenLabs)
- memory soft throttle: 30 GiB
- memory hard limit: 34 GiB
- swap: 4 GiB
- tasks: 512
- GPU: one declared research job per device, 75% total VRAM ceiling, at least
  2048 MiB free, stop at 85 C; default declared job budget below is 8192 MiB.

The memory, swap and task limits match the installed OpenMath guard. OpenMath
does not currently define a CPU quota; OpenLabs retains its pre-existing 75%
CPU policy and applies it at the aggregate slice as well as scheduler admission.

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
bin/openlabs-resource-guard -- python path/to/heavy_search.py
bin/openlabs-resource-guard --gpu-memory-mib 8192 --gpu-device 0 -- python train.py
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

The stdlib supervisor `orchestrator/src/openlabs/gpu_guard.py` checks GPU memory
and temperature every 0.5 s (each telemetry call has a 2 s timeout). Excess global
usage, job-attributed global growth above the reservation, 85 C, inventory change,
or telemetry failure stops the owned process tree: SIGINT, then SIGTERM, then
SIGKILL if necessary. Normal exit also cleans up remaining descendants and
releases the lock. It does not kill unrelated processes or alter driver clocks,
power settings, compute modes, or display configuration. WSL lacks reliable
per-process VRAM telemetry, so external GPU pressure may also stop our job.

Ordinary wrapper commands and factory workers run through the same monitor and
receive a conservative PyTorch allocator cap. They do not reserve a GPU merely
to execute CPU work. Explicit GPU reservations remain mandatory: advisory locks
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
soft throttle, no swap, 256 tasks**. The observed WSL physical memory is about
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
