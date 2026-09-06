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
