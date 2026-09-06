#!/usr/bin/env python3
"""Validate the field-recognized physics problem portfolio."""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCHEMA_VERSION = "openlabs.physics_problem_portfolio.v1"
POLICY_VERSION = "openlabs.physics_problem_selection.v2"
SUBPROBLEM_SCHEMA_VERSION = "openlabs.physics_recognized_subproblems.v1"
SUBPROBLEM_POLICY_VERSION = "openlabs.physics_subproblem_selection.v1"
PROBLEM_ID = re.compile(r"PHY-\d{3}\Z")
SUBPROBLEM_ID = re.compile(r"PHY-\d{3}-SP-\d{2}\Z")
SOURCE_ID = re.compile(r"SRC-[A-Z0-9-]+\Z")
LEGACY_ID = re.compile(r"TP-\d{3}\Z")
ALLOWED_EVIDENCE_KINDS = {
    "prize_problem",
    "official_strategy",
    "decadal_survey",
    "community_frontier_report",
}
SUBPROBLEM_EVIDENCE_KINDS = ALLOWED_EVIDENCE_KINDS | {"community_program_report"}
INSTITUTIONAL_EVIDENCE_KINDS = {
    "prize_problem",
    "official_strategy",
    "decadal_survey",
}


def _iso_date(value: Any, field: str, errors: list[str]) -> date | None:
    if not isinstance(value, str):
        errors.append(f"{field} must be an ISO date")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.append(f"{field} must be an ISO date")
        return None


def _nonempty_text(value: Any, field: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{field} must be non-empty text")


def _nonempty_text_list(value: Any, field: str, errors: list[str]) -> None:
    if not isinstance(value, list) or not value:
        errors.append(f"{field} must be a non-empty list")
        return
    for index, item in enumerate(value):
        _nonempty_text(item, f"{field}[{index}]", errors)


def validate_portfolio(data: Any) -> list[str]:
    """Return validation errors without mutating the supplied portfolio."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["portfolio root must be an object"]

    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if data.get("selection_policy_version") != POLICY_VERSION:
        errors.append(f"selection_policy_version must be {POLICY_VERSION}")
    audit_date = _iso_date(data.get("audited_at"), "audited_at", errors)
    if data.get("status") != "active_portfolio_execution_paused":
        errors.append("portfolio must remain execution-paused until a work package is approved")

    problems = data.get("problems")
    if not isinstance(problems, list) or not problems:
        errors.append("problems must be a non-empty list")
        return errors

    seen_ids: set[str] = set()
    for index, problem in enumerate(problems):
        prefix = f"problems[{index}]"
        if not isinstance(problem, dict):
            errors.append(f"{prefix} must be an object")
            continue
        problem_id = problem.get("problem_id")
        if not isinstance(problem_id, str) or not PROBLEM_ID.fullmatch(problem_id):
            errors.append(f"{prefix}.problem_id must match PHY-NNN")
        elif problem_id in seen_ids:
            errors.append(f"duplicate problem_id {problem_id}")
        else:
            seen_ids.add(problem_id)

        if problem.get("status") != "active":
            errors.append(f"{prefix}.status must be active")
        for field in ("title", "open_question", "field_level_impact"):
            _nonempty_text(problem.get(field), f"{prefix}.{field}", errors)
        for field in ("recognized_subproblem_domains", "excluded_as_standalone"):
            _nonempty_text_list(problem.get(field), f"{prefix}.{field}", errors)

        legacy = problem.get("legacy_alignment")
        if not isinstance(legacy, list):
            errors.append(f"{prefix}.legacy_alignment must be a list")
        else:
            for legacy_id in legacy:
                if not isinstance(legacy_id, str) or not LEGACY_ID.fullmatch(legacy_id):
                    errors.append(f"{prefix}.legacy_alignment contains invalid ID {legacy_id!r}")

        evidence = problem.get("recognition_evidence")
        if not isinstance(evidence, list) or len(evidence) < 2:
            errors.append(f"{prefix} requires at least 2 recognition evidence records")
            continue
        authorities: set[str] = set()
        kinds: set[str] = set()
        for evidence_index, record in enumerate(evidence):
            evidence_prefix = f"{prefix}.recognition_evidence[{evidence_index}]"
            if not isinstance(record, dict):
                errors.append(f"{evidence_prefix} must be an object")
                continue
            authority = record.get("authority")
            _nonempty_text(authority, f"{evidence_prefix}.authority", errors)
            if isinstance(authority, str) and authority.strip():
                authorities.add(authority.strip())
            kind = record.get("kind")
            if kind not in ALLOWED_EVIDENCE_KINDS:
                errors.append(f"{evidence_prefix}.kind is not authoritative portfolio evidence")
            else:
                kinds.add(kind)
            url = record.get("url")
            if (
                not isinstance(url, str)
                or urlparse(url).scheme != "https"
                or not urlparse(url).netloc
            ):
                errors.append(f"{evidence_prefix}.url must be an absolute HTTPS URL")
            accessed = _iso_date(
                record.get("accessed_at"), f"{evidence_prefix}.accessed_at", errors
            )
            if audit_date is not None and accessed is not None and accessed > audit_date:
                errors.append(f"{evidence_prefix}.accessed_at cannot be after audited_at")
        if len(authorities) < 2:
            errors.append(f"{prefix} requires recognition from 2 independent authorities")
        if not (kinds & INSTITUTIONAL_EVIDENCE_KINDS):
            errors.append(
                f"{prefix} requires a prize, official strategy, or decadal-survey source"
            )

    return errors


def validate_subproblems(data: Any, portfolio: Any) -> list[str]:
    """Validate recognized subproblems against their active mother problems."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["subproblem registry root must be an object"]
    if not isinstance(portfolio, dict):
        return ["parent portfolio root must be an object"]

    if data.get("schema_version") != SUBPROBLEM_SCHEMA_VERSION:
        errors.append(f"subproblem schema_version must be {SUBPROBLEM_SCHEMA_VERSION}")
    if data.get("policy_version") != SUBPROBLEM_POLICY_VERSION:
        errors.append(f"subproblem policy_version must be {SUBPROBLEM_POLICY_VERSION}")
    audit_date = _iso_date(data.get("audited_at"), "subproblems.audited_at", errors)
    if data.get("status") != "recognized_subproblem_portfolio_execution_paused":
        errors.append("subproblem registry must remain execution-paused")
    if data.get("parent_portfolio") != "portfolio.json":
        errors.append("subproblem parent_portfolio must be portfolio.json")
    if data.get("required_resolution_significance") != "prl_class_scientific_gate":
        errors.append("subproblems require the PRL-class scientific significance gate")
    venue_claim = data.get("venue_claim")
    _nonempty_text(venue_claim, "subproblems.venue_claim", errors)
    if isinstance(venue_claim, str) and "No venue is guaranteed" not in venue_claim:
        errors.append("venue_claim must explicitly state that no venue is guaranteed")

    parent_ids = {
        problem.get("problem_id")
        for problem in portfolio.get("problems", [])
        if isinstance(problem, dict) and problem.get("status") == "active"
    }
    sources = data.get("sources")
    source_map: dict[str, dict[str, Any]] = {}
    if not isinstance(sources, list) or not sources:
        errors.append("subproblems.sources must be a non-empty list")
    else:
        for index, source in enumerate(sources):
            prefix = f"subproblems.sources[{index}]"
            if not isinstance(source, dict):
                errors.append(f"{prefix} must be an object")
                continue
            source_id = source.get("source_id")
            if not isinstance(source_id, str) or not SOURCE_ID.fullmatch(source_id):
                errors.append(f"{prefix}.source_id must match SRC-...")
            elif source_id in source_map:
                errors.append(f"duplicate source_id {source_id}")
            else:
                source_map[source_id] = source
            _nonempty_text(source.get("authority"), f"{prefix}.authority", errors)
            if source.get("kind") not in SUBPROBLEM_EVIDENCE_KINDS:
                errors.append(f"{prefix}.kind is not recognized evidence")
            url = source.get("url")
            if (
                not isinstance(url, str)
                or urlparse(url).scheme != "https"
                or not urlparse(url).netloc
            ):
                errors.append(f"{prefix}.url must be an absolute HTTPS URL")
            accessed = _iso_date(
                source.get("accessed_at"), f"{prefix}.accessed_at", errors
            )
            if audit_date is not None and accessed is not None and accessed > audit_date:
                errors.append(f"{prefix}.accessed_at cannot be after audited_at")

    subproblems = data.get("subproblems")
    if not isinstance(subproblems, list) or not subproblems:
        errors.append("subproblems.subproblems must be a non-empty list")
        return errors

    seen_ids: set[str] = set()
    parent_counts: dict[str, int] = {str(parent_id): 0 for parent_id in parent_ids}
    for index, subproblem in enumerate(subproblems):
        prefix = f"subproblems.subproblems[{index}]"
        if not isinstance(subproblem, dict):
            errors.append(f"{prefix} must be an object")
            continue
        subproblem_id = subproblem.get("subproblem_id")
        if not isinstance(subproblem_id, str) or not SUBPROBLEM_ID.fullmatch(subproblem_id):
            errors.append(f"{prefix}.subproblem_id must match PHY-NNN-SP-NN")
        elif subproblem_id in seen_ids:
            errors.append(f"duplicate subproblem_id {subproblem_id}")
        else:
            seen_ids.add(subproblem_id)
        parent_id = subproblem.get("parent_problem_id")
        if parent_id not in parent_ids:
            errors.append(f"{prefix}.parent_problem_id is not an active mother problem")
        else:
            parent_counts[str(parent_id)] += 1
            if isinstance(subproblem_id, str) and not subproblem_id.startswith(
                f"{parent_id}-SP-"
            ):
                errors.append(f"{prefix}.subproblem_id does not match its parent")
        if subproblem.get("status") != "recognized_open":
            errors.append(f"{prefix}.status must be recognized_open")
        if subproblem.get("work_package_status") != "unselected":
            errors.append(f"{prefix}.work_package_status must remain unselected")
        for field in ("title", "open_question"):
            _nonempty_text(subproblem.get(field), f"{prefix}.{field}", errors)
        for field in ("decisive_resolution", "excluded_outputs"):
            values = subproblem.get(field)
            _nonempty_text_list(values, f"{prefix}.{field}", errors)
            if isinstance(values, list) and len(values) < 2:
                errors.append(f"{prefix}.{field} requires at least 2 entries")

        source_ids = subproblem.get("recognition_source_ids")
        if not isinstance(source_ids, list) or len(source_ids) < 2:
            errors.append(f"{prefix} requires at least 2 recognition sources")
            continue
        if any(not isinstance(source_id, str) for source_id in source_ids):
            errors.append(f"{prefix}.recognition_source_ids must contain strings")
            continue
        records = [source_map.get(source_id) for source_id in source_ids]
        unknown = [
            source_id
            for source_id, record in zip(source_ids, records, strict=True)
            if record is None
        ]
        if unknown:
            errors.append(f"{prefix} references unknown sources {unknown}")
            continue
        authorities = {str(record.get("authority")) for record in records if record}
        kinds = {record.get("kind") for record in records if record}
        if len(authorities) < 2:
            errors.append(f"{prefix} requires 2 independent recognition authorities")
        if not (kinds & INSTITUTIONAL_EVIDENCE_KINDS):
            errors.append(f"{prefix} requires an official, decadal, or prize source")

    missing_parents = sorted(parent_id for parent_id, count in parent_counts.items() if count < 2)
    if missing_parents:
        errors.append(f"every mother problem requires at least 2 subproblems: {missing_parents}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("portfolio", type=Path)
    parser.add_argument("--subproblems", type=Path)
    args = parser.parse_args()
    data = json.loads(args.portfolio.read_text(encoding="utf-8"))
    errors = validate_portfolio(data)
    subproblem_count = 0
    if args.subproblems is not None:
        subproblem_data = json.loads(args.subproblems.read_text(encoding="utf-8"))
        errors.extend(validate_subproblems(subproblem_data, data))
        subproblem_count = len(subproblem_data.get("subproblems", []))
    print(
        json.dumps(
            {
                "valid": not errors,
                "problem_count": len(data.get("problems", [])),
                "subproblem_count": subproblem_count,
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
