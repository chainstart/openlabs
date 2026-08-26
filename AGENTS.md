# OpenLabs resource policy

All long-running or potentially memory- or CPU-intensive work started from this
repository must run inside the repository aggregate resource guard.

- Launch interactive Codex research with `bin/openlabs-codex`.
- Launch scripts, Python searches, solvers, package synchronization and other
  heavy commands with `bin/openlabs-resource-guard -- <command> [args...]`.
- Do not bypass the guard for background jobs, resumed campaigns or child
  processes. Nested wrapper calls intentionally reuse the shared slice.
- The aggregate limit is 75% of visible logical CPUs, 30 GiB memory soft, 34
  GiB memory hard, 4 GiB swap and 512 tasks.
- If the guard or its systemd slice is unavailable, fail closed and repair it
  instead of running heavy work unbounded.

See `RESOURCE_GUARD.md` for installation, monitoring and recovery commands.
