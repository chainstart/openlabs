from copy import deepcopy

import pytest

from paper_writing.registry import _validate_journal_target_policy


def record():
    return {
        "target_journal": "Example Journal",
        "target_journal_checked_at": "2020-01-01",
        "target_journal_required_indexes": ["SCIE"],
        "target_journal_indexing": {
            "journal": "Example Journal", "indexes": ["SCIE", "Scopus"],
            "source": "https://publisher.example/journal", "checked_at": "2026-11-05",
        },
    }


def validate(paper):
    _validate_journal_target_policy(
        paper, paper_id="example", policy={"required_after_basic_draft": False},
    )


def test_exact_science_index_evidence_is_accepted():
    validate(record())


@pytest.mark.parametrize("indexes", [["ESCI"], ["Scopus"], ["SCI"], ["SCIE candidate"], None, "SCIE"])
def test_other_indexes_never_satisfy_scie_even_for_historical_target(indexes):
    p = record()
    p["target_journal_indexing"]["indexes"] = indexes
    with pytest.raises(ValueError, match="required indexes"):
        validate(p)


@pytest.mark.parametrize("change", [
    {"journal": "Another Journal"}, {"source": "local assertion"}, {"checked_at": ""},
])
def test_index_assertion_must_bind_current_title_and_dated_web_evidence(change):
    p = record()
    p["target_journal_indexing"].update(change)
    with pytest.raises(ValueError, match="target_journal_indexing"):
        validate(p)


def test_constraint_without_evidence_fails_closed():
    p = record()
    del p["target_journal_indexing"]
    with pytest.raises(ValueError, match="evidence is required"):
        validate(p)


def test_existing_unconstrained_records_remain_readable():
    p = deepcopy(record())
    del p["target_journal_required_indexes"]
    del p["target_journal_indexing"]
    validate(p)
