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
    assert set(profiles["profiles"]) == {"ai_ml", "mathematics", "materials"}

    for profile in profiles["profiles"].values():
        components = profile["components"]
        assert set(components) == set(policy["roles"])
        assert len(components) <= policy["maximum_active_components"]

        entry = ROOT / profile["entry_path"]
        assert (entry / "SKILL.md").is_file()
        interface = _yaml(entry / "agents" / "openai.yaml")
        assert interface["policy"]["allow_implicit_invocation"] is False
        assert f"${profile['entry_skill']}" in interface["interface"]["default_prompt"]

        for source_name in components.values():
            source = lock["sources"][source_name]
            assert source["audit_status"].startswith("approved")
            assert re.fullmatch(r"[0-9a-f]{40}", source["commit"])
            assert (ROOT / source["installed_path"] / "SKILL.md").is_file()


def test_local_llm_score_gate_uses_role_specific_views_and_cas_zone_1() -> None:
    profiles = _yaml(ROOT / "skills" / "profiles.yaml")
    settings = _yaml(repository_root() / profiles["quality_gate"]["settings_path"])
    review_skill = ROOT / profiles["quality_gate"]["review_skill_path"]

    assert profiles["quality_gate"]["review_mode"] == "independent_dual_provider_panel"
    assert profiles["quality_gate"]["review_panel_size"] == 2
    assert profiles["quality_gate"]["parallel_execution"] is False
    assert profiles["quality_gate"]["independent_contexts"] == "required"
    assert profiles["quality_gate"]["prior_reviews_hidden"] == "required"
    assert profiles["quality_gate"]["execution_order"] == "frozen_codex_then_blind_claude"
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
        },
    }
    assert profiles["quality_gate"]["score_aggregation"] == "coordinatewise_minimum"
    assert profiles["quality_gate"]["decision_aggregation"] == "strictest_decision"
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
    }
    assert profiles["quality_gate"]["recommendation_views"] == {
        "ai": ["top_conference", "cas_zone_1_journal"],
        "cs": ["top_conference", "cas_zone_1_journal"],
        "se": ["top_conference", "cas_zone_1_journal"],
        "math": ["four_top_math_journals", "cas_zone_1_journal"],
        "materials": ["leading_materials_journals", "cas_zone_1_journal"],
    }
    assert profiles["quality_gate"]["gate_decision_standard"] == "cas_zone_1_journal"
    assert profiles["quality_gate"]["cas_zone_1_scope"] == "major_category"
    assert profiles["quality_gate"]["reviewer_roles"] == {
        "ai": "cs_top_tier",
        "cs": "cs_top_tier",
        "se": "cs_top_tier",
        "math": "math",
        "materials": "materials",
    }
    assert profiles["quality_gate"]["reviewer_rubric_ids"] == {
        "ai": "ara.revision-agent.cs-top-tier.v1",
        "cs": "ara.revision-agent.cs-top-tier.v1",
        "se": "ara.revision-agent.cs-top-tier.v1",
        "math": "ara.paper-writing.math-four-journals.v1",
        "materials": "openlabs.paper-writing.materials-leading-journals.v1",
    }
    rubric_text = (review_skill / "references" / "rubrics.md").read_text(encoding="utf-8")
    for journal in (
        "Annals of Mathematics",
        "Inventiones Mathematicae",
        "Journal of the American Mathematical Society",
        "Acta Mathematica",
    ):
        assert journal in rubric_text
    assert profiles["quality_gate"]["required_before_submission_consideration"] is True
    gate = settings[profiles["quality_gate"]["settings_key"]]
    assert gate["minimum_score"] == 5.0
    assert gate["review_panel_size"] == 2
    assert gate["score_aggregation"] == "coordinatewise_minimum"
    assert gate["decision_aggregation"] == "strictest_decision"
    assert gate["decision_standard"] == "cas_zone_1_journal"
    assert gate["cas_zone_1_scope"] == "major_category"
    assert gate["cas_zone_1_minimum_decision"] == "minor_revision"
