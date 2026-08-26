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
