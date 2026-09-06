import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from paper_writing.handoff import HandoffError, validate_release_preconditions
from paper_writing.operations import create_paper, record_quality_gate
from paper_writing.registry import load_paper_metadata, write_paper_metadata
from paper_writing.revision_policy import (
    AUTHORIZATION_SCHEMA,
    EXCEPTION_FIELD,
    EXCEPTION_SCHEMA,
    EXCEPTION_SCOPE,
    revision_round_policy,
    validate_release_revision_policy,
)


PAPER_ID = "20260901-math-combinatorics-exception-test"
OTHER_ID = "20260901-math-combinatorics-other-test"


def _exception(root: Path) -> dict:
    record = {
        "schema_version": AUTHORIZATION_SCHEMA,
        "paper_ids": [PAPER_ID],
        "scope": EXCEPTION_SCOPE,
        "maximum_revision_rounds": 7,
        "actor": "user",
        "confirmed": True,
        "confirmed_at": "2020-01-01T00:00:00+00:00",
        "source": "user-message:test-fixture",
        "quote": "Temporarily permit up to 7 review rounds for this paper only.",
    }
    relative = "registry/quality-gate-exceptions/test-authorization.json"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return {
        "schema_version": EXCEPTION_SCHEMA,
        "paper_id": PAPER_ID,
        "manuscript_version": "0.1.0",
        "active": True,
        "scope": EXCEPTION_SCOPE,
        "maximum_revision_rounds": 7,
        "authorization": {
            **{key: record[key] for key in (
                "actor", "confirmed", "confirmed_at", "source", "quote"
            )},
            "record": relative,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        },
    }


def _metadata(root: Path) -> dict:
    return {"paper_id": PAPER_ID, "version": "0.1.0", EXCEPTION_FIELD: _exception(root)}


def _gate(root: Path, *, independent: bool = False) -> dict:
    (root / "registry" / "papers").mkdir(parents=True)
    (root / "registry" / "settings.yaml").write_text(
        "schema_version: ara.paper_writing.registry.v1\n"
        "quality_gate:\n"
        "  minimum_score: 5.0\n"
        "  maximum_revision_rounds: 3\n"
        f"  require_validated_independent_review: {str(independent).lower()}\n"
        "  decision_standard: cas_zone_1_journal\n"
        "  cas_zone_1_minimum_decision: minor_revision\n",
        encoding="utf-8",
    )
    create_paper(
        root=root, paper_id=PAPER_ID, title="A test paper", created_at="2026-09-01",
        domain="math", subdomain="combinatorics", venue_type="journal",
    )
    metadata = load_paper_metadata(PAPER_ID, root)
    metadata[EXCEPTION_FIELD] = _exception(root)
    write_paper_metadata(PAPER_ID, metadata, root)
    return metadata


def _record(root: Path, *, rounds: int = 7, score: float = 6, decision: str = "minor_revision", blockers=()):
    return record_quality_gate(
        PAPER_ID, root=root, venue_type="journal", score=score, decision=decision,
        revision_rounds=rounds, unresolved_blockers=blockers,
    )


def test_exception_is_opt_in_exact_and_returns_a_detached_copy(tmp_path: Path) -> None:
    metadata = _metadata(tmp_path)
    gate = {"maximum_revision_rounds": 3}
    assert revision_round_policy(OTHER_ID, {}, gate, root=tmp_path) == (3, None)
    assert revision_round_policy(PAPER_ID, {}, {}, root=tmp_path) == (3, None)
    maximum, exception = revision_round_policy(PAPER_ID, metadata, gate, root=tmp_path)
    assert maximum == 7
    assert exception == metadata[EXCEPTION_FIELD]
    exception["authorization"]["quote"] = "changed copy"
    assert metadata[EXCEPTION_FIELD]["authorization"]["quote"] != "changed copy"
    metadata[EXCEPTION_FIELD]["active"] = False
    assert revision_round_policy(PAPER_ID, metadata, gate, root=tmp_path) == (3, None)


@pytest.mark.parametrize("field,value", [
    ("schema_version", "unknown"), ("paper_id", OTHER_ID),
    ("manuscript_version", "0.1.1"), ("manuscript_version", "0.1.*"),
    ("active", "true"), ("active", 1), ("scope", "all_quality_checks"),
    ("maximum_revision_rounds", True), ("maximum_revision_rounds", "7"),
    ("maximum_revision_rounds", 7.0), ("maximum_revision_rounds", 3),
    ("maximum_revision_rounds", 8), ("minimum_score", 1),
])
def test_exception_rejects_malformed_or_broader_scope(tmp_path: Path, field, value) -> None:
    metadata = _metadata(tmp_path)
    metadata[EXCEPTION_FIELD][field] = value
    with pytest.raises(ValueError, match=EXCEPTION_FIELD):
        revision_round_policy(PAPER_ID, metadata, {}, root=tmp_path)


@pytest.mark.parametrize("field,value", [
    ("actor", "assistant"), ("confirmed", False), ("confirmed", 1),
    ("source", ""), ("quote", ""), ("quote", "different authorization"),
    ("confirmed_at", "2020-01-01"), ("confirmed_at", "9999-01-01T00:00:00+00:00"),
    ("record", "../outside.json"), ("record", "/tmp/outside.json"),
    ("record", "registry/quality-gate-exceptions/../outside.json"),
    ("sha256", "0" * 64),
])
def test_exception_requires_exact_explicit_authorization(tmp_path: Path, field, value) -> None:
    metadata = _metadata(tmp_path)
    metadata[EXCEPTION_FIELD]["authorization"][field] = value
    with pytest.raises(ValueError, match=EXCEPTION_FIELD):
        revision_round_policy(PAPER_ID, metadata, {}, root=tmp_path)


@pytest.mark.parametrize("paper_ids", [[OTHER_ID], ["*"], [PAPER_ID, PAPER_ID], [1], []])
def test_authorization_record_must_explicitly_list_the_target(tmp_path: Path, paper_ids) -> None:
    metadata = _metadata(tmp_path)
    authorization = metadata[EXCEPTION_FIELD]["authorization"]
    path = tmp_path / authorization["record"]
    record = json.loads(path.read_text())
    record["paper_ids"] = paper_ids
    path.write_text(json.dumps(record))
    authorization["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="explicitly list"):
        revision_round_policy(PAPER_ID, metadata, {}, root=tmp_path)


def test_authorization_file_cannot_be_missing_changed_or_symlinked(tmp_path: Path) -> None:
    metadata = _metadata(tmp_path)
    path = tmp_path / metadata[EXCEPTION_FIELD]["authorization"]["record"]
    original = path.read_bytes()
    path.write_bytes(original + b"\n")
    with pytest.raises(ValueError, match="SHA256"):
        revision_round_policy(PAPER_ID, metadata, {}, root=tmp_path)
    path.unlink()
    with pytest.raises(ValueError, match="existing bounded"):
        revision_round_policy(PAPER_ID, metadata, {}, root=tmp_path)
    target = tmp_path / "elsewhere.json"
    target.write_bytes(original)
    path.symlink_to(target)
    with pytest.raises(ValueError, match="non-symlink"):
        revision_round_policy(PAPER_ID, metadata, {}, root=tmp_path)


@pytest.mark.parametrize("cap", [True, 3.0, "3", 0, -1])
def test_configured_cap_is_a_positive_integer(tmp_path: Path, cap) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        revision_round_policy(PAPER_ID, {}, {"maximum_revision_rounds": cap}, root=tmp_path)


def test_round_seven_is_recorded_truthfully_and_eight_is_rejected(tmp_path: Path) -> None:
    metadata = _gate(tmp_path)
    result = _record(tmp_path)
    assert result["passed"] is True
    assert result["revision_rounds"] == 7
    assert result["maximum_revision_rounds"] == 7
    assert result["minimum_score"] == 5
    release = load_paper_metadata(PAPER_ID, tmp_path)["writing_release"]
    assert release["revision_rounds_completed"] == 7
    assert release[EXCEPTION_FIELD] == metadata[EXCEPTION_FIELD]
    before = (tmp_path / "registry" / "papers" / f"{PAPER_ID}.yaml").read_bytes()
    with pytest.raises(ValueError, match="configured maximum of 7"):
        _record(tmp_path, rounds=8)
    assert (tmp_path / "registry" / "papers" / f"{PAPER_ID}.yaml").read_bytes() == before
    assert "maximum_revision_rounds: 3" in (tmp_path / "registry/settings.yaml").read_text()


@pytest.mark.parametrize("score,decision,blockers", [
    (4.9, "minor_revision", ()), (8, "major_revision", ()),
    (8, "minor_revision", ("Scientific evidence is incomplete.",)),
])
def test_exception_cannot_waive_the_quality_thresholds(tmp_path, score, decision, blockers) -> None:
    _gate(tmp_path)
    result = _record(tmp_path, score=score, decision=decision, blockers=blockers)
    assert result["passed"] is False
    assert result["status"] == "blocked"


def test_exception_cannot_replace_independent_review(tmp_path: Path) -> None:
    _gate(tmp_path, independent=True)
    result = _record(tmp_path, score=10, decision="accept")
    assert result["passed"] is False
    assert any("direct score entry is not a review" in item for item in result["unresolved_blockers"])


@pytest.mark.parametrize("rounds", [True, 1.1, "7", -1])
def test_round_count_is_a_nonnegative_integer(tmp_path: Path, rounds) -> None:
    _gate(tmp_path)
    with pytest.raises(ValueError, match="nonnegative integer"):
        _record(tmp_path, rounds=rounds)


def test_exception_does_not_expand_other_papers_budget(tmp_path: Path) -> None:
    _gate(tmp_path)
    create_paper(
        root=tmp_path, paper_id=OTHER_ID, title="Unrelated paper", created_at="2026-09-01",
        domain="math", subdomain="combinatorics", venue_type="journal",
    )
    with pytest.raises(ValueError, match="configured maximum of 3"):
        record_quality_gate(
            OTHER_ID, root=tmp_path, venue_type="journal", score=9,
            decision="accept", revision_rounds=4,
        )


@pytest.mark.parametrize("mutation", ["revoked", "deleted", "stale_cap", "stale_rounds", "missing_snapshot"])
def test_release_revalidates_the_exception(tmp_path: Path, mutation: str) -> None:
    _gate(tmp_path)
    _record(tmp_path)
    metadata = load_paper_metadata(PAPER_ID, tmp_path)
    if mutation == "revoked":
        metadata[EXCEPTION_FIELD]["active"] = False
    elif mutation == "deleted":
        del metadata[EXCEPTION_FIELD]
    elif mutation == "stale_cap":
        metadata["writing_release"]["max_revision_rounds"] = 3
    elif mutation == "stale_rounds":
        metadata["writing_release"]["revision_rounds_completed"] = 8
    elif mutation == "missing_snapshot":
        del metadata["writing_release"][EXCEPTION_FIELD]
    with pytest.raises(ValueError, match="stale"):
        validate_release_revision_policy(PAPER_ID, metadata, {}, root=tmp_path)


def _commit(root: Path, *paths: str) -> None:
    subprocess.run(["git", "add", "--", *paths], cwd=root, check=True)
    subprocess.run([
        "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "-qm", "Freeze scoped release inputs",
    ], cwd=root, check=True)


def test_handoff_requires_the_authorization_in_the_frozen_git_inputs(tmp_path: Path) -> None:
    _gate(tmp_path)
    (tmp_path / "papers" / PAPER_ID / "manuscript/main.pdf").write_bytes(b"%PDF frozen")
    _record(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    _commit(tmp_path, "registry/papers", "registry/settings.yaml", "papers")
    with pytest.raises(HandoffError, match="Release files are not committed.*test-authorization"):
        validate_release_preconditions(PAPER_ID, root=tmp_path)
    _commit(tmp_path, "registry/quality-gate-exceptions")
    assert validate_release_preconditions(PAPER_ID, root=tmp_path)["paper_id"] == PAPER_ID
    metadata = load_paper_metadata(PAPER_ID, tmp_path)
    metadata[EXCEPTION_FIELD]["active"] = False
    write_paper_metadata(PAPER_ID, metadata, tmp_path)
    with pytest.raises(HandoffError, match="revision policy is invalid"):
        validate_release_preconditions(PAPER_ID, root=tmp_path)
