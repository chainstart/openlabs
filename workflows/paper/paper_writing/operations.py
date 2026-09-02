"""Small Git-friendly operations for evidence-backed manuscript workspaces."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from paper_writing.identifiers import (
    domain_scoped_parts,
    public_manuscript_filename,
    validate_new_paper_id,
    work_id_from_paper_id,
)
from paper_writing.inventory import build_inventory
from paper_writing.manuscript_style import (
    audit_manuscript_style,
    manuscript_style_blockers,
)
from paper_writing.registry import (
    load_paper_metadata,
    load_registry,
    load_registry_settings,
    paper_metadata_path,
    write_paper_metadata,
)
from paper_writing.review import (
    CAS_ZONE_1_JOURNAL_VIEW,
    CS_TOP_TIER_REVIEWER_ROLE,
    FOUR_TOP_MATH_JOURNALS_VIEW,
    LEADING_MATERIALS_JOURNALS_VIEW,
    LEADING_PHYSICS_JOURNALS_VIEW,
    LEADING_QUANT_FINANCE_JOURNALS_VIEW,
    MATERIALS_REVIEWER_ROLE,
    PHYSICS_HIGHEST_TIER_VENUES,
    PHYSICS_REVIEWER_ROLE,
    QUANT_FINANCE_REVIEWER_ROLE,
    TOP_CONFERENCE_VIEW,
    decision_meets_standard_threshold,
    decisions_for_standard,
    configured_review_contract,
    reviewer_role_for_domain,
    validate_review_panel_files,
)
from paper_writing.support import SupportPackageError
from paper_writing.support_policy import publication_policy
from paper_writing.support_citations import audit_manuscript_support, support_audit_blockers


REVIEW_CARRY_FORWARD_SCHEMA_VERSION = "ara.paper_writing.review_carry_forward.v1"
REVIEW_SIGNIFICANT_REGISTRY_FIELDS = (
    "abstract",
    "description",
    "domain",
    "keywords",
    "subdomain",
    "subtitle",
    "target_journal",
    "target_journal_section",
    "title",
    "venue_type",
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _registry_review_content_sha256(metadata: Mapping[str, Any]) -> str:
    """Hash registry fields that can alter the reviewed public scientific claim."""

    import hashlib

    projected = {
        field: metadata[field]
        for field in REVIEW_SIGNIFICANT_REGISTRY_FIELDS
        if metadata.get(field) is not None
    }
    encoded = json.dumps(
        projected,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(
        b"ara.paper_writing.registry_review_content.v1\0" + encoded
    ).hexdigest()


def _review_workspace_fingerprints(
    paper_id: str,
    metadata: Mapping[str, Any],
    repo_root: Path,
) -> dict[str, str | None]:
    from paper_writing.handoff import (
        manuscript_review_content_sha256,
        manuscript_snapshot_sha256,
    )
    from paper_writing.support import support_sources_snapshot_sha256

    manuscript = repo_root / str(
        metadata.get("manuscript_dir") or f"papers/{paper_id}/manuscript"
    )
    canonical_pdf = repo_root / str(
        metadata.get("latest_pdf") or f"papers/{paper_id}/manuscript/main.pdf"
    )
    if not manuscript.is_dir():
        raise FileNotFoundError(manuscript)
    return {
        "manuscript_snapshot_sha256": manuscript_snapshot_sha256(
            manuscript, canonical_pdf
        ),
        "review_content_sha256": manuscript_review_content_sha256(
            manuscript, canonical_pdf
        ),
        "registry_review_content_sha256": _registry_review_content_sha256(metadata),
        "support_sources_sha256": support_sources_snapshot_sha256(
            metadata, repo_root=repo_root
        ),
    }


def _review_carry_forward_candidate(
    paper_id: str,
    metadata: Mapping[str, Any],
    repo_root: Path,
) -> dict[str, Any] | None:
    """Capture a verified baseline before a revision can modify any file."""

    release = metadata.get("writing_release")
    if not isinstance(release, Mapping) or release.get("status") != "ready":
        return None
    try:
        fingerprints = _review_workspace_fingerprints(paper_id, metadata, repo_root)
    except (OSError, ValueError, SupportPackageError):
        return None
    if (
        release.get("manuscript_snapshot_sha256")
        != fingerprints["manuscript_snapshot_sha256"]
    ):
        return None
    for key in (
        "review_content_sha256",
        "registry_review_content_sha256",
        "support_sources_sha256",
    ):
        if key in release and release.get(key) != fingerprints.get(key):
            return None
    if str(release.get("manuscript_version") or "") != str(
        metadata.get("version") or "1.0.0"
    ):
        return None
    support = metadata.get("support")
    support = support if isinstance(support, Mapping) else {}
    publication = support.get("publication")
    publication = publication if isinstance(publication, Mapping) else {}
    current_package = str(publication.get("package_sha256") or "")
    gated_package = str(release.get("support_package_sha256") or "")
    if current_package and gated_package != current_package:
        return None
    return {
        "schema_version": REVIEW_CARRY_FORWARD_SCHEMA_VERSION,
        "captured_at": _now(),
        "source_release": deepcopy(dict(release)),
        "source_review": deepcopy(metadata.get("ara_llm_self_review")),
        **fingerprints,
    }


def create_paper(
    *,
    root: str | Path,
    paper_id: str,
    title: str,
    created_at: str,
    domain: str,
    subdomain: str,
    venue_type: str,
    project_name: str | None = None,
    target_journal: str | None = None,
) -> Path:
    repo_root = Path(root).resolve()
    validate_new_paper_id(
        paper_id,
        created_at=created_at,
        domain=domain,
        subdomain=subdomain,
    )
    path = paper_metadata_path(paper_id, repo_root)
    if path.exists() or (repo_root / "papers" / paper_id).exists():
        raise FileExistsError(paper_id)
    workspace = repo_root / "papers" / paper_id
    for folder in ("manuscript", "evidence", "revisions", "support-materials"):
        (workspace / folder).mkdir(parents=True, exist_ok=True)
    (workspace / "manuscript" / "main.tex").write_text(
        "\\documentclass{article}\n\\title{" + title + "}\n\\author{}\n"
        "\\begin{document}\n\\maketitle\n\\begin{abstract}\n\\end{abstract}\n"
        "\\section*{Generative AI declaration}\n"
        "During the preparation of this work, the authors used OpenAI GPT-5.6 "
        "through Codex to assist with manuscript drafting, editing, and technical "
        "preparation. The authors reviewed and edited all AI-assisted text and take "
        "full responsibility for the article. AI-generated output was not treated as "
        "evidence, mathematical proof, formal verification, or external peer review.\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (workspace / "manuscript" / "references.bib").write_text("", encoding="utf-8")
    (workspace / "evidence" / "claim_evidence_map.md").write_text(
        "# Claim–evidence map\n\nNo manuscript claim is approved until it is linked to a validated artifact or verified source.\n",
        encoding="utf-8",
    )
    work_id = work_id_from_paper_id(paper_id)
    if work_id is None:  # Guard the invariant established by the format check above.
        raise AssertionError("descriptive paper_id did not produce a work_id")
    normalized_project_name = str(project_name or "").strip() or work_id
    settings = load_registry_settings(repo_root)
    support_policy = publication_policy(settings)
    default_support_mode = str(
        support_policy.get("default_mode") or "zenodo_only"
    ).strip()
    default_support_license = str(
        support_policy.get("default_license") or ""
    ).strip()
    support_publication = {
        "mode": default_support_mode,
        "status": "planned",
    }
    if default_support_license:
        support_publication["license"] = default_support_license
    payload = {
        "paper_id": paper_id,
        "display_id": paper_id,
        "work_id": work_id,
        "workspace": f"papers/{paper_id}",
        "project_name": normalized_project_name,
        "created_at": created_at,
        "domain": domain,
        "subdomain": subdomain,
        "record_status": "paper_workspace",
        "title": title,
        "title_history": [],
        "manuscript_dir": f"papers/{paper_id}/manuscript",
        "latest_source": f"papers/{paper_id}/manuscript/main.tex",
        "version": "0.1.0",
        "venue_type": venue_type,
        "evidence_bundles": [],
        "writing_release": {"status": "draft"},
        "support": {
            "publication": support_publication
        },
        "status_updated_at": _now(),
    }
    if target_journal and target_journal.strip():
        payload["target_journal"] = target_journal.strip()
    return write_paper_metadata(paper_id, payload, repo_root)


def canonical_public_manuscript_filename(
    paper_id: str, *, root: str | Path
) -> str:
    """Resolve the policy-compliant public PDF name from registered metadata."""

    metadata = load_paper_metadata(paper_id, Path(root).resolve())
    display_id = str(metadata.get("display_id") or "").strip()
    if not display_id and domain_scoped_parts(paper_id):
        display_id = paper_id
    if not display_id:
        raise ValueError(
            f"A domain-scoped display_id is required for public files: {paper_id}"
        )
    version = str(metadata.get("version") or "").strip()
    return public_manuscript_filename(display_id, version)


def start_revision(paper_id: str, reason: str, *, root: str | Path) -> dict[str, Any]:
    repo_root = Path(root).resolve()
    payload = load_paper_metadata(paper_id, repo_root)
    carry_forward = _review_carry_forward_candidate(paper_id, payload, repo_root)
    revision_root = repo_root / "papers" / paper_id / "revisions"
    revision_root.mkdir(parents=True, exist_ok=True)
    existing = [
        int(match.group(1))
        for path in revision_root.glob("round-*.md")
        if (match := re.fullmatch(r"round-(\d+)\.md", path.name))
    ]
    round_number = max(existing, default=0) + 1
    path = revision_root / f"round-{round_number:02d}.md"
    path.write_text(
        f"# 返修第 {round_number} 轮\n\n- 开始时间：{_now()}\n- 原因：{reason}\n"
        "- 审稿意见：\n- 证据变化：\n- 修改文件：\n- 验证结果：\n",
        encoding="utf-8",
    )
    version = str(payload.get("version") or "0.1.0")
    parts = version.lstrip("v").split(".")
    try:
        major, minor, patch = (int(parts[0]), int(parts[1]), int(parts[2]))
        new_version = f"{major}.{minor}.{patch + 1}"
    except (IndexError, ValueError):
        new_version = f"{version}-revision-{round_number}"
    payload["version"] = new_version
    changed_at = _now()
    draft_release: dict[str, Any] = {
        "status": "draft",
        "invalidated_at": changed_at,
        "invalidated_reason": "revision_started",
    }
    if carry_forward is not None:
        draft_release["review_carry_forward"] = carry_forward
    payload["writing_release"] = draft_release
    payload["status_updated_at"] = changed_at
    write_paper_metadata(paper_id, payload, repo_root)
    return {
        "paper_id": paper_id,
        "round": round_number,
        "version": new_version,
        "file": str(path.relative_to(repo_root)),
        "review_carry_forward_available": carry_forward is not None,
    }


def _validated_review_blockers(
    *,
    paper_id: str,
    review: str | Path | None,
    repo_root: Path,
    metadata: Mapping[str, Any],
    gate: Mapping[str, Any],
    score: float,
    decision: str,
    snapshot_sha256: str,
) -> list[str]:
    """Return blockers for an absent, stale, non-independent, or mismatched review."""

    prefix = "REVIEW-VALIDATION"
    if review is None:
        return [
            f"{prefix}: a validated fresh-context review must be applied with "
            "`paper-writing review apply`; direct score entry is not a review"
        ]
    review_path = Path(review)
    if not review_path.is_absolute():
        review_path = repo_root / review_path
    review_path = review_path.resolve()
    try:
        review_path.relative_to(repo_root)
    except ValueError:
        return [f"{prefix}: review record escapes the paper repository"]
    if not review_path.is_file():
        return [f"{prefix}: review record does not exist: {review_path}"]
    try:
        review_payload = json.loads(review_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{prefix}: review record is unreadable: {exc}"]
    if not isinstance(review_payload, Mapping):
        return [f"{prefix}: review record must be a JSON object"]

    expected_role = reviewer_role_for_domain(metadata.get("domain"))
    validation_errors = validate_review_panel_files(
        review_payload,
        review_path=review_path,
        repo_root=repo_root,
        expected_role=expected_role,
        expected_paper_id=paper_id,
    )
    blockers = [f"{prefix}: {item}" for item in validation_errors]
    review_metadata = review_payload.get("review_metadata")
    review_metadata = review_metadata if isinstance(review_metadata, Mapping) else {}
    panel = review_metadata.get("review_panel")
    panel = panel if isinstance(panel, Mapping) else {}
    try:
        review_contract = configured_review_contract(gate)
    except ValueError as exc:
        return blockers + [f"{prefix}: invalid configured review contract: {exc}"]
    configured_contract = {
        "panel_size": review_contract["panel_size"],
        "score_aggregation": review_contract["score_aggregation"],
        "decision_aggregation": review_contract["decision_aggregation"],
        "independent_contexts": True,
        "isolated_processes": True,
        "prior_reviews_hidden": True,
    }
    for key, expected in configured_contract.items():
        if panel.get(key) != expected:
            blockers.append(
                f"{prefix}: review_metadata.review_panel.{key} must be {expected!r} "
                "under the active paper settings"
            )

    scores = review_payload.get("scores")
    scores = scores if isinstance(scores, Mapping) else {}
    if scores.get("overall") != score:
        blockers.append(
            f"{prefix}: supplied score {score!r} does not match panel overall "
            f"{scores.get('overall')!r}"
        )
    recommendations = review_payload.get("recommendations")
    recommendations = recommendations if isinstance(recommendations, Mapping) else {}
    cas = recommendations.get(CAS_ZONE_1_JOURNAL_VIEW)
    cas = cas if isinstance(cas, Mapping) else {}
    if cas.get("decision") != decision:
        blockers.append(
            f"{prefix}: supplied decision {decision!r} does not match panel CAS Zone 1 "
            f"decision {cas.get('decision')!r}"
        )
    for key in (
        "manuscript_snapshot_sha256_before",
        "manuscript_snapshot_sha256_after",
    ):
        if review_metadata.get(key) != snapshot_sha256:
            blockers.append(
                f"{prefix}: review {key} is not bound to the current manuscript snapshot"
            )

    panel_blockers = review_payload.get("unresolved_blockers")
    if isinstance(panel_blockers, list):
        blockers.extend(
            str(item).strip()
            for item in panel_blockers
            if isinstance(item, str) and item.strip() and item not in blockers
        )
    publishability = review_payload.get("publishability_summary")
    publishability = publishability if isinstance(publishability, Mapping) else {}
    if publishability.get("text_ready") is not True:
        blockers.append(f"{prefix}: review panel does not mark the manuscript text ready")
    if publishability.get("scientific_ready") is not True:
        blockers.append(f"{prefix}: review panel does not mark the manuscript scientifically ready")
    return blockers


def record_quality_gate(
    paper_id: str,
    *,
    venue_type: str,
    score: float,
    decision: str,
    revision_rounds: int,
    unresolved_blockers: Iterable[str] = (),
    review: str | Path | None = None,
    root: str | Path,
) -> dict[str, Any]:
    """Record and deterministically evaluate an LLM review result.

    This does not run an LLM. The configured review workflow supplies a validated
    fresh-context panel record; this function applies the repository's stable
    pass/freeze thresholds. When independent review is required, an unbound
    score can never advance the paper to ``ready``.
    """

    repo_root = Path(root).resolve()
    if venue_type not in {"conference", "journal"}:
        raise ValueError("venue_type must be conference or journal")
    if not 0 <= score <= 10:
        raise ValueError("score must be between 0 and 10")
    if revision_rounds < 0:
        raise ValueError("revision_rounds cannot be negative")
    blockers = [str(item).strip() for item in unresolved_blockers]
    if any(not item for item in blockers):
        raise ValueError("unresolved_blockers must contain only non-empty strings")

    support_audit = audit_manuscript_support(paper_id, root=repo_root)
    blockers.extend(
        blocker
        for blocker in support_audit_blockers(support_audit)
        if blocker not in blockers
    )

    settings = load_registry(
        repo_root,
        include_local_repositories=False,
        paper_ids=[paper_id],
    )
    gate = settings.get("quality_gate", {})
    style_audit: dict[str, Any] | None = None
    if bool(gate.get("require_manuscript_style_check", False)):
        style_audit = audit_manuscript_style(
            paper_id,
            root=repo_root,
            require_ai_declaration=bool(gate.get("require_ai_use_declaration", True)),
        )
        blockers.extend(
            blocker
            for blocker in manuscript_style_blockers(style_audit)
            if blocker not in blockers
        )
    minimum_score = float(gate.get("minimum_score", 5.0))
    maximum_rounds = int(gate.get("maximum_revision_rounds", 3))
    if revision_rounds > maximum_rounds:
        raise ValueError(
            "revision_rounds cannot exceed the configured maximum of "
            f"{maximum_rounds}"
        )
    decision_standard = str(gate.get("decision_standard") or venue_type)
    allowed = decisions_for_standard(decision_standard, venue_type=venue_type)
    if decision not in allowed:
        raise ValueError(f"Invalid {decision_standard} decision: {decision}")
    if decision_standard == CAS_ZONE_1_JOURNAL_VIEW:
        minimum_decision = str(
            gate.get("cas_zone_1_minimum_decision", "minor_revision")
        )
    else:
        minimum_decision = str(
            gate.get(
                "conference_minimum_decision"
                if decision_standard == "conference"
                else "journal_minimum_decision",
                "weak_accept"
                if decision_standard == "conference"
                else "minor_revision",
            )
        )
    if minimum_decision not in allowed:
        raise ValueError(
            f"Invalid configured {decision_standard} minimum decision: {minimum_decision}"
        )
    payload = load_paper_metadata(paper_id, repo_root)
    fingerprints = _review_workspace_fingerprints(paper_id, payload, repo_root)
    snapshot_sha256 = str(fingerprints["manuscript_snapshot_sha256"])
    if bool(gate.get("require_validated_independent_review", True)):
        review_blockers = _validated_review_blockers(
            paper_id=paper_id,
            review=review,
            repo_root=repo_root,
            metadata=payload,
            gate=gate,
            score=score,
            decision=decision,
            snapshot_sha256=snapshot_sha256,
        )
        blockers.extend(item for item in review_blockers if item not in blockers)

    passed = (
        score >= minimum_score
        and decision_meets_standard_threshold(
            decision,
            minimum_decision,
            decision_standard,
            venue_type=venue_type,
        )
        and not blockers
    )
    status = (
        "ready"
        if passed
        else "blocked"
        if revision_rounds >= maximum_rounds
        else "revision_required"
    )

    payload["venue_type"] = venue_type
    release_record = {
        "status": status,
        "target_score": minimum_score,
        "score": score,
        "venue_type": venue_type,
        "decision_standard": decision_standard,
        "decision": decision,
        "minimum_decision": minimum_decision,
        "revision_rounds_completed": revision_rounds,
        "max_revision_rounds": maximum_rounds,
        "reviewed_at": _now(),
        "manuscript_snapshot_sha256": snapshot_sha256,
        "review_content_sha256": fingerprints["review_content_sha256"],
        "registry_review_content_sha256": fingerprints[
            "registry_review_content_sha256"
        ],
        "manuscript_version": str(payload.get("version") or "1.0.0"),
    }
    if fingerprints["support_sources_sha256"] is not None:
        release_record["support_sources_sha256"] = fingerprints[
            "support_sources_sha256"
        ]
    if blockers:
        release_record["unresolved_review_blockers"] = blockers
    support = payload.get("support")
    support = support if isinstance(support, Mapping) else {}
    publication = support.get("publication")
    publication = publication if isinstance(publication, Mapping) else {}
    package_sha256 = str(publication.get("package_sha256") or "")
    if re.fullmatch(r"[0-9a-f]{64}", package_sha256):
        release_record["support_package_sha256"] = package_sha256
    payload["writing_release"] = release_record
    payload["status_updated_at"] = _now()
    write_paper_metadata(paper_id, payload, repo_root)
    return {
        "paper_id": paper_id,
        "status": status,
        "passed": passed,
        "score": score,
        "minimum_score": minimum_score,
        "decision": decision,
        "decision_standard": decision_standard,
        "minimum_decision": minimum_decision,
        "revision_rounds": revision_rounds,
        "maximum_revision_rounds": maximum_rounds,
        "unresolved_blockers": blockers,
        "manuscript_snapshot_sha256": snapshot_sha256,
        "review_content_sha256": fingerprints["review_content_sha256"],
        "registry_review_content_sha256": fingerprints[
            "registry_review_content_sha256"
        ],
        "support_sources_sha256": fingerprints["support_sources_sha256"],
        "support_package_sha256": release_record.get("support_package_sha256"),
        "support_materials_audit": support_audit,
        "manuscript_style_audit": style_audit,
    }


def apply_review_record(
    paper_id: str,
    *,
    review: str | Path,
    venue_type: str,
    revision_rounds: int | None,
    root: str | Path,
) -> dict[str, Any]:
    """Validate and register a skill-authored review, then apply the stable gate.

    The review skill owns every score and recommendation. This helper only
    verifies the immutable record and manuscript hashes, projects its fields into
    the paper registry, and delegates the pass/fail decision to the quality gate.
    """

    from paper_writing.handoff import manuscript_snapshot_sha256, sha256_file

    repo_root = Path(root).resolve()
    review_path = Path(review)
    if not review_path.is_absolute():
        review_path = repo_root / review_path
    review_path = review_path.resolve()
    try:
        review_relative = review_path.relative_to(repo_root).as_posix()
    except ValueError as exc:
        raise ValueError("Review record must stay inside the Writing repository") from exc
    if not review_path.is_file():
        raise FileNotFoundError(review_path)
    review_payload = json.loads(review_path.read_text(encoding="utf-8"))

    metadata = load_paper_metadata(paper_id, repo_root)
    expected_role = reviewer_role_for_domain(metadata.get("domain"))
    errors = validate_review_panel_files(
        review_payload,
        review_path=review_path,
        repo_root=repo_root,
        expected_role=expected_role,
        expected_paper_id=paper_id,
    )
    if errors:
        raise ValueError("Invalid review record: " + "; ".join(errors))

    manuscript = repo_root / str(
        metadata.get("manuscript_dir") or f"papers/{paper_id}/manuscript"
    )
    pdf = repo_root / str(
        metadata.get("latest_pdf") or f"papers/{paper_id}/manuscript/main.pdf"
    )
    main_tex = repo_root / str(
        metadata.get("latest_source") or f"papers/{paper_id}/manuscript/main.tex"
    )
    if not manuscript.is_dir() or not pdf.is_file() or not main_tex.is_file():
        raise FileNotFoundError(
            f"Canonical manuscript inputs are incomplete for {paper_id}"
        )
    current_snapshot = manuscript_snapshot_sha256(manuscript, pdf)
    review_metadata = review_payload["review_metadata"]
    if review_metadata["main_tex_sha256"] != sha256_file(main_tex):
        raise ValueError("Review main-TeX hash does not match the current manuscript")
    for key in (
        "manuscript_snapshot_sha256_before",
        "manuscript_snapshot_sha256_after",
    ):
        if review_metadata[key] != current_snapshot:
            raise ValueError(
                f"Review {key} does not match the current manuscript snapshot"
            )

    recommendations = review_payload["recommendations"]
    if expected_role == CS_TOP_TIER_REVIEWER_ROLE:
        high_standard_view = TOP_CONFERENCE_VIEW
        high_standard = recommendations[TOP_CONFERENCE_VIEW]["seven_point"]
    elif expected_role == MATERIALS_REVIEWER_ROLE:
        high_standard_view = LEADING_MATERIALS_JOURNALS_VIEW
        high_standard = recommendations[LEADING_MATERIALS_JOURNALS_VIEW]
    elif expected_role == PHYSICS_REVIEWER_ROLE:
        high_standard_view = LEADING_PHYSICS_JOURNALS_VIEW
        high_standard = recommendations[LEADING_PHYSICS_JOURNALS_VIEW]
    elif expected_role == QUANT_FINANCE_REVIEWER_ROLE:
        high_standard_view = LEADING_QUANT_FINANCE_JOURNALS_VIEW
        high_standard = recommendations[LEADING_QUANT_FINANCE_JOURNALS_VIEW]
    else:
        high_standard_view = FOUR_TOP_MATH_JOURNALS_VIEW
        high_standard = recommendations[FOUR_TOP_MATH_JOURNALS_VIEW]
    cas_zone_1 = recommendations[CAS_ZONE_1_JOURNAL_VIEW]
    scores = dict(review_payload["scores"])

    existing_release = metadata.get("writing_release")
    existing_release = existing_release if isinstance(existing_release, Mapping) else {}
    rounds = (
        int(existing_release.get("revision_rounds_completed") or 0)
        if revision_rounds is None
        else revision_rounds
    )
    original_metadata = dict(metadata)
    metadata["ara_llm_self_review"] = {
        "schema_version": review_payload["schema_version"],
        "score": scores["overall"],
        "scale": 10,
        "scores": scores,
        "reviewer_role": review_metadata["reviewer_role"],
        "rubric_id": review_metadata["rubric_id"],
        "high_standard_view": high_standard_view,
        "high_standard_decision": high_standard["decision"],
        "high_standard_confidence": high_standard["confidence"],
        "cas_zone_1_decision": cas_zone_1["decision"],
        "cas_zone_1_confidence": cas_zone_1["confidence"],
        "cas_zone_1_basis": dict(review_metadata["cas_zone_1_basis"]),
        "model": review_metadata["model"],
        "reasoning_effort": review_metadata["reasoning_effort"],
        "reviewed_at": review_metadata["reviewed_at_utc"],
        "manuscript_snapshot_sha256": current_snapshot,
        "review_content_sha256": _review_workspace_fingerprints(
            paper_id, metadata, repo_root
        )["review_content_sha256"],
        "not_external_peer_review": True,
        "simulated_venue_decisions": True,
        "review_panel": dict(review_metadata["review_panel"]),
        "source": review_relative,
    }
    if expected_role == PHYSICS_REVIEWER_ROLE:
        venue_reviews = high_standard.get("venue_reviews")
        venue_reviews = venue_reviews if isinstance(venue_reviews, Mapping) else {}
        metadata["ara_llm_self_review"].update(
            {
                "high_standard_score": high_standard.get("score"),
                "high_standard_best_fit_venue": high_standard.get("best_fit_venue"),
                "high_standard_venue_reviews": {
                    venue: dict(venue_reviews.get(venue, {}))
                    for venue in PHYSICS_HIGHEST_TIER_VENUES
                },
            }
        )
    write_paper_metadata(paper_id, metadata, repo_root)
    try:
        gate = record_quality_gate(
            paper_id,
            venue_type=venue_type,
            score=scores["overall"],
            decision=cas_zone_1["decision"],
            revision_rounds=rounds,
            unresolved_blockers=review_payload["unresolved_blockers"],
            review=review_relative,
            root=repo_root,
        )
    except Exception:
        write_paper_metadata(paper_id, original_metadata, repo_root)
        raise
    return {
        "paper_id": paper_id,
        "review": review_relative,
        "reviewer_role": expected_role,
        "scores": scores,
        "high_standard_view": high_standard_view,
        "high_standard_decision": high_standard["decision"],
        "cas_zone_1_decision": cas_zone_1["decision"],
        "quality_gate": gate,
    }


def reuse_review_for_metadata_only_revision(
    paper_id: str,
    *,
    root: str | Path,
) -> dict[str, Any]:
    """Carry a passing review across a narrowly verified metadata-only revision.

    The operation never calls an LLM and never changes a score.  It compares a
    baseline captured by :func:`start_revision` with the current manuscript and
    support source fingerprints, reruns deterministic gates, then binds the old
    review to the new immutable release snapshot.  Unknown or scientific
    changes fail closed.
    """

    repo_root = Path(root).resolve()
    payload = load_paper_metadata(paper_id, repo_root)
    release = payload.get("writing_release")
    release = release if isinstance(release, Mapping) else {}
    candidate = release.get("review_carry_forward")
    if not isinstance(candidate, Mapping):
        raise ValueError(
            "No verified review carry-forward baseline is available; start the "
            "revision from a current ready gate or run a fresh review"
        )
    if candidate.get("schema_version") != REVIEW_CARRY_FORWARD_SCHEMA_VERSION:
        raise ValueError("Unsupported review carry-forward baseline")
    source_release = candidate.get("source_release")
    if (
        not isinstance(source_release, Mapping)
        or source_release.get("status") != "ready"
    ):
        raise ValueError("Review carry-forward baseline is not a passing quality gate")

    current = _review_workspace_fingerprints(paper_id, payload, repo_root)
    comparisons = (
        "review_content_sha256",
        "registry_review_content_sha256",
        "support_sources_sha256",
    )
    changed = [key for key in comparisons if candidate.get(key) != current.get(key)]
    if changed:
        labels = {
            "review_content_sha256": "manuscript scientific/textual sources",
            "registry_review_content_sha256": "review-significant registry metadata",
            "support_sources_sha256": "support evidence sources",
        }
        raise ValueError(
            "Fresh scientific review required; changed: "
            + ", ".join(labels[key] for key in changed)
        )

    canonical_pdf = repo_root / str(
        payload.get("latest_pdf") or f"papers/{paper_id}/manuscript/main.pdf"
    )
    if not canonical_pdf.is_file():
        raise ValueError("Metadata-only review reuse requires a rebuilt canonical PDF")

    support = payload.get("support")
    support = support if isinstance(support, Mapping) else {}
    publication = support.get("publication")
    publication = publication if isinstance(publication, Mapping) else {}
    package_sha256 = str(publication.get("package_sha256") or "")
    zenodo = publication.get("zenodo")
    zenodo = zenodo if isinstance(zenodo, Mapping) else {}
    package_version = str(zenodo.get("version") or "")
    current_version = str(payload.get("version") or "1.0.0")
    if package_sha256 and package_version and package_version != current_version:
        raise ValueError(
            "Support package is still bound to the previous paper version; run "
            "`zenodo prepare` before reusing the review"
        )

    support_audit = audit_manuscript_support(paper_id, root=repo_root)
    blockers = list(support_audit_blockers(support_audit))
    settings = load_registry(
        repo_root,
        include_local_repositories=False,
        paper_ids=[paper_id],
    )
    gate = settings.get("quality_gate")
    gate = gate if isinstance(gate, Mapping) else {}
    style_audit: dict[str, Any] | None = None
    if bool(gate.get("require_manuscript_style_check", False)):
        style_audit = audit_manuscript_style(
            paper_id,
            root=repo_root,
            require_ai_declaration=bool(gate.get("require_ai_use_declaration", True)),
        )
        blockers.extend(
            blocker
            for blocker in manuscript_style_blockers(style_audit)
            if blocker not in blockers
        )
    if blockers:
        raise ValueError(
            "Metadata-only review reuse failed deterministic checks: "
            + "; ".join(blockers)
        )

    minimum_score = float(gate.get("minimum_score", 5.0))
    try:
        score = float(source_release.get("score"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Source review score is missing") from exc
    if score < minimum_score:
        raise ValueError("Source review no longer meets the configured score threshold")
    venue_type = str(
        source_release.get("venue_type") or payload.get("venue_type") or ""
    )
    decision_standard = str(gate.get("decision_standard") or venue_type)
    decision = str(source_release.get("decision") or "")
    allowed = decisions_for_standard(decision_standard, venue_type=venue_type)
    minimum_decision = str(
        gate.get(
            "cas_zone_1_minimum_decision"
            if decision_standard == CAS_ZONE_1_JOURNAL_VIEW
            else (
                "conference_minimum_decision"
                if decision_standard == "conference"
                else "journal_minimum_decision"
            ),
            "minor_revision",
        )
    )
    if (
        decision not in allowed
        or minimum_decision not in allowed
        or not decision_meets_standard_threshold(
            decision,
            minimum_decision,
            decision_standard,
            venue_type=venue_type,
        )
    ):
        raise ValueError("Source review no longer meets the configured decision threshold")

    reused_at = _now()
    refreshed = deepcopy(dict(source_release))
    refreshed.update(
        {
            "status": "ready",
            "target_score": minimum_score,
            "decision_standard": decision_standard,
            "minimum_decision": minimum_decision,
            "manuscript_snapshot_sha256": current["manuscript_snapshot_sha256"],
            "review_content_sha256": current["review_content_sha256"],
            "registry_review_content_sha256": current[
                "registry_review_content_sha256"
            ],
            "manuscript_version": current_version,
            "review_carry_forward": deepcopy(dict(candidate)),
            "review_reuse": {
                "classification": "author_or_release_metadata_only",
                "carried_forward_at": reused_at,
                "source_reviewed_at": source_release.get("reviewed_at"),
                "source_manuscript_snapshot_sha256": candidate.get(
                    "manuscript_snapshot_sha256"
                ),
                "current_manuscript_snapshot_sha256": current[
                    "manuscript_snapshot_sha256"
                ],
                "review_content_sha256": current["review_content_sha256"],
                "support_sources_sha256": current["support_sources_sha256"],
                "llm_review_rerun": False,
                "deterministic_checks_rerun": True,
            },
        }
    )
    refreshed.pop("unresolved_review_blockers", None)
    if current["support_sources_sha256"] is None:
        refreshed.pop("support_sources_sha256", None)
    else:
        refreshed["support_sources_sha256"] = current["support_sources_sha256"]
    if re.fullmatch(r"[0-9a-f]{64}", package_sha256):
        refreshed["support_package_sha256"] = package_sha256
    else:
        refreshed.pop("support_package_sha256", None)
    payload["writing_release"] = refreshed
    review_projection = payload.get("ara_llm_self_review")
    if isinstance(review_projection, Mapping):
        projected = deepcopy(dict(review_projection))
        projected.setdefault(
            "review_content_sha256", candidate.get("review_content_sha256")
        )
        projected["last_reused_at"] = reused_at
        projected["last_reused_for_manuscript_snapshot_sha256"] = current[
            "manuscript_snapshot_sha256"
        ]
        payload["ara_llm_self_review"] = projected
    payload["status_updated_at"] = reused_at
    write_paper_metadata(paper_id, payload, repo_root)
    return {
        "paper_id": paper_id,
        "status": "ready",
        "classification": "author_or_release_metadata_only",
        "llm_review_rerun": False,
        "manuscript_snapshot_sha256": current["manuscript_snapshot_sha256"],
        "review_content_sha256": current["review_content_sha256"],
        "support_sources_sha256": current["support_sources_sha256"],
        "support_package_sha256": refreshed.get("support_package_sha256"),
        "support_materials_audit": support_audit,
        "manuscript_style_audit": style_audit,
    }


def validate_repository(root: str | Path, *, settings: str | Path | None = None) -> dict[str, Any]:
    repo_root = Path(root).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    try:
        config = load_registry(repo_root, settings=settings)
        inventory = build_inventory(repo_root, config=config)
    except (OSError, ValueError) as exc:
        return {"valid": False, "papers": 0, "errors": [str(exc)], "warnings": []}
    warnings.extend(inventory.get("warnings", []))
    for workspace, paper in config.get("papers", {}).items():
        paper_id = str(paper.get("paper_id") or "")
        if not (repo_root / workspace / "manuscript").is_dir():
            errors.append(f"{paper_id}: manuscript workspace is missing")
        bundles = paper.get("evidence_bundles", [])
        if not isinstance(bundles, list):
            errors.append(f"{paper_id}: evidence_bundles must be a list")
            continue
        for index, bundle in enumerate(bundles):
            if not isinstance(bundle, Mapping):
                errors.append(f"{paper_id}: evidence_bundles[{index}] must be an object")
                continue
            for field in ("repository", "commit", "path"):
                if not str(bundle.get(field) or "").strip():
                    errors.append(f"{paper_id}: evidence_bundles[{index}].{field} is required")
            commit = str(bundle.get("commit") or "")
            if commit and not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
                errors.append(f"{paper_id}: evidence_bundles[{index}].commit must be a full Git commit")
            manifest_hash = str(bundle.get("manifest_sha256") or "")
            if not re.fullmatch(r"[0-9a-fA-F]{64}", manifest_hash):
                errors.append(f"{paper_id}: evidence_bundles[{index}].manifest_sha256 is required")
    return {
        "valid": not errors,
        "papers": inventory.get("summary", {}).get("total", 0),
        "errors": errors,
        "warnings": warnings,
        "inventory_warnings": len(inventory.get("warnings", [])),
    }
