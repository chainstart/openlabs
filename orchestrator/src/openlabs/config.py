"""Workspace discovery and small TOML configuration loader."""

from __future__ import annotations

import os
import re
import shlex
import stat
import tomllib
from collections.abc import MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_ENVIRONMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_ZENODO_ENVIRONMENT_NAMES = frozenset(
    {
        "ZENODO_ACCESS_TOKEN",
        "ZENODO_SANDBOX_ACCESS_TOKEN",
        "ZENODO_ENVIRONMENT",
    }
)


# Project configs of the default (unnamed) instance, relative to
# ``<data>/workspaces``. A named instance (OPENLABS_INSTANCE) scans only
# ``<domain>/instances/<name>/projects/*/project.json``, which these globs never
# match, so an instance that does not know about named instances (an older
# orchestrator) never picks up a named instance's projects either.
DEFAULT_PROJECT_GLOBS = ("*/projects/*/project.json", "*/production/*/project.json")
INSTANCE_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,62}\Z")


@dataclass(frozen=True)
class WorkspacePaths:
    workspace: Path
    code: Path
    data: Path
    artifacts: Path
    database: Path
    database_file: Path
    # Named orchestrator instance sharing the data and artifact repositories
    # with others (None: the default instance, every path as before).
    instance: str | None = None
    # TOML settings file (None: <code>/config/openlabs.toml).
    config_file: Path | None = None
    # Job/result inbox root (None: <data>/inbox). Receipts name tasks of one
    # database, so a separate database always gets its own inbox.
    inbox_root: Path | None = None

    @property
    def settings_file(self) -> Path:
        return self.config_file or self.code / "config" / "openlabs.toml"

    @property
    def job_inbox(self) -> Path:
        return (self.inbox_root or self.data / "inbox") / "jobs"

    @property
    def result_inbox(self) -> Path:
        return (self.inbox_root or self.data / "inbox") / "results"

    @property
    def instance_artifacts(self) -> Path:
        """Artifact-store subtree for instance-private control state."""

        if self.instance is None:
            return self.artifacts
        return self.artifacts / "instances" / self.instance

    @property
    def attempt_workspaces(self) -> Path:
        # Every orchestrator reconciles all attempt workspaces under this root
        # against its own database, so instances must never share it.
        return self.instance_artifacts / "attempt-workspaces"

    @property
    def program_control(self) -> Path:
        return self.instance_artifacts / "program-control"

    def project_config_paths(self) -> list[Path]:
        root = self.data / "workspaces"
        if self.instance is None:
            globs: tuple[str, ...] = DEFAULT_PROJECT_GLOBS
        else:
            globs = (f"*/instances/{self.instance}/projects/*/project.json",)
        found: set[Path] = set()
        for pattern in globs:
            found.update(root.glob(pattern))
        return sorted(found)

    @property
    def scans_legacy_production_plans(self) -> bool:
        """Old math production plans belong to the default instance only."""

        return self.instance is None

    @property
    def receipt_archive(self) -> Path:
        return self.data / "ledger" / "receipts"

    def ensure_runtime_directories(self) -> None:
        for path in (
            self.data,
            self.artifacts,
            self.database,
            self.job_inbox,
            self.result_inbox,
            self.receipt_archive,
        ):
            path.mkdir(parents=True, exist_ok=True)


DEFAULT_TOPIC_LEDGER_PATH = "registry/topic-ledger.json"
DEFAULT_ASSET_INDEX_PATH = "registry/reusable-assets.json"


DEFAULT_GIT_MESSAGE = "{action}: {paper_id} v{version}"
GIT_MESSAGE_FIELDS = ("action", "paper_id", "version", "topic_id")


@dataclass(frozen=True)
class ProgramSettings:
    """Research-program controller switches (``[program]`` in openlabs.toml).

    ``config/openlabs.toml`` is the only source of these values; the orchestrator
    never reads ``registry/settings.yaml#research_portfolio.autonomy``, which only
    records the owner's decisions. Disabled by default: when ``enabled`` is false
    the controller neither reads nor writes the topic ledger and the tick behaves
    exactly as before.
    """

    enabled: bool = False
    max_active_topics: int = 5
    max_ready_unsubmitted: int = 6
    # Relative to the data repository root (``WorkspacePaths.data``).
    ledger_path: str = DEFAULT_TOPIC_LEDGER_PATH
    # A topic scout is scheduled only while fewer proposed (undecided) topics
    # than this wait for the admission gate.
    candidate_pool_low_water: int = 3
    # Minimum time between two scheduled topic scouts: program-wide while
    # ``max_concurrent_scouts`` is 1, per domain when scouts may run in parallel.
    scout_min_interval_hours: float = 12.0
    # Topic scouts in flight at once (at most one per domain). 1 keeps the
    # original single-scout front end.
    max_concurrent_scouts: int = 1
    # Cards one scout is expected to register; an in-flight scout counts this
    # much toward ``candidate_pool_low_water`` (replaced by this instance's own
    # average once a few scouts have finished).
    scout_expected_cards: float = 2.0
    # Admission reviews of one domain in flight at once (different batches of
    # its proposed topics); 1 keeps one review per domain.
    max_admissions_per_domain: int = 1
    # Admission reviews in flight across all domains; 0 means no global cap.
    max_concurrent_admissions: int = 0
    # When true, a new research workstream of a non-program project is only
    # activated if the topic ledger links it to an admitted topic.
    enforce_admission: bool = False
    # Reusable-asset index offered to scouts and the admission gate when present
    # (relative to the data repository root).
    asset_index_path: str = DEFAULT_ASSET_INDEX_PATH
    # Domains taking part in scout rotation, in preference order; empty means
    # every domain that has an active program project.
    domains: tuple[str, ...] = ()
    # Calendar limit from admission to review ``ready``; past it the topic gets
    # one direction decision (it is not frozen outright).
    max_days_from_admission_to_ready: float = 28.0
    # Hard per-topic Agent-time ceiling. A topic campaign's budget is the smaller
    # of this and its card's ``cost_estimate.agent_seconds``.
    topic_max_agent_seconds: int = 259_200
    # Per-topic number of direction-decision choices that keep a topic alive;
    # once used up only ``freeze`` is accepted.
    direction_limits: dict[str, int] = field(
        default_factory=lambda: dict(DEFAULT_DIRECTION_LIMITS)
    )
    # Deliver ready papers to the paper-management site automatically (without
    # a submission handler). False: ready papers are only queued.
    auto_handoff: bool = False
    # argv prefix of the paper-writing CLI used for delivery and handler
    # assignment (it owns the YAML/HTTP dependencies the orchestrator avoids).
    paper_writing_command: tuple[str, ...] = ("paper-writing",)
    # Delivery attempts per ready paper (one per tick) before it waits for a human.
    handoff_max_attempts: int = 3
    # Release pipeline (runs while auto_handoff is on): publish the Zenodo support
    # material (prepare/release) on the standing production authorization of
    # registry/settings.yaml#support_publication. False: stop before the first
    # Zenodo write and wait for a human.
    auto_release: bool = False
    # Failures per release stage, and writer rounds for formal fixes, before the
    # pipeline stops for a human.
    release_max_attempts: int = 3
    # Upper bound for one `review unified-run --delta-only` (formal stage included).
    release_review_timeout_seconds: int = 7_200
    # [program.git]: identity and message of the local data-repository commits the
    # pipeline makes (never pushed). Unset identity: the repository's own
    # user.name/user.email; neither set: the commit step fails and waits.
    git_user_name: str | None = None
    git_user_email: str | None = None
    git_message: str = DEFAULT_GIT_MESSAGE
    # Experiment locations this instance can serve (topic card
    # cost_estimate.compute_plan.locations). A card naming another location is
    # rejected at registration and admission. Inside a container ``wsl_math`` is
    # never available, whatever this says (the launcher refuses mathematics there).
    compute_locations: tuple[str, ...] = (
        "container_cpu", "container_gpu", "ailab", "wsl_math",
    )


DEFAULT_DIRECTION_LIMITS: dict[str, int] = {
    "targeted_core_analysis": 1,
    "retarget_or_short_format": 2,
}


DEFAULT_QUOTA_BACKOFF_MINUTES: tuple[int, ...] = (15, 30, 60, 120, 300)


@dataclass(frozen=True)
class BudgetSettings:
    """Provider-quota backoff and agent parallelism (``[budget]`` in openlabs.toml).

    The defaults keep scheduling unchanged until a real ``agent_quota`` failure is
    seen: ``max_parallel_agents=None`` means "same as ``max_worker_processes``"
    and no backoff state exists before the first quota hit.
    """

    max_parallel_agents: int | None = None
    quota_backoff_minutes: tuple[int, ...] = DEFAULT_QUOTA_BACKOFF_MINUTES
    quota_backoff_cap_minutes: int = 300
    restore_step: int = 1
    # Adaptive launch ceiling (off by default: the static ceiling applies). Each
    # tick moves the ceiling by at most ``adaptive_step`` toward what demand,
    # measured host load and the providers' quota pace allow; the static
    # ceiling and the quota-failure halving stay hard limits.
    adaptive_parallel: bool = False
    adaptive_step: int = 2
    # Measured container CPU/memory fraction (cgroup, page cache excluded)
    # above which the adaptive ceiling stops growing / shrinks.
    host_utilization_target: float = 0.8
    # Declared ailab load the agents are encouraged to fill (reported only;
    # the bridge does the admission).
    ailab_utilization_target: float = 0.9
    # Consecutive agent_quota results one task may defer before ordinary failure
    # handling takes over (guards against a misclassified real failure).
    quota_retry_limit: int = 8
    # Automatic retries of a needs_human/quarantined task whose last attempt
    # failed for an infrastructure reason before it blocks or freezes its topic.
    infrastructure_retry_limit: int = 3


TIERS = ("lead", "worker", "light")
# Pre-provider runner names. They request a tier, never a model family: with a
# ``[runners]`` table configured, a task carrying one of them is routed.
LEGACY_RUNNER_TIERS: dict[str, str] = {"frontier": "lead", "balanced": "worker", "cheap": "light"}

DEFAULT_TASK_TIERS: dict[str, str] = {
    # lead: portfolio planning, admission, direction and review decisions.
    "paper_review": "lead",
    "independent_review": "lead",
    "review": "lead",
    "portfolio_review": "lead",
    "portfolio_planning": "lead",
    "direction_decision": "lead",
    "topic_admission": "lead",
    "failure_diagnosis": "lead",
    "replan": "lead",
    # worker: code, experiments, analysis, writing.
    "research": "worker",
    "research_continue": "worker",
    "experiment_continue": "worker",
    "experiment": "worker",
    "analysis": "worker",
    "evidence_remediation": "worker",
    "candidate_maturation": "worker",
    # Topic scouting verifies data access and estimates cost, not just
    # literature screening, so it runs on the worker tier.
    "topic_scout": "worker",
    # Distilling a finished topic into reusable assets is bookkeeping-sized work.
    "topic_retrospective": "light",
    "paper_revision": "worker",
    "paper_readiness": "worker",
    "paper_writing": "worker",
    # light: cheapest model.
    "literature_scan": "light",
    "literature_search": "light",
    "literature_screening": "light",
    "data_download": "light",
    "data_curation": "light",
    "format_fix": "light",
    "figure_redraw": "light",
}
DEFAULT_ROLE_TIERS: dict[str, str] = {
    "reviewer": "lead",
    "researcher": "worker",
    "experimenter": "worker",
    "writer": "worker",
}
# decision > review > ordinary governs which reserves a task may spend.
DEFAULT_DECISION_TASK_TYPES: tuple[str, ...] = (
    "topic_admission",
    "direction_decision",
    "portfolio_review",
    "portfolio_planning",
)
DEFAULT_REVIEW_TASK_TYPES: tuple[str, ...] = ("paper_review", "independent_review", "review")
# Claim order while parallelism is limited (higher first); unlisted types use
# ``default_claim_rank`` (in-progress research).
DEFAULT_CLAIM_RANKS: dict[str, int] = {
    "paper_review": 3,
    "independent_review": 3,
    "review": 3,
    "direction_decision": 3,
    "portfolio_review": 3,
    "portfolio_planning": 3,
    "paper_revision": 3,
    "paper_readiness": 3,
    "paper_writing": 3,
    "topic_admission": 1,
    "topic_scout": 0,
    "literature_scan": 0,
    "literature_search": 0,
    "literature_screening": 0,
}
# Task types held while no lead runner can take a decision task.
DEFAULT_LEAD_SHORTAGE_PAUSED: tuple[str, ...] = (
    "topic_admission",
    "topic_scout",
    "literature_scan",
    "literature_search",
    "literature_screening",
)
# Measured 2026-11-11: claude-fable-5-2 calls report an extra window that
# cheaper-model calls do not.
DEFAULT_MODEL_WINDOWS: dict[str, tuple[str, ...]] = {
    "claude-fable-5-2": ("seven_day_overage_included",),
}
DEFAULT_PROTECTED_MODELS: tuple[str, ...] = ("claude-fable-5-2",)


@dataclass(frozen=True)
class RunnerSpec:
    """One ``[runners.<name>]`` entry; the argv still comes from the environment."""

    name: str
    provider: str
    tier: str
    model: str | None = None
    # Windows constraining only this runner, beyond the provider-wide ones.
    windows: tuple[str, ...] = ()
    # The provider's protected lead (Fable): its windows carry the decision
    # reserve and the review ceiling.
    protected: bool = False
    # Claude sub-agent tools (Task, Agent) for this runner's tasks; None: the
    # tier decides (lead yes, worker and light no).
    allow_subagents: bool | None = None

    @property
    def subagents_allowed(self) -> bool:
        return self.tier == "lead" if self.allow_subagents is None else self.allow_subagents


@dataclass(frozen=True)
class RoutingSettings:
    """Quota-aware runner selection (``[routing]`` in openlabs.toml).

    Only active when ``FactorySettings.runners`` is non-empty.
    """

    review_reserve: float = 0.15
    snapshot_stale_hours: float = 6.0
    unknown_headroom: float = 0.5
    pace_min_elapsed_fraction: float = 0.1
    lead_decision_reserve: float = 0.25
    lead_review_ceiling: float = 0.60
    escalate_to_lead_after_failures: int = 2
    legacy_runner_provider: str = "openai-codex"
    task_tiers: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_TASK_TIERS))
    role_tiers: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_ROLE_TIERS))
    decision_task_types: tuple[str, ...] = DEFAULT_DECISION_TASK_TYPES
    review_task_types: tuple[str, ...] = DEFAULT_REVIEW_TASK_TYPES
    claim_ranks: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_CLAIM_RANKS))
    default_claim_rank: int = 2
    lead_shortage_paused: tuple[str, ...] = DEFAULT_LEAD_SHORTAGE_PAUSED
    model_windows: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: dict(DEFAULT_MODEL_WINDOWS)
    )
    protected_models: tuple[str, ...] = DEFAULT_PROTECTED_MODELS
    # provider -> argv of a cheap probe whose stdout carries a quota reading.
    probe_commands: dict[str, tuple[str, ...]] = field(default_factory=dict)
    probe_idle_minutes: int = 360
    # Codex probe: read the newest session file here (None disables it).
    codex_sessions_dir: str | None = None
    # Share of each quota window to have used when it resets, reserves
    # included (0 disables the strategy: routing compares plain headroom).
    # Ordinary work stops at min(this, the reserve ceilings); routing then
    # spreads work by relative abundance, (ceiling - used) / time-to-reset
    # fraction, so a provider whose window resets soon with quota left is
    # used first and a freshly reset one is saved.
    utilization_target: float = 0.0
    # Minimum minutes between free refreshes (Codex session file) of a stale
    # reading; None: ``probe_idle_minutes`` like the paid probe.
    stale_refresh_minutes: int | None = None
    # A stale reading younger than this many hours is extrapolated instead of
    # treated as unknown: used + the window's average pace since then + this
    # instance's agent-hours on the provider x ``estimate_fraction_per_agent_hour``
    # (of a 7-day window; scaled for shorter windows). 0 disables it.
    stale_estimate_hours: float = 0.0
    estimate_fraction_per_agent_hour: float = 0.01


@dataclass(frozen=True)
class FactorySettings:
    # Resource admission is the primary concurrency control. This is only a
    # final process-count fuse for tiny or incorrectly declared tasks.
    max_worker_processes: int = 8
    lease_seconds: int = 600
    heartbeat_seconds: int = 30
    max_attempts: int = 3
    retry_backoff_seconds: int = 120
    auto_continue: bool = True
    # Lifetime limit for bounded campaigns; renewable per-epoch limit for
    # campaigns bound to an active production plan.
    max_auto_tasks_per_campaign: int = 24
    max_task_wall_seconds: int = 43_200
    max_campaign_agent_seconds: int = 86_400
    launch_jobs: bool = True
    archive_result_receipts: bool = True
    max_cpu_fraction_of_host: float = 0.75
    reserve_cpu_threads: int = 2
    reserve_memory_mib: int = 8_192
    reserve_scratch_mib: int = 65_536
    default_task_cpu_threads: int = 2
    default_task_memory_mib: int = 4_096
    default_task_scratch_mib: int = 4_096
    program: ProgramSettings = field(default_factory=ProgramSettings)
    budget: BudgetSettings = field(default_factory=BudgetSettings)
    runners: dict[str, RunnerSpec] = field(default_factory=dict)
    routing: RoutingSettings = field(default_factory=RoutingSettings)
    assets: AssetSettings = field(default_factory=lambda: AssetSettings())


@dataclass(frozen=True)
class AssetSettings:
    """Reusable-asset library (``[program.assets]`` in openlabs.toml).

    Both switches are off by default; with them off the tick, the packets and
    the task specs are exactly as before. Everything only acts while
    ``[program].enabled`` is true as well.
    """

    # Check-before-build: index summaries in scout/admission/direction/research
    # inputs, the admission reference check, usage counting and archiving.
    enabled: bool = False
    # One ``topic_retrospective`` task per topic entering ready_queue or frozen.
    retrospective_enabled: bool = False
    # Asset bodies, relative to the data repository (archive under ``<root>/archive``).
    root: str = "assets"
    summary_limit: int = 40
    summary_max_chars: int = 12_000
    maintenance_interval_hours: float = 24.0
    unused_archive_days: float = 120.0
    max_lessons: int = 200
    broken_reports_to_archive: int = 2
    # Code-repository globs scanned by ``program assets seed``.
    seed_paths: tuple[str, ...] = ("labs/*/tools", "packages/research-core")


def load_asset_settings(program_payload: Any) -> AssetSettings:
    program = program_payload if isinstance(program_payload, dict) else {}
    raw = program.get("assets")
    assets = raw if isinstance(raw, dict) else {}
    seed = assets.get("seed_paths")
    if seed is not None and (
        not isinstance(seed, list) or any(not isinstance(item, str) or not item.strip()
                                           for item in seed)
    ):
        raise ValueError("[program.assets].seed_paths must be an array of glob strings")
    return AssetSettings(
        enabled=assets.get("enabled", False) is True,
        retrospective_enabled=assets.get(
            "retrospective_enabled", program.get("retrospective_enabled", False)
        ) is True,
        root=_relative_data_path(assets.get("root"), "assets", "assets.root"),
        summary_limit=_positive_int(assets.get("summary_limit"), 40),
        summary_max_chars=_positive_int(assets.get("summary_max_chars"), 12_000),
        maintenance_interval_hours=_positive_float(
            assets.get("maintenance_interval_hours"), 24.0
        ),
        unused_archive_days=_positive_float(assets.get("unused_archive_days"), 120.0),
        max_lessons=_positive_int(assets.get("max_lessons"), 200),
        broken_reports_to_archive=_positive_int(assets.get("broken_reports_to_archive"), 2),
        seed_paths=tuple(item.strip() for item in seed) if seed is not None else (
            "labs/*/tools", "packages/research-core"
        ),
    )


def _default_workspace() -> Path:
    # .../openlabs/openlabs/orchestrator/src/openlabs/config.py -> outer workspace
    return Path(__file__).resolve().parents[4]


def _environment_file_value(raw: str) -> str:
    """Decode one systemd-style EnvironmentFile value without executing a shell."""

    value = raw.strip()
    if not value or value[:1] not in {"'", '"'}:
        return value
    try:
        parsed = shlex.split(value, comments=False, posix=True)
    except ValueError as exc:
        raise ValueError(f"invalid quoted environment value: {exc}") from exc
    if len(parsed) != 1:
        raise ValueError("quoted environment value must decode to one string")
    return parsed[0]


def _require_private_environment_file(path: Path) -> None:
    """Reject a credential file that another local account could replace/read."""

    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"private environment file must be a regular file: {path}")
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise ValueError(f"private environment file must be owned by the current user: {path}")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ValueError(f"private environment file must use owner-only permissions: {path}")


def load_local_environment(
    environment: MutableMapping[str, str] | None = None,
    *,
    config_home: str | Path | None = None,
) -> tuple[Path, ...]:
    """Load the same local Agent/proxy files for every OpenLabs CLI entrypoint.

    Existing process values always win. Files are parsed as data and are never
    sourced, so a local configuration line cannot execute shell code. The
    default Zenodo credential file is additionally owner/mode checked and may
    define only the three explicitly supported Zenodo variables.
    """

    target = environment if environment is not None else os.environ
    configured_home = config_home or target.get("XDG_CONFIG_HOME")
    root = (
        Path(configured_home).expanduser()
        if configured_home
        else Path(target.get("HOME") or Path.home()).expanduser() / ".config"
    )
    explicit = str(target.get("OPENLABS_ENV_FILES") or "").strip()
    if explicit:
        file_specs = tuple(
            (Path(item).expanduser(), None, False)
            for item in explicit.split(os.pathsep)
            if item.strip()
        )
    else:
        file_specs = (
            (root / "ara" / "zenodo.env", _ZENODO_ENVIRONMENT_NAMES, True),
            (root / "openlabs" / "env", None, False),
            (root / "environment.d" / "90-openlabs-proxy.conf", None, False),
        )
    loaded: list[Path] = []
    for path, allowed_names, require_private in file_specs:
        if not path.is_file():
            continue
        if require_private:
            _require_private_environment_file(path)
        for line_number, raw_line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            if "=" not in line:
                raise ValueError(f"{path}:{line_number}: expected NAME=VALUE")
            name, raw_value = line.split("=", 1)
            name = name.strip()
            if not _ENVIRONMENT_NAME.fullmatch(name):
                raise ValueError(f"{path}:{line_number}: invalid environment name {name!r}")
            if allowed_names is not None and name not in allowed_names:
                raise ValueError(
                    f"{path}:{line_number}: unsupported private environment name {name!r}"
                )
            target.setdefault(name, _environment_file_value(raw_value))
        loaded.append(path.resolve())
    return tuple(loaded)


INSTANCE_ENV = "OPENLABS_INSTANCE"
DATABASE_ROOT_ENV = "OPENLABS_DATABASE_ROOT"
CONFIG_FILE_ENV = "OPENLABS_CONFIG_FILE"


def workspace_paths(explicit: str | Path | None = None) -> WorkspacePaths:
    """Resolve the repositories; three variables select a separate instance.

    ``OPENLABS_DATABASE_ROOT`` (runtime database directory, with its own job and
    result inbox), ``OPENLABS_INSTANCE`` (project discovery, attempt workspaces
    and program control state under instance-specific paths) and
    ``OPENLABS_CONFIG_FILE`` (TOML settings). The data and artifact repositories
    stay shared. Unset, every path is exactly as before. The first two only come
    together: a named instance on the shared database would pause every campaign
    of the default instance, and a second database scanning the default
    instance's projects would run them twice.
    """

    configured = explicit or os.environ.get("OPENLABS_WORKSPACE")
    workspace = Path(configured).expanduser().resolve() if configured else _default_workspace()
    code = workspace / "openlabs"
    default_database = workspace / "openlabs-database"
    instance = str(os.environ.get(INSTANCE_ENV) or "").strip() or None
    raw_database = str(os.environ.get(DATABASE_ROOT_ENV) or "").strip()
    raw_config = str(os.environ.get(CONFIG_FILE_ENV) or "").strip()
    if instance is not None and not INSTANCE_NAME.fullmatch(instance):
        raise ValueError(
            f"{INSTANCE_ENV} must be lower-case letters, digits and '-': {instance!r}"
        )
    database = Path(raw_database).expanduser().resolve() if raw_database else default_database
    separate = database != default_database.resolve() if raw_database else False
    if instance is not None and not separate:
        raise ValueError(
            f"{INSTANCE_ENV}={instance} needs its own {DATABASE_ROOT_ENV} "
            f"(not {default_database})"
        )
    if separate and instance is None:
        raise ValueError(f"{DATABASE_ROOT_ENV} is set without {INSTANCE_ENV}")
    return WorkspacePaths(
        workspace=workspace,
        code=code,
        data=workspace / "openlabs-data",
        artifacts=workspace / "openlabs-artifacts",
        database=database,
        database_file=database / "live" / "factory.sqlite",
        instance=instance,
        config_file=Path(raw_config).expanduser().resolve() if raw_config else None,
        inbox_root=database / "inbox" if separate else None,
    )


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _nonnegative_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _fraction(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if 0 < parsed <= 1 else default


def _relative_data_path(value: Any, default: str, key: str) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    candidate = Path(text)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"[program].{key} must stay inside the data repository: {text!r}")
    return candidate.as_posix()


def _relative_ledger_path(value: Any) -> str:
    return _relative_data_path(value, DEFAULT_TOPIC_LEDGER_PATH, "ledger_path")


def _nonnegative_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _domain_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("[program].domains must be an array of domain names")
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if not text:
            raise ValueError("[program].domains entries must be non-empty strings")
        if text not in result:
            result.append(text)
    return tuple(result)


def load_program_settings(payload: Any) -> ProgramSettings:
    program = payload if isinstance(payload, dict) else {}
    return ProgramSettings(
        enabled=program.get("enabled", False) is True,
        max_active_topics=_positive_int(program.get("max_active_topics"), 5),
        max_ready_unsubmitted=_nonnegative_int(program.get("max_ready_unsubmitted"), 6),
        ledger_path=_relative_ledger_path(program.get("ledger_path")),
        candidate_pool_low_water=_nonnegative_int(program.get("candidate_pool_low_water"), 3),
        scout_min_interval_hours=_nonnegative_float(
            program.get("scout_min_interval_hours"), 12.0
        ),
        max_concurrent_scouts=_positive_int(program.get("max_concurrent_scouts"), 1),
        scout_expected_cards=_positive_float(program.get("scout_expected_cards"), 2.0),
        max_admissions_per_domain=_positive_int(program.get("max_admissions_per_domain"), 1),
        max_concurrent_admissions=_nonnegative_int(
            program.get("max_concurrent_admissions"), 0
        ),
        enforce_admission=program.get("enforce_admission", False) is True,
        asset_index_path=_relative_data_path(
            program.get("asset_index_path"), DEFAULT_ASSET_INDEX_PATH, "asset_index_path"
        ),
        domains=_domain_list(program.get("domains")),
        max_days_from_admission_to_ready=_positive_float(
            program.get("max_days_from_admission_to_ready"), 28.0
        ),
        topic_max_agent_seconds=_positive_int(program.get("topic_max_agent_seconds"), 259_200),
        direction_limits=_direction_limits(program.get("direction_limits")),
        auto_handoff=program.get("auto_handoff", False) is True,
        paper_writing_command=_command(program.get("paper_writing_command"), ("paper-writing",)),
        handoff_max_attempts=_positive_int(program.get("handoff_max_attempts"), 3),
        auto_release=program.get("auto_release", False) is True,
        release_max_attempts=_positive_int(program.get("release_max_attempts"), 3),
        release_review_timeout_seconds=_positive_int(
            program.get("release_review_timeout_seconds"), 7_200
        ),
        compute_locations=_compute_locations(program.get("compute_locations")),
        **_git_settings(program.get("git")),
    )


def _compute_locations(value: Any) -> tuple[str, ...]:
    default = ProgramSettings().compute_locations
    if value is None:
        return default
    if not isinstance(value, list) or any(item not in default for item in value):
        raise ValueError(
            "[program].compute_locations must be an array of " + ", ".join(default)
        )
    return tuple(dict.fromkeys(value))


def _git_settings(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("[program.git] must be a table")
    name = str(value.get("user_name") or "").strip() or None
    email = str(value.get("user_email") or "").strip() or None
    message = str(value.get("message") or "").strip() or DEFAULT_GIT_MESSAGE
    try:
        message.format(**{field: "x" for field in GIT_MESSAGE_FIELDS})
    except (KeyError, IndexError, ValueError) as exc:
        raise ValueError(
            f"[program.git].message may only use {{{'}, {'.join(GIT_MESSAGE_FIELDS)}}}"
        ) from exc
    return {"git_user_name": name, "git_user_email": email, "git_message": message}


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _direction_limits(value: Any) -> dict[str, int]:
    limits = dict(DEFAULT_DIRECTION_LIMITS)
    if value is None:
        return limits
    if not isinstance(value, dict):
        raise ValueError("[program].direction_limits must be a table")
    for key, raw in value.items():
        if key not in DEFAULT_DIRECTION_LIMITS:
            raise ValueError(f"[program].direction_limits has an unknown choice {key!r}")
        limits[key] = _nonnegative_int(raw, DEFAULT_DIRECTION_LIMITS[key])
    return limits


def _command(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        value = shlex.split(value)
    if not isinstance(value, (list, tuple)) or not value or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError("[program].paper_writing_command must be a non-empty argv array")
    return tuple(value)


def _minutes_sequence(value: Any) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)):
        return DEFAULT_QUOTA_BACKOFF_MINUTES
    parsed = tuple(_positive_int(item, 0) for item in value)
    if not parsed or any(item <= 0 for item in parsed):
        return DEFAULT_QUOTA_BACKOFF_MINUTES
    return parsed


def load_budget_settings(payload: Any) -> BudgetSettings:
    budget = payload if isinstance(payload, dict) else {}
    raw_parallel = budget.get("max_parallel_agents")
    return BudgetSettings(
        max_parallel_agents=(
            None if raw_parallel is None else _positive_int(raw_parallel, 0) or None
        ),
        quota_backoff_minutes=_minutes_sequence(budget.get("quota_backoff_minutes")),
        quota_backoff_cap_minutes=_positive_int(budget.get("quota_backoff_cap_minutes"), 300),
        restore_step=_positive_int(budget.get("restore_step"), 1),
        quota_retry_limit=_positive_int(budget.get("quota_retry_limit"), 8),
        infrastructure_retry_limit=_nonnegative_int(
            budget.get("infrastructure_retry_limit"), 3
        ),
        adaptive_parallel=budget.get("adaptive_parallel", False) is True,
        adaptive_step=_positive_int(budget.get("adaptive_step"), 2),
        host_utilization_target=_fraction(budget.get("host_utilization_target"), 0.8),
        ailab_utilization_target=_fraction(budget.get("ailab_utilization_target"), 0.9),
    )


def _unit_fraction(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if 0 <= parsed <= 1 else default


def _string_tuple(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return default
    return tuple(str(item).strip() for item in value if str(item).strip())


def load_runner_specs(payload: Any) -> dict[str, RunnerSpec]:
    """Parse ``[runners.<name>]``; tier and provider are required per entry."""

    if not isinstance(payload, dict):
        return {}
    specs: dict[str, RunnerSpec] = {}
    for name, raw in payload.items():
        if not isinstance(raw, dict):
            continue
        runner = str(name).strip()
        provider = str(raw.get("provider") or "").strip()
        tier = str(raw.get("tier") or "").strip()
        if not runner or not provider:
            raise ValueError(f"[runners.{name}] needs a provider")
        if tier not in TIERS:
            raise ValueError(f"[runners.{name}].tier must be one of {TIERS}")
        model = str(raw.get("model") or "").strip() or None
        specs[runner] = RunnerSpec(
            name=runner,
            provider=provider,
            tier=tier,
            model=model,
            # Unset windows/protected take [routing] model defaults (apply_model_defaults).
            windows=_string_tuple(raw.get("windows"), ()),
            protected=raw.get("protected") is True,
            allow_subagents=_optional_bool(raw.get("allow_subagents"),
                                           f"[runners.{name}].allow_subagents"),
        )
    return specs


def _optional_bool(value: Any, label: str) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise ValueError(f"{label} must be true or false")


def load_routing_settings(payload: Any) -> RoutingSettings:
    routing = payload if isinstance(payload, dict) else {}
    defaults = RoutingSettings()
    task_tiers = dict(defaults.task_tiers)
    if isinstance(routing.get("task_tiers"), dict):
        for key, value in routing["task_tiers"].items():
            if str(value) not in TIERS:
                raise ValueError(f"[routing.task_tiers].{key} must be one of {TIERS}")
            task_tiers[str(key)] = str(value)
    role_tiers = dict(defaults.role_tiers)
    if isinstance(routing.get("role_tiers"), dict):
        for key, value in routing["role_tiers"].items():
            if str(value) in TIERS:
                role_tiers[str(key)] = str(value)
    claim_ranks = dict(defaults.claim_ranks)
    if isinstance(routing.get("claim_ranks"), dict):
        for key, value in routing["claim_ranks"].items():
            try:
                claim_ranks[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
    model_windows = dict(defaults.model_windows)
    if isinstance(routing.get("model_windows"), dict):
        for key, value in routing["model_windows"].items():
            model_windows[str(key)] = _string_tuple(value, ())
    protected_models = _string_tuple(routing.get("protected_models"), defaults.protected_models)
    probe_commands: dict[str, tuple[str, ...]] = {}
    if isinstance(routing.get("probe_commands"), dict):
        for key, value in routing["probe_commands"].items():
            command = _string_tuple(value, ())
            if not command:
                continue
            # A one-word Fable call costs ~70x the cheapest model; Fable-only
            # windows are read from real Fable task receipts instead.
            if any(token in protected_models for token in command) or any(
                token.split("=", 1)[-1] in protected_models
                for token in command
                if token.startswith("--model=")
            ):
                raise ValueError(f"[routing.probe_commands].{key} must not use a protected model")
            probe_commands[str(key)] = command
    try:
        stale = float(routing.get("snapshot_stale_hours", defaults.snapshot_stale_hours))
    except (TypeError, ValueError):
        stale = defaults.snapshot_stale_hours
    return RoutingSettings(
        review_reserve=_unit_fraction(routing.get("review_reserve"), defaults.review_reserve),
        snapshot_stale_hours=stale if stale > 0 else defaults.snapshot_stale_hours,
        unknown_headroom=_unit_fraction(
            routing.get("unknown_headroom"), defaults.unknown_headroom
        ),
        pace_min_elapsed_fraction=_unit_fraction(
            routing.get("pace_min_elapsed_fraction"), defaults.pace_min_elapsed_fraction
        ),
        lead_decision_reserve=_unit_fraction(
            routing.get("lead_decision_reserve"), defaults.lead_decision_reserve
        ),
        lead_review_ceiling=_unit_fraction(
            routing.get("lead_review_ceiling"), defaults.lead_review_ceiling
        ),
        escalate_to_lead_after_failures=_nonnegative_int(
            routing.get("escalate_to_lead_after_failures"),
            defaults.escalate_to_lead_after_failures,
        ),
        legacy_runner_provider=str(
            routing.get("legacy_runner_provider") or defaults.legacy_runner_provider
        ),
        task_tiers=task_tiers,
        role_tiers=role_tiers,
        decision_task_types=_string_tuple(
            routing.get("decision_task_types"), defaults.decision_task_types
        ),
        review_task_types=_string_tuple(
            routing.get("review_task_types"), defaults.review_task_types
        ),
        claim_ranks=claim_ranks,
        default_claim_rank=int(routing.get("default_claim_rank", defaults.default_claim_rank)),
        lead_shortage_paused=_string_tuple(
            routing.get("lead_shortage_paused"), defaults.lead_shortage_paused
        ),
        model_windows=model_windows,
        protected_models=protected_models,
        probe_commands=probe_commands,
        probe_idle_minutes=_positive_int(
            routing.get("probe_idle_minutes"), defaults.probe_idle_minutes
        ),
        codex_sessions_dir=str(routing.get("codex_sessions_dir") or "").strip() or None,
        utilization_target=_unit_fraction(
            routing.get("utilization_target"), defaults.utilization_target
        ),
        stale_refresh_minutes=(
            None if routing.get("stale_refresh_minutes") is None
            else _positive_int(routing.get("stale_refresh_minutes"), defaults.probe_idle_minutes)
        ),
        stale_estimate_hours=_nonnegative_float(
            routing.get("stale_estimate_hours"), defaults.stale_estimate_hours
        ),
        estimate_fraction_per_agent_hour=_unit_fraction(
            routing.get("estimate_fraction_per_agent_hour"),
            defaults.estimate_fraction_per_agent_hour,
        ),
    )


def apply_model_defaults(
    runners: dict[str, RunnerSpec],
    routing: RoutingSettings,
    raw_runners: Any,
) -> dict[str, RunnerSpec]:
    """Apply ``[routing].model_windows``/``protected_models`` to runners that did not override."""

    raw = raw_runners if isinstance(raw_runners, dict) else {}
    resolved: dict[str, RunnerSpec] = {}
    for name, spec in runners.items():
        entry = raw.get(name) if isinstance(raw.get(name), dict) else {}
        windows = spec.windows
        protected = spec.protected
        if "windows" not in entry:
            windows = routing.model_windows.get(spec.model or "", ())
        if "protected" not in entry:
            protected = bool(spec.model and spec.model in routing.protected_models)
        resolved[name] = RunnerSpec(
            name=spec.name,
            provider=spec.provider,
            tier=spec.tier,
            model=spec.model,
            windows=windows,
            protected=protected,
            allow_subagents=spec.allow_subagents,
        )
    return resolved


def load_settings(paths: WorkspacePaths) -> FactorySettings:
    path = paths.settings_file
    payload: dict[str, Any] = {}
    if paths.config_file is not None and not path.is_file():
        raise FileNotFoundError(f"{CONFIG_FILE_ENV} names a missing file: {path}")
    if path.is_file():
        with path.open("rb") as handle:
            payload = tomllib.load(handle)
    factory = payload.get("factory") if isinstance(payload.get("factory"), dict) else {}
    resources = payload.get("resources") if isinstance(payload.get("resources"), dict) else {}
    retention = payload.get("retention") if isinstance(payload.get("retention"), dict) else {}
    runners = load_runner_specs(payload.get("runners"))
    routing = load_routing_settings(payload.get("routing"))
    runners = apply_model_defaults(runners, routing, payload.get("runners"))
    return FactorySettings(
        max_worker_processes=_positive_int(
            factory.get("max_worker_processes", factory.get("max_concurrent_jobs")), 8
        ),
        lease_seconds=_positive_int(factory.get("lease_seconds"), 600),
        heartbeat_seconds=_positive_int(factory.get("heartbeat_seconds"), 30),
        max_attempts=_positive_int(factory.get("max_attempts"), 3),
        retry_backoff_seconds=_positive_int(factory.get("retry_backoff_seconds"), 120),
        auto_continue=bool(factory.get("auto_continue", True)),
        max_auto_tasks_per_campaign=_positive_int(
            factory.get(
                "max_auto_tasks_per_epoch",
                factory.get("max_auto_tasks_per_campaign"),
            ),
            24,
        ),
        max_task_wall_seconds=_positive_int(factory.get("max_task_wall_seconds"), 43_200),
        max_campaign_agent_seconds=_positive_int(factory.get("max_campaign_agent_seconds"), 86_400),
        launch_jobs=bool(factory.get("launch_jobs", True)),
        archive_result_receipts=bool(retention.get("archive_result_receipts", True)),
        max_cpu_fraction_of_host=_fraction(resources.get("max_cpu_fraction_of_host"), 0.75),
        reserve_cpu_threads=_nonnegative_int(resources.get("reserve_cpu_threads"), 2),
        reserve_memory_mib=_nonnegative_int(resources.get("reserve_memory_mib"), 8_192),
        reserve_scratch_mib=_nonnegative_int(resources.get("reserve_scratch_mib"), 65_536),
        default_task_cpu_threads=_positive_int(resources.get("default_task_cpu_threads"), 2),
        default_task_memory_mib=_positive_int(resources.get("default_task_memory_mib"), 4_096),
        default_task_scratch_mib=_positive_int(resources.get("default_task_scratch_mib"), 4_096),
        program=load_program_settings(payload.get("program")),
        assets=load_asset_settings(payload.get("program")),
        budget=load_budget_settings(payload.get("budget")),
        runners=runners,
        routing=routing,
    )
