from pathlib import Path

import pytest

from paper_writing.operations import create_paper, record_quality_gate, start_revision
from paper_writing.registry import (
    load_paper_metadata,
    load_registry,
    repository_root,
    write_paper_metadata,
)


ROOT = Path(__file__).resolve().parents[1]


def _settings(root: Path) -> None:
    registry = root / "registry"
    (registry / "papers").mkdir(parents=True)
    (registry / "settings.yaml").write_text(
        """schema_version: ara.paper_writing.registry.v1
require_registration: true
support_publication:
  default_mode: zenodo_only
  infer_github_mode_from_existing_url: false
  zenodo_environment: sandbox
quality_gate:
  minimum_score: 5.0
  maximum_revision_rounds: 3
  decision_standard: cas_zone_1_journal
  cas_zone_1_scope: major_category
  cas_zone_1_minimum_decision: minor_revision
  conference_minimum_decision: weak_accept
  journal_minimum_decision: minor_revision
defaults: {}
""",
        encoding="utf-8",
    )


def test_real_registry_contains_migrated_papers() -> None:
    registry = load_registry(repository_root(), include_local_repositories=False)

    assert len(registry["papers"]) == 45
    assert "papers/20260706aihealth0001" in registry["papers"]
    for paper_id in (
        "20260718matherdos0001",
        "20260720matherdos0002",
        "20260720matherdos0003",
        "20260721matherdos0001",
        "20260724mathgraph0007",
    ):
        assert f"papers/{paper_id}" in registry["papers"]


def test_journal_target_policy_requires_tier_fee_and_canonical_format(tmp_path: Path) -> None:
    _settings(tmp_path)
    settings = tmp_path / "registry" / "settings.yaml"
    settings.write_text(
        settings.read_text(encoding="utf-8")
        + """journal_target_policy:
  required_after_basic_draft: true
  classification_system: 2026 XinRui Mathematics
  allowed_tiers: [1, 2]
  require_no_mandatory_author_fee: true
  require_canonical_venue_format: true
""",
        encoding="utf-8",
    )
    paper_id = "20260813-math-graph-target-policy"
    create_paper(
        root=tmp_path,
        paper_id=paper_id,
        title="A policy test",
        created_at="2026-08-13",
        domain="math",
        subdomain="graph",
        venue_type="journal",
        target_journal="A Journal",
    )

    with pytest.raises(ValueError, match="target_journal_tier"):
        load_registry(tmp_path, include_local_repositories=False)

    metadata = load_paper_metadata(paper_id, tmp_path)
    metadata.update(
        {
            "target_journal_tier": 2,
            "target_journal_ranking_system": "2026 XinRui Mathematics",
            "target_journal_ranking_source": "https://example.test/ranking",
            "target_journal_fee_policy": "no_mandatory_author_fee",
            "target_journal_fee_source": "https://example.test/fees",
            "target_journal_checked_at": "2026-08-13",
            "target_journal_format": {
                "canonical": True,
                "source": "https://example.test/format",
                "checked_at": "2026-08-13",
            },
        }
    )
    write_paper_metadata(paper_id, metadata, tmp_path)
    assert load_registry(tmp_path, include_local_repositories=False)["papers"]


def test_journal_target_policy_supports_domain_specific_systems(tmp_path: Path) -> None:
    _settings(tmp_path)
    settings = tmp_path / "registry" / "settings.yaml"
    settings.write_text(
        settings.read_text(encoding="utf-8")
        + """journal_target_policy:
  required_after_basic_draft: true
  classification_system:
    ai: [2026 XinRui Computer Science, 2026 XinRui Medicine]
  allowed_tiers: [1, 2]
  require_no_mandatory_author_fee: true
  require_canonical_venue_format: true
""",
        encoding="utf-8",
    )
    paper_id = "20260814-ai-health-target-system"
    create_paper(
        root=tmp_path,
        paper_id=paper_id,
        title="A cross-domain policy test",
        created_at="2026-08-14",
        domain="ai",
        subdomain="health",
        venue_type="journal",
        target_journal="Health AI Journal",
    )
    metadata = load_paper_metadata(paper_id, tmp_path)
    metadata.update(
        {
            "target_journal_tier": 2,
            "target_journal_ranking_system": "2026 XinRui Medicine",
            "target_journal_ranking_source": "https://example.test/ranking",
            "target_journal_fee_policy": "no_mandatory_author_fee",
            "target_journal_fee_source": "https://example.test/fees",
            "target_journal_checked_at": "2026-08-24",
            "target_journal_format": {
                "canonical": True,
                "source": "https://example.test/format",
                "checked_at": "2026-08-24",
            },
        }
    )
    write_paper_metadata(paper_id, metadata, tmp_path)
    assert load_registry(tmp_path, include_local_repositories=False)["papers"]


def test_journal_target_policy_grandfathers_truthful_pre_policy_metadata(
    tmp_path: Path,
) -> None:
    _settings(tmp_path)
    settings = tmp_path / "registry" / "settings.yaml"
    settings.write_text(
        settings.read_text(encoding="utf-8")
        + """journal_target_policy:
  required_after_basic_draft: true
  effective_from: '2026-08-27'
  classification_system:
    math: [2026 XinRui Mathematics]
  allowed_tiers: [1, 2]
  require_no_mandatory_author_fee: true
  require_canonical_venue_format: true
""",
        encoding="utf-8",
    )
    paper_id = "20260801-math-graph-legacy-target"
    create_paper(
        root=tmp_path,
        paper_id=paper_id,
        title="A pre-policy target",
        created_at="2026-08-01",
        domain="math",
        subdomain="graph",
        venue_type="journal",
        target_journal="A historical target",
    )
    metadata = load_paper_metadata(paper_id, tmp_path)
    metadata["target_journal_checked_at"] = "2026-08-07"
    write_paper_metadata(paper_id, metadata, tmp_path)

    assert load_registry(tmp_path, include_local_repositories=False)["papers"]


def test_create_revision_and_quality_gate(tmp_path: Path) -> None:
    _settings(tmp_path)
    paper_id = "20260721-ai-llm-reliability-audit"
    create_paper(
        root=tmp_path,
        paper_id=paper_id,
        title="A test manuscript",
        created_at="2026-07-21",
        domain="ai",
        subdomain="llm",
        venue_type="journal",
        target_journal="Journal of Artificial Intelligence Research",
    )

    failed = record_quality_gate(
        paper_id,
        venue_type="journal",
        score=6.5,
        decision="major_revision",
        revision_rounds=2,
        root=tmp_path,
    )
    assert failed["status"] == "revision_required"
    below_score_floor = record_quality_gate(
        paper_id,
        venue_type="journal",
        score=4.99,
        decision="minor_revision",
        revision_rounds=2,
        root=tmp_path,
    )
    assert below_score_floor["passed"] is False
    assert below_score_floor["status"] == "revision_required"
    evidence_blocked = record_quality_gate(
        paper_id,
        venue_type="journal",
        score=5,
        decision="minor_revision",
        revision_rounds=2,
        unresolved_blockers=["A material claim is not mapped to evidence."],
        root=tmp_path,
    )
    assert evidence_blocked["passed"] is False
    assert evidence_blocked["status"] == "revision_required"
    assert evidence_blocked["unresolved_blockers"] == [
        "A material claim is not mapped to evidence."
    ]
    revision = start_revision(paper_id, "quality gate", root=tmp_path)
    assert revision["round"] == 1
    assert load_paper_metadata(paper_id, tmp_path)["writing_release"]["status"] == "draft"
    passed = record_quality_gate(
        paper_id,
        venue_type="journal",
        score=5.0,
        decision="minor_revision",
        revision_rounds=3,
        root=tmp_path,
    )
    assert passed["passed"] is True
    assert passed["score"] == 5.0
    assert passed["minimum_score"] == 5.0
    assert passed["decision_standard"] == "cas_zone_1_journal"

    metadata = load_paper_metadata(paper_id, tmp_path)
    assert metadata["record_status"] == "paper_workspace"
    assert metadata["work_id"] == "ai-llm-reliability-audit"
    assert metadata["display_id"] == paper_id
    assert metadata["project_name"] == "ai-llm-reliability-audit"
    assert metadata["target_journal"] == "Journal of Artificial Intelligence Research"
    assert metadata["writing_release"]["status"] == "ready"
    assert metadata["writing_release"]["decision_standard"] == "cas_zone_1_journal"
    assert metadata["writing_release"]["manuscript_version"] == "0.1.1"
    assert len(metadata["writing_release"]["manuscript_snapshot_sha256"]) == 64
    assert "submission" not in metadata
    assert metadata["version"] == "0.1.1"


def test_cas_zone_1_gate_is_independent_of_actual_venue_type(tmp_path: Path) -> None:
    _settings(tmp_path)
    paper_id = "20260804-ai-ml-calibration-study"
    create_paper(
        root=tmp_path,
        paper_id=paper_id,
        title="A conference-targeted test manuscript",
        created_at="2026-08-04",
        domain="ai",
        subdomain="ml",
        venue_type="conference",
    )

    result = record_quality_gate(
        paper_id,
        venue_type="conference",
        score=6,
        decision="minor_revision",
        revision_rounds=0,
        root=tmp_path,
    )

    assert result["passed"] is True
    metadata = load_paper_metadata(paper_id, tmp_path)
    assert metadata["writing_release"]["venue_type"] == "conference"
    assert metadata["writing_release"]["decision_standard"] == "cas_zone_1_journal"


def test_create_paper_rejects_legacy_or_mismatched_new_ids(tmp_path: Path) -> None:
    _settings(tmp_path)
    with pytest.raises(ValueError, match="YYYYMMDD-domain-subdomain-keywords"):
        create_paper(
            root=tmp_path,
            paper_id="20260721aillm0001",
            title="Legacy naming",
            project_name="legacy-naming",
            created_at="2026-07-21",
            domain="ai",
            subdomain="llm",
            venue_type="journal",
        )
    with pytest.raises(ValueError, match="must start with 20260721-"):
        create_paper(
            root=tmp_path,
            paper_id="20260722-math-erdos-866-pairwise-sum",
            title="Wrong date",
            project_name="erdos-866-pairwise-sum",
            created_at="2026-07-21",
            domain="math",
            subdomain="erdos",
            venue_type="journal",
        )
    with pytest.raises(ValueError, match="domain segment 'cs'"):
        create_paper(
            root=tmp_path,
            paper_id="20260721-cs-llm-reliability-audit",
            title="Wrong domain segment",
            created_at="2026-07-21",
            domain="ai",
            subdomain="llm",
            venue_type="journal",
        )
    with pytest.raises(ValueError, match="subdomain segment 'health'"):
        create_paper(
            root=tmp_path,
            paper_id="20260721-ai-health-reliability-audit",
            title="Wrong subdomain segment",
            created_at="2026-07-21",
            domain="ai",
            subdomain="llm",
            venue_type="journal",
        )
