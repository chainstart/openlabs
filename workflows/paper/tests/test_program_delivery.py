"""Research-program delivery: provisional escalation, handoff without handler, assignment."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from paper_writing import program_delivery, venue_policy
from paper_writing.__main__ import build_parser
from paper_writing.handoff import _paper_projection
from paper_writing.registry import load_paper_metadata, write_paper_metadata

PAPER = "20261111-ai-health-temporal-retrieval"
POLICY = {
    "venue_eligibility": {
        "effective_from": "2026-11-07",
        "journal": {"required_indexes": ["SCIE"], "allowed_tiers": [1, 2, 3, 4],
                    "routine_tiers": [3, 4]},
        "escalation": {"journal_tiers": [1, 2], "ccf_ranks": ["A"], "minimum_internal_score": 7},
    }
}
AUTHORS = [
    {"name": "First Author", "email": "first@example.test"},
    {"name": "Second Author", "email": "second@example.test"},
    {"name": "Third Author", "email": "third@example.test"},
]


def _paper(**overrides) -> dict:
    paper = {
        "venue_type": "journal",
        "target_journal": "Example Top Journal",
        "target_journal_checked_at": "2026-11-10",
        "target_journal_tier": 1,
        "target_journal_ranking_year": 2025,
        "target_journal_ranking_scope": "major_category",
        "target_journal_fee_policy": "no_mandatory_author_fee",
        "target_journal_indexing": {"indexes": ["SCIE"], "source": "https://mjl.clarivate.com/x",
                                    "checked_at": "2026-11-10"},
    }
    paper.update(overrides)
    return paper


def _provisional(**overrides) -> dict:
    record = {"status": "provisional", "venue": "Example Top Journal",
              "approved_by": "admission:portfolio:abc", "approved_at": "2026-11-10",
              "strength_evidence": "program-control/admissions/t.json (sha256 " + "a" * 64 + ")",
              "fallback_venue": "Journal of Biomedical Informatics"}
    record.update(overrides)
    return record


def _ready(score: float) -> dict:
    return {"status": "ready", "score": score, "decision_record": "reviews/unified/p/r/decision.json",
            "review_process": "unified_v1"}


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    registry = tmp_path / "registry"
    (registry / "papers").mkdir(parents=True)
    (registry / "settings.yaml").write_text(yaml.safe_dump({
        "schema_version": "ara.paper_writing.registry.v1",
        "journal_target_policy": POLICY,
        "defaults": {"authors": AUTHORS},
    }), encoding="utf-8")
    write_paper_metadata(PAPER, _paper(title="Temporal retrieval"), tmp_path)
    return tmp_path


def test_provisional_escalation_is_reviewable_without_a_score() -> None:
    paper = _paper(target_escalation=_provisional())
    venue_policy.validate_journal_eligibility(paper, paper_id=PAPER, policy=POLICY)
    assert venue_policy.is_escalation_venue(paper, POLICY)  # reviewed on the escalation track
    hand_made = _paper(target_escalation=_provisional(approved_by="Someone"))
    with pytest.raises(ValueError, match="admission gate"):
        venue_policy.validate_journal_eligibility(hand_made, paper_id=PAPER, policy=POLICY)
    approved_without_score = _paper(target_escalation=_provisional(status="approved"))
    with pytest.raises(ValueError, match="internal_review_score"):
        venue_policy.validate_journal_eligibility(
            approved_without_score, paper_id=PAPER, policy=POLICY
        )


def test_provisional_escalation_is_not_deliverable_until_the_score_meets_the_bar() -> None:
    paper = _paper(target_escalation=_provisional())
    assert venue_policy.provisional_escalation_blockers(paper, POLICY, paper_id=PAPER)
    low = _paper(target_escalation=_provisional(), writing_release=_ready(6.5))
    assert "below the escalation minimum" in venue_policy.provisional_escalation_blockers(
        low, POLICY, paper_id=PAPER
    )[0]
    ok = _paper(target_escalation=_provisional(), writing_release=_ready(7.5))
    assert venue_policy.provisional_escalation_blockers(ok, POLICY, paper_id=PAPER) == []
    routine = _paper(target_journal_tier=3, target_escalation=_provisional())
    assert venue_policy.provisional_escalation_blockers(routine, POLICY, paper_id=PAPER) == []


def _fallback_evidence(**overrides) -> dict:
    evidence = {
        "venue": "Journal of Biomedical Informatics", "venue_type": "journal",
        "checked_at": "2026-11-12",
        "indexing": {"indexes": ["SCIE"], "source": "https://mjl.clarivate.com/y",
                     "checked_at": "2026-11-12"},
        "tier": 3, "ranking_year": 2025, "ranking_scope": "major_category",
        "ranking_category": "医学", "ranking_source": "https://www.letpub.com.cn/y",
        "fee_policy": "no_mandatory_author_fee", "fee_source": "https://example.org/costs",
        "fee_charges_checked": ["apc", "page_charge", "colour_charge", "submission_fee"],
        "fee_evidence": "There are no page or colour charges and no submission fee.",
    }
    evidence.update(overrides)
    return evidence


def test_register_and_confirm_escalation(repo: Path) -> None:
    record = repo / "admission.json"
    record.write_text("{}", encoding="utf-8")
    registered = program_delivery.register_provisional_escalation(
        PAPER, root=repo, venue="Example Top Journal", admission_task_id="portfolio:abc",
        admission_record=record, fallback_venue="Journal of Biomedical Informatics",
        fallback_evidence=_fallback_evidence(),
    )["target_escalation"]
    assert registered["status"] == "provisional"
    assert registered["fallback_eligibility"]["tier"] == 3
    assert registered["approved_by"] == "admission:portfolio:abc"
    assert len(registered["strength_evidence_sha256"]) == 64
    with pytest.raises(program_delivery.ProgramDeliveryError):
        program_delivery.confirm_escalation(PAPER, root=repo)  # no ready review yet
    metadata = load_paper_metadata(PAPER, repo)
    metadata["writing_release"] = _ready(8)
    write_paper_metadata(PAPER, metadata, repo)
    confirmed = program_delivery.confirm_escalation(PAPER, root=repo)["target_escalation"]
    assert confirmed["status"] == "approved" and confirmed["internal_review_score"] == 8
    assert confirmed["internal_review_source"] == "reviews/unified/p/r/decision.json"
    venue_policy.validate_journal_eligibility(
        load_paper_metadata(PAPER, repo), paper_id=PAPER, policy=POLICY
    )


def test_deliver_marks_owner_review_without_a_handler(repo: Path) -> None:
    metadata = load_paper_metadata(PAPER, repo)
    metadata.update(writing_release=_ready(8), target_escalation=_provisional())
    write_paper_metadata(PAPER, metadata, repo)
    calls: list[str] = []

    def fake_release(paper_id, *, root, client):
        calls.append(paper_id)
        assert client == "fake-client"
        return {"paper_id": paper_id, "package_id": "pkg-1", "version": "1.0.0",
                "receipt": "papers/x/releases/pkg-1.json"}

    result = program_delivery.deliver(PAPER, root=repo, client="fake-client",
                                      release=fake_release)
    assert calls == [PAPER]
    assert result["submission_handler"] is None and result["awaiting_owner_review"] is True
    assert result["escalation_confirmed"] is True
    stored = load_paper_metadata(PAPER, repo)
    assert stored["delivery"]["awaiting_owner_review"] is True
    assert stored["delivery"]["submission_handler"] is None
    assert "submission_contact" not in stored
    assert stored["target_escalation"]["status"] == "approved"


def test_manage_projection_never_carries_a_submission_handler() -> None:
    metadata = {"title": "T", "domain": "ai", "subdomain": "health",
                "submission_contact": {"name": "Second Author", "email": "second@example.test",
                                       "role": "submission_handler"},
                "delivery": {"awaiting_owner_review": True}}
    projection = json.dumps(_paper_projection(PAPER, metadata, origin_commit="0" * 40))
    assert "submission_handler" not in projection
    assert "second@example.test" not in projection


def test_assign_handler_defaults_to_the_second_author(repo: Path) -> None:
    metadata = load_paper_metadata(PAPER, repo)
    metadata["delivery"] = {"awaiting_owner_review": True}
    write_paper_metadata(PAPER, metadata, repo)
    result = program_delivery.assign_handler(PAPER, root=repo)
    assert result["submission_handler"] == "Second Author"
    assert result["journal_submission_authorized"] is False
    stored = load_paper_metadata(PAPER, repo)
    assert stored["submission_contact"]["role"] == "submission_handler"
    assert stored["submission_contact"]["email"] == "second@example.test"
    assert stored["delivery"]["awaiting_owner_review"] is False
    named = program_delivery.assign_handler(PAPER, root=repo, handler="Third Author")
    assert named["submission_handler"] == "Third Author"
    with pytest.raises(program_delivery.ProgramDeliveryError):
        program_delivery.assign_handler(PAPER, root=repo, handler="Nobody")


def test_program_cli_and_the_external_write_switch(repo: Path, monkeypatch, capsys) -> None:
    from paper_writing.__main__ import main

    args = build_parser().parse_args(["program", "deliver", "--paper-id", PAPER, "--json"])
    assert args.program_command == "deliver" and args.json
    assert build_parser().parse_args(
        ["program", "assign-handler", "--paper-id", PAPER]).handler == "second_author"
    monkeypatch.delenv("OPENLABS_ENABLE_EXTERNAL_WRITES", raising=False)
    assert main(["program", "deliver", "--paper-id", PAPER, "--root", str(repo),
                 "--api-url", "https://manage.invalid", "--json"]) == 1
    assert "OPENLABS_ENABLE_EXTERNAL_WRITES" in json.loads(capsys.readouterr().out)["error"]
    assert main(["program", "assign-handler", "--paper-id", PAPER, "--root", str(repo),
                 "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["submission_handler"] == "Second Author"


def test_handoff_refuses_a_provisional_escalation_below_the_bar(repo: Path) -> None:
    from paper_writing.handoff import HandoffError, validate_release_preconditions

    metadata = load_paper_metadata(PAPER, repo)
    metadata.update(writing_release={**_ready(6.0), "target_score": 6.0},
                    target_escalation=_provisional(), domain="ai", subdomain="health",
                    created_at="2026-11-11",
                    data_sources=[{"kind": "public_dataset", "name": "MIMIC-IV",
                                   "license_or_access": "PhysioNet credentialed",
                                   "source": "https://physionet.org/content/mimiciv/",
                                   "version": "2.2"}])
    write_paper_metadata(PAPER, metadata, repo)
    with pytest.raises(HandoffError, match="provisional"):
        validate_release_preconditions(PAPER, root=repo)


def test_register_escalation_refuses_an_unverified_or_paid_fallback(repo: Path) -> None:
    record = repo / "admission.json"
    record.write_text("{}", encoding="utf-8")

    def register(evidence):
        return program_delivery.register_provisional_escalation(
            PAPER, root=repo, venue="Example Top Journal", admission_task_id="portfolio:abc",
            admission_record=record, fallback_venue="Journal of Biomedical Informatics",
            fallback_evidence=evidence,
        )

    with pytest.raises(program_delivery.ProgramDeliveryError, match="no eligibility evidence"):
        register(None)
    # "No APC" evidence that never looked at page or colour charges is not enough.
    with pytest.raises(program_delivery.ProgramDeliveryError, match="page_charge, colour_charge"):
        register(_fallback_evidence(fee_charges_checked=["apc"]))
    with pytest.raises(program_delivery.ProgramDeliveryError, match="not eligible"):
        register(_fallback_evidence(fee_policy="mandatory_author_fee"))
    with pytest.raises(program_delivery.ProgramDeliveryError, match="SCIE"):
        register(_fallback_evidence(indexing={"indexes": ["ESCI"], "source": "https://x",
                                              "checked_at": "2026-11-12"}))
    with pytest.raises(program_delivery.ProgramDeliveryError, match="major-category"):
        register(_fallback_evidence(ranking_scope="subcategory"))
    with pytest.raises(program_delivery.ProgramDeliveryError, match="routine CAS zone"):
        register(_fallback_evidence(tier=2))
    with pytest.raises(program_delivery.ProgramDeliveryError, match="name the fallback venue"):
        register(_fallback_evidence(venue="Another Journal"))
    assert "target_escalation" not in load_paper_metadata(PAPER, repo)


def test_register_escalation_cli_reads_the_fallback_evidence_file(repo: Path) -> None:
    from paper_writing.__main__ import main

    record = repo / "admission.json"
    record.write_text("{}", encoding="utf-8")
    evidence = repo / "fallback.json"
    evidence.write_text(json.dumps(_fallback_evidence()), encoding="utf-8")
    base = ["program", "register-escalation", "--paper-id", PAPER, "--venue",
            "Example Top Journal", "--admission-task-id", "portfolio:abc", "--admission-record",
            str(record), "--fallback-venue", "Journal of Biomedical Informatics", "--root",
            str(repo), "--json"]
    with pytest.raises(SystemExit):
        build_parser().parse_args(base)  # the evidence is required
    assert main([*base, "--fallback-evidence", str(evidence)]) == 0
    stored = load_paper_metadata(PAPER, repo)["target_escalation"]
    assert stored["fallback_eligibility"]["fee_source"] == "https://example.org/costs"


def test_legacy_fallback_loads_but_must_pass_before_it_is_used(repo: Path) -> None:
    # An older record without fallback evidence stays valid while the escalation target holds.
    legacy = _paper(target_escalation=_provisional())
    venue_policy.validate_journal_eligibility(legacy, paper_id=PAPER, policy=POLICY)
    metadata = load_paper_metadata(PAPER, repo)
    metadata["target_escalation"] = _provisional()
    write_paper_metadata(PAPER, metadata, repo)
    with pytest.raises(program_delivery.ProgramDeliveryError, match="no eligibility evidence"):
        program_delivery.check_fallback(PAPER, root=repo)
    with pytest.raises(program_delivery.ProgramDeliveryError, match="page_charge"):
        program_delivery.check_fallback(
            PAPER, root=repo, fallback_evidence=_fallback_evidence(fee_charges_checked=["apc"]))
    assert "fallback_eligibility" not in load_paper_metadata(PAPER, repo)["target_escalation"]
    # Falling back to the venue without the evidence fails registry validation.
    fallen = _paper(target_journal="Journal of Biomedical Informatics", target_journal_tier=3,
                    target_escalation=_provisional(status="superseded"))
    with pytest.raises(ValueError, match="fallback eligibility check"):
        venue_policy.validate_journal_eligibility(fallen, paper_id=PAPER, policy=POLICY)
    result = program_delivery.check_fallback(PAPER, root=repo,
                                             fallback_evidence=_fallback_evidence())
    assert result["eligible"] and result["evidence_updated"]
    completed = load_paper_metadata(PAPER, repo)["target_escalation"]
    assert completed["fallback_eligibility"]["tier"] == 3
    assert program_delivery.check_fallback(PAPER, root=repo)["evidence_updated"] is False
    fallen["target_escalation"] = completed
    venue_policy.validate_journal_eligibility(fallen, paper_id=PAPER, policy=POLICY)
