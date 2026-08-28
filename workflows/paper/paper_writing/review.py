"""Shared guardrails for skill-authored paper review records.

The reviewing skill makes every scientific and editorial judgment.  This
module only defines stable domain routing, recommendation vocabularies, and
structural validation so deterministic code cannot manufacture a score.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

CS_TOP_TIER_REVIEWER_ROLE = "cs_top_tier"
MATHEMATICS_REVIEWER_ROLE = "math"
MATERIALS_REVIEWER_ROLE = "materials"
PHYSICS_REVIEWER_ROLE = "physics"
QUANT_FINANCE_REVIEWER_ROLE = "quant_finance"

INDIVIDUAL_REVIEW_SCHEMA_VERSION = "ara.paper_writing.review.v2"
LEGACY_REVIEW_SCHEMA_VERSION = "ara.paper_writing.review.v3"
LEGACY_REVIEW_PANEL_SIZE = 3
LEGACY_REVIEW_SCORE_AGGREGATION = "coordinatewise_median"
LEGACY_REVIEW_DECISION_AGGREGATION = "ordinal_median"
REVIEW_SCHEMA_VERSION = "openlabs.paper_writing.review.v1"
REVIEW_PANEL_SIZE = 2
REVIEW_SCORE_AGGREGATION = "coordinatewise_minimum"
REVIEW_DECISION_AGGREGATION = "strictest_decision"
SINGLE_REVIEW_SCHEMA_VERSION = "openlabs.paper_writing.review.single.v1"
SINGLE_REVIEW_PANEL_SIZE = 1
SINGLE_REVIEW_SCORE_AGGREGATION = "coordinatewise_median"
SINGLE_REVIEW_DECISION_AGGREGATION = "ordinal_median"
REVIEWER_PROVIDER_CONTRACTS = {
    "reviewer-1": {"provider": "openai-codex", "model": None},
    "reviewer-2": {"provider": "packy", "model": "claude-opus-5"},
}
LEAN_OBJECTIVE_AUDIT_SCHEMA_VERSION = "ara.paper_writing.lean_objective_audit.v1"
LEAN_OBJECTIVE_AUDIT_KIND = "lean_mathlib"
CS_TOP_TIER_RUBRIC_ID = "ara.revision-agent.cs-top-tier.v1"
MATH_FOUR_JOURNALS_RUBRIC_ID = "ara.paper-writing.math-four-journals.v1"
MATERIALS_LEADING_JOURNALS_RUBRIC_ID = "openlabs.paper-writing.materials-leading-journals.v1"
PHYSICS_LEADING_JOURNALS_RUBRIC_ID = "openlabs.paper-writing.physics-leading-journals.v1"
QUANT_FINANCE_LEADING_JOURNALS_RUBRIC_ID = (
    "openlabs.paper-writing.quant-finance-leading-journals.v1"
)
RECOMMENDATION_SCHEMA_VERSION = "ara.review_recommendations.v2"

TOP_CONFERENCE_VIEW = "top_conference"
FOUR_TOP_MATH_JOURNALS_VIEW = "four_top_math_journals"
LEADING_MATERIALS_JOURNALS_VIEW = "leading_materials_journals"
LEADING_PHYSICS_JOURNALS_VIEW = "leading_physics_journals"
LEADING_QUANT_FINANCE_JOURNALS_VIEW = "leading_quant_finance_journals"
CAS_ZONE_1_JOURNAL_VIEW = "cas_zone_1_journal"
CAS_ZONE_1_SCOPE = "major_category"
CAS_ZONE_1_BASIS_MODES = ("generic_standard", "verified_target")

RUBRIC_IDS_BY_ROLE = {
    CS_TOP_TIER_REVIEWER_ROLE: CS_TOP_TIER_RUBRIC_ID,
    MATHEMATICS_REVIEWER_ROLE: MATH_FOUR_JOURNALS_RUBRIC_ID,
    MATERIALS_REVIEWER_ROLE: MATERIALS_LEADING_JOURNALS_RUBRIC_ID,
    PHYSICS_REVIEWER_ROLE: PHYSICS_LEADING_JOURNALS_RUBRIC_ID,
    QUANT_FINANCE_REVIEWER_ROLE: QUANT_FINANCE_LEADING_JOURNALS_RUBRIC_ID,
}

# Match ARA RevisionAgent ordering: most favorable to least favorable.
CONFERENCE_DECISIONS = (
    "strong_accept",
    "accept",
    "weak_accept",
    "borderline",
    "weak_reject",
    "reject",
    "strong_reject",
)
JOURNAL_DECISIONS = (
    "accept",
    "minor_revision",
    "major_revision",
    "reject_and_resubmit",
    "reject",
)
RECOMMENDATION_CONFIDENCE_LEVELS = ("high", "medium", "low")
CHANGE_PRIORITIES = ("high", "medium", "low")

_CS_DOMAINS = {
    "ai",
    "artificial_intelligence",
    "computer",
    "computer_science",
    "cs",
    "machine_learning",
    "ml",
    "se",
    "software_engineering",
}
_MATH_DOMAINS = {"math", "mathematics"}
_MATERIALS_DOMAINS = {"material", "materials", "materials_science"}
_PHYSICS_DOMAINS = {
    "physics",
    "theoretical_physics",
    "high_energy_physics",
    "cosmology",
}
_QUANT_FINANCE_DOMAINS = {"finance", "quant", "quant_finance", "quantitative_finance"}
_SHA256 = re.compile(r"[0-9a-f]{64}")


def review_safe_registry(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Return registry metadata with every repository review projection removed."""

    safe = deepcopy(dict(metadata))
    for field in ("ara_llm_self_review", "writing_release", "review_file"):
        safe.pop(field, None)
    support = safe.get("support")
    if isinstance(support, dict):
        publication = support.get("publication")
        if isinstance(publication, dict):
            publication.pop("release_binding", None)
    return safe


def _normalized_token(value: Any) -> str:
    return re.sub(r"[-\s]+", "_", str(value or "").strip().lower())


def reviewer_role_for_domain(domain: Any) -> str:
    """Resolve the repository domain to its configured reviewer role.

    Unknown domains fail closed so a manuscript cannot silently receive the
    computer-science rubric merely because no route was configured.
    """

    token = _normalized_token(domain)
    if token in _CS_DOMAINS:
        return CS_TOP_TIER_REVIEWER_ROLE
    if token in _MATH_DOMAINS:
        return MATHEMATICS_REVIEWER_ROLE
    if token in _MATERIALS_DOMAINS:
        return MATERIALS_REVIEWER_ROLE
    if token in _PHYSICS_DOMAINS:
        return PHYSICS_REVIEWER_ROLE
    if token in _QUANT_FINANCE_DOMAINS:
        return QUANT_FINANCE_REVIEWER_ROLE
    raise ValueError(f"No paper-review rubric is configured for domain: {domain!r}")


def rubric_id_for_role(reviewer_role: str) -> str:
    """Return the explicit rubric bound to a validated reviewer role."""

    try:
        return RUBRIC_IDS_BY_ROLE[reviewer_role]
    except KeyError as exc:
        raise ValueError(
            f"No paper-review rubric is configured for role: {reviewer_role!r}"
        ) from exc


def decisions_for_venue(venue_type: str) -> tuple[str, ...]:
    if venue_type == "conference":
        return CONFERENCE_DECISIONS
    if venue_type == "journal":
        return JOURNAL_DECISIONS
    raise ValueError("venue_type must be conference or journal")


def decisions_for_standard(
    decision_standard: str,
    *,
    venue_type: str | None = None,
) -> tuple[str, ...]:
    """Return the vocabulary for a configured quality-gate decision standard.

    ``conference`` and ``journal`` preserve records created under the original
    venue-dependent gate.  The current repository gate uses the independent
    CAS Zone 1 journal view for every supported domain.
    """

    if decision_standard == CAS_ZONE_1_JOURNAL_VIEW:
        return JOURNAL_DECISIONS
    if decision_standard in {"conference", "journal"}:
        return decisions_for_venue(decision_standard)
    if not decision_standard and venue_type is not None:
        return decisions_for_venue(venue_type)
    raise ValueError(f"Unknown quality-gate decision standard: {decision_standard!r}")


def decision_meets_threshold(decision: str, minimum: str, venue_type: str) -> bool:
    """Return whether a decision is at least as favorable as the threshold."""

    decisions = decisions_for_venue(venue_type)
    try:
        return decisions.index(decision) <= decisions.index(minimum)
    except ValueError:
        return False


def decision_meets_standard_threshold(
    decision: str,
    minimum: str,
    decision_standard: str,
    *,
    venue_type: str | None = None,
) -> bool:
    """Return whether a decision clears a named review-standard threshold."""

    try:
        decisions = decisions_for_standard(decision_standard, venue_type=venue_type)
        return decisions.index(decision) <= decisions.index(minimum)
    except (ValueError, TypeError):
        return False


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _median(values: list[int]) -> int:
    """Return the middle value for the required odd review panel."""

    return sorted(values)[len(values) // 2]


def _decision_median(values: list[str], ordering: tuple[str, ...]) -> str:
    """Return the ordinal middle decision without making an editorial judgment."""

    indexes = sorted(ordering.index(value) for value in values)
    return ordering[indexes[len(indexes) // 2]]


def _panel_contract(schema_version: Any) -> tuple[int, str, str, bool] | None:
    """Return the immutable contract attached to a panel schema."""

    if schema_version == REVIEW_SCHEMA_VERSION:
        return (
            REVIEW_PANEL_SIZE,
            REVIEW_SCORE_AGGREGATION,
            REVIEW_DECISION_AGGREGATION,
            False,
        )
    if schema_version == SINGLE_REVIEW_SCHEMA_VERSION:
        return (
            SINGLE_REVIEW_PANEL_SIZE,
            SINGLE_REVIEW_SCORE_AGGREGATION,
            SINGLE_REVIEW_DECISION_AGGREGATION,
            False,
        )
    if schema_version == LEGACY_REVIEW_SCHEMA_VERSION:
        return (
            LEGACY_REVIEW_PANEL_SIZE,
            LEGACY_REVIEW_SCORE_AGGREGATION,
            LEGACY_REVIEW_DECISION_AGGREGATION,
            True,
        )
    return None


def _aggregate_score(values: list[int], aggregation: str) -> int:
    if aggregation == REVIEW_SCORE_AGGREGATION:
        return min(values)
    if aggregation == LEGACY_REVIEW_SCORE_AGGREGATION:
        return _median(values)
    raise ValueError(f"Unknown review score aggregation: {aggregation!r}")


def _aggregate_decision(values: list[str], ordering: tuple[str, ...], aggregation: str) -> str:
    if aggregation == REVIEW_DECISION_AGGREGATION:
        return max(values, key=ordering.index)
    if aggregation == LEGACY_REVIEW_DECISION_AGGREGATION:
        return _decision_median(values, ordering)
    raise ValueError(f"Unknown review decision aggregation: {aggregation!r}")


def _validate_text_list(
    review: Mapping[str, Any],
    key: str,
    errors: list[str],
    *,
    require_nonempty: bool = False,
) -> None:
    value = review.get(key)
    if not isinstance(value, list):
        errors.append(f"{key} must be an array")
        return
    if require_nonempty and not value:
        errors.append(f"{key} must not be empty")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        errors.append(f"{key} must contain only non-empty strings")


def _validate_recommendation_entry(
    entry: Mapping[str, Any],
    *,
    path: str,
    decisions: tuple[str, ...],
    errors: list[str],
) -> None:
    decision = entry.get("decision")
    if decision not in decisions:
        errors.append(f"{path}.decision must be one of: {', '.join(decisions)}")
    if entry.get("confidence") not in RECOMMENDATION_CONFIDENCE_LEVELS:
        errors.append(
            f"{path}.confidence must be one of: {', '.join(RECOMMENDATION_CONFIDENCE_LEVELS)}"
        )
    rationale = entry.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        errors.append(f"{path}.rationale must be a non-empty string")


def validate_review_record(
    payload: Any,
    *,
    expected_role: str | None = None,
    expected_paper_id: str | None = None,
) -> list[str]:
    """Validate a review record without judging or changing its scores."""

    if not isinstance(payload, Mapping):
        return ["review must be a JSON object"]
    review = payload
    errors: list[str] = []

    schema_version = review.get("schema_version")
    if schema_version not in (
        INDIVIDUAL_REVIEW_SCHEMA_VERSION,
        LEGACY_REVIEW_SCHEMA_VERSION,
        REVIEW_SCHEMA_VERSION,
        SINGLE_REVIEW_SCHEMA_VERSION,
    ):
        errors.append(
            "schema_version must be "
            f"{INDIVIDUAL_REVIEW_SCHEMA_VERSION} for an individual review or "
            f"{REVIEW_SCHEMA_VERSION} for a dual-provider panel result, "
            f"{SINGLE_REVIEW_SCHEMA_VERSION} for an explicitly configured "
            "single-reviewer result "
            f"({LEGACY_REVIEW_SCHEMA_VERSION} remains valid for historical panels)"
        )

    scores = _mapping(review.get("scores"))
    for key in ("clarity", "soundness", "significance", "novelty", "overall"):
        value = scores.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append(f"scores.{key} must be an integer from 1 to 10")
        elif not 1 <= value <= 10:
            errors.append(f"scores.{key} must be between 1 and 10")

    _validate_text_list(review, "strengths", errors, require_nonempty=True)
    _validate_text_list(review, "weaknesses", errors, require_nonempty=True)
    _validate_text_list(review, "required_changes", errors)
    _validate_text_list(review, "unresolved_blockers", errors)

    feedback = review.get("section_feedback")
    if not isinstance(feedback, Mapping):
        errors.append("section_feedback must be an object")
    elif any(
        not isinstance(key, str)
        or not key.strip()
        or not isinstance(value, str)
        or not value.strip()
        for key, value in feedback.items()
    ):
        errors.append("section_feedback must map section names to non-empty strings")

    requests = review.get("change_requests")
    if not isinstance(requests, list):
        errors.append("change_requests must be an array")
    else:
        for index, request in enumerate(requests):
            path = f"change_requests[{index}]"
            item = _mapping(request)
            if not item:
                errors.append(f"{path} must be an object")
                continue
            for key in ("request", "category", "priority", "rationale"):
                if not isinstance(item.get(key), str) or not str(item.get(key)).strip():
                    errors.append(f"{path}.{key} must be a non-empty string")
            if item.get("priority") not in CHANGE_PRIORITIES:
                errors.append(f"{path}.priority must be one of: {', '.join(CHANGE_PRIORITIES)}")
            targets = item.get("targets")
            if not isinstance(targets, list) or any(
                not isinstance(target, str) or not target.strip() for target in targets
            ):
                errors.append(f"{path}.targets must be an array of non-empty strings")
            if not isinstance(item.get("text_only"), bool):
                errors.append(f"{path}.text_only must be boolean")

    publishability = _mapping(review.get("publishability_summary"))
    for key in ("text_ready", "scientific_ready"):
        if not isinstance(publishability.get(key), bool):
            errors.append(f"publishability_summary.{key} must be boolean")
    if not isinstance(publishability.get("blocking_reason"), str):
        errors.append("publishability_summary.blocking_reason must be a string")
    elif (
        publishability.get("scientific_ready") is False
        and not publishability.get("blocking_reason", "").strip()
    ):
        errors.append(
            "publishability_summary.blocking_reason must explain why scientific_ready is false"
        )

    metadata = _mapping(review.get("review_metadata"))
    if metadata.get("score_kind") != "ara_llm_self_review":
        errors.append("review_metadata.score_kind must be ara_llm_self_review")
    if metadata.get("recommendation_schema_version") != RECOMMENDATION_SCHEMA_VERSION:
        errors.append(
            f"review_metadata.recommendation_schema_version must be {RECOMMENDATION_SCHEMA_VERSION}"
        )
    if metadata.get("not_external_peer_review") is not True:
        errors.append("review_metadata.not_external_peer_review must be true")
    if metadata.get("simulated_venue_decisions") is not True:
        errors.append("review_metadata.simulated_venue_decisions must be true")
    if metadata.get("review_only") is not True:
        errors.append("review_metadata.review_only must be true")
    if metadata.get("manuscript_unchanged") is not True:
        errors.append("review_metadata.manuscript_unchanged must be true")
    paper_id = metadata.get("paper_id")
    if not isinstance(paper_id, str) or not paper_id.strip():
        errors.append("review_metadata.paper_id must be a non-empty string")
    reviewer_role = metadata.get("reviewer_role")
    if reviewer_role not in RUBRIC_IDS_BY_ROLE:
        errors.append(
            f"review_metadata.reviewer_role must be one of: {', '.join(RUBRIC_IDS_BY_ROLE)}"
        )
    rubric_role = expected_role if expected_role in RUBRIC_IDS_BY_ROLE else reviewer_role
    expected_rubric_id = RUBRIC_IDS_BY_ROLE.get(rubric_role)
    if expected_rubric_id is None:
        if metadata.get("rubric_id") not in RUBRIC_IDS_BY_ROLE.values():
            errors.append(
                "review_metadata.rubric_id must be one of: "
                f"{', '.join(RUBRIC_IDS_BY_ROLE.values())}"
            )
    elif metadata.get("rubric_id") != expected_rubric_id:
        errors.append(f"review_metadata.rubric_id must be {expected_rubric_id}")
    if expected_role is not None and metadata.get("reviewer_role") != expected_role:
        errors.append(f"review_metadata.reviewer_role must be {expected_role}")
    if expected_paper_id is not None and metadata.get("paper_id") != expected_paper_id:
        errors.append(f"review_metadata.paper_id must be {expected_paper_id}")

    cas_basis = _mapping(metadata.get("cas_zone_1_basis"))
    if cas_basis.get("scope") != CAS_ZONE_1_SCOPE:
        errors.append(f"review_metadata.cas_zone_1_basis.scope must be {CAS_ZONE_1_SCOPE}")
    cas_basis_mode = cas_basis.get("mode")
    if cas_basis_mode not in CAS_ZONE_1_BASIS_MODES:
        errors.append(
            "review_metadata.cas_zone_1_basis.mode must be one of: "
            f"{', '.join(CAS_ZONE_1_BASIS_MODES)}"
        )
    if cas_basis_mode == "verified_target":
        for key in ("target_journal", "classification_source", "classification_checked_at"):
            value = cas_basis.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(
                    f"review_metadata.cas_zone_1_basis.{key} must be a non-empty string "
                    "for verified_target"
                )

    recommendation_role = expected_role if expected_role in RUBRIC_IDS_BY_ROLE else reviewer_role
    recommendations = _mapping(review.get("recommendations"))
    cas_zone_1 = _mapping(recommendations.get(CAS_ZONE_1_JOURNAL_VIEW))
    _validate_recommendation_entry(
        cas_zone_1,
        path=f"recommendations.{CAS_ZONE_1_JOURNAL_VIEW}",
        decisions=JOURNAL_DECISIONS,
        errors=errors,
    )
    if recommendation_role == CS_TOP_TIER_REVIEWER_ROLE:
        top_conference = _mapping(recommendations.get(TOP_CONFERENCE_VIEW))
        conference_seven = _mapping(top_conference.get("seven_point"))
        _validate_recommendation_entry(
            conference_seven,
            path=f"recommendations.{TOP_CONFERENCE_VIEW}.seven_point",
            decisions=CONFERENCE_DECISIONS,
            errors=errors,
        )
        if FOUR_TOP_MATH_JOURNALS_VIEW in recommendations:
            errors.append(
                f"recommendations.{FOUR_TOP_MATH_JOURNALS_VIEW} is only valid for math reviews"
            )
        if LEADING_MATERIALS_JOURNALS_VIEW in recommendations:
            errors.append(
                f"recommendations.{LEADING_MATERIALS_JOURNALS_VIEW} is only valid for materials reviews"
            )
        if LEADING_QUANT_FINANCE_JOURNALS_VIEW in recommendations:
            errors.append(
                f"recommendations.{LEADING_QUANT_FINANCE_JOURNALS_VIEW} is only valid for quant-finance reviews"
            )
        if LEADING_PHYSICS_JOURNALS_VIEW in recommendations:
            errors.append(
                f"recommendations.{LEADING_PHYSICS_JOURNALS_VIEW} is only valid for physics reviews"
            )
    elif recommendation_role == MATHEMATICS_REVIEWER_ROLE:
        four_journals = _mapping(recommendations.get(FOUR_TOP_MATH_JOURNALS_VIEW))
        _validate_recommendation_entry(
            four_journals,
            path=f"recommendations.{FOUR_TOP_MATH_JOURNALS_VIEW}",
            decisions=JOURNAL_DECISIONS,
            errors=errors,
        )
        for forbidden in (TOP_CONFERENCE_VIEW, "conference"):
            if forbidden in recommendations:
                errors.append(
                    f"recommendations.{forbidden} is forbidden for math reviews; "
                    "use four_top_math_journals"
                )
        if LEADING_MATERIALS_JOURNALS_VIEW in recommendations:
            errors.append(
                f"recommendations.{LEADING_MATERIALS_JOURNALS_VIEW} is forbidden for math reviews"
            )
        if LEADING_QUANT_FINANCE_JOURNALS_VIEW in recommendations:
            errors.append(
                f"recommendations.{LEADING_QUANT_FINANCE_JOURNALS_VIEW} is forbidden for math reviews"
            )
        if LEADING_PHYSICS_JOURNALS_VIEW in recommendations:
            errors.append(
                f"recommendations.{LEADING_PHYSICS_JOURNALS_VIEW} is forbidden for math reviews"
            )
    elif recommendation_role == MATERIALS_REVIEWER_ROLE:
        leading_materials = _mapping(recommendations.get(LEADING_MATERIALS_JOURNALS_VIEW))
        _validate_recommendation_entry(
            leading_materials,
            path=f"recommendations.{LEADING_MATERIALS_JOURNALS_VIEW}",
            decisions=JOURNAL_DECISIONS,
            errors=errors,
        )
        for forbidden in (
            TOP_CONFERENCE_VIEW,
            FOUR_TOP_MATH_JOURNALS_VIEW,
            LEADING_QUANT_FINANCE_JOURNALS_VIEW,
            LEADING_PHYSICS_JOURNALS_VIEW,
            "conference",
        ):
            if forbidden in recommendations:
                errors.append(
                    f"recommendations.{forbidden} is forbidden for materials reviews; "
                    "use leading_materials_journals"
                )
    elif recommendation_role == PHYSICS_REVIEWER_ROLE:
        leading_physics = _mapping(recommendations.get(LEADING_PHYSICS_JOURNALS_VIEW))
        _validate_recommendation_entry(
            leading_physics,
            path=f"recommendations.{LEADING_PHYSICS_JOURNALS_VIEW}",
            decisions=JOURNAL_DECISIONS,
            errors=errors,
        )
        for forbidden in (
            TOP_CONFERENCE_VIEW,
            FOUR_TOP_MATH_JOURNALS_VIEW,
            LEADING_MATERIALS_JOURNALS_VIEW,
            LEADING_QUANT_FINANCE_JOURNALS_VIEW,
            "conference",
        ):
            if forbidden in recommendations:
                errors.append(
                    f"recommendations.{forbidden} is forbidden for physics reviews; "
                    "use leading_physics_journals"
                )
    elif recommendation_role == QUANT_FINANCE_REVIEWER_ROLE:
        leading_quant = _mapping(recommendations.get(LEADING_QUANT_FINANCE_JOURNALS_VIEW))
        _validate_recommendation_entry(
            leading_quant,
            path=f"recommendations.{LEADING_QUANT_FINANCE_JOURNALS_VIEW}",
            decisions=JOURNAL_DECISIONS,
            errors=errors,
        )
        for forbidden in (
            TOP_CONFERENCE_VIEW,
            FOUR_TOP_MATH_JOURNALS_VIEW,
            LEADING_MATERIALS_JOURNALS_VIEW,
            LEADING_PHYSICS_JOURNALS_VIEW,
            "conference",
        ):
            if forbidden in recommendations:
                errors.append(
                    f"recommendations.{forbidden} is forbidden for quant-finance reviews; "
                    "use leading_quant_finance_journals"
                )
    for key in ("model", "reasoning_effort", "reviewed_at_utc"):
        if not isinstance(metadata.get(key), str) or not str(metadata.get(key)).strip():
            errors.append(f"review_metadata.{key} must be a non-empty string")
    main_sha256 = metadata.get("main_tex_sha256")
    if not isinstance(main_sha256, str) or _SHA256.fullmatch(main_sha256) is None:
        errors.append("review_metadata.main_tex_sha256 must be a lowercase SHA-256")
    snapshot_hashes: list[str] = []
    for key in ("manuscript_snapshot_sha256_before", "manuscript_snapshot_sha256_after"):
        value = metadata.get(key)
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            errors.append(f"review_metadata.{key} must be a lowercase SHA-256")
        else:
            snapshot_hashes.append(value)
    if len(snapshot_hashes) == 2 and snapshot_hashes[0] != snapshot_hashes[1]:
        errors.append("review_metadata before/after manuscript snapshot hashes must match")

    panel_contract = _panel_contract(schema_version)
    if panel_contract is not None:
        (
            expected_panel_size,
            expected_score_aggregation,
            expected_decision_aggregation,
            expected_parallel_execution,
        ) = panel_contract
        panel = _mapping(metadata.get("review_panel"))
        if panel.get("panel_size") != expected_panel_size:
            errors.append(
                "review_metadata.review_panel.panel_size must be "
                f"{expected_panel_size} for {schema_version}"
            )
        if panel.get("score_aggregation") != expected_score_aggregation:
            errors.append(
                "review_metadata.review_panel.score_aggregation must be "
                f"{expected_score_aggregation} for {schema_version}"
            )
        if panel.get("decision_aggregation") != expected_decision_aggregation:
            errors.append(
                "review_metadata.review_panel.decision_aggregation must be "
                f"{expected_decision_aggregation} for {schema_version}"
            )
        if panel.get("parallel_execution") is not expected_parallel_execution:
            errors.append(
                "review_metadata.review_panel.parallel_execution must be "
                f"{str(expected_parallel_execution).lower()} for {schema_version}"
            )
        if panel.get("independent_contexts") is not True:
            errors.append("review_metadata.review_panel.independent_contexts must be true")
        if panel.get("prior_reviews_hidden") is not True:
            errors.append("review_metadata.review_panel.prior_reviews_hidden must be true")
        reviewer_records = panel.get("reviewer_records")
        if not isinstance(reviewer_records, list) or len(reviewer_records) != expected_panel_size:
            errors.append(
                "review_metadata.review_panel.reviewer_records must contain exactly "
                f"{expected_panel_size} entries"
            )
        else:
            reviewer_ids: list[str] = []
            sources: list[str] = []
            for index, record in enumerate(reviewer_records):
                path = f"review_metadata.review_panel.reviewer_records[{index}]"
                item = _mapping(record)
                reviewer_id = item.get("reviewer_id")
                source = item.get("source")
                sha256 = item.get("sha256")
                if not isinstance(reviewer_id, str) or not reviewer_id.strip():
                    errors.append(f"{path}.reviewer_id must be a non-empty string")
                else:
                    reviewer_ids.append(reviewer_id)
                if not isinstance(source, str) or not source.strip():
                    errors.append(f"{path}.source must be a non-empty string")
                else:
                    sources.append(source)
                if not isinstance(sha256, str) or _SHA256.fullmatch(sha256) is None:
                    errors.append(f"{path}.sha256 must be a lowercase SHA-256")
                if schema_version in (
                    REVIEW_SCHEMA_VERSION,
                    SINGLE_REVIEW_SCHEMA_VERSION,
                ):
                    expected_reviewer_id = f"reviewer-{index + 1}"
                    if reviewer_id != expected_reviewer_id:
                        errors.append(f"{path}.reviewer_id must be {expected_reviewer_id}")
                    contract = REVIEWER_PROVIDER_CONTRACTS.get(str(reviewer_id))
                    if contract is None:
                        errors.append(f"{path}.reviewer_id is not in the current provider contract")
                    else:
                        if item.get("provider") != contract["provider"]:
                            errors.append(f"{path}.provider must be {contract['provider']}")
                        expected_model = contract["model"]
                        if expected_model is not None and item.get("model") != expected_model:
                            errors.append(f"{path}.model must be {expected_model}")
                        elif expected_model is None and (
                            not isinstance(item.get("model"), str)
                            or not str(item.get("model")).strip()
                        ):
                            errors.append(f"{path}.model must be a non-empty string")
            if len(set(reviewer_ids)) != len(reviewer_ids):
                errors.append("review panel reviewer_id values must be unique")
            if len(set(sources)) != len(sources):
                errors.append("review panel source values must be unique")

        shared_audits = panel.get("shared_objective_audits", [])
        if not isinstance(shared_audits, list):
            errors.append("review_metadata.review_panel.shared_objective_audits must be an array")
        else:
            audit_kinds: list[str] = []
            audit_sources: list[str] = []
            for index, record in enumerate(shared_audits):
                path = f"review_metadata.review_panel.shared_objective_audits[{index}]"
                item = _mapping(record)
                kind = item.get("kind")
                source = item.get("source")
                sha256 = item.get("sha256")
                if kind != LEAN_OBJECTIVE_AUDIT_KIND:
                    errors.append(f"{path}.kind must be {LEAN_OBJECTIVE_AUDIT_KIND}")
                else:
                    audit_kinds.append(kind)
                if not isinstance(source, str) or not source.strip():
                    errors.append(f"{path}.source must be a non-empty string")
                else:
                    audit_sources.append(source)
                if not isinstance(sha256, str) or _SHA256.fullmatch(sha256) is None:
                    errors.append(f"{path}.sha256 must be a lowercase SHA-256")
                if item.get("status") != "PASS":
                    errors.append(f"{path}.status must be PASS")
                for key in (
                    "manuscript_snapshot_sha256",
                    "support_package_sha256",
                ):
                    value = item.get(key)
                    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                        errors.append(f"{path}.{key} must be a lowercase SHA-256")
            if len(set(audit_kinds)) != len(audit_kinds):
                errors.append("review panel may reference at most one Lean objective audit")
            if len(set(audit_sources)) != len(audit_sources):
                errors.append("review panel objective-audit source values must be unique")

    return errors


def validate_review_panel_files(
    payload: Any,
    *,
    review_path: str | Path,
    repo_root: str | Path,
    expected_role: str | None = None,
    expected_paper_id: str | None = None,
) -> list[str]:
    """Validate a review panel and its schema-bound mechanical aggregation.

    Reviewer agents own the scientific judgments. This function only verifies
    immutable sources, provider separation, common snapshots, and aggregation.
    """

    errors = validate_review_record(
        payload,
        expected_role=expected_role,
        expected_paper_id=expected_paper_id,
    )
    if not isinstance(payload, Mapping):
        return errors
    schema_version = payload.get("schema_version")
    panel_contract = _panel_contract(schema_version)
    if panel_contract is None:
        errors.append(
            "final review must use panel schema "
            f"{REVIEW_SCHEMA_VERSION}, {SINGLE_REVIEW_SCHEMA_VERSION}, "
            f"or historical {LEGACY_REVIEW_SCHEMA_VERSION}"
        )
        return errors
    (
        expected_panel_size,
        score_aggregation,
        decision_aggregation,
        _,
    ) = panel_contract

    root = Path(repo_root).resolve()
    aggregate_path = Path(review_path).resolve()
    try:
        aggregate_path.relative_to(root)
    except ValueError:
        errors.append("panel review must stay inside the Writing repository")
        return errors

    metadata = _mapping(payload.get("review_metadata"))
    panel = _mapping(metadata.get("review_panel"))
    records = panel.get("reviewer_records")
    if not isinstance(records, list) or len(records) != expected_panel_size:
        return errors

    reviewer_payloads: list[Mapping[str, Any]] = []
    for index, record in enumerate(records):
        item = _mapping(record)
        source = item.get("source")
        if not isinstance(source, str) or not source.strip():
            continue
        source_path = (root / source).resolve()
        try:
            source_path.relative_to(root)
        except ValueError:
            errors.append(f"reviewer record {index + 1} escapes the Writing repository")
            continue
        if source_path == aggregate_path:
            errors.append(f"reviewer record {index + 1} cannot reference the panel result")
            continue
        if source_path.parent != aggregate_path.parent:
            errors.append(f"reviewer record {index + 1} must be stored beside the panel result")
            continue
        if not source_path.is_file():
            errors.append(f"reviewer record {index + 1} does not exist: {source}")
            continue
        raw = source_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item.get("sha256"):
            errors.append(f"reviewer record {index + 1} SHA-256 mismatch: {source}")
            continue
        try:
            reviewer = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"reviewer record {index + 1} is invalid JSON: {exc}")
            continue
        if not isinstance(reviewer, Mapping):
            errors.append(f"reviewer record {index + 1} must be a JSON object")
            continue
        if reviewer.get("schema_version") != INDIVIDUAL_REVIEW_SCHEMA_VERSION:
            errors.append(
                f"reviewer record {index + 1} must use schema {INDIVIDUAL_REVIEW_SCHEMA_VERSION}"
            )
        errors.extend(
            f"reviewer record {index + 1}: {error}"
            for error in validate_review_record(
                reviewer,
                expected_role=expected_role,
                expected_paper_id=expected_paper_id,
            )
        )
        reviewer_metadata = _mapping(reviewer.get("review_metadata"))
        if reviewer_metadata.get("panel_reviewer_id") != item.get("reviewer_id"):
            errors.append(f"reviewer record {index + 1} panel_reviewer_id does not match the panel")
        if reviewer_metadata.get("independent_context") is not True:
            errors.append(f"reviewer record {index + 1} independent_context must be true")
        if reviewer_metadata.get("prior_reviews_hidden") is not True:
            errors.append(f"reviewer record {index + 1} prior_reviews_hidden must be true")
        if schema_version in (
            REVIEW_SCHEMA_VERSION,
            SINGLE_REVIEW_SCHEMA_VERSION,
        ):
            reviewer_id = str(item.get("reviewer_id") or "")
            provider_contract = REVIEWER_PROVIDER_CONTRACTS.get(reviewer_id)
            if provider_contract is not None:
                if reviewer_metadata.get("provider") != provider_contract["provider"]:
                    errors.append(
                        f"reviewer record {index + 1} provider must be "
                        f"{provider_contract['provider']}"
                    )
                expected_model = provider_contract["model"]
                if expected_model is not None and reviewer_metadata.get("model") != expected_model:
                    errors.append(f"reviewer record {index + 1} model must be {expected_model}")
                if item.get("provider") != reviewer_metadata.get("provider"):
                    errors.append(f"reviewer record {index + 1} provider does not match the panel")
                if item.get("model") != reviewer_metadata.get("model"):
                    errors.append(f"reviewer record {index + 1} model does not match the panel")
        for key in (
            "main_tex_sha256",
            "manuscript_snapshot_sha256_before",
            "manuscript_snapshot_sha256_after",
        ):
            if reviewer_metadata.get(key) != metadata.get(key):
                errors.append(f"reviewer record {index + 1} {key} does not match the panel result")
        reviewer_payloads.append(reviewer)

    if len(reviewer_payloads) != expected_panel_size:
        return errors

    if schema_version == REVIEW_SCHEMA_VERSION:
        reviewer_one_hash = str(_mapping(records[0]).get("sha256") or "")
        reviewer_two_metadata = _mapping(reviewer_payloads[1].get("review_metadata"))
        if reviewer_two_metadata.get("hidden_peer_review_sha256") != reviewer_one_hash:
            errors.append(
                "reviewer record 2 hidden_peer_review_sha256 must bind the frozen reviewer-1 record"
            )

    shared_audits = panel.get("shared_objective_audits", [])
    if isinstance(shared_audits, list):
        for index, record in enumerate(shared_audits):
            item = _mapping(record)
            source = item.get("source")
            if not isinstance(source, str) or not source.strip():
                continue
            receipt_path = (root / source).resolve()
            try:
                receipt_path.relative_to(root)
            except ValueError:
                errors.append(f"objective audit {index + 1} escapes the Writing repository")
                continue
            if receipt_path == aggregate_path:
                errors.append(f"objective audit {index + 1} cannot reference the panel result")
                continue
            if not receipt_path.is_file():
                errors.append(f"objective audit {index + 1} does not exist: {source}")
                continue
            raw = receipt_path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != item.get("sha256"):
                errors.append(f"objective audit {index + 1} SHA-256 mismatch: {source}")
                continue
            try:
                receipt = json.loads(raw)
            except json.JSONDecodeError as exc:
                errors.append(f"objective audit {index + 1} is invalid JSON: {exc}")
                continue
            if not isinstance(receipt, Mapping):
                errors.append(f"objective audit {index + 1} must be a JSON object")
                continue
            prefix = f"objective audit {index + 1}"
            expected_snapshot = metadata.get("manuscript_snapshot_sha256_before")
            checks = (
                ("schema_version", LEAN_OBJECTIVE_AUDIT_SCHEMA_VERSION),
                ("status", "PASS"),
                ("paper_id", expected_paper_id or metadata.get("paper_id")),
                ("manuscript_snapshot_sha256", expected_snapshot),
                ("support_package_sha256", item.get("support_package_sha256")),
                ("objective_only", True),
                ("score_bearing", False),
                ("execution_count", 1),
                ("formal_validation_execution_count", 1),
                ("cumulative_formal_validation_execution_count", 1),
            )
            for key, expected in checks:
                if receipt.get(key) != expected:
                    errors.append(
                        f"{prefix} {key} must equal {expected!r}, got {receipt.get(key)!r}"
                    )
            if item.get("manuscript_snapshot_sha256") != expected_snapshot:
                errors.append(f"{prefix} panel snapshot binding does not match the review")
            if item.get("status") != receipt.get("status"):
                errors.append(f"{prefix} panel status does not match the receipt")

            limits = _mapping(receipt.get("resource_limits"))
            bounded_limits = (
                ("threads", 1, 4),
                ("aggregate_rss_mib", 1024, 24576),
                ("per_process_as_mib", 1024, 32768),
                ("max_processes", 2, 24),
                ("timeout_seconds", 60, 3600),
            )
            for key, minimum, maximum in bounded_limits:
                value = limits.get(key)
                if (
                    not isinstance(value, int)
                    or isinstance(value, bool)
                    or not minimum <= value <= maximum
                ):
                    errors.append(
                        f"{prefix} resource_limits.{key} must be between {minimum} and {maximum}"
                    )
            preflight = _mapping(receipt.get("preflight"))
            total_memory = preflight.get("total_memory_mib")
            available_memory = preflight.get("available_memory_mib")
            reserved_headroom = preflight.get("reserved_headroom_mib")
            required_available = preflight.get("required_available_memory_mib")
            aggregate_limit = limits.get("aggregate_rss_mib")
            memory_values = (
                total_memory,
                available_memory,
                reserved_headroom,
                required_available,
                aggregate_limit,
            )
            if not all(
                isinstance(value, int) and not isinstance(value, bool) and value > 0
                for value in memory_values
            ):
                errors.append(f"{prefix} must record positive integer memory preflight values")
            else:
                expected_reserve = max(8192, total_memory // 4)
                if reserved_headroom != expected_reserve:
                    errors.append(f"{prefix} reserved_headroom_mib must equal {expected_reserve}")
                expected_required = aggregate_limit + reserved_headroom
                if required_available != expected_required:
                    errors.append(
                        f"{prefix} required_available_memory_mib must equal {expected_required}"
                    )
                if available_memory < required_available:
                    errors.append(f"{prefix} available memory did not preserve the host headroom")
            audit_file = receipt.get("audit_file")
            commands = receipt.get("commands")
            expected_commands = (
                ["lake", "build", "--quiet"],
                ["lake", "env", "lean", audit_file],
            )
            if not isinstance(commands, list) or len(commands) != 2:
                errors.append(f"{prefix} must contain exactly two sequential commands")
            else:
                for command_index, (command, expected_command) in enumerate(
                    zip(commands, expected_commands, strict=True), start=1
                ):
                    result = _mapping(command)
                    if result.get("command") != expected_command:
                        errors.append(
                            f"{prefix} command {command_index} does not match the bounded workflow"
                        )
                    if result.get("return_code") != 0:
                        errors.append(f"{prefix} command {command_index} did not pass")
                    if "resource_violation" in result:
                        errors.append(
                            f"{prefix} command {command_index} reports a resource violation"
                        )

            project = receipt.get("project")
            if not isinstance(project, str) or not project.strip():
                errors.append(f"{prefix} project must be a repository-relative path")
            else:
                project_path = (root / project).resolve()
                try:
                    project_path.relative_to(root)
                except ValueError:
                    errors.append(f"{prefix} project escapes the Writing repository")
                else:
                    if not project_path.is_dir():
                        errors.append(f"{prefix} project does not exist: {project}")
                    elif isinstance(audit_file, str):
                        audit_path = (project_path / audit_file).resolve()
                        if not audit_path.is_relative_to(project_path) or not audit_path.is_file():
                            errors.append(f"{prefix} audit_file is missing or escapes its project")

            source_hashes = receipt.get("source_sha256")
            if not isinstance(source_hashes, Mapping) or not source_hashes:
                errors.append(f"{prefix} source_sha256 must be a non-empty object")
            elif isinstance(project, str) and (root / project).resolve().is_dir():
                project_path = (root / project).resolve()
                for relative, expected_hash in source_hashes.items():
                    if (
                        not isinstance(relative, str)
                        or not isinstance(expected_hash, str)
                        or _SHA256.fullmatch(expected_hash) is None
                    ):
                        errors.append(f"{prefix} contains an invalid source hash entry")
                        continue
                    source_path = (project_path / relative).resolve()
                    if not source_path.is_relative_to(project_path) or not source_path.is_file():
                        errors.append(
                            f"{prefix} source is missing or escapes its project: {relative}"
                        )
                    elif hashlib.sha256(source_path.read_bytes()).hexdigest() != expected_hash:
                        errors.append(f"{prefix} source SHA-256 mismatch: {relative}")

    final_scores = _mapping(payload.get("scores"))
    for key in ("clarity", "soundness", "significance", "novelty", "overall"):
        values = [_mapping(review.get("scores")).get(key) for review in reviewer_payloads]
        if all(isinstance(value, int) and not isinstance(value, bool) for value in values):
            expected = _aggregate_score(values, score_aggregation)
            if final_scores.get(key) != expected:
                errors.append(
                    f"scores.{key} must equal {score_aggregation} {expected}, got "
                    f"{final_scores.get(key)!r}"
                )

    role = expected_role or metadata.get("reviewer_role")
    final_recommendations = _mapping(payload.get("recommendations"))
    if role == CS_TOP_TIER_REVIEWER_ROLE:
        values = [
            _mapping(
                _mapping(_mapping(review.get("recommendations")).get(TOP_CONFERENCE_VIEW)).get(
                    "seven_point"
                )
            ).get("decision")
            for review in reviewer_payloads
        ]
        if all(value in CONFERENCE_DECISIONS for value in values):
            expected = _aggregate_decision(values, CONFERENCE_DECISIONS, decision_aggregation)
            actual = _mapping(
                _mapping(final_recommendations.get(TOP_CONFERENCE_VIEW)).get("seven_point")
            ).get("decision")
            if actual != expected:
                errors.append(
                    f"recommendations.{TOP_CONFERENCE_VIEW}.seven_point.decision must equal "
                    f"{decision_aggregation} {expected}"
                )
    elif role == MATHEMATICS_REVIEWER_ROLE:
        values = [
            _mapping(_mapping(review.get("recommendations")).get(FOUR_TOP_MATH_JOURNALS_VIEW)).get(
                "decision"
            )
            for review in reviewer_payloads
        ]
        if all(value in JOURNAL_DECISIONS for value in values):
            expected = _aggregate_decision(values, JOURNAL_DECISIONS, decision_aggregation)
            actual = _mapping(final_recommendations.get(FOUR_TOP_MATH_JOURNALS_VIEW)).get(
                "decision"
            )
            if actual != expected:
                errors.append(
                    f"recommendations.{FOUR_TOP_MATH_JOURNALS_VIEW}.decision must equal "
                    f"{decision_aggregation} {expected}"
                )
    elif role == MATERIALS_REVIEWER_ROLE:
        values = [
            _mapping(
                _mapping(review.get("recommendations")).get(LEADING_MATERIALS_JOURNALS_VIEW)
            ).get("decision")
            for review in reviewer_payloads
        ]
        if all(value in JOURNAL_DECISIONS for value in values):
            expected = _aggregate_decision(values, JOURNAL_DECISIONS, decision_aggregation)
            actual = _mapping(final_recommendations.get(LEADING_MATERIALS_JOURNALS_VIEW)).get(
                "decision"
            )
            if actual != expected:
                errors.append(
                    f"recommendations.{LEADING_MATERIALS_JOURNALS_VIEW}.decision must equal "
                    f"{decision_aggregation} {expected}"
                )
    elif role == PHYSICS_REVIEWER_ROLE:
        values = [
            _mapping(
                _mapping(review.get("recommendations")).get(LEADING_PHYSICS_JOURNALS_VIEW)
            ).get("decision")
            for review in reviewer_payloads
        ]
        if all(value in JOURNAL_DECISIONS for value in values):
            expected = _aggregate_decision(values, JOURNAL_DECISIONS, decision_aggregation)
            actual = _mapping(final_recommendations.get(LEADING_PHYSICS_JOURNALS_VIEW)).get(
                "decision"
            )
            if actual != expected:
                errors.append(
                    f"recommendations.{LEADING_PHYSICS_JOURNALS_VIEW}.decision must equal "
                    f"{decision_aggregation} {expected}"
                )
    elif role == QUANT_FINANCE_REVIEWER_ROLE:
        values = [
            _mapping(
                _mapping(review.get("recommendations")).get(LEADING_QUANT_FINANCE_JOURNALS_VIEW)
            ).get("decision")
            for review in reviewer_payloads
        ]
        if all(value in JOURNAL_DECISIONS for value in values):
            expected = _aggregate_decision(values, JOURNAL_DECISIONS, decision_aggregation)
            actual = _mapping(final_recommendations.get(LEADING_QUANT_FINANCE_JOURNALS_VIEW)).get(
                "decision"
            )
            if actual != expected:
                errors.append(
                    f"recommendations.{LEADING_QUANT_FINANCE_JOURNALS_VIEW}.decision must equal "
                    f"{decision_aggregation} {expected}"
                )

    cas_values = [
        _mapping(_mapping(review.get("recommendations")).get(CAS_ZONE_1_JOURNAL_VIEW)).get(
            "decision"
        )
        for review in reviewer_payloads
    ]
    if all(value in JOURNAL_DECISIONS for value in cas_values):
        expected = _aggregate_decision(cas_values, JOURNAL_DECISIONS, decision_aggregation)
        actual = _mapping(final_recommendations.get(CAS_ZONE_1_JOURNAL_VIEW)).get("decision")
        if actual != expected:
            errors.append(
                f"recommendations.{CAS_ZONE_1_JOURNAL_VIEW}.decision must equal "
                f"{decision_aggregation} {expected}"
            )

    return errors


def review_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Extract display and gate inputs after a record has been validated."""

    scores = _mapping(payload.get("scores"))
    recommendations = _mapping(payload.get("recommendations"))
    metadata = _mapping(payload.get("review_metadata"))
    reviewer_role = metadata.get("reviewer_role")
    if reviewer_role == MATHEMATICS_REVIEWER_ROLE:
        high_standard_view = FOUR_TOP_MATH_JOURNALS_VIEW
        high_standard = _mapping(recommendations.get(FOUR_TOP_MATH_JOURNALS_VIEW))
    elif reviewer_role == MATERIALS_REVIEWER_ROLE:
        high_standard_view = LEADING_MATERIALS_JOURNALS_VIEW
        high_standard = _mapping(recommendations.get(LEADING_MATERIALS_JOURNALS_VIEW))
    elif reviewer_role == PHYSICS_REVIEWER_ROLE:
        high_standard_view = LEADING_PHYSICS_JOURNALS_VIEW
        high_standard = _mapping(recommendations.get(LEADING_PHYSICS_JOURNALS_VIEW))
    elif reviewer_role == QUANT_FINANCE_REVIEWER_ROLE:
        high_standard_view = LEADING_QUANT_FINANCE_JOURNALS_VIEW
        high_standard = _mapping(recommendations.get(LEADING_QUANT_FINANCE_JOURNALS_VIEW))
    else:
        high_standard_view = TOP_CONFERENCE_VIEW
        high_standard = _mapping(
            _mapping(recommendations.get(TOP_CONFERENCE_VIEW)).get("seven_point")
        )
    cas_zone_1 = _mapping(recommendations.get(CAS_ZONE_1_JOURNAL_VIEW))
    return {
        "paper_id": metadata.get("paper_id"),
        "reviewer_role": reviewer_role,
        "rubric_id": metadata.get("rubric_id"),
        "overall": scores.get("overall"),
        "high_standard_view": high_standard_view,
        "high_standard_decision": high_standard.get("decision"),
        "cas_zone_1_decision": cas_zone_1.get("decision"),
        "panel_size": _mapping(metadata.get("review_panel")).get("panel_size"),
        "score_aggregation": _mapping(metadata.get("review_panel")).get("score_aggregation"),
    }
