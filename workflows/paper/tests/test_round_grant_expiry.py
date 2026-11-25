"""B4 (2026-11-25): round grants expire; no new rounds after a stall; per-paper round usage."""

import json

import pytest

from paper_writing import review_flow as flow
from test_review_round_limits import BIO, TARGET, authorized_metadata, config


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setattr(flow, "review_config", lambda root: dict(config(), max_rounds_per_target=4))


def _decisions(root, rows, target=TARGET):
    base = flow.runs_dir(root, BIO)
    for index, row in enumerate(rows):
        path = base / f"2026112{index % 10}T00000{index}Z-{index:04d}" / "decision.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"target_journal": target, "stage_reached": "decision", **row}
        path.write_text(json.dumps(record))


def _round(outcome="revision_required", **extra):
    return {"merged": {"outcome": outcome, **extra.pop("merged", {})}, **extra}


def test_grant_stays_active_while_the_review_is_in_progress(tmp_path):
    _decisions(tmp_path, [_round(), _round()])
    grant = flow.review_round_limit_override(authorized_metadata(tmp_path), tmp_path, BIO)
    assert grant["max_rounds_per_target"] == 20
    assert grant["expiry"]["status"] == "active"
    assert grant["expiry"]["condition"]["source"] == "default"


def test_grant_expires_at_ready_and_keeps_the_rounds_used(tmp_path):
    _decisions(tmp_path, [_round()] * 6 + [_round("ready")])
    grant = flow.review_round_limit_override(authorized_metadata(tmp_path), tmp_path, BIO)
    assert grant["expiry"]["status"] == "expired"
    assert grant["max_rounds_per_target"] == 7 and grant["granted_max_rounds_per_target"] == 20
    # Never below the standing per-target rule.
    other = tmp_path / "b"
    other.mkdir()
    _decisions(other, [_round("ready")])
    meta = authorized_metadata(other)
    assert flow.review_round_limit_override(meta, other, BIO)["max_rounds_per_target"] == 4


def test_final_ruling_allows_only_the_one_final_check_then_nothing(tmp_path):
    ruling = {"final_ruling": {"basis": {"criterion": "blocking_count_not_falling"},
                               "must_fix": ["x"], "advice": []}}
    _decisions(tmp_path, [_round()] * 7 + [_round(merged=ruling)])
    grant = flow.review_round_limit_override(authorized_metadata(tmp_path), tmp_path, BIO)
    assert grant["expiry"]["latest_state"] == "stalled"
    assert grant["max_rounds_per_target"] == 9   # 8 used + the final check
    _decisions(tmp_path, [_round()] * 7 + [_round(merged=ruling),
                                           _round(final_check=True, merged={"stalled": True})])
    grant = flow.review_round_limit_override(authorized_metadata(tmp_path), tmp_path, BIO)
    assert grant["max_rounds_per_target"] == 9   # 9 used: the final check ran; no further round


def test_no_new_grant_after_a_stall(tmp_path):
    # The stall was decided under a 10-round limit; a later grant of 20 is refused.
    ruling = {"final_ruling": {"basis": {}, "must_fix": ["x"], "advice": []}}
    _decisions(tmp_path, [_round()] * 9 + [_round(merged=ruling,
                                                  review_round_limit_override={"max_rounds_per_target": 10})])
    grant = flow.review_round_limit_override(authorized_metadata(tmp_path), tmp_path, BIO)
    refused = grant["expiry"]["extension_refused"]
    assert refused["requested"] == 20 and refused["limit_at_stall"] == 10
    assert "停滞后，不再追加" in refused["reason"]
    assert grant["max_rounds_per_target"] == 11  # 10 used + the final check, never 20


def test_explicit_until_ends_the_grant(tmp_path):
    _decisions(tmp_path, [_round()] * 5)
    meta = authorized_metadata(tmp_path)
    meta["review_round_limit_override"]["expires"] = {"on_decision": ["ready", "stalled"],
                                                     "until": "2026-01-01", "cycle": "polish"}
    grant = flow.review_round_limit_override(meta, tmp_path, BIO)
    assert grant["expiry"]["status"] == "expired" and grant["max_rounds_per_target"] == 5
    meta["review_round_limit_override"]["expires"] = {"on_decision": ["accepted"]}
    with pytest.raises(ValueError):
        flow.review_round_limit_override(meta, tmp_path, BIO)


def test_round_usage_reports_this_target_and_the_cross_journal_total(tmp_path, monkeypatch):
    _decisions(tmp_path, [_round()] * 4, target="First Journal")
    base = flow.runs_dir(tmp_path, BIO)
    for index in range(3):
        path = base / f"20261125T00000{index}Z-b{index}" / "decision.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"target_journal": TARGET, "stage_reached": "decision",
                                    "merged": {"outcome": "ready" if index == 2 else "x"}}))
    technical = base / "20261125T000009Z-t" / "decision.json"
    technical.parent.mkdir(parents=True)
    technical.write_text(json.dumps({"target_journal": TARGET, "stage_reached": "decision",
                                     "consumes_scientific_round": False, "merged": {}}))
    meta = authorized_metadata(tmp_path)
    monkeypatch.setattr(flow, "load_paper_metadata", lambda *args: meta)
    usage = flow.round_usage(tmp_path, BIO)
    assert usage["used_at_target"] == 3 and usage["all_targets_total"] == 7
    assert usage["per_target"] == {"First Journal": 4, TARGET: 3}
    assert usage["limit"] == 4 and usage["granted"] == 20 and usage["grant_status"] == "expired"
