"""Immutable manuscript-package handoff to ara-paper-manage's Agent API."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import httpx

from paper_writing.identifiers import PAPER_ID_PATTERN, domain_scoped_parts
from paper_writing.review import (
    CAS_ZONE_1_JOURNAL_VIEW,
    decision_meets_standard_threshold,
    decisions_for_standard,
)
from paper_writing.registry import load_paper_metadata, load_registry, paper_metadata_path


WRITING_REPOSITORY = "chainstart/ara-paper-writing"
HANDOFF_SCHEMA_VERSION = "ara.paper_writing.handoff.v2"
SUPPORTED_HANDOFF_SCHEMAS = {
    "ara.paper_writing.handoff.v1",
    HANDOFF_SCHEMA_VERSION,
}
PAPER_REGISTRY_PATH = re.compile(
    r"^registry/papers/(?P<paper_id>[a-z0-9-]+)\.yaml$"
)
ZERO_GIT_COMMIT = "0" * 40


EXCLUDED_SOURCE_SUFFIXES = {
    ".aux",
    ".blg",
    ".fdb_latexmk",
    ".fls",
    ".log",
    ".out",
    ".rar",
    ".synctex.gz",
    ".tar.gz",
    ".tgz",
    ".toc",
    ".zip",
    ".7z",
}
EXCLUDED_SOURCE_DIRECTORIES = {
    ".git",
    "__pycache__",
    "_build",
    "artifacts",
    "build",
    "supplement",
    "supplementary",
    "supplements",
    "support-materials",
}
EXCLUDED_ROOT_PDFS = {
    "cover_letter.pdf",
    "paper.pdf",
    "supplementary_material.pdf",
}


class HandoffError(RuntimeError):
    """Raised when package construction or API handoff fails."""


class _SignedUploadRetryable(HandoffError):
    """Raised when one fresh signed URL may resolve a transient upload failure."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _signed_upload_url(signed: Mapping[str, Any]) -> str:
    url = next(
        (
            str(signed[key])
            for key in ("signedUrl", "fullSignedURL", "url")
            if signed.get(key)
        ),
        "",
    )
    if not url:
        raise HandoffError("CloudBase did not return a signed upload URL")
    # Some CloudBase SDK releases return a gateway base path that already ends
    # in /v1/storages and then append that prefix a second time.
    return url.replace(
        "/v1/storages/v1/storages/",
        "/v1/storages/",
        1,
    )


def _signed_upload_token_expired(response: httpx.Response) -> bool:
    if response.status_code != 401:
        return False
    parts = [response.text]
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, Mapping):
        parts.extend(str(payload.get(field) or "") for field in ("code", "message"))
        error = payload.get("error")
        if isinstance(error, Mapping):
            parts.extend(str(error.get(field) or "") for field in ("code", "message"))
    detail = " ".join(parts).casefold()
    return "storage_invalid_jwt" in detail and "expired" in detail


def _signed_upload_transient(response: httpx.Response) -> bool:
    """Recognize bounded-retry storage failures without retrying bad requests."""

    if response.status_code in {408, 425, 429} or response.status_code >= 500:
        return True
    parts = [response.text]
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, Mapping):
        parts.extend(str(payload.get(field) or "") for field in ("code", "message"))
        error = payload.get("error")
        if isinstance(error, Mapping):
            parts.extend(str(error.get(field) or "") for field in ("code", "message"))
    detail = " ".join(parts).casefold()
    return "storage_aborted" in detail


def _source_files(manuscript: Path, canonical_pdf: Path) -> Iterable[Path]:
    for path in sorted(manuscript.rglob("*")):
        if not path.is_file() or path.name == ".DS_Store":
            continue
        relative = path.relative_to(manuscript)
        if any(
            part.casefold() in EXCLUDED_SOURCE_DIRECTORIES
            for part in relative.parts[:-1]
        ):
            continue
        name = path.name.casefold()
        if any(name.endswith(suffix) for suffix in EXCLUDED_SOURCE_SUFFIXES):
            continue
        if path.resolve() == canonical_pdf.resolve():
            continue
        if path.parent == manuscript and (
            name in EXCLUDED_ROOT_PDFS
            or (name.startswith("main") and name.endswith(".pdf"))
        ):
            continue
        yield path


def _safe_version(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-") or "1.0.0"


def manuscript_snapshot_sha256(manuscript: Path, canonical_pdf: Path) -> str:
    """Hash the exact manuscript inputs plus the canonical PDF.

    Paths, sizes and bytes are framed explicitly so the digest is stable and
    cannot confuse different file layouts with the same concatenated content.
    A missing PDF is allowed while drafting; adding it later changes the digest
    and therefore prevents release under an earlier quality-gate result.
    """

    files = list(_source_files(manuscript, canonical_pdf))
    if canonical_pdf.is_file():
        files.append(canonical_pdf)
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(manuscript).as_posix()):
        relative = path.relative_to(manuscript).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(path.stat().st_size.to_bytes(8, "big"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _public_records(value: Any, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return records
    for item in value:
        if not isinstance(item, Mapping):
            continue
        record = {field: item[field] for field in fields if item.get(field) is not None}
        if record:
            records.append(record)
    return records


def _title_history(value: Any) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return history
    for item in value:
        if isinstance(item, str) and item.strip():
            history.append({"title": item.strip()})
        elif isinstance(item, Mapping) and str(item.get("title") or "").strip():
            history.append(
                {
                    field: str(item[field])
                    for field in ("title", "changed_at", "valid_from", "valid_to", "reason")
                    if item.get(field) is not None
                }
            )
    return history


def _support_projection(metadata: Mapping[str, Any]) -> dict[str, Any]:
    support = metadata.get("support")
    support = support if isinstance(support, Mapping) else {}
    publication = support.get("publication")
    publication = publication if isinstance(publication, Mapping) else {}
    projected = {
        field: publication[field]
        for field in (
            "mode",
            "mode_label",
            "status",
            "status_label",
            "requires_github",
            "concept_doi",
            "version_doi",
            "record_url",
        )
        if publication.get(field) is not None
    }
    mode = projected.get("mode")
    status = projected.get("status")
    if mode and not projected.get("mode_label"):
        projected["mode_label"] = {
            "zenodo_only": "仅 Zenodo",
            "github_zenodo": "GitHub + Zenodo",
            "not_required": "无需公开发布",
        }.get(str(mode), str(mode))
    if status and not projected.get("status_label"):
        projected["status_label"] = {
            "planned": "已规划",
            "prepared": "已准备",
            "draft": "草稿",
            "published": "已发布",
            "update_required": "需要更新",
            "not_required": "无需归档",
        }.get(str(status), str(status))
    if mode and "requires_github" not in projected:
        projected["requires_github"] = mode == "github_zenodo"
    for service, fields in {
        "zenodo": (
            "environment",
            "concept_doi",
            "concept_doi_url",
            "version_doi",
            "version_doi_url",
            "record_url",
            "version",
            "published_at",
        ),
        "github": ("repository_url", "release_url", "commit"),
    }.items():
        source = publication.get(service)
        if isinstance(source, Mapping):
            projected[service] = {
                field: source[field]
                for field in fields
                if source.get(field) is not None
            }
    result: dict[str, Any] = {"publication": projected}
    if isinstance(support.get("score"), (int, float)):
        result["score"] = support["score"]
    return result


def _release_snapshot(metadata: Mapping[str, Any]) -> dict[str, Any]:
    release = metadata.get("writing_release")
    release = release if isinstance(release, Mapping) else {}
    snapshot = {
        field: release[field]
        for field in (
            "status",
            "target_score",
            "score",
            "venue_type",
            "decision_standard",
            "decision",
            "minimum_decision",
            "revision_rounds_completed",
            "max_revision_rounds",
            "unresolved_review_blockers",
            "reviewed_at",
            "manuscript_snapshot_sha256",
            "manuscript_version",
            "support_package_sha256",
        )
        if release.get(field) is not None
    }
    snapshot["quality_gate_schema"] = "ara.paper_writing.quality_gate.v2"
    review = metadata.get("ara_llm_self_review")
    if isinstance(review, Mapping) and review.get("source"):
        snapshot["review_record"] = str(review["source"])
    elif metadata.get("review_file"):
        snapshot["review_record"] = str(metadata["review_file"])
    return snapshot


def _internal_review_snapshot(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Project the simulated venue reviews without implying external peer review."""

    review = metadata.get("ara_llm_self_review")
    if not isinstance(review, Mapping):
        return {}

    scores = review.get("scores")
    projected_scores = (
        {
            field: scores[field]
            for field in ("clarity", "soundness", "significance", "novelty", "overall")
            if isinstance(scores.get(field), (int, float))
        }
        if isinstance(scores, Mapping)
        else {}
    )
    high_standard = {
        key: value
        for key, value in {
            "view": review.get("high_standard_view"),
            "decision": review.get("high_standard_decision"),
            "confidence": review.get("high_standard_confidence"),
        }.items()
        if value is not None
    }
    cas_zone_1 = {
        key: value
        for key, value in {
            "decision": review.get("cas_zone_1_decision"),
            "confidence": review.get("cas_zone_1_confidence"),
            "basis": review.get("cas_zone_1_basis"),
        }.items()
        if value is not None
    }
    snapshot: dict[str, Any] = {
        "schema_version": "ara.paper_writing.internal_review.v1",
        "simulated_venue_decisions": True,
        "not_external_peer_review": True,
    }
    if projected_scores:
        snapshot["scores"] = projected_scores
    if high_standard:
        snapshot["high_standard"] = high_standard
    if cas_zone_1:
        snapshot["cas_zone_1_journal"] = cas_zone_1
    for field in ("reviewer_role", "rubric_id", "reviewed_at", "source"):
        if review.get(field) is not None:
            snapshot[field] = review[field]
    return snapshot


def build_writing_projection(
    paper_id: str,
    metadata: Mapping[str, Any],
    *,
    origin_commit: str | None,
) -> dict[str, Any]:
    """Build the contact-free Writing-owned projection consumed by Manage."""

    authors = _public_records(
        metadata.get("authors"),
        ("name", "name_zh", "display_name", "affiliation_ids", "corresponding"),
    )
    names = [str(item["name"]) for item in authors if item.get("name")]
    release = _release_snapshot(metadata)
    ready = release.get("status") == "ready"
    version = str(metadata.get("version") or "1.0.0")
    workspace = str(metadata.get("workspace") or f"papers/{paper_id}")
    status_updated_at = metadata.get("status_updated_at")
    work_id = str(metadata.get("work_id") or metadata.get("project_name") or "").strip()
    display_id = str(metadata.get("display_id") or "").strip()
    if not display_id and domain_scoped_parts(paper_id):
        display_id = paper_id
    target_journal = str(metadata.get("target_journal") or "").strip()
    internal_review = _internal_review_snapshot(metadata)
    projection: dict[str, Any] = {
        "id": paper_id,
        "title": str(metadata.get("title") or paper_id),
        "root_path": workspace,
        "metadata": {
            "paper_id": paper_id,
            "project_name": metadata.get("project_name"),
            "created_at": str(metadata["created_at"]) if metadata.get("created_at") else None,
            "domain": metadata.get("domain"),
            "subdomain": metadata.get("subdomain"),
            "title_history": _title_history(metadata.get("title_history")),
            "status_updated_at": str(status_updated_at) if status_updated_at else None,
        },
        "authors": {
            "names": names,
            "people": authors,
            "affiliations": _public_records(
                metadata.get("affiliations"), ("id", "name", "name_zh")
            ),
            "funding": _public_records(
                metadata.get("funding"), ("funder", "grant_number", "statement")
            ),
            "source": "ara-paper-writing registry",
            "status": "declared" if names else "missing",
            "verification_required": not bool(names),
        },
        "self_review": {
            "score": release.get("score"),
            "scale": 10,
            "label": "ARA local LLM self-review",
            "blocking_reason": None if ready else "Writing quality gate is not ready",
        },
        "llm_revision": {
            "status": "passed" if ready else release.get("status"),
            "score": release.get("score"),
            "target_score": release.get("target_score"),
            "decision_standard": release.get("decision_standard"),
            "decision": release.get("decision"),
            "minimum_decision": release.get("minimum_decision"),
            "revision_rounds_completed": release.get("revision_rounds_completed"),
            "max_revision_rounds": release.get("max_revision_rounds"),
            "unresolved_review_blockers": release.get(
                "unresolved_review_blockers", []
            ),
        },
        "readiness": {
            "ready_for_submission": ready,
            "blocking_reason": None if ready else "Writing quality gate is not ready",
        },
        "support": _support_projection(metadata),
        "manuscript": {
            "directory": metadata.get("manuscript_dir"),
            "source": metadata.get("latest_source"),
            "pdf": metadata.get("latest_pdf"),
            "version": {
                "label": version,
                "changed_at": str(status_updated_at) if status_updated_at else None,
                "git_commit": origin_commit,
            },
        },
        "writing_release": release,
        "version": version,
        "project_name": metadata.get("project_name"),
        "created_at": str(metadata["created_at"]) if metadata.get("created_at") else None,
        "domain": metadata.get("domain"),
        "subdomain": metadata.get("subdomain"),
        "status_updated_at": str(status_updated_at) if status_updated_at else None,
        "title_history": _title_history(metadata.get("title_history")),
        "source_snapshot": {
            "repository": WRITING_REPOSITORY,
            "commit": origin_commit,
        },
    }
    if work_id:
        projection["work_id"] = work_id
    if display_id:
        projection["display_id"] = display_id
    if internal_review:
        projection["internal_review"] = internal_review
    if target_journal:
        projected_target: dict[str, Any] = {
            "name": target_journal,
            "source": str(
                metadata.get("target_journal_source") or "ara-paper-writing registry"
            ),
        }
        if metadata.get("target_journal_section"):
            projected_target["section"] = str(metadata["target_journal_section"])
        projection["target_journal"] = projected_target
    return projection


def _paper_projection(
    paper_id: str,
    metadata: Mapping[str, Any],
    *,
    origin_commit: str | None,
) -> dict[str, Any]:
    projection = {
        "paper_id": paper_id,
        "title": str(metadata.get("title") or paper_id),
        "project_name": metadata.get("project_name"),
        "domain": metadata.get("domain"),
        "subdomain": metadata.get("subdomain"),
        "origin_repository": WRITING_REPOSITORY,
        "origin_commit": origin_commit,
        "origin_path": str(metadata.get("workspace") or f"papers/{paper_id}"),
        "writing_metadata": build_writing_projection(
            paper_id, metadata, origin_commit=origin_commit
        ),
    }
    if "target_journal" in metadata:
        target_journal = metadata.get("target_journal")
        projection["target_journal"] = (
            str(target_journal).strip() if target_journal is not None else None
        )
    return projection


def build_handoff_package(
    paper_id: str,
    *,
    root: str | Path,
    output: str | Path,
    revision_request_id: str | None = None,
) -> dict[str, Any]:
    repo_root = Path(root).resolve()
    metadata = load_paper_metadata(paper_id, repo_root)
    manuscript = repo_root / str(
        metadata.get("manuscript_dir") or f"papers/{paper_id}/manuscript"
    )
    pdf_source = repo_root / str(
        metadata.get("latest_pdf") or f"papers/{paper_id}/manuscript/main.pdf"
    )
    if not manuscript.is_dir():
        raise HandoffError(f"Manuscript directory does not exist: {manuscript}")
    if not pdf_source.is_file():
        raise HandoffError(f"Compile the canonical PDF before handoff: {pdf_source}")
    target = Path(output).resolve()
    target.mkdir(parents=True, exist_ok=True)
    source_zip = target / "source.zip"
    files = list(_source_files(manuscript, pdf_source))
    if not files:
        raise HandoffError("No LaTeX source files were found")
    with zipfile.ZipFile(
        source_zip,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(manuscript).as_posix())
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    pdf = target / "paper.pdf"
    shutil.copyfile(pdf_source, pdf)
    source_hash = sha256_file(source_zip)
    pdf_hash = sha256_file(pdf)
    version = str(metadata.get("version") or "1.0.0")
    origin_commit = _git_head(repo_root)
    release = _release_snapshot(metadata)
    release_hash = hashlib.sha256(
        json.dumps(release, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    package_id = (
        f"pkg_{paper_id}_{_safe_version(version)}_"
        f"{source_hash[:6]}{pdf_hash[:6]}{release_hash[:6]}"
    )
    origin = metadata.get("origin") if isinstance(metadata.get("origin"), Mapping) else {}
    manifest = {
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "paper_id": paper_id,
        "package_id": package_id,
        "version": version,
        "revision_request_id": revision_request_id,
        "origin_repository": WRITING_REPOSITORY,
        "origin_commit": origin_commit,
        "legacy_origin": dict(origin),
        "paper": _paper_projection(
            paper_id, metadata, origin_commit=origin_commit
        ),
        "release": release,
        "source": {
            "path": source_zip.name,
            "filename": "source.zip",
            "size": source_zip.stat().st_size,
            "sha256": source_hash,
            "file_count": len(files),
        },
        "pdf": {
            "path": pdf.name,
            "filename": "paper.pdf",
            "size": pdf.stat().st_size,
            "sha256": pdf_hash,
        },
    }
    manifest_path = target / "handoff.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _git_head(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
        value = result.stdout.strip() if result.returncode == 0 else ""
        return value if re.fullmatch(r"[0-9a-f]{40}", value) else None
    except OSError:
        return None


def load_handoff_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path).resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") not in SUPPORTED_HANDOFF_SCHEMAS:
        raise HandoffError("Unsupported handoff manifest")
    for section in ("source", "pdf"):
        artifact = payload.get(section)
        if not isinstance(artifact, dict):
            raise HandoffError(f"{section} metadata is missing")
        local = Path(str(artifact.get("path") or ""))
        if not local.is_absolute():
            local = manifest_path.parent / local
        if not local.is_file():
            raise HandoffError(f"{section} file is missing: {local}")
        if sha256_file(local) != artifact.get("sha256"):
            raise HandoffError(f"{section} SHA-256 no longer matches the manifest")
        # Consumers need a resolved path for upload, while the on-disk manifest
        # stays portable across checkouts and machines.
        artifact["path"] = str(local.resolve())
    return payload


def _git_output(root: Path, arguments: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise HandoffError("Git is required for a finalized release") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "Git command failed"
        raise HandoffError(detail)
    return result.stdout


def _resolve_git_commit(root: Path, revision: str) -> str:
    value = _git_output(root, ["rev-parse", "--verify", f"{revision}^{{commit}}"]).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise HandoffError(f"Git revision is not a full commit: {revision}")
    return value


def changed_registry_paper_ids(
    *,
    root: str | Path,
    base: str,
    head: str,
) -> list[str]:
    """Return paper IDs whose registry records changed between two commits.

    A passing quality gate always updates the canonical per-paper registry record,
    so this is the narrow trigger used by post-push Manage synchronization. Receipt,
    documentation, and unrelated code-only commits do not select papers.
    """

    repo_root = Path(root).resolve()
    head_commit = _resolve_git_commit(repo_root, head)
    if base == ZERO_GIT_COMMIT:
        arguments = [
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-only",
            "--diff-filter=ACMRT",
            "-r",
            "-z",
            head_commit,
            "--",
            "registry/papers",
        ]
    else:
        base_commit = _resolve_git_commit(repo_root, base)
        arguments = [
            "diff",
            "--name-only",
            "--diff-filter=ACMRT",
            "-z",
            base_commit,
            head_commit,
            "--",
            "registry/papers",
        ]
    paper_ids: set[str] = set()
    for path in _git_output(repo_root, arguments).split("\0"):
        match = PAPER_REGISTRY_PATH.fullmatch(path)
        if match and PAPER_ID_PATTERN.fullmatch(match.group("paper_id")):
            paper_ids.add(match.group("paper_id"))
    return sorted(paper_ids)


def validate_metadata_sync_preconditions(
    paper_id: str,
    *,
    root: str | Path,
) -> dict[str, Any]:
    """Validate the committed Writing records used by a metadata-only sync.

    Unlike an immutable handoff, this deliberately does not require a passing
    quality gate or a frozen manuscript package. It only projects committed
    Writing-owned metadata and never sends a Manage lifecycle or submission
    mutation. Manage remains responsible for its own server-side defaults.
    """

    repo_root = Path(root).resolve()
    if not PAPER_ID_PATTERN.fullmatch(paper_id):
        raise HandoffError(f"Invalid paper_id: {paper_id}")
    metadata = load_paper_metadata(paper_id, repo_root)
    origin_commit = _git_head(repo_root)
    if not origin_commit:
        raise HandoffError("Metadata synchronization requires a valid Git HEAD commit")

    registry_path = paper_metadata_path(paper_id, repo_root).resolve()
    scopes = [registry_path.relative_to(repo_root).as_posix()]
    review = metadata.get("ara_llm_self_review")
    if isinstance(review, Mapping) and review.get("source"):
        review_path = (repo_root / str(review["source"])).resolve()
        try:
            review_relative = review_path.relative_to(repo_root).as_posix()
        except ValueError as exc:
            raise HandoffError(
                "Registered quality review must stay inside the Writing repository"
            ) from exc
        if not review_path.is_file():
            raise HandoffError(f"Registered quality review is missing: {review_path}")
        scopes.append(review_relative)

    tracked_output = _git_output(
        repo_root,
        ["ls-files", "--cached", "-z", "--", *scopes],
    )
    tracked = {item for item in tracked_output.split("\0") if item}
    missing = sorted(set(scopes) - tracked)
    if missing:
        raise HandoffError(
            "Writing metadata files are not committed to Git: " + ", ".join(missing)
        )
    status = _git_output(
        repo_root,
        ["status", "--porcelain=v1", "--untracked-files=all", "--", *scopes],
    ).strip()
    if status:
        sample = "; ".join(status.splitlines()[:5])
        raise HandoffError(f"Writing metadata differs from Git HEAD: {sample}")
    return {
        "paper_id": paper_id,
        "origin_commit": origin_commit,
        "registry_sha256": sha256_file(registry_path),
        "metadata": metadata,
    }


def _release_paths(
    paper_id: str,
    repo_root: Path,
    metadata: Mapping[str, Any],
) -> tuple[Path, Path, list[Path]]:
    manuscript = repo_root / str(
        metadata.get("manuscript_dir") or f"papers/{paper_id}/manuscript"
    )
    pdf = repo_root / str(
        metadata.get("latest_pdf") or f"papers/{paper_id}/manuscript/main.pdf"
    )
    if not manuscript.is_dir():
        raise HandoffError(f"Manuscript directory does not exist: {manuscript}")
    if not pdf.is_file():
        raise HandoffError(f"Compile the canonical PDF before release: {pdf}")
    files = [paper_metadata_path(paper_id, repo_root), *_source_files(manuscript, pdf), pdf]
    review_record = _release_snapshot(metadata).get("review_record")
    if review_record:
        review_path = repo_root / str(review_record)
        if not review_path.is_file():
            raise HandoffError(f"Registered quality review is missing: {review_path}")
        files.append(review_path)
    try:
        for path in files:
            path.resolve().relative_to(repo_root)
    except ValueError as exc:
        raise HandoffError("Release files must stay inside the Writing repository") from exc
    return manuscript, pdf, files


def validate_release_preconditions(
    paper_id: str,
    *,
    root: str | Path,
) -> dict[str, Any]:
    """Require a passing, current quality gate and a Git-frozen paper tree."""

    repo_root = Path(root).resolve()
    metadata = load_paper_metadata(paper_id, repo_root)
    release = metadata.get("writing_release")
    if not isinstance(release, Mapping) or release.get("status") != "ready":
        raise HandoffError(
            f"{paper_id} is not release-ready; run and pass the quality gate first"
        )

    settings = load_registry(repo_root, include_local_repositories=False)
    configured_gate = settings.get("quality_gate")
    configured_gate = configured_gate if isinstance(configured_gate, Mapping) else {}
    minimum_score = float(configured_gate.get("minimum_score", 5.0))
    raw_score = release.get("score")
    raw_target_score = release.get("target_score")
    if (
        isinstance(raw_score, bool)
        or not isinstance(raw_score, (int, float))
        or isinstance(raw_target_score, bool)
        or not isinstance(raw_target_score, (int, float))
    ):
        raise HandoffError("Writing quality gate score metadata is incomplete")
    try:
        score = float(raw_score)
        target_score = float(raw_target_score)
    except (TypeError, ValueError) as exc:
        raise HandoffError("Writing quality gate score metadata is incomplete") from exc
    if (
        not math.isfinite(score)
        or not math.isfinite(target_score)
        or target_score < minimum_score
        or target_score > 10
        or score < target_score
        or score > 10
    ):
        raise HandoffError(
            f"Writing quality gate requires at least {minimum_score:g}/10; got {score:g}"
        )

    venue_type = str(release.get("venue_type") or "")
    configured_standard_value = configured_gate.get("decision_standard")
    configured_standard = str(configured_standard_value or venue_type)
    if configured_standard_value is not None:
        release_standard = str(release.get("decision_standard") or "")
        if release_standard != configured_standard:
            raise HandoffError(
                "Writing quality gate uses a stale decision standard; rerun quality-gate"
            )
    else:
        release_standard = str(release.get("decision_standard") or venue_type)
    decision = str(release.get("decision") or "")
    try:
        decisions = (
            decisions_for_standard(release_standard, venue_type=venue_type)
            if venue_type in {"conference", "journal"}
            else ()
        )
    except ValueError:
        decisions = ()
    if configured_standard == CAS_ZONE_1_JOURNAL_VIEW:
        configured_minimum = str(
            configured_gate.get("cas_zone_1_minimum_decision", "minor_revision")
        )
    else:
        configured_minimum = str(
            configured_gate.get(
                "conference_minimum_decision"
                if configured_standard == "conference"
                else "journal_minimum_decision",
                "weak_accept"
                if configured_standard == "conference"
                else "minor_revision",
            )
        )
    if (
        not decisions
        or release_standard != configured_standard
        or decision not in decisions
        or configured_minimum not in decisions
        or not decision_meets_standard_threshold(
            decision,
            configured_minimum,
            release_standard,
            venue_type=venue_type,
        )
    ):
        raise HandoffError(
            "Writing quality-gate decision does not meet the configured review threshold"
        )
    if not str(release.get("reviewed_at") or "").strip():
        raise HandoffError("Writing quality gate is missing reviewed_at")
    gated_version = str(release.get("manuscript_version") or "")
    if not gated_version:
        raise HandoffError(
            "Quality gate is not bound to a paper version; rerun quality-gate"
        )
    if gated_version != str(metadata.get("version") or "1.0.0"):
        raise HandoffError(
            "Paper version changed after the quality review; rerun quality-gate"
        )
    gated_support_sha256 = str(release.get("support_package_sha256") or "")
    if gated_support_sha256:
        support = metadata.get("support")
        support = support if isinstance(support, Mapping) else {}
        publication = support.get("publication")
        publication = publication if isinstance(publication, Mapping) else {}
        current_support_sha256 = str(publication.get("package_sha256") or "")
        if (
            not re.fullmatch(r"[0-9a-f]{64}", gated_support_sha256)
            or current_support_sha256 != gated_support_sha256
        ):
            raise HandoffError(
                "Support package changed after the quality review; rerun quality-gate"
            )

    manuscript, pdf, files = _release_paths(paper_id, repo_root, metadata)
    current_snapshot = manuscript_snapshot_sha256(manuscript, pdf)
    gated_snapshot = str(release.get("manuscript_snapshot_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", gated_snapshot):
        raise HandoffError(
            "Quality gate is not bound to a manuscript snapshot; rerun quality-gate"
        )
    if current_snapshot != gated_snapshot:
        raise HandoffError(
            "Manuscript or PDF changed after the quality review; rerun quality-gate"
        )

    origin_commit = _git_head(repo_root)
    if not origin_commit:
        raise HandoffError("A finalized release requires a valid Git HEAD commit")
    registry_relative = paper_metadata_path(paper_id, repo_root).relative_to(repo_root).as_posix()
    manuscript_relative = manuscript.relative_to(repo_root).as_posix()
    pdf_relative = pdf.relative_to(repo_root).as_posix()
    scopes = list(dict.fromkeys((registry_relative, manuscript_relative, pdf_relative)))
    for path in files:
        relative = path.resolve().relative_to(repo_root).as_posix()
        if not relative.startswith(f"{manuscript_relative}/"):
            scopes.append(relative)
    scopes = list(dict.fromkeys(scopes))
    tracked_output = _git_output(
        repo_root,
        ["ls-files", "--cached", "-z", "--", *scopes],
    )
    tracked = {item for item in tracked_output.split("\0") if item}
    expected = {path.resolve().relative_to(repo_root).as_posix() for path in files}
    missing = sorted(expected - tracked)
    if missing:
        sample = ", ".join(missing[:5])
        suffix = " ..." if len(missing) > 5 else ""
        raise HandoffError(f"Release files are not committed to Git: {sample}{suffix}")
    status = _git_output(
        repo_root,
        ["status", "--porcelain=v1", "--untracked-files=all", "--", *scopes],
    ).strip()
    if status:
        sample = "; ".join(status.splitlines()[:5])
        raise HandoffError(f"Release files differ from Git HEAD: {sample}")
    return {
        "paper_id": paper_id,
        "origin_commit": origin_commit,
        "manuscript_snapshot_sha256": current_snapshot,
        "score": score,
        "target_score": target_score,
        "decision_standard": release_standard,
        "decision": decision,
    }


class ManageApiClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        timeout: float | httpx.Timeout | None = None,
        retry_delays: tuple[float, ...] = (1.0, 3.0),
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        request_timeout = timeout or httpx.Timeout(180.0, connect=15.0)
        self.client = client or httpx.Client(
            timeout=request_timeout,
            follow_redirects=True,
        )
        self.retry_delays = retry_delays
        self.headers = {"Authorization": f"Bearer {api_key}"}

    @classmethod
    def from_environment(
        cls,
        base_url: str,
        *,
        key_environment: str = "ARA_PAPER_MANAGE_API_KEY",
    ) -> "ManageApiClient":
        key = os.environ.get(key_environment, "").strip()
        if not key:
            raise HandoffError(
                f"Missing {key_environment}; keep the Agent API key outside the repository."
            )
        return cls(base_url, key)

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "ManageApiClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def list_revision_requests(
        self,
        *,
        status: str = "open",
        paper_id: str | None = None,
    ) -> list[dict[str, Any]]:
        params = {"status": status}
        if paper_id:
            params["paper_id"] = paper_id
        data = self._request("GET", "/v1/revision-requests", params=params)
        return [dict(item) for item in data if isinstance(item, Mapping)]

    def claim_revision(self, request_id: str, *, claimed_by: str) -> dict[str, Any]:
        return dict(
            self._request(
                "POST",
                f"/v1/revision-requests/{request_id}/claim",
                json={"claimed_by": claimed_by},
                idempotency_key=f"claim:{request_id}:{claimed_by}",
            )
        )

    def sync_paper(self, manifest: Mapping[str, Any]) -> dict[str, Any]:
        paper = manifest.get("paper")
        if not isinstance(paper, Mapping):
            raise HandoffError("Handoff manifest is missing the Writing paper projection")
        paper_id = str(manifest["paper_id"])
        if paper.get("paper_id") != paper_id:
            raise HandoffError("Handoff paper projection does not match paper_id")
        body = dict(paper)
        self._request(
            "POST",
            "/v1/papers",
            json=body,
            idempotency_key=f"paper:{paper_id}:register",
        )
        body.pop("paper_id", None)
        projection_digest = hashlib.sha256(
            json.dumps(
                body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()[:16]
        return dict(
            self._request(
                "PATCH",
                f"/v1/papers/{paper_id}",
                json=body,
                idempotency_key=(
                    f"paper:{paper_id}:sync:{manifest['package_id']}:{projection_digest}"
                ),
            )
        )

    def sync_writing_projection(
        self,
        paper_id: str,
        paper: Mapping[str, Any],
        *,
        origin_commit: str,
    ) -> dict[str, Any] | None:
        """Patch only Writing-owned paper metadata on an existing Manage paper.

        A missing paper is left untouched so draft registry commits do not create
        Manage records or assignments before the immutable ready-paper workflow.
        """

        if paper.get("paper_id") != paper_id:
            raise HandoffError("Writing paper projection does not match paper_id")
        body = dict(paper)
        body.pop("paper_id", None)
        projection_digest = hashlib.sha256(
            json.dumps(
                body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()[:16]
        result = self._request(
            "PATCH",
            f"/v1/papers/{paper_id}",
            json=body,
            idempotency_key=(
                f"paper:{paper_id}:writing:{origin_commit}:{projection_digest}"
            ),
            allow_not_found=True,
        )
        return dict(result) if isinstance(result, Mapping) else None

    def push_package(self, manifest: Mapping[str, Any]) -> dict[str, Any]:
        paper_id = str(manifest["paper_id"])
        package_id = str(manifest["package_id"])
        source = manifest["source"]
        pdf = manifest["pdf"]
        registration_body = {
            "package_id": package_id,
            "version": manifest["version"],
            "revision_request_id": manifest.get("revision_request_id"),
            "origin_repository": manifest.get("origin_repository"),
            "origin_commit": manifest.get("origin_commit"),
            "release_metadata": manifest.get("release") or {},
            "source_sha256": source["sha256"],
            "source_size": source["size"],
            "pdf_sha256": pdf["sha256"],
            "pdf_size": pdf["size"],
        }
        registration_key = f"package:{package_id}:register"

        def register_package() -> Any:
            return self._request(
                "POST",
                f"/v1/papers/{paper_id}/packages",
                json=registration_body,
                idempotency_key=registration_key,
            )

        registration = register_package()
        upload = registration.get("upload") if isinstance(registration, Mapping) else None
        if isinstance(upload, Mapping):
            artifacts = (
                ("source", Path(source["path"]), "application/zip"),
                ("pdf", Path(pdf["path"]), "application/pdf"),
            )
            for artifact, path, content_type in artifacts:
                if artifact not in upload:
                    raise HandoffError(
                        f"Manage API did not return a signed {artifact} upload URL"
                    )
                signed = upload[artifact]
                if signed is None:
                    # Manage verified that the immutable object already exists.
                    continue
                if not isinstance(signed, Mapping):
                    raise HandoffError(
                        f"Manage API did not return a signed {artifact} upload URL"
                    )
                try:
                    self._put_signed(signed, path, content_type)
                except _SignedUploadRetryable:
                    # Re-register the same immutable package and retry only the
                    # failed artifact once. This refreshes an expired signature
                    # and also verifies whether a transient storage timeout
                    # committed the exact bytes despite its error response. A
                    # successfully uploaded sibling is never overwritten.
                    registration = register_package()
                    refreshed = (
                        registration.get("upload")
                        if isinstance(registration, Mapping)
                        else None
                    )
                    if not isinstance(refreshed, Mapping):
                        raise HandoffError(
                            "Manage API did not return refreshed signed upload URLs"
                        )
                    if artifact not in refreshed:
                        raise HandoffError(
                            f"Manage API did not refresh the signed {artifact} upload URL"
                        )
                    signed = refreshed[artifact]
                    if signed is None:
                        # The failed request may have reached storage despite its
                        # response; the server has now verified the exact bytes.
                        upload = refreshed
                        continue
                    if not isinstance(signed, Mapping):
                        raise HandoffError(
                            f"Manage API did not refresh the signed {artifact} upload URL"
                        )
                    self._put_signed(signed, path, content_type)
                    upload = refreshed
        return dict(
            self._request(
                "POST",
                f"/v1/papers/{paper_id}/packages/{package_id}/complete",
                json={},
                idempotency_key=f"package:{package_id}:complete",
            )
        )

    def _put_signed(
        self,
        signed: Mapping[str, Any],
        path: Path,
        content_type: str,
    ) -> None:
        url = _signed_upload_url(signed)
        with path.open("rb") as handle:
            response = self.client.put(
                url,
                content=handle,
                headers={
                    "Content-Type": content_type,
                    "Content-Length": str(path.stat().st_size),
                },
            )
        if response.status_code >= 400:
            message = (
                f"Signed upload failed ({response.status_code}): {response.text[:500]}"
            )
            if _signed_upload_token_expired(response) or _signed_upload_transient(
                response
            ):
                raise _SignedUploadRetryable(message)
            raise HandoffError(message)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
        allow_not_found: bool = False,
    ) -> Any:
        headers = dict(self.headers)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        retryable_request = method.upper() in {"GET", "HEAD", "OPTIONS"} or bool(
            idempotency_key
        )
        response: httpx.Response | None = None
        attempts = len(self.retry_delays) + 1 if retryable_request else 1
        for attempt in range(attempts):
            try:
                response = self.client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=headers,
                    json=dict(json) if json is not None else None,
                    params=dict(params) if params is not None else None,
                )
            except httpx.TransportError as exc:
                if attempt + 1 >= attempts:
                    raise HandoffError(
                        f"Manage API transport failure after {attempt + 1} "
                        f"attempt(s): {exc}"
                    ) from exc
                time.sleep(self.retry_delays[attempt])
                continue
            if (
                response.status_code in {408, 425, 429, 500, 502, 503, 504}
                and attempt + 1 < attempts
            ):
                time.sleep(self.retry_delays[attempt])
                continue
            break
        if response is None:  # pragma: no cover - loop always attempts once
            raise HandoffError("Manage API request produced no response")
        try:
            payload = response.json()
        except ValueError as exc:
            raise HandoffError(
                f"Manage API returned non-JSON ({response.status_code})"
            ) from exc
        if response.status_code == 404 and allow_not_found:
            return None
        if response.status_code >= 400:
            error = payload.get("error", {}) if isinstance(payload, Mapping) else {}
            raise HandoffError(
                f"Manage API {error.get('code', response.status_code)}: "
                f"{error.get('message', response.text[:500])}"
            )
        return payload.get("data") if isinstance(payload, Mapping) else payload


def _manage_summary(value: Mapping[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: value[field] for field in fields if value.get(field) is not None}


def save_release_receipt(
    manifest: Mapping[str, Any],
    *,
    manage_paper: Mapping[str, Any],
    manage_package: Mapping[str, Any],
    root: str | Path,
    receipt_dir: str | Path | None = None,
    manage_api_url: str,
) -> tuple[Path, dict[str, Any]]:
    repo_root = Path(root).resolve()
    target_dir = (
        Path(receipt_dir).resolve()
        if receipt_dir
        else repo_root / "papers" / str(manifest["paper_id"]) / "releases"
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = target_dir / f"{manifest['package_id']}.json"
    receipt = {
        "schema_version": "ara.paper_writing.release_receipt.v1",
        "paper_id": manifest["paper_id"],
        "package_id": manifest["package_id"],
        "version": manifest["version"],
        "released_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "manage_api_url": manage_api_url.rstrip("/"),
        "origin_repository": manifest.get("origin_repository"),
        "origin_commit": manifest.get("origin_commit"),
        "release": dict(manifest.get("release") or {}),
        "source": {
            "filename": manifest["source"]["filename"],
            "size": manifest["source"]["size"],
            "sha256": manifest["source"]["sha256"],
        },
        "pdf": {
            "filename": manifest["pdf"]["filename"],
            "size": manifest["pdf"]["size"],
            "sha256": manifest["pdf"]["sha256"],
        },
        "manage": {
            "paper": _manage_summary(
                manage_paper,
                ("paper_id", "current_package_id", "lifecycle_status", "updated_at"),
            ),
            "package": _manage_summary(
                manage_package,
                ("id", "package_id", "status", "completed_at"),
            ),
        },
    }
    if receipt_path.exists():
        existing = json.loads(receipt_path.read_text(encoding="utf-8"))
        identity = (
            "paper_id",
            "package_id",
            "version",
            "origin_repository",
            "origin_commit",
            "source",
            "pdf",
            "release",
        )
        if any(existing.get(field) != receipt.get(field) for field in identity):
            raise HandoffError(f"Existing release receipt conflicts: {receipt_path}")
        return receipt_path, existing
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt_path, receipt


def release_handoff(
    paper_id: str,
    *,
    root: str | Path,
    client: ManageApiClient,
    revision_request_id: str | None = None,
    receipt_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Validate, build, synchronize and receipt one finalized paper version."""

    before = validate_release_preconditions(paper_id, root=root)
    with tempfile.TemporaryDirectory(prefix=f"ara-{paper_id}-release-") as temporary:
        build_handoff_package(
            paper_id,
            root=root,
            output=temporary,
            revision_request_id=revision_request_id,
        )
        manifest = load_handoff_manifest(Path(temporary) / "handoff.json")
        after = validate_release_preconditions(paper_id, root=root)
        if before != after or manifest.get("origin_commit") != before["origin_commit"]:
            raise HandoffError("Paper or Git HEAD changed while the release was being built")
        manage_paper = client.sync_paper(manifest)
        manage_package = client.push_package(manifest)
        receipt_path, _ = save_release_receipt(
            manifest,
            manage_paper=manage_paper,
            manage_package=manage_package,
            root=root,
            receipt_dir=receipt_dir,
            manage_api_url=client.base_url,
        )
    return {
        "paper_id": paper_id,
        "package_id": manifest["package_id"],
        "version": manifest["version"],
        "score": manifest["release"].get("score"),
        "origin_commit": manifest["origin_commit"],
        "manage_package_status": manage_package.get("status"),
        "receipt": str(receipt_path),
    }


def sync_handoff_metadata(
    paper_id: str,
    *,
    root: str | Path,
    client: ManageApiClient,
) -> dict[str, Any]:
    """Refresh mutable paper metadata without replacing an immutable package."""

    before = validate_release_preconditions(paper_id, root=root)
    with tempfile.TemporaryDirectory(prefix=f"ara-{paper_id}-metadata-") as temporary:
        build_handoff_package(paper_id, root=root, output=temporary)
        manifest = load_handoff_manifest(Path(temporary) / "handoff.json")
        after = validate_release_preconditions(paper_id, root=root)
        if before != after or manifest.get("origin_commit") != before["origin_commit"]:
            raise HandoffError("Paper or Git HEAD changed while metadata was being synchronized")
        manage_paper = client.sync_paper(manifest)
    return {
        "paper_id": paper_id,
        "package_id": manifest["package_id"],
        "version": manifest["version"],
        "origin_commit": manifest["origin_commit"],
        "manage_lifecycle_status": manage_paper.get("lifecycle_status"),
    }


def sync_writing_metadata(
    paper_id: str,
    *,
    root: str | Path,
    client: ManageApiClient,
) -> dict[str, Any]:
    """Synchronize a committed Writing projection without requiring readiness.

    This updates scores, target venue, authorship and readiness metadata only. It
    neither uploads a package nor sends assignment, lifecycle, or submission fields.
    """

    before = validate_metadata_sync_preconditions(paper_id, root=root)
    metadata = before["metadata"]
    projection = _paper_projection(
        paper_id,
        metadata,
        origin_commit=str(before["origin_commit"]),
    )
    after = validate_metadata_sync_preconditions(paper_id, root=root)
    if any(
        before[field] != after[field]
        for field in ("origin_commit", "registry_sha256")
    ):
        raise HandoffError(
            "Paper registry or Git HEAD changed while metadata was being prepared"
        )
    manage_paper = client.sync_writing_projection(
        paper_id,
        projection,
        origin_commit=str(before["origin_commit"]),
    )
    if manage_paper is None:
        return {
            "paper_id": paper_id,
            "origin_commit": before["origin_commit"],
            "status": "skipped",
            "reason": "not_registered_in_manage",
        }
    release = metadata.get("writing_release")
    release = release if isinstance(release, Mapping) else {}
    return {
        "paper_id": paper_id,
        "origin_commit": before["origin_commit"],
        "status": "synchronized",
        "score": release.get("score"),
        "manage_lifecycle_status": manage_paper.get("lifecycle_status"),
    }


def sync_writing_metadata_batch(
    paper_ids: Iterable[str],
    *,
    root: str | Path,
    client: ManageApiClient,
) -> dict[str, Any]:
    """Synchronize Writing projections for a deterministic set of paper IDs."""

    candidates = sorted(
        {str(paper_id).strip() for paper_id in paper_ids if str(paper_id).strip()}
    )
    synchronized: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for paper_id in candidates:
        try:
            result = sync_writing_metadata(paper_id, root=root, client=client)
            if result.get("status") == "skipped":
                skipped.append(result)
            else:
                synchronized.append(result)
        except (HandoffError, OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append({"paper_id": paper_id, "error": str(exc)})
    return {
        "candidates": candidates,
        "synchronized": synchronized,
        "skipped": skipped,
        "errors": errors,
        "ok": not errors,
    }


def _default_release_receipt(
    repo_root: Path,
    paper_id: str,
    package_id: str,
) -> Path:
    return repo_root / "papers" / paper_id / "releases" / f"{package_id}.json"


def _receipt_matches_manifest(
    receipt: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> bool:
    # ``release`` is the historical gate snapshot captured by the immutable
    # receipt. A later fresh review may change only mutable Writing metadata;
    # artifact identity remains the paper/version plus exact source/PDF bytes.
    if receipt.get("package_id") != manifest.get("package_id"):
        return False
    return _receipt_matches_artifacts(receipt, manifest)


def _receipt_matches_artifacts(
    receipt: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> bool:
    """Match immutable manuscript bytes independently of mutable gate metadata."""

    if any(
        receipt.get(field) != manifest.get(field)
        for field in ("paper_id", "version")
    ):
        return False
    for section in ("source", "pdf"):
        receipt_artifact = receipt.get(section)
        manifest_artifact = manifest.get(section)
        if not isinstance(receipt_artifact, Mapping) or not isinstance(
            manifest_artifact, Mapping
        ):
            return False
        for field in ("filename", "size", "sha256"):
            if receipt_artifact.get(field) != manifest_artifact.get(field):
                return False
    return True


def plan_ready_handoffs(
    paper_ids: Iterable[str],
    *,
    root: str | Path,
) -> dict[str, Any]:
    """Plan idempotent Manage synchronization for explicit paper IDs.

    Non-ready papers are ignored. A ready paper must satisfy the same immutable
    Git/snapshot checks as ``handoff release``. A matching committed package receipt
    changes the operation into a metadata-only refresh, so registry fields such as
    an explicitly selected target journal are not hidden by package idempotency.
    """

    repo_root = Path(root).resolve()
    candidates = sorted(
        {
            str(paper_id).strip()
            for paper_id in paper_ids
            if str(paper_id).strip()
        }
    )
    pending: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for paper_id in candidates:
        if not PAPER_ID_PATTERN.fullmatch(paper_id):
            errors.append({"paper_id": paper_id, "error": "invalid paper_id"})
            continue
        try:
            metadata = load_paper_metadata(paper_id, repo_root)
            release = metadata.get("writing_release")
            release = release if isinstance(release, Mapping) else {}
            status = str(release.get("status") or "draft")
            if status != "ready":
                skipped.append(
                    {"paper_id": paper_id, "reason": "not_ready", "status": status}
                )
                continue
            validate_release_preconditions(paper_id, root=repo_root)
            with tempfile.TemporaryDirectory(
                prefix=f"ara-{paper_id}-handoff-plan-"
            ) as temporary:
                manifest = build_handoff_package(
                    paper_id,
                    root=repo_root,
                    output=temporary,
                )
            receipt_path = _default_release_receipt(
                repo_root, paper_id, str(manifest["package_id"])
            )
            if receipt_path.is_file():
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                if not isinstance(receipt, Mapping) or not _receipt_matches_manifest(
                    receipt, manifest
                ):
                    raise HandoffError(
                        f"Existing release receipt conflicts: {receipt_path}"
                    )
                pending.append(
                    {
                        "paper_id": paper_id,
                        "package_id": manifest["package_id"],
                        "version": manifest["version"],
                        "mode": "metadata_only",
                        "receipt": str(receipt_path),
                    }
                )
                continue
            historical_receipt = None
            for candidate in sorted(receipt_path.parent.glob("*.json")):
                try:
                    receipt = json.loads(candidate.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise HandoffError(
                        f"Existing release receipt is unreadable: {candidate}"
                    ) from exc
                if isinstance(receipt, Mapping) and _receipt_matches_artifacts(
                    receipt, manifest
                ):
                    historical_receipt = (candidate, receipt)
                    break
            if historical_receipt is not None:
                candidate, receipt = historical_receipt
                pending.append(
                    {
                        "paper_id": paper_id,
                        "package_id": receipt.get("package_id"),
                        "version": manifest["version"],
                        "mode": "metadata_only",
                        "receipt": str(candidate),
                    }
                )
                continue
            pending.append(
                {
                    "paper_id": paper_id,
                    "package_id": manifest["package_id"],
                    "version": manifest["version"],
                    "mode": "release",
                }
            )
        except (HandoffError, OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append({"paper_id": paper_id, "error": str(exc)})
    return {
        "candidates": candidates,
        "pending": pending,
        "skipped": skipped,
        "errors": errors,
    }


def execute_ready_handoff_plan(
    plan: Mapping[str, Any],
    *,
    root: str | Path,
    client: ManageApiClient,
) -> dict[str, Any]:
    """Execute a plan while retaining receipts from each successful paper."""

    released: list[dict[str, Any]] = []
    metadata_synced: list[dict[str, Any]] = []
    errors = [dict(item) for item in plan.get("errors", []) if isinstance(item, Mapping)]
    pending = plan.get("pending")
    pending = pending if isinstance(pending, list) else []
    for item in pending:
        if not isinstance(item, Mapping):
            errors.append({"paper_id": "", "error": "invalid handoff plan item"})
            continue
        paper_id = str(item.get("paper_id") or "")
        mode = str(item.get("mode") or "release")
        try:
            if mode == "release":
                released.append(release_handoff(paper_id, root=root, client=client))
            elif mode == "metadata_only":
                metadata_synced.append(
                    sync_handoff_metadata(paper_id, root=root, client=client)
                )
            else:
                raise HandoffError(f"Unsupported handoff plan mode: {mode}")
        except (HandoffError, OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append({"paper_id": paper_id, "error": str(exc)})
    return {
        "candidates": list(plan.get("candidates") or []),
        "released": released,
        "metadata_synced": metadata_synced,
        "skipped": list(plan.get("skipped") or []),
        "errors": errors,
        "ok": not errors,
    }


def save_revision_requests(
    requests: Iterable[Mapping[str, Any]],
    *,
    root: str | Path,
) -> list[Path]:
    repo_root = Path(root).resolve()
    written: list[Path] = []
    for item in requests:
        paper_id = str(item.get("paper_id") or "")
        request_id = str(item.get("request_id") or "")
        if not PAPER_ID_PATTERN.fullmatch(paper_id):
            raise HandoffError(f"Invalid paper_id from Manage API: {paper_id}")
        if not re.fullmatch(r"[A-Za-z0-9._-]+", request_id):
            raise HandoffError(f"Invalid request_id from Manage API: {request_id}")
        target = (
            repo_root
            / "papers"
            / paper_id
            / "revisions"
            / "external"
            / f"{request_id}.json"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(dict(item), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        written.append(target)
    return written
