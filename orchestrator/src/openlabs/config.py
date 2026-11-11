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


@dataclass(frozen=True)
class WorkspacePaths:
    workspace: Path
    code: Path
    data: Path
    artifacts: Path
    database: Path
    database_file: Path

    @property
    def job_inbox(self) -> Path:
        return self.data / "inbox" / "jobs"

    @property
    def result_inbox(self) -> Path:
        return self.data / "inbox" / "results"

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


@dataclass(frozen=True)
class ProgramSettings:
    """Research-program controller switches (``[program]`` in openlabs.toml).

    Disabled by default: when ``enabled`` is false the controller neither reads nor
    writes the topic ledger and the tick behaves exactly as before.
    """

    enabled: bool = False
    max_active_topics: int = 5
    max_ready_unsubmitted: int = 6
    # Relative to the data repository root (``WorkspacePaths.data``).
    ledger_path: str = DEFAULT_TOPIC_LEDGER_PATH
    # A topic scout is scheduled only while fewer proposed (undecided) topics
    # than this wait for the admission gate.
    candidate_pool_low_water: int = 3
    # Minimum time between two scheduled topic scouts (whole program).
    scout_min_interval_hours: float = 12.0
    # When true, a new research workstream of a non-program project is only
    # activated if the topic ledger links it to an admitted topic.
    enforce_admission: bool = False
    # Reusable-asset index offered to scouts and the admission gate when present
    # (relative to the data repository root).
    asset_index_path: str = DEFAULT_ASSET_INDEX_PATH
    # Domains taking part in scout rotation, in preference order; empty means
    # every domain that has an active program project.
    domains: tuple[str, ...] = ()


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


def workspace_paths(explicit: str | Path | None = None) -> WorkspacePaths:
    configured = explicit or os.environ.get("OPENLABS_WORKSPACE")
    workspace = Path(configured).expanduser().resolve() if configured else _default_workspace()
    code = workspace / "openlabs"
    return WorkspacePaths(
        workspace=workspace,
        code=code,
        data=workspace / "openlabs-data",
        artifacts=workspace / "openlabs-artifacts",
        database=workspace / "openlabs-database",
        database_file=workspace / "openlabs-database" / "live" / "factory.sqlite",
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
        enforce_admission=program.get("enforce_admission", False) is True,
        asset_index_path=_relative_data_path(
            program.get("asset_index_path"), DEFAULT_ASSET_INDEX_PATH, "asset_index_path"
        ),
        domains=_domain_list(program.get("domains")),
    )


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
        )
    return specs


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
        )
    return resolved


def load_settings(paths: WorkspacePaths) -> FactorySettings:
    path = paths.code / "config" / "openlabs.toml"
    payload: dict[str, Any] = {}
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
        budget=load_budget_settings(payload.get("budget")),
        runners=runners,
        routing=routing,
    )
