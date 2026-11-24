"""Clean-up A (2026-11-24): code defaults follow the user's decisions, and an expired
temporary panel kept only as a historical binding selects the same panel as before."""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest
from paper_writing import review_flow as flow
from paper_writing import review_round_guard, temporary_panels

from test_temporary_panels import FABLE, SETTINGS, SINCE, SOL, UNTIL


def test_round_cooldown_defaults_to_zero() -> None:
    # User 2026-11-23 ("我记得删除了这条限制啊"): no waiting time between rounds.
    assert review_round_guard.settings({})["cooldown_hours"] == 0
    assert review_round_guard.settings({"round_cooldown_hours": 3})["cooldown_hours"] == 3


def test_max_rounds_per_target_defaults_to_four(monkeypatch) -> None:
    # User 2026-11-11: 4 completed scientific rounds per target journal.
    data = copy.deepcopy(SETTINGS)
    data["review"].pop("max_rounds_per_target", None)
    monkeypatch.setattr(flow, "load_review_settings", lambda root: data)
    assert flow.review_config("unused")["max_rounds_per_target"] == 4
    data["review"]["max_rounds_per_target"] = 6
    assert flow.review_config("unused")["max_rounds_per_target"] == 6


def _as_history(settings: dict) -> dict:
    """The expired temporary panel rewritten as an equivalent previous_panels entry."""
    data = copy.deepcopy(settings)
    entry = data["review"].pop("temporary_panels")[0]
    data["review"]["previous_panels"].append({
        "valid_for_reviews_started_from": entry["since"],
        "valid_for_reviews_started_before": entry["until"],
        "cross_model_basis": entry["cross_model"]["basis"],
        "referee_roles": ["referee_a", "referee_b"],
        "roles": entry["roles"]})
    return data


def _selected(monkeypatch, data, record):
    monkeypatch.setattr(flow, "load_review_settings", lambda root: data)
    config = flow.policy_for_record(record, flow.review_config("unused"))
    return config["roles"], config["referee_roles"], flow.cross_model_basis(config)


@pytest.mark.parametrize("started", [
    SINCE - timedelta(days=3), SINCE - timedelta(seconds=1), SINCE, SINCE + timedelta(hours=5),
    UNTIL - timedelta(seconds=1), UNTIL, UNTIL + timedelta(hours=2), None])
def test_expired_temporary_panel_as_history_binds_the_same_panel(monkeypatch, started) -> None:
    monkeypatch.setattr(temporary_panels, "now", lambda: UNTIL + timedelta(days=1))
    record = {"active_referee_roles": ["referee_a", "referee_b"],
              "started_at": started.isoformat() if started else None}
    before = _selected(monkeypatch, copy.deepcopy(SETTINGS), record)
    after = _selected(monkeypatch, _as_history(SETTINGS), record)
    assert before == after
    if started is not None and SINCE <= started < UNTIL:
        assert before[0]["referee_a"] == SOL and before[2] == "model"
    elif started is not None and started < SINCE:
        assert before[0]["referee_a"] == FABLE
