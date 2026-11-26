"""Prescreens ask for Gemini first (user 2026-11-26: "派给gemini").

``[program.funnel].prescreen_runners`` names the runners a prescreen asks for, in order; the
first one outside the card proposer's model family goes into the packet as
``preferred_runner``. The router takes it when quota and parallelism allow, else routes as usual.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import test_nc_funnel as nc
import test_quota_routing as routing
import test_research_program_flow as flow
from test_scout_breadth import GEMINI

from openlabs import budget as budget_control
from openlabs import nc_funnel
from openlabs.config import load_program_settings
from openlabs.program import open_topic_ledger

ORDER = ("worker_gemini", "worker_claude")


def _settings_with(settings, **funnel):
    program = settings.program
    return replace(settings, runners={**settings.runners, "worker_gemini": GEMINI},
                   program=replace(program, funnel=replace(program.funnel, **funnel)))


def test_config_reads_prescreen_runners() -> None:
    program = load_program_settings({"funnel": {"prescreen_runners": list(ORDER)}})
    assert program.funnel.prescreen_runners == ORDER
    assert load_program_settings({}).funnel.prescreen_runners == ()


def test_first_runner_outside_the_proposer_family() -> None:
    settings = _settings_with(flow._settings(), prescreen_runners=ORDER)
    assert nc_funnel.preferred_prescreen_runner(settings, "openai-codex") == "worker_gemini"
    assert nc_funnel.preferred_prescreen_runner(settings, None) == "worker_gemini"
    # A Gemini card is never prescreened by Gemini (independence): the next one.
    assert nc_funnel.preferred_prescreen_runner(settings, "google") == "worker_claude"
    only = _settings_with(flow._settings(), prescreen_runners=("worker_gemini",))
    assert nc_funnel.preferred_prescreen_runner(only, "google") is None
    assert nc_funnel.preferred_prescreen_runner(flow._settings(), "openai-codex") is None


def test_prescreen_packet_carries_the_preference(tmp_path, monkeypatch) -> None:
    paths, db, settings = nc._setup(tmp_path)
    settings = _settings_with(settings, prescreen_runners=ORDER)
    _, report = flow._scout_round(paths, db, settings, monkeypatch, [nc._nc_card(0)])
    assert report.errors == [], report.errors
    ledger = open_topic_ledger(paths, settings.program)
    topic = ledger.topic(report.program["cards_registered"][0]["topic_id"])
    task = db.task(topic["card_check"]["prescreen"]["task_id"])
    packet = json.loads(Path(task["input_path"]).read_text())
    expected = nc_funnel.preferred_prescreen_runner(settings, task["exclude_provider"] or None)
    assert expected and packet["preferred_runner"] == expected


def test_router_takes_the_preferred_prescreen_runner_and_falls_back(tmp_path) -> None:
    paths, db = routing._setup(tmp_path)
    settings = replace(routing._settings(), runners={**routing.RUNNERS, "worker_gemini": GEMINI})
    routing._record(db, settings, "worker_gpt", {"seven_day": 0.1})
    routing._record(db, settings, "worker_claude", {"five_hour": 0.2, "seven_day": 0.2})
    budget_control.record_quota_snapshot(db, settings, routing._snapshot(
        "google-antigravity", GEMINI.model, {"gemini-weekly": 0.1}), runner="worker_gemini")
    packet = paths.data / "p1.json"
    packet.write_text(json.dumps({"preferred_runner": "worker_gemini"}))
    routing._enqueue(db, "p1", "c1", task_type="topic_prescreen", input_path=str(packet),
                     routing_reason="topic_prescreen", exclude_provider="openai-codex")
    task, router = routing._claim(db, settings)
    assert task["runner"] == "worker_gemini"
    assert router.decisions["p1"]["preferred_runner"] == "worker_gemini"

    # Gemini out of quota: routed as usual, never to the proposer's family.
    paths2, db2 = routing._setup(tmp_path / "b")
    routing._record(db2, settings, "worker_gpt", {"seven_day": 0.1})
    routing._record(db2, settings, "worker_claude", {"five_hour": 0.2, "seven_day": 0.2})
    budget_control.record_quota_snapshot(db2, settings, routing._snapshot(
        "google-antigravity", GEMINI.model, {"gemini-weekly": 0.99, "gemini-5h": 0.99}),
        runner="worker_gemini")
    packet2 = paths2.data / "p2.json"
    packet2.write_text(json.dumps({"preferred_runner": "worker_gemini"}))
    routing._enqueue(db2, "p2", "c2", task_type="topic_prescreen", input_path=str(packet2),
                     routing_reason="topic_prescreen", exclude_provider="openai-codex")
    task, router = routing._claim(db2, settings)
    assert task["runner"] == "worker_claude"
    assert router.decisions["p2"]["preferred_runner_unavailable"] == "worker_gemini"
