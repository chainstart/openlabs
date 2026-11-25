"""What "delivered" means, once (2026-11-25, B5).

Before this module three readers decided it on their own (architecture report 2026-11-24, P28):
``paper-writing program release-status`` (the registry ``delivery`` block names the current
version), ``program reconcile`` (the same plus a matching receipt ``papers/<id>/releases/
pkg_*.json``) and the funnel (ledger history). The current version of a paper is delivered when
the registry record's ``delivery`` block carries a package id for the record's ``version`` and a
delivery receipt for that package exists. The funnel keeps counting papers that were *ever*
delivered from the ledger history; that is a different question (see ``ever_delivered``).

Pure functions, standard library only: ``paper_writing`` imports this file too.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

RECEIPT_GLOB = "pkg_*.json"
# Ledger history reasons that record a delivery (the last one is program.DELIVERY_RECONCILE_REASON).
EVER_DELIVERED_REASONS = frozenset({"record-delivery", "delivered", "auto_handoff",
                                    "delivery_receipt_reconciled"})


def receipts(data_root: str | Path, paper_id: str) -> list[dict[str, Any]]:
    """Delivery receipts of a paper (``papers/<id>/releases/pkg_*.json``), oldest first."""

    folder = Path(data_root) / "papers" / str(paper_id) / "releases"
    if not paper_id or "/" in str(paper_id) or not folder.is_dir():
        return []
    found = []
    for path in sorted(folder.glob(RECEIPT_GLOB)):
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(body, Mapping) or str(body.get("paper_id") or "") != str(paper_id):
            continue
        found.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                      "version": body.get("version"), "package_id": body.get("package_id"),
                      "released_at": body.get("released_at")})
    return sorted(found, key=lambda item: str(item.get("released_at") or ""))


def current_delivery(record: Mapping[str, Any] | None,
                     found: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """The delivery of the record's current version (with its receipt), or None."""

    if not isinstance(record, Mapping):
        return None
    version = str(record.get("version") or "")
    delivery = record.get("delivery")
    if not isinstance(delivery, Mapping) or not version:
        return None
    package_id = str(delivery.get("package_id") or "")
    if not package_id or str(delivery.get("version") or "") != version:
        return None
    receipt = next((dict(item) for item in found if item.get("package_id") == package_id), None)
    if receipt is None:
        return None
    return {"version": version, "package_id": package_id,
            "delivered_at": delivery.get("delivered_at") or receipt.get("released_at"),
            "receipt": receipt}


def delivered(record: Mapping[str, Any] | None, data_root: str | Path, paper_id: str) -> bool:
    """Whether the record's current version is delivered (delivery block + receipt)."""

    return current_delivery(record, receipts(data_root, paper_id)) is not None


def ever_delivered(topic: Mapping[str, Any]) -> bool:
    """Whether a ledger topic's paper was delivered at some point (any version)."""

    handoff = topic.get("handoff") if isinstance(topic.get("handoff"), Mapping) else {}
    reasons = {entry.get("reason") for entry in topic.get("history") or []
               if isinstance(entry, Mapping)}
    return bool(handoff.get("delivered_at") or handoff.get("status") == "delivered"
                or reasons & EVER_DELIVERED_REASONS)
