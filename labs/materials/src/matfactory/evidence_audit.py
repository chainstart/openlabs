"""Declarative, hash-aware audit of the complete LLZTO publication evidence chain."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .provenance import atomic_write_json, fingerprint, sha256_file


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def _repo_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (Path(__file__).resolve().parents[2] / path).resolve()


def json_path(payload: Any, path: str) -> Any:
    """Resolve a dot-separated object path without silently accepting a missing key."""
    value = payload
    for component in path.split("."):
        if not component:
            raise ValueError(f"invalid empty JSON-path component in {path!r}")
        if isinstance(value, dict):
            if component not in value:
                raise KeyError(path)
            value = value[component]
        elif isinstance(value, list) and component.isdigit():
            index = int(component)
            if not 0 <= index < len(value):
                raise IndexError(path)
            value = value[index]
        else:
            raise KeyError(path)
    return value


def evaluate_assertion(payload: dict[str, Any], assertion: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one frozen assertion and return its actual value and disposition."""
    path = str(assertion["json_path"])
    operator = str(assertion["operator"])
    expected = assertion.get("value")
    try:
        actual = json_path(payload, path)
        if operator == "equals":
            passed = actual == expected
        elif operator == "is_true":
            passed = actual is True
        elif operator == "is_false":
            passed = actual is False
        elif operator == "at_least":
            passed = float(actual) >= float(expected)
        elif operator == "at_most":
            passed = float(actual) <= float(expected)
        elif operator == "length_equals":
            passed = len(actual) == int(expected)
        elif operator == "length_at_least":
            passed = len(actual) >= int(expected)
        else:
            raise ValueError(f"unsupported assertion operator {operator!r}")
        return {
            "json_path": path,
            "operator": operator,
            "expected": expected,
            "actual": actual,
            "pass": bool(passed),
        }
    except (KeyError, IndexError, TypeError, ValueError, OverflowError) as exc:
        return {
            "json_path": path,
            "operator": operator,
            "expected": expected,
            "actual": None,
            "pass": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def validate_exclusion_ledger(
    payload: dict[str, Any], *, ledger_path: Path
) -> dict[str, Any]:
    """Verify every hash-bearing excluded or retained-negative artifact."""
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("exclusion ledger must contain entries")
    seen: set[str] = set()
    artifact_checks = []
    entry_checks = []
    for entry in entries:
        entry_id = str(entry.get("entry_id", ""))
        basic = bool(
            entry_id
            and entry_id not in seen
            and entry.get("disposition")
            and entry.get("scope")
            and entry.get("reason")
        )
        seen.add(entry_id)
        artifacts = entry.get("artifacts", [])
        if not isinstance(artifacts, list):
            basic = False
            artifacts = []
        entry_checks.append({"entry_id": entry_id, "metadata_complete": basic})
        for artifact in artifacts:
            path = Path(str(artifact.get("path", "")))
            if not path.is_absolute():
                # Ledger paths are repository-relative, not relative to analysis/.
                path = Path(__file__).resolve().parents[2] / path
            path = path.resolve()
            expected = artifact.get("sha256")
            exists = path.is_file()
            actual = sha256_file(path) if exists else None
            artifact_checks.append(
                {
                    "entry_id": entry_id,
                    "path": str(path),
                    "expected_sha256": expected,
                    "actual_sha256": actual,
                    "pass": bool(exists and expected and actual == expected),
                }
            )
    return {
        "ledger_path": str(ledger_path.resolve()),
        "n_entries": len(entries),
        "n_hash_bearing_artifacts": len(artifact_checks),
        "entry_checks": entry_checks,
        "artifact_checks": artifact_checks,
        "ledger_gate_pass": bool(
            all(row["metadata_complete"] for row in entry_checks)
            and all(row["pass"] for row in artifact_checks)
        ),
    }


def audit_artifact(specification: dict[str, Any]) -> dict[str, Any]:
    """Audit one file while converting every expected failure into a blocker."""
    artifact_id = str(specification.get("artifact_id", ""))
    path = _repo_path(str(specification.get("path", "")))
    result: dict[str, Any] = {
        "artifact_id": artifact_id,
        "path": str(path),
        "format": specification.get("format"),
        "checks": {},
        "assertions": [],
    }
    if not artifact_id:
        result["checks"]["artifact_id"] = False
    else:
        result["checks"]["artifact_id"] = True
    exists = path.is_file()
    result["checks"]["exists"] = exists
    if not exists:
        result["artifact_gate_pass"] = False
        result["error"] = "FileNotFoundError: required artifact does not exist"
        return result

    size = path.stat().st_size
    actual_sha256 = sha256_file(path)
    result["size_bytes"] = size
    result["sha256"] = actual_sha256
    minimum_bytes = specification.get("minimum_bytes")
    result["checks"]["minimum_bytes"] = bool(
        minimum_bytes is None or size >= int(minimum_bytes)
    )
    expected_sha256 = specification.get("expected_sha256")
    result["checks"]["expected_sha256"] = bool(
        expected_sha256 is None or actual_sha256 == expected_sha256
    )
    result["expected_sha256"] = expected_sha256

    artifact_format = specification.get("format")
    if artifact_format == "file":
        if specification.get("assertions"):
            result["checks"]["format"] = False
            result["error"] = "ValueError: plain files cannot have JSON assertions"
        else:
            result["checks"]["format"] = True
    elif artifact_format in {"json", "exclusion_ledger"}:
        try:
            payload = _read_json(path)
            result["checks"]["format"] = True
            fingerprint_field = specification.get("fingerprint_field")
            if fingerprint_field is not None:
                unsigned = dict(payload)
                stored = unsigned.pop(str(fingerprint_field), None)
                calculated = fingerprint(unsigned)
                result["fingerprint"] = {
                    "field": fingerprint_field,
                    "stored": stored,
                    "calculated": calculated,
                }
                result["checks"]["fingerprint"] = stored == calculated
            for assertion in specification.get("assertions", []):
                result["assertions"].append(
                    evaluate_assertion(payload, assertion)
                )
            if artifact_format == "exclusion_ledger":
                ledger = validate_exclusion_ledger(payload, ledger_path=path)
                result["exclusion_ledger"] = ledger
                result["checks"]["exclusion_ledger"] = ledger["ledger_gate_pass"]
        except (json.JSONDecodeError, TypeError, ValueError, OSError) as exc:
            result["checks"]["format"] = False
            result["error"] = f"{type(exc).__name__}: {exc}"
    else:
        result["checks"]["format"] = False
        result["error"] = f"ValueError: unsupported artifact format {artifact_format!r}"

    result["artifact_gate_pass"] = bool(
        all(result["checks"].values())
        and all(row["pass"] for row in result["assertions"])
    )
    return result


def build_evidence_audit(protocol_path: Path | str) -> dict[str, Any]:
    """Evaluate every declared gate without short-circuiting after a blocker."""
    source = Path(protocol_path).resolve()
    protocol = _read_json(source)
    if protocol.get("schema_version") != "1.0":
        raise ValueError("evidence-audit protocol schema_version must be '1.0'")
    gates = protocol.get("gates")
    if not isinstance(gates, list) or not gates:
        raise ValueError("evidence-audit protocol contains no gates")
    seen: set[str] = set()
    gate_results = []
    blockers = []
    for gate in gates:
        gate_id = str(gate.get("gate_id", ""))
        if not gate_id or gate_id in seen:
            raise ValueError(f"duplicate or missing evidence gate id {gate_id!r}")
        seen.add(gate_id)
        artifacts = [audit_artifact(item) for item in gate.get("artifacts", [])]
        passed = bool(artifacts) and all(
            item["artifact_gate_pass"] for item in artifacts
        )
        gate_result = {
            "gate_id": gate_id,
            "hard_gate": gate.get("hard_gate") is True,
            "gate_pass": passed,
            "n_artifacts": len(artifacts),
            "n_passing_artifacts": sum(
                item["artifact_gate_pass"] for item in artifacts
            ),
            "artifacts": artifacts,
        }
        gate_results.append(gate_result)
        if gate_result["hard_gate"] and not passed:
            for artifact in artifacts:
                if not artifact["artifact_gate_pass"]:
                    blockers.append(
                        {
                            "gate_id": gate_id,
                            "artifact_id": artifact["artifact_id"],
                            "path": artifact["path"],
                            "failed_checks": [
                                name
                                for name, value in artifact["checks"].items()
                                if not value
                            ],
                            "failed_assertions": [
                                {
                                    "json_path": row["json_path"],
                                    "operator": row["operator"],
                                    "expected": row["expected"],
                                    "actual": row["actual"],
                                }
                                for row in artifact["assertions"]
                                if not row["pass"]
                            ],
                            "error": artifact.get("error"),
                        }
                    )
            if not artifacts:
                blockers.append(
                    {
                        "gate_id": gate_id,
                        "artifact_id": None,
                        "error": "hard gate declares no artifacts",
                    }
                )
    hard_gates = [gate for gate in gate_results if gate["hard_gate"]]
    complete = bool(hard_gates) and all(gate["gate_pass"] for gate in hard_gates)
    report = {
        "schema_version": "1.0",
        "report_kind": "llzto-q1-evidence-audit",
        "protocol_path": str(source),
        "protocol_sha256": sha256_file(source),
        "claim_boundary": protocol["claim_boundary"],
        "n_gates": len(gate_results),
        "n_hard_gates": len(hard_gates),
        "n_passing_hard_gates": sum(gate["gate_pass"] for gate in hard_gates),
        "evidence_chain_complete": complete,
        "ready_for_final_qualitative_q1_assessment": complete,
        "q1_journal_acceptance_guaranteed": False,
        "gates": gate_results,
        "blockers": blockers,
        "implementation_path": str(Path(__file__).resolve()),
        "implementation_sha256": sha256_file(__file__),
    }
    report["report_fingerprint"] = fingerprint(report)
    return report


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = build_evidence_audit(args.protocol)
    destination = Path(args.out).resolve()
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite evidence audit: {destination}")
    atomic_write_json(destination, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
