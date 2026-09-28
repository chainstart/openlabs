import json
from pathlib import Path

from paper_writing.editorial_screen import editorial_screen_blockers
from paper_writing.handoff import manuscript_snapshot_sha256
from paper_writing.operations import create_paper, record_quality_gate
from paper_writing.registry import load_paper_metadata, write_paper_metadata


PAPER_ID = "20260928-math-graph-editorial-screen"
TARGET = "Example Journal"
SNAPSHOT = "a" * 64


def _receipt() -> dict:
    return {
        "schema_version": "openlabs.paper_writing.editorial_screen.v1",
        "paper_id": PAPER_ID,
        "manuscript_snapshot_sha256": SNAPSHOT,
        "target_journal": TARGET,
        "decision": "pass",
        "independent_context": True,
        "prior_rejections_reviewed": True,
        "reviewed_at_utc": "2026-09-28T12:00:00Z",
        "reviewer_model": "gpt-6-sol",
        "contribution": "A specified new theorem",
        "why_target_readers_care": "It resolves a question in the journal's scope",
        "research_depth": "It extends the known range",
        "editorial_risk": "The theorem remains specialized",
        "required_scientific_work": [],
        "closest_work": [
            {"source": "https://example.org/a", "known_result": "A", "advance": "B"},
            {"source": "https://example.org/b", "known_result": "C", "advance": "D"},
        ],
        "target_articles": ["https://example.org/c", "https://example.org/d"],
        "rejection_responses": [
            {"decision_source": "anticipated", "concern": "Too narrow", "current_evidence": "New theorem", "remaining_limit": "One case"}
        ],
    }


def test_editorial_screen_binds_target_snapshot_and_unresolved_work(tmp_path: Path) -> None:
    metadata = {
        "target_journal": TARGET,
        "target_journal_fit": {"status": "approved"},
        "target_journal_ranking_year": 2025,
        "target_journal_ranking_scope": "major_category",
        "editorial_screen": {"source": "reviews/editorial-screens/test.json"},
        "journal_rejections": [{"source": "maintenance/decision.json"}],
    }
    path = tmp_path / metadata["editorial_screen"]["source"]
    path.parent.mkdir(parents=True)
    receipt = _receipt()
    receipt["rejection_responses"][0]["decision_source"] = "maintenance/decision.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    blockers, digest = editorial_screen_blockers(PAPER_ID, metadata, tmp_path, SNAPSHOT)
    assert blockers == [] and digest is not None

    receipt["rejection_responses"][0]["decision_source"] = "anticipated"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    blockers, _ = editorial_screen_blockers(PAPER_ID, metadata, tmp_path, SNAPSHOT)
    assert any("not every registered rejection" in item for item in blockers)

    receipt["rejection_responses"][0]["decision_source"] = "maintenance/decision.json"
    receipt["manuscript_snapshot_sha256"] = "b" * 64
    receipt["required_scientific_work"] = ["Prove the general case"]
    path.write_text(json.dumps(receipt), encoding="utf-8")
    blockers, changed_digest = editorial_screen_blockers(PAPER_ID, metadata, tmp_path, SNAPSHOT)
    assert changed_digest != digest
    assert any("manuscript_snapshot_sha256" in item for item in blockers)
    assert any("unresolved scientific work" in item for item in blockers)


def test_journal_quality_gate_requires_editorial_screen(tmp_path: Path) -> None:
    registry = tmp_path / "registry"
    (registry / "papers").mkdir(parents=True)
    (registry / "settings.yaml").write_text(
        "schema_version: ara.paper_writing.registry.v1\n"
        "require_registration: true\n"
        "quality_gate:\n"
        "  minimum_score: 5\n"
        "  maximum_revision_rounds: 3\n"
        "  decision_standard: cas_zone_1_journal\n"
        "  cas_zone_1_minimum_decision: minor_revision\n"
        "  require_validated_independent_review: false\n"
        "  require_target_editorial_screen: true\n",
        encoding="utf-8",
    )
    create_paper(
        root=tmp_path, paper_id=PAPER_ID, title="A test", created_at="2026-09-28",
        domain="math", subdomain="graph", venue_type="journal", target_journal=TARGET,
    )
    result = record_quality_gate(
        PAPER_ID, venue_type="journal", score=8, decision="accept",
        revision_rounds=1, root=tmp_path,
    )
    assert result["status"] == "revision_required"
    assert any("EDITORIAL-SCREEN" in item for item in result["unresolved_blockers"])

    metadata = load_paper_metadata(PAPER_ID, tmp_path)
    assert metadata["writing_release"]["status"] != "ready"
    manuscript = tmp_path / "papers" / PAPER_ID / "manuscript"
    receipt = _receipt()
    receipt["manuscript_snapshot_sha256"] = manuscript_snapshot_sha256(
        manuscript, manuscript / "main.pdf"
    )
    metadata.update({
        "target_journal_fit": {"status": "approved"},
        "target_journal_ranking_year": 2025,
        "target_journal_ranking_scope": "major_category",
        "editorial_screen": {"source": "reviews/editorial-screens/approved.json"},
    })
    write_paper_metadata(PAPER_ID, metadata, tmp_path)
    screen = tmp_path / "reviews" / "editorial-screens" / "approved.json"
    screen.parent.mkdir(parents=True)
    screen.write_text(json.dumps(receipt), encoding="utf-8")
    passed = record_quality_gate(
        PAPER_ID, venue_type="journal", score=8, decision="accept",
        revision_rounds=1, root=tmp_path,
    )
    assert passed["status"] == "ready"
    assert load_paper_metadata(PAPER_ID, tmp_path)["writing_release"]["editorial_screen_sha256"]
