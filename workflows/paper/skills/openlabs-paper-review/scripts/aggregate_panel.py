#!/usr/bin/env python3
"""Mechanically aggregate three skill-authored independent review records.

This helper never judges a manuscript and never derives a score from manuscript
features.  It verifies three v2 records, takes the required score and decision
medians, preserves every distinct finding and blocker, binds the source hashes,
and writes a v3 panel record for the coordinating context to inspect.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKFLOW_ROOT = Path(__file__).resolve().parents[3]
if str(WORKFLOW_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_ROOT))

from paper_writing.registry import load_paper_metadata, repository_root  # noqa: E402
from paper_writing.review import (  # noqa: E402
    CAS_ZONE_1_JOURNAL_VIEW,
    CONFERENCE_DECISIONS,
    FOUR_TOP_MATH_JOURNALS_VIEW,
    INDIVIDUAL_REVIEW_SCHEMA_VERSION,
    JOURNAL_DECISIONS,
    MATHEMATICS_REVIEWER_ROLE,
    LEADING_MATERIALS_JOURNALS_VIEW,
    MATERIALS_REVIEWER_ROLE,
    REVIEW_DECISION_AGGREGATION,
    REVIEW_PANEL_SIZE,
    REVIEW_SCHEMA_VERSION,
    REVIEW_SCORE_AGGREGATION,
    TOP_CONFERENCE_VIEW,
    reviewer_role_for_domain,
    validate_review_panel_files,
    validate_review_record,
)


SCORE_KEYS = ("clarity", "soundness", "significance", "novelty", "overall")
CONFIDENCE_ORDER = ("high", "medium", "low")


def _median(values: list[int]) -> int:
    return sorted(values)[len(values) // 2]


def _decision_median(values: list[str], order: tuple[str, ...]) -> str:
    return order[_median([order.index(value) for value in values])]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _distinct_strings(reviews: list[dict[str, Any]], key: str) -> list[str]:
    result: list[str] = []
    for review in reviews:
        for value in review.get(key, []):
            if isinstance(value, str) and value not in result:
                result.append(value)
    return result


def _distinct_objects(reviews: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    fingerprints: set[str] = set()
    for review in reviews:
        for value in review.get(key, []):
            if not isinstance(value, dict):
                continue
            fingerprint = json.dumps(value, ensure_ascii=False, sort_keys=True)
            if fingerprint not in fingerprints:
                fingerprints.add(fingerprint)
                result.append(deepcopy(value))
    return result


def _section_feedback(reviews: list[dict[str, Any]]) -> dict[str, str]:
    by_section: dict[str, list[str]] = {}
    for index, review in enumerate(reviews, start=1):
        feedback = review.get("section_feedback")
        if not isinstance(feedback, dict):
            continue
        for section, value in feedback.items():
            if not isinstance(section, str) or not isinstance(value, str):
                continue
            labelled = f"Reviewer-{index}: {value}"
            if labelled not in by_section.setdefault(section, []):
                by_section[section].append(labelled)
    return {section: " ".join(values) for section, values in by_section.items()}


def _least_confident(entries: list[dict[str, Any]]) -> str:
    return max(
        (str(entry["confidence"]) for entry in entries),
        key=CONFIDENCE_ORDER.index,
    )


def _aggregate_recommendation(
    entries: list[dict[str, Any]], *, order: tuple[str, ...]
) -> dict[str, str]:
    decisions = [str(entry["decision"]) for entry in entries]
    decision = _decision_median(decisions, order)
    source = next(entry for entry in entries if entry["decision"] == decision)
    rationale = (
        f"Ordinal median of the three independent decisions "
        f"({', '.join(decisions)}). {source['rationale']}"
    )
    return {
        "decision": decision,
        "confidence": _least_confident(entries),
        "rationale": rationale,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aggregate exactly three independent OpenLabs v2 reviews into a v3 panel."
    )
    parser.add_argument("--paper-id", required=True)
    parser.add_argument("--review-dir", required=True)
    parser.add_argument("--output", default="review.json")
    parser.add_argument(
        "--objective-audit",
        action="append",
        default=[],
        help="repository-relative objective audit receipt shared with all three reviewers",
    )
    parser.add_argument("--root", default=str(repository_root()))
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    review_dir = Path(args.review_dir)
    if not review_dir.is_absolute():
        review_dir = root / review_dir
    review_dir = review_dir.resolve()
    output = Path(args.output)
    if not output.is_absolute():
        output = review_dir / output
    output = output.resolve()
    if output.exists() and not args.force:
        raise FileExistsError(f"refusing to overwrite {output}; pass --force explicitly")
    if output.parent != review_dir:
        raise ValueError("panel output must be stored beside the three reviewer records")

    metadata = load_paper_metadata(args.paper_id, root)
    expected_role = reviewer_role_for_domain(metadata.get("domain"))
    reviews: list[dict[str, Any]] = []
    records: list[dict[str, str]] = []
    common: dict[str, str] | None = None
    for index in range(1, REVIEW_PANEL_SIZE + 1):
        reviewer_id = f"reviewer-{index}"
        source_path = review_dir / f"{reviewer_id}.json"
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        errors = validate_review_record(
            payload,
            expected_role=expected_role,
            expected_paper_id=args.paper_id,
        )
        if errors:
            raise ValueError(f"invalid {reviewer_id}: {'; '.join(errors)}")
        if payload.get("schema_version") != INDIVIDUAL_REVIEW_SCHEMA_VERSION:
            raise ValueError(f"{reviewer_id} must use the v2 individual schema")
        review_metadata = payload["review_metadata"]
        if review_metadata.get("panel_reviewer_id") != reviewer_id:
            raise ValueError(f"{reviewer_id} has a mismatched panel_reviewer_id")
        if review_metadata.get("independent_context") is not True:
            raise ValueError(f"{reviewer_id} is not marked independent")
        if review_metadata.get("prior_reviews_hidden") is not True:
            raise ValueError(f"{reviewer_id} did not hide prior reviews")
        current = {
            key: review_metadata[key]
            for key in (
                "main_tex_sha256",
                "manuscript_snapshot_sha256_before",
                "manuscript_snapshot_sha256_after",
            )
        }
        if common is None:
            common = current
        elif current != common:
            raise ValueError("reviewer records do not describe one common frozen snapshot")
        reviews.append(payload)
        records.append(
            {
                "reviewer_id": reviewer_id,
                "source": source_path.relative_to(root).as_posix(),
                "sha256": _sha256(source_path),
            }
        )

    assert common is not None
    objective_audits: list[dict[str, str]] = []
    for value in args.objective_audit:
        source_path = Path(value)
        if not source_path.is_absolute():
            source_path = root / source_path
        source_path = source_path.resolve()
        try:
            source = source_path.relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError("objective audit must stay inside the Writing repository") from exc
        receipt = json.loads(source_path.read_text(encoding="utf-8"))
        objective_audits.append(
            {
                "kind": "lean_mathlib",
                "source": source,
                "sha256": _sha256(source_path),
                "status": str(receipt.get("status")),
                "manuscript_snapshot_sha256": str(
                    receipt.get("manuscript_snapshot_sha256")
                ),
                "support_package_sha256": str(receipt.get("support_package_sha256")),
            }
        )
    panel = deepcopy(reviews[1])
    panel["schema_version"] = REVIEW_SCHEMA_VERSION
    panel["scores"] = {
        key: _median([int(review["scores"][key]) for review in reviews])
        for key in SCORE_KEYS
    }
    panel["strengths"] = _distinct_strings(reviews, "strengths")
    panel["weaknesses"] = _distinct_strings(reviews, "weaknesses")
    panel["section_feedback"] = _section_feedback(reviews)
    panel["required_changes"] = _distinct_strings(reviews, "required_changes")
    panel["change_requests"] = _distinct_objects(reviews, "change_requests")
    blockers = _distinct_strings(reviews, "unresolved_blockers")
    panel["unresolved_blockers"] = blockers

    recommendations = [review["recommendations"] for review in reviews]
    if expected_role == MATHEMATICS_REVIEWER_ROLE:
        high_entries = [entry[FOUR_TOP_MATH_JOURNALS_VIEW] for entry in recommendations]
        final_recommendations = {
            FOUR_TOP_MATH_JOURNALS_VIEW: _aggregate_recommendation(
                high_entries, order=JOURNAL_DECISIONS
            )
        }
    elif expected_role == MATERIALS_REVIEWER_ROLE:
        high_entries = [entry[LEADING_MATERIALS_JOURNALS_VIEW] for entry in recommendations]
        final_recommendations = {
            LEADING_MATERIALS_JOURNALS_VIEW: _aggregate_recommendation(
                high_entries, order=JOURNAL_DECISIONS
            )
        }
    else:
        high_entries = [
            entry[TOP_CONFERENCE_VIEW]["seven_point"] for entry in recommendations
        ]
        final_recommendations = {
            TOP_CONFERENCE_VIEW: {
                "seven_point": _aggregate_recommendation(
                    high_entries, order=CONFERENCE_DECISIONS
                )
            }
        }
    cas_entries = [entry[CAS_ZONE_1_JOURNAL_VIEW] for entry in recommendations]
    final_recommendations[CAS_ZONE_1_JOURNAL_VIEW] = _aggregate_recommendation(
        cas_entries, order=JOURNAL_DECISIONS
    )
    panel["recommendations"] = final_recommendations

    text_ready = all(
        review["publishability_summary"].get("text_ready") is True for review in reviews
    )
    scientific_ready = all(
        review["publishability_summary"].get("scientific_ready") is True
        for review in reviews
    )
    panel["publishability_summary"] = {
        "text_ready": text_ready and not blockers,
        "scientific_ready": scientific_ready and not blockers,
        "blocking_reason": " ".join(blockers),
    }

    panel_metadata = panel["review_metadata"]
    for key in ("panel_reviewer_id", "independent_context", "prior_reviews_hidden"):
        panel_metadata.pop(key, None)
    panel_metadata.update(
        {
            "model": "three-agent-median-panel",
            "reasoning_effort": (
                "mechanical coordinatewise and ordinal median aggregation; "
                "distinct findings and blockers preserved"
            ),
            "reviewed_at_utc": datetime.now(timezone.utc).isoformat(),
            **common,
            "manuscript_unchanged": True,
            "review_panel": {
                "panel_size": REVIEW_PANEL_SIZE,
                "score_aggregation": REVIEW_SCORE_AGGREGATION,
                "decision_aggregation": REVIEW_DECISION_AGGREGATION,
                "parallel_execution": True,
                "independent_contexts": True,
                "prior_reviews_hidden": True,
                "reviewer_records": records,
                **(
                    {"shared_objective_audits": objective_audits}
                    if objective_audits
                    else {}
                ),
            },
        }
    )

    output.write_text(json.dumps(panel, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    errors = validate_review_panel_files(
        panel,
        review_path=output,
        repo_root=root,
        expected_role=expected_role,
        expected_paper_id=args.paper_id,
    )
    if errors:
        raise ValueError("generated invalid panel: " + "; ".join(errors))
    print(
        json.dumps(
            {
                "paper_id": args.paper_id,
                "output": output.relative_to(root).as_posix(),
                "scores": panel["scores"],
                "recommendations": panel["recommendations"],
                "unresolved_blockers": blockers,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
