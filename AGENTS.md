# OpenLabs mandatory resource policy

Every process that can plausibly consume substantial memory or CPU must run
inside the repository aggregate resource guard. This is a hard requirement,
not a recommendation. When resource use is uncertain, treat the command as
resource-intensive and use the guard.

- Launch interactive Codex research with `bin/openlabs-codex` so every child
  process inherits the guard.
- If the current Codex or shell is not already inside `openlabs-workers.slice`,
  launch each potentially resource-intensive command with
  `bin/openlabs-resource-guard -- <command> [args...]`.
- Always guard interpreters and runtimes that execute repository or generated
  code, including Python, R, Julia, Java, Node.js, Bun and Deno. Inline scripts,
  one-off probes and commands expected to use only a small input are not exempt.
- Always guard tests, benchmarks, fuzzers, solvers, symbolic or exact
  computation, model inference or training, compilers, linkers, documentation
  and PDF builds, package installation or synchronization, browser or Electron
  automation, container builds, archive or dataset processing, and nested
  Codex invocations.
- Put the whole pipeline or command group inside one guard. For example, use
  `bin/openlabs-resource-guard -- bash -lc '<producer> | <consumer>'`; guarding
  only one stage is insufficient.
- Background jobs, asynchronous exec sessions, `nohup`, `tmux`, `timeout`,
  resumed campaigns, workers, subagents and child processes must not bypass the
  guard. Nested wrapper calls intentionally reuse the shared slice.
- Only commands whose memory use is inherently small and bounded may run
  directly, such as `pwd`, `ls`, `find` over a narrowly bounded tree, `rg`,
  `sed`, `head`, `tail`, `stat`, `git status`, `git diff`, `systemctl status`
  and bounded `journalctl` queries. If a command reads an unbounded file/tree,
  loads project code, or can fan out into child processes, it is not exempt.
- Before relying on inherited protection, verify `/proc/self/cgroup` contains
  `openlabs-workers.slice`. Do not infer protection merely because another
  guarded job is running elsewhere.
- The aggregate limit is 75% of visible logical CPUs, 30 GiB memory soft, 34
  GiB memory hard, 4 GiB swap and 512 tasks.
- Keep GPU available. Every model inference/training or other CUDA workload
  must explicitly reserve its GPU with
  `bin/openlabs-resource-guard --gpu-memory-mib 8192 --gpu-device 0 -- <command>`
  (choose a smaller budget when sufficient). Only one declared GPU job may run
  on each device at a time; CPU research can continue in parallel. Call this
  wrapper even inside an inherited worker cgroup to acquire the GPU reservation.
- GPU admission and supervision preserve at least 25% VRAM and 2048 MiB free,
  enforce an 85 C temperature stop, and fail closed on telemetry loss. PyTorch
  receives a native allocator cap with 768 MiB of each budget reserved for
  contexts/other allocations. Do not unset/override the allocator cap, launch
  parallel GPU children inside one lease, or bypass the supervisor. For another
  framework, configure its allocator budget explicitly before model allocation.
  Global sampling is a backstop, not a kernel-level VRAM or utilization quota.
- Ordinary guarded commands and factory workers also receive GPU monitoring
  and a PyTorch cap without hiding CUDA. This does not replace explicit GPU
  admission for GPU workloads. Never solve GPU pressure by disabling CUDA or
  increasing ceilings; reduce batch/context/model memory, offload, or queue work.
- If the guard, systemd user manager or cgroup v2 controllers are unavailable,
  fail closed: do not start the command unbounded. Repair or install the guard
  first.

See `RESOURCE_GUARD.md` for installation, monitoring and recovery commands.

# Paper target policy

For every journal manuscript beyond its basic draft, use the domain-specific target policy in
`workflows/paper/skills/profiles.yaml` and the active data repository's
`registry/settings.yaml`.

- Select only a journal verified as Zone 1 or Zone 2 in the **2025 edition of the Chinese Academy
  of Sciences Journal Ranking Table, upgraded edition, major-category partition**. This 2025 CAS
  major-category table is the repository's fixed journal-classification baseline until a human
  explicitly changes the policy. JCR/WOS/JCI quartiles, CAS subject-category partitions, and
  XinRui tiers are different systems and must never be substituted or relabeled as this value.
- Record the numeric major-category zone in the compatibility field `target_journal_tier`, plus
  `target_journal_ranking_year: 2025`, `target_journal_ranking_scope: major_category`, the CAS
  major-category name, a dated classification source, and the check date. If the 2025 CAS value
  cannot be verified, leave the target blocked rather than infer it from another ranking.
- Missing local ranking metadata is a lookup task, not a reason to stop at `unverified`: query the
  2025 CAS major-category record from the official service or an auditable public index, verify the
  exact title/ISSN, and write the zone, category, source, and check date back into local metadata.
  Use `unverified` only when those searches genuinely fail or conflict, and record the conflict.
- Require an official publication route carrying no mandatory author fee. Optional paid open
  access is acceptable only when a fee-free subscription route remains available. Record dated
  official sources for scope, article type, author fees, and formatting, and apply the verified
  venue format to the canonical manuscript; a side candidate alone is insufficient.
- Journal selection and a passing paper gate never authorize submission, spending, or a journal
  event.

# Paper identifier policy

For every domain, follow `docs/PAPER_ID_POLICY.md` when creating a paper or naming a public
manuscript file.

- New `paper_id` values use `YYYYMMDD-domain-subdomain-keywords`; the date, domain and subdomain
  must match the registry record.
- Repository-local question, task, round and workstream labels such as `tp-042` are provenance,
  not paper identifiers or public filenames.
- Keep an established `paper_id` immutable. Use the domain-scoped `display_id` for reader-facing
  names and `<display_id>-v<MAJOR.MINOR.PATCH>.pdf` for exported manuscripts.
