"""Offline discovery/identity boundaries; only temporary fixtures are written.

No live source snapshot, catalog bundle, database or research campaign is used.
"""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


TOOLS = Path(__file__).resolve().parents[1] / "tools"
SPEC = importlib.util.spec_from_file_location("discovery_catalog_under_test", TOOLS / "problem_catalog.py")
assert SPEC and SPEC.loader
catalog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(catalog)

STAMP = "2026-09-05T08:58:29Z"
SOURCE = "aim-problem-lists"
COLLECTION = catalog.sid("collection-test-list")
MOTHER = catalog.pid("discovery-fixture-mother")
DECISIONS = (
    "excluded_placeholder", "closed_in_literature", "historical_solved_in_source",
    "candidate_identity_pending", "candidate_scope_pending",
)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))

    def reject_network(*args, **kwargs):
        raise AssertionError("discovery regression tests must not access the network")

    monkeypatch.setattr(catalog.urllib.request, "urlopen", reject_network)


def fixture_records():
    mother = catalog.new_problem("discovery-fixture-mother", "Existing open mother", SOURCE, "open_in_source")
    records = {
        catalog.sid(SOURCE): catalog.record("math_source", SOURCE, "AIM", "approved", {}),
        COLLECTION: catalog.record("math_source", "collection-test-list", "Community list", "discovery_only", {
            "parent_source_id": catalog.sid(SOURCE),
        }),
    }
    return {MOTHER: mother}, {}, records


def discovery_review(**patch):
    result = {
        "source_id": SOURCE, "source_item_id": "test-list/problem-1",
        "collection_source_id": COLLECTION, "candidate_problem_id": MOTHER,
        "source_url": "https://example.org/primary-list#problem-1",
        "decision": "candidate_identity_pending", "reviewed_at": STAMP,
        "evidence": ["https://example.org/primary-list#problem-1"],
        "reason": "Exact definitions and quantifiers still require manual comparison.",
        "automatic_problem_admission": False,
    }
    result.update(patch)
    return result


def batch(reviews, **patch):
    result = {
        "batch_id": "discovery-test-v1", "_seal": {"review_body_sha256": "a" * 64},
        "problems": [], "statements": [], "reviews": [],
        "discovery_reviews": reviews, "identity_decisions": [],
    }
    result.update(patch)
    return result


@pytest.mark.parametrize("decision", DECISIONS)
def test_each_legal_discovery_decision_is_review_only_and_cannot_close_mother(decision):
    problems, statements, records = fixture_records()
    original = deepcopy((problems, statements, records))
    review = discovery_review(
        decision=decision, selection_eligible=True, research_ready=True,
        automatically_closes_problems=True, creates_or_merges_problem_identity=True,
        scientific_status="solved_in_source", canonical_alias_of="spoofed-parent",
    )
    catalog.apply_batch_items([batch([review])], problems, statements, records)
    assert problems == original[0]
    assert statements == original[1]
    assert {key: records[key] for key in original[2]} == original[2]
    added = [value for key, value in records.items() if key not in original[2]]
    assert len(added) == 1
    item = added[0]
    assert item["kind"] == "math_review"
    assert item["status"] == "source_discovery_review"
    meta = item["metadata"]
    assert meta["decision"] == decision
    assert meta["selection_eligible"] is False
    assert meta["research_ready"] is False
    assert meta["automatically_closes_problems"] is False
    assert meta["creates_or_merges_problem_identity"] is False
    assert meta["record_references"] == [catalog.sid(SOURCE), COLLECTION, MOTHER]
    assert problems[MOTHER]["metadata"]["scientific_status"] == "open_in_source"
    assert "canonical_alias_of" not in problems[MOTHER]["metadata"]


def test_discovery_without_candidate_or_collection_never_creates_a_mother():
    _, statements, records = fixture_records()
    problems = {}
    review = discovery_review()
    review.pop("collection_source_id")
    review.pop("candidate_problem_id")
    catalog.apply_batch_items([batch([review])], problems, statements, records)
    assert not problems and not statements
    added = [item for item in records.values() if item["kind"] == "math_review"]
    assert len(added) == 1
    assert added[0]["metadata"]["record_references"] == [catalog.sid(SOURCE)]


@pytest.mark.parametrize("patch,match", [
    ({"source_id": "unregistered-source"}, "unregistered source"),
    ({"collection_source_id": catalog.sid("missing-collection")}, "mismatched source collection"),
    ({"candidate_problem_id": catalog.pid("missing-mother")}, "missing candidate identity"),
    ({"reviewed_at": "2026-09-05T08:58:29"}, "timezone"),
    ({"decision": "admit_and_close"}, "unsupported discovery review decision"),
    ({"automatic_problem_admission": True}, "safe admission boundary"),
    ({"automatic_problem_admission": None}, "safe admission boundary"),
    ({"automatic_problem_admission": 0}, "safe admission boundary"),
    ({"automatic_problem_admission": "false"}, "safe admission boundary"),
])
def test_discovery_rejects_unsafe_provenance_and_admission(patch, match):
    problems, statements, records = fixture_records()
    original = deepcopy((problems, statements, records))
    with pytest.raises(ValueError, match=match):
        catalog.apply_batch_items([batch([discovery_review(**patch)])], problems, statements, records)
    assert (problems, statements, records) == original


@pytest.mark.parametrize("field", [
    "source_item_id", "source_url", "evidence", "reason", "reviewed_at", "automatic_problem_admission",
])
def test_discovery_requires_each_evidence_and_boundary_field(field):
    problems, statements, records = fixture_records()
    review = discovery_review()
    review.pop(field)
    with pytest.raises(ValueError, match="provenance or safe admission boundary"):
        catalog.apply_batch_items([batch([review])], problems, statements, records)


@pytest.mark.parametrize("field", ["source_item_id", "source_url", "evidence", "reason", "reviewed_at"])
def test_discovery_rejects_empty_required_provenance(field):
    problems, statements, records = fixture_records()
    with pytest.raises(ValueError, match="provenance or safe admission boundary"):
        catalog.apply_batch_items([batch([discovery_review(**{field: [] if field == "evidence" else ""})])], problems, statements, records)


@pytest.mark.parametrize("mode", ["wrong_parent", "not_source", "source_record_not_source"])
def test_discovery_collection_must_belong_to_the_registered_source(mode):
    problems, statements, records = fixture_records()
    if mode == "wrong_parent":
        records[COLLECTION]["metadata"]["parent_source_id"] = catalog.sid("clay-millennium")
    elif mode == "not_source":
        records[COLLECTION]["kind"] = "math_problem"
    else:
        records[catalog.sid(SOURCE)]["kind"] = "math_review"
    with pytest.raises(ValueError, match="source"):
        catalog.apply_batch_items([batch([discovery_review()])], problems, statements, records)


def test_duplicate_source_item_in_one_batch_is_rejected_without_problem_mutation():
    problems, statements, records = fixture_records()
    original = deepcopy((problems, statements))
    first = discovery_review()
    second = discovery_review(decision="closed_in_literature", reason="A later scoped claim, not a new source identity.")
    with pytest.raises(ValueError, match="duplicate discovery review item"):
        catalog.apply_batch_items([batch([first, second])], problems, statements, records)
    assert (problems, statements) == original


def test_same_source_item_in_later_batch_preserves_both_historical_reviews():
    problems, statements, records = fixture_records()
    original = deepcopy(problems)
    catalog.apply_batch_items([
        batch([discovery_review()]),
        batch([discovery_review(decision="closed_in_literature")], batch_id="discovery-test-v2"),
    ], problems, statements, records)
    assert problems == original
    assert sum(item["kind"] == "math_review" for item in records.values()) == 2


def test_build_weakening_relation_does_not_alias_or_propagate_solved_status(tmp_path, monkeypatch):
    """Run the actual builder relation path using synthetic source trees only."""
    import problem_catalog_formal
    import problem_catalog_intake

    paths = SimpleNamespace(data=tmp_path / "data", artifacts=tmp_path / "artifacts")
    root = paths.data / catalog.DATA_SUBDIR
    root.mkdir(parents=True)

    def write_json(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content), encoding="utf-8")

    write_json(root / "source-registry.json", {"sources": [
        {"source_id": source, "name": source, "admission": "approved"}
        for source in ["erdos-problems", "formal-conjectures", "aim-problem-lists"]
    ]})
    write_json(paths.data / "workspaces/math/problem-curation-20260905/catalog.json", {"entries": []})
    tree = tmp_path / "synthetic-source-tree"
    (tree / "data").mkdir(parents=True)
    (tree / "data/problems.yaml").write_text("[]\n", encoding="utf-8")
    pointer = {"revision": "b" * 40, "retrieved_at": STAMP, "checked_at": STAMP, "tree_path": "synthetic-source-tree"}
    monkeypatch.setattr(catalog, "load_snapshot", lambda paths, source: (deepcopy(pointer), {"files": []}, tree))
    monkeypatch.setattr(catalog, "load_erdos_rows", lambda source_tree: [])
    monkeypatch.setattr(problem_catalog_formal, "parse_formal_tree", lambda *args: [])

    strong, weak = catalog.pid("synthetic-rh"), catalog.pid("synthetic-density")

    def mother(problem_id, status):
        return {
            "problem_id": problem_id, "title": problem_id, "source_id": SOURCE,
            "source_item_id": problem_id, "scientific_status": status,
            "source_url": "https://example.org/quantified-problems", "checked_at": STAMP,
            "evidence": ["https://example.org/quantified-problems"],
            "source_summary": "Synthetic statement summary; no proof audit is claimed.",
        }

    relation = {
        "from_id": weak, "to_id": strong, "relation_type": "weakening_of",
        "evidence": ["https://example.org/quantifier-comparison"],
        "scope_note": "Synthetic stronger-implies-weaker relation; no equivalence was asserted.",
    }
    incoming = batch([], problems=[mother(strong, "open_in_source"), mother(weak, "solved_in_source")],
                     identity_decisions=[relation])
    monkeypatch.setattr(problem_catalog_intake, "load_reviewed_batches", lambda paths: [deepcopy(incoming)])
    bundle = catalog.build_catalog(paths)
    records = {item["record_id"]: item for item in bundle["records"]}
    assert bundle["summary"]["problem_identity_records"] == 2
    assert bundle["summary"]["canonical_alias_records"] == 0
    assert bundle["summary"]["reviewed_identity_relations"] == 1
    assert records[strong]["metadata"]["scientific_status"] == "open_in_source"
    assert records[weak]["metadata"]["scientific_status"] == "solved_in_source"
    for problem_id in [strong, weak]:
        assert "canonical_alias_of" not in records[problem_id]["metadata"]
        assert not records[problem_id]["metadata"]["selection_eligible"]
        assert not records[problem_id]["metadata"]["research_ready"]
    links = [item for item in bundle["records"] if item["kind"] == "math_relation"]
    assert len(links) == 1
    assert links[0]["metadata"]["relation_type"] == "weakening_of"
    assert links[0]["metadata"]["record_references"] == [weak, strong]
