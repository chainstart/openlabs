"""Independent catalog policy and archive fixtures; no network or live DB."""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path
import tarfile

import pytest


_PATH = Path(__file__).resolve().parents[1] / "tools/problem_catalog.py"
_SPEC = importlib.util.spec_from_file_location("problem_catalog_builder_under_test", _PATH)
assert _SPEC and _SPEC.loader
catalog = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(catalog)


@pytest.mark.parametrize("raw,expected", [
    ("open", "open_in_source"), ("verifiable", "open_in_source"),
    ("falsifiable", "open_in_source"), ("decidable", "open_in_source"),
    ("proved", "solved_in_source"), ("solved", "solved_in_source"),
    ("disproved", "disproved_in_source"), ("refuted", "disproved_in_source"),
    ("independent", "independent_of_zfc_in_source"),
    ("not provable", "axiomatic_obstruction_in_source"),
    ("not disprovable", "axiomatic_obstruction_in_source"),
    ("solved (Lean)", "solved_in_source"),
    ("disproved (Lean)", "disproved_in_source"),
    (None, "unknown"), ("", "unknown"), ("new label", "unknown"),
])
def test_exact_source_statuses(raw, expected):
    assert catalog.normalize_status(raw) == expected


@pytest.mark.parametrize("raw", [
    "unsolved", "unproved", "not solved", "not proved", "not disproved",
    "unresolved", "possibly solved", "not yet proved", "solved?",
])
def test_unrecognized_free_text_cannot_silently_close_problem(raw):
    assert catalog.normalize_status(raw) == "unknown"


def candidate(**metadata):
    problem = catalog.new_problem("test", "Example mother", "erdos-problems", "open_in_source")
    problem["metadata"].update({
        "influence_status": "benchmark_passed", "legacy_review_retained": True,
        "statement_status": "reviewed_natural_language",
        "quantifier_review": "reviewed_in_local_intake",
    })
    problem["metadata"].update(metadata)
    return problem


@pytest.mark.parametrize("status", [
    "solved_in_source", "disproved_in_source", "independent_of_zfc_in_source",
    "axiomatic_obstruction_in_source", "unknown", "source_status_conflict",
    "locally_resolved", "refuted", "solved_in_literature",
])
def test_nonopen_mathematical_states_never_enter_active_pool(status):
    problem = candidate(scientific_status=status)
    catalog.finalize_problem(problem, {})
    assert not problem["metadata"]["screening_eligible"]
    assert not problem["metadata"]["selection_eligible"]
    assert problem["status"] == status


@pytest.mark.parametrize("status", ["locally_resolved", "refuted", "solved_in_literature"])
def test_old_open_source_does_not_override_local_closure(status):
    problem = candidate(local_research_status=status)
    catalog.finalize_problem(problem, {})
    assert not problem["metadata"]["screening_eligible"]
    assert not problem["metadata"]["selection_eligible"]


@pytest.mark.parametrize("patch", [
    {"influence_status": "alias_not_independent"},
    {"influence_status": "pending_review"},
    {"source_admission_allows_screening": False},
    {"legacy_review_retained": False},
    {"statement_status": "missing"},
    {"quantifier_review": "pending"},
])
def test_selection_requires_all_declared_intake_gates(patch):
    problem = candidate(**patch)
    catalog.finalize_problem(problem, {})
    assert not problem["metadata"]["selection_eligible"]
    assert problem["metadata"]["review_required"]


def test_upstream_ambiguity_cannot_be_overridden_by_old_review_labels():
    problem = candidate(source_ambiguity_flag=True)
    catalog.finalize_problem(problem, {})
    assert not problem["metadata"]["selection_eligible"]
    assert problem["metadata"]["review_required"]


def test_solved_lean_variant_does_not_close_open_mother_or_certify_lean():
    problem = catalog.new_problem("erdos-3", "Erdos 3", "erdos-problems", "open_in_source")
    meta = problem["metadata"]
    meta["influence_status"] = "benchmark_passed"
    statement_id = "math-catalog:statement:variant"
    meta["statement_ids"] = [statement_id, statement_id]
    meta["status_observations"] = [{"scope": "individual_lean_declaration_not_whole_mother_problem", "status": "solved"}]
    statement = {"metadata": {"language": "lean4", "source_status": "solved", "contains_sorry": True}}
    catalog.finalize_problem(problem, {statement_id: statement})
    assert problem["status"] == "open_in_source"
    assert meta["scientific_status"] == "open_in_source"
    assert meta["statement_ids"] == [statement_id]
    assert meta["formalization_status"] == "lean_source_present_not_locally_verified"
    assert meta["lean_statement_count"] == 1
    assert not meta["selection_eligible"]
    assert "lean_elaboration_and_faithfulness_check_not_run" in meta["next_actions"]


def test_canonical_formal_keys_do_not_merge_by_title_or_cross_reference():
    erdos = {"canonical_erdos_id": "830", "source_item_id": "ErdosProblems/830.lean::Erdos830.parts.i"}
    wiki = {"canonical_erdos_id": None, "source_item_id": "Wikipedia/AmicableNumbers.lean::question",
            "title": "Erdos 830", "references": ["https://www.erdosproblems.com/830"]}
    wiki_other = {**wiki, "source_item_id": "Wikipedia/AmicableNumbers.lean::question_variant"}
    assert catalog.canonical_formal_key(erdos) == "erdos-830"
    assert catalog.canonical_formal_key(wiki).startswith("fc-")
    assert catalog.canonical_formal_key(wiki) != catalog.canonical_formal_key(wiki_other)


def archive(members):
    """Small in-memory tar; a member is (path, content, type, linkname)."""
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as handle:
        for name, content, member_type, linkname in members:
            item = tarfile.TarInfo(name)
            item.type = member_type
            item.linkname = linkname
            item.size = len(content) if member_type == tarfile.REGTYPE else 0
            handle.addfile(item, io.BytesIO(content) if member_type == tarfile.REGTYPE else None)
    return output.getvalue()


def test_archive_reads_source_files_without_executing_them(tmp_path):
    raw = archive([
        ("repo/Example.lean", b"-- source only", tarfile.REGTYPE, ""),
        ("repo/scripts/danger.py", b"raise RuntimeError('never execute')", tarfile.REGTYPE, ""),
        ("repo/LICENSE", b"license", tarfile.REGTYPE, ""),
    ])
    inventory = catalog.unpack_source_archive(raw, tmp_path / "tree")
    assert {item["path"] for item in inventory} == {"Example.lean", "LICENSE"}
    assert not (tmp_path / "tree/scripts/danger.py").exists()
    assert (tmp_path / "tree/Example.lean").read_bytes() == b"-- source only"


@pytest.mark.parametrize("name,kind,link", [
    ("/escape.md", tarfile.REGTYPE, ""),
    ("repo/../../escape.md", tarfile.REGTYPE, ""),
    ("repo/link.md", tarfile.SYMTYPE, "../../escape.md"),
    ("repo/link.md", tarfile.LNKTYPE, "repo/other.md"),
])
def test_archive_rejects_traversal_and_all_links(tmp_path, name, kind, link):
    with pytest.raises(ValueError):
        catalog.unpack_source_archive(archive([(name, b"source", kind, link)]), tmp_path / "tree")
    assert not (tmp_path / "escape.md").exists()


def test_archive_rejects_existing_destination_symlink_escape(tmp_path):
    destination = tmp_path / "tree"
    outside = tmp_path / "outside"
    destination.mkdir()
    outside.mkdir()
    (destination / "redirect").symlink_to(outside, target_is_directory=True)
    raw = archive([("repo/redirect/escape.md", b"bad", tarfile.REGTYPE, "")])
    with pytest.raises(ValueError, match="escaped"):
        catalog.unpack_source_archive(raw, destination)
    assert not (outside / "escape.md").exists()


def test_immutable_source_cannot_be_replaced(tmp_path):
    destination = tmp_path / "tree"
    raw = archive([("repo/a.md", b"first", tarfile.REGTYPE, "")])
    catalog.unpack_source_archive(raw, destination)
    catalog.unpack_source_archive(raw, destination)
    replacement = archive([("repo/a.md", b"second", tarfile.REGTYPE, "")])
    with pytest.raises(ValueError, match="immutable"):
        catalog.unpack_source_archive(replacement, destination)
    assert (destination / "a.md").read_bytes() == b"first"


def test_archive_rejects_oversized_source_member(tmp_path):
    content = b"x" * (8 * 1024 * 1024 + 1)
    raw = archive([("repo/huge.md", content, tarfile.REGTYPE, "")])
    with pytest.raises(ValueError, match="limits"):
        catalog.unpack_source_archive(raw, tmp_path / "tree")
