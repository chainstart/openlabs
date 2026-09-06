"""Explicit intake-review gates; pure fixtures, no network, snapshots or DB."""

from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest


_PATH = Path(__file__).resolve().parents[1] / "tools/problem_catalog.py"
_SPEC = importlib.util.spec_from_file_location("problem_catalog_intake_under_test", _PATH)
assert _SPEC and _SPEC.loader
catalog = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(catalog)


def candidate(language="lean4", **metadata):
    problem = catalog.new_problem("intake-fixture", "A precise research question", "formal-conjectures", "open_in_source")
    problem_id = problem["record_id"]
    statement_id = "math-catalog:statement:intake-fixture"
    problem["metadata"].update({
        "statement_ids": [statement_id],
        "source_family_admission": "requires_individual_influence_review",
        "source_admission_allows_screening": False,
        "influence_status": "pending_review",
    })
    problem["metadata"].update(metadata)
    statement = catalog.record("math_statement", "intake-fixture", "Exact source declaration", "lean_source_unverified", {
        "problem_id": problem_id,
        "language": language,
        "statement_text": "theorem question : True := by sorry" if language == "lean4" else "Every object has property P.",
        "verified": False,
        "local_elaboration_checked": False,
        "faithfulness_checked": False,
        "formalization_status": "lean_source_present_not_locally_verified",
    })
    return {problem_id: problem}, {statement_id: statement}, {}


def valid_review(problems, statements, **patch):
    review = {
        "problem_id": next(iter(problems)),
        "reviewed_statement_ids": list(statements),
        "scope_review": "passed",
        "influence_status": "review_passed",
        "reviewed_at": "2026-09-05T08:00:00Z",
        "reason": "The cited source and this exact declaration have matching domain and quantifiers.",
        "evidence": ["https://example.org/primary-source/theorem-2"],
    }
    review.update(patch)
    return review


def apply_and_finalize(problems, statements, records, reviews):
    catalog.apply_intake_reviews(problems, statements, records, reviews)
    for problem in problems.values():
        catalog.finalize_problem(problem, statements)


def test_empty_reviews_do_not_upgrade_imported_legacy_natural_language():
    problems, statements, records = candidate(
        "natural_language", legacy_review_retained=True,
        influence_status="review_passed", source_admission_allows_screening=True,
        statement_status="imported_natural_language",
        quantifier_review="pending_independent_scope_review",
    )
    before = deepcopy((problems, statements, records))
    catalog.apply_intake_reviews(problems, statements, records, [])
    assert (problems, statements, records) == before
    problem = next(iter(problems.values()))
    catalog.finalize_problem(problem, statements)
    meta = problem["metadata"]
    assert meta["screening_eligible"]
    assert not meta["selection_eligible"]
    assert meta["quantifier_review"] == "pending_independent_scope_review"
    assert not meta["research_ready"]


@pytest.mark.parametrize("language,statement_status", [
    ("natural_language", "reviewed_natural_language"),
    ("lean4", "reviewed_lean_statement"),
])
def test_evidence_and_exact_statement_review_can_unlock_selection_only(language, statement_status):
    problems, statements, records = candidate(language)
    original_statements = deepcopy(statements)
    review = valid_review(problems, statements, verified=True, research_ready=True,
                          formalization_status="verified")
    apply_and_finalize(problems, statements, records, [review])
    problem = next(iter(problems.values()))
    meta = problem["metadata"]
    assert meta["screening_eligible"]
    assert meta["selection_eligible"]
    assert meta["explicit_intake_review_passed"]
    assert meta["statement_status"] == statement_status
    assert meta["quantifier_review"] == "reviewed_explicit_intake"
    assert meta["reviewed_statement_ids"] == list(statements)
    assert not meta["research_ready"]
    assert meta["short_horizon_feasibility"] == "not_assessed"
    assert statements == original_statements
    assert all(not item["metadata"]["verified"] for item in statements.values())
    if language == "lean4":
        assert meta["formalization_status"] == "lean_source_present_not_locally_verified"
        assert "lean_elaboration_and_faithfulness_check_not_run" in meta["next_actions"]
    recorded, = records.values()
    assert recorded["metadata"]["does_not_certify_lean_or_close_problem"]
    assert recorded["metadata"]["record_references"] == [problem["record_id"]] + list(statements)


def test_influence_only_review_does_not_imply_quantifier_scope_review():
    problems, statements, records = candidate()
    review = valid_review(problems, statements, scope_review="pending", reviewed_statement_ids=[])
    apply_and_finalize(problems, statements, records, [review])
    meta = next(iter(problems.values()))["metadata"]
    assert not meta["selection_eligible"]
    assert meta["quantifier_review"] == "pending"
    assert not meta.get("explicit_intake_review_passed", False)


@pytest.mark.parametrize("field,empty", [
    ("evidence", []), ("evidence", None), ("reviewed_at", ""), ("reason", ""),
])
def test_review_without_evidence_date_or_reason_is_rejected(field, empty):
    problems, statements, records = candidate()
    review = valid_review(problems, statements, **{field: empty})
    with pytest.raises(ValueError, match="requires evidence, date and reason"):
        catalog.apply_intake_reviews(problems, statements, records, [review])


@pytest.mark.parametrize("mode", ["empty", "nonexistent", "belongs_to_other_problem", "missing_statement_object"])
def test_scope_review_must_identify_existing_statements_of_this_problem(mode):
    problems, statements, records = candidate()
    problem = next(iter(problems.values()))
    statement_id = next(iter(statements))
    reviewed_ids = [statement_id]
    if mode == "empty":
        reviewed_ids = []
    elif mode == "nonexistent":
        reviewed_ids = ["math-catalog:statement:does-not-exist"]
    elif mode == "belongs_to_other_problem":
        foreign_id = "math-catalog:statement:other-problem"
        statements[foreign_id] = {"metadata": {"problem_id": "math-catalog:problem:other", "language": "lean4"}}
        reviewed_ids = [foreign_id]
        assert foreign_id not in problem["metadata"]["statement_ids"]
    else:
        del statements[statement_id]
    review = valid_review(problems, statements, reviewed_statement_ids=reviewed_ids)
    with pytest.raises(ValueError, match="existing statements for this mother"):
        catalog.apply_intake_reviews(problems, statements, records, [review])


def test_missing_problem_review_is_rejected():
    problems, statements, records = candidate()
    review = valid_review(problems, statements, problem_id="math-catalog:problem:does-not-exist")
    with pytest.raises(ValueError, match="missing or multiply reviewed"):
        catalog.apply_intake_reviews(problems, statements, records, [review])


def test_duplicate_reviews_of_same_problem_are_rejected_even_with_different_dates():
    problems, statements, records = candidate()
    first = valid_review(problems, statements)
    second = valid_review(problems, statements, reviewed_at="2026-09-06T08:00:00Z")
    with pytest.raises(ValueError, match="missing or multiply reviewed"):
        catalog.apply_intake_reviews(problems, statements, records, [first, second])


@pytest.mark.parametrize("status", ["solved_in_source", "disproved_in_source", "source_status_conflict", "independent_of_zfc_in_source"])
def test_closed_or_nonopen_mother_cannot_be_reopened_by_an_intake_review(status):
    problems, statements, records = candidate(scientific_status=status)
    review = valid_review(problems, statements, scientific_status="open_in_source")
    apply_and_finalize(problems, statements, records, [review])
    problem = next(iter(problems.values()))
    assert problem["status"] == status
    assert problem["metadata"]["scientific_status"] == status
    assert not problem["metadata"]["screening_eligible"]
    assert not problem["metadata"]["selection_eligible"]


@pytest.mark.parametrize("status", ["locally_resolved", "refuted", "solved_in_literature"])
def test_local_closure_blocks_selection_even_if_upstream_mother_remains_open(status):
    problems, statements, records = candidate(local_research_status=status)
    review = valid_review(problems, statements, local_research_status="not_assessed")
    apply_and_finalize(problems, statements, records, [review])
    meta = next(iter(problems.values()))["metadata"]
    assert meta["local_research_status"] == status
    assert not meta["selection_eligible"]


def test_source_ambiguity_cannot_be_bypassed_by_scope_review():
    problems, statements, records = candidate(source_ambiguity_flag=True)
    review = valid_review(problems, statements, source_ambiguity_flag=False)
    apply_and_finalize(problems, statements, records, [review])
    meta = next(iter(problems.values()))["metadata"]
    assert meta["source_ambiguity_flag"]
    assert not meta["screening_eligible"]
    assert not meta["selection_eligible"]
    assert "resolve_source_statement_ambiguity" in meta["next_actions"]


def test_same_problem_alias_cannot_be_reopened_by_individual_intake_review():
    canonical_id = "math-catalog:problem:canonical-mother"
    problems, statements, records = candidate(
        canonical_alias_of=canonical_id, influence_status="alias_not_independent",
    )
    canonical = catalog.new_problem("canonical-mother", "The canonical mother", "erdos-problems", "open_in_source")
    alias_id = next(iter(problems))
    review = valid_review(problems, statements, problem_id=alias_id)
    problems[canonical_id] = canonical
    apply_and_finalize(problems, statements, records, [review])
    meta = problems[alias_id]["metadata"]
    assert meta["canonical_alias_of"] == canonical_id
    assert not meta["screening_eligible"]
    assert not meta["selection_eligible"]
    assert not meta["research_ready"]
    assert canonical_id in meta["record_references"]
