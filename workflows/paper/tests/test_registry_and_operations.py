from pathlib import Path

import pytest

from paper_writing.operations import (
    canonical_public_manuscript_filename,
    create_paper,
    record_quality_gate,
    reuse_review_for_metadata_only_revision,
    start_revision,
)
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
  default_license: cc-by-4.0
  infer_github_mode_from_existing_url: false
  zenodo_environment: sandbox
quality_gate:
  minimum_score: 5.0
  require_validated_independent_review: false
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

    assert len(registry["papers"]) >= 46
    assert "papers/20260706aihealth0001" in registry["papers"]
    assert "papers/20260828-physics-hep-p5-chain-bootstrap" in registry["papers"]
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

    indexed = load_registry(
        tmp_path,
        include_local_repositories=False,
        enforce_target_policy=False,
    )
    assert indexed["papers"][f"papers/{paper_id}"]["target_journal"] == "A Journal"

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


def test_journal_target_policy_accepts_scoped_user_tier_override(tmp_path: Path) -> None:
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
    paper_id = "20260902-math-group-tier-override"
    create_paper(
        root=tmp_path,
        paper_id=paper_id,
        title="A scoped target override test",
        created_at="2026-09-02",
        domain="math",
        subdomain="group",
        venue_type="journal",
        target_journal="A Specialist Journal",
    )
    metadata = load_paper_metadata(paper_id, tmp_path)
    metadata.update(
        {
            "target_journal_tier": 3,
            "target_journal_ranking_system": "2026 XinRui Mathematics",
            "target_journal_ranking_source": "https://example.test/ranking",
            "target_journal_fee_policy": "no_mandatory_author_fee",
            "target_journal_fee_source": "https://example.test/fees",
            "target_journal_checked_at": "2026-09-02",
            "target_journal_format": {
                "canonical": True,
                "source": "https://example.test/format",
                "checked_at": "2026-09-02",
            },
            "target_policy_exception": {
                "status": "approved",
                "kind": "target_journal_tier_override",
                "scope": "this_paper_and_target_only",
                "target_journal": "A Specialist Journal",
                "target_journal_tier": 3,
                "authorized_by": "user",
                "authorized_at": "2026-09-02T06:05:49+00:00",
                "reason": "The user explicitly selected this specialist venue.",
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


def test_quality_gate_scopes_registry_validation_to_target_paper(tmp_path: Path) -> None:
    _settings(tmp_path)
    settings = tmp_path / "registry" / "settings.yaml"
    settings.write_text(
        settings.read_text(encoding="utf-8")
        + """journal_target_policy:
  required_after_basic_draft: true
  classification_system: 2026 XinRui Physics
  allowed_tiers: [1, 2]
""",
        encoding="utf-8",
    )
    paper_id = "20260901-math-combinatorics-scoped-gate"
    create_paper(
        root=tmp_path,
        paper_id=paper_id,
        title="A scoped quality-gate test",
        created_at="2026-09-01",
        domain="math",
        subdomain="combinatorics",
        venue_type="journal",
    )
    unrelated_id = "20260901-physics-hep-transient-target"
    create_paper(
        root=tmp_path,
        paper_id=unrelated_id,
        title="An unrelated transient record",
        created_at="2026-09-01",
        domain="physics",
        subdomain="hep",
        venue_type="journal",
        target_journal="A Physics Journal",
    )
    unrelated = load_paper_metadata(unrelated_id, tmp_path)
    unrelated["target_journal_tier"] = 3
    write_paper_metadata(unrelated_id, unrelated, tmp_path)

    with pytest.raises(ValueError, match=unrelated_id):
        load_registry(tmp_path, include_local_repositories=False)

    scoped = load_registry(
        tmp_path,
        include_local_repositories=False,
        paper_ids=[paper_id],
    )
    assert list(scoped["papers"]) == [f"papers/{paper_id}"]
    result = record_quality_gate(
        paper_id,
        venue_type="journal",
        score=6,
        decision="minor_revision",
        revision_rounds=0,
        root=tmp_path,
    )
    assert result["passed"] is True

    target = load_paper_metadata(paper_id, tmp_path)
    target["target_journal"] = "A Mathematics Journal"
    target["target_journal_tier"] = 3
    write_paper_metadata(paper_id, target, tmp_path)
    with pytest.raises(ValueError, match=paper_id):
        record_quality_gate(
            paper_id,
            venue_type="journal",
            score=6,
            decision="minor_revision",
            revision_rounds=0,
            root=tmp_path,
        )


def test_direct_score_cannot_replace_required_independent_review(tmp_path: Path) -> None:
    _settings(tmp_path)
    settings = tmp_path / "registry" / "settings.yaml"
    settings.write_text(
        settings.read_text(encoding="utf-8").replace(
            "require_validated_independent_review: false",
            "require_validated_independent_review: true",
        ),
        encoding="utf-8",
    )
    paper_id = "20260829-physics-hep-independent-review-gate"
    create_paper(
        root=tmp_path,
        paper_id=paper_id,
        title="An independent-review gate test",
        created_at="2026-08-29",
        domain="physics",
        subdomain="hep",
        venue_type="journal",
    )

    result = record_quality_gate(
        paper_id,
        venue_type="journal",
        score=8,
        decision="accept",
        revision_rounds=0,
        root=tmp_path,
    )

    assert result["passed"] is False
    assert result["status"] == "revision_required"
    assert any(
        "direct score entry is not a review" in blocker
        for blocker in result["unresolved_blockers"]
    )


def test_author_only_revision_reuses_review_but_body_change_fails_closed(
    tmp_path: Path,
) -> None:
    _settings(tmp_path)
    paper_id = "20260829-physics-hep-author-metadata-revision"
    create_paper(
        root=tmp_path,
        paper_id=paper_id,
        title="An author metadata revision test",
        created_at="2026-08-29",
        domain="physics",
        subdomain="hep",
        venue_type="journal",
    )
    first_gate = record_quality_gate(
        paper_id,
        venue_type="journal",
        score=8,
        decision="accept",
        revision_rounds=0,
        root=tmp_path,
    )
    assert first_gate["passed"] is True
    original_reviewed_at = load_paper_metadata(paper_id, tmp_path)["writing_release"][
        "reviewed_at"
    ]

    revision = start_revision(paper_id, "add a second author", root=tmp_path)
    assert revision["review_carry_forward_available"] is True
    manuscript = tmp_path / "papers" / paper_id / "manuscript"
    main = manuscript / "main.tex"
    main.write_text(
        main.read_text(encoding="utf-8").replace(
            "\\author{}",
            "\\author[a]{First Author}\n"
            "\\author[b]{Second Author}\n"
            "\\affiliation[a]{First Institute}\n"
            "\\affiliation[b]{Second Institute}\n"
            "\\emailAdd{second@example.test}",
        ),
        encoding="utf-8",
    )
    (manuscript / "main.pdf").write_bytes(b"%PDF rebuilt author edition")

    reused = reuse_review_for_metadata_only_revision(paper_id, root=tmp_path)
    assert reused["status"] == "ready"
    assert reused["llm_review_rerun"] is False
    metadata = load_paper_metadata(paper_id, tmp_path)
    assert metadata["writing_release"]["reviewed_at"] == original_reviewed_at
    assert metadata["writing_release"]["manuscript_version"] == "0.1.1"
    assert metadata["writing_release"]["review_reuse"]["classification"] == (
        "author_or_release_metadata_only"
    )

    next_revision = start_revision(paper_id, "change a result", root=tmp_path)
    assert next_revision["review_carry_forward_available"] is True
    main.write_text(
        main.read_text(encoding="utf-8").replace(
            "\\begin{abstract}\n\\end{abstract}",
            "\\begin{abstract}\nA new scientific claim.\n\\end{abstract}",
        ),
        encoding="utf-8",
    )
    (manuscript / "main.pdf").write_bytes(b"%PDF scientific revision")
    with pytest.raises(ValueError, match="Fresh scientific review required"):
        reuse_review_for_metadata_only_revision(paper_id, root=tmp_path)


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


def test_create_paper_applies_configured_support_license(tmp_path: Path) -> None:
    _settings(tmp_path)
    paper_id = "20260804-math-graph-default-license"

    create_paper(
        root=tmp_path,
        paper_id=paper_id,
        title="A default-license test",
        created_at="2026-08-04",
        domain="math",
        subdomain="graph",
        venue_type="journal",
    )

    publication = load_paper_metadata(paper_id, tmp_path)["support"]["publication"]
    assert publication == {
        "mode": "zenodo_only",
        "status": "planned",
        "license": "cc-by-4.0",
    }


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


@pytest.mark.parametrize(
    "paper_id,tracking_label",
    [
        ("20260830-physics-hep-tp-042", "tp-042"),
        ("20260830-physics-hep-tp042-bootstrap", "tp042"),
        ("20260830-math-number-problem-29", "problem-29"),
        ("20260830-ai-llm-round5-ablation", "round5"),
    ],
)
def test_create_paper_rejects_repository_local_tracking_ids(
    tmp_path: Path, paper_id: str, tracking_label: str
) -> None:
    _settings(tmp_path)
    domain, subdomain = paper_id.split("-")[1:3]
    with pytest.raises(ValueError, match=tracking_label):
        create_paper(
            root=tmp_path,
            paper_id=paper_id,
            title="Internal tracking must not become a paper identifier",
            created_at="2026-08-30",
            domain=domain,
            subdomain=subdomain,
            venue_type="journal",
        )


def test_public_manuscript_filename_uses_display_id_and_semantic_version(
    tmp_path: Path,
) -> None:
    _settings(tmp_path)
    paper_id = "20260830-physics-hep-p5-chain-bootstrap"
    create_paper(
        root=tmp_path,
        paper_id=paper_id,
        title="A public naming test",
        created_at="2026-08-30",
        domain="physics",
        subdomain="hep",
        venue_type="journal",
    )

    assert canonical_public_manuscript_filename(paper_id, root=tmp_path) == (
        "20260830-physics-hep-p5-chain-bootstrap-v0.1.0.pdf"
    )

    metadata = load_paper_metadata(paper_id, tmp_path)
    metadata["display_id"] = "20260830-physics-hep-tp-042"
    write_paper_metadata(paper_id, metadata, tmp_path)
    with pytest.raises(ValueError, match="repository-local tracking label 'tp-042'"):
        load_registry(tmp_path, include_local_repositories=False)


def test_create_paper_accepts_namespaced_external_problem_identifier(
    tmp_path: Path,
) -> None:
    _settings(tmp_path)
    paper_id = "20260830-math-erdos-866-sumfree-bound"

    path = create_paper(
        root=tmp_path,
        paper_id=paper_id,
        title="A catalogued problem",
        created_at="2026-08-30",
        domain="math",
        subdomain="erdos",
        venue_type="journal",
    )

    assert path.name == f"{paper_id}.yaml"


@pytest.mark.parametrize("created_at", ["2026-02-30", "20260830"])
def test_create_paper_rejects_invalid_or_noncanonical_date(
    tmp_path: Path, created_at: str
) -> None:
    _settings(tmp_path)
    with pytest.raises(ValueError, match="valid YYYY-MM-DD"):
        create_paper(
            root=tmp_path,
            paper_id="20260830-physics-hep-chain-bootstrap",
            title="An invalid date",
            created_at=created_at,
            domain="physics",
            subdomain="hep",
            venue_type="journal",
        )
