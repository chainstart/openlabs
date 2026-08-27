"""Isolated attempt workspaces and immutable result archives.

Research agents are intentionally allowed to create many files, but an interrupted
agent must not mutate the authoritative campaign state.  Each attempt therefore
works on a private copy.  A validated completed result is promoted with one
directory exchange; every other disposition leaves the private tree quarantined.
"""

from __future__ import annotations

import copy
import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .config import WorkspacePaths
from .contracts import atomic_write_json, executable_artifact, sha256_file
from .reproduction import materialize_reproduction

ATTEMPT_SCHEMA = "openlabs.attempt_workspace.v1"
ARCHIVE_SCHEMA = "openlabs.immutable_result_archive.v1"
ARTIFACT_POLICY_SCHEMA = "openlabs.artifact_policy.v1"
CAMPAIGN_ARTIFACT_MANIFEST_SCHEMA = "openlabs.campaign_artifact_manifest.v1"
EXPERIMENT_ARTIFACT_MANIFEST_SCHEMA = "openlabs.experiment_artifact_manifest.v1"
DEFAULT_MAX_DATA_FILE_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_CHANGED_FILES = 1_000
DEFAULT_MAX_CHANGED_BYTES = 50 * 1024 * 1024
_ARTIFACT_ONLY_SUFFIXES = (
    ".7z",
    ".bin",
    ".bz2",
    ".ckpt",
    ".cnf",
    ".db",
    ".drat",
    ".gz",
    ".h5",
    ".hdf5",
    ".jsonl",
    ".log",
    ".mp4",
    ".npy",
    ".npz",
    ".onnx",
    ".out",
    ".parquet",
    ".pickle",
    ".pkl",
    ".pdf",
    ".pth",
    ".pt",
    ".safetensors",
    ".sqlite",
    ".sqlite3",
    ".stdout",
    ".tar",
    ".tar.gz",
    ".tgz",
    ".traj",
    ".wav",
    ".xz",
    ".zst",
    ".zip",
)
_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")
_RENAME_EXCHANGE = 2
_ATTEMPT_RUNTIME_DIRS = frozenset({".agents", ".codex", ".openlabs"})


class AttemptWorkspaceError(RuntimeError):
    """Raised when an attempt cannot be isolated, promoted, or archived."""


@dataclass(frozen=True)
class AttemptWorkspace:
    root: Path
    domain_root: Path
    campaign_root: Path
    canonical_domain_root: Path
    canonical_campaign_root: Path
    metadata_path: Path

    @property
    def artifact_staging_root(self) -> Path:
        """Attempt-private payload staging that is never campaign state."""

        return self.root / "artifact-stage"

    def map_path(self, value: str | Path | None) -> str | None:
        """Map a canonical domain path to its private counterpart when possible."""

        if value is None:
            return None
        raw = str(value).strip()
        if not raw:
            return raw
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            return raw
        resolved = candidate.resolve()
        if resolved == self.canonical_domain_root or resolved.is_relative_to(
            self.canonical_domain_root
        ):
            return str(self.domain_root / resolved.relative_to(self.canonical_domain_root))
        return str(resolved)

    def rewrite_text(self, value: str) -> str:
        """Redirect exact canonical paths embedded in an objective to staging."""

        replacements = (
            (str(self.canonical_campaign_root), str(self.campaign_root)),
            (str(self.canonical_domain_root), str(self.domain_root)),
        )
        rewritten = value
        for source, target in replacements:
            rewritten = rewritten.replace(source, target)
        return rewritten


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _token(value: object, *, prefix: str = "item") -> str:
    raw = str(value)
    cleaned = _SAFE_NAME.sub("-", raw).strip("-._")[:48] or prefix
    digest = hashlib.sha256(raw.encode()).hexdigest()[:12]
    return f"{cleaned}-{digest}"


def artifact_policy_payload() -> dict[str, Any]:
    """Return the versioned storage boundary attached to every new attempt."""

    return {
        "schema_version": ARTIFACT_POLICY_SCHEMA,
        "max_data_file_bytes": DEFAULT_MAX_DATA_FILE_BYTES,
        "max_changed_files": DEFAULT_MAX_CHANGED_FILES,
        "max_changed_bytes": DEFAULT_MAX_CHANGED_BYTES,
        "artifact_only_suffixes": list(_ARTIFACT_ONLY_SUFFIXES),
        "undeclared_staging_policy": "reject",
    }


def _inside(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    base = root.resolve()
    return resolved == base or resolved.is_relative_to(base)


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    os.close(descriptor)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def _link_or_copy_file(source: Path, target: Path) -> None:
    """Atomically hard-link immutable bytes, falling back to a copy across filesystems."""

    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    temporary.unlink()
    try:
        os.link(source, temporary)
        os.replace(temporary, target)
    except OSError:
        temporary.unlink(missing_ok=True)
        _copy_file(source, target)


def _content_object(paths: WorkspacePaths, source: Path, digest: str) -> Path:
    """Materialize one immutable, deduplicated object for verified bytes."""

    target = paths.artifacts / "objects" / "sha256" / digest[:2] / digest / "payload"
    if target.is_file():
        if sha256_file(target) != digest:
            raise AttemptWorkspaceError(f"content-addressed artifact collision: {target}")
    else:
        _copy_file(source, target)
        target.chmod(0o444)
    return target


def _copy_plan_closure(
    canonical_domain_root: Path,
    staged_domain_root: Path,
    plan_path: Path,
) -> Path:
    """Copy the plan plus the small sibling-lane files needed by its validator."""

    if not _inside(plan_path, canonical_domain_root):
        raise AttemptWorkspaceError(f"Production plan is outside its domain: {plan_path}")
    staged_plan = staged_domain_root / plan_path.relative_to(canonical_domain_root)
    _copy_file(plan_path, staged_plan)
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    lanes = payload.get("lanes", []) if isinstance(payload, Mapping) else []
    for item in lanes:
        if not isinstance(item, Mapping):
            continue
        configured = str(item.get("config_path") or "").strip()
        if not configured:
            continue
        lane_path = (plan_path.parent / configured).resolve()
        if not lane_path.is_file() or not _inside(lane_path, canonical_domain_root):
            continue
        staged_lane = staged_domain_root / lane_path.relative_to(canonical_domain_root)
        if not staged_lane.is_file():
            _copy_file(lane_path, staged_lane)
        lane = json.loads(lane_path.read_text(encoding="utf-8"))
        if not isinstance(lane, Mapping):
            continue
        for field in ("program_summary", "paper_seed_registry"):
            configured_file = str(lane.get(field) or "").strip()
            if not configured_file:
                continue
            source = (lane_path.parent / configured_file).resolve()
            if source.is_file() and _inside(source, canonical_domain_root):
                target = staged_domain_root / source.relative_to(canonical_domain_root)
                if not target.is_file():
                    _copy_file(source, target)
    return staged_plan


def _copy_project_closure(
    canonical_domain_root: Path,
    staged_domain_root: Path,
    project_path: Path,
) -> Path:
    """Copy a generic project envelope and its declared read-only config closure."""

    if not _inside(project_path, canonical_domain_root):
        raise AttemptWorkspaceError(f"Project config is outside its domain: {project_path}")
    staged_project = staged_domain_root / project_path.relative_to(canonical_domain_root)
    _copy_file(project_path, staged_project)
    payload = json.loads(project_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise AttemptWorkspaceError(f"Project config is not an object: {project_path}")
    domain_config = payload.get("domain_config")
    if isinstance(domain_config, Mapping):
        configured = str(domain_config.get("path") or "").strip()
        if configured:
            source = (project_path.parent / configured).resolve()
            if not source.is_file() or not _inside(source, canonical_domain_root):
                raise AttemptWorkspaceError(f"Invalid project domain config: {source}")
            if source.name == "production_plan.json":
                _copy_plan_closure(canonical_domain_root, staged_domain_root, source)
            else:
                _copy_file(
                    source,
                    staged_domain_root / source.relative_to(canonical_domain_root),
                )
    research_index = payload.get("research_index")
    if isinstance(research_index, Mapping):
        configured = str(research_index.get("path") or "").strip()
        if configured:
            source = (project_path.parent / configured).resolve()
            if not source.is_file() or not _inside(source, canonical_domain_root):
                raise AttemptWorkspaceError(f"Invalid project research index: {source}")
            _copy_file(
                source,
                staged_domain_root / source.relative_to(canonical_domain_root),
            )
    # Large historical archives remain canonical read-only inputs. Validate
    # their declared closure here, but do not duplicate them into every attempt.
    read_resources = payload.get("read_resources", [])
    if not isinstance(read_resources, list):
        raise AttemptWorkspaceError("Project read_resources must be an array")
    for index, item in enumerate(read_resources):
        if not isinstance(item, Mapping):
            raise AttemptWorkspaceError(f"Invalid project read resource {index}")
        configured = str(item.get("path") or "").strip()
        source = (project_path.parent / configured).resolve()
        workspace_root = canonical_domain_root.parents[2]
        code_root = (workspace_root / "openlabs").resolve()
        if (
            not configured
            or not source.exists()
            or not (source.is_file() or source.is_dir())
            or not (
                _inside(source, canonical_domain_root)
                or _inside(source, code_root)
            )
        ):
            raise AttemptWorkspaceError(f"Invalid project read resource: {source}")
    for item in payload.get("workstreams", []):
        if not isinstance(item, Mapping):
            continue
        configured = str(item.get("state_path") or "").strip()
        if not configured:
            continue
        source = (project_path.parent / configured).resolve()
        if not source.is_file() or not _inside(source, canonical_domain_root):
            raise AttemptWorkspaceError(f"Invalid project workstream state: {source}")
        target = staged_domain_root / source.relative_to(canonical_domain_root)
        if not target.is_file():
            _copy_file(source, target)
    return staged_project


def _tree_manifest(root: Path, *, exclude_results: bool = True) -> dict[str, str]:
    manifest: dict[str, str] = {}
    if not root.is_dir():
        return manifest
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if exclude_results and relative.parts[:1] == ("results",):
            continue
        if relative.parts[:1] and relative.parts[0] in _ATTEMPT_RUNTIME_DIRS:
            continue
        if path.is_symlink():
            raise AttemptWorkspaceError(f"Symlinks are not allowed in campaign state: {path}")
        if path.is_file():
            manifest[relative.as_posix()] = sha256_file(path)
    return manifest


def prepare_attempt_workspace(
    paths: WorkspacePaths,
    task: Mapping[str, Any],
    campaign: Mapping[str, Any],
) -> AttemptWorkspace:
    """Create or recover the private worktree for one leased attempt."""

    attempt_id = str(task.get("current_attempt_id") or "").strip()
    campaign_id = str(task.get("campaign_id") or "").strip()
    domain = str(task.get("domain") or "").strip()
    if not attempt_id or not campaign_id or not domain:
        raise AttemptWorkspaceError("Attempt workspace requires task, campaign, and attempt IDs")
    canonical_domain = (paths.data / "workspaces" / domain).resolve()
    configured_state_root = str(campaign.get("state_path") or "").strip()
    canonical_campaign = (
        Path(configured_state_root).expanduser().resolve()
        if configured_state_root
        else (canonical_domain / campaign_id).resolve()
    )
    if not _inside(canonical_campaign, canonical_domain):
        raise AttemptWorkspaceError("Campaign path escapes its domain workspace")
    canonical_campaign.mkdir(parents=True, exist_ok=True)

    root = (
        paths.artifacts
        / "attempt-workspaces"
        / _token(campaign_id, prefix="campaign")
        / _token(attempt_id, prefix="attempt")
    ).resolve()
    staged_domain = root / "workspaces" / domain
    staged_campaign = staged_domain / canonical_campaign.relative_to(canonical_domain)
    metadata_path = root / "attempt-workspace.json"
    workspace = AttemptWorkspace(
        root=root,
        domain_root=staged_domain,
        campaign_root=staged_campaign,
        canonical_domain_root=canonical_domain,
        canonical_campaign_root=canonical_campaign,
        metadata_path=metadata_path,
    )
    if metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        identity = (
            metadata.get("task_id"),
            metadata.get("campaign_id"),
            metadata.get("attempt_id"),
        )
        expected = (task.get("task_id"), campaign_id, attempt_id)
        if identity != expected or not staged_campaign.is_dir():
            raise AttemptWorkspaceError(f"Attempt workspace identity mismatch: {root}")
        return workspace
    if root.exists():
        raise AttemptWorkspaceError(f"Unrecognized attempt workspace already exists: {root}")

    root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{root.name}.", dir=root.parent))
    try:
        temporary_domain = temporary / "workspaces" / domain
        temporary_campaign = temporary_domain / canonical_campaign.relative_to(canonical_domain)
        (temporary / "artifact-stage").mkdir(parents=True)
        # Prior result bundles are immutable inputs referenced explicitly by the
        # task and must not be recursively recopied into every new attempt.
        shutil.copytree(
            canonical_campaign,
            temporary_campaign,
            ignore=shutil.ignore_patterns("results", *_ATTEMPT_RUNTIME_DIRS),
        )
        plan_value = str(campaign.get("production_plan_path") or "").strip()
        project_value = str(campaign.get("project_config_path") or "").strip()
        staged_plan: Path | None = None
        staged_project: Path | None = None
        if project_value:
            staged_project = _copy_project_closure(
                canonical_domain,
                temporary_domain,
                Path(project_value).expanduser().resolve(),
            )
        if plan_value:
            staged_plan = _copy_plan_closure(
                canonical_domain,
                temporary_domain,
                Path(plan_value).expanduser().resolve(),
            )
        baseline = _tree_manifest(canonical_campaign)
        atomic_write_json(
            temporary / "attempt-workspace.json",
            {
                "schema_version": ATTEMPT_SCHEMA,
                "task_id": task.get("task_id"),
                "campaign_id": campaign_id,
                "attempt_id": attempt_id,
                "domain": domain,
                "status": "active",
                "created_at": _utc_now(),
                "canonical_campaign_root": str(canonical_campaign),
                "staged_campaign_root": str(temporary_campaign),
                "artifact_staging_root": str(root / "artifact-stage"),
                "artifact_policy": artifact_policy_payload(),
                "staged_plan_path": str(staged_plan) if staged_plan else None,
                "staged_project_path": str(staged_project) if staged_project else None,
                "baseline": baseline,
            },
        )
        os.replace(temporary, root)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    # The metadata was written under the temporary name; normalize its recorded
    # paths after the atomic directory rename.
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["staged_campaign_root"] = str(staged_campaign)
    staged_plan = metadata.get("staged_plan_path")
    if isinstance(staged_plan, str) and staged_plan:
        relative = Path(staged_plan).relative_to(temporary)
        metadata["staged_plan_path"] = str(root / relative)
    staged_project = metadata.get("staged_project_path")
    if isinstance(staged_project, str) and staged_project:
        relative = Path(staged_project).relative_to(temporary)
        metadata["staged_project_path"] = str(root / relative)
    atomic_write_json(metadata_path, metadata)
    return workspace


def find_attempt_workspace(
    paths: WorkspacePaths,
    *,
    campaign_id: str,
    attempt_id: str,
) -> AttemptWorkspace | None:
    """Load an existing attempt workspace without creating authoritative state."""

    root = (
        paths.artifacts
        / "attempt-workspaces"
        / _token(campaign_id, prefix="campaign")
        / _token(attempt_id, prefix="attempt")
    ).resolve()
    metadata_path = root / "attempt-workspace.json"
    if not metadata_path.is_file():
        return None
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("schema_version") != ATTEMPT_SCHEMA:
        raise AttemptWorkspaceError(f"Unsupported attempt workspace metadata: {metadata_path}")
    if metadata.get("campaign_id") != campaign_id or metadata.get("attempt_id") != attempt_id:
        raise AttemptWorkspaceError(f"Attempt workspace identity mismatch: {metadata_path}")
    canonical_campaign = Path(str(metadata["canonical_campaign_root"])).resolve()
    staged_campaign = Path(str(metadata["staged_campaign_root"])).resolve()
    domain = str(metadata.get("domain") or "")
    canonical_domain = (paths.data / "workspaces" / domain).resolve()
    staged_domain = root / "workspaces" / domain
    if not _inside(canonical_campaign, canonical_domain) or not _inside(staged_campaign, root):
        raise AttemptWorkspaceError(f"Attempt workspace paths escape their roots: {metadata_path}")
    return AttemptWorkspace(
        root=root,
        domain_root=staged_domain,
        campaign_root=staged_campaign,
        canonical_domain_root=canonical_domain,
        canonical_campaign_root=canonical_campaign,
        metadata_path=metadata_path,
    )


def attempt_output_path(
    workspace: AttemptWorkspace,
    task: Mapping[str, Any],
) -> Path:
    attempt_id = str(task.get("current_attempt_id") or "").strip()
    configured = task.get("requested_output_path")
    if isinstance(configured, str) and configured.strip():
        requested = Path(configured).expanduser().resolve()
        if not _inside(requested, workspace.canonical_campaign_root):
            raise AttemptWorkspaceError(
                f"Requested output is outside its campaign workspace: {requested}"
            )
        mapped = workspace.campaign_root / requested.relative_to(workspace.canonical_campaign_root)
        output = mapped.parent / "attempts" / _token(attempt_id, prefix="attempt") / mapped.name
    else:
        output = (
            workspace.campaign_root
            / "results"
            / _token(task.get("task_id"), prefix="task")
            / "attempts"
            / _token(attempt_id, prefix="attempt")
            / "result.json"
        )
    output = output.resolve()
    if not _inside(output, workspace.campaign_root):
        raise AttemptWorkspaceError(f"Attempt output escapes staging: {output}")
    return output


def _update_metadata(workspace: AttemptWorkspace, **changes: Any) -> dict[str, Any]:
    metadata = json.loads(workspace.metadata_path.read_text(encoding="utf-8"))
    metadata.update(changes)
    atomic_write_json(workspace.metadata_path, metadata)
    return metadata


def quarantine_attempt_workspace(
    paths: WorkspacePaths,
    *,
    campaign_id: str,
    attempt_id: str,
    reason: str,
) -> dict[str, Any] | None:
    root = (
        paths.artifacts
        / "attempt-workspaces"
        / _token(campaign_id, prefix="campaign")
        / _token(attempt_id, prefix="attempt")
    ).resolve()
    metadata_path = root / "attempt-workspace.json"
    if not metadata_path.is_file():
        return None
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("status") in {"promotion_pending", "promotion_pending_db"}:
        workspace = find_attempt_workspace(
            paths,
            campaign_id=campaign_id,
            attempt_id=attempt_id,
        )
        if workspace is None:  # pragma: no cover - metadata was just read above.
            raise AttemptWorkspaceError(f"Attempt workspace disappeared: {root}")
        metadata = recover_attempt_promotion(workspace, database_committed=False)
    if metadata.get("status") == "committed":
        return metadata
    metadata.update(
        {
            "status": "quarantined",
            "quarantined_at": _utc_now(),
            "quarantine_reason": reason,
        }
    )
    atomic_write_json(metadata_path, metadata)
    return metadata


def reactivate_protocol_failed_attempt_workspace(
    paths: WorkspacePaths,
    *,
    campaign_id: str,
    attempt_id: str,
    expected_error_fragment: str,
) -> dict[str, Any]:
    """Reactivate only an attempt quarantined by the named protocol infrastructure error."""

    workspace = find_attempt_workspace(
        paths,
        campaign_id=campaign_id,
        attempt_id=attempt_id,
    )
    if workspace is None:
        raise AttemptWorkspaceError(f"Attempt workspace is missing: {campaign_id}/{attempt_id}")
    metadata = json.loads(workspace.metadata_path.read_text(encoding="utf-8"))
    if metadata.get("status") != "quarantined":
        raise AttemptWorkspaceError(
            f"Attempt is not quarantined: {metadata.get('status')!r}"
        )
    reason = str(metadata.get("quarantine_reason") or "")
    if not expected_error_fragment or expected_error_fragment not in reason:
        raise AttemptWorkspaceError("Attempt quarantine reason does not match protocol failure")
    history = metadata.get("replay_history")
    replay_history = list(history) if isinstance(history, list) else []
    replay_history.append(
        {
            "reactivated_at": _utc_now(),
            "prior_quarantine_reason": reason,
        }
    )
    return _update_metadata(
        workspace,
        status="active",
        quarantine_reason=None,
        quarantined_at=None,
        replay_history=replay_history,
    )


def _rename_exchange(left: Path, right: Path) -> None:
    """Atomically exchange two same-filesystem directories on Linux."""

    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise OSError(errno.ENOSYS, "renameat2 is unavailable")
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        -100,
        os.fsencode(left),
        -100,
        os.fsencode(right),
        _RENAME_EXCHANGE,
    )
    if result != 0:
        value = ctypes.get_errno()
        raise OSError(value, os.strerror(value), f"{left} <-> {right}")


def begin_attempt_promotion(workspace: AttemptWorkspace) -> dict[str, Any]:
    """Exchange staged state into place while retaining an atomic rollback copy."""

    metadata = json.loads(workspace.metadata_path.read_text(encoding="utf-8"))
    if metadata.get("status") in {"promotion_pending_db", "committed"}:
        return metadata
    if metadata.get("status") != "active":
        raise AttemptWorkspaceError(
            f"Attempt is not promotable from status {metadata.get('status')!r}"
        )
    # Keep the storage boundary inside the promotion primitive so maintenance
    # callers cannot accidentally bypass the same gate used by ingestion.
    enforce_campaign_data_boundary(workspace)
    policy = metadata.get("artifact_policy")
    if isinstance(policy, Mapping) and policy.get("schema_version") == ARTIFACT_POLICY_SCHEMA:
        stage_manifest = _artifact_stage_manifest(workspace)
        publication = metadata.get("artifact_publication")
        published_manifest = (
            publication.get("stage_manifest") if isinstance(publication, Mapping) else None
        )
        if stage_manifest and published_manifest != stage_manifest:
            raise AttemptWorkspaceError(
                "artifact staging changed or was not published before promotion"
            )
    baseline = metadata.get("baseline")
    if not isinstance(baseline, dict):
        raise AttemptWorkspaceError("Attempt baseline is missing")
    current = _tree_manifest(workspace.canonical_campaign_root)
    normalized_baseline = {str(key): str(value) for key, value in baseline.items()}
    if current != normalized_baseline:
        raise AttemptWorkspaceError("Canonical campaign changed while the attempt was running")
    staged = _tree_manifest(workspace.campaign_root)
    deleted = sorted(set(normalized_baseline) - set(staged))
    if deleted:
        raise AttemptWorkspaceError(
            "Attempt tried to delete authoritative state: " + ", ".join(deleted[:8])
        )
    changed = sorted(
        relative
        for relative, digest in staged.items()
        if normalized_baseline.get(relative) != digest
    )

    candidate = workspace.canonical_campaign_root.parent / (
        f".openlabs-promote-{_token(metadata.get('attempt_id'), prefix='attempt')}"
    )
    if candidate.exists():
        raise AttemptWorkspaceError(f"Stale promotion candidate exists: {candidate}")
    shutil.copytree(workspace.canonical_campaign_root, candidate)
    exchanged = False
    try:
        for relative in changed:
            _copy_file(workspace.campaign_root / relative, candidate / relative)
        candidate_manifest = _tree_manifest(candidate)
        if candidate_manifest != staged:
            raise AttemptWorkspaceError("Promotion candidate does not match staged campaign state")
        _update_metadata(
            workspace,
            status="promotion_pending",
            promotion_started_at=_utc_now(),
            changed_files=changed,
            promotion_candidate=str(candidate),
        )
        _rename_exchange(candidate, workspace.canonical_campaign_root)
        exchanged = True
        metadata = _update_metadata(
            workspace,
            status="promotion_pending_db",
            promoted_at=_utc_now(),
            rollback_path=str(candidate),
        )
    except Exception as exc:
        if exchanged and candidate.is_dir():
            try:
                _rename_exchange(candidate, workspace.canonical_campaign_root)
            except Exception as rollback_error:  # noqa: BLE001
                raise AttemptWorkspaceError(
                    f"Promotion failed and atomic rollback also failed: {rollback_error}"
                ) from exc
        if candidate.exists():
            shutil.rmtree(candidate, ignore_errors=True)
        current_metadata = json.loads(workspace.metadata_path.read_text(encoding="utf-8"))
        if current_metadata.get("status") == "promotion_pending":
            _update_metadata(workspace, status="active", promotion_candidate=None)
        raise
    return metadata


def finalize_attempt_promotion(workspace: AttemptWorkspace) -> dict[str, Any]:
    """Discard the rollback tree after the database accepted the result."""

    metadata = json.loads(workspace.metadata_path.read_text(encoding="utf-8"))
    if metadata.get("status") == "committed":
        return metadata
    if metadata.get("status") != "promotion_pending_db":
        raise AttemptWorkspaceError(
            f"Attempt promotion is not finalizable from status {metadata.get('status')!r}"
        )
    rollback = Path(str(metadata.get("rollback_path") or "")).resolve()
    expected_parent = workspace.canonical_campaign_root.parent.resolve()
    if rollback.parent != expected_parent or not rollback.name.startswith(".openlabs-promote-"):
        raise AttemptWorkspaceError(f"Unsafe promotion rollback path: {rollback}")
    if rollback.exists():
        shutil.rmtree(rollback)
    policy = metadata.get("artifact_policy")
    compacted: list[str] = []
    if isinstance(policy, Mapping) and policy.get("schema_version") == ARTIFACT_POLICY_SCHEMA:
        for directory in (workspace.root / "workspaces", workspace.artifact_staging_root):
            if directory.exists():
                shutil.rmtree(directory)
                compacted.append(str(directory))
    return _update_metadata(
        workspace,
        status="committed",
        committed_at=_utc_now(),
        compacted_paths=compacted,
        promotion_candidate=None,
        rollback_path=None,
    )


def rollback_attempt_promotion(
    workspace: AttemptWorkspace,
    *,
    reason: str,
) -> dict[str, Any]:
    """Restore the exact pre-promotion campaign after a failed DB commit."""

    metadata = json.loads(workspace.metadata_path.read_text(encoding="utf-8"))
    if metadata.get("status") != "promotion_pending_db":
        return metadata
    rollback = Path(str(metadata.get("rollback_path") or "")).resolve()
    expected_parent = workspace.canonical_campaign_root.parent.resolve()
    if rollback.parent != expected_parent or not rollback.name.startswith(".openlabs-promote-"):
        raise AttemptWorkspaceError(f"Unsafe promotion rollback path: {rollback}")
    if not rollback.is_dir():
        raise AttemptWorkspaceError(f"Promotion rollback tree is missing: {rollback}")
    _rename_exchange(rollback, workspace.canonical_campaign_root)
    shutil.rmtree(rollback)
    return _update_metadata(
        workspace,
        status="quarantined",
        quarantined_at=_utc_now(),
        quarantine_reason=reason,
        promotion_candidate=None,
        rollback_path=None,
    )


def recover_attempt_promotion(
    workspace: AttemptWorkspace,
    *,
    database_committed: bool,
) -> dict[str, Any]:
    """Resolve a crash between filesystem exchange and database finalization."""

    metadata = json.loads(workspace.metadata_path.read_text(encoding="utf-8"))
    status = str(metadata.get("status") or "")
    if status == "promotion_pending_db":
        if database_committed:
            return finalize_attempt_promotion(workspace)
        return rollback_attempt_promotion(
            workspace,
            reason="crash_recovery_before_database_commit",
        )
    if status != "promotion_pending":
        return metadata
    candidate = Path(str(metadata.get("promotion_candidate") or "")).resolve()
    expected_parent = workspace.canonical_campaign_root.parent.resolve()
    if candidate.parent != expected_parent or not candidate.name.startswith(".openlabs-promote-"):
        raise AttemptWorkspaceError(f"Unsafe incomplete promotion candidate: {candidate}")
    baseline = metadata.get("baseline")
    if not isinstance(baseline, dict):
        raise AttemptWorkspaceError("Incomplete promotion has no baseline")
    normalized_baseline = {str(key): str(value) for key, value in baseline.items()}
    canonical_manifest = _tree_manifest(workspace.canonical_campaign_root)
    if candidate.is_dir():
        candidate_manifest = _tree_manifest(candidate)
        if canonical_manifest == normalized_baseline:
            # Crash before the exchange.
            shutil.rmtree(candidate)
        elif candidate_manifest == normalized_baseline:
            # Crash after exchange but before promotion_pending_db metadata.
            _rename_exchange(candidate, workspace.canonical_campaign_root)
            shutil.rmtree(candidate)
        else:
            raise AttemptWorkspaceError(
                "Cannot determine which side of an interrupted promotion is authoritative"
            )
    elif canonical_manifest != normalized_baseline:
        raise AttemptWorkspaceError("Interrupted promotion lost its rollback tree")
    return _update_metadata(
        workspace,
        status="quarantined",
        quarantined_at=_utc_now(),
        quarantine_reason="crash_recovery_incomplete_promotion",
        promotion_candidate=None,
        rollback_path=None,
    )


def promote_attempt_workspace(workspace: AttemptWorkspace) -> dict[str, Any]:
    """Convenience helper for non-DB callers: begin and immediately finalize."""

    begin_attempt_promotion(workspace)
    return finalize_attempt_promotion(workspace)


def _artifact_path(uri: object) -> Path:
    parsed = urlparse(str(uri or ""))
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        raise AttemptWorkspaceError(f"Artifact is not a local file URI: {uri}")
    return Path(unquote(parsed.path)).resolve()


def freeze_result_bundle(
    paths: WorkspacePaths,
    payload: Mapping[str, Any],
    *,
    attempt_id: str,
    source_result_path: Path,
    source_result_sha256: str,
    source_workspace: Path | None = None,
) -> tuple[dict[str, Any], Path, str]:
    """Copy every artifact and replayable dependency closure into an immutable archive."""

    campaign_id = str(payload.get("campaign_id") or "")
    task_id = str(payload.get("task_id") or "")
    archive = (
        paths.artifacts
        / "result-bundles"
        / _token(campaign_id, prefix="campaign")
        / _token(task_id, prefix="task")
        / _token(attempt_id, prefix="attempt")
    ).resolve()
    archive.mkdir(parents=True, exist_ok=True)
    frozen = copy.deepcopy(dict(payload))
    frozen_artifacts: list[dict[str, Any]] = []
    reproduction_manifest: list[dict[str, Any]] = []
    for index, artifact in enumerate(payload.get("artifacts", [])):
        if not isinstance(artifact, Mapping):
            continue
        item = dict(artifact)
        source = _artifact_path(item.get("uri"))
        digest = str(item.get("sha256") or "")
        if not source.is_file() or sha256_file(source) != digest:
            raise AttemptWorkspaceError(
                f"Artifact changed before immutable snapshot: {item.get('artifact_id')}"
            )
        content_object = _content_object(paths, source, digest)
        suffix = source.suffix[:24]
        target = archive / "artifacts" / f"{index:03d}-{digest}{suffix}"
        if target.is_file():
            if sha256_file(target) != digest:
                raise AttemptWorkspaceError(f"Immutable artifact collision: {target}")
        else:
            _link_or_copy_file(content_object, target)
            target.chmod(0o444)
        item["uri"] = target.as_uri()
        if executable_artifact(artifact):
            if source_workspace is None:
                raise AttemptWorkspaceError(
                    f"Executable artifact has no attempt workspace: {item.get('artifact_id')}"
                )
            closure_root = (
                archive
                / "reproductions"
                / _token(item.get("artifact_id"), prefix=f"artifact-{index}")
            )
            try:
                reproduction = materialize_reproduction(
                    artifact,
                    workspace_root=source_workspace,
                    closure_root=closure_root,
                )
            except Exception as exc:
                raise AttemptWorkspaceError(
                    f"Could not materialize reproduction closure for "
                    f"{item.get('artifact_id')}: {exc}"
                ) from exc
            for reproduced_path in sorted((closure_root / "workspace").rglob("*"), reverse=True):
                reproduced_path.chmod(0o444 if reproduced_path.is_file() else 0o555)
            (closure_root / "workspace").chmod(0o555)
            item["reproduction"] = reproduction
            reproduction_manifest.append(
                {
                    "artifact_id": item.get("artifact_id"),
                    "workspace_uri": reproduction["workspace_uri"],
                    "artifact_path": reproduction["artifact_path"],
                    "replay": reproduction["replay"],
                    "inputs": reproduction["inputs"],
                }
            )
        frozen_artifacts.append(item)
    frozen["artifacts"] = frozen_artifacts
    frozen["openlabs_archive"] = {
        "schema_version": ARCHIVE_SCHEMA,
        "attempt_id": attempt_id,
        "source_result_path": str(source_result_path),
        "source_result_sha256": source_result_sha256,
        "archived_at": _utc_now(),
        "reproduction": {
            "required": len(reproduction_manifest),
            "passed": sum(
                1
                for item in reproduction_manifest
                if item.get("replay", {}).get("status") == "passed"
            ),
            "reproducible": all(
                item.get("replay", {}).get("status") == "passed" for item in reproduction_manifest
            ),
        },
    }
    result_path = atomic_write_json(archive / "result.json", frozen)
    result_sha256 = sha256_file(result_path)
    result_path.chmod(0o444)
    atomic_write_json(
        archive / "manifest.json",
        {
            "schema_version": ARCHIVE_SCHEMA,
            "attempt_id": attempt_id,
            "task_id": task_id,
            "campaign_id": campaign_id,
            "result_path": str(result_path),
            "result_sha256": result_sha256,
            "source_result_path": str(source_result_path),
            "source_result_sha256": source_result_sha256,
            "artifacts": [
                {
                    "artifact_id": item.get("artifact_id"),
                    "uri": item.get("uri"),
                    "sha256": item.get("sha256"),
                }
                for item in frozen_artifacts
            ],
            "reproductions": reproduction_manifest,
        },
    )
    return frozen, result_path, result_sha256


def attempt_artifact_policy(workspace: AttemptWorkspace) -> Mapping[str, Any] | None:
    metadata = json.loads(workspace.metadata_path.read_text(encoding="utf-8"))
    policy = metadata.get("artifact_policy")
    if not isinstance(policy, Mapping) or policy.get("schema_version") != ARTIFACT_POLICY_SCHEMA:
        # Attempts created before artifact_policy.v1 remain governed by the
        # contract that was active when their worker started.
        return None
    return policy


def _artifact_declared_sources(payload: Mapping[str, Any]) -> dict[Path, list[dict[str, Any]]]:
    declared: dict[Path, list[dict[str, Any]]] = {}
    for item in payload.get("artifacts", []):
        if not isinstance(item, Mapping):
            continue
        path = _artifact_path(item.get("uri"))
        declared.setdefault(path, []).append(dict(item))
    return declared


def _artifact_stage_manifest(workspace: AttemptWorkspace) -> dict[str, str]:
    staging = workspace.artifact_staging_root.resolve()
    staging.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, str] = {}
    for candidate in sorted(staging.rglob("*")):
        if candidate.is_symlink():
            raise AttemptWorkspaceError(
                f"symlinks are not allowed in artifact staging: {candidate}"
            )
        if candidate.is_file():
            resolved = candidate.resolve()
            if not _inside(resolved, staging):
                raise AttemptWorkspaceError(f"artifact staging path escapes its root: {candidate}")
            manifest[candidate.relative_to(staging).as_posix()] = sha256_file(candidate)
    return manifest


def publish_staged_artifacts(
    paths: WorkspacePaths,
    source_payload: Mapping[str, Any],
    archived_payload: Mapping[str, Any],
    *,
    workspace: AttemptWorkspace,
    attempt_id: str,
) -> Path | None:
    """Publish declared attempt payloads and add only a small campaign reference.

    Bytes staged under ``artifact-stage`` are content-addressed under ``objects``.
    The browsable experiment tree and the staged campaign each receive a small
    manifest. No payload byte is copied into the canonical data tree.
    """

    if attempt_artifact_policy(workspace) is None:
        return None
    staging = workspace.artifact_staging_root.resolve()
    staging.mkdir(parents=True, exist_ok=True)
    stage_manifest = _artifact_stage_manifest(workspace)
    staged_files = tuple((staging / relative).resolve() for relative in stage_manifest)
    declared = _artifact_declared_sources(source_payload)
    declared_staged = {path for path in declared if _inside(path, staging)}
    undeclared = [path for path in staged_files if path not in declared_staged]
    if undeclared:
        relative = [path.relative_to(staging).as_posix() for path in undeclared[:8]]
        raise AttemptWorkspaceError(
            "artifact staging contains files absent from result.artifacts: " + ", ".join(relative)
        )
    missing = [path for path in declared_staged if not path.is_file()]
    if missing:
        raise AttemptWorkspaceError(
            "declared staged artifacts are missing: " + ", ".join(str(path) for path in missing[:8])
        )

    immutable_roots = (
        (paths.artifacts / "objects").resolve(),
        (paths.artifacts / "result-bundles").resolve(),
    )
    for source in declared:
        if _inside(source, staging) or _inside(source, workspace.campaign_root):
            continue
        if any(_inside(source, root) for root in immutable_roots):
            continue
        if _inside(source, paths.artifacts):
            raise AttemptWorkspaceError(
                f"new artifact must use attempt staging, not a live artifact path: {source}"
            )

    if not staged_files:
        _update_metadata(
            workspace,
            artifact_publication={
                "schema_version": EXPERIMENT_ARTIFACT_MANIFEST_SCHEMA,
                "published_at": _utc_now(),
                "stage_manifest": {},
                "experiment_manifest": None,
                "campaign_reference": None,
            },
        )
        return None

    archived_by_id = {
        str(item.get("artifact_id")): item
        for item in archived_payload.get("artifacts", [])
        if isinstance(item, Mapping)
    }
    campaign_id = str(source_payload.get("campaign_id") or "")
    task_id = str(source_payload.get("task_id") or "")
    experiment_dir = (
        paths.artifacts
        / "experiments"
        / _token(campaign_id, prefix="campaign")
        / _token(task_id, prefix="task")
        / _token(attempt_id, prefix="attempt")
    ).resolve()
    entries: list[dict[str, Any]] = []
    for source in staged_files:
        for artifact in declared[source]:
            digest = str(artifact.get("sha256") or "")
            if not digest or sha256_file(source) != digest:
                raise AttemptWorkspaceError(
                    f"staged artifact SHA-256 mismatch: {artifact.get('artifact_id')}"
                )
            target = _content_object(paths, source, digest)
            archived = archived_by_id.get(str(artifact.get("artifact_id")), {})
            entries.append(
                {
                    "artifact_id": artifact.get("artifact_id"),
                    "kind": artifact.get("kind"),
                    "sha256": digest,
                    "bytes": source.stat().st_size,
                    "staged_path": source.relative_to(staging).as_posix(),
                    "filename": source.name,
                    "object_uri": target.resolve().as_uri(),
                    "result_bundle_uri": archived.get("uri"),
                }
            )

    reference_relative = (
        Path("artifact-references")
        / f"{_token(task_id, prefix='task')}-{_token(attempt_id, prefix='attempt')}.json"
    )
    experiment_manifest = experiment_dir / "manifest.json"
    experiment_record = {
        "schema_version": EXPERIMENT_ARTIFACT_MANIFEST_SCHEMA,
        "campaign_id": campaign_id,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "created_at": _utc_now(),
        "campaign_reference_path": reference_relative.as_posix(),
        "artifacts": entries,
    }
    atomic_write_json(experiment_manifest, experiment_record)
    campaign_record = {
        "schema_version": CAMPAIGN_ARTIFACT_MANIFEST_SCHEMA,
        "campaign_id": campaign_id,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "experiment_manifest_uri": experiment_manifest.resolve().as_uri(),
        "artifacts": entries,
    }
    reference = atomic_write_json(workspace.campaign_root / reference_relative, campaign_record)
    _update_metadata(
        workspace,
        artifact_publication={
            "schema_version": EXPERIMENT_ARTIFACT_MANIFEST_SCHEMA,
            "published_at": _utc_now(),
            "stage_manifest": stage_manifest,
            "experiment_manifest": str(experiment_manifest),
            "campaign_reference": str(reference),
        },
    )
    return reference


def enforce_campaign_data_boundary(workspace: AttemptWorkspace) -> tuple[str, ...]:
    """Reject new bulk/generated payloads before the staged campaign is promoted."""

    policy = attempt_artifact_policy(workspace)
    if policy is None:
        return ()
    metadata = json.loads(workspace.metadata_path.read_text(encoding="utf-8"))
    baseline = metadata.get("baseline")
    if not isinstance(baseline, Mapping):
        raise AttemptWorkspaceError("Attempt baseline is missing")
    current = _tree_manifest(workspace.campaign_root)
    changed = sorted(
        relative
        for relative, digest in current.items()
        if str(baseline.get(relative) or "") != digest
    )
    max_file = int(policy.get("max_data_file_bytes") or DEFAULT_MAX_DATA_FILE_BYTES)
    max_files = int(policy.get("max_changed_files") or DEFAULT_MAX_CHANGED_FILES)
    max_bytes = int(policy.get("max_changed_bytes") or DEFAULT_MAX_CHANGED_BYTES)
    suffixes = tuple(
        str(item).lower()
        for item in policy.get("artifact_only_suffixes", _ARTIFACT_ONLY_SUFFIXES)
        if str(item)
    )
    violations: list[str] = []
    total_bytes = 0
    for relative in changed:
        path = workspace.campaign_root / relative
        size = path.stat().st_size
        total_bytes += size
        lowered = relative.lower()
        if size > max_file:
            violations.append(f"{relative} is {size} bytes (limit {max_file})")
        elif any(lowered.endswith(suffix) for suffix in suffixes):
            violations.append(f"{relative} uses artifact-only format")
    if len(changed) > max_files:
        violations.append(f"campaign changed {len(changed)} files (limit {max_files})")
    if total_bytes > max_bytes:
        violations.append(f"campaign changed {total_bytes} bytes (limit {max_bytes})")
    if violations:
        raise AttemptWorkspaceError(
            "campaign data boundary rejected payload; use artifact_staging_root: "
            + "; ".join(violations[:12])
        )
    return tuple(changed)
