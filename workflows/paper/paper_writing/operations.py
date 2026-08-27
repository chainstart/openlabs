"""Small Git-friendly operations for evidence-backed manuscript workspaces."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from paper_writing.identifiers import (
    DOMAIN_SCOPED_PAPER_ID_PATTERN,
    domain_scoped_parts,
    work_id_from_paper_id,
)
from paper_writing.inventory import build_inventory
from paper_writing.registry import (
    load_paper_metadata,
    load_registry,
    paper_metadata_path,
    write_paper_metadata,
)
from paper_writing.review import (
    CAS_ZONE_1_JOURNAL_VIEW,
    CS_TOP_TIER_REVIEWER_ROLE,
    FOUR_TOP_MATH_JOURNALS_VIEW,
    LEADING_MATERIALS_JOURNALS_VIEW,
    LEADING_QUANT_FINANCE_JOURNALS_VIEW,
    MATERIALS_REVIEWER_ROLE,
    QUANT_FINANCE_REVIEWER_ROLE,
    TOP_CONFERENCE_VIEW,
    decision_meets_standard_threshold,
    decisions_for_standard,
    reviewer_role_for_domain,
    validate_review_panel_files,
)
from paper_writing.support_citations import audit_manuscript_support, support_audit_blockers


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


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
    if not DOMAIN_SCOPED_PAPER_ID_PATTERN.fullmatch(paper_id):
        raise ValueError(
            "New paper_id must use YYYYMMDD-domain-subdomain-keywords, for "
            "example 20260802-math-graph-opg1757-active-newton"
        )
    expected = f"{created_at.replace('-', '')}-"
    if not paper_id.startswith(expected):
        raise ValueError(f"paper_id must start with {expected}")
    parts = domain_scoped_parts(paper_id)
    if parts is None:  # Guard the invariant established by the format check above.
        raise AssertionError("domain-scoped paper_id did not parse")
    if parts["domain"] != domain:
        raise ValueError(
            f"paper_id domain segment {parts['domain']!r} must match domain {domain!r}"
        )
    if parts["subdomain"] != subdomain:
        raise ValueError(
            "paper_id subdomain segment "
            f"{parts['subdomain']!r} must match subdomain {subdomain!r}"
        )
    path = paper_metadata_path(paper_id, repo_root)
    if path.exists() or (repo_root / "papers" / paper_id).exists():
        raise FileExistsError(paper_id)
    workspace = repo_root / "papers" / paper_id
    for folder in ("manuscript", "evidence", "revisions", "support-materials"):
        (workspace / folder).mkdir(parents=True, exist_ok=True)
    (workspace / "manuscript" / "main.tex").write_text(
        "\\documentclass{article}\n\\title{" + title + "}\n\\author{}\n"
        "\\begin{document}\n\\maketitle\n\\begin{abstract}\n\\end{abstract}\n\\end{document}\n",
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
        "support": {"publication": {"mode": "zenodo_only", "status": "planned"}},
        "status_updated_at": _now(),
    }
    if target_journal and target_journal.strip():
        payload["target_journal"] = target_journal.strip()
    return write_paper_metadata(paper_id, payload, repo_root)


def start_revision(paper_id: str, reason: str, *, root: str | Path) -> dict[str, Any]:
    repo_root = Path(root).resolve()
    payload = load_paper_metadata(paper_id, repo_root)
    revision_root = repo_root / "papers" / paper_id / "revisions"
    revision_root.mkdir(parents=True, exist_ok=True)
    existing = [int(match.group(1)) for path in revision_root.glob("round-*.md") if (match := re.fullmatch(r"round-(\d+)\.md", path.name))]
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
    payload["writing_release"] = {
        "status": "draft",
        "invalidated_at": changed_at,
        "invalidated_reason": "revision_started",
    }
    payload["status_updated_at"] = changed_at
    write_paper_metadata(paper_id, payload, repo_root)
    return {"paper_id": paper_id, "round": round_number, "version": new_version, "file": str(path.relative_to(repo_root))}


def record_quality_gate(
    paper_id: str,
    *,
    venue_type: str,
    score: float,
    decision: str,
    revision_rounds: int,
    unresolved_blockers: Iterable[str] = (),
    root: str | Path,
) -> dict[str, Any]:
    """Record and deterministically evaluate an LLM review result.

    This does not run an LLM.  Codex or another reviewer supplies the assessment;
    the function applies the repository's stable pass/freeze thresholds.
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

    settings = load_registry(repo_root)
    gate = settings.get("quality_gate", {})
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

    payload = load_paper_metadata(paper_id, repo_root)
    from paper_writing.handoff import manuscript_snapshot_sha256

    manuscript = repo_root / str(
        payload.get("manuscript_dir") or f"papers/{paper_id}/manuscript"
    )
    canonical_pdf = repo_root / str(
        payload.get("latest_pdf") or f"papers/{paper_id}/manuscript/main.pdf"
    )
    if not manuscript.is_dir():
        raise FileNotFoundError(manuscript)
    snapshot_sha256 = manuscript_snapshot_sha256(manuscript, canonical_pdf)
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
        "manuscript_version": str(payload.get("version") or "1.0.0"),
    }
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
        "support_package_sha256": release_record.get("support_package_sha256"),
        "support_materials_audit": support_audit,
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
        "not_external_peer_review": True,
        "simulated_venue_decisions": True,
        "review_panel": dict(review_metadata["review_panel"]),
        "source": review_relative,
    }
    write_paper_metadata(paper_id, metadata, repo_root)
    try:
        gate = record_quality_gate(
            paper_id,
            venue_type=venue_type,
            score=scores["overall"],
            decision=cas_zone_1["decision"],
            revision_rounds=rounds,
            unresolved_blockers=review_payload["unresolved_blockers"],
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
