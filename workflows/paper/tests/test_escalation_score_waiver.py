"""Owner score waiver for an escalation target (target_escalation.score_waiver)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from paper_writing import program_delivery, review_flow, venue_policy
from paper_writing.registry import load_paper_metadata, write_paper_metadata

from tests.test_program_delivery import AUTHORS, PAPER, POLICY, _paper, _provisional, _ready

import yaml

VENUE = "Example Top Journal"
TEXT = "Keep the zone-2 target for this paper."


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _waiver(root: Path, *, grant_overrides: dict | None = None, user_text: str = TEXT,
            floor: float = 6) -> dict:
    basis = root / "reviews" / "decision.json"
    basis.parent.mkdir(parents=True, exist_ok=True)
    basis.write_text('{"score": 6}', encoding="utf-8")
    grant = {"kind": venue_policy.SCORE_WAIVER_KIND, "paper_id": PAPER, "target_journal": VENUE,
             "minimum_accepted_score": floor, "authorization": "Owner keeps the escalation target"}
    grant.update(grant_overrides or {})
    receipt = {"schema": "openlabs.actual_author_instruction.v1",
               "source": "actual user message in this session", "user_text": TEXT,
               "authorizations": [grant]}
    path = root / "receipts" / "owner.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return {"venue": VENUE, "authorized_by": "repository owner", "authorized_at": "2026-11-12",
            "user_text": user_text, "minimum_accepted_score": floor,
            "basis_review": {"path": "reviews/decision.json", "sha256": _sha(basis), "score": 6},
            "authorization": {"path": "receipts/owner.json", "sha256": _sha(path),
                              "json_pointer": "/authorizations/0",
                              "summary": "Owner keeps the escalation target"}}


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "registry" / "papers").mkdir(parents=True)
    (tmp_path / "registry" / "settings.yaml").write_text(yaml.safe_dump({
        "schema_version": "ara.paper_writing.registry.v1",
        "journal_target_policy": POLICY, "defaults": {"authors": AUTHORS},
    }), encoding="utf-8")
    return tmp_path


def test_valid_waiver_lowers_the_bar_but_still_needs_a_ready_review(repo: Path) -> None:
    record = _provisional(score_waiver=_waiver(repo))
    paper = _paper(paper_id=PAPER, target_escalation=record)
    assert venue_policy.escalation_minimum(paper, POLICY, paper_id=PAPER, root=repo) == 6
    not_ready = dict(paper, writing_release=dict(_ready(6), status="blocked"))
    assert "not ready" in venue_policy.provisional_escalation_blockers(
        not_ready, POLICY, paper_id=PAPER, root=repo)[0]
    ok = dict(paper, writing_release=_ready(6))
    assert venue_policy.provisional_escalation_blockers(ok, POLICY, paper_id=PAPER, root=repo) == []
    lower = dict(paper, writing_release=_ready(5))
    assert "below the escalation minimum 6" in venue_policy.provisional_escalation_blockers(
        lower, POLICY, paper_id=PAPER, root=repo)[0]
    # Without a waiver the configured bar applies.
    plain = _paper(target_escalation=_provisional(), writing_release=_ready(6))
    assert venue_policy.provisional_escalation_blockers(plain, POLICY, paper_id=PAPER, root=repo)


@pytest.mark.parametrize("mutation", ["other_paper", "other_venue", "other_score", "kind",
                                      "summary", "user_text", "receipt_changed", "basis_changed",
                                      "waiver_venue", "missing_auth"])
def test_invalid_waiver_is_refused_not_ignored(repo: Path, mutation: str) -> None:
    grant = {"other_paper": {"paper_id": "other"}, "other_venue": {"target_journal": "Other"},
             "other_score": {"minimum_accepted_score": 5},
             "kind": {"kind": "something_else"},
             "summary": {"authorization": "different"}}.get(mutation)
    waiver = _waiver(repo, grant_overrides=grant)
    if mutation == "user_text":
        waiver["user_text"] = "different words"
    if mutation == "receipt_changed":
        (repo / "receipts" / "owner.json").write_text("{}", encoding="utf-8")
    if mutation == "basis_changed":
        (repo / "reviews" / "decision.json").write_text("{}", encoding="utf-8")
    if mutation == "waiver_venue":
        waiver["venue"] = "Other"
    if mutation == "missing_auth":
        waiver.pop("authorization")
    paper = _paper(paper_id=PAPER, target_escalation=_provisional(score_waiver=waiver),
                   writing_release=_ready(6))
    blockers = venue_policy.provisional_escalation_blockers(paper, POLICY, paper_id=PAPER, root=repo)
    assert blockers and "score_waiver" in blockers[0]
    with pytest.raises(ValueError, match="score_waiver"):
        venue_policy.escalation_minimum(paper, POLICY, paper_id=PAPER, root=repo)


def test_approved_escalation_validates_with_waiver_only(repo: Path) -> None:
    approved = _provisional(status="approved", approved_by="owner", internal_review_score=6,
                            internal_review_source="reviews/decision.json")
    with pytest.raises(ValueError, match="below the escalation minimum"):
        venue_policy.validate_journal_eligibility(_paper(target_escalation=approved),
                                                  paper_id=PAPER, policy=POLICY, root=repo)
    approved["score_waiver"] = _waiver(repo)
    venue_policy.validate_journal_eligibility(_paper(target_escalation=approved),
                                              paper_id=PAPER, policy=POLICY, root=repo)
    approved["internal_review_score"] = 5
    with pytest.raises(ValueError, match="below the escalation minimum 6"):
        venue_policy.validate_journal_eligibility(_paper(target_escalation=approved),
                                                  paper_id=PAPER, policy=POLICY, root=repo)


def test_confirm_escalation_records_the_applied_waiver(repo: Path) -> None:
    write_paper_metadata(PAPER, _paper(title="T", writing_release=_ready(6),
                                       target_escalation=_provisional(score_waiver=_waiver(repo))), repo)
    confirmed = program_delivery.confirm_escalation(PAPER, root=repo)["target_escalation"]
    assert confirmed["status"] == "approved" and confirmed["internal_review_score"] == 6
    assert confirmed["score_waiver_applied"] == {"configured_minimum": 7.0, "minimum_accepted_score": 6}
    assert confirmed["score_waiver"]["user_text"] == TEXT
    venue_policy.validate_journal_eligibility(load_paper_metadata(PAPER, repo), paper_id=PAPER,
                                              policy=POLICY, root=repo)


def test_review_track_uses_the_waived_bar(repo: Path) -> None:
    meta = _paper(paper_id=PAPER, target_escalation=_provisional(score_waiver=_waiver(repo)))
    track = review_flow.review_track(meta, repo)
    assert track == {"track": "escalation", "minimum_overall_score": 6.0, "score_waiver": True}
    referees = {"referee_a": {"scores": {"overall": 6}, "confidence": "medium"},
                "referee_b": {"scores": {"overall": 7}, "confidence": "medium"}}
    assert review_flow.apply_review_track({"outcome": "ready"}, referees, track)["outcome"] == "ready"
    low = dict(referees, referee_a={"scores": {"overall": 5}, "confidence": "medium"})
    assert review_flow.apply_review_track({"outcome": "ready"}, low, track)["outcome"] == "revision_required"
    unsure = dict(referees, referee_a={"scores": {"overall": 6}, "confidence": "low"})
    assert review_flow.apply_review_track({"outcome": "ready"}, unsure, track)["outcome"] == "revision_required"
    plain = review_flow.review_track(_paper(paper_id=PAPER, target_escalation=_provisional()), repo)
    assert plain == {"track": "escalation", "minimum_overall_score": 7.0}
