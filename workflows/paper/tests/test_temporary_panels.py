"""review.temporary_panels (user 2026-11-20): GPT-only panel until a fixed time, then the
standard cross-family panel again; a review stays bound to the panel it started under."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from paper_writing import editorial_rewrite as er
from paper_writing import review_flow as flow
from paper_writing import temporary_panels

UNTIL = datetime(2026, 11, 23, 11, 0, tzinfo=UTC)
SINCE = datetime(2026, 11, 20, 8, 30, 42, tzinfo=UTC)
BEFORE, AFTER = UNTIL - timedelta(hours=1), UNTIL + timedelta(hours=1)


def _role(provider, model):
    tool = "Codex" if provider == "openai-codex" else "Claude Code"
    return {"provider": provider, "tool": tool, "model": model}


ASTRA, SOL = _role("openai-codex", "gpt-6.2-astra"), _role("openai-codex", "gpt-6.2-sol")
FABLE, OPUS = _role("anthropic", "claude-fable-5-2"), _role("anthropic", "claude-opus-5-5")
SETTINGS = {
    "quality_gate": {"review_process": "unified_v1", "editorial_rewrite": {
        "rewriters": {"gpt": SOL, "opus": OPUS}, "judges": {"gpt": SOL, "opus": OPUS}}},
    "review": {
        "referee_roles": ["referee_a", "referee_b"],
        "cross_model": {"required": True},
        "roles": {"editor": ASTRA, "referee_a": FABLE, "referee_b": ASTRA, "formal_verifier": SOL},
        "previous_panels": [{"valid_for_reviews_started_before": SINCE.isoformat(),
                             "referee_roles": ["referee_a", "referee_b"],
                             "roles": {"editor": ASTRA, "referee_a": FABLE, "referee_b": ASTRA}}],
        "temporary_panels": [{
            "since": SINCE.isoformat(), "until": UNTIL.isoformat(),
            "authorization": {"actor": "user", "date": "2026-11-20",
                              "quote": "取消claude的临时放宽，后面的活都派给gpt"},
            "cross_model": {"basis": "model"},
            "roles": {"editor": ASTRA, "referee_a": SOL, "referee_b": ASTRA, "formal_verifier": SOL},
            "editorial_rewrite": {"rewriters": {"gpt": SOL, "astra": ASTRA},
                                  "judges": {"gpt": SOL, "astra": ASTRA}}}],
    },
}


@pytest.fixture
def settings(monkeypatch):
    data = copy.deepcopy(SETTINGS)
    monkeypatch.setattr(flow, "load_registry_settings", lambda root: data)
    monkeypatch.setattr(er, "load_registry_settings", lambda root: data)
    monkeypatch.setattr(er, "settings_path", lambda root: Path(__file__))
    return data


def _at(monkeypatch, moment):
    monkeypatch.setattr(temporary_panels, "now", lambda: moment)


def test_before_the_deadline_the_temporary_gpt_panel_applies(settings, monkeypatch):
    _at(monkeypatch, BEFORE)
    config = flow.review_config("x")
    assert config["roles"]["referee_a"]["model"] == "gpt-6.2-sol"
    assert config["cross_model_basis"] == "model"
    assert config["temporary_panel"]["until"] == UNTIL.isoformat()
    assert flow.cross_model_blockers(config, "gpt-6.2-sol") == []
    assert flow.cross_model_independence(config, "openai", "gpt-6.2-sol") == "same_family_different_model"
    rewrite = er.rewrite_config(Path("x"))
    assert set(rewrite["judges"]) == {"gpt", "astra"}
    assert rewrite["judge_independence"] == "same_family_different_model"


def test_after_the_deadline_the_standard_cross_family_panel_returns(settings, monkeypatch):
    _at(monkeypatch, AFTER)
    config = flow.review_config("x")
    assert config["roles"]["referee_a"]["model"] == "claude-fable-5-2"
    assert config["cross_model_basis"] == "model_family" and config["temporary_panel"] is None
    assert flow.cross_model_independence(config, "openai", "gpt-6.2-sol") == "cross_family"
    rewrite = er.rewrite_config(Path("x"))
    assert set(rewrite["judges"]) == {"gpt", "opus"}
    assert rewrite["judge_independence"] == "cross_family"


def test_a_review_stays_bound_to_the_panel_it_started_under(settings, monkeypatch):
    _at(monkeypatch, AFTER)
    config = flow.review_config("x")
    panel = ["referee_a", "referee_b"]
    during = flow.policy_for_record({"started_at": BEFORE.isoformat(),
                                     "active_referee_roles": panel}, config)
    assert during["roles"]["referee_a"]["model"] == "gpt-6.2-sol"
    assert during["cross_model_basis"] == "model"
    assert flow.cross_model_blockers(during, "gpt-6.2-sol") == []
    earlier = flow.policy_for_record({"started_at": (SINCE - timedelta(minutes=5)).isoformat(),
                                      "active_referee_roles": panel}, config)
    assert earlier["roles"]["referee_a"]["model"] == "claude-fable-5-2"
    later = flow.policy_for_record({"started_at": AFTER.isoformat(),
                                    "active_referee_roles": panel}, config)
    assert later["roles"]["referee_a"]["model"] == "claude-fable-5-2"
    # The policy hash of a review started under the temporary panel still matches.
    _at(monkeypatch, BEFORE)
    started = flow.review_config("x")
    assert flow.review_policy_sha256(started) == flow.review_policy_sha256(during)


def test_both_panels_are_validated_when_the_settings_load(settings, monkeypatch):
    _at(monkeypatch, AFTER)
    settings["review"]["temporary_panels"][0]["roles"]["referee_a"] = dict(ASTRA)
    with pytest.raises(ValueError, match="different models"):
        flow.review_config("x")
    settings["review"]["temporary_panels"][0]["roles"]["referee_a"] = dict(SOL)
    del settings["review"]["temporary_panels"][0]["authorization"]["quote"]
    with pytest.raises(ValueError, match="actor, date and quote"):
        flow.review_config("x")


def test_temporary_judges_need_two_models(settings, monkeypatch):
    _at(monkeypatch, AFTER)
    settings["review"]["temporary_panels"][0]["editorial_rewrite"]["judges"] = {"a": SOL, "b": dict(SOL)}
    with pytest.raises(ValueError, match="at least two different models"):
        er.rewrite_config(Path("x"))


def test_until_needs_a_zone(settings, monkeypatch):
    _at(monkeypatch, BEFORE)
    settings["review"]["temporary_panels"][0]["until"] = "2026-11-23T11:00:00"
    with pytest.raises(ValueError, match="zone"):
        flow.review_config("x")
