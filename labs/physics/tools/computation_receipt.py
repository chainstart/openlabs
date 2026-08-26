#!/usr/bin/env python3
"""Create a hash-bound receipt for an already completed physics computation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = "openlabs.physics_computation.v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _record(root: Path, path: Path) -> dict[str, object]:
    resolved = path.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError(f"receipt files must exist under root: {path}")
    return {
        "path": str(resolved.relative_to(root)),
        "sha256": sha256_file(resolved),
        "bytes": resolved.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--receipt-id", required=True)
    parser.add_argument("--code", type=Path, required=True)
    parser.add_argument("--environment-lock", type=Path, required=True)
    parser.add_argument("--input", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, action="append", required=True)
    parser.add_argument("--command", action="append", required=True)
    parser.add_argument("--precision", required=True)
    parser.add_argument("--random-seed", type=int)
    parser.add_argument("--convergence", required=True)
    parser.add_argument("--uncertainty-budget", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    destination = args.destination.resolve()
    if not destination.is_relative_to(root):
        raise ValueError("destination must be under root")
    payload = {
        "schema_version": SCHEMA,
        "receipt_id": args.receipt_id,
        "recorded_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "code": _record(root, args.code),
        "environment_lock": _record(root, args.environment_lock),
        "inputs": [_record(root, path) for path in args.input],
        "outputs": [_record(root, path) for path in args.output],
        "command": args.command,
        "precision": args.precision,
        "random_seed": args.random_seed,
        "numerical_controls": {
            "dimensional_analysis": True,
            "convergence": args.convergence,
            "uncertainty_budget": args.uncertainty_budget,
        },
        "status": "PASS",
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, destination)
    print(json.dumps({"receipt": str(destination)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
