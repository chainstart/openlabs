#!/usr/bin/env python3
"""Reject prior evaluative projections embedded in blinded review archives."""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import BinaryIO


MAX_MEMBER_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
TEXT_SUFFIXES = {
    ".bib",
    ".cff",
    ".csv",
    ".g",
    ".json",
    ".md",
    ".py",
    ".rst",
    ".tex",
    ".txt",
    ".yaml",
    ".yml",
}
PATTERNS = (
    ("internal_pass", re.compile(r"\bPASS_INTERNAL\b", re.IGNORECASE)),
    ("publishability", re.compile(r"\bpublishability\b|\bpotentially\s+publishable\b", re.IGNORECASE)),
    ("publication_assessment", re.compile(r"\bpublication\s+assessment\b", re.IGNORECASE)),
    ("publication_suitability", re.compile(r"\bsuitable\s+for\s+(?:publication|conversion\s+into\s+(?:a\s+)?(?:focused\s+)?(?:paper|preprint))", re.IGNORECASE)),
    ("venue_tier_readiness", re.compile(r"\bCAS\s*1\s*区\b|\bfour[_ -]top[_ -]math[_ -]journals\b|\btop[_ -]conference\b", re.IGNORECASE)),
    ("quality_gate", re.compile(r"\bquality[_ -]?gate\b|\bwriting_release\b|\bara_llm_self_review\b", re.IGNORECASE)),
    ("audit_verdict", re.compile(r"\b(?:core|theorem|proof|manuscript|paper)(?:\s+\w+){0,3}\s+passed\s+(?:the\s+)?audit\b", re.IGNORECASE)),
    ("review_decision", re.compile(r"[\"']?(?:decision|recommendation)[\"']?\s*[:=]\s*[\"']?(?:accept|reject|minor_revision|major_revision|weak_accept|weak_reject)\b", re.IGNORECASE)),
    ("review_score", re.compile(r"[\"']?(?:overall|clarity|soundness|significance|novelty)[\"']?\s*[:=]\s*[1-9]|\boverall\s+score\b", re.IGNORECASE)),
)


def _scan_zip(
    source: str,
    handle: BinaryIO,
    *,
    depth: int,
    findings: list[dict[str, object]],
    budget: list[int],
) -> None:
    if depth > 3:
        raise ValueError(f"nested ZIP depth exceeds 3 at {source}")
    with zipfile.ZipFile(handle) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            if member.file_size > MAX_MEMBER_BYTES:
                raise ValueError(f"archive member exceeds {MAX_MEMBER_BYTES} bytes: {source}!{member.filename}")
            budget[0] += member.file_size
            if budget[0] > MAX_TOTAL_BYTES:
                raise ValueError(f"expanded archive input exceeds {MAX_TOTAL_BYTES} bytes")
            data = archive.read(member)
            member_source = f"{source}!{member.filename}"
            if member.filename.casefold().endswith(".zip"):
                _scan_zip(
                    member_source,
                    io.BytesIO(data),
                    depth=depth + 1,
                    findings=findings,
                    budget=budget,
                )
                continue
            if Path(member.filename).suffix.casefold() not in TEXT_SUFFIXES:
                continue
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            for label, pattern in PATTERNS:
                for match in pattern.finditer(text):
                    findings.append(
                        {
                            "code": "REVIEW-INPUT-EVALUATION-PROJECTION",
                            "label": label,
                            "source": member_source,
                            "line": text.count("\n", 0, match.start()) + 1,
                            "match": match.group(0),
                        }
                    )


def audit_archives(paths: list[Path]) -> dict[str, object]:
    findings: list[dict[str, object]] = []
    budget = [0]
    for path in paths:
        with path.open("rb") as handle:
            _scan_zip(str(path), handle, depth=0, findings=findings, budget=budget)
    return {
        "valid": not findings,
        "archives": [str(path) for path in paths],
        "expanded_bytes": budget[0],
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", action="append", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = audit_archives(args.archive)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        result = {
            "valid": False,
            "archives": [str(path) for path in args.archive],
            "findings": [
                {
                    "code": "REVIEW-INPUT-ARCHIVE-INVALID",
                    "source": "",
                    "line": None,
                    "match": str(exc),
                }
            ],
        }
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif result["valid"]:
        print(f"Review input hygiene: valid; archives={len(args.archive)}")
    else:
        print("Review input hygiene: invalid")
        for item in result["findings"]:
            print(
                f"ERROR {item['code']}: {item.get('source')}:{item.get('line')}: "
                f"{item.get('label', '')} {item.get('match', '')}"
            )
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
