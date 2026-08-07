#!/usr/bin/env python3
"""Validate a skill-authored review record without calculating its score."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


WORKFLOW_ROOT = Path(__file__).resolve().parents[3]
if str(WORKFLOW_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_ROOT))

from paper_writing.registry import load_paper_metadata, repository_root  # noqa: E402
from paper_writing.handoff import manuscript_snapshot_sha256, sha256_file  # noqa: E402
from paper_writing.review import (  # noqa: E402
    INDIVIDUAL_REVIEW_SCHEMA_VERSION,
    review_summary,
    reviewer_role_for_domain,
    validate_review_panel_files,
    validate_review_record,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate an OpenLabs skill-authored review JSON without judging the paper."
    )
    parser.add_argument("--paper-id", required=True)
    parser.add_argument("--review", required=True)
    parser.add_argument("--root", default=str(repository_root()))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    review_path = Path(args.review)
    if not review_path.is_absolute():
        review_path = root / review_path

    errors: list[str] = []
    payload: Any = None
    metadata: dict[str, Any] | None = None
    try:
        metadata = load_paper_metadata(args.paper_id, root)
        expected_role = reviewer_role_for_domain(metadata.get("domain"))
    except (FileNotFoundError, ValueError, TypeError) as exc:
        expected_role = None
        errors.append(str(exc))

    try:
        payload = json.loads(review_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cannot read review JSON: {exc}")

    if payload is not None:
        if (
            isinstance(payload, dict)
            and payload.get("schema_version") == INDIVIDUAL_REVIEW_SCHEMA_VERSION
        ):
            errors.extend(
                validate_review_record(
                    payload,
                    expected_role=expected_role,
                    expected_paper_id=args.paper_id,
                )
            )
        else:
            errors.extend(
                validate_review_panel_files(
                    payload,
                    review_path=review_path,
                    repo_root=root,
                    expected_role=expected_role,
                    expected_paper_id=args.paper_id,
                )
            )
        if metadata is not None and isinstance(payload, dict):
            manuscript = root / str(
                metadata.get("manuscript_dir")
                or f"papers/{args.paper_id}/manuscript"
            )
            main_tex = root / str(
                metadata.get("latest_source")
                or f"papers/{args.paper_id}/manuscript/main.tex"
            )
            pdf = root / str(
                metadata.get("latest_pdf")
                or f"papers/{args.paper_id}/manuscript/main.pdf"
            )
            if not manuscript.is_dir() or not main_tex.is_file() or not pdf.is_file():
                errors.append("canonical manuscript inputs are incomplete")
            else:
                current_snapshot = manuscript_snapshot_sha256(manuscript, pdf)
                review_metadata = payload.get("review_metadata")
                review_metadata = (
                    review_metadata if isinstance(review_metadata, dict) else {}
                )
                if review_metadata.get("main_tex_sha256") != sha256_file(main_tex):
                    errors.append(
                        "review_metadata.main_tex_sha256 does not match the current manuscript"
                    )
                for key in (
                    "manuscript_snapshot_sha256_before",
                    "manuscript_snapshot_sha256_after",
                ):
                    if review_metadata.get(key) != current_snapshot:
                        errors.append(
                            f"review_metadata.{key} does not match the canonical current snapshot"
                        )

    result: dict[str, Any] = {
        "valid": not errors,
        "paper_id": args.paper_id,
        "review": str(review_path.relative_to(root))
        if review_path.is_relative_to(root)
        else str(review_path),
        "expected_reviewer_role": expected_role,
        "errors": errors,
    }
    if payload is not None and isinstance(payload, dict):
        result.update(review_summary(payload))
        result["paper_id"] = args.paper_id
        result["schema_version"] = payload.get("schema_version")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
