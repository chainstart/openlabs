"""Select the cheapest passing adjacent QE setting without reading model errors."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .provenance import atomic_write_json, fingerprint, sha256_file

NUMERICAL_FIELDS = (
    "ecutwfc_ry",
    "ecutrho_ry",
    "kpoints",
    "conv_thr_ry",
    "electron_maxstep",
    "mixing_mode",
    "mixing_beta",
    "diagonalization",
)
STAGE_FIELDS = {
    "cutoff": ("ecutwfc_ry", "ecutrho_ry"),
    "kpoint": ("kpoints",),
    "scf": ("conv_thr_ry",),
}


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def _settings(report: dict[str, Any], side: str) -> dict[str, Any]:
    records = report.get("records")
    if not isinstance(records, list) or len(records) < 2:
        raise ValueError("numerical report needs at least two matched structures")
    first = records[0].get(side, {}).get("settings")
    if not isinstance(first, dict):
        raise ValueError(f"numerical report has no {side} settings")
    selected = {field: first.get(field) for field in NUMERICAL_FIELDS}
    if any(value is None for value in selected.values()):
        raise ValueError(f"numerical report has incomplete {side} settings")
    for record in records[1:]:
        other = record.get(side, {}).get("settings", {})
        if any(other.get(field) != value for field, value in selected.items()):
            raise ValueError(f"matched structures use inconsistent {side} settings")
    return selected


def _kpoint_density(value: Any) -> int:
    if value == "gamma":
        return 1
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"invalid k-point setting {value!r}")
    dimensions = [int(item) for item in value]
    if any(item <= 0 for item in dimensions):
        raise ValueError(f"invalid k-point setting {value!r}")
    return math.prod(dimensions)


def _validate_adjacent_change(
    lower: dict[str, Any], upper: dict[str, Any], *, stage: str
) -> None:
    changed = set(STAGE_FIELDS[stage])
    invariant = set(NUMERICAL_FIELDS) - changed
    differences = [field for field in invariant if lower[field] != upper[field]]
    if differences:
        raise ValueError(
            f"{stage} comparison changes non-stage settings: {', '.join(sorted(differences))}"
        )
    if any(lower[field] == upper[field] for field in changed):
        raise ValueError(f"{stage} comparison does not change every stage field")
    if stage == "cutoff":
        if not (
            float(upper["ecutwfc_ry"]) > float(lower["ecutwfc_ry"])
            and float(upper["ecutrho_ry"]) > float(lower["ecutrho_ry"])
        ):
            raise ValueError("cutoff ladder is not strictly increasing")
    elif stage == "kpoint":
        if _kpoint_density(upper["kpoints"]) <= _kpoint_density(lower["kpoints"]):
            raise ValueError("k-point ladder is not strictly increasing")
    elif float(upper["conv_thr_ry"]) >= float(lower["conv_thr_ry"]):
        raise ValueError("SCF threshold ladder is not strictly tighter")


def choose_adjacent_setting(
    report_paths: list[Path | str],
    *,
    stage: str,
    protocol_path: Path | str,
) -> dict[str, Any]:
    """Choose the lower side of the first passing adjacent comparison."""
    if stage not in STAGE_FIELDS:
        raise ValueError(f"unsupported numerical stage {stage!r}")
    if not report_paths:
        raise ValueError("at least one adjacent comparison report is required")
    protocol_source = Path(protocol_path).resolve()
    protocol_sha256 = sha256_file(protocol_source)
    comparisons = []
    previous_upper: dict[str, Any] | None = None
    selected: dict[str, Any] | None = None
    selected_index: int | None = None
    for index, value in enumerate(report_paths):
        path = Path(value).resolve()
        report = _read_json(path)
        if report.get("comparison_kind") != "qe-numerical-convergence":
            raise ValueError(f"not a QE convergence report: {path}")
        if report.get("protocol_sha256") != protocol_sha256:
            raise RuntimeError(f"convergence report protocol hash mismatch: {path}")
        lower = _settings(report, "lower")
        upper = _settings(report, "upper")
        _validate_adjacent_change(lower, upper, stage=stage)
        if previous_upper is not None and lower != previous_upper:
            raise ValueError("adjacent convergence reports do not form a continuous ladder")
        previous_upper = upper
        passed = report.get("numerically_converged") is True
        comparisons.append(
            {
                "index": index,
                "report_path": str(path),
                "report_sha256": sha256_file(path),
                "lower_settings": lower,
                "upper_settings": upper,
                "metrics": report.get("metrics"),
                "checks": report.get("checks"),
                "passed": passed,
            }
        )
        if passed and selected is None:
            selected = lower
            selected_index = index

    decision = {
        "schema_version": "1.0",
        "decision_kind": "qe-cheapest-passing-adjacent-setting",
        "stage": stage,
        "protocol_path": str(protocol_source),
        "protocol_sha256": protocol_sha256,
        "selection_is_model_blind": True,
        "decision_rule": (
            "Choose the lower setting of the first passing adjacent comparison; "
            "do not inspect CHGNet-minus-DFT errors."
        ),
        "comparisons": comparisons,
        "selected_comparison_index": selected_index,
        "selected_settings": selected,
        "decision_status": "selected" if selected is not None else "no_passing_pair",
        "can_continue": selected is not None,
    }
    decision["decision_fingerprint"] = fingerprint(decision)
    return decision


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=sorted(STAGE_FIELDS), required=True)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--report", action="append", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    decision = choose_adjacent_setting(
        args.report,
        stage=args.stage,
        protocol_path=args.protocol,
    )
    destination = Path(args.out).resolve()
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite numerical decision: {destination}")
    atomic_write_json(destination, decision)
    print(json.dumps(decision, indent=2))


if __name__ == "__main__":
    main()
