"""Workspace discovery and small TOML configuration loader."""

from __future__ import annotations

import os
import re
import shlex
import stat
import tomllib
from collections.abc import MutableMapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .download_window import ProxyDownloadWindow, load_window

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
DEFAULT_RESEARCH_LINES_PATH = "registry/research-lines.yaml"


DEFAULT_GIT_MESSAGE = "{action}: {paper_id} v{version}"
GIT_MESSAGE_FIELDS = ("action", "paper_id", "version", "topic_id")
SUPPORT_RELEASE_MODES = ("zenodo", "none")
DEFAULT_SUPPORT_NONE_REASON = (
    "No Zenodo record or other public deposit is made for this version ([program] "
    "support_release = \"none\"). The registered support source files stay in the OpenLabs data "
    "repository; whether they are provided as journal supplementary material is decided at "
    "submission."
)


def _support_release(value: Any) -> str:
    if value is None:
        return "zenodo"
    text = str(value).strip().lower()
    if text not in SUPPORT_RELEASE_MODES:
        raise ValueError(f"[program].support_release must be one of {list(SUPPORT_RELEASE_MODES)}")
    return text


def _nonempty_text(value: Any, default: str, name: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"[program].{name} must be a non-empty string")
    return value.strip()


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
    # Proposed cards needed per line. Unbound legacy projects share their own pool.
    candidate_pool_low_water: int = 3
    # Default interval per research line (domain fallback for projects without a line).
    scout_min_interval_hours: float = 12.0
    line_scout_min_interval_hours: dict[str, float] = field(default_factory=dict)
    # Program-wide worker ceiling. At most one scout per research line.
    max_concurrent_scouts: int = 1
    # Expected cards per legacy scout for the shared pool, until enough finish
    # to use this instance's measured average.
    scout_expected_cards: float = 2.0
    # Empty-draw backoff (2026-11-16): after the n-th consecutive scout of a line
    # that registered no usable card while the line's candidate supply (queue files,
    # line entry, held-entry releases, its ledger topics) is unchanged, the next
    # scout of that line waits scout_empty_backoff_hours[n-1] (last value repeats).
    # A supply change releases the backoff at once. After scout_exhausted_after
    # such draws the line is reported as candidates_exhausted and no longer scouted
    # until its supply changes (0 = never mark exhausted).
    scout_empty_backoff_hours: tuple[float, ...] = (1.0, 6.0, 24.0)
    scout_exhausted_after: int = 4
    # Admission batches in flight per line. TOML accepts the former domain key as an alias.
    max_admissions_per_line: int = 1
    # Admission reviews in flight across all lines; 0 means no global cap.
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
    # Research lines taking part in scout rotation, in preference order. When set,
    # only program projects whose ``research_line`` is listed are scouted (rotation,
    # per-line interval and load are kept per line); projects without a line keep
    # their admissions and campaigns but get no new scouts. Empty: use the legacy
    # host-domain filter, with rotation still keyed by line when one is present.
    research_lines: tuple[str, ...] = ()
    # Direction file (relative to the data repository root): line definitions read
    # by scouts and the admission gate, and each line's environment status.
    research_lines_path: str = DEFAULT_RESEARCH_LINES_PATH
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
    # Site submitter reconciliation (2026-11-25, B1): every tick, a pre-submission paper on the
    # management site that is not submittable loses its active submitter, a submittable one gets
    # its recorded submitter (else the second author), and a paper under a manual-assignment
    # hold is left alone (paper_writing.site_assignments). Independent of ``auto_handoff``:
    # holding deliveries back must not hold back taking a submitter off a not-ready paper.
    site_assignment_sync: bool = True
    # argv prefix of the paper-writing CLI used for delivery and handler
    # assignment (it owns the YAML/HTTP dependencies the orchestrator avoids).
    paper_writing_command: tuple[str, ...] = ("paper-writing",)
    # Delivery attempts per ready paper (one per tick) before it waits for a human.
    handoff_max_attempts: int = 3
    # Credentials file of the release pipeline (2026-11-20): NAME=VALUE lines read by the
    # tick for the delivery (ARA_PAPER_MANAGE_API_URL/_KEY) and Zenodo (ZENODO_ACCESS_TOKEN)
    # child processes only -- never exported into the tick, so research seats (which inherit
    # the tick's environment) do not see them. Must be a regular file of this user, mode
    # 0600 or stricter (otherwise ignored, and the pipeline waits for credentials). The
    # process environment still wins over the file. None: environment only.
    credentials_file: str | None = None
    # Ledger reconciliation (``program reconcile``, program_reconcile.py) and the tick's
    # next-step check: a topic or task untouched this many days counts as stale (a parked
    # legacy topic is archived, an orphaned needs_human record closed, an admitted card
    # never materialized is reported without a next step).
    reconcile_stale_days: float = 5.0
    # A held topic (research_state ``paused``, openlabs.holds.topic_hold) is never archived by
    # reconcile; it is reported, as expired once its ``until`` passed. The former
    # ``reconcile_operator_pause_days`` knob (2026-11-24, P01) was retired on 2026-11-25 (B3)
    # and is ignored when an instance file still sets it.
    # Release pipeline (runs while auto_handoff is on): publish the Zenodo support
    # material (prepare/release) on the standing production authorization of
    # registry/settings.yaml#support_publication. False: stop before the first
    # Zenodo write and wait for a human.
    auto_release: bool = False
    # How a ready paper's support material is released before delivery. "zenodo":
    # the Zenodo steps above. "none": no Zenodo (or other public) record is ever
    # created; a paper whose support record is still only planned gets
    # support.publication.mode not_required with ``support_none_reason`` (refused,
    # and the pipeline waits for the owner, when a record exists or the
    # manuscript's data-availability section names a Zenodo deposit).
    support_release: str = "zenodo"
    support_none_reason: str = DEFAULT_SUPPORT_NONE_REASON
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
    # Owner mode (owner decision 2026-11-14): after admission one owner agent
    # session carries a topic to a reviewed manuscript or a freeze. "off" keeps
    # the staged post-admission flow; "all" applies it to every program topic; a
    # list of research-line ids applies it to the topics of those lines only.
    owner_mode: str | tuple[str, ...] = "off"
    owner: OwnerSettings = field(default_factory=lambda: OwnerSettings())
    # [program.supply] (2026-11-20, W1): topic supply and early screening.
    supply: SupplySettings = field(default_factory=lambda: SupplySettings())
    # [program.funnel] (2026-11-25, NC aim): target stage and the topic funnel's parameters.
    funnel: FunnelSettings = field(default_factory=lambda: FunnelSettings())
    # Automatic reopens per frozen topic whose recorded line-level conditions
    # (``auto_reopen``: shared control receipt, line capability) came true; a
    # topic may ask for fewer. 0 turns automatic reopening off.
    auto_reopen_max: int = 1
    # Operator text-revision grants per frozen topic (``program reopen-grant``,
    # 2026-11-20), counted apart from ``auto_reopen_max``. 0 turns the command off.
    operator_reopen_max: int = 1
    # Card intake (2026-11-16): run the mechanical precheck a research line declares
    # (``admission_precheck`` in research-lines.yaml, no model involved) before a card is
    # registered for admission, and raise a card's compute plan to the line's typical
    # cost (``card_compute_floor`` / ``per_paper_cost``). A line that declares
    # neither is unaffected. The timeout caps any line's own timeout_seconds.
    card_precheck: bool = True
    card_precheck_max_seconds: int = 900
    card_compute_floor: bool = True
    # Compute backlog gate (2026-11-18, after 9 topics in 10 hours left ailab with 21
    # queued jobs declaring 11x its threads): while the CPU threads declared by queued
    # jobs of the ailab and local compute queues exceed compute_backlog_ratio x their
    # combined capacity (or more than compute_backlog_max_queued_jobs jobs are queued,
    # 0 = no job-count limit), no new scout, admission review or materialization starts.
    # Topics already in research are not affected; the gate lifts by itself once the
    # backlog falls. Reported as production_blocked reason compute_backlog.
    compute_backlog_gate: bool = True
    compute_backlog_ratio: float = 2.0
    compute_backlog_max_queued_jobs: int = 0
    # Brief limit per topic (owner seats): CPU threads its queued + running compute jobs
    # may declare at once; openlabs-remote refuses a submission beyond it (0 = off).
    campaign_compute_threads: int = 8
    # Per-line research slots (2026-11-19, three-line comparison): {line id: limit}. A
    # line at its limit (admitted + active + in-review topics of the line) gets no scout,
    # no admission review and no new campaign; ``max_active_topics`` still caps the
    # total. Lines not listed are bounded by the global limit only.
    line_max_active_topics: dict[str, int] = field(default_factory=dict)
    # Polish mode (2026-11-23, owner: "stop new tasks and new experiments, polish the
    # papers already produced"): no new topic supply and no new research starts -- no
    # scout, card repair, card revision, admission review, admission pilot, auto-reopen
    # of a frozen topic or materialization of an admitted topic. Writing, reviews,
    # delivery, delivered-version revisions (revise-delivered), operator reopen grants,
    # journal mail and topics already in research keep running. Off by default;
    # turning it off restores normal supply on the next tick.
    polish_mode: bool = False
    # Lines exempt from polish mode (2026-11-25 NC trial, user: "NC产线完整就绪后，你尝试性的
    # 试产一篇看看"): an exempt line gets its whole supply and research start back (scout,
    # card repair and revision, hold release, prescreen, pilot, admission, materialization,
    # auto-reopen) while polish mode keeps every other line stopped. Empty by default.
    polish_exempt_lines: tuple[str, ...] = ()

    def polish_blocks(self, line: Any = None) -> bool:
        """Whether polish mode stops new supply/research for a topic of ``line``."""

        if not self.polish_mode:
            return False
        return not (isinstance(line, str) and line and line in self.polish_exempt_lines)

    def polish_blocks_all(self) -> bool:
        """Polish mode is on and no line is exempt: every supply step stops."""

        return self.polish_mode and not self.polish_exempt_lines


DEFAULT_OWNER_RUNNERS: tuple[str, ...] = ("lead_claude", "worker_claude", "lead_gpt")


@dataclass(frozen=True)
class SupplySettings:
    """``[program.supply]`` (2026-11-20, pipeline overhaul W1): topic supply and early screens.

    Every switch defaults to on; a research line that declares none of the fields these
    screens read (``capabilities``/``required_capabilities``, ``data_requirements``,
    ``admission_pilot``) is unaffected by items 2 and 3.
    """

    # 1. Line-level shared facts: a feasibility-precheck freeze caused by a shared line
    # reference (control receipt) blocks the line instead of freezing each topic; a
    # freeze while a named compute job is still queued/running parks the topic on the
    # job (at most reference_wait_max times per topic); a borderline miss (the excess
    # over the tolerance is below the measurement's uncertainty, or without one at most
    # borderline_relative_margin x the tolerance) goes to a direction decision.
    line_facts: bool = True
    borderline_relative_margin: float = 0.05
    reference_wait_max: int = 2
    # Days a line block may hold its waiting topics before each gets its own direction
    # decision.
    line_block_max_days: float = 7.0
    # 2. Capability table and data availability screens at card intake.
    capability_screen: bool = True
    data_screen: bool = True
    # 3. Pilot gate: a template's declared admission_pilot runs on ailab before review.
    pilot: bool = True
    pilot_core_hours_max: float = 16.0
    pilot_max_threads: int = 8
    pilot_max_concurrent: int = 2
    pilot_max_attempts: int = 2
    # 4. Target memory: a target that failed for a mechanical reason with unchanged
    # input, or that has a frozen topic the card does not reopen, gets no new card.
    target_memory: bool = True
    # 5. Scouts: no scout for a line whose enumerated queues have nothing drawable;
    # the empty-draw backoff keeps doubling past scout_empty_backoff_hours up to this.
    scout_skip_empty_queue: bool = True
    scout_backoff_max_hours: float = 48.0


# Research target stages (target_stage.py). "line_events" keeps the per-line recorded stage
# (run_in -> tier2_aim, 2026-11-22); any other value is the one stage of every line.
FUNNEL_TARGET_STAGES = ("nc_aim", "line_events")
EXPECTED_BANDS = ("nc", "zone_1", "zone_2", "zones_3_4")


@dataclass(frozen=True)
class FunnelSettings:
    """``[program.funnel]`` (2026-11-25): NC-aimed topic selection as a graded funnel.

    User decision UD-20261125-nc-aim (registry/user-decisions.yaml): every topic aims at
    Nature Communications; the journal is decided by the results (NC, then CAS Zone 1, 2, 3-4).
    Each funnel level is dearer and stricter than the one before (design:
    maintenance/20261125-nc-aim/DESIGN.md). Hard stops are only: data unavailable, fewer than
    ``min_nc_thresholds`` NC thresholds, a kill test whose signal is absent, and an expected
    band below ``admission_min_band``; everything else is recorded for the admission gate.
    """

    target_stage: str = "nc_aim"
    # NC thresholds (generality, counterintuitive, scale, benchmark, resource) a topic must meet.
    min_nc_thresholds: int = 2
    # L1 (mechanical): data source catalogue, capacity and near-duplicate screens.
    uncatalogued_data: str = "reject"  # reject | warn
    max_topic_data_gb: float = 2000.0
    max_topic_storage_gb: float = 2000.0
    dedup_reject_similarity: float = 0.8
    dedup_warn_similarity: float = 0.5
    # L2+L3 (topic_prescreen task): quick novelty + NC pre-assessment, then the kill test.
    prescreen: bool = True
    prescreen_max_concurrent: int = 2
    prescreen_max_attempts: int = 2
    prescreen_wall_seconds: int = 5_400
    kill_test_core_hours: float = 2.0
    kill_test_cpus: int = 2
    kill_test_max_download_mb: int = 200
    # A null model explaining at least this share of the claimed effect lowers the band one
    # step. Was 0.8; 0.5 after the NC trial (2026-11-25 report section 5, item 2: the ECG card
    # passed with an effect a simple null model largely explained). A signal a known formula
    # or algebraic relation determines counts as fully explained (nc_funnel.evaluate_prescreen).
    null_explained_max: float = 0.5
    # L4 (admission): independent novelty search and the floor of the expected band.
    novelty_min_papers: int = 50
    novelty_window_years: int = 3
    novelty_closest: int = 5
    admission_min_band: str = "zone_1"
    # L0 (scouts): weekly model budget per line (USD equivalent, 0 = off) and stall backoff.
    scout_weekly_usd_per_line: float = 60.0
    stall_zero_pass_after: int = 5
    stall_backoff_hours: float = 48.0
    # L6 (grading): journals of the NC band (the rest is graded by CAS zone).
    nc_journals: tuple[str, ...] = ("Nature Communications",)
    # User 2026-11-25 (item 3): grade the journal before writing (owner hand-over to writing),
    # re-check only for changed evidence at review-ready. readiness_returns: how often an
    # owner seat without the decisive analysis and the four required checks is sent back.
    grade_before_writing: bool = True
    readiness_returns: int = 2
    # Target mix per 10 topics (user 2026-11-25): 2-3 NC, 2-3 Zone 1, the rest lower.
    target_mix: dict[str, tuple[int, int]] = field(default_factory=lambda: {
        "nc": (2, 3), "zone_1": (2, 3)})
    # Lines that keep their own (templated) standard instead of the NC aim; empty by default.
    exempt_lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class OwnerSettings:
    """``[program.owner]``: the owner agent's seat, runner choice and breaker."""

    # Main-agent preference (owner 2026-11-14: Fable, then Opus 5.5, then astra);
    # names of [runners.*] entries. A topic keeps its owner while that runner
    # can take ordinary work.
    runners: tuple[str, ...] = DEFAULT_OWNER_RUNNERS
    # Upper bound of one seat (one agent process); the env timeout still caps it.
    seat_wall_seconds: int = 14_400
    # A queued seat whose runner has been unable to start it this long moves to
    # the next usable runner (fresh session, or the same session when the new
    # runner is of the same provider and keep_session_within_provider is true).
    switch_after_minutes: float = 120.0
    # Keep the session on such a move only when the new runner runs the same model
    # (2026-11-20: prompt caches are per model, so a Fable session continued on Opus
    # re-read its whole context uncached - 7 cross-model resumes cost about $21). The
    # name is kept for existing configs; a different model always starts fresh.
    keep_session_within_provider: bool = True
    # Topics one runner may own at once (unlisted runners: no limit). Default:
    # Fable owns at most one topic.
    max_topics_per_runner: dict[str, int] = field(
        default_factory=lambda: {"lead_claude": 1}
    )
    # Consecutive finished seats without new evidence (unchanged workspace digest,
    # no new artifact hash, no remote-job wake-up) that schedule a direction decision.
    no_progress_seats: int = 3
    # Backoff before the next seat once the streak reaches 2 (2026-11-17, after 75
    # half-minute quota-stop seats): minutes per further no-progress seat, the last
    # value repeats; the seat is queued with not_before so nothing is dispatched early.
    no_progress_backoff_minutes: tuple[int, ...] = (10, 30, 120)
    # A seat shorter than this counts as progress only through a substantive signal
    # (new jobs, new non-bookkeeping artifacts, phase/status advance), never through
    # workspace file changes alone.
    short_seat_seconds: int = 180
    # Default model of Claude sub-agents an owner session starts without naming
    # one (CLAUDE_CODE_SUBAGENT_MODEL); an explicit Agent `model` still wins.
    claude_subagent_model: str | None = "claude-opus-5-5"
    # Weaker GPT model the brief offers through `codex exec` / Codex spawn_agent.
    # User 2026-11-18 ("所有模型都选用最新版本"): the newest sol (was gpt-6.1-sol).
    codex_helper_model: str = "gpt-6.2-sol"
    codex_light_model: str = "gpt-6-luna"
    # Recompute review (2026-11-16): a manuscript the owner returns as ready_for_review
    # first goes to an independent reviewer (other model family; same family, other
    # model when only one is configured) who recomputes its core results from the data.
    # major -> back to the owner, then the next round; minor -> the owner fixes and
    # self-checks, then the unified review; accept -> the unified review; reject or a
    # major verdict in round review_max_rounds -> direction decision. False: the owner's
    # ready_for_review goes straight to the unified review (behaviour before 2026-11-16).
    recompute_review: bool = True
    review_max_rounds: int = 3
    # Session length (2026-11-16): seats one agent session may run before the next seat
    # starts a fresh session from the owner's handover (OWNER_HANDOVER.md). 1 = every
    # seat is a fresh session; 0 = no seat limit (always resume, the earlier behaviour).
    session_max_seats: int = 1
    # Tokens read (uncached + cached input) by one session above which the next seat
    # starts fresh even below session_max_seats; 0 = no token threshold.
    session_max_tokens_read: int = 0
    # Short continuation (2026-11-20, cache-cost review): a seat queued right after the
    # last one may resume its session even past session_max_seats when all hold: the
    # last seat's final context (last request's input) is below
    # short_resume_context_tokens, the gap since it finished is at most
    # short_resume_gap_minutes (well inside the 1-hour prompt cache), both run the same
    # model, and the session has read less than short_resume_max_tokens_read in total
    # (stops snowballing). A queued short resume that does not start within the gap is
    # turned back into a fresh seat. 0 disables it: on gpt-6.2-sol owner seats (fresh
    # first request ~20 K tokens, ~64 % cached) carrying 40-100 K of old context through
    # every later request cost more than the fresh start saved (11-18..11-20 replay:
    # 22 eligible seats, about -$2), so it stays off by default; suggested values when
    # enabled: 100_000 / 10 / 1_000_000.
    short_resume_context_tokens: int = 0
    short_resume_gap_minutes: float = 10.0
    short_resume_max_tokens_read: int = 1_000_000
    # Size limit of the owner's handover file; a larger one is cut for the next brief.
    handover_max_bytes: int = 8_192
    # Writer of the manuscript (user decision 2026-11-19): once the owner declares the
    # research done (packet ``phase: writing``, or a first ``ready_for_review``), this
    # runner writes the whole paper and every revision after it, from the owner's
    # OWNER_HANDOVER.md. None/empty: the owner writes (behaviour before 2026-11-19).
    writing_runner: str | None = None
    # Writing seats of the writer running at once (the owner cap max_topics_per_runner
    # does not apply to them); further writing seats wait for a slot.
    max_writing_topics: int = 2
    # A writing seat waits for its writer (quota, pacing or a slot) this long before the
    # original owner writes instead; the fallback is noted on the topic.
    writing_wait_hours: float = 12.0
    # Runner of the figure seats (``paper_figure_repair``; user decision 2026-11-23: the
    # paper's writing and figures go to Claude Opus). None/empty: ``writing_runner``. A
    # figure seat waits for it up to ``writing_wait_hours`` (as a writer seat does), then
    # goes to the runner of the seat that asked for it. With neither set, or a runner not
    # configured, the figure seat runs on that asking seat's runner (behaviour before);
    # a figure_runner that is not configured is skipped in favour of writing_runner.
    figure_runner: str | None = None


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
    # 2026-11-19: judge the host load for agent launches without the CPU the local overflow
    # queue's running jobs declared (they fill the container by design, bounded by
    # config/local-compute.json max_cpus; agent sessions are light). Off by default.
    host_load_excludes_local_compute: bool = False
    # Consecutive agent_quota results one task may defer before ordinary failure
    # handling takes over (guards against a misclassified real failure).
    quota_retry_limit: int = 8
    # Automatic retries of a needs_human/quarantined task whose last attempt
    # failed for an infrastructure reason before it blocks or freezes its topic.
    infrastructure_retry_limit: int = 3


TIERS = ("lead", "worker", "light")
# Task classes a runner may restrict itself to (``[runners.<name>].task_classes``); the
# values ``budget.task_class`` returns.
TASK_CLASSES = ("ordinary", "review", "decision", "owner")
# The Antigravity CLI (``agy``, Google): one login, several quota pools, and models of
# three families. Its runners draw quota from this provider; their review independence
# follows the model family (``runner_family``).
ANTIGRAVITY_PROVIDER = "google-antigravity"
GOOGLE_FAMILY = "google"


def runner_family(provider: str, model: str | None) -> str:
    """Model family of a runner, for author/reviewer independence.

    A provider is its own family, except the Antigravity CLI, which serves Gemini
    (``google``), Claude (``anthropic``: the same models as Claude Code, from a
    separate quota pool) and GPT-OSS (``openai-codex``: an OpenAI open-weight model;
    counted with GPT so a GPT-OSS review never passes as independent of GPT work).
    """

    if provider != ANTIGRAVITY_PROVIDER:
        return provider
    name = str(model or "").strip().lower()
    if name.startswith("claude"):
        return "anthropic"
    if name.startswith("gpt"):
        return "openai-codex"
    return GOOGLE_FAMILY
# One owner-agent seat of a research-program topic in owner mode ([program].owner_mode).
OWNER_TASK_TYPE = "topic_owner"
# Pre-provider runner names. They request a tier, never a model family: with a
# ``[runners]`` table configured, a task carrying one of them is routed.
LEGACY_RUNNER_TIERS: dict[str, str] = {"frontier": "lead", "balanced": "worker", "cheap": "light"}
# The legacy runner name a dispatch point writes for a tier (``dispatch_runner``).
TIER_RUNNER_ALIASES: dict[str, str] = {tier: alias for alias, tier in LEGACY_RUNNER_TIERS.items()}

# Task type (optionally ``task_type:routing_reason``) -> tier. This is the one
# table of who does what; ``[routing.task_tiers]`` overrides single entries. A
# ``task_type:routing_reason`` entry wins over the plain ``task_type`` entry;
# a type with no entry keeps the tier its runner name requests.
#
# User decision 2026-11-18 ("opus和sol各自负责这三个功能，fable和astra只做最最重要的
# 关键节点"): admission, the owner's recompute review, replanning, candidate
# maturation and the other portfolio reviews run on the worker tier (Claude Opus /
# gpt-sol); the lead tier (Claude Fable / gpt-astra) keeps the direction decisions.
# The formal pre-delivery review panel is configured in the data repository
# (registry/settings.yaml review.roles), not here. Reviews keep their independence
# within the tier: the router excludes the author's family (sol <-> Opus).
DEFAULT_TASK_TIERS: dict[str, str] = {
    # lead: the key decisions.
    "direction_decision": "lead",
    "portfolio_planning": "lead",
    "failure_diagnosis": "lead",
    # Unified-review carriers outside the owner flow (legacy paper path) and the
    # generic review types.
    "paper_review": "lead",
    "independent_review": "lead",
    "review": "lead",
    # worker since 2026-11-18 (were lead).
    "portfolio_review": "worker",
    "portfolio_review:topic_admission": "worker",
    "portfolio_review:new_project_results_review": "worker",
    "topic_admission": "worker",
    "paper_review:owner_recompute_review": "worker",
    # Carriers of the unified review: the agent runs `paper-writing review
    # unified-run` (whose editor/referees come from settings.yaml) plus the literal
    # pre-registration check, so its own session is worker-sized.
    "paper_review:owner_review": "worker",
    "paper_review:release_full_review": "worker",
    "replan": "worker",
    "paper_revision:direction_retarget": "worker",
    "paper_readiness:direction_retarget": "worker",
    # An owner seat is pinned to a concrete runner ([program.owner].runners).
    "topic_owner": "lead",
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
    # Revising a held topic against its reopen conditions is scout work; fixing
    # a card's format errors is light.
    "topic_revision": "worker",
    "topic_card_repair": "light",
    # NC funnel prescreen (2026-11-25): quick novelty + NC thresholds, then a <= 2 core-hour
    # kill test it writes and runs itself; worker tier because it writes a little code.
    "topic_prescreen": "worker",
    # Distilling a finished topic into reusable assets is bookkeeping-sized work.
    "topic_retrospective": "light",
    "paper_revision": "worker",
    "paper_readiness": "worker",
    "paper_writing": "worker",
    "paper_figure_repair": "worker",
    # light: cheapest model.
    "literature_scan": "light",
    "literature_search": "light",
    "literature_screening": "light",
    "data_download": "light",
    "data_curation": "light",
    "format_fix": "light",
    "figure_redraw": "light",
}
# Routing reasons the orchestrator dispatches; a ``task_type:routing_reason``
# key of ``[routing.task_tiers]`` must name one of them (typos would otherwise be
# silently ignored). Keep in step with the constants of the dispatching modules
# (test_task_tiers checks it).
KNOWN_ROUTING_REASONS: frozenset[str] = frozenset({
    # program_flow
    "topic_admission", "program_slot_open", "topic_card_repair", "topic_revision",
    "topic_prescreen",
    # portfolio
    "new_project_results_review", "reviewer_selected_candidate_maturation",
    # owner
    "owner_first_seat", "owner_continue", "owner_converted", "owner_review",
    "owner_review_returned", "owner_recompute_review", "owner_recompute_returned",
    "owner_retry", "owner_reopened", "owner_operator_reopen", "paper_figure_repair",
    # program_autonomy
    "direction_decision", "direction_targeted_analysis", "direction_retarget",
    "release_format_fix", "release_full_review",
    # engine
    "gate_replan", "infrastructure_retry", "production_idle_reseed", "production_rollover",
    "production_gate_repair", "remote_wait", "role_handoff", "independent_restart",
    "validated_continuation", "review_evidence_completed", "readiness_evidence_completed",
    "paper_evidence_audit", "independent_audit_passed", "paper_review_scope_selection",
    "review_text_revision", "review_evidence_remediation",
    # assets
    "topic_retrospective",
})
_TASK_TIER_PART = re.compile(r"[a-z][a-z0-9_]*")


def task_tier_key(task_type: str, routing_reason: str | None = None) -> str:
    """``[routing.task_tiers]`` key of a task type, optionally narrowed by its routing reason."""

    return f"{task_type}:{routing_reason}" if routing_reason else task_type


def lookup_task_tier(
    task_tiers: dict[str, str], task_type: Any, routing_reason: Any = None
) -> str | None:
    """Configured tier of a task: ``type:reason`` first, then ``type``; None when unlisted."""

    kind = str(task_type or "")
    reason = str(routing_reason or "")
    if reason:
        tier = task_tiers.get(task_tier_key(kind, reason))
        if tier is not None:
            return tier
    return task_tiers.get(kind)


def dispatch_runner(
    settings: "FactorySettings",
    task_type: str,
    routing_reason: str | None,
    default: str,
) -> str:
    """Runner name a dispatch point writes: the configured tier's legacy alias.

    ``default`` (a legacy alias or tier) applies only when the table has no entry
    for the task. With ``[runners]`` configured the router resolves the same table
    again (``QuotaRouter.required_tier``); without it the alias picks the argv.
    """

    tier = lookup_task_tier(settings.routing.task_tiers, task_type, routing_reason)
    if tier is None:
        return default
    return TIER_RUNNER_ALIASES[tier]


def parse_task_tiers(payload: Any, defaults: dict[str, str]) -> dict[str, str]:
    """``[routing.task_tiers]`` merged over ``defaults``, with clear errors.

    Keys: ``task_type`` (any task type, custom ones included) or
    ``task_type:routing_reason`` (a known task type and a known routing reason).
    Values: ``lead``, ``worker`` or ``light`` (the legacy ``frontier``, ``balanced``
    and ``cheap`` are accepted and normalized).
    """

    merged = dict(defaults)
    if payload is None:
        return merged
    if not isinstance(payload, dict):
        raise ValueError("[routing.task_tiers] must be a table of task type -> tier")
    known_types = {key.split(":", 1)[0] for key in defaults} | {OWNER_TASK_TYPE}
    for raw_key, raw_value in payload.items():
        key = str(raw_key).strip()
        value = str(raw_value).strip()
        value = LEGACY_RUNNER_TIERS.get(value, value)
        if value not in TIERS:
            raise ValueError(
                f"[routing.task_tiers].{key!r} = {raw_value!r}: tier must be one of "
                f"{', '.join(TIERS)}"
            )
        parts = key.split(":")
        if len(parts) > 2 or not all(_TASK_TIER_PART.fullmatch(part) for part in parts):
            raise ValueError(
                f"[routing.task_tiers].{key!r}: key must be task_type or "
                "task_type:routing_reason (lowercase letters, digits, underscores)"
            )
        if len(parts) == 2:
            kind, reason = parts
            if kind not in known_types:
                raise ValueError(
                    f"[routing.task_tiers].{key!r}: unknown task type {kind!r} "
                    f"(known: {', '.join(sorted(known_types))})"
                )
            if reason not in KNOWN_ROUTING_REASONS:
                raise ValueError(
                    f"[routing.task_tiers].{key!r}: unknown routing reason {reason!r} "
                    f"(known: {', '.join(sorted(KNOWN_ROUTING_REASONS))})"
                )
        merged[key] = value
    return merged


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
# topic_prescreen (2026-11-25 NC trial): the funnel's independent judgment of another family's
# card, the cheap first half of the admission gate - a review like the worker-tier admission
# review, so a review-class runner (Gemini) may take it when the card's other family is paced.
DEFAULT_REVIEW_TASK_TYPES: tuple[str, ...] = ("paper_review", "independent_review", "review",
                                              "topic_prescreen")
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
    "paper_figure_repair": 3,
    "topic_admission": 1,
    "topic_card_repair": 1,
    "topic_prescreen": 1,
    "topic_revision": 0,
    "topic_scout": 0,
    "literature_scan": 0,
    "literature_search": 0,
    "literature_screening": 0,
}
# Task types held while no lead runner can take a decision task.
DEFAULT_LEAD_SHORTAGE_PAUSED: tuple[str, ...] = (
    "topic_admission",
    "topic_scout",
    "topic_revision",
    "topic_card_repair",
    "topic_prescreen",
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
# Owner decision 2026-11-14: front-loaded pacing; (elapsed share of the window,
# share of the class ceiling allowed). For a 7-day window the points are the
# ends of days 0..6; the factor is 1 from the start of the last day.
DEFAULT_PACE_CURVE: tuple[tuple[float, float], ...] = (
    (0.0, 0.0),
    (0.1429, 0.3125),
    (0.2857, 0.525),
    (0.4286, 0.6875),
    (0.5714, 0.8125),
    (0.7143, 0.9125),
    (0.8571, 1.0),
)


def parse_pace_curve(value: Any) -> tuple[tuple[float, float], ...]:
    """Validate ``[routing].pace_curve``: ``[[elapsed share, factor], ...]``.

    Elapsed shares start at 0 and strictly increase within [0, 1]; factors lie
    in [0, 1], never decrease and end at 1. Anything else is a configuration
    error (ValueError).
    """

    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("[routing].pace_curve must be a non-empty list of [share, factor]")
    points: list[tuple[float, float]] = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError(f"[routing].pace_curve point {item!r} is not [share, factor]")
        try:
            x, y = float(item[0]), float(item[1])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"[routing].pace_curve point {item!r} is not numeric") from exc
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise ValueError(f"[routing].pace_curve point {item!r} is outside [0, 1]")
        if points and (x <= points[-1][0] or y < points[-1][1]):
            raise ValueError(
                "[routing].pace_curve must have increasing shares and non-decreasing factors"
            )
        points.append((x, y))
    if points[0][0] != 0:
        raise ValueError("[routing].pace_curve must start at share 0")
    if points[-1][1] != 1:
        raise ValueError("[routing].pace_curve must end at factor 1")
    return tuple(points)


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
    # Task classes the router may give this runner (empty: all). A runner pinned
    # by name (an owner seat, a manual pin) is not restricted.
    task_classes: tuple[str, ...] = ()
    # An overflow runner is chosen only when no other runner of the pool can take
    # the task now (quota, backoff or parallelism): the Antigravity runners join as
    # a supplement, never as the first choice.
    overflow: bool = False
    # Explicit model family; None derives it (``runner_family``).
    family_override: str | None = None

    @property
    def subagents_allowed(self) -> bool:
        return self.tier == "lead" if self.allow_subagents is None else self.allow_subagents

    @property
    def family(self) -> str:
        """Model family used for author/reviewer independence (not for quota)."""

        return self.family_override or runner_family(self.provider, self.model)

    def accepts(self, klass: str) -> bool:
        return not self.task_classes or klass in self.task_classes


@dataclass(frozen=True)
class RoutingSettings:
    """Quota-aware runner selection (``[routing]`` in openlabs.toml).

    Only active when ``FactorySettings.runners`` is non-empty.
    """

    # Owner rule 2026-11-14: on every quota window of every provider, ordinary
    # tasks stop at ``ordinary_ceiling`` used and every automatic task (reviews
    # and decisions included) at ``hard_ceiling``. Both are reached only in the
    # window's last day: at elapsed share x of a window a class may use
    # ``min(ceiling, max(ceiling x pace(x), pace_lead))`` where ``pace`` is the
    # piecewise-linear ``pace_curve`` (points ``(elapsed share, factor)``,
    # front-loaded by default: 7-day ends of day 1..6 -> 0.3125, 0.525, 0.6875,
    # 0.8125, 0.9125, 1.0) and ``pace_lead`` a small start allowance so a fresh
    # window can begin. Windows shorter than ``pace_min_window_hours`` (the
    # 5-hour window) are not paced, only capped. ``pace_curve = [[0, 1]]``
    # disables pacing; ``[[0, 0], [0.8571, 1]]`` is plain linear pacing to the
    # last day of a 7-day window. These replace the former ``review_reserve``
    # and the ceiling role of ``utilization_target`` (now only the switch for
    # abundance spreading).
    ordinary_ceiling: float = 0.8
    hard_ceiling: float = 0.9
    # Optional per-provider overrides (``[routing.provider_ceilings.<provider>]``
    # with ``ordinary_ceiling`` and/or ``hard_ceiling``): provider ->
    # ``(ordinary, hard)``, already resolved against the global values above.
    # Providers not listed use the global values. Read them through
    # ``ceilings_for``/``for_provider``, never the two fields directly, wherever
    # the task's provider is known.
    provider_ceilings: dict[str, tuple[float, float]] = field(default_factory=dict)
    pace_curve: tuple[tuple[float, float], ...] = DEFAULT_PACE_CURVE
    pace_min_window_hours: float = 48.0
    pace_lead: float = 0.05
    # Highest ceiling a manual override (``program quota-override``) or a task
    # enqueued with ``--quota-override`` may use; kept below 100% so manual work
    # never reaches paid overage.
    override_max_ceiling: float = 0.99
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
    # > 0 switches on the utilization strategy: routing spreads work by relative
    # abundance, (final-day ceiling - used) / time-to-reset fraction, so a
    # provider whose window resets soon with quota left is used first, and the
    # tick supervises throughput. The value itself is no longer a ceiling
    # (``ordinary_ceiling``/``hard_ceiling`` are); 0 compares plain headroom.
    utilization_target: float = 0.0
    # Minimum minutes between free refreshes (Codex session file) of a stale
    # reading; None: ``probe_idle_minutes`` like the paid probe.
    stale_refresh_minutes: int | None = None
    # A stale reading younger than this many hours is extrapolated instead of
    # treated as unknown: used + the window's average pace over the time this
    # instance actually ran agents on the provider since then + its agent-hours
    # x ``estimate_fraction_per_agent_hour`` (of a 7-day window; scaled for
    # shorter windows), capped at +0.25. A stopped loop extrapolates nothing.
    # 0 disables it.
    stale_estimate_hours: float = 0.0
    estimate_fraction_per_agent_hour: float = 0.01
    # User decision 2026-11-16: a review/decision whose independent family is
    # configured but has no runner able to take it for quota reasons (state
    # unavailable: ceiling, pace, reserve, backoff) goes to another model of the
    # producer's family instead of waiting. The other family's estimated
    # reopening within ``independence_fallback_min_wait_minutes`` is waited for
    # (0: fall back as soon as it is unavailable).
    independence_fallback_on_quota: bool = True
    independence_fallback_min_wait_minutes: float = 0.0

    def ceilings_for(self, provider: str | None) -> tuple[float, float]:
        """``(ordinary, hard)`` ceilings of ``provider`` (the global pair when not overridden)."""

        if provider is not None and provider in self.provider_ceilings:
            return self.provider_ceilings[provider]
        return (min(self.ordinary_ceiling, self.hard_ceiling), self.hard_ceiling)

    def for_provider(self, provider: str | None) -> "RoutingSettings":
        """These settings with ``provider``'s own ceilings as ``ordinary``/``hard``.

        Returns ``self`` unchanged when the provider has no override, so the
        global behaviour is exactly the former one.
        """

        if provider is None or provider not in self.provider_ceilings:
            return self
        ordinary, hard = self.provider_ceilings[provider]
        if ordinary == self.ordinary_ceiling and hard == self.hard_ceiling:
            return self
        return replace(self, ordinary_ceiling=ordinary, hard_ceiling=hard)


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
    # Local overflow compute queue dispatch; None follows launch_jobs. Setting it
    # true keeps CPU-only local jobs starting while launch_jobs = false stops every
    # agent session (production stop).
    launch_local_compute: bool | None = None
    # Generic no-progress guard (spin_guard.py): after this many consecutive tasks of
    # one campaign without progress its queued tasks wait no_progress_backoff_minutes
    # (last value repeats); at no_progress_escalate_after they stop as needs_human.
    # 0 disables the backoff (and the guard); escalate 0 = back off only.
    no_progress_backoff_after: int = 4
    no_progress_escalate_after: int = 8
    no_progress_backoff_minutes: tuple[int, ...] = (60, 240, 1440)
    # Same-state stall detection (spin_guard.state_signature, 2026-11-20). A seat's state
    # signature (phase, packet status, research-file digest, job ids, review stage,
    # writer, ledger status) repeated this many seats in a row schedules one direction
    # decision with a diagnosis; still unchanged stall_seats_after_decision seats after
    # that decision, the topic gets no further seat (reported under stuck_topics) until
    # its workspace or ledger status changes. 0 disables it.
    stall_signature_repeats: int = 6
    stall_seats_after_decision: int = 3
    archive_result_receipts: bool = True
    # User rule 2026-11-18: large proxy-route downloads only 02:00-14:00 Asia/Shanghai
    # ([factory] proxy_download_*; download_window.py).
    proxy_download: ProxyDownloadWindow = field(default_factory=ProxyDownloadWindow)
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
    # [routing.provider_suspensions] as configured, each marked active or expired at load
    # time (suspensions.py); the active ones are already applied to runners and routing.
    provider_suspensions: tuple[Any, ...] = ()
    assets: AssetSettings = field(default_factory=lambda: AssetSettings())
    reporting: ReportingSettings = field(default_factory=lambda: ReportingSettings())


@dataclass(frozen=True)
class ModelPrice:
    """List price of one model in USD per million tokens (an equivalent, not a bill)."""

    input: float
    cached_input: float
    output: float
    cache_write: float = 0.0
    cache_write_1h: float | None = None


# Prices used by the 2026-11-16 cost review (maintenance/20261116-cost-review section 1):
# the Claude rows from the claude-api model table (2026-11-03), the OpenAI rows from the
# GPT-6.1 Sol announcement and public price trackers (2026-11-16), short-context tier.
# gpt-6.2-sol / gpt-6.2-astra (released 2026-11-17): Standard tier, prompts up to 272K,
# as reported from OpenAI's pricing page by eesel.ai ("GPT-6.2 Sol pricing", "GPT-6.2
# Astra pricing") and computingforgeeks.com ("GPT-6.2 Astra and Sol: Pricing and API"),
# read 2026-11-18; cache write = the 30-minute write (12-hour writes are not split out).
DEFAULT_MODEL_PRICES: dict[str, ModelPrice] = {
    "claude-fable-5-2": ModelPrice(8.0, 0.20, 40.0, 10.0, 16.0),
    "claude-opus-5-5": ModelPrice(4.0, 0.20, 20.0, 5.0, 8.0),
    "claude-haiku-5-5": ModelPrice(0.10, 0.01, 0.50, 0.125, 0.20),
    "gpt-6.2-sol": ModelPrice(2.0, 0.10, 10.0, 2.5),
    "gpt-6.2-astra": ModelPrice(8.0, 0.40, 40.0, 10.0),
    # Earlier versions stay priced for attempts recorded under them.
    "gpt-6.1-sol": ModelPrice(2.0, 0.10, 10.0, 2.5),
    "gpt-6-astra": ModelPrice(10.0, 1.0, 50.0, 12.5),
    "gpt-6-luna": ModelPrice(0.10, 0.01, 0.50, 0.125),
}


@dataclass(frozen=True)
class ReportingSettings:
    """``[reporting]``: token cost and per-topic economics in the tick report."""

    prices: dict[str, ModelPrice] = field(default_factory=lambda: dict(DEFAULT_MODEL_PRICES))
    # Window of the per-task-type token/cost summary next to the idle metrics.
    token_window_hours: int = 24
    # Only attempts finished at or after this time count toward the per-paper averages
    # (for example the date of a restart); None counts everything recorded.
    economics_since: str | None = None


def load_reporting_settings(value: Any) -> ReportingSettings:
    if value is None:
        return ReportingSettings()
    if not isinstance(value, dict):
        raise ValueError("[reporting] must be a table")
    defaults = ReportingSettings()
    prices = dict(defaults.prices)
    raw_prices = value.get("prices")
    if raw_prices is not None:
        if not isinstance(raw_prices, dict):
            raise ValueError("[reporting.prices] must be a table of models")
        for model, row in raw_prices.items():
            if not isinstance(row, dict):
                raise ValueError(f"[reporting.prices.{model}] must be a table")
            try:
                prices[str(model)] = ModelPrice(
                    input=float(row["input"]),
                    cached_input=float(row.get("cached_input", row["input"])),
                    output=float(row["output"]),
                    cache_write=float(row.get("cache_write", 0.0)),
                    cache_write_1h=(None if row.get("cache_write_1h") is None
                                    else float(row["cache_write_1h"])),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"[reporting.prices.{model}] needs numeric input and output"
                ) from exc
    since = value.get("economics_since")
    return ReportingSettings(
        prices=prices,
        token_window_hours=_positive_int(value.get("token_window_hours"),
                                         defaults.token_window_hours),
        economics_since=str(since).strip() if since else None,
    )


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


def _hours_sequence(value: Any, default: tuple[float, ...]) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        return default
    parsed = tuple(_nonnegative_float(item, -1.0) for item in value)
    if any(item < 0 for item in parsed):
        return default
    return parsed


def _domain_list(value: Any, key: str = "domains") -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"[program].{key} must be an array of names")
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if not text:
            raise ValueError(f"[program].{key} entries must be non-empty strings")
        if text not in result:
            result.append(text)
    return tuple(result)


def _optional_path_text(value: Any, label: str) -> str | None:
    """An absolute path given as text, or None when unset/empty."""

    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str) or not Path(value.strip()).expanduser().is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    return str(Path(value.strip()).expanduser())


def _line_scout_intervals(value: Any) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("[program].line_scout_min_interval_hours must be a table")
    intervals = {}
    for line, raw in value.items():
        hours = _nonnegative_float(raw, -1.0)
        if not line.strip() or isinstance(raw, bool) or not 0 <= hours < float("inf"):
            raise ValueError(f"invalid scout interval for research line {line!r}")
        intervals[line.strip()] = hours
    return intervals


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
        line_scout_min_interval_hours=_line_scout_intervals(
            program.get("line_scout_min_interval_hours")
        ),
        max_concurrent_scouts=_positive_int(program.get("max_concurrent_scouts"), 1),
        scout_expected_cards=_positive_float(program.get("scout_expected_cards"), 2.0),
        scout_empty_backoff_hours=_hours_sequence(
            program.get("scout_empty_backoff_hours"), (1.0, 6.0, 24.0)
        ),
        scout_exhausted_after=_nonnegative_int(program.get("scout_exhausted_after"), 4),
        max_admissions_per_line=_positive_int(
            program.get("max_admissions_per_line", program.get("max_admissions_per_domain")), 1
        ),
        max_concurrent_admissions=_nonnegative_int(
            program.get("max_concurrent_admissions"), 0
        ),
        enforce_admission=program.get("enforce_admission", False) is True,
        asset_index_path=_relative_data_path(
            program.get("asset_index_path"), DEFAULT_ASSET_INDEX_PATH, "asset_index_path"
        ),
        domains=_domain_list(program.get("domains")),
        research_lines=_domain_list(program.get("research_lines"), "research_lines"),
        research_lines_path=_relative_data_path(
            program.get("research_lines_path"), DEFAULT_RESEARCH_LINES_PATH,
            "research_lines_path",
        ),
        max_days_from_admission_to_ready=_positive_float(
            program.get("max_days_from_admission_to_ready"), 28.0
        ),
        topic_max_agent_seconds=_positive_int(program.get("topic_max_agent_seconds"), 259_200),
        direction_limits=_direction_limits(program.get("direction_limits")),
        auto_handoff=program.get("auto_handoff", False) is True,
        site_assignment_sync=program.get("site_assignment_sync", True) is not False,
        paper_writing_command=_command(program.get("paper_writing_command"), ("paper-writing",)),
        handoff_max_attempts=_positive_int(program.get("handoff_max_attempts"), 3),
        credentials_file=_optional_path_text(program.get("credentials_file"),
                                             "[program].credentials_file"),
        reconcile_stale_days=_positive_float(program.get("reconcile_stale_days"), 5.0),
        auto_release=program.get("auto_release", False) is True,
        support_release=_support_release(program.get("support_release")),
        support_none_reason=_nonempty_text(program.get("support_none_reason"),
                                           DEFAULT_SUPPORT_NONE_REASON, "support_none_reason"),
        release_max_attempts=_positive_int(program.get("release_max_attempts"), 3),
        release_review_timeout_seconds=_positive_int(
            program.get("release_review_timeout_seconds"), 7_200
        ),
        compute_locations=_compute_locations(program.get("compute_locations")),
        owner_mode=_owner_mode(program.get("owner_mode")),
        owner=_owner_settings(program.get("owner")),
        supply=_supply_settings(program.get("supply")),
        funnel=_funnel_settings(program.get("funnel")),
        auto_reopen_max=_nonnegative_int(program.get("auto_reopen_max"), 1),
        operator_reopen_max=_nonnegative_int(program.get("operator_reopen_max"), 1),
        card_precheck=program.get("card_precheck", True) is not False,
        card_precheck_max_seconds=_positive_int(program.get("card_precheck_max_seconds"), 900),
        card_compute_floor=program.get("card_compute_floor", True) is not False,
        compute_backlog_gate=program.get("compute_backlog_gate", True) is not False,
        compute_backlog_ratio=_positive_float(program.get("compute_backlog_ratio"), 2.0),
        compute_backlog_max_queued_jobs=_nonnegative_int(
            program.get("compute_backlog_max_queued_jobs"), 0
        ),
        campaign_compute_threads=_nonnegative_int(program.get("campaign_compute_threads"), 8),
        polish_mode=program.get("polish_mode", False) is True,
        polish_exempt_lines=_domain_list(program.get("polish_exempt_lines"),
                                         "polish_exempt_lines"),
        line_max_active_topics=_line_limits(program.get("line_max_active_topics")),
        **_git_settings(program.get("git")),
    )


def _line_limits(value: Any) -> dict[str, int]:
    """``[program].line_max_active_topics``: ``{line id: non-negative int}``."""

    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("[program].line_max_active_topics must be a table of line = limit")
    limits: dict[str, int] = {}
    for key, raw in value.items():
        line = str(key or "").strip()
        if not line:
            raise ValueError("[program].line_max_active_topics keys must be line ids")
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise ValueError(
                f"[program].line_max_active_topics.{line} must be a non-negative integer")
        limits[line] = raw
    return limits


def _owner_mode(value: Any) -> str | tuple[str, ...]:
    if value is None or value is False:
        return "off"
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"off", "all"}:
            return text
        raise ValueError('[program].owner_mode must be "off", "all" or an array of line ids')
    if isinstance(value, list):
        return _domain_list(value, "owner_mode")
    raise ValueError('[program].owner_mode must be "off", "all" or an array of line ids')


def _funnel_settings(value: Any) -> FunnelSettings:
    """``[program.funnel]``; absent keys keep their defaults."""

    if value is None:
        return FunnelSettings()
    if not isinstance(value, dict):
        raise ValueError("[program.funnel] must be a table")
    d = FunnelSettings()
    stage = str(value.get("target_stage", d.target_stage)).strip()
    if stage not in FUNNEL_TARGET_STAGES:
        raise ValueError(f"[program.funnel].target_stage must be one of {FUNNEL_TARGET_STAGES}")
    band = str(value.get("admission_min_band", d.admission_min_band)).strip()
    if band not in EXPECTED_BANDS:
        raise ValueError(f"[program.funnel].admission_min_band must be one of {EXPECTED_BANDS}")
    data = str(value.get("uncatalogued_data", d.uncatalogued_data)).strip()
    if data not in {"reject", "warn"}:
        raise ValueError('[program.funnel].uncatalogued_data must be "reject" or "warn"')
    mix = value.get("target_mix")
    target_mix = dict(d.target_mix)
    if isinstance(mix, dict):
        for key, pair in mix.items():
            if key not in EXPECTED_BANDS or not isinstance(pair, list) or len(pair) != 2:
                raise ValueError("[program.funnel].target_mix maps a band to [low, high]")
            target_mix[key] = (int(pair[0]), int(pair[1]))
    journals = value.get("nc_journals")
    return FunnelSettings(
        target_stage=stage,
        min_nc_thresholds=min(5, _positive_int(value.get("min_nc_thresholds"),
                                               d.min_nc_thresholds)),
        uncatalogued_data=data,
        max_topic_data_gb=_positive_float(value.get("max_topic_data_gb"), d.max_topic_data_gb),
        max_topic_storage_gb=_positive_float(value.get("max_topic_storage_gb"),
                                             d.max_topic_storage_gb),
        dedup_reject_similarity=min(1.0, _positive_float(value.get("dedup_reject_similarity"),
                                                         d.dedup_reject_similarity)),
        dedup_warn_similarity=min(1.0, _positive_float(value.get("dedup_warn_similarity"),
                                                       d.dedup_warn_similarity)),
        prescreen=value.get("prescreen", d.prescreen) is not False,
        prescreen_max_concurrent=_positive_int(value.get("prescreen_max_concurrent"),
                                               d.prescreen_max_concurrent),
        prescreen_max_attempts=_positive_int(value.get("prescreen_max_attempts"),
                                             d.prescreen_max_attempts),
        prescreen_wall_seconds=_positive_int(value.get("prescreen_wall_seconds"),
                                             d.prescreen_wall_seconds),
        kill_test_core_hours=_positive_float(value.get("kill_test_core_hours"),
                                             d.kill_test_core_hours),
        kill_test_cpus=_positive_int(value.get("kill_test_cpus"), d.kill_test_cpus),
        kill_test_max_download_mb=_positive_int(value.get("kill_test_max_download_mb"),
                                                d.kill_test_max_download_mb),
        null_explained_max=min(1.0, _positive_float(value.get("null_explained_max"),
                                                    d.null_explained_max)),
        novelty_min_papers=_positive_int(value.get("novelty_min_papers"), d.novelty_min_papers),
        novelty_window_years=_positive_int(value.get("novelty_window_years"),
                                           d.novelty_window_years),
        novelty_closest=_positive_int(value.get("novelty_closest"), d.novelty_closest),
        admission_min_band=band,
        scout_weekly_usd_per_line=_nonnegative_float(value.get("scout_weekly_usd_per_line"),
                                                     d.scout_weekly_usd_per_line),
        stall_zero_pass_after=_nonnegative_int(value.get("stall_zero_pass_after"),
                                               d.stall_zero_pass_after),
        stall_backoff_hours=_nonnegative_float(value.get("stall_backoff_hours"),
                                               d.stall_backoff_hours),
        nc_journals=tuple(str(item) for item in journals) if isinstance(journals, list)
        and journals else d.nc_journals,
        grade_before_writing=value.get("grade_before_writing", d.grade_before_writing)
        is not False,
        readiness_returns=_nonnegative_int(value.get("readiness_returns"), d.readiness_returns),
        target_mix=target_mix,
        exempt_lines=_domain_list(value.get("exempt_lines"), "funnel.exempt_lines"),
    )


def _supply_settings(value: Any) -> SupplySettings:
    """``[program.supply]``; absent keys keep their (enabled) defaults."""

    if value is None:
        return SupplySettings()
    if not isinstance(value, dict):
        raise ValueError("[program.supply] must be a table")
    defaults = SupplySettings()

    def switch(key: str) -> bool:
        return value.get(key, getattr(defaults, key)) is not False

    margin = _nonnegative_float(value.get("borderline_relative_margin"),
                                defaults.borderline_relative_margin)
    return SupplySettings(
        line_facts=switch("line_facts"),
        borderline_relative_margin=min(margin, 1.0),
        reference_wait_max=_nonnegative_int(value.get("reference_wait_max"),
                                            defaults.reference_wait_max),
        line_block_max_days=_positive_float(value.get("line_block_max_days"),
                                            defaults.line_block_max_days),
        capability_screen=switch("capability_screen"),
        data_screen=switch("data_screen"),
        pilot=switch("pilot"),
        pilot_core_hours_max=_positive_float(value.get("pilot_core_hours_max"),
                                             defaults.pilot_core_hours_max),
        pilot_max_threads=min(8, _positive_int(value.get("pilot_max_threads"),
                                               defaults.pilot_max_threads)),
        pilot_max_concurrent=_positive_int(value.get("pilot_max_concurrent"),
                                           defaults.pilot_max_concurrent),
        pilot_max_attempts=_positive_int(value.get("pilot_max_attempts"),
                                         defaults.pilot_max_attempts),
        target_memory=switch("target_memory"),
        scout_skip_empty_queue=switch("scout_skip_empty_queue"),
        scout_backoff_max_hours=_positive_float(value.get("scout_backoff_max_hours"),
                                                defaults.scout_backoff_max_hours),
    )


def _owner_settings(value: Any) -> OwnerSettings:
    if value is None:
        return OwnerSettings()
    if not isinstance(value, dict):
        raise ValueError("[program.owner] must be a table")
    defaults = OwnerSettings()
    runners = value.get("runners")
    if runners is not None and (
        not isinstance(runners, list) or not runners
        or any(not isinstance(item, str) or not item.strip() for item in runners)
    ):
        raise ValueError("[program.owner].runners must be a non-empty array of runner names")
    limits_raw = value.get("max_topics_per_runner")
    limits = dict(defaults.max_topics_per_runner)
    if limits_raw is not None:
        if not isinstance(limits_raw, dict):
            raise ValueError("[program.owner].max_topics_per_runner must be a table")
        limits = {str(key): _nonnegative_int(raw, 1) for key, raw in limits_raw.items()}
    subagent = value.get("claude_subagent_model", defaults.claude_subagent_model)
    return OwnerSettings(
        runners=tuple(item.strip() for item in runners) if runners else defaults.runners,
        seat_wall_seconds=_positive_int(value.get("seat_wall_seconds"),
                                        defaults.seat_wall_seconds),
        switch_after_minutes=_nonnegative_float(value.get("switch_after_minutes"),
                                                defaults.switch_after_minutes),
        keep_session_within_provider=value.get(
            "keep_session_within_provider", defaults.keep_session_within_provider
        ) is not False,
        max_topics_per_runner=limits,
        no_progress_seats=_positive_int(value.get("no_progress_seats"),
                                        defaults.no_progress_seats),
        no_progress_backoff_minutes=(
            _minutes_sequence(value.get("no_progress_backoff_minutes"))
            if value.get("no_progress_backoff_minutes") is not None
            else defaults.no_progress_backoff_minutes
        ),
        short_seat_seconds=_nonnegative_int(value.get("short_seat_seconds"),
                                            defaults.short_seat_seconds),
        claude_subagent_model=(str(subagent).strip() or None) if subagent else None,
        codex_helper_model=str(value.get("codex_helper_model") or defaults.codex_helper_model),
        codex_light_model=str(value.get("codex_light_model") or defaults.codex_light_model),
        recompute_review=value.get("recompute_review", defaults.recompute_review) is not False,
        review_max_rounds=_positive_int(value.get("review_max_rounds"),
                                        defaults.review_max_rounds),
        session_max_seats=_nonnegative_int(value.get("session_max_seats"),
                                           defaults.session_max_seats),
        session_max_tokens_read=_nonnegative_int(value.get("session_max_tokens_read"),
                                                 defaults.session_max_tokens_read),
        short_resume_context_tokens=_nonnegative_int(
            value.get("short_resume_context_tokens"), defaults.short_resume_context_tokens),
        short_resume_gap_minutes=_nonnegative_float(
            value.get("short_resume_gap_minutes"), defaults.short_resume_gap_minutes),
        short_resume_max_tokens_read=_nonnegative_int(
            value.get("short_resume_max_tokens_read"), defaults.short_resume_max_tokens_read),
        handover_max_bytes=_positive_int(value.get("handover_max_bytes"),
                                         defaults.handover_max_bytes),
        writing_runner=str(value.get("writing_runner") or "").strip() or None,
        max_writing_topics=_positive_int(value.get("max_writing_topics"),
                                         defaults.max_writing_topics),
        writing_wait_hours=_nonnegative_float(value.get("writing_wait_hours"),
                                              defaults.writing_wait_hours),
        figure_runner=str(value.get("figure_runner") or "").strip() or None,
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
        host_load_excludes_local_compute=budget.get(
            "host_load_excludes_local_compute", False) is True,
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
        classes = _string_tuple(raw.get("task_classes"), ())
        unknown = sorted(set(classes) - set(TASK_CLASSES))
        if unknown:
            raise ValueError(
                f"[runners.{name}].task_classes has unknown classes {unknown}; "
                f"known: {list(TASK_CLASSES)}"
            )
        family = str(raw.get("family") or "").strip() or None
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
            task_classes=classes,
            overflow=_optional_bool(raw.get("overflow"), f"[runners.{name}].overflow") is True,
            family_override=family,
        )
    return specs


def _optional_bool(value: Any, label: str) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise ValueError(f"{label} must be true or false")


PROVIDER_CEILING_KEYS = ("ordinary_ceiling", "hard_ceiling")


def _strict_ceiling(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number in (0, 1], got {value!r}")
    parsed = float(value)
    if not 0 < parsed <= 1:
        raise ValueError(f"{label} must be in (0, 1], got {value!r}")
    return parsed


def parse_provider_ceilings(
    payload: Any,
    *,
    ordinary: float,
    hard: float,
) -> dict[str, tuple[float, float]]:
    """``[routing.provider_ceilings.<provider>]`` -> provider -> ``(ordinary, hard)``.

    Each table may set ``ordinary_ceiling`` and/or ``hard_ceiling``; an unset
    value is the global one (an inherited ordinary ceiling is lowered to the
    provider's hard ceiling, as globally). An explicit ordinary ceiling above
    the provider's hard ceiling, an unknown key or a value outside (0, 1] is a
    configuration error.
    """

    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("[routing.provider_ceilings] must be a table of provider tables")
    result: dict[str, tuple[float, float]] = {}
    for provider, entry in payload.items():
        label = f"[routing.provider_ceilings.{provider}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{label} must be a table with ordinary_ceiling and/or hard_ceiling")
        unknown = sorted(set(entry) - set(PROVIDER_CEILING_KEYS))
        if unknown:
            raise ValueError(
                f"{label} has unknown key(s) {', '.join(unknown)}; "
                f"allowed: {', '.join(PROVIDER_CEILING_KEYS)}"
            )
        provider_hard = (
            _strict_ceiling(entry["hard_ceiling"], f"{label}.hard_ceiling")
            if "hard_ceiling" in entry else hard
        )
        if "ordinary_ceiling" in entry:
            provider_ordinary = _strict_ceiling(
                entry["ordinary_ceiling"], f"{label}.ordinary_ceiling"
            )
            if provider_ordinary > provider_hard:
                raise ValueError(
                    f"{label}.ordinary_ceiling ({provider_ordinary}) must not exceed "
                    f"its hard_ceiling ({provider_hard})"
                )
        else:
            provider_ordinary = min(ordinary, provider_hard)
        result[str(provider)] = (provider_ordinary, provider_hard)
    return result


def load_routing_settings(payload: Any) -> RoutingSettings:
    routing = payload if isinstance(payload, dict) else {}
    defaults = RoutingSettings()
    task_tiers = parse_task_tiers(routing.get("task_tiers"), defaults.task_tiers)
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
    hard_ceiling = _unit_fraction(routing.get("hard_ceiling"), defaults.hard_ceiling)
    ordinary_ceiling = min(
        hard_ceiling, _unit_fraction(routing.get("ordinary_ceiling"), defaults.ordinary_ceiling)
    )
    override_max = _unit_fraction(
        routing.get("override_max_ceiling"), defaults.override_max_ceiling
    )
    provider_ceilings = parse_provider_ceilings(
        routing.get("provider_ceilings"), ordinary=ordinary_ceiling, hard=hard_ceiling
    )
    return RoutingSettings(
        ordinary_ceiling=ordinary_ceiling,
        hard_ceiling=hard_ceiling,
        provider_ceilings=provider_ceilings,
        pace_curve=(
            defaults.pace_curve if routing.get("pace_curve") is None
            else parse_pace_curve(routing.get("pace_curve"))
        ),
        pace_min_window_hours=_nonnegative_float(
            routing.get("pace_min_window_hours"), defaults.pace_min_window_hours
        ),
        pace_lead=_unit_fraction(routing.get("pace_lead"), defaults.pace_lead),
        # Manual overrides never reach 100% (paid overage).
        override_max_ceiling=min(override_max, defaults.override_max_ceiling),
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
        independence_fallback_on_quota=_optional_bool(
            routing.get("independence_fallback_on_quota"),
            "[routing] independence_fallback_on_quota",
        ) is not False,
        independence_fallback_min_wait_minutes=_nonnegative_float(
            routing.get("independence_fallback_min_wait_minutes"),
            defaults.independence_fallback_min_wait_minutes,
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
        resolved[name] = replace(spec, windows=windows, protected=protected)
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
    from . import suspensions as suspension_rules

    # Time-limited provider suspensions apply before anything is parsed (suspensions.py).
    payload, provider_suspensions = suspension_rules.apply(payload)
    runners = load_runner_specs(payload.get("runners"))
    routing = load_routing_settings(payload.get("routing"))
    runners = apply_model_defaults(runners, routing, payload.get("runners"))
    if runners and routing.provider_ceilings:
        known = {spec.provider for spec in runners.values()}
        stray = sorted(set(routing.provider_ceilings) - known)
        if stray:
            raise ValueError(
                f"[routing.provider_ceilings] names unknown provider(s) {', '.join(stray)}; "
                f"configured runners use: {', '.join(sorted(known))}"
            )
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
        launch_local_compute=(
            None if factory.get("launch_local_compute") is None
            else bool(factory.get("launch_local_compute"))
        ),
        no_progress_backoff_after=_nonnegative_int(factory.get("no_progress_backoff_after"), 4),
        no_progress_escalate_after=_nonnegative_int(
            factory.get("no_progress_escalate_after"), 8
        ),
        no_progress_backoff_minutes=(
            _minutes_sequence(factory.get("no_progress_backoff_minutes"))
            if factory.get("no_progress_backoff_minutes") is not None else (60, 240, 1440)
        ),
        stall_signature_repeats=_nonnegative_int(factory.get("stall_signature_repeats"), 6),
        stall_seats_after_decision=_positive_int(factory.get("stall_seats_after_decision"), 3),
        archive_result_receipts=bool(retention.get("archive_result_receipts", True)),
        proxy_download=load_window(factory),
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
        reporting=load_reporting_settings(payload.get("reporting")),
        provider_suspensions=provider_suspensions,
    )
