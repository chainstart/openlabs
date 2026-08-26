#!/usr/bin/env python3
"""Replay a receipt rejected solely by a repaired protocol-validator failure."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from openlabs.attempts import reactivate_protocol_failed_attempt_workspace
from openlabs.config import workspace_paths
from openlabs.contracts import atomic_write_json, validate_receipt
from openlabs.db import FactoryDB
from openlabs.locking import factory_operation_lock


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--expected-error-fragment", required=True)
    args = parser.parse_args()
    paths = workspace_paths(args.workspace)
    paths.ensure_runtime_directories()
    receipt_path = args.receipt.expanduser().resolve()
    if not receipt_path.is_relative_to(paths.receipt_archive.resolve()):
        raise SystemExit("receipt must be inside the OpenLabs receipt archive")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    validation = validate_receipt(receipt)
    if not validation.valid:
        raise SystemExit("invalid archived receipt: " + "; ".join(validation.errors))
    task_id = str(receipt["task_id"])
    attempt_id = str(receipt["attempt_id"])
    campaign_id = str(receipt["campaign_id"])
    db = FactoryDB(paths.database_file)
    db.initialize()
    with factory_operation_lock(paths):
        reactivate_protocol_failed_attempt_workspace(
            paths,
            campaign_id=campaign_id,
            attempt_id=attempt_id,
            expected_error_fragment=args.expected_error_fragment,
        )
        reopened = db.reopen_protocol_failed_attempt(
            task_id,
            attempt_id=attempt_id,
            expected_error_fragment=args.expected_error_fragment,
        )
        target = paths.result_inbox / f"{task_id}-{attempt_id}.json"
        atomic_write_json(target, receipt)
    print(
        json.dumps(
            {
                "schema_version": "openlabs.protocol_receipt_replay.v1",
                "published_receipt": str(target),
                **reopened,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
