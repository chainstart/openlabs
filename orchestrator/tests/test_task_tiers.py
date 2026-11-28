"""Task -> tier table (user decision 2026-11-18) and independence inside the worker tier."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from openlabs import budget as budget_control
from openlabs import usage
from openlabs.config import (
    DEFAULT_MODEL_PRICES,
    DEFAULT_TASK_TIERS,
    KNOWN_ROUTING_REASONS,
    FactorySettings,
    RoutingSettings,
    RunnerSpec,
    dispatch_runner,
    load_routing_settings,
    lookup_task_tier,
)
from openlabs.utilization import argv_model, division_of_labour, runner_model_warnings
from test_quota_routing import CLAUDE, GPT, NOW, _claim, _enqueue, _routed_events, _setup
from test_quota_routing import _settings as _base_settings
from test_quota_routing import _snapshot

# The instance's runners after the 2026-11-18 upgrade to the newest versions.
RUNNERS = {
    "lead_gpt": RunnerSpec("lead_gpt", GPT, "lead", "gpt-6.2-astra"),
    "lead_claude": RunnerSpec(
        "lead_claude", CLAUDE, "lead", "claude-fable-5-2",
        windows=("seven_day_overage_included",), protected=True,
    ),
    "worker_gpt": RunnerSpec("worker_gpt", GPT, "worker", "gpt-6.2-sol"),
    "worker_claude": RunnerSpec("worker_claude", CLAUDE, "worker", "claude-opus-5-5"),
    "light_gpt": RunnerSpec("light_gpt", GPT, "light", "gpt-6-luna"),
    "light_claude": RunnerSpec("light_claude", CLAUDE, "light", "claude-haiku-5-5"),
}
SRC = Path(__file__).resolve().parents[1] / "src" / "openlabs"


def _settings(**routing) -> FactorySettings:
    return replace(_base_settings(**routing), runners=dict(RUNNERS))


def _record(db, settings, runner: str, used: dict[str, float]) -> None:
    spec = RUNNERS[runner]
    budget_control.record_quota_snapshot(
        db, settings, _snapshot(spec.provider, spec.model, used), runner=runner
    )


def _fresh(db, settings) -> None:
    _record(db, settings, "lead_gpt", {"seven_day": 0.05})
    _record(db, settings, "lead_claude",
            {"five_hour": 0.05, "seven_day": 0.05, "seven_day_overage_included": 0.05})


def _tier(settings: FactorySettings, task_type: str, reason: str | None = None) -> str:
    return budget_control.requested_tier(
        settings, {"task_type": task_type, "routing_reason": reason, "runner": "frontier"}
    )


# ------------------------------------------------------------------ the table


@pytest.mark.parametrize(
    ("task_type", "reason", "tier"),
    [
        ("portfolio_review", "topic_admission", "worker"),
        ("portfolio_review", "new_project_results_review", "worker"),
        ("paper_review", "owner_recompute_review", "worker"),
        ("paper_review", "owner_review", "worker"),
        ("paper_review", "release_full_review", "worker"),
        ("replan", "gate_replan", "worker"),
        ("candidate_maturation", "reviewer_selected_candidate_maturation", "worker"),
        ("paper_revision", "direction_retarget", "worker"),
        ("paper_readiness", "direction_retarget", "worker"),
        # Kept on the lead tier.
        ("direction_decision", "direction_decision", "lead"),
        ("paper_review", "paper_review_scope_selection", "lead"),
        ("portfolio_planning", None, "lead"),
        ("topic_scout", "program_slot_open", "worker"),
    ],
)
def test_default_division_of_labour(task_type, reason, tier) -> None:
    assert _tier(FactorySettings(), task_type, reason) == tier


def test_reason_key_wins_over_type_key() -> None:
    table = {"paper_review": "lead", "paper_review:owner_review": "worker"}
    assert lookup_task_tier(table, "paper_review", "owner_review") == "worker"
    assert lookup_task_tier(table, "paper_review", "other") == "lead"
    assert lookup_task_tier(table, "unlisted", "owner_review") is None


def test_unlisted_type_keeps_its_runner_alias_and_escalation_wins() -> None:
    settings = FactorySettings()
    assert budget_control.requested_tier(
        settings, {"task_type": "custom", "runner": "cheap"}) == "light"
    assert budget_control.requested_tier(
        settings, {"task_type": "portfolio_review", "routing_reason": "topic_admission",
                   "runner_request": "lead"}) == "lead"


def test_config_overrides_and_normalizes() -> None:
    routing = load_routing_settings({"task_tiers": {
        "portfolio_review:topic_admission": "lead",
        "replan": "frontier",
        "dataset_refresh": "light",
    }})
    assert routing.task_tiers["portfolio_review:topic_admission"] == "lead"
    assert routing.task_tiers["replan"] == "lead"
    assert routing.task_tiers["dataset_refresh"] == "light"
    # Untouched entries keep the code default.
    assert routing.task_tiers["paper_review:owner_recompute_review"] == "worker"
    settings = FactorySettings(routing=routing)
    assert dispatch_runner(settings, "portfolio_review", "topic_admission", "balanced") == "frontier"
    assert dispatch_runner(settings, "paper_review", "owner_recompute_review", "frontier") == (
        "balanced")
    assert dispatch_runner(settings, "custom_type", None, "cheap") == "cheap"


@pytest.mark.parametrize(
    ("table", "message"),
    [
        ({"replan": "strong"}, "tier must be one of lead, worker, light"),
        ({"Replan": "worker"}, "key must be task_type or task_type:routing_reason"),
        ({"a:b:c": "worker"}, "key must be task_type or task_type:routing_reason"),
        ({"portfolio_review:topic_admision": "lead"}, "unknown routing reason 'topic_admision'"),
        ({"portfolio_reveiw:topic_admission": "lead"}, "unknown task type 'portfolio_reveiw'"),
    ],
)
def test_invalid_entries_are_rejected(table, message) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        load_routing_settings({"task_tiers": table})


def test_task_tiers_must_be_a_table() -> None:
    with pytest.raises(ValueError, match="must be a table"):
        load_routing_settings({"task_tiers": ["replan"]})


def test_known_routing_reasons_cover_the_dispatching_constants() -> None:
    from openlabs import assets, owner, program_autonomy, program_flow, reopen

    constants = {
        program_flow.ADMISSION_ROUTING_REASON, program_flow.SCOUT_ROUTING_REASON,
        owner.ROUTING_FIRST, owner.ROUTING_CONTINUE, owner.ROUTING_CONVERTED,
        owner.ROUTING_REVIEW, owner.ROUTING_REVIEWED, owner.ROUTING_RECOMPUTE,
        owner.ROUTING_RECOMPUTED, owner.ROUTING_RETRY, reopen.ROUTING_REOPENED,
        reopen.ROUTING_OPERATOR_REOPEN,
        program_autonomy.DIRECTION_ROUTING_REASON, program_autonomy.TARGETED_ROUTING,
        program_autonomy.RETARGET_ROUTING, program_autonomy.RELEASE_FIX_ROUTING,
        program_autonomy.RELEASE_REVIEW_ROUTING, assets.RETROSPECTIVE_ROUTING_REASON,
    }
    assert constants <= KNOWN_ROUTING_REASONS
    for key in DEFAULT_TASK_TIERS:
        if ":" in key:
            assert key.split(":", 1)[1] in KNOWN_ROUTING_REASONS


def test_dispatch_points_take_their_runner_from_the_table() -> None:
    """No enqueue in the dispatching modules writes a literal tier alias any more."""

    literal = re.compile(r'runner="(frontier|balanced|cheap)"')
    for name in ("owner.py", "portfolio.py", "program_autonomy.py", "program_flow.py",
                 "assets.py", "engine.py"):
        text = (SRC / name).read_text(encoding="utf-8")
        assert not literal.search(text), name
        if name != "engine.py":
            assert "dispatch_runner(" in text, name


# ------------------------------------------------- independence inside the tier


def _admission(paths, db, task_id: str, *, scout_provider: str, producer: str) -> None:
    packet = paths.artifacts / f"{task_id}.json"
    packet.parent.mkdir(parents=True, exist_ok=True)
    packet.write_text(json.dumps({"producer_model": producer,
                                  "producer_models": [producer]}), encoding="utf-8")
    settings = _settings()
    _enqueue(db, task_id, task_id, task_type="portfolio_review", agent_role="reviewer",
             runner=dispatch_runner(settings, "portfolio_review", "topic_admission", "frontier"),
             exclude_provider=scout_provider, input_path=str(packet),
             routing_reason="topic_admission")


def test_sol_scout_cards_are_admitted_by_opus(tmp_path) -> None:
    paths, db = _setup(tmp_path)
    settings = _settings()
    _fresh(db, settings)
    _admission(paths, db, "admit", scout_provider=GPT, producer="gpt-6.2-sol")
    task, _router = _claim(db, settings)
    assert task["runner"] == "worker_claude"
    event = _routed_events(db, "admit")[0]
    assert event["requested_tier"] == "worker" and event["model"] == "claude-opus-5-5"
    assert event["task_class"] == "review"  # a worker-tier decision type counts as review


def test_opus_scout_cards_are_admitted_by_sol(tmp_path) -> None:
    paths, db = _setup(tmp_path)
    settings = _settings()
    _fresh(db, settings)
    _admission(paths, db, "admit", scout_provider=CLAUDE, producer="claude-opus-5-5")
    task, _router = _claim(db, settings)
    assert task["runner"] == "worker_gpt"
    assert _routed_events(db, "admit")[0]["model"] == "gpt-6.2-sol"


@pytest.mark.parametrize(("owner_runner", "reviewer"),
                         [("worker_gpt", "worker_claude"), ("worker_claude", "worker_gpt")])
def test_recompute_review_goes_to_the_other_worker(tmp_path, owner_runner, reviewer) -> None:
    _paths, db = _setup(tmp_path)
    settings = _settings()
    _fresh(db, settings)
    _enqueue(db, "seat", "c", runner=owner_runner, task_type="topic_owner")
    _enqueue(db, "review", "c", task_type="paper_review", agent_role="reviewer", priority=5,
             runner=dispatch_runner(settings, "paper_review", "owner_recompute_review",
                                    "frontier"),
             parent_task_id="seat", routing_reason="owner_recompute_review")
    task, _router = _claim(db, settings)
    assert task["task_id"] == "review" and task["runner"] == reviewer
    event = _routed_events(db, "review")[0]
    assert event["requested_tier"] == "worker" and event["tier"] == "worker"
    assert "independence" not in event  # cross-family, no fallback


def test_sol_author_falls_back_up_to_astra_when_claude_is_out(tmp_path) -> None:
    paths, db = _setup(tmp_path)
    settings = _settings()
    _record(db, settings, "lead_gpt", {"seven_day": 0.05})
    _record(db, settings, "lead_claude",
            {"five_hour": 0.2, "seven_day": 0.95, "seven_day_overage_included": 0.2})
    _admission(paths, db, "admit", scout_provider=GPT, producer="gpt-6.2-sol")
    task, _router = _claim(db, settings)
    assert task["runner"] == "lead_gpt"  # astra: up, not down to luna, never sol itself
    event = _routed_events(db, "admit")[0]
    assert event["independence"] == "same_family_different_model"
    assert event["independence_fallback"] == "other_family_quota_unavailable"
    assert event["tier_changed_for_independence"] == {"from": "worker", "to": "lead"}
    assert event["producer_model"] == "gpt-6.2-sol" and event["model"] == "gpt-6.2-astra"


def test_opus_author_falls_back_up_to_fable_when_codex_is_out(tmp_path) -> None:
    _paths, db = _setup(tmp_path)
    settings = _settings()
    _record(db, settings, "lead_gpt", {"seven_day": 0.95})
    _record(db, settings, "lead_claude",
            {"five_hour": 0.05, "seven_day": 0.05, "seven_day_overage_included": 0.05})
    _enqueue(db, "seat", "c", runner="worker_claude", task_type="topic_owner")
    _enqueue(db, "review", "c", task_type="paper_review", agent_role="reviewer", priority=5,
             runner="balanced", parent_task_id="seat",
             routing_reason="owner_recompute_review")
    task, _router = _claim(db, settings)
    assert task["task_id"] == "review" and task["runner"] == "lead_claude"
    event = _routed_events(db, "review")[0]
    assert event["producer_model"] == "claude-opus-5-5" and event["model"] == "claude-fable-5-2"
    assert event["tier_changed_for_independence"] == {"from": "worker", "to": "lead"}
    assert event["task_class"] == "review"  # Fable's review ceiling applies


def test_fable_fallback_respects_its_review_ceiling(tmp_path) -> None:
    _paths, db = _setup(tmp_path)
    settings = _settings()
    _record(db, settings, "lead_gpt", {"seven_day": 0.95})
    # Fable above lead_review_ceiling (0.60): the review may not take it.
    _record(db, settings, "lead_claude",
            {"five_hour": 0.05, "seven_day": 0.30, "seven_day_overage_included": 0.65})
    _enqueue(db, "seat", "c", runner="worker_claude", task_type="topic_owner")
    _enqueue(db, "review", "c", task_type="paper_review", agent_role="reviewer", priority=5,
             runner="balanced", parent_task_id="seat",
             routing_reason="owner_recompute_review")
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    # Fable is configured but out of its review allowance: the review waits; it is
    # neither given to the author's Opus nor pushed down to Haiku.
    assert router.route(db.task("review"), {}) is None
    deferred = router.deferred["review"]
    assert deferred["reason"] == "no_runner_available"
    assert deferred["independence"] == "same_family_different_model"


def test_multiple_producer_models_are_all_avoided(tmp_path) -> None:
    paths, db = _setup(tmp_path)
    settings = _settings()
    _record(db, settings, "lead_gpt", {"seven_day": 0.05})
    _record(db, settings, "lead_claude",
            {"five_hour": 0.2, "seven_day": 0.95, "seven_day_overage_included": 0.2})
    packet = paths.artifacts / "mixed.json"
    packet.parent.mkdir(parents=True, exist_ok=True)
    packet.write_text(json.dumps({"producer_model": None,
                                  "producer_models": ["gpt-6.2-astra", "gpt-6.2-sol"]}),
                      encoding="utf-8")
    _enqueue(db, "admit", "a", task_type="portfolio_review", agent_role="reviewer",
             runner="balanced", exclude_provider=GPT, input_path=str(packet),
             routing_reason="topic_admission")
    task, _router = _claim(db, settings)
    assert task["runner"] == "light_gpt"  # the only GPT model that wrote none of the cards


def test_direction_decision_stays_on_lead(tmp_path) -> None:
    _paths, db = _setup(tmp_path)
    settings = _settings()
    _fresh(db, settings)
    _enqueue(db, "decide", "d", task_type="direction_decision", agent_role="reviewer",
             runner=dispatch_runner(settings, "direction_decision", "direction_decision",
                                    "balanced"),
             exclude_provider=GPT, routing_reason="direction_decision")
    task, _router = _claim(db, settings)
    assert task["runner"] == "lead_claude"
    event = _routed_events(db, "decide")[0]
    assert event["requested_tier"] == "lead" and event["task_class"] == "decision"


# ---------------------------------------------------------- quota classes


def test_task_class_of_a_downgraded_decision_type() -> None:
    settings = FactorySettings()
    admission = {"task_type": "portfolio_review", "routing_reason": "topic_admission"}
    assert budget_control.task_class(settings, admission) == "review"
    assert budget_control.task_class(
        settings, {**admission, "runner_request": "lead"}) == "decision"
    assert budget_control.task_class(
        settings, {"task_type": "direction_decision"}) == "decision"
    lead_admission = replace(settings, routing=load_routing_settings(
        {"task_tiers": {"portfolio_review:topic_admission": "lead"}}))
    assert budget_control.task_class(lead_admission, admission) == "decision"


def test_lead_shortage_no_longer_pauses_worker_admission_and_scouting(tmp_path) -> None:
    paths, db = _setup(tmp_path)
    settings = _settings()
    _fresh(db, settings)
    router = budget_control.QuotaRouter.build(db, settings, now=NOW)
    router.lead_short = True  # no lead can take a decision
    _enqueue(db, "scout", "s", task_type="topic_scout", runner="balanced")
    assert router.route(db.task("scout"), {})["tier"] == "worker"
    assert "scout" not in router.deferred
    assert router.lead_summary()["paused_task_types"] == []

    lead_gate = replace(settings, routing=replace(
        settings.routing,
        task_tiers={**settings.routing.task_tiers, "portfolio_review:topic_admission": "lead"}))
    router = budget_control.QuotaRouter.build(db, lead_gate, now=NOW)
    router.lead_short = True
    assert router.route(db.task("scout"), {}) is None
    assert router.deferred["scout"]["reason"] == "lead_quota_short"
    assert "topic_scout" in router.lead_summary()["paused_task_types"]


# ---------------------------------------------- card author across a repair


def test_repaired_card_keeps_its_scout_as_author() -> None:
    from openlabs.program_flow import card_author

    scout = {"topic_id": "t1", "proposer_provider": GPT, "source_task_id": "scout-1"}
    legacy_repair = {"topic_id": "t2", "proposer_provider": CLAUDE,
                     "source_task_id": "repair-1", "repair_of": "t1"}
    new_repair = {"topic_id": "t3", "proposer_provider": GPT, "source_task_id": "repair-2",
                  "repair_of": "t1", "proposer_task_id": "scout-1"}
    document = {"topics": [scout, legacy_repair, new_repair]}
    assert card_author(scout, document) == (GPT, "scout-1")
    assert card_author(legacy_repair, document) == (GPT, "scout-1")
    assert card_author(new_repair, document) == (GPT, "scout-1")
    # Without the ledger the record is taken as it stands.
    assert card_author(legacy_repair) == (CLAUDE, "repair-1")


# -------------------------------------------------------- report and prices


def test_division_of_labour_table() -> None:
    settings = _settings()
    env = {"OPENLABS_AGENT_COMMAND_WORKER_GPT_JSON":
           json.dumps(["codex", "exec", "-m", "gpt-6.1-sol", "-"]),
           "OPENLABS_AGENT_COMMAND_LEAD_GPT_JSON":
           json.dumps(["codex", "exec", "-m", "gpt-6.2-astra", "-"])}
    table = division_of_labour(settings, env)
    assert table["tiers"]["lead"]["models"] == {CLAUDE: "claude-fable-5-2", GPT: "gpt-6.2-astra"}
    assert table["tiers"]["worker"]["models"] == {CLAUDE: "claude-opus-5-5", GPT: "gpt-6.2-sol"}
    assert "portfolio_review:topic_admission" in table["tiers"]["worker"]["tasks"]
    assert "direction_decision" in table["tiers"]["lead"]["tasks"]
    assert table["overrides"] == {}
    assert table["argv_model_mismatch"] == {
        "worker_gpt": {"configured": "gpt-6.2-sol", "argv": "gpt-6.1-sol"}}
    assert argv_model("light_gpt", env) is None


def test_runner_model_warnings_flag_mismatch_and_fable() -> None:
    """NC trial 2026-11-25: a toml/env model mismatch (and Fable) is reported every tick."""

    settings = _settings()
    env = {"OPENLABS_AGENT_COMMAND_WORKER_GPT_JSON":
           json.dumps(["codex", "exec", "-m", "gpt-6.1-sol", "-"]),
           "OPENLABS_AGENT_RESUME_COMMAND_WORKER_CLAUDE_JSON":
           json.dumps(["claude", "-p", "--resume", "{session_id}", "--model", "claude-fable-5-2"]),
           "OPENLABS_AGENT_COMMAND_LIGHT_CLAUDE_JSON":
           json.dumps(["claude", "-p", "--model", "claude-haiku-5-5"])}
    warnings = runner_model_warnings(settings, env)
    text = "\n".join(warnings)
    assert "OPENLABS_AGENT_COMMAND_WORKER_GPT_JSON runs --model gpt-6.1-sol" in text
    assert "[runners.worker_gpt].model is gpt-6.2-sol" in text
    assert "OPENLABS_AGENT_RESUME_COMMAND_WORKER_CLAUDE_JSON runs --model claude-fable-5-2" in text
    assert "OPENLABS_AGENT_RESUME_COMMAND_WORKER_CLAUDE_JSON names a claude-fable-* model" in text
    assert "[runners.lead_claude].model claude-fable-5-2" in text  # the toml runner itself
    assert not any("light_claude" in item or "LIGHT_CLAUDE" in item for item in warnings)
    clean = replace(settings, runners={
        name: replace(spec, model="claude-opus-5-5") if spec.model == "claude-fable-5-2" else spec
        for name, spec in settings.runners.items()})
    assert runner_model_warnings(clean, {
        "OPENLABS_AGENT_COMMAND_WORKER_GPT_JSON":
        json.dumps(["codex", "exec", "-m", "gpt-6.2-sol", "-"])}) == []


def test_newest_gpt_versions_are_priced() -> None:
    for model in (
        "gpt-6.2-sol", "gpt-6.2-astra", "gpt-6-luna", "gpt-6.2-sol[1m]",
        "gemini-4-neon-xhigh", "gemini-4-hydrogen-high", "gemini-3.8-flash-medium",
        "claude-opus-5-5-high", "claude-sonnet-5-5",
    ):
        assert usage._price(DEFAULT_MODEL_PRICES, model) is not None, model
    assert usage._price(DEFAULT_MODEL_PRICES, "gpt-6.2-astra").output == 40.0
    # The older versions stay priced for attempts recorded under them.
    assert usage._price(DEFAULT_MODEL_PRICES, "gpt-6.1-sol") is not None


def test_routing_settings_default_table_is_the_code_table() -> None:
    assert RoutingSettings().task_tiers == DEFAULT_TASK_TIERS
