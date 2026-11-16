"""Small deterministic gates; scientific judgment stays in agents and lab tools."""

from __future__ import annotations

import tempfile
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


# --------------------------------------------------------------------------- external references
#
# A result may cite a file outside the data/artifact roots that it read but did not make
# (its own job packet, a research line's queue under build/lines). Such a citation is a
# registration matter, settled by the control plane (2026-11-16: an admission review was
# refused whole for citing task-input and queue-source). It is accepted as an
# ``external_reference`` when the file exists, is outside every protected location below,
# and was last modified before the attempt began; the control plane computes its size and
# hash. A file outside the roots that the attempt created or changed is an output written
# to the wrong place and is still refused, as is a missing file or a protected path.

EXTERNAL_REFERENCE_SCHEMA = "openlabs.external_reference.v1"
# Protected locations: never accepted as evidence, whatever their age.
PROTECTED_REFERENCE_ROOTS = (
    "/workspace/secret-key",
    "/workspace/.download-bridge",
    "/root",
    "/home",
    "/etc",
    "/proc",
    "/sys",
    "/dev",
    "/run",
    "/var/run",
    "/boot",
)
PROTECTED_REFERENCE_PARTS = frozenset({
    ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", ".codex", ".claude", ".config",
    ".git", "secret-key", "secrets", "credentials",
})
PROTECTED_REFERENCE_NAMES = frozenset({
    ".env", ".netrc", ".git-credentials", ".pgpass", ".npmrc", ".pypirc", "auth.json",
    "credentials.json", "token.json", "known_hosts", "authorized_keys",
})
PROTECTED_REFERENCE_PREFIXES = ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", ".env.")
PROTECTED_REFERENCE_SUFFIXES = (
    ".pem", ".key", ".p12", ".pfx", ".kdbx", ".gpg", ".asc", ".age",
    ".sqlite", ".sqlite3", ".sqlite-wal", ".sqlite-shm", ".db",
)


def protected_reference(path: Path) -> bool:
    """Whether a resolved path is in the refusal list for external references."""

    text = str(path)
    if any(text == root or text.startswith(root + "/") for root in PROTECTED_REFERENCE_ROOTS):
        # The process temp directory may sit under a home directory; it holds no
        # configuration (the dot-directory and file-name rules below still apply).
        temp = str(Path(tempfile.gettempdir()).resolve())
        in_temp = temp.startswith(("/home/", "/root/")) and text.startswith(temp + "/")
        if not in_temp:
            return True
    if any(part in PROTECTED_REFERENCE_PARTS for part in path.parts[:-1]):
        return True
    name = path.name.lower()
    return (
        name in PROTECTED_REFERENCE_NAMES
        or name.startswith(PROTECTED_REFERENCE_PREFIXES)
        or name.endswith(PROTECTED_REFERENCE_SUFFIXES)
    )


def _local_path(uri: object) -> Path | None:
    parsed = urlparse(str(uri or ""))
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        return None
    return Path(unquote(parsed.path)).resolve()


def _inside_any(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == root or path.is_relative_to(root) for root in roots)


def external_reference_problem(
    path: Path,
    *,
    started: float | None,
    control_plane_inputs: Mapping[Path, float | None] | None = None,
) -> str | None:
    """Why a file outside the roots cannot be cited (``None``: it can)."""

    if protected_reference(path):
        return "is in a protected location (credentials, home or system paths are never evidence)"
    if not path.is_file():
        return "is outside data/artifact roots and does not exist"
    if started is None:
        return "is outside data/artifact roots (no attempt start time to show it is an input)"
    modified = path.stat().st_mtime
    inputs = control_plane_inputs or {}
    if path in inputs:
        # The control plane writes the attempt's own job packet just after the attempt
        # workspace; it counts as an input when unchanged since the agent was launched.
        cutoff = inputs[path]
        if cutoff is None or modified <= cutoff:
            return None
    if modified >= started:
        return (
            "is outside data/artifact roots and was written during this attempt; "
            "write outputs under the attempt's artifact staging"
        )
    return None


def bind_external_references(
    payload: Mapping[str, Any],
    *,
    allowed_roots: tuple[Path, ...],
    started: float | None,
    control_plane_inputs: Mapping[Path, float | None] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Mark citable files outside the roots as control-plane ``external_reference``s.

    Any ``external_reference`` / ``external_reference_refused`` an agent wrote is
    dropped first, so only this function's verdict reaches the gate. Returns the payload
    and one record per accepted reference (path, bytes, sha256 and any hash corrected).
    """

    roots = tuple(root.resolve() for root in allowed_roots)
    bound = dict(payload)
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or not roots:
        return bound, []
    records: list[dict[str, Any]] = []
    rewritten: list[Any] = []
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            rewritten.append(artifact)
            continue
        item = {k: v for k, v in artifact.items()
                if k not in {"external_reference", "external_reference_refused"}}
        path = _local_path(item.get("uri"))
        if path is None or _inside_any(path, roots):
            rewritten.append(item)
            continue
        problem = external_reference_problem(
            path, started=started, control_plane_inputs=control_plane_inputs
        )
        if problem is not None:
            item["external_reference_refused"] = problem
            rewritten.append(item)
            continue
        digest = sha256_file(path)
        declared = str(item.get("sha256") or "")
        stat = path.stat()
        reference = {
            "schema_version": EXTERNAL_REFERENCE_SCHEMA,
            "path": str(path),
            "bytes": stat.st_size,
            "sha256": digest,
            "mtime": stat.st_mtime,
            "basis": (
                "attempt_job_packet" if path in (control_plane_inputs or {})
                else "unchanged_since_attempt_start"
            ),
        }
        if declared != digest:
            reference["declared_sha256"] = declared or None
        item["sha256"] = digest
        item["external_reference"] = reference
        records.append({"artifact_id": item.get("artifact_id"), **reference})
        rewritten.append(item)
    bound["artifacts"] = rewritten
    return bound, records


def _verified_external_reference(artifact: Mapping[str, Any], path: Path) -> bool:
    reference = artifact.get("external_reference")
    return (
        isinstance(reference, Mapping)
        and reference.get("schema_version") == EXTERNAL_REFERENCE_SCHEMA
        and str(reference.get("path") or "") == str(path)
        and reference.get("sha256") == artifact.get("sha256")
        and not protected_reference(path)
        and path.is_file()
        and sha256_file(path) == artifact.get("sha256")
    )


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
                if _verified_external_reference(artifact, path):
                    pass  # a cited input, bound by the control plane
                else:
                    refused = artifact.get("external_reference_refused")
                    if isinstance(refused, str) and refused:
                        detail = refused
                    elif protected_reference(path):
                        detail = external_reference_problem(path, started=None)
                    else:
                        detail = "is outside data/artifact roots"
                    blockers.append(f"artifact {artifact_id} {detail}")
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
