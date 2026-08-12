"""Small deterministic gates; scientific judgment stays in agents and lab tools."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .contracts import ValidationResult, artifact_digests, sha256_file, validate_result_bundle


@dataclass(frozen=True)
class GateResult:
    passed: bool
    validation: ValidationResult
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    failure_classes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "validation": self.validation.to_dict(),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "failure_classes": list(self.failure_classes),
        }


def evaluate_result_bundle(
    payload: Mapping[str, Any],
    *,
    allowed_roots: tuple[Path, ...] = (),
) -> GateResult:
    validation = validate_result_bundle(payload)
    blockers = list(validation.errors)
    warnings = list(validation.warnings)
    failure_classes: set[str] = {"result_contract"} if validation.errors else set()
    if validation.valid and allowed_roots:
        roots = tuple(root.resolve() for root in allowed_roots)
        for artifact in payload.get("artifacts", []):
            if not isinstance(artifact, Mapping):
                continue
            artifact_id = artifact.get("artifact_id")
            parsed = urlparse(str(artifact.get("uri") or ""))
            if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
                blockers.append(f"artifact {artifact_id} must use a verifiable local file URI")
                failure_classes.add("artifact_binding")
                continue
            path = Path(unquote(parsed.path)).resolve()
            if not any(path == root or path.is_relative_to(root) for root in roots):
                blockers.append(f"artifact {artifact_id} is outside data/artifact roots")
                failure_classes.add("artifact_binding")
            elif not path.is_file():
                blockers.append(f"artifact {artifact_id} does not exist")
                failure_classes.add("artifact_binding")
            elif artifact.get("sha256") and sha256_file(path) != artifact.get("sha256"):
                blockers.append(f"artifact {artifact_id} SHA-256 mismatch")
                failure_classes.add("artifact_binding")
    if validation.valid and payload.get("status") in {"completed", "succeeded"}:
        digests = artifact_digests(payload)
        for claim in payload.get("claims", []):
            if not isinstance(claim, Mapping):
                continue
            status = claim.get("status")
            if status not in {"supported", "verified", "refuted"}:
                continue
            for artifact_id in claim.get("evidence", []):
                if artifact_id not in digests:
                    blockers.append(
                        f"claim {claim.get('claim_id')} uses artifact {artifact_id} without sha256"
                    )
                    failure_classes.add("claim_evidence")
        if payload.get("paper_candidate") is True and not any(
            isinstance(claim, Mapping) and claim.get("status") in {"supported", "verified"}
            for claim in payload.get("claims", [])
        ):
            blockers.append("paper_candidate requires at least one supported or verified claim")
            failure_classes.add("paper_candidate_evidence")
    return GateResult(
        passed=not blockers,
        validation=validation,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        failure_classes=tuple(sorted(failure_classes)),
    )
