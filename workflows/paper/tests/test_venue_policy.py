from __future__ import annotations

import pytest

from paper_writing import venue_policy

POLICY = {
    "venue_eligibility": {
        "effective_from": "2026-11-07",
        "journal": {"required_indexes": ["SCIE"], "allowed_tiers": [1, 2, 3, 4], "routine_tiers": [3, 4]},
        "conference": {"allowed_ccf_ranks": ["A", "B", "C"]},
        "escalation": {"journal_tiers": [1, 2], "ccf_ranks": ["A"], "minimum_internal_score": 7},
        "empirical_real_data": {"domains": ["ai", "biology"], "exempt_tracks": ["scoped_theorem"]},
    }
}


def journal(**overrides):
    paper = {
        "venue_type": "journal",
        "target_journal": "Journal of Example Biology",
        "target_journal_checked_at": "2026-11-08",
        "target_journal_tier": 4,
        "target_journal_ranking_year": 2025,
        "target_journal_ranking_scope": "major_category",
        "target_journal_fee_policy": "no_mandatory_author_fee",
        "target_journal_indexing": {"journal": "Journal of Example Biology", "indexes": ["SCIE"],
                                    "source": "https://mjl.clarivate.com/x", "checked_at": "2026-11-08"},
    }
    paper.update(overrides)
    return paper


def escalation(venue: str, score: float = 7):
    return {"status": "approved", "venue": venue, "approved_by": "Example Author", "approved_at": "2026-11-08",
            "internal_review_score": score, "internal_review_source": "reviews/unified/x.json",
            "strength_evidence": "external cohort replication", "fallback_venue": "Journal of Example Biology"}


def test_routine_scie_zone_four_passes() -> None:
    venue_policy.validate_journal_eligibility(journal(), paper_id="p", policy=POLICY)


def test_historical_target_is_not_revalidated() -> None:
    venue_policy.validate_journal_eligibility(
        journal(target_journal_checked_at="2026-10-01", target_journal_indexing=None),
        paper_id="p", policy=POLICY)


def test_zone_must_come_from_cas_2025_major_category() -> None:
    with pytest.raises(ValueError, match="2025 CAS"):
        venue_policy.validate_journal_eligibility(journal(target_journal_ranking_year=2023), paper_id="p", policy=POLICY)
    with pytest.raises(ValueError, match="2025 CAS"):
        venue_policy.validate_journal_eligibility(journal(target_journal_ranking_scope="subject_category"),
                                                  paper_id="p", policy=POLICY)


def test_esci_only_and_paid_journals_are_rejected() -> None:
    esci = journal(target_journal_indexing={"journal": "J", "indexes": ["ESCI"], "source": "https://x", "checked_at": "2026-11-08"})
    with pytest.raises(ValueError, match="SCIE"):
        venue_policy.validate_journal_eligibility(esci, paper_id="p", policy=POLICY)
    with pytest.raises(ValueError, match="fee-free"):
        venue_policy.validate_journal_eligibility(journal(target_journal_fee_policy="mandatory_apc"), paper_id="p", policy=POLICY)


def test_zone_one_two_requires_approved_escalation() -> None:
    with pytest.raises(ValueError, match="escalation track"):
        venue_policy.validate_journal_eligibility(journal(target_journal_tier=2), paper_id="p", policy=POLICY)
    low = journal(target_journal_tier=1, target_escalation=escalation("Journal of Example Biology", 6))
    with pytest.raises(ValueError, match="below the escalation minimum"):
        venue_policy.validate_journal_eligibility(low, paper_id="p", policy=POLICY)
    ok = journal(target_journal_tier=1, target_escalation=escalation("Journal of Example Biology"))
    venue_policy.validate_journal_eligibility(ok, paper_id="p", policy=POLICY)
    assert venue_policy.is_escalation_venue(ok, POLICY)


def conference(rank: str = "C", **overrides):
    paper = {"venue_type": "conference", "target_conference": "Example Conf 2027",
             "target_conference_checked_at": "2026-11-08",
             "target_conference_ccf": {"rank": rank, "category": "人工智能", "edition": "2022",
                                       "source": "https://www.ccf.org.cn/x", "checked_at": "2026-11-08"},
             "target_conference_fee_policy": "no_mandatory_publication_fee",
             "target_conference_fee_source": "https://example.org/registration"}
    paper.update(overrides)
    return paper


def test_conference_rules() -> None:
    venue_policy.validate_conference_eligibility(conference(), paper_id="p", policy=POLICY)
    with pytest.raises(ValueError, match="CCF rank"):
        venue_policy.validate_conference_eligibility(conference(rank="none"), paper_id="p", policy=POLICY)
    with pytest.raises(ValueError, match="page/publication charge"):
        venue_policy.validate_conference_eligibility(conference(target_conference_fee_policy="page_charge"),
                                                     paper_id="p", policy=POLICY)
    with pytest.raises(ValueError, match="escalation track"):
        venue_policy.validate_conference_eligibility(conference(rank="A"), paper_id="p", policy=POLICY)
    venue_policy.validate_conference_eligibility(
        conference(rank="A", target_escalation=escalation("Example Conf 2027")), paper_id="p", policy=POLICY)


def source(kind: str = "public_dataset"):
    return {"name": "MIMIC-IV", "kind": kind, "source": "https://physionet.org/content/mimiciv/",
            "version": "3.1", "license_or_access": "PhysioNet credentialed"}


def test_new_empirical_paper_needs_real_data() -> None:
    paper = {"domain": "biology", "created_at": "2026-11-08"}
    with pytest.raises(ValueError, match="data_sources"):
        venue_policy.validate_empirical_data_sources(paper, paper_id="p", policy=POLICY)
    with pytest.raises(ValueError, match="real"):
        venue_policy.validate_empirical_data_sources({**paper, "data_sources": [source("synthetic")]},
                                                     paper_id="p", policy=POLICY)
    venue_policy.validate_empirical_data_sources({**paper, "data_sources": [source(), source("simulation")]},
                                                 paper_id="p", policy=POLICY)


def test_old_math_and_exempt_papers_are_not_forced() -> None:
    venue_policy.validate_empirical_data_sources({"domain": "biology", "created_at": "2026-10-01"}, paper_id="p", policy=POLICY)
    venue_policy.validate_empirical_data_sources({"domain": "math", "created_at": "2026-11-08"}, paper_id="p", policy=POLICY)
    venue_policy.validate_empirical_data_sources(
        {"domain": "ai", "created_at": "2026-11-08", "research_track": "scoped_theorem"}, paper_id="p", policy=POLICY)


def test_declared_sources_are_checked_even_when_not_required() -> None:
    bad = {"domain": "biology", "created_at": "2026-10-01", "data_sources": [{"name": "x", "kind": "public_dataset"}]}
    with pytest.raises(ValueError):
        venue_policy.validate_empirical_data_sources(bad, paper_id="p", policy=POLICY)


def test_review_track_tightens_only_escalation_targets() -> None:
    from paper_writing import review_flow as flow

    referees = {"referee_b": {"scores": {"overall": 6}, "confidence": "high"}}
    ready = {"outcome": "ready", "scientific_blockers": [], "next_action": None}
    routine = {"track": "routine", "minimum_overall_score": None}
    assert flow.apply_review_track(ready, referees, routine)["outcome"] == "ready"
    escalation = {"track": "escalation", "minimum_overall_score": 7.0}
    blocked = flow.apply_review_track(ready, referees, escalation)
    assert blocked["outcome"] == "revision_required" and blocked["escalation_blockers"]
    strong = {"referee_b": {"scores": {"overall": 8}, "confidence": "medium"}}
    assert flow.apply_review_track(ready, strong, escalation)["outcome"] == "ready"
    not_ready = {"outcome": "revision_required", "scientific_blockers": ["x"]}
    assert flow.apply_review_track(not_ready, referees, escalation) == not_ready


def test_target_block_states_track_and_supports_conferences() -> None:
    from paper_writing import review_flow as flow

    text = flow._target_block({"venue_type": "conference", "target_conference": "Example Conf 2027",
                               "target_conference_ccf": {"rank": "A", "edition": "2026", "category": "AI"}},
                              "escalation")
    assert "Conference: Example Conf 2027" in text and "class A" in text and "Review track: escalation" in text
    assert "Review track: routine" in flow._target_block({"target_journal": "J", "target_journal_tier": 4})


def test_conference_fallback_evidence_follows_the_conference_rules() -> None:
    policy = {"venue_eligibility": {**POLICY["venue_eligibility"],
                                    "conference": {"allowed_ccf_ranks": ["A", "B", "C"],
                                                   "ccf_list_edition": "2026"}}}
    evidence = {"venue": "Example Conference", "venue_type": "conference", "checked_at": "2026-11-12",
                "ccf": {"rank": "B", "category": "人工智能", "edition": "2026",
                        "source": "https://www.ccf.org.cn/x", "checked_at": "2026-11-12"},
                "fee_policy": "no_mandatory_publication_fee", "fee_source": "https://example.org/reg",
                "fee_charges_checked": ["page_charge", "colour_charge", "submission_fee"],
                "fee_evidence": "No page charges; registration only."}
    assert venue_policy.fallback_eligibility_problems(
        evidence, fallback_venue="Example Conference", policy=policy) == []
    problems = venue_policy.fallback_eligibility_problems(
        {**evidence, "ccf": {**evidence["ccf"], "rank": "A"}, "fee_charges_checked": []},
        fallback_venue="Example Conference", policy=policy)
    assert any("routine CCF rank" in p for p in problems)
    assert any("missing page_charge" in p for p in problems)
