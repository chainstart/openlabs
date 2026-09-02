import re
from pathlib import Path

import yaml
from paper_writing.registry import repository_root

ROOT = Path(__file__).resolve().parents[1]


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_profiles_are_explicit_bounded_and_pinned() -> None:
    profiles = _yaml(ROOT / "skills" / "profiles.yaml")
    lock = _yaml(ROOT / "skills" / "lock.yaml")
    policy = profiles["selection_policy"]

    assert policy["invocation"] == "explicit"
    assert policy["maximum_active_components"] == 3
    assert set(profiles["profiles"]) == {
        "ai_ml",
        "mathematics",
        "materials",
        "physics",
        "quantitative_finance",
    }

    for profile in profiles["profiles"].values():
        components = profile["components"]
        assert set(components) == set(policy["roles"])
        assert len(components) <= policy["maximum_active_components"]

        entry = ROOT / profile["entry_path"]
        assert (entry / "SKILL.md").is_file()
        assert "../references/paper-identifiers.md" in (
            entry / "SKILL.md"
        ).read_text(encoding="utf-8")
        interface = _yaml(entry / "agents" / "openai.yaml")
        assert interface["policy"]["allow_implicit_invocation"] is False
        assert f"${profile['entry_skill']}" in interface["interface"]["default_prompt"]

        for source_name in components.values():
            source = lock["sources"][source_name]
            assert source["audit_status"].startswith("approved")
            assert re.fullmatch(r"[0-9a-f]{40}", source["commit"])
            assert (ROOT / source["installed_path"] / "SKILL.md").is_file()

    assert (ROOT / "skills" / "references" / "paper-identifiers.md").is_file()


def test_local_llm_score_gate_uses_role_specific_views_and_cas_zone_1() -> None:
    profiles = _yaml(ROOT / "skills" / "profiles.yaml")
    settings = _yaml(repository_root() / profiles["quality_gate"]["settings_path"])
    review_skill = ROOT / profiles["quality_gate"]["review_skill_path"]

    assert profiles["quality_gate"]["review_mode"] == "configured_independent_panel"
    assert profiles["quality_gate"]["require_target_journal_after_basic_draft"] is True
    assert profiles["quality_gate"]["target_journal_classification_system"] == {
        "math": ["2026 XinRui Mathematics"],
        "ai": [
            "2026 XinRui Mathematics",
            "2026 XinRui Medicine",
            "2026 XinRui Computer Science",
        ],
        "cs": ["2026 XinRui Computer Science", "2026 XinRui Medicine"],
        "se": ["2026 XinRui Computer Science", "2026 XinRui Medicine"],
        "physics": ["2026 XinRui Physics and Astronomy"],
    }
    assert profiles["quality_gate"]["allowed_target_journal_tiers"] == [1, 2]
    assert profiles["quality_gate"]["require_no_mandatory_author_fee"] is True
    assert profiles["quality_gate"]["require_canonical_target_journal_format"] is True
    assert profiles["quality_gate"]["zenodo_public_identifier"] == "display_id"
    assert profiles["quality_gate"]["support_publication_settings_key"] == (
        "support_publication"
    )
    assert profiles["quality_gate"]["support_publication_default_license_key"] == (
        "default_license"
    )
    assert profiles["quality_gate"]["support_release_after_ready"] == "automatic"
    assert profiles["quality_gate"]["support_release_uses_standing_authorization"] is True
    assert profiles["quality_gate"]["support_check_command"] == (
        "python -m paper_writing support-check --paper-id <paper_id>"
    )
    assert profiles["quality_gate"]["support_review_gate"] == (
        "prepared_version_doi_and_manuscript_citation"
    )
    assert profiles["quality_gate"]["support_release_gate"] == (
        "prepared_version_and_reviewed_package_binding"
    )
    assert profiles["quality_gate"]["support_handoff_gate"] == (
        "published_version_and_reviewed_package_binding"
    )
    assert profiles["quality_gate"]["manuscript_style_check"] == "required"
    assert profiles["quality_gate"]["manuscript_style_command"] == (
        "python -m paper_writing style-check --paper-id <paper_id>"
    )
    assert profiles["quality_gate"]["require_validated_independent_review"] is True
    assert profiles["quality_gate"]["require_ai_use_declaration"] is True
    assert profiles["quality_gate"]["ai_workflow_disclosure_location"] == (
        "final_ai_use_declaration_only"
    )
    assert profiles["quality_gate"]["require_code_and_formalization_purpose_disclosure"] is True
    assert profiles["quality_gate"]["forbid_internal_audit_terms_and_paths"] is True
    assert profiles["quality_gate"]["scan_bibliography_workflow_notes"] is True
    assert profiles["quality_gate"]["review_panel_size"] == 1
    assert profiles["quality_gate"]["parallel_execution"] is False
    assert profiles["quality_gate"]["independent_contexts"] == "required"
    assert profiles["quality_gate"]["isolated_processes"] == "required"
    assert profiles["quality_gate"]["prior_reviews_hidden"] == "required"
    assert profiles["quality_gate"]["execution_order"] == (
        "frozen_codex_then_optional_blind_claude"
    )
    assert profiles["quality_gate"]["reviewers"] == {
        "reviewer-1": {
            "runtime": "codex",
            "provider": "openai-codex",
            "session": "fresh",
        },
        "reviewer-2": {
            "runtime": "claude-code",
            "provider": "packy",
            "model": "claude-opus-5",
            "session": "fresh",
            "optional": True,
            "enabled_when_panel_size": 2,
        },
    }
    assert profiles["quality_gate"]["score_aggregation"] == "coordinatewise_median"
    assert profiles["quality_gate"]["decision_aggregation"] == "ordinal_median"
    assert profiles["quality_gate"]["optional_dual_provider_contract"] == {
        "review_panel_size": 2,
        "score_aggregation": "coordinatewise_minimum",
        "decision_aggregation": "strictest_decision",
    }
    assert profiles["quality_gate"]["review_skill"] == "openlabs-paper-review"
    assert (review_skill / "SKILL.md").is_file()
    assert (review_skill / "references" / "rubrics.md").is_file()
    assert (review_skill / "references" / "review-schema.md").is_file()
    assert (review_skill / "scripts" / "validate_review.py").is_file()
    assert profiles["quality_gate"]["score_field"] == "scores.overall"
    assert profiles["quality_gate"]["score_type"] == "integer"
    assert profiles["quality_gate"]["score_range"] == [1, 10]
    assert profiles["quality_gate"]["require_dual_simulated_decisions"] is True
    assert profiles["quality_gate"]["score_standard"] == {
        "ai": "top_conference",
        "cs": "top_conference",
        "se": "top_conference",
        "math": "four_top_math_journals",
        "materials": "leading_materials_journals",
        "physics": "physics_explicit_highest_tier_venues",
        "quant": "leading_quant_finance_journals",
    }
    assert profiles["quality_gate"]["recommendation_views"] == {
        "ai": ["top_conference", "cas_zone_1_journal"],
        "cs": ["top_conference", "cas_zone_1_journal"],
        "se": ["top_conference", "cas_zone_1_journal"],
        "math": ["four_top_math_journals", "cas_zone_1_journal"],
        "materials": ["leading_materials_journals", "cas_zone_1_journal"],
        "physics": ["leading_physics_journals", "cas_zone_1_journal"],
        "quant": ["leading_quant_finance_journals", "cas_zone_1_journal"],
    }
    assert profiles["quality_gate"]["gate_decision_standard"] == "cas_zone_1_journal"
    assert profiles["quality_gate"]["cas_zone_1_scope"] == "major_category"
    assert profiles["quality_gate"]["reviewer_roles"] == {
        "ai": "cs_top_tier",
        "cs": "cs_top_tier",
        "se": "cs_top_tier",
        "math": "math",
        "materials": "materials",
        "physics": "physics",
        "quant": "quant_finance",
    }
    assert profiles["quality_gate"]["reviewer_rubric_ids"] == {
        "ai": "ara.revision-agent.cs-top-tier.v1",
        "cs": "ara.revision-agent.cs-top-tier.v1",
        "se": "ara.revision-agent.cs-top-tier.v1",
        "math": "ara.paper-writing.math-four-journals.v1",
        "materials": "openlabs.paper-writing.materials-leading-journals.v1",
        "physics": "openlabs.paper-writing.physics-explicit-highest-tier-venues.v1",
        "quant": "openlabs.paper-writing.quant-finance-leading-journals.v1",
    }
    assert profiles["quality_gate"]["physics_highest_tier_benchmark"] == {
        "id": "openlabs.physics-highest-tier-original-research.v1",
        "venues": [
            "physical_review_letters",
            "physical_review_x",
            "nature_physics",
        ],
        "criteria_source": (
            "skills/openlabs-paper-review/references/"
            "physics-highest-tier-venues.md"
        ),
    }
    assert (
        review_skill / "references" / "physics-highest-tier-venues.md"
    ).is_file()
    rubric_text = (review_skill / "references" / "rubrics.md").read_text(encoding="utf-8")
    for journal in (
        "Annals of Mathematics",
        "Inventiones Mathematicae",
        "Journal of the American Mathematical Society",
        "Acta Mathematica",
    ):
        assert journal in rubric_text
    for journal in ("Physical Review Letters", "Physical Review X", "Nature Physics"):
        assert journal in rubric_text
    assert profiles["quality_gate"]["required_before_submission_consideration"] is True
    assert profiles["quality_gate"]["submission_target"] == (
        "ready_without_additional_author_intervention"
    )
    assert profiles["quality_gate"]["default_author_confirmation"] == "confirmed"
    assert profiles["quality_gate"]["forbid_unconfirmed_language_in_submission_files"] is True
    assert profiles["quality_gate"]["external_human_action_file"] == (
        "production/human_action_checklist.md"
    )
    gate = settings[profiles["quality_gate"]["settings_key"]]
    assert gate["minimum_score"] == 5.0
    assert gate["review_panel_size"] == 1
    assert gate["score_aggregation"] == "coordinatewise_median"
    assert gate["decision_aggregation"] == "ordinal_median"
    assert gate["decision_standard"] == "cas_zone_1_journal"
    assert gate["cas_zone_1_scope"] == "major_category"
    assert gate["cas_zone_1_minimum_decision"] == "minor_revision"
    assert gate["require_manuscript_style_check"] is True
    assert gate["require_ai_use_declaration"] is True
    assert gate["require_validated_independent_review"] is True
    target_policy = settings["journal_target_policy"]
    assert target_policy["required_after_basic_draft"] is True
    assert target_policy["effective_from"] == "2026-08-27"
    assert target_policy["classification_system"]["physics"] == [
        "2026 XinRui Physics and Astronomy"
    ]
    assert target_policy["allowed_tiers"] == [1, 2]
    assert target_policy["require_no_mandatory_author_fee"] is True
    assert target_policy["require_canonical_venue_format"] is True
    assert settings["support_publication"]["public_archive_identifier"] == "display_id"
    assert settings["support_publication"]["public_archive_root_identifier"] == "display_id"
    assert settings["support_publication"]["default_license"] == "cc-by-4.0"
    assert settings["support_publication"]["zenodo_environment"] == "production"
    assert settings["support_publication"]["release_after_ready"] == "automatic"
    assert settings["support_publication"]["standing_production_release_authorization"] is True
    assert settings["support_publication"]["gates"] == {
        "before_review": {
            "minimum_status": "draft",
            "require_version_doi": True,
            "require_manuscript_citation": True,
        },
        "before_support_release": {
            "minimum_status": "draft",
            "require_version_doi": True,
            "require_manuscript_citation": True,
            "require_quality_gate_package_binding": True,
        },
        "before_handoff": {
            "minimum_status": "published",
            "require_version_doi": True,
            "require_manuscript_citation": True,
            "require_quality_gate_package_binding": True,
        },
    }
    assert settings["support_publication"]["not_required"] == {
        "require_reason": True
    }
    assert settings["submission_readiness"]["target_state"] == (
        "ready_without_additional_author_intervention"
    )
    assert settings["submission_readiness"]["default_author_confirmation"] == "confirmed"
    assert settings["submission_readiness"]["human_action_checklist"] == {
        "relative_path": "production/human_action_checklist.md",
        "must_be_outside_submission_package": True,
    }
    assert settings["lean_audit_policy"] == {
        "unchanged_inputs": "reuse_verified_pass_without_lean_execution",
        "support_hash_change_alone_invalidates_lean": False,
        "local_source_change": "incremental_build_then_axiom_audit",
        "large_change": "full_clean_build_then_axiom_audit",
        "full_build_triggers": [
            "toolchain",
            "dependency_lock",
            "lake_configuration",
            "foundational_interface",
        ],
    }
