import pytest

from paper_writing.registry import _validate_journal_target_policy


POLICY = {
    "excluded_journals": ["EPJC", "The European Physical Journal C", "Eur. Phys. J. C",
                          "JHEP", "Journal of High Energy Physics", "J. High Energy Phys."],
    "required_after_basic_draft": False,
    "effective_from": "2026-09-12",
}


@pytest.mark.parametrize("name", [
    "EPJC", "epjc", " EPJC ", "European Physical Journal C",
    "The European Physical Journal C", "European Physical Journal-C",
    "Eur. Phys. J. C", "EUR PHYS J C",
    "JHEP", "jhep", "Journal of High Energy Physics", "J. High Energy Phys.",
    "The Journal of High Energy Physics", "journal-of-high-energy-physics",
])
def test_exclusion_blocks_aliases_even_for_historical_targets(name):
    with pytest.raises(ValueError, match="excluded"):
        _validate_journal_target_policy(
            {"target_journal": name, "target_journal_checked_at": "2026-01-01"},
            paper_id="test", policy=POLICY,
        )


@pytest.mark.parametrize("name", [
    "The European Physical Journal A", "The European Physical Journal Plus",
    "Physics of the Dark Universe", "Discrete Mathematics",
    "Physical Review D", "Journal of High Energy Astrophysics",
])
def test_exclusion_does_not_block_other_venues(name):
    _validate_journal_target_policy({"target_journal": name}, paper_id="test", policy=POLICY)


@pytest.mark.parametrize("invalid", [None, "EPJC", [None], [""]])
def test_malformed_exclusion_policy_fails_closed(invalid):
    with pytest.raises(ValueError, match="list of names"):
        _validate_journal_target_policy(
            {"target_journal": "EPJC"}, paper_id="test",
            policy={**POLICY, "excluded_journals": invalid},
        )
