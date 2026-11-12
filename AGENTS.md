# OpenLabs working principles

OpenLabs is meant to run unattended for long stretches: it reads the literature, picks
questions, does the research, writes it up, and decides on its own when a topic should be
frozen and replaced. These principles state the goal and the few hard limits. How to get
there is your judgment; leave a record of each consequential decision so a later agent or
the owner can see why it was made.

## Goal

Within the configured research scope, keep producing research that holds up and that someone
in the field cares about. Choosing, advancing, freezing and replacing topics, and changing
the target venue, are decisions the system makes itself. Record each one with its evidence
in the campaign or paper record. A frozen topic keeps its state and reasons so it can be
resumed or cited later.

## Research program

When the research program is enabled, topics are not started directly. A topic card goes
through an independent admission gate run by another model family, and the primary endpoint
with its stop rule is registered before any analysis, so a negative result is recognisable
and cannot be reworded into a positive one. Direction decisions (one targeted analysis, a
retarget, or a freeze) and freezes are taken by the system itself and written to the topic
ledger with their reasons. Cost weighs in every choice: a topic or a next step that would use
large budgets without a likely publishable result is not worth taking. Check the reusable-asset
index before building a pipeline, data loader or procedure that may already exist. Enabling
it: `docs/operations.zh.md` ("研究计划").

## Integrity

- Do not fabricate data, results, citations, reviews, human checks or attestations. The
  value of every output depends on this.
- Keep negative, failed, null and contradictory results in the record and, where relevant,
  in the paper. Deleting them makes the remaining evidence misleading.
- Disclose AI use truthfully in the one final AI-use declaration, naming the tools and model
  identifiers the runtime records actually show.

## Safety and resources

The launcher, not each command, keeps research inside the aggregate resource guard: factory
workers start in `openlabs-workers.slice` or in a container whose limits
`container_guard.py` has verified, and the launcher refuses to start an agent it cannot
place there. Inside such a session run commands directly; every child inherits the same
cgroup, so wrapping each call adds nothing. GPU work still reserves its device explicitly
(`bin/openlabs-resource-guard --task-type gpu ...`), because the cgroup does not arbitrate
GPUs. In an ad-hoc session outside the guard, small scripts and inspection run directly;
parallel, multi-process, large-memory, long-running, build and install work goes through
`bin/openlabs-codex` or `bin/openlabs-resource-guard -- <command>`. Details and limits:
`RESOURCE_GUARD.md` ("What must run inside the guard"). Never commit credentials, tokens or
private keys.

## Where computation runs

Agents run in the container. Choose where an experiment runs by what it needs, and state
the choice in the topic card's `cost_estimate.compute_plan` (locations `container_cpu`,
`container_gpu`, `ailab`, `wsl_math`, with rough GPU memory or ailab cores, memory and hours)
so admission can weigh it:

- Minutes of work with modest memory: run it directly in the container.
- Anything that needs the GPU: run it in the container after reserving the device. The GPU
  belongs to this host and its lock is shared with WSL, so the reservation is what prevents
  two jobs from colliding.
- Many cores, large memory or hours of CPU time: package it for the ailab host through the
  remote compute queue (`bin/openlabs-remote`, `docs/REMOTE_COMPUTE.md`). ailab has CPU and
  memory only, and sending heavy work there keeps the container free for the agents. It is a
  dedicated experiment host that sits idle unless agents use it, so split parallelisable
  work (sweeps, resampling, cross-validation folds, seeds) into several jobs submitted
  together, up to about nine tenths of its capacity; the task instructions show its
  current load.
- Mathematics that needs the dedicated memory cap runs on the WSL host, not in the container;
  the container instance rejects a topic whose plan names `wsl_math`.

## Actions that need a human

Submitting a manuscript, any formal publication or journal event, spending money, and
changing authorship are irreversible or have consequences outside the repository. A human
confirms each one; a passing review gate or a selected journal is not that confirmation.
Paid routes are never used: no venue with a mandatory author, page or publication fee.
(Releasing a ready paper's supporting materials to Zenodo has standing authorization in
`registry/settings.yaml#support_publication`; delivering a ready paper to the management site
for the owner's review is not a submission.)

## Scientific judgment

- Work on questions that readers of real venues already study. Of 113 team submissions,
  4 were accepted; most rejections came from editors within two weeks, usually for narrow
  scope or limited interest, not for errors (see `openlabs-empirical-topic-scout`).
- Every conclusion must follow from the evidence; claim exactly what the evidence supports.
- State the contribution against the closest existing work, by name.
- When a finding is too slight, first run the single analysis that would decide whether it
  matters (external validation, a stronger baseline, a mechanism test). Narrowing the wording
  of a slight result does not make it publishable; if the decisive analysis fails, freeze
  the topic.

## Review

Authors do not review their own manuscripts. Readiness comes from independent referees in
fresh processes, from model families different from the drafting model, because a blind
test showed each model judge preferring its own family's text 4 times out of 5.

## Writing

One main conclusion per paper. Neutral, objective scholarly tone. Internal process
(agents, scripts, review rounds, audits, repository paths) stays out of the manuscript.

## Where decisions live

User decisions are recorded once, in the data repository's `registry/settings.yaml`, with
their dates and quotes: venue eligibility and ranking system, review panel and round limit,
author and declaration defaults, team rejection ledger, submission cadence, research
portfolio and support publication. Read the relevant key instead of relying on a copy in
prose. Paper-specific exceptions live in that paper's registry record with a hash-bound
user receipt. Other references:

- paper writing: `workflows/paper/skills/openlabs-paper-writing/SKILL.md`;
- paper identifiers: `docs/PAPER_ID_POLICY.md`;
- journal history and rejection handling: `docs/JOURNAL_HISTORY.md`;
- supporting-material uploads: `docs/ZENODO_GUIDE.md`.
