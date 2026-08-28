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

# Paper target policy

For every journal manuscript beyond its basic draft, use the domain-specific target policy in
`workflows/paper/skills/profiles.yaml` and the active data repository's
`registry/settings.yaml`.

- Select only a configured 2026 XinRui Tier 1 or Tier 2 journal with an official publication route
  carrying no mandatory author fee. Optional paid open access is acceptable only when a fee-free
  subscription route remains available.
- Record dated official sources for scope, article type, author fees, and formatting, together with
  a dated ranking source. Apply the verified venue format to the canonical manuscript; a side
  candidate alone is insufficient.
- If the requested target is specifically a Chinese Academy of Sciences major-category Zone 1
  journal, verify that partition directly and record the dated source. JCR Q1, a subject-category
  quartile, and a XinRui tier must not be reported as the CAS major-category partition.
- Journal selection and a passing paper gate never authorize submission, spending, or a journal
  event.
