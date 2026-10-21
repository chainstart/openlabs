"""Audit sample and independent-group overlap in a frozen train/validation/test CSV."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from tools.common import atomic_json, sha256

UNIT_COLUMNS = {
    "molecule": "molecule_id",
    "donor": "donor_id",
    "cell_line": "cell_line_id",
    "study": "study_id",
}
SPLITS = {"train", "validation", "test"}
STRATEGIES = {"group", "scaffold", "study", "time"}


def audit(
    samples: Path,
    *,
    independent_unit: str,
    group_columns: list[str],
    strategy: str,
    project_root: Path | None = None,
    max_rows: int = 100_000,
) -> dict:
    samples = samples.resolve()
    project_root = (project_root or samples.parent).resolve()
    if not samples.is_relative_to(project_root):
        raise ValueError("sample table must be within project root")
    if samples.stat().st_size > 64 * 1024**2 or max_rows < 1:
        raise ValueError("sample table exceeds 64 MiB or row limit is invalid")
    if independent_unit not in UNIT_COLUMNS or strategy not in STRATEGIES:
        raise ValueError("unsupported independent unit or split strategy")
    if not group_columns or len(set(group_columns)) != len(group_columns):
        raise ValueError("nonempty unique group columns required")
    required_group = UNIT_COLUMNS[independent_unit]
    if required_group not in group_columns:
        raise ValueError(f"independent unit requires grouping on {required_group}")
    if strategy == "scaffold" and "scaffold_id" not in group_columns:
        raise ValueError("scaffold split requires scaffold_id")
    if strategy == "study" and "study_id" not in group_columns:
        raise ValueError("study split requires study_id")
    counts = dict.fromkeys(sorted(SPLITS), 0)
    owners = {column: {} for column in ["sample_id", *group_columns]}
    errors = []
    error_count = 0

    def fail(message: str) -> None:
        nonlocal error_count
        error_count += 1
        if len(errors) < 30:
            errors.append(message)

    with samples.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"sample_id", "split", *group_columns}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("missing required CSV columns: " + ", ".join(sorted(required)))
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError("duplicate CSV column names")
        for index, row in enumerate(reader, 1):
            if index > max_rows:
                raise ValueError("sample row ceiling exceeded; partition the audit explicitly")
            split = row.get("split")
            if split not in SPLITS:
                fail(f"row {index}: invalid split")
                continue
            counts[split] += 1
            for column, groups in owners.items():
                value = (row.get(column) or "").strip()
                if not value:
                    fail(f"row {index}: missing {column}")
                    continue
                previous = groups.get(value)
                if previous is not None and (previous != split or column == "sample_id"):
                    fail(f"row {index}: duplicate sample or cross-split {column}: {value}")
                groups[value] = split
    if not all(counts.values()):
        fail("train, validation and test partitions must all be nonempty")
    return {
        "schema_version": "openlabs.biomed_split_audit.v1",
        "valid": error_count == 0,
        "errors": errors,
        "error_count": error_count,
        "independent_unit": independent_unit,
        "strategy": strategy,
        "group_columns": group_columns,
        "counts": counts,
        "unique_groups": {column: len(values) for column, values in owners.items()},
        "sample_table": {"path": str(samples.relative_to(project_root)), "sha256": sha256(samples)},
        "limitations": [
            "Audits supplied identifiers only; standardize molecules and resolve donors upstream.",
            "Does not establish chronology, feature isolation or external-study independence.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", required=True, type=Path)
    parser.add_argument("--independent-unit", required=True, choices=sorted(UNIT_COLUMNS))
    parser.add_argument("--group-column", required=True, action="append")
    parser.add_argument("--strategy", required=True, choices=sorted(STRATEGIES))
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = audit(
            args.samples,
            independent_unit=args.independent_unit,
            group_columns=args.group_column,
            strategy=args.strategy,
            project_root=args.project_root,
        )
        if args.output.resolve() == args.samples.resolve():
            raise ValueError("audit must not overwrite the sample table")
        atomic_json(args.output, report)
        print(json.dumps(report))
        return int(not report["valid"])
    except (OSError, ValueError, csv.Error) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
