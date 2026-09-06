"""Freeze review evidence against exact statement versions before catalog reuse."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path("registry/math-problems")


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def statement_binding(statement):
    meta = statement.get("metadata", statement)
    # A declaration can keep its text while imports/definitions change.
    return canonical_digest({k: meta.get(k) for k in (
        "statement_text", "language", "source_revision", "file_sha256", "source_sha256")})


def checked_batch_path(paths, value):
    root = paths.data / ROOT / "intake-batches"
    path = Path(value)
    path = path if path.is_absolute() else paths.data / path
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or path.suffix != ".json":
        raise ValueError("intake batch must be a JSON file inside intake-batches")
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("intake batch exceeds size limit")
    return path


def seal_batch(paths, value, atomic_write_json):
    path = checked_batch_path(paths, value)
    payload = json.loads(path.read_text())
    if not payload.get("batch_id") or "_seal" in payload:
        raise ValueError("missing batch ID or batch is already sealed")
    source_digest = canonical_digest(payload)
    target = paths.data / ROOT / "reviewed-batches" / path.name
    if target.exists():
        old = json.loads(target.read_text())
        if old.get("_seal", {}).get("source_body_sha256") != source_digest:
            raise ValueError("reviewed batch changed: use a new revision filename, do not overwrite history")
        return {"path": str(target.relative_to(paths.data)), "unchanged": True}
    bundle = json.loads((paths.data / ROOT / "catalog-bundle.json").read_text())
    statements = {r["record_id"]: r for r in bundle["records"] if r["kind"] == "math_statement"}
    for statement in payload.get("statements", []):
        if statement["statement_id"] in statements:
            raise ValueError("a new intake statement must not overwrite an existing statement ID")
        statements[statement["statement_id"]] = statement
    for review in payload.get("reviews", []):
        ids = review.get("reviewed_statement_ids", [])
        if review.get("scope_review") == "passed" and not ids:
            raise ValueError("passing scope review has no statements")
        if any(s not in statements for s in ids):
            raise ValueError("review names a missing statement")
        review["statement_bindings"] = {s: statement_binding(statements[s]) for s in ids}
        review["require_statement_bindings"] = True
    payload["_seal"] = {"schema_version": "openlabs.math_reviewed_batch.v1",
        "sealed_at": datetime.now(timezone.utc).isoformat(),
        "source_path": str(path.relative_to(paths.data)), "source_body_sha256": source_digest,
        "review_body_sha256": canonical_digest(payload)}
    atomic_write_json(target, payload)
    return {"path": str(target.relative_to(paths.data)), "unchanged": False,
            "problems": len(payload.get("problems", [])), "reviews": len(payload.get("reviews", []))}


def load_reviewed_batches(paths):
    result, seen = [], set()
    root = paths.data / ROOT / "reviewed-batches"
    for path in sorted(root.glob("*.json")):
        if path.is_symlink() or path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("unsafe reviewed batch")
        payload = json.loads(path.read_text())
        seal = payload.pop("_seal", {})
        if seal.get("schema_version") != "openlabs.math_reviewed_batch.v1" or canonical_digest(payload) != seal.get("review_body_sha256"):
            raise ValueError("reviewed batch content hash mismatch")
        if payload["batch_id"] in seen:
            raise ValueError("duplicate reviewed batch ID")
        seen.add(payload["batch_id"])
        payload["_seal"] = seal
        result.append(payload)
    return result


def current_reviews(reviews):
    """Keep past assessments while requiring an unambiguous newest review."""
    groups = {}
    for review in reviews:
        timestamp = datetime.fromisoformat(review["reviewed_at"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("review timestamps must include timezone")
        groups.setdefault(review["problem_id"], []).append((timestamp, review))
    active, historical = [], []
    for group in groups.values():
        group.sort(key=lambda pair: pair[0])
        latest_time, latest = group[-1]
        tied = [r for t, r in group if t == latest_time]
        if len(tied) > 1:
            raise ValueError("multiple intake reviews at the same latest timestamp")
        active.append(latest)
        historical.extend({**r, "superseded_by_reviewed_at": latest["reviewed_at"]} for _, r in group[:-1])
    return active, historical
