#!/usr/bin/env python3
"""Create and validate append-oriented Quant Lab trial ledgers."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LEDGER_SCHEMA = "openlabs.quant_trial_ledger.v1"
TRIAL_STAGES = {"pilot", "validation", "confirmation"}
TRIAL_STATUSES = {"planned", "running", "completed", "failed", "inconclusive"}
TERMINAL_STATUSES = {"completed", "failed", "inconclusive"}
SHA256_LENGTH = 64


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_trial(trial: Any, index: int) -> list[str]:
    prefix = f"trials[{index}]"
    if not isinstance(trial, dict):
        return [f"{prefix} must be an object"]
    errors: list[str] = []
    for field in ("trial_id", "hypothesis_id", "registered_at_utc"):
        if not isinstance(trial.get(field), str) or not trial[field].strip():
            errors.append(f"{prefix}.{field} must be a non-empty string")
    if trial.get("stage") not in TRIAL_STAGES:
        errors.append(f"{prefix}.stage must be one of {sorted(TRIAL_STAGES)}")
    if trial.get("status") not in TRIAL_STATUSES:
        errors.append(f"{prefix}.status must be one of {sorted(TRIAL_STATUSES)}")
    if not is_sha256(trial.get("config_sha256")):
        errors.append(f"{prefix}.config_sha256 must be a lowercase SHA-256")
    snapshots = trial.get("data_snapshot_ids")
    if not isinstance(snapshots, list) or not snapshots or any(
        not isinstance(item, str) or not item.strip() for item in snapshots
    ):
        errors.append(f"{prefix}.data_snapshot_ids must be a non-empty string array")
    if trial.get("stage") == "confirmation":
        if trial.get("selection_locked") is not True:
            errors.append(f"{prefix}.selection_locked must be true for confirmation")
        if trial.get("holdout_access") not in {"sealed", "consumed_once"}:
            errors.append(
                f"{prefix}.holdout_access must be sealed or consumed_once for confirmation"
            )
        family_size = trial.get("multiplicity_family_size")
        if not isinstance(family_size, int) or isinstance(family_size, bool) or family_size < 1:
            errors.append(f"{prefix}.multiplicity_family_size must be a positive integer")
    return errors


def validate_ledger(
    payload: dict[str, Any],
    *,
    project_id: str | None = None,
    workstream_id: str | None = None,
) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != LEDGER_SCHEMA:
        errors.append(f"ledger schema must be {LEDGER_SCHEMA}")
    if project_id is not None and payload.get("project_id") != project_id:
        errors.append("ledger project_id differs from the workstream")
    if workstream_id is not None and payload.get("workstream_id") != workstream_id:
        errors.append("ledger workstream_id differs from the workstream")
    for field in ("project_id", "workstream_id", "created_at_utc"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            errors.append(f"ledger {field} must be a non-empty string")
    trials = payload.get("trials")
    if not isinstance(trials, list):
        errors.append("ledger trials must be an array")
        return errors
    ids: list[str] = []
    for index, trial in enumerate(trials):
        errors.extend(validate_trial(trial, index))
        if isinstance(trial, dict) and isinstance(trial.get("trial_id"), str):
            ids.append(trial["trial_id"])
    if len(ids) != len(set(ids)):
        errors.append("ledger trial_id values must be unique")
    return errors


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def create_ledger(path: Path, project_id: str, workstream_id: str) -> None:
    with _locked(path):
        if path.exists():
            raise ValueError(f"ledger already exists: {path}")
        _atomic_write(
            path,
            {
                "schema_version": LEDGER_SCHEMA,
                "project_id": project_id,
                "workstream_id": workstream_id,
                "created_at_utc": utc_now(),
                "trials": [],
            },
        )


def register_trial(path: Path, trial_path: Path) -> None:
    trial = read_object(trial_path)
    errors = validate_trial(trial, 0)
    if errors:
        raise ValueError("; ".join(errors))
    if trial.get("status") != "planned":
        raise ValueError("a newly registered trial must have status planned")
    with _locked(path):
        ledger = read_object(path)
        existing_errors = validate_ledger(ledger)
        if existing_errors:
            raise ValueError("; ".join(existing_errors))
        if any(item.get("trial_id") == trial["trial_id"] for item in ledger["trials"]):
            raise ValueError(f"duplicate trial_id: {trial['trial_id']}")
        ledger["trials"].append(trial)
        _atomic_write(path, ledger)


def transition_trial(path: Path, trial_id: str, status: str) -> None:
    if status not in TRIAL_STATUSES:
        raise ValueError(f"unsupported status: {status}")
    allowed = {
        "planned": {"running", "failed", "inconclusive"},
        "running": TERMINAL_STATUSES,
    }
    with _locked(path):
        ledger = read_object(path)
        trials = [item for item in ledger.get("trials", []) if item.get("trial_id") == trial_id]
        if len(trials) != 1:
            raise ValueError(f"expected exactly one trial {trial_id!r}")
        trial = trials[0]
        current = trial.get("status")
        if status not in allowed.get(current, set()):
            raise ValueError(f"invalid trial transition: {current} -> {status}")
        trial["status"] = status
        trial["status_updated_at_utc"] = utc_now()
        errors = validate_ledger(ledger)
        if errors:
            raise ValueError("; ".join(errors))
        _atomic_write(path, ledger)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--ledger", type=Path, required=True)
    create.add_argument("--project-id", required=True)
    create.add_argument("--workstream-id", required=True)

    register = subparsers.add_parser("register")
    register.add_argument("--ledger", type=Path, required=True)
    register.add_argument("--trial", type=Path, required=True)

    transition = subparsers.add_parser("transition")
    transition.add_argument("--ledger", type=Path, required=True)
    transition.add_argument("--trial-id", required=True)
    transition.add_argument("--status", choices=sorted(TRIAL_STATUSES), required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--ledger", type=Path, required=True)

    args = parser.parse_args()
    try:
        if args.command == "create":
            create_ledger(args.ledger.resolve(), args.project_id, args.workstream_id)
        elif args.command == "register":
            register_trial(args.ledger.resolve(), args.trial.resolve())
        elif args.command == "transition":
            transition_trial(args.ledger.resolve(), args.trial_id, args.status)
        else:
            errors = validate_ledger(read_object(args.ledger.resolve()))
            print(json.dumps({"valid": not errors, "errors": errors}, indent=2))
            return 1 if errors else 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"valid": True, "errors": []}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
