"""Small deterministic validator for registered result bundles."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml


SUPPORTIVE_STATUSES = {"supported", "partially_supported", "verified", "reproduced"}
COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass
class BundleValidation:
    valid: bool
    bundle_path: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_artifacts: int = 0
    checked_claims: int = 0
    bundle_id: str | None = None
    producer_repository: str | None = None
    producer_commit: str | None = None
    manifest_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    if path.suffix.lower() in {".yaml", ".yml"}:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected an object in {path}")
    return payload


def validate_result_bundle(path: str | Path) -> BundleValidation:
    bundle_path = Path(path).resolve()
    manifest_path = bundle_path if bundle_path.is_file() else _manifest_path(bundle_path)
    root = manifest_path.parent
    result = BundleValidation(valid=False, bundle_path=str(root))
    try:
        manifest = _load_object(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        result.errors.append(f"Cannot read bundle manifest: {exc}")
        return result

    result.manifest_sha256 = sha256_file(manifest_path)
    result.bundle_id = str(manifest.get("bundle_id") or "").strip() or None

    if manifest.get("schema_version") != "ara.result_bundle.v1":
        result.errors.append("schema_version must be ara.result_bundle.v1")
    if not str(manifest.get("bundle_id") or "").strip():
        result.errors.append("bundle_id is required")
    producer = manifest.get("producer")
    if not isinstance(producer, Mapping):
        result.errors.append("producer must be an object")
    else:
        result.producer_repository = str(producer.get("repository") or "").strip() or None
        result.producer_commit = str(producer.get("commit") or "").strip() or None
        if not result.producer_repository:
            result.errors.append("producer.repository is required")
        commit = result.producer_commit or ""
        if not COMMIT_PATTERN.fullmatch(commit):
            result.errors.append("producer.commit must be a full 40-character hexadecimal Git commit")

    artifacts = manifest.get("artifacts")
    artifact_ids: set[str] = set()
    if not isinstance(artifacts, list):
        result.errors.append("artifacts must be a list")
        artifacts = []
    for index, item in enumerate(artifacts):
        if not isinstance(item, Mapping):
            result.errors.append(f"artifacts[{index}] must be an object")
            continue
        artifact_id = str(item.get("id") or "").strip()
        relative = str(item.get("path") or "").strip()
        expected = str(item.get("sha256") or "").strip().lower()
        if not artifact_id or artifact_id in artifact_ids:
            result.errors.append(f"artifacts[{index}].id is missing or duplicated")
        artifact_ids.add(artifact_id)
        target = _safe_child(root, relative, result.errors, f"artifacts[{index}].path")
        if target is None or not target.is_file():
            result.errors.append(f"artifacts[{index}] file is missing: {relative}")
            continue
        if not SHA256_PATTERN.fullmatch(expected):
            result.errors.append(f"artifacts[{index}].sha256 is invalid")
            continue
        actual = sha256_file(target)
        if actual != expected:
            result.errors.append(f"artifacts[{index}] sha256 mismatch: {relative}")
        result.checked_artifacts += 1

    claims_file = str(manifest.get("claims_file") or "").strip()
    claims_path = _safe_child(root, claims_file, result.errors, "claims_file")
    if claims_path is None or not claims_path.is_file():
        result.errors.append(f"claims_file is missing: {claims_file}")
    else:
        try:
            claims_payload = _load_object(claims_path)
            _validate_claims(claims_payload, artifact_ids, result)
        except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
            result.errors.append(f"Cannot read claims file: {exc}")

    result.valid = not result.errors
    return result


def _manifest_path(root: Path) -> Path:
    for name in ("result_bundle.yaml", "result_bundle.yml", "result_bundle.json"):
        candidate = root / name
        if candidate.is_file():
            return candidate
    return root / "result_bundle.yaml"


def _safe_child(root: Path, relative: str, errors: list[str], field_name: str) -> Path | None:
    if not relative:
        errors.append(f"{field_name} is required")
        return None
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        errors.append(f"{field_name} escapes the bundle directory")
        return None
    return candidate


def _validate_claims(
    payload: Mapping[str, Any], artifact_ids: set[str], result: BundleValidation
) -> None:
    claims = payload.get("claims")
    if not isinstance(claims, list):
        result.errors.append("claims must be a list")
        return
    if not claims:
        result.warnings.append("claims is empty; there is no evidence-backed material to write")
    seen: set[str] = set()
    for index, claim in enumerate(claims):
        if not isinstance(claim, Mapping):
            result.errors.append(f"claims[{index}] must be an object")
            continue
        claim_id = str(claim.get("claim_id") or "").strip()
        text = str(claim.get("claim") or "").strip()
        status = str(claim.get("status") or "").strip()
        supporting = claim.get("supported_by")
        limitations = claim.get("limitations")
        if not claim_id or claim_id in seen:
            result.errors.append(f"claims[{index}].claim_id is missing or duplicated")
        seen.add(claim_id)
        if not text:
            result.errors.append(f"claims[{index}].claim is required")
        if not isinstance(supporting, list):
            result.errors.append(f"claims[{index}].supported_by must be a list")
            supporting = []
        missing = sorted(str(ref) for ref in supporting if str(ref) not in artifact_ids)
        if missing:
            result.errors.append(f"claims[{index}] references undeclared artifacts: {missing}")
        if status in SUPPORTIVE_STATUSES and not supporting:
            result.errors.append(f"claims[{index}] status {status!r} requires supporting artifacts")
        if not isinstance(limitations, list):
            result.errors.append(f"claims[{index}].limitations must be a list")
        if not any(claim.get(key) for key in ("evidence_level", "verification_status", "reproduction_status")):
            result.errors.append(
                f"claims[{index}] requires evidence_level, verification_status, or reproduction_status"
            )
        result.checked_claims += 1
