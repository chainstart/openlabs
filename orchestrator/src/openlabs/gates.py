"""Small deterministic gates; scientific judgment stays in agents and lab tools."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .contracts import (
    COMMITTABLE_RESULT_STATUSES,
    PRIMARY_ENDPOINT_VERDICTS,
    ValidationResult,
    artifact_digests,
    sha256_file,
    validate_result_bundle,
)


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


def research_promotion(payload: Mapping[str, Any]) -> bool:
    """A result that would leave research: a paper candidate or an audited terminal freeze."""

    if str(payload.get("status") or "") not in {"completed", "succeeded"}:
        return False
    gate_result = payload.get("gate_result")
    freeze = isinstance(gate_result, Mapping) and (
        str(gate_result.get("promotion_decision") or "").strip().lower() == "freeze"
    )
    return payload.get("paper_candidate") is True or freeze


def preregistration_blockers(
    payload: Mapping[str, Any],
    expected_sha256: str,
) -> list[str]:
    """Pre-registration binding of a research result of an admitted topic.

    ``expected_sha256`` comes from the topic ledger (canonical), never from the
    campaign state an agent can edit. Only a declared hash that differs from the
    ledger blocks: a missing hash is filled in by the control plane
    (:func:`fill_control_plane_fields`), and a missing or ``pending`` verdict is
    read as not yet evaluated (a paper candidate then keeps researching instead of
    entering writing, so nothing is reworded on the way).
    """

    if not research_promotion(payload):
        return []
    blockers: list[str] = []
    verdict = str(payload.get("primary_endpoint_verdict") or "").strip()
    if verdict and verdict not in PRIMARY_ENDPOINT_VERDICTS:
        blockers.append(
            "primary_endpoint_verdict must be met, failed, inconclusive or pending"
        )
    declared = str(payload.get("preregistration_sha256") or "").strip().lower()
    if declared and declared != expected_sha256:
        blockers.append(
            "preregistration_sha256 differs from the pre-registration recorded in the topic ledger"
        )
    return blockers


def preregistration_advisories(payload: Mapping[str, Any]) -> list[str]:
    """What a promoted result should still state; asked once in the same session.

    These never fail a result (see :func:`preregistration_blockers`); the Stop
    hook asks the agent once to state them before it stops.
    """

    if not research_promotion(payload):
        return []
    verdict = str(payload.get("primary_endpoint_verdict") or "").strip()
    if payload.get("paper_candidate") is True and verdict in {"", "pending"}:
        return [
            "paper_candidate: true needs primary_endpoint_verdict met, failed or inconclusive "
            "(with pending the topic keeps researching and does not enter writing)"
        ]
    if not verdict:
        return [
            "a freeze should state primary_endpoint_verdict (met, failed, inconclusive, or "
            "pending when the endpoint was never evaluated)"
        ]
    return []


def fill_control_plane_fields(
    payload: Mapping[str, Any],
    expected_sha256: str | None,
) -> tuple[dict[str, Any], list[str]]:
    """Add the fields of a promoted result the control plane can compute itself."""

    filled = dict(payload)
    notes: list[str] = []
    if expected_sha256 is None or not research_promotion(payload):
        return filled, notes
    if not str(payload.get("preregistration_sha256") or "").strip():
        filled["preregistration_sha256"] = expected_sha256
        notes.append("preregistration_sha256 (from the topic ledger)")
    if not str(payload.get("primary_endpoint_verdict") or "").strip():
        filled["primary_endpoint_verdict"] = "pending"
        notes.append("primary_endpoint_verdict pending (not stated)")
    return filled, notes


def evaluate_result_bundle(
    payload: Mapping[str, Any],
    *,
    allowed_roots: tuple[Path, ...] = (),
    preregistration_sha256: str | None = None,
) -> GateResult:
    validation = validate_result_bundle(payload)
    blockers = list(validation.errors)
    warnings = list(validation.warnings)
    failure_classes: set[str] = {"result_contract"} if validation.errors else set()
    if any(".reproduction" in error for error in validation.errors):
        failure_classes.add("reproducibility")
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
            archive = payload.get("openlabs_archive")
            reproduction = artifact.get("reproduction")
            if isinstance(archive, Mapping) and isinstance(reproduction, Mapping):
                workspace_uri = urlparse(str(reproduction.get("workspace_uri") or ""))
                workspace_path = Path(unquote(workspace_uri.path)).resolve()
                if (
                    workspace_uri.scheme != "file"
                    or workspace_uri.netloc not in {"", "localhost"}
                    or not any(
                        workspace_path == root or workspace_path.is_relative_to(root)
                        for root in roots
                    )
                    or not workspace_path.is_dir()
                ):
                    blockers.append(
                        f"artifact {artifact_id} reproduction workspace is not archived"
                    )
                    failure_classes.add("reproducibility")
                for declared in reproduction.get("inputs", []):
                    if not isinstance(declared, Mapping):
                        continue
                    input_uri = urlparse(str(declared.get("uri") or ""))
                    input_path = Path(unquote(input_uri.path)).resolve()
                    if (
                        input_uri.scheme != "file"
                        or input_uri.netloc not in {"", "localhost"}
                        or not any(
                            input_path == root or input_path.is_relative_to(root) for root in roots
                        )
                        or not input_path.is_file()
                        or sha256_file(input_path) != declared.get("sha256")
                    ):
                        blockers.append(
                            f"artifact {artifact_id} reproduction input "
                            f"{declared.get('path')} is not hash-bound in the archive"
                        )
                        failure_classes.add("reproducibility")
    if validation.valid and payload.get("status") in COMMITTABLE_RESULT_STATUSES:
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
    if validation.valid and preregistration_sha256 is not None:
        problems = preregistration_blockers(payload, preregistration_sha256)
        if problems:
            blockers.extend(problems)
            failure_classes.add("preregistration")
    return GateResult(
        passed=not blockers,
        validation=validation,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        failure_classes=tuple(sorted(failure_classes)),
    )
