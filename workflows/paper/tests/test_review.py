import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from paper_writing.handoff import manuscript_snapshot_sha256, sha256_file
from paper_writing.operations import apply_review_record
from paper_writing.registry import load_paper_metadata
from paper_writing.review import (
    CAS_ZONE_1_JOURNAL_VIEW,
    CS_TOP_TIER_REVIEWER_ROLE,
    CS_TOP_TIER_RUBRIC_ID,
    FOUR_TOP_MATH_JOURNALS_VIEW,
    INDIVIDUAL_REVIEW_SCHEMA_VERSION,
    LEADING_MATERIALS_JOURNALS_VIEW,
    LEADING_QUANT_FINANCE_JOURNALS_VIEW,
    LEAN_OBJECTIVE_AUDIT_KIND,
    LEAN_OBJECTIVE_AUDIT_SCHEMA_VERSION,
    LEGACY_REVIEW_SCHEMA_VERSION,
    MATERIALS_LEADING_JOURNALS_RUBRIC_ID,
    MATERIALS_REVIEWER_ROLE,
    MATH_FOUR_JOURNALS_RUBRIC_ID,
    MATHEMATICS_REVIEWER_ROLE,
    QUANT_FINANCE_LEADING_JOURNALS_RUBRIC_ID,
    QUANT_FINANCE_REVIEWER_ROLE,
    RECOMMENDATION_SCHEMA_VERSION,
    REVIEW_SCHEMA_VERSION,
    TOP_CONFERENCE_VIEW,
    decision_meets_standard_threshold,
    decision_meets_threshold,
    review_safe_registry,
    reviewer_role_for_domain,
    rubric_id_for_role,
    validate_review_panel_files,
    validate_review_record,
)

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "skills" / "openlabs-paper-review" / "scripts" / "validate_review.py"
AGGREGATOR = ROOT / "skills" / "openlabs-paper-review" / "scripts" / "aggregate_panel.py"
CLAUDE_REVIEWER = ROOT / "skills" / "openlabs-paper-review" / "scripts" / "run_claude_reviewer.py"


def test_review_safe_registry_removes_all_review_projections() -> None:
    metadata = {
        "paper_id": "paper",
        "review_file": "reviews/old.md",
        "ara_llm_self_review": {"score": 5},
        "writing_release": {"decision": "minor_revision"},
        "support": {
            "publication": {
                "version_doi": "10.5281/zenodo.1",
                "release_binding": {"score": 6, "decision": "minor_revision"},
            }
        },
    }

    safe = review_safe_registry(metadata)

    assert "review_file" not in safe
    assert "ara_llm_self_review" not in safe
    assert "writing_release" not in safe
    assert "release_binding" not in safe["support"]["publication"]
    assert safe["support"]["publication"]["version_doi"] == "10.5281/zenodo.1"
    assert metadata["support"]["publication"]["release_binding"]["score"] == 6


def _review(*, paper_id: str = "20260804-ai-llm-review-test", role: str = "cs_top_tier") -> dict:
    if role == MATHEMATICS_REVIEWER_ROLE:
        recommendations = {
            FOUR_TOP_MATH_JOURNALS_VIEW: {
                "decision": "reject",
                "confidence": "high",
                "rationale": "The contribution is below the four-journal bar.",
            },
            CAS_ZONE_1_JOURNAL_VIEW: {
                "decision": "major_revision",
                "confidence": "high",
                "rationale": "Substantive mathematical repair is still required.",
            },
        }
    elif role == MATERIALS_REVIEWER_ROLE:
        recommendations = {
            LEADING_MATERIALS_JOURNALS_VIEW: {
                "decision": "major_revision",
                "confidence": "high",
                "rationale": "The evidence package needs stronger validation.",
            },
            CAS_ZONE_1_JOURNAL_VIEW: {
                "decision": "major_revision",
                "confidence": "high",
                "rationale": "The study is promising but not yet ready.",
            },
        }
    elif role == QUANT_FINANCE_REVIEWER_ROLE:
        recommendations = {
            LEADING_QUANT_FINANCE_JOURNALS_VIEW: {
                "decision": "major_revision",
                "confidence": "high",
                "rationale": "The finance evidence package needs stronger validation.",
            },
            CAS_ZONE_1_JOURNAL_VIEW: {
                "decision": "major_revision",
                "confidence": "high",
                "rationale": "The study is promising but not yet ready.",
            },
        }
    else:
        recommendations = {
            TOP_CONFERENCE_VIEW: {
                "seven_point": {
                    "decision": "weak_reject",
                    "confidence": "high",
                    "rationale": "The contribution is not yet at the selective conference bar.",
                }
            },
            CAS_ZONE_1_JOURNAL_VIEW: {
                "decision": "major_revision",
                "confidence": "high",
                "rationale": "The paper may become viable after substantive repair.",
            },
        }
    return {
        "schema_version": INDIVIDUAL_REVIEW_SCHEMA_VERSION,
        "scores": {
            "clarity": 7,
            "soundness": 6,
            "significance": 6,
            "novelty": 5,
            "overall": 6,
        },
        "strengths": ["The central question is clearly stated."],
        "weaknesses": ["The evidence does not yet support the broadest claim."],
        "section_feedback": {"introduction": "Narrow the contribution statement."},
        "required_changes": ["Add evidence or narrow the central claim."],
        "change_requests": [
            {
                "request": "Narrow the abstract claim.",
                "category": "title_abstract_scope",
                "priority": "high",
                "targets": ["introduction"],
                "rationale": "The current evidence is narrower than the claim.",
                "text_only": True,
            }
        ],
        "unresolved_blockers": ["The broad claim remains unsupported."],
        "recommendations": recommendations,
        "publishability_summary": {
            "text_ready": False,
            "scientific_ready": False,
            "blocking_reason": "The central evidence gap remains.",
        },
        "review_metadata": {
            "paper_id": paper_id,
            "reviewer_role": role,
            "score_kind": "ara_llm_self_review",
            "rubric_id": rubric_id_for_role(role),
            "recommendation_schema_version": RECOMMENDATION_SCHEMA_VERSION,
            "cas_zone_1_basis": {
                "scope": "major_category",
                "mode": "generic_standard",
                "target_journal": None,
                "classification_source": None,
                "classification_checked_at": None,
            },
            "not_external_peer_review": True,
            "simulated_venue_decisions": True,
            "review_only": True,
            "model": "test-model",
            "reasoning_effort": "high",
            "reviewed_at_utc": "2026-08-04T00:00:00+00:00",
            "main_tex_sha256": "a" * 64,
            "manuscript_snapshot_sha256_before": "b" * 64,
            "manuscript_snapshot_sha256_after": "b" * 64,
            "manuscript_unchanged": True,
        },
    }


def _write_panel(
    root: Path,
    *,
    paper_id: str,
    role: str,
    snapshot: str,
    main_tex_sha256: str,
    ready: bool = False,
) -> Path:
    panel_dir = root / "reviews" / "fresh" / paper_id
    panel_dir.mkdir(parents=True, exist_ok=True)
    records = []
    reviewer_payloads = []
    overall_values = [6, 7] if ready else [5, 6]
    cas_decisions = (
        ["accept", "minor_revision"]
        if ready
        else [
            "major_revision",
            "reject_and_resubmit",
        ]
    )
    for index in range(2):
        reviewer = _review(paper_id=paper_id, role=role)
        reviewer["scores"]["overall"] = overall_values[index]
        reviewer["recommendations"][CAS_ZONE_1_JOURNAL_VIEW]["decision"] = cas_decisions[index]
        provider = "openai-codex" if index == 0 else "packy"
        model = "test-codex" if index == 0 else "claude-opus-5"
        reviewer["review_metadata"].update(
            {
                "provider": provider,
                "model": model,
                "main_tex_sha256": main_tex_sha256,
                "manuscript_snapshot_sha256_before": snapshot,
                "manuscript_snapshot_sha256_after": snapshot,
                "panel_reviewer_id": f"reviewer-{index + 1}",
                "independent_context": True,
                "prior_reviews_hidden": True,
            }
        )
        if index == 1:
            reviewer["review_metadata"]["hidden_peer_review_sha256"] = records[0]["sha256"]
        if ready:
            reviewer["unresolved_blockers"] = []
            reviewer["publishability_summary"] = {
                "text_ready": True,
                "scientific_ready": True,
                "blocking_reason": "",
            }
        source_path = panel_dir / f"reviewer-{index + 1}.json"
        source_path.write_text(json.dumps(reviewer), encoding="utf-8")
        records.append(
            {
                "reviewer_id": f"reviewer-{index + 1}",
                "provider": provider,
                "model": model,
                "source": source_path.relative_to(root).as_posix(),
                "sha256": sha256_file(source_path),
            }
        )
        reviewer_payloads.append(reviewer)

    panel = deepcopy(reviewer_payloads[0])
    panel["schema_version"] = REVIEW_SCHEMA_VERSION
    panel["scores"]["overall"] = min(overall_values)
    panel["recommendations"][CAS_ZONE_1_JOURNAL_VIEW]["decision"] = cas_decisions[-1]
    panel["review_metadata"].pop("panel_reviewer_id")
    panel["review_metadata"].pop("independent_context")
    panel["review_metadata"].pop("prior_reviews_hidden")
    panel["review_metadata"].pop("provider")
    panel["review_metadata"].update(
        {
            "model": "codex-plus-claude-opus-5-conservative-panel",
            "reasoning_effort": "mechanical conservative aggregation",
            "review_panel": {
                "panel_size": 2,
                "score_aggregation": "coordinatewise_minimum",
                "decision_aggregation": "strictest_decision",
                "parallel_execution": False,
                "independent_contexts": True,
                "prior_reviews_hidden": True,
                "reviewer_records": records,
            },
        }
    )
    panel_path = panel_dir / "review.json"
    panel_path.write_text(json.dumps(panel), encoding="utf-8")
    return panel_path


def test_domain_routing_matches_openlabs_roles() -> None:
    for domain in ("ai", "cs", "se", "machine-learning", "software engineering"):
        assert reviewer_role_for_domain(domain) == CS_TOP_TIER_REVIEWER_ROLE
    for domain in ("math", "mathematics"):
        assert reviewer_role_for_domain(domain) == MATHEMATICS_REVIEWER_ROLE
    for domain in ("materials", "materials-science"):
        assert reviewer_role_for_domain(domain) == MATERIALS_REVIEWER_ROLE
    for domain in ("quant", "finance", "quantitative-finance"):
        assert reviewer_role_for_domain(domain) == QUANT_FINANCE_REVIEWER_ROLE
    assert rubric_id_for_role(CS_TOP_TIER_REVIEWER_ROLE) == CS_TOP_TIER_RUBRIC_ID
    assert rubric_id_for_role(MATHEMATICS_REVIEWER_ROLE) == MATH_FOUR_JOURNALS_RUBRIC_ID
    assert rubric_id_for_role(MATERIALS_REVIEWER_ROLE) == MATERIALS_LEADING_JOURNALS_RUBRIC_ID
    assert (
        rubric_id_for_role(QUANT_FINANCE_REVIEWER_ROLE) == QUANT_FINANCE_LEADING_JOURNALS_RUBRIC_ID
    )


def test_review_validation_requires_integer_scores_and_role_specific_views() -> None:
    review = _review()
    assert (
        validate_review_record(
            review,
            expected_role=CS_TOP_TIER_REVIEWER_ROLE,
            expected_paper_id="20260804-ai-llm-review-test",
        )
        == []
    )

    review["scores"]["overall"] = 6.5
    del review["recommendations"][CAS_ZONE_1_JOURNAL_VIEW]
    errors = validate_review_record(review, expected_role=CS_TOP_TIER_REVIEWER_ROLE)
    assert "scores.overall must be an integer from 1 to 10" in errors
    assert any(
        error.startswith(f"recommendations.{CAS_ZONE_1_JOURNAL_VIEW}.decision") for error in errors
    )


def test_review_validation_rejects_unknown_role_and_priority() -> None:
    review = _review()
    review["review_metadata"]["reviewer_role"] = "generic"
    review["change_requests"][0]["priority"] = "urgent"

    errors = validate_review_record(review)

    assert any(error.startswith("review_metadata.reviewer_role must be one of") for error in errors)
    assert any(error.startswith("change_requests[0].priority must be one of") for error in errors)


def test_math_review_requires_four_journal_rubric_id() -> None:
    review = _review(role=MATHEMATICS_REVIEWER_ROLE)
    review["review_metadata"]["rubric_id"] = CS_TOP_TIER_RUBRIC_ID

    errors = validate_review_record(review, expected_role=MATHEMATICS_REVIEWER_ROLE)

    assert f"review_metadata.rubric_id must be {MATH_FOUR_JOURNALS_RUBRIC_ID}" in errors


def test_math_review_forbids_conference_view() -> None:
    review = _review(role=MATHEMATICS_REVIEWER_ROLE)
    review["recommendations"][TOP_CONFERENCE_VIEW] = {
        "seven_point": {
            "decision": "reject",
            "confidence": "high",
            "rationale": "This view must not be present in a math review.",
        }
    }

    errors = validate_review_record(review, expected_role=MATHEMATICS_REVIEWER_ROLE)

    assert any("is forbidden for math reviews" in error for error in errors)


def test_materials_review_requires_its_domain_view() -> None:
    review = _review(role=MATERIALS_REVIEWER_ROLE)

    assert (
        validate_review_record(
            review,
            expected_role=MATERIALS_REVIEWER_ROLE,
            expected_paper_id="20260804-ai-llm-review-test",
        )
        == []
    )

    del review["recommendations"][LEADING_MATERIALS_JOURNALS_VIEW]
    errors = validate_review_record(review, expected_role=MATERIALS_REVIEWER_ROLE)
    assert any(
        error.startswith(f"recommendations.{LEADING_MATERIALS_JOURNALS_VIEW}.decision")
        for error in errors
    )


def test_quant_finance_review_requires_its_domain_view() -> None:
    review = _review(role=QUANT_FINANCE_REVIEWER_ROLE)

    assert (
        validate_review_record(
            review,
            expected_role=QUANT_FINANCE_REVIEWER_ROLE,
            expected_paper_id="20260804-ai-llm-review-test",
        )
        == []
    )

    del review["recommendations"][LEADING_QUANT_FINANCE_JOURNALS_VIEW]
    errors = validate_review_record(review, expected_role=QUANT_FINANCE_REVIEWER_ROLE)
    assert any(
        error.startswith(f"recommendations.{LEADING_QUANT_FINANCE_JOURNALS_VIEW}.decision")
        for error in errors
    )


def test_verified_cas_zone_1_target_requires_classification_provenance() -> None:
    review = _review()
    review["review_metadata"]["cas_zone_1_basis"]["mode"] = "verified_target"

    errors = validate_review_record(review, expected_role=CS_TOP_TIER_REVIEWER_ROLE)

    for key in ("target_journal", "classification_source", "classification_checked_at"):
        assert any(f"cas_zone_1_basis.{key}" in error for error in errors)


def test_full_ara_recommendation_ordering_is_supported() -> None:
    assert decision_meets_threshold("weak_accept", "weak_accept", "conference")
    assert decision_meets_threshold("accept", "weak_accept", "conference")
    assert not decision_meets_threshold("borderline", "weak_accept", "conference")
    assert decision_meets_threshold("minor_revision", "minor_revision", "journal")
    assert not decision_meets_threshold("reject_and_resubmit", "minor_revision", "journal")
    assert decision_meets_standard_threshold(
        "minor_revision",
        "minor_revision",
        CAS_ZONE_1_JOURNAL_VIEW,
        venue_type="conference",
    )
    assert not decision_meets_standard_threshold(
        "major_revision",
        "minor_revision",
        CAS_ZONE_1_JOURNAL_VIEW,
        venue_type="conference",
    )


def test_skill_validator_uses_registry_domain_without_scoring(tmp_path: Path) -> None:
    paper_id = "20260804-math-number-review-test"
    manuscript = tmp_path / "papers" / paper_id / "manuscript"
    manuscript.mkdir(parents=True)
    main_tex = manuscript / "main.tex"
    main_pdf = manuscript / "main.pdf"
    main_tex.write_text("\\documentclass{article}\n", encoding="utf-8")
    main_pdf.write_bytes(b"%PDF-1.4 validator fixture")
    snapshot = manuscript_snapshot_sha256(manuscript, main_pdf)
    paper_registry = tmp_path / "registry" / "papers"
    paper_registry.mkdir(parents=True)
    (paper_registry / f"{paper_id}.yaml").write_text(
        f"""paper_id: {paper_id}
created_at: 2026-08-04
domain: math
subdomain: number
manuscript_dir: papers/{paper_id}/manuscript
latest_source: papers/{paper_id}/manuscript/main.tex
latest_pdf: papers/{paper_id}/manuscript/main.pdf
""",
        encoding="utf-8",
    )
    review_path = _write_panel(
        tmp_path,
        paper_id=paper_id,
        role="math",
        snapshot=snapshot,
        main_tex_sha256=sha256_file(main_tex),
    )

    result = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--paper-id",
            paper_id,
            "--review",
            str(review_path),
            "--root",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert payload["valid"] is True
    assert payload["expected_reviewer_role"] == "math"
    assert payload["rubric_id"] == MATH_FOUR_JOURNALS_RUBRIC_ID
    assert payload["overall"] == 5
    assert payload["high_standard_view"] == FOUR_TOP_MATH_JOURNALS_VIEW
    assert payload["high_standard_decision"] == "reject"
    assert payload["cas_zone_1_decision"] == "reject_and_resubmit"

    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["review_metadata"]["manuscript_snapshot_sha256_before"] = "c" * 64
    review_path.write_text(json.dumps(review), encoding="utf-8")
    stale = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--paper-id",
            paper_id,
            "--review",
            str(review_path),
            "--root",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    stale_payload = json.loads(stale.stdout)
    assert stale.returncode == 1
    assert any("canonical current snapshot" in error for error in stale_payload["errors"])


def test_skill_validator_accepts_individual_v2_source_record(tmp_path: Path) -> None:
    paper_id = "20260804-math-source-review-test"
    manuscript = tmp_path / "papers" / paper_id / "manuscript"
    manuscript.mkdir(parents=True)
    main_tex = manuscript / "main.tex"
    main_pdf = manuscript / "main.pdf"
    main_tex.write_text("\\documentclass{article}\n", encoding="utf-8")
    main_pdf.write_bytes(b"%PDF-1.4 source validator fixture")
    snapshot = manuscript_snapshot_sha256(manuscript, main_pdf)
    registry = tmp_path / "registry" / "papers"
    registry.mkdir(parents=True)
    (registry / f"{paper_id}.yaml").write_text(
        f"""paper_id: {paper_id}
created_at: 2026-08-04
domain: math
subdomain: number
manuscript_dir: papers/{paper_id}/manuscript
latest_source: papers/{paper_id}/manuscript/main.tex
latest_pdf: papers/{paper_id}/manuscript/main.pdf
""",
        encoding="utf-8",
    )
    review = _review(paper_id=paper_id, role=MATHEMATICS_REVIEWER_ROLE)
    review["review_metadata"].update(
        {
            "main_tex_sha256": sha256_file(main_tex),
            "manuscript_snapshot_sha256_before": snapshot,
            "manuscript_snapshot_sha256_after": snapshot,
            "panel_reviewer_id": "reviewer-1",
            "independent_context": True,
            "prior_reviews_hidden": True,
        }
    )
    review_path = tmp_path / "reviews" / "fresh" / paper_id / "reviewer-1.json"
    review_path.parent.mkdir(parents=True)
    review_path.write_text(json.dumps(review), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--paper-id",
            paper_id,
            "--review",
            str(review_path),
            "--root",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["valid"] is True
    assert payload["schema_version"] == INDIVIDUAL_REVIEW_SCHEMA_VERSION
    assert payload["overall"] == 6


def test_claude_reviewer_uses_packy_config_and_hides_peer_review(tmp_path: Path) -> None:
    paper_id = "20260804-ai-llm-claude-test"
    manuscript = tmp_path / "papers" / paper_id / "manuscript"
    manuscript.mkdir(parents=True)
    main_tex = manuscript / "main.tex"
    main_pdf = manuscript / "main.pdf"
    main_tex.write_text("\\documentclass{article}\nEvidence only.\n", encoding="utf-8")
    main_pdf.write_bytes(b"%PDF-1.4 claude reviewer fixture")
    snapshot = manuscript_snapshot_sha256(manuscript, main_pdf)
    registry = tmp_path / "registry" / "papers"
    registry.mkdir(parents=True)
    (registry / f"{paper_id}.yaml").write_text(
        f"""paper_id: {paper_id}
created_at: 2026-08-04
domain: ai
subdomain: llm
manuscript_dir: papers/{paper_id}/manuscript
latest_source: papers/{paper_id}/manuscript/main.tex
latest_pdf: papers/{paper_id}/manuscript/main.pdf
""",
        encoding="utf-8",
    )
    review_dir = tmp_path / "reviews" / "fresh" / paper_id
    review_dir.mkdir(parents=True)
    peer = _review(paper_id=paper_id, role=CS_TOP_TIER_REVIEWER_ROLE)
    peer["weaknesses"] = ["PEER-ONLY-SECRET"]
    peer["review_metadata"].update(
        {
            "provider": "openai-codex",
            "model": "test-codex",
            "main_tex_sha256": sha256_file(main_tex),
            "manuscript_snapshot_sha256_before": snapshot,
            "manuscript_snapshot_sha256_after": snapshot,
            "panel_reviewer_id": "reviewer-1",
            "independent_context": True,
            "prior_reviews_hidden": True,
        }
    )
    peer_path = review_dir / "reviewer-1.json"
    peer_path.write_text(json.dumps(peer), encoding="utf-8")

    settings = tmp_path / "claude-settings.json"
    settings.write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_BASE_URL": "https://www.packyapi.com",
                    "ANTHROPIC_AUTH_TOKEN": "test-packy-secret",
                }
            }
        ),
        encoding="utf-8",
    )
    fake_claude = tmp_path / "fake-claude"
    judgment = {
        "scores": {
            "clarity": 6,
            "soundness": 5,
            "significance": 5,
            "novelty": 4,
            "overall": 5,
        },
        "strengths": ["The question is explicit."],
        "weaknesses": ["The evidence is narrow."],
        "section_feedback": {"main": "Narrow the claim."},
        "required_changes": ["Narrow the claim."],
        "change_requests": [],
        "unresolved_blockers": ["The broad claim is unsupported."],
        "recommendations": {
            TOP_CONFERENCE_VIEW: {
                "seven_point": {
                    "decision": "reject",
                    "confidence": "high",
                    "rationale": "Evidence is insufficient.",
                }
            },
            CAS_ZONE_1_JOURNAL_VIEW: {
                "decision": "major_revision",
                "confidence": "high",
                "rationale": "Substantive repair is required.",
            },
        },
        "publishability_summary": {
            "text_ready": False,
            "scientific_ready": False,
            "blocking_reason": "The broad claim is unsupported.",
        },
    }
    fake_claude.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "prompt = sys.stdin.read()\n"
        "if 'PEER-ONLY-SECRET' in prompt:\n"
        "    raise SystemExit(9)\n"
        f"judgment = {judgment!r}\n"
        "print(json.dumps({'type': 'result', 'subtype': 'success', "
        "'is_error': False, 'structured_output': judgment, "
        "'modelUsage': {'claude-opus-5': {'canonicalModel': 'claude-opus-5'}}, "
        "'total_cost_usd': 0.01}))\n",
        encoding="utf-8",
    )
    fake_claude.chmod(0o755)

    result = subprocess.run(
        [
            sys.executable,
            str(CLAUDE_REVIEWER),
            "--paper-id",
            paper_id,
            "--peer-review",
            str(peer_path),
            "--root",
            str(tmp_path),
            "--settings",
            str(settings),
            "--claude-command",
            str(fake_claude),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    review = json.loads((review_dir / "reviewer-2.json").read_text(encoding="utf-8"))
    assert review["review_metadata"]["provider"] == "packy"
    assert review["review_metadata"]["model"] == "claude-opus-5"
    assert review["review_metadata"]["hidden_peer_review_sha256"] == sha256_file(peer_path)
    assert (
        validate_review_record(
            review,
            expected_role=CS_TOP_TIER_REVIEWER_ROLE,
            expected_paper_id=paper_id,
        )
        == []
    )


def test_panel_validator_rejects_nonconservative_score_and_decision(tmp_path: Path) -> None:
    paper_id = "20260804-ai-llm-panel-test"
    review_path = _write_panel(
        tmp_path,
        paper_id=paper_id,
        role=CS_TOP_TIER_REVIEWER_ROLE,
        snapshot="b" * 64,
        main_tex_sha256="a" * 64,
        ready=True,
    )
    panel = json.loads(review_path.read_text(encoding="utf-8"))
    panel["scores"]["overall"] = 7
    panel["recommendations"][CAS_ZONE_1_JOURNAL_VIEW]["decision"] = "accept"

    errors = validate_review_panel_files(
        panel,
        review_path=review_path,
        repo_root=tmp_path,
        expected_role=CS_TOP_TIER_REVIEWER_ROLE,
        expected_paper_id=paper_id,
    )

    assert "scores.overall must equal coordinatewise_minimum 6, got 7" in errors
    assert any("strictest_decision minor_revision" in error for error in errors)


def test_panel_validator_accepts_quant_finance_view(tmp_path: Path) -> None:
    paper_id = "20260821-quant-finance-panel-test"
    review_path = _write_panel(
        tmp_path,
        paper_id=paper_id,
        role=QUANT_FINANCE_REVIEWER_ROLE,
        snapshot="b" * 64,
        main_tex_sha256="a" * 64,
        ready=True,
    )
    panel = json.loads(review_path.read_text(encoding="utf-8"))

    assert (
        validate_review_panel_files(
            panel,
            review_path=review_path,
            repo_root=tmp_path,
            expected_role=QUANT_FINANCE_REVIEWER_ROLE,
            expected_paper_id=paper_id,
        )
        == []
    )


def test_panel_validator_requires_sources_beside_panel_result(tmp_path: Path) -> None:
    paper_id = "20260804-ai-llm-panel-location-test"
    review_path = _write_panel(
        tmp_path,
        paper_id=paper_id,
        role=CS_TOP_TIER_REVIEWER_ROLE,
        snapshot="b" * 64,
        main_tex_sha256="a" * 64,
        ready=True,
    )
    panel = json.loads(review_path.read_text(encoding="utf-8"))
    record = panel["review_metadata"]["review_panel"]["reviewer_records"][0]
    old_source = tmp_path / record["source"]
    other_dir = tmp_path / "reviews" / "fresh" / "other"
    other_dir.mkdir(parents=True)
    new_source = other_dir / old_source.name
    old_source.rename(new_source)
    record["source"] = new_source.relative_to(tmp_path).as_posix()

    errors = validate_review_panel_files(
        panel,
        review_path=review_path,
        repo_root=tmp_path,
        expected_role=CS_TOP_TIER_REVIEWER_ROLE,
        expected_paper_id=paper_id,
    )

    assert "reviewer record 1 must be stored beside the panel result" in errors


def test_panel_validator_keeps_historical_three_reviewer_records_readable(
    tmp_path: Path,
) -> None:
    paper_id = "20260804-ai-llm-legacy-panel-test"
    review_path = _write_panel(
        tmp_path,
        paper_id=paper_id,
        role=CS_TOP_TIER_REVIEWER_ROLE,
        snapshot="b" * 64,
        main_tex_sha256="a" * 64,
        ready=True,
    )
    panel = json.loads(review_path.read_text(encoding="utf-8"))
    review_dir = review_path.parent
    reviewer_three = _review(paper_id=paper_id, role=CS_TOP_TIER_REVIEWER_ROLE)
    reviewer_three["scores"]["overall"] = 5
    reviewer_three["recommendations"][CAS_ZONE_1_JOURNAL_VIEW]["decision"] = "major_revision"
    reviewer_three["unresolved_blockers"] = []
    reviewer_three["publishability_summary"] = {
        "text_ready": True,
        "scientific_ready": True,
        "blocking_reason": "",
    }
    reviewer_three["review_metadata"].update(
        {
            "panel_reviewer_id": "reviewer-3",
            "independent_context": True,
            "prior_reviews_hidden": True,
        }
    )
    reviewer_three_path = review_dir / "reviewer-3.json"
    reviewer_three_path.write_text(json.dumps(reviewer_three), encoding="utf-8")
    panel["schema_version"] = LEGACY_REVIEW_SCHEMA_VERSION
    panel_metadata = panel["review_metadata"]["review_panel"]
    panel_metadata.update(
        {
            "panel_size": 3,
            "score_aggregation": "coordinatewise_median",
            "decision_aggregation": "ordinal_median",
            "parallel_execution": True,
        }
    )
    panel_metadata["reviewer_records"].append(
        {
            "reviewer_id": "reviewer-3",
            "source": reviewer_three_path.relative_to(tmp_path).as_posix(),
            "sha256": sha256_file(reviewer_three_path),
        }
    )

    assert (
        validate_review_panel_files(
            panel,
            review_path=review_path,
            repo_root=tmp_path,
            expected_role=CS_TOP_TIER_REVIEWER_ROLE,
            expected_paper_id=paper_id,
        )
        == []
    )


def test_panel_validator_accepts_one_shared_bounded_lean_receipt(tmp_path: Path) -> None:
    paper_id = "20260804-math-lean-panel-test"
    snapshot = "b" * 64
    support_sha256 = "c" * 64
    review_path = _write_panel(
        tmp_path,
        paper_id=paper_id,
        role=MATHEMATICS_REVIEWER_ROLE,
        snapshot=snapshot,
        main_tex_sha256="a" * 64,
        ready=True,
    )
    project = tmp_path / "papers" / paper_id / "evidence" / "lean"
    project.mkdir(parents=True)
    audit_file = project / "GuardAxiomAudit.lean"
    audit_file.write_text("#print axioms guard\n", encoding="utf-8")
    (project / "lean-toolchain").write_text("leanprover/lean4:v4.26.0\n", encoding="utf-8")
    source_hashes = {
        path.relative_to(project).as_posix(): sha256_file(path)
        for path in (audit_file, project / "lean-toolchain")
    }
    receipt_path = tmp_path / "reviews" / "objective-audits" / paper_id / snapshot / "lean.json"
    receipt_path.parent.mkdir(parents=True)
    receipt = {
        "schema_version": LEAN_OBJECTIVE_AUDIT_SCHEMA_VERSION,
        "status": "PASS",
        "paper_id": paper_id,
        "manuscript_snapshot_sha256": snapshot,
        "support_package_sha256": support_sha256,
        "project": project.relative_to(tmp_path).as_posix(),
        "audit_file": audit_file.relative_to(project).as_posix(),
        "source_sha256": source_hashes,
        "resource_limits": {
            "threads": 2,
            "aggregate_rss_mib": 16384,
            "per_process_as_mib": 24576,
            "max_processes": 12,
            "timeout_seconds": 3600,
        },
        "preflight": {
            "total_memory_mib": 44000,
            "available_memory_mib": 40000,
            "reserved_headroom_mib": 11000,
            "required_available_memory_mib": 27384,
        },
        "commands": [
            {"command": ["lake", "build", "--quiet"], "return_code": 0},
            {
                "command": ["lake", "env", "lean", "GuardAxiomAudit.lean"],
                "return_code": 0,
            },
        ],
        "objective_only": True,
        "score_bearing": False,
        "execution_count": 1,
        "formal_validation_execution_count": 1,
        "cumulative_formal_validation_execution_count": 1,
    }
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    panel = json.loads(review_path.read_text(encoding="utf-8"))
    panel["review_metadata"]["review_panel"]["shared_objective_audits"] = [
        {
            "kind": LEAN_OBJECTIVE_AUDIT_KIND,
            "source": receipt_path.relative_to(tmp_path).as_posix(),
            "sha256": sha256_file(receipt_path),
            "status": "PASS",
            "manuscript_snapshot_sha256": snapshot,
            "support_package_sha256": support_sha256,
        }
    ]
    review_path.write_text(json.dumps(panel), encoding="utf-8")

    assert (
        validate_review_panel_files(
            panel,
            review_path=review_path,
            repo_root=tmp_path,
            expected_role=MATHEMATICS_REVIEWER_ROLE,
            expected_paper_id=paper_id,
        )
        == []
    )

    receipt["execution_count"] = 2
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    panel["review_metadata"]["review_panel"]["shared_objective_audits"][0]["sha256"] = sha256_file(
        receipt_path
    )
    errors = validate_review_panel_files(
        panel,
        review_path=review_path,
        repo_root=tmp_path,
        expected_role=MATHEMATICS_REVIEWER_ROLE,
        expected_paper_id=paper_id,
    )
    assert any("execution_count must equal 1" in error for error in errors)


def test_skill_aggregator_applies_conservative_dual_review_rules(tmp_path: Path) -> None:
    paper_id = "20260804-ai-llm-aggregate-test"
    registry = tmp_path / "registry" / "papers"
    registry.mkdir(parents=True)
    (registry / f"{paper_id}.yaml").write_text(
        f"""paper_id: {paper_id}
created_at: 2026-08-04
domain: ai
subdomain: llm
""",
        encoding="utf-8",
    )
    existing_panel = _write_panel(
        tmp_path,
        paper_id=paper_id,
        role=CS_TOP_TIER_REVIEWER_ROLE,
        snapshot="b" * 64,
        main_tex_sha256="a" * 64,
        ready=True,
    )
    existing_panel.unlink()

    result = subprocess.run(
        [
            sys.executable,
            str(AGGREGATOR),
            "--paper-id",
            paper_id,
            "--review-dir",
            str(existing_panel.parent),
            "--root",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    panel = json.loads(existing_panel.read_text(encoding="utf-8"))
    assert panel["scores"]["overall"] == 6
    assert panel["recommendations"][CAS_ZONE_1_JOURNAL_VIEW]["decision"] == "minor_revision"
    metadata = panel["review_metadata"]["review_panel"]
    assert metadata["panel_size"] == 2
    assert metadata["score_aggregation"] == "coordinatewise_minimum"
    assert metadata["decision_aggregation"] == "strictest_decision"
    assert [record["provider"] for record in metadata["reviewer_records"]] == [
        "openai-codex",
        "packy",
    ]


def test_skill_aggregator_supports_quant_finance(tmp_path: Path) -> None:
    paper_id = "20260821-quant-finance-aggregate-test"
    registry = tmp_path / "registry" / "papers"
    registry.mkdir(parents=True)
    (registry / f"{paper_id}.yaml").write_text(
        f"""paper_id: {paper_id}
created_at: 2026-08-21
domain: quant
subdomain: finance
""",
        encoding="utf-8",
    )
    panel_path = _write_panel(
        tmp_path,
        paper_id=paper_id,
        role=QUANT_FINANCE_REVIEWER_ROLE,
        snapshot="b" * 64,
        main_tex_sha256="a" * 64,
        ready=True,
    )
    panel_path.unlink()

    result = subprocess.run(
        [
            sys.executable,
            str(AGGREGATOR),
            "--paper-id",
            paper_id,
            "--review-dir",
            str(panel_path.parent),
            "--root",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    panel = json.loads(panel_path.read_text(encoding="utf-8"))
    assert (
        panel["recommendations"][LEADING_QUANT_FINANCE_JOURNALS_VIEW]["decision"]
        == "major_revision"
    )


def test_apply_review_registers_skill_judgment_and_uses_cas_gate(tmp_path: Path) -> None:
    paper_id = "20260804-ai-llm-review-test"
    manuscript = tmp_path / "papers" / paper_id / "manuscript"
    manuscript.mkdir(parents=True)
    main_tex = manuscript / "main.tex"
    main_pdf = manuscript / "main.pdf"
    main_tex.write_text("\\documentclass{article}\n", encoding="utf-8")
    main_pdf.write_bytes(b"%PDF-1.4 review fixture")
    snapshot = manuscript_snapshot_sha256(manuscript, main_pdf)

    registry = tmp_path / "registry" / "papers"
    registry.mkdir(parents=True)
    (tmp_path / "registry" / "settings.yaml").write_text(
        """schema_version: ara.paper_writing.registry.v1
quality_gate:
  minimum_score: 6.0
  maximum_revision_rounds: 3
  decision_standard: cas_zone_1_journal
  cas_zone_1_minimum_decision: minor_revision
""",
        encoding="utf-8",
    )
    (registry / f"{paper_id}.yaml").write_text(
        f"""paper_id: {paper_id}
title: Review application fixture
created_at: 2026-08-04
domain: ai
subdomain: llm
version: 1.0.0
manuscript_dir: papers/{paper_id}/manuscript
latest_source: papers/{paper_id}/manuscript/main.tex
latest_pdf: papers/{paper_id}/manuscript/main.pdf
writing_release:
  status: revision_required
  revision_rounds_completed: 2
""",
        encoding="utf-8",
    )

    review_path = _write_panel(
        tmp_path,
        paper_id=paper_id,
        role=CS_TOP_TIER_REVIEWER_ROLE,
        snapshot=snapshot,
        main_tex_sha256=sha256_file(main_tex),
        ready=True,
    )

    result = apply_review_record(
        paper_id,
        review=review_path,
        venue_type="journal",
        revision_rounds=None,
        root=tmp_path,
    )

    metadata = load_paper_metadata(paper_id, tmp_path)
    assert result["quality_gate"]["passed"] is True
    assert result["quality_gate"]["revision_rounds"] == 2
    assert metadata["ara_llm_self_review"]["score"] == 6
    assert metadata["ara_llm_self_review"]["high_standard_view"] == TOP_CONFERENCE_VIEW
    assert metadata["ara_llm_self_review"]["cas_zone_1_decision"] == "minor_revision"
    assert metadata["ara_llm_self_review"]["review_panel"]["panel_size"] == 2
    assert metadata["ara_llm_self_review"]["source"] == (f"reviews/fresh/{paper_id}/review.json")
    assert metadata["writing_release"]["status"] == "ready"
