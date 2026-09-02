"""Safe, account-later Zenodo deposit support for the paper inventory.

The module deliberately separates local planning from external mutation:
planning never requires a token, draft creation is reversible, and publishing
requires explicit human authorization in addition to the passing quality gate
that `publish_zenodo_release` revalidates against the frozen manuscript, Git
state and remote package hashes.
Tokens are read only from the environment and are never written to repository
files or command output.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import quote, urlparse

import httpx

from paper_writing.inventory import build_inventory, default_repo_root, load_config
from paper_writing.registry import load_paper_metadata, write_paper_metadata
from paper_writing.support_policy import (
    effective_publication_license,
    publication_policy,
)
from paper_writing.support import (
    SupportPackageError,
    build_support_archive,
    git_head,
    md5_file,
    resolve_support_sources,
    sha256_file,
    validate_git_frozen_paths,
    verify_support_archive,
)


ZENODO_ENVIRONMENTS = {
    "sandbox": {
        "api_url": "https://sandbox.zenodo.org/api",
        "token_env": "ZENODO_SANDBOX_ACCESS_TOKEN",
        "doi_prefix": "10.5072/zenodo.",
    },
    "production": {
        "api_url": "https://zenodo.org/api",
        "token_env": "ZENODO_ACCESS_TOKEN",
        "doi_prefix": "10.5281/zenodo.",
    },
}
MAX_FILES = 100
MAX_TOTAL_BYTES = 50_000_000_000
TRANSIENT_METADATA_STATUS_MARKERS = ("HTTP 502:", "HTTP 503:", "HTTP 504:")
ZENODO_IDENTITY_FIELDS = (
    "title",
    "version",
    "upload_type",
    "publication_type",
    "publication_date",
    "access_right",
    "license",
)


class ZenodoError(RuntimeError):
    """Raised when local validation or a Zenodo API operation fails."""


def token_environment_name(environment: str) -> str:
    return str(_environment(environment)["token_env"])


def token_from_environment(environment: str) -> str:
    variable = token_environment_name(environment)
    token = os.environ.get(variable, "").strip()
    if not token:
        raise ZenodoError(f"Missing {variable}; keep the token in the environment, not in the repository.")
    return token


def find_paper_record(
    paper_id: str,
    *,
    repo_root: str | Path | None = None,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(repo_root or default_repo_root()).resolve()
    config = load_config(config_path or root / "registry" / "settings.yaml")
    payload = build_inventory(root, config=config, paper_ids=[paper_id])
    for paper in payload.get("papers", []):
        if isinstance(paper, dict) and paper.get("id") == paper_id:
            return paper
    raise ZenodoError(f"Unknown registered paper_id: {paper_id}")


def build_zenodo_metadata(
    record: Mapping[str, Any], *, default_license: str | None = None
) -> dict[str, Any]:
    support = record.get("support") if isinstance(record.get("support"), Mapping) else {}
    publication = support.get("publication") if isinstance(support.get("publication"), Mapping) else {}
    mode = publication.get("mode")
    if mode == "not_required":
        raise ZenodoError("This paper is marked as not requiring public support-material publication.")
    zenodo = publication.get("zenodo") if isinstance(publication.get("zenodo"), Mapping) else {}
    authors = record.get("authors") if isinstance(record.get("authors"), Mapping) else {}
    people = authors.get("people") if isinstance(authors.get("people"), list) else []
    affiliations = authors.get("affiliations") if isinstance(authors.get("affiliations"), list) else []
    affiliation_by_id = {
        str(item.get("id")): str(item.get("name"))
        for item in affiliations
        if isinstance(item, Mapping) and item.get("id") and item.get("name")
    }
    creators: list[dict[str, str]] = []
    for person in people:
        if not isinstance(person, Mapping):
            continue
        name = str(person.get("name") or "").strip()
        if not name or _anonymous_name(name):
            continue
        creator = {"name": _zenodo_person_name(name)}
        affiliation_ids = person.get("affiliation_ids")
        if isinstance(affiliation_ids, list):
            matched = [affiliation_by_id.get(str(value)) for value in affiliation_ids]
            matched = [value for value in matched if value]
            if matched:
                creator["affiliation"] = "; ".join(matched)
        orcid = person.get("orcid")
        if isinstance(orcid, str) and orcid.strip():
            creator["orcid"] = orcid.strip().removeprefix("https://orcid.org/")
        creators.append(creator)
    if not creators:
        names = authors.get("names") if isinstance(authors.get("names"), list) else []
        creators = [
            {"name": _zenodo_person_name(str(name))}
            for name in names
            if str(name).strip() and not _anonymous_name(str(name))
        ]
    if not creators:
        raise ZenodoError("Zenodo metadata requires at least one non-anonymous creator.")

    title = str(zenodo.get("title") or f"{record.get('title')}: supporting materials")
    description = str(
        zenodo.get("description")
        or f"Supporting materials for the manuscript “{record.get('title')}”."
    )
    metadata: dict[str, Any] = {
        "title": title,
        "upload_type": zenodo.get("upload_type") or ("software" if mode == "github_zenodo" else "other"),
        "description": description,
        "creators": creators,
        "publication_date": zenodo.get("publication_date") or date.today().isoformat(),
        "access_right": zenodo.get("access_right") or "open",
        "prereserve_doi": True,
    }
    optional_scalar_fields = ("publication_type", "notes", "language")
    for field in optional_scalar_fields:
        value = zenodo.get(field)
        if isinstance(value, str) and value.strip():
            metadata[field] = value.strip()
    license_value = (
        zenodo.get("license") or publication.get("license") or default_license
    )
    if isinstance(license_value, str) and license_value.strip():
        metadata["license"] = license_value.strip()
    # ``support.publication.zenodo.version`` records the version associated
    # with the current remote state.  It is deliberately not a metadata
    # override: after a manuscript version bump that value is stale until
    # preparation completes.  The paper registry remains the version source
    # of truth for every metadata update.
    version_value = _record_version(record)
    if isinstance(version_value, str) and version_value.strip():
        metadata["version"] = version_value.strip()
    for field in ("keywords", "related_identifiers", "communities", "grants"):
        value = zenodo.get(field)
        if isinstance(value, list) and value:
            metadata[field] = value
    return metadata


def resolve_package_files(
    record: Mapping[str, Any],
    explicit_files: Iterable[str | Path] = (),
    *,
    repo_root: str | Path | None = None,
) -> list[Path]:
    root = Path(repo_root or default_repo_root()).resolve()
    support = record.get("support") if isinstance(record.get("support"), Mapping) else {}
    publication = support.get("publication") if isinstance(support.get("publication"), Mapping) else {}
    configured = publication.get("package_files") if isinstance(publication.get("package_files"), list) else []
    values = [*configured, *explicit_files]
    paths: list[Path] = []
    seen_paths: set[Path] = set()
    for value in values:
        path = Path(value)
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        if path not in seen_paths:
            seen_paths.add(path)
            paths.append(path)
    return paths


def build_deposit_plan(
    record: Mapping[str, Any],
    files: Iterable[str | Path] = (),
    *,
    environment: str | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(repo_root or default_repo_root()).resolve()
    publication = record.get("support", {}).get("publication", {})
    selected_environment = environment or publication.get("zenodo", {}).get("environment") or "sandbox"
    _environment(selected_environment)
    settings_path = root / "registry" / "settings.yaml"
    settings = load_config(settings_path) if settings_path.is_file() else {}
    default_license = effective_publication_license(
        {}, publication_policy(settings)
    )
    metadata = build_zenodo_metadata(record, default_license=default_license)
    paths = resolve_package_files(record, files, repo_root=root)
    errors: list[str] = []
    if not paths:
        errors.append("No support-package files were selected.")
    if len(paths) > MAX_FILES:
        errors.append(f"Zenodo accepts at most {MAX_FILES} files per record.")
    duplicate_names = sorted({path.name for path in paths if sum(item.name == path.name for item in paths) > 1})
    if duplicate_names:
        errors.append(f"Duplicate upload filenames: {', '.join(duplicate_names)}")
    file_records: list[dict[str, Any]] = []
    total_bytes = 0
    for path in paths:
        if not path.is_file():
            errors.append(f"Package file does not exist or is not a regular file: {path}")
            continue
        size = path.stat().st_size
        total_bytes += size
        file_records.append(
            {
                "path": str(path),
                "name": path.name,
                "size": size,
                "sha256": _sha256(path),
            }
        )
    if total_bytes > MAX_TOTAL_BYTES:
        errors.append(f"Selected files exceed the {MAX_TOTAL_BYTES}-byte Zenodo record limit.")
    token_env = token_environment_name(selected_environment)
    return {
        "paper_id": record.get("id"),
        "paper_title": record.get("title"),
        "publication_mode": publication.get("mode"),
        "environment": selected_environment,
        "api_url": _api_url(selected_environment),
        "token_env": token_env,
        "token_configured": bool(os.environ.get(token_env, "").strip()),
        "metadata": metadata,
        "files": file_records,
        "file_count": len(file_records),
        "total_bytes": total_bytes,
        "errors": errors,
        "ready": not errors,
    }


class ZenodoClient:
    """Small synchronous client for the official Zenodo deposition API."""

    def __init__(
        self,
        environment: str,
        token: str,
        *,
        client: httpx.Client | None = None,
        timeout: float = 300.0,
    ) -> None:
        self.environment = environment
        self.api_url = _api_url(environment)
        self._expected_host = urlparse(self.api_url).hostname
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=timeout)
        self.headers = {"Authorization": f"Bearer {token}"}

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "ZenodoClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def create_draft(self, metadata: Mapping[str, Any]) -> dict[str, Any]:
        return self._json(
            self.client.post(
                f"{self.api_url}/deposit/depositions",
                json={"metadata": dict(metadata)},
                headers=self.headers,
            ),
            "create Zenodo draft",
        )

    def get_deposition(self, deposition_id: int | str) -> dict[str, Any]:
        return self._json(
            self.client.get(
                f"{self.api_url}/deposit/depositions/{deposition_id}",
                headers=self.headers,
            ),
            "read Zenodo deposition",
        )

    def update_metadata(self, deposition_id: int | str, metadata: Mapping[str, Any]) -> dict[str, Any]:
        return self._json(
            self.client.put(
                f"{self.api_url}/deposit/depositions/{deposition_id}",
                json={"metadata": dict(metadata)},
                headers=self.headers,
            ),
            "update Zenodo deposition metadata",
        )

    def upload_file(self, draft: Mapping[str, Any], path: str | Path) -> dict[str, Any]:
        bucket = draft.get("links", {}).get("bucket") if isinstance(draft.get("links"), Mapping) else None
        if not isinstance(bucket, str) or not bucket:
            raise ZenodoError("Zenodo draft response did not include a file bucket URL.")
        parsed = urlparse(bucket)
        if parsed.scheme != "https" or parsed.hostname != self._expected_host:
            raise ZenodoError(f"Refusing unexpected Zenodo bucket URL: {bucket}")
        upload_path = Path(path)
        with upload_path.open("rb") as handle:
            response = self.client.put(
                f"{bucket.rstrip('/')}/{quote(upload_path.name)}",
                content=handle,
                headers=self.headers,
            )
        return self._json(response, f"upload {upload_path.name}")

    def delete_file(self, deposition_id: int | str, file_id: int | str) -> dict[str, Any]:
        """Delete one file from an unpublished deposition draft."""
        encoded_file_id = quote(str(file_id), safe="")
        response = self.client.delete(
            f"{self.api_url}/deposit/depositions/{deposition_id}/files/{encoded_file_id}",
            headers=self.headers,
        )
        if not response.is_success:
            try:
                payload: Any = response.json()
            except ValueError:
                payload = response.text[:1000]
            raise ZenodoError(
                f"Failed to delete Zenodo draft file {file_id}: "
                f"HTTP {response.status_code}: {payload}"
            )
        return {"deleted": True, "deposition_id": deposition_id, "file_id": str(file_id)}

    def publish(self, deposition_id: int | str) -> dict[str, Any]:
        return self._json(
            self.client.post(
                f"{self.api_url}/deposit/depositions/{deposition_id}/actions/publish",
                headers=self.headers,
            ),
            "publish Zenodo deposition",
        )

    def new_version(self, deposition_id: int | str) -> dict[str, Any]:
        source = self._json(
            self.client.post(
                f"{self.api_url}/deposit/depositions/{deposition_id}/actions/newversion",
                headers=self.headers,
            ),
            "create Zenodo version draft",
        )
        latest_draft = source.get("links", {}).get("latest_draft") if isinstance(source.get("links"), Mapping) else None
        if not isinstance(latest_draft, str) or not latest_draft:
            raise ZenodoError("Zenodo new-version response did not include links.latest_draft.")
        parsed = urlparse(latest_draft)
        if parsed.scheme != "https" or parsed.hostname != self._expected_host:
            raise ZenodoError(f"Refusing unexpected Zenodo draft URL: {latest_draft}")
        return self._json(self.client.get(latest_draft, headers=self.headers), "read Zenodo version draft")

    @staticmethod
    def _json(response: httpx.Response, operation: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not response.is_success:
            detail = payload if payload is not None else response.text[:1000]
            raise ZenodoError(f"Failed to {operation}: HTTP {response.status_code}: {detail}")
        if not isinstance(payload, dict):
            raise ZenodoError(f"Failed to {operation}: Zenodo returned a non-object response.")
        return payload


def _update_metadata_with_transient_readback(
    client: ZenodoClient,
    draft: Mapping[str, Any],
    record: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Recover a timed-out idempotent metadata update by verifying read-back.

    Zenodo's gateway can return a transient 5xx after the deposition backend
    has accepted a PUT.  Repeating the same PUT is safe, but it is unnecessary
    when a fresh GET already proves that every release-critical identity field
    and creator matches the requested metadata.  Authentication and validation
    failures are never recovered this way.
    """

    draft_id = _deposition_id(draft)
    reserved_doi = _reserved_version_doi(draft)
    try:
        return client.update_metadata(draft_id, metadata)
    except ZenodoError as exc:
        if not any(marker in str(exc) for marker in TRANSIENT_METADATA_STATUS_MARKERS):
            raise
        refreshed = client.get_deposition(draft_id)
        _require_unpublished_draft(refreshed)
        _verify_draft_identity(
            record,
            {"zenodo": {"reserved_version_doi": reserved_doi}},
            refreshed,
            expected_metadata=metadata,
        )
        return refreshed


def create_draft_with_files(
    record: Mapping[str, Any],
    files: Iterable[str | Path],
    *,
    environment: str,
    token: str,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    plan = build_deposit_plan(record, files, environment=environment, repo_root=repo_root)
    if not plan["ready"]:
        raise ZenodoError("Deposit preflight failed: " + "; ".join(plan["errors"]))
    with ZenodoClient(environment, token) as client:
        draft = client.create_draft(plan["metadata"])
        uploads = [client.upload_file(draft, item["path"]) for item in plan["files"]]
    return {"plan": plan, "draft": draft, "uploads": uploads}


def create_version_with_files(
    record: Mapping[str, Any],
    deposition_id: int | str,
    files: Iterable[str | Path],
    *,
    environment: str,
    token: str,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    plan = build_deposit_plan(record, files, environment=environment, repo_root=repo_root)
    if not plan["ready"]:
        raise ZenodoError("Deposit preflight failed: " + "; ".join(plan["errors"]))
    with ZenodoClient(environment, token) as client:
        draft = client.new_version(deposition_id)
        draft = client.update_metadata(draft["id"], plan["metadata"])
        removed = [
            client.delete_file(draft["id"], item["id"])
            for item in draft.get("files", [])
            if isinstance(item, Mapping) and item.get("id") is not None
        ]
        uploads = [client.upload_file(draft, item["path"]) for item in plan["files"]]
    return {"plan": plan, "draft": draft, "removed_inherited_files": removed, "uploads": uploads}


def prepare_zenodo_release(
    paper_id: str,
    sources: Iterable[str | Path] = (),
    *,
    environment: str,
    token: str,
    repo_root: str | Path | None = None,
    config_path: str | Path | None = None,
    output: str | Path | None = None,
    deposition_id: int | str | None = None,
    license_id: str | None = None,
) -> dict[str, Any]:
    """Build and upload a deterministic package to a reversible Zenodo draft.

    The draft is recorded in the paper registry, including its reserved DOI and
    exact local package digest. This operation never runs an LLM and never
    publishes the deposition. If ``start-revision`` captured a passing baseline,
    it may deterministically carry that review across an author/release-metadata
    change after proving that manuscript and support evidence are unchanged.
    """

    root = Path(repo_root or default_repo_root()).resolve()
    record = find_paper_record(paper_id, repo_root=root, config_path=config_path)
    source_paths = resolve_support_sources(record, sources, repo_root=root)
    validate_git_frozen_paths(root, source_paths)
    origin_commit = git_head(root)
    settings = load_config(config_path or root / "registry" / "settings.yaml")
    policy = publication_policy(settings)
    raw_publication = record.get("support", {}).get("publication", {})
    raw_publication = (
        raw_publication if isinstance(raw_publication, Mapping) else {}
    )
    metadata = build_zenodo_metadata(
        record,
        default_license=effective_publication_license(raw_publication, policy),
    )
    selected_license = str(
        license_id
        or metadata.get("license")
        or ""
    ).strip()
    if not selected_license:
        raise ZenodoError(
            "A support-material license is required; set support.publication.license "
            "or pass --license"
        )
    metadata["license"] = selected_license

    raw_record = load_paper_metadata(paper_id, root)
    publication = _mutable_publication(raw_record)
    registered_zenodo = publication.get("zenodo")
    registered_zenodo = (
        dict(registered_zenodo) if isinstance(registered_zenodo, Mapping) else {}
    )
    current_status = str(publication.get("status") or "planned")
    registered_environment = str(registered_zenodo.get("environment") or "")
    registered_deposition = registered_zenodo.get("deposition_id")
    if (
        current_status == "published"
        and registered_deposition is not None
        and str(registered_zenodo.get("version") or "") == _record_version(record)
    ):
        raise ZenodoError(
            "The current paper version already has a published Zenodo release; start a new "
            "paper revision/version before preparing replacement support files"
        )
    if (
        current_status == "draft"
        and registered_deposition is not None
        and registered_environment
        and registered_environment != environment
    ):
        if registered_environment == "sandbox" and environment == "production":
            registered_zenodo["sandbox_deposition_id"] = registered_deposition
            registered_zenodo["sandbox_reserved_version_doi"] = registered_zenodo.get(
                "reserved_version_doi"
            )
            current_status = "planned"
            registered_deposition = None
        else:
            raise ZenodoError(
                "A prepared Zenodo draft already exists in a different environment; do not "
                "overwrite its registry state"
            )
    resume_id = deposition_id
    if (
        resume_id is None
        and current_status == "draft"
        and registered_environment == environment
        and registered_deposition is not None
    ):
        resume_id = registered_deposition

    active_draft_id: int | str | None = None
    try:
        with ZenodoClient(environment, token) as client:
            if resume_id is not None:
                draft = client.get_deposition(resume_id)
                _require_unpublished_draft(draft)
                draft = _update_metadata_with_transient_readback(
                    client,
                    draft,
                    record,
                    metadata,
                )
            elif current_status == "published" and registered_deposition is not None:
                draft = client.new_version(registered_deposition)
                _require_unpublished_draft(draft)
                draft = _update_metadata_with_transient_readback(
                    client,
                    draft,
                    record,
                    metadata,
                )
            else:
                draft = client.create_draft(metadata)
            active_draft_id = _deposition_id(draft)
            reserved_doi = _reserved_version_doi(draft)
            if not reserved_doi:
                raise ZenodoError("Zenodo draft did not return a reserved Version DOI")

            package = build_support_archive(
                record,
                source_paths,
                repo_root=root,
                output=output,
                reserved_doi=reserved_doi,
                origin_commit=origin_commit,
                license_id=selected_license,
            )
            removed = [
                client.delete_file(active_draft_id, item["id"])
                for item in draft.get("files", [])
                if isinstance(item, Mapping) and item.get("id") is not None
            ]
            upload_paths = [package["archive"], package["checksum"]]
            uploads = [client.upload_file(draft, path) for path in upload_paths]
            refreshed = client.get_deposition(active_draft_id)
            remote_files = verify_deposition_files(refreshed, upload_paths)
            verified_metadata = _verify_draft_identity(
                record,
                {"zenodo": {"reserved_version_doi": reserved_doi}},
                refreshed,
                expected_metadata=metadata,
            )
    except SupportPackageError as exc:
        suffix = (
            f"; Zenodo draft {active_draft_id} can be resumed with --deposition-id"
            if active_draft_id is not None
            else ""
        )
        raise ZenodoError(f"Support package preparation failed: {exc}{suffix}") from exc
    except ZenodoError as exc:
        if active_draft_id is None:
            raise
        raise ZenodoError(
            f"Zenodo draft {active_draft_id} was not published and can be resumed: {exc}"
        ) from exc

    prepared_at = _now()
    archive = Path(package["archive"])
    checksum = Path(package["checksum"])
    receipt_path = archive.parent / "draft.json"
    receipt = {
        "schema_version": "ara.paper_writing.zenodo_draft.v2",
        "paper_id": paper_id,
        "paper_version": _record_version(record),
        "environment": environment,
        "deposition_id": active_draft_id,
        "reserved_version_doi": reserved_doi,
        "prepared_at": prepared_at,
        "origin_commit": origin_commit,
        "submitted_metadata": _receipt_metadata(metadata),
        "submitted_metadata_sha256": _json_sha256(_receipt_metadata(metadata)),
        "verified_remote_metadata": verified_metadata,
        "verified_remote_metadata_sha256": _json_sha256(verified_metadata),
        "package": {
            "archive": _relative_path(archive, root),
            "checksum": _relative_path(checksum, root),
            "size": package["archive_size"],
            "sha256": package["archive_sha256"],
            "source_files": package["source_files"],
        },
        "remote_files": remote_files,
    }
    _write_json(receipt_path, receipt)

    _preserve_previous_published_identity(
        publication,
        registered_zenodo,
        current_status=current_status,
        current_draft_doi=reserved_doi,
    )
    publication.update(
        {
            "status": "draft",
            "version_doi": reserved_doi,
            "record_url": f"https://doi.org/{reserved_doi}",
            "license": selected_license,
            "source_files": package["source_files"],
            "package_files": [
                _relative_path(archive, root),
                _relative_path(checksum, root),
            ],
            "package_size": package["archive_size"],
            "package_sha256": package["archive_sha256"],
            "prepared_at": prepared_at,
            "prepared_from_commit": origin_commit,
            "draft_receipt": _relative_path(receipt_path, root),
        }
    )
    # Legacy imported releases kept the sidecar in ``verification_files``
    # while current prepared releases register the ZIP and sidecar together
    # in ``package_files``.  Retaining both representations makes the same
    # sidecar appear twice to the support audit and release verifier.
    publication.pop("verification_files", None)
    registered_zenodo.update(
        {
            "environment": environment,
            "deposition_id": active_draft_id,
            "reserved_version_doi": reserved_doi,
            "version_doi": reserved_doi,
            "record_url": f"https://doi.org/{reserved_doi}",
            "version": _record_version(record),
            "license": selected_license,
            "publication_date": metadata["publication_date"],
            "title": verified_metadata.get("title"),
            "creators": verified_metadata.get("creators", []),
            "metadata_source": (
                f"{_api_url(environment)}/deposit/depositions/{active_draft_id}"
            ),
            "metadata_verified_at": prepared_at,
            "remote_files": remote_files,
            "remote_files_verified_at": prepared_at,
        }
    )
    publication["zenodo"] = registered_zenodo
    raw_record["status_updated_at"] = prepared_at
    write_paper_metadata(paper_id, raw_record, root)
    review_reuse: dict[str, Any] | None = None
    writing_release = raw_record.get("writing_release")
    writing_release = writing_release if isinstance(writing_release, Mapping) else {}
    if isinstance(writing_release.get("review_carry_forward"), Mapping):
        from paper_writing.operations import reuse_review_for_metadata_only_revision

        try:
            review_reuse = reuse_review_for_metadata_only_revision(
                paper_id,
                root=root,
            )
        except (OSError, SupportPackageError, ValueError) as exc:
            review_reuse = {
                "status": "fresh_review_required",
                "llm_review_rerun": None,
                "reason": str(exc),
            }
    return {
        "paper_id": paper_id,
        "version": _record_version(record),
        "status": "draft",
        "environment": environment,
        "deposition_id": active_draft_id,
        "reserved_version_doi": reserved_doi,
        "archive": _relative_path(archive, root),
        "archive_sha256": package["archive_sha256"],
        "remote_files": remote_files,
        "receipt": _relative_path(receipt_path, root),
        "removed_draft_files": len(removed),
        "uploaded_files": len(uploads),
        "review_reuse": review_reuse,
        "next_action": (
            "Commit the registry, manuscript, PDF and support package, then release the "
            "prepared draft."
            if review_reuse and review_reuse.get("status") == "ready"
            else "Cite the reserved DOI if appropriate, rebuild/review the manuscript, pass "
            "the quality gate, and commit the registry, manuscript, PDF and support package."
        ),
    }


def publish_zenodo_release(
    paper_id: str,
    *,
    environment: str,
    token: str,
    repo_root: str | Path | None = None,
    config_path: str | Path | None = None,
    deposition_id: int | str | None = None,
) -> dict[str, Any]:
    """Publish a prepared draft after revalidating gate, Git and remote files.

    The revalidated quality gate establishes eligibility for this irreversible
    publication. The CLI separately requires explicit production and paper-ID
    confirmation.
    """

    from paper_writing.handoff import HandoffError, validate_release_preconditions

    root = Path(repo_root or default_repo_root()).resolve()
    try:
        gate = validate_release_preconditions(
            paper_id,
            root=root,
            support_gate_name="before_support_release",
        )
    except HandoffError as exc:
        raise ZenodoError(f"Zenodo release gate failed: {exc}") from exc
    record = find_paper_record(paper_id, repo_root=root, config_path=config_path)
    raw_record = load_paper_metadata(paper_id, root)
    publication = _mutable_publication(raw_record)
    if publication.get("status") != "draft":
        raise ZenodoError(
            "Zenodo release requires a prepared draft; run `paper-writing zenodo prepare` first"
        )
    zenodo = publication.get("zenodo")
    zenodo = dict(zenodo) if isinstance(zenodo, Mapping) else {}
    registered_environment = str(zenodo.get("environment") or "")
    if registered_environment != environment:
        raise ZenodoError(
            f"Prepared draft environment is {registered_environment!r}, not {environment!r}"
        )
    selected_deposition = deposition_id or zenodo.get("deposition_id")
    if selected_deposition is None:
        raise ZenodoError("Prepared draft is missing its Zenodo deposition_id")
    if deposition_id is not None and str(deposition_id) != str(zenodo.get("deposition_id")):
        raise ZenodoError("--deposition-id does not match the prepared paper registry")

    package_paths = resolve_package_files(record, (), repo_root=root)
    archive_paths = [path for path in package_paths if path.suffix.casefold() == ".zip"]
    checksum_paths = [path for path in package_paths if path.name.casefold().endswith(".zip.sha256")]
    if len(archive_paths) != 1 or len(checksum_paths) != 1 or len(package_paths) != 2:
        raise ZenodoError("Prepared release must contain exactly one ZIP and its .zip.sha256 sidecar")
    raw_sources = publication.get("source_files")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ZenodoError("Prepared release is missing its expanded support source file list")
    source_paths = [root / str(value) for value in raw_sources]
    validate_git_frozen_paths(root, [*source_paths, *package_paths])
    archive = archive_paths[0]
    checksum = checksum_paths[0]
    archive_result = verify_support_archive(archive)
    if archive_result.get("paper_id") != paper_id:
        raise ZenodoError("Support archive paper_id does not match the requested paper")
    if archive_result.get("paper_version") != _record_version(record):
        raise ZenodoError("Support archive version does not match the manuscript version")
    expected_sha256 = str(publication.get("package_sha256") or "")
    if sha256_file(archive) != expected_sha256:
        raise ZenodoError("Support archive SHA-256 no longer matches the paper registry")
    writing_release = raw_record.get("writing_release")
    writing_release = writing_release if isinstance(writing_release, Mapping) else {}
    if writing_release.get("support_package_sha256") != expected_sha256:
        raise ZenodoError(
            "Quality gate is not bound to this support package; rerun quality-gate after "
            "`zenodo prepare`"
        )
    if archive.stat().st_size != publication.get("package_size"):
        raise ZenodoError("Support archive size no longer matches the paper registry")
    expected_sidecar = f"{expected_sha256}  {archive.name}\n"
    if checksum.read_text(encoding="utf-8") != expected_sidecar:
        raise ZenodoError("Support archive .sha256 sidecar is stale or malformed")
    _verify_archive_sources(archive_result, source_paths, root)

    with ZenodoClient(environment, token) as client:
        draft = client.get_deposition(selected_deposition)
        if str(_deposition_id(draft)) != str(selected_deposition):
            raise ZenodoError("Zenodo returned a different deposition than requested")
        _verify_draft_identity(record, publication, draft)
        remote_files = verify_deposition_files(draft, package_paths)
        already_published = draft.get("submitted") is True
        if not already_published:
            client.publish(selected_deposition)
            response = client.get_deposition(selected_deposition)
        else:
            response = draft
        if not isinstance(response, Mapping):
            raise ZenodoError("Zenodo publish returned an invalid response")
        if response.get("submitted") is not True:
            raise ZenodoError(
                f"Zenodo did not confirm publication of deposition {selected_deposition}; retry "
                "the same release command to reconcile its state"
            )

    registration = publication_registration(record, response, environment)
    registered_publication = registration["support"]["publication"]
    registered_zenodo = registered_publication["zenodo"]
    version_doi = registered_zenodo.get("version_doi")
    reserved_doi = zenodo.get("reserved_version_doi")
    if reserved_doi and version_doi and reserved_doi != version_doi:
        raise ZenodoError("Published Zenodo DOI does not match the reserved draft DOI")

    published_at = str(registered_zenodo.get("published_at") or _now())
    receipt_path = archive.parent / "release.json"
    receipt = {
        "schema_version": "ara.paper_writing.zenodo_release.v1",
        "paper_id": paper_id,
        "paper_version": _record_version(record),
        "environment": environment,
        "deposition_id": selected_deposition,
        "already_published": already_published,
        "origin_commit": gate["origin_commit"],
        "manuscript_snapshot_sha256": gate["manuscript_snapshot_sha256"],
        "quality_gate_score": gate["score"],
        "quality_gate_decision_standard": gate["decision_standard"],
        "package_sha256": expected_sha256,
        "remote_files": remote_files,
        "version_doi": version_doi,
        "concept_doi": registered_zenodo.get("concept_doi"),
        "record_url": registered_zenodo.get("record_url"),
        "published_at": published_at,
    }
    _write_json(receipt_path, receipt)

    publication["status"] = "published" if environment == "production" else "draft"
    publication["release_receipt"] = _relative_path(receipt_path, root)
    publication["release_binding"] = {
        "origin_commit": gate["origin_commit"],
        "manuscript_snapshot_sha256": gate["manuscript_snapshot_sha256"],
        "score": gate["score"],
        "target_score": gate["target_score"],
        "decision_standard": gate["decision_standard"],
        "decision": gate["decision"],
        "package_sha256": expected_sha256,
    }
    for key in ("version_doi", "concept_doi", "record_url"):
        if registered_zenodo.get(key):
            publication[key] = registered_zenodo[key]
    zenodo.update({key: value for key, value in registered_zenodo.items() if value is not None})
    if environment != "production":
        zenodo["sandbox_published"] = True
    publication["zenodo"] = zenodo
    raw_record["status_updated_at"] = _now()
    write_paper_metadata(paper_id, raw_record, root)
    return {
        "paper_id": paper_id,
        "version": _record_version(record),
        "status": publication["status"],
        "environment": environment,
        "deposition_id": selected_deposition,
        "version_doi": version_doi,
        "concept_doi": registered_zenodo.get("concept_doi"),
        "record_url": registered_zenodo.get("record_url"),
        "already_published": already_published,
        "receipt": _relative_path(receipt_path, root),
        "commit_required": True,
        "next_action": (
            "Commit and push the Zenodo registry/receipt update; the main-branch workflow "
            "will synchronize the ready paper to Manage."
        ),
    }


def verify_prepared_zenodo_draft(
    paper_id: str,
    *,
    environment: str,
    token: str,
    repo_root: str | Path | None = None,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Read back and verify a prepared draft without changing remote state."""

    root = Path(repo_root or default_repo_root()).resolve()
    record = find_paper_record(paper_id, repo_root=root, config_path=config_path)
    raw_record = load_paper_metadata(paper_id, root)
    publication = _mutable_publication(raw_record)
    if publication.get("status") != "draft":
        raise ZenodoError("Draft verification requires support.publication.status=draft")
    zenodo = publication.get("zenodo")
    zenodo = dict(zenodo) if isinstance(zenodo, Mapping) else {}
    if str(zenodo.get("environment") or "") != environment:
        raise ZenodoError(
            f"Prepared draft environment is {zenodo.get('environment')!r}, not {environment!r}"
        )
    deposition_id = zenodo.get("deposition_id")
    if deposition_id is None:
        raise ZenodoError("Prepared draft is missing its Zenodo deposition_id")
    package_paths = resolve_package_files(record, (), repo_root=root)
    archive_paths = [path for path in package_paths if path.suffix.casefold() == ".zip"]
    checksum_paths = [
        path for path in package_paths if path.name.casefold().endswith(".zip.sha256")
    ]
    if len(package_paths) != 2 or len(archive_paths) != 1 or len(checksum_paths) != 1:
        raise ZenodoError(
            "Prepared draft must contain exactly one ZIP and its .zip.sha256 sidecar"
        )
    archive = archive_paths[0]
    checksum = checksum_paths[0]
    if not archive.is_file() or not checksum.is_file():
        raise ZenodoError("Prepared draft package files are missing locally")
    expected_sha256 = str(publication.get("package_sha256") or "")
    if sha256_file(archive) != expected_sha256:
        raise ZenodoError("Support archive SHA-256 no longer matches the paper registry")
    if checksum.read_text(encoding="utf-8") != f"{expected_sha256}  {archive.name}\n":
        raise ZenodoError("Support archive .sha256 sidecar is stale or malformed")
    archive_result = verify_support_archive(archive)
    if archive_result.get("paper_id") != paper_id:
        raise ZenodoError("Support archive paper_id does not match the requested paper")
    if archive_result.get("paper_version") != _record_version(record):
        raise ZenodoError("Support archive version does not match the manuscript version")
    with ZenodoClient(environment, token) as client:
        draft = client.get_deposition(deposition_id)
        if str(_deposition_id(draft)) != str(deposition_id):
            raise ZenodoError("Zenodo returned a different deposition than requested")
        if draft.get("submitted") is True:
            raise ZenodoError(
                "Registered draft has already been published; reconcile with zenodo release"
            )
        verified_metadata = _verify_draft_identity(record, publication, draft)
        remote_files = verify_deposition_files(draft, package_paths)
    return {
        "paper_id": paper_id,
        "status": "draft",
        "environment": environment,
        "deposition_id": deposition_id,
        "reserved_version_doi": zenodo.get("reserved_version_doi"),
        "version": _record_version(record),
        "package_sha256": expected_sha256,
        "verified_remote_metadata": verified_metadata,
        "remote_files": remote_files,
        "remote_state_changed": False,
    }


def verify_deposition_files(
    deposition: Mapping[str, Any],
    local_files: Iterable[str | Path],
) -> list[dict[str, Any]]:
    """Require exact remote filenames, sizes and cryptographic transfer checksums."""

    local_paths = [Path(path).resolve() for path in local_files]
    local = {path.name: path for path in local_paths}
    if len(local) != len(local_paths):
        raise ZenodoError("Local Zenodo upload filenames must be unique")
    remote_items = deposition.get("files")
    if not isinstance(remote_items, list):
        raise ZenodoError("Zenodo deposition did not return a file list")
    remote: dict[str, Mapping[str, Any]] = {}
    for item in remote_items:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("filename") or item.get("key") or "").strip()
        if name:
            if name in remote:
                raise ZenodoError(f"Zenodo deposition contains duplicate filename: {name}")
            remote[name] = item
    if set(remote) != set(local):
        raise ZenodoError(
            "Zenodo draft files differ from the prepared package: "
            f"local={sorted(local)}, remote={sorted(remote)}"
        )

    verified: list[dict[str, Any]] = []
    for name, path in sorted(local.items()):
        item = remote[name]
        raw_size = item.get("filesize", item.get("size"))
        try:
            remote_size = int(raw_size)
        except (TypeError, ValueError) as exc:
            raise ZenodoError(f"Zenodo file {name} is missing its byte size") from exc
        if remote_size != path.stat().st_size:
            raise ZenodoError(f"Zenodo file size mismatch for {name}")
        algorithm, remote_digest = _remote_checksum(item.get("checksum"))
        local_digest = sha256_file(path) if algorithm == "sha256" else md5_file(path)
        if remote_digest != local_digest:
            raise ZenodoError(f"Zenodo {algorithm} checksum mismatch for {name}")
        verified.append(
            {
                "name": name,
                "size": remote_size,
                "checksum": f"{algorithm}:{remote_digest}",
                "sha256": sha256_file(path),
            }
        )
    return verified


def publication_registration(record: Mapping[str, Any], response: Mapping[str, Any], environment: str) -> dict[str, Any]:
    metadata = response.get("metadata") if isinstance(response.get("metadata"), Mapping) else {}
    links = response.get("links") if isinstance(response.get("links"), Mapping) else {}
    version_doi = response.get("doi") or metadata.get("doi")
    if not version_doi and isinstance(metadata.get("prereserve_doi"), Mapping):
        version_doi = metadata["prereserve_doi"].get("doi")
    concept_record_id = response.get("conceptrecid")
    concept_doi = response.get("conceptdoi") or metadata.get("conceptdoi")
    if not concept_doi and concept_record_id:
        concept_doi = f"{_environment(environment)['doi_prefix']}{concept_record_id}"
    return {
        "paper_id": record.get("id"),
        "support": {
            "publication": {
                "status": "published" if environment == "production" else "draft",
                "zenodo": {
                    "environment": environment,
                    "deposition_id": response.get("id"),
                    "record_id": response.get("record_id"),
                    "concept_record_id": concept_record_id,
                    "concept_doi": concept_doi,
                    "version_doi": version_doi,
                    "record_url": links.get("html") or (f"https://doi.org/{version_doi}" if version_doi else None),
                    "version": metadata.get("version"),
                    "published_at": response.get("modified"),
                },
            }
        },
    }


def _record_version(record: Mapping[str, Any]) -> str:
    direct = record.get("version")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    metadata = record.get("metadata")
    if isinstance(metadata, Mapping):
        value = metadata.get("version")
        if isinstance(value, str) and value.strip():
            return value.strip()
    manuscript = record.get("manuscript")
    if isinstance(manuscript, Mapping):
        version = manuscript.get("version")
        if isinstance(version, Mapping):
            value = version.get("label")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return "1.0.0"


def _mutable_publication(record: dict[str, Any]) -> dict[str, Any]:
    support = record.get("support")
    support = dict(support) if isinstance(support, Mapping) else {}
    publication = support.get("publication")
    publication = dict(publication) if isinstance(publication, Mapping) else {}
    support["publication"] = publication
    record["support"] = support
    return publication


def _preserve_previous_published_identity(
    publication: dict[str, Any],
    zenodo: dict[str, Any],
    *,
    current_status: str,
    current_draft_doi: str,
) -> None:
    """Move a superseded public-record identity out of the active draft fields.

    The active ``version_doi`` always names the support version that the
    manuscript must cite.  Any earlier published record remains available as
    internal audit history, never as the active reader-facing identity.
    """

    old_doi = str(publication.get("version_doi") or zenodo.get("version_doi") or "").strip()
    if old_doi and old_doi != current_draft_doi:
        # ``previous_published`` is singular and must describe the immediate
        # predecessor of the new draft.  Reusing older values with
        # ``setdefault`` silently skipped the record being superseded on the
        # third and later Zenodo versions.
        previous: dict[str, Any] = {"version_doi": old_doi}
        for field in (
            "concept_doi",
            "record_url",
            "record_id",
            "published_at",
        ):
            value = publication.get(field) or zenodo.get(field)
            if value is not None:
                previous[field] = value
        if current_status == "published" and zenodo.get("version") is not None:
            previous["version"] = zenodo["version"]
        if publication.get("public_download_verified") is True:
            previous["public_download_verified"] = True
        zenodo["previous_published"] = previous

    publication.pop("public_download_verified", None)
    for field in ("record_id", "published_at"):
        zenodo.pop(field, None)


def _deposition_id(deposition: Mapping[str, Any]) -> int | str:
    value = deposition.get("id")
    if value is None or not str(value).strip():
        raise ZenodoError("Zenodo deposition response did not include an id")
    return value


def _require_unpublished_draft(deposition: Mapping[str, Any]) -> None:
    if deposition.get("submitted") is True:
        raise ZenodoError("The selected Zenodo deposition is already published")
    _deposition_id(deposition)


def _reserved_version_doi(deposition: Mapping[str, Any]) -> str | None:
    metadata = deposition.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    preregistered = metadata.get("prereserve_doi")
    if isinstance(preregistered, Mapping) and preregistered.get("doi"):
        return str(preregistered["doi"])
    for value in (deposition.get("doi"), metadata.get("doi")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _verify_draft_identity(
    record: Mapping[str, Any],
    publication: Mapping[str, Any],
    deposition: Mapping[str, Any],
    *,
    expected_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = deposition.get("metadata")
    if not isinstance(metadata, Mapping):
        raise ZenodoError("Zenodo deposition metadata is missing")
    expected = dict(expected_metadata or build_zenodo_metadata(record))
    for field in ZENODO_IDENTITY_FIELDS:
        if expected.get(field) and metadata.get(field) != expected[field]:
            raise ZenodoError(f"Zenodo draft {field} does not match the paper registry")
    expected_creators = _normalized_creators(expected.get("creators"))
    remote_creators = _normalized_creators(metadata.get("creators"))
    if not expected_creators:
        raise ZenodoError("Paper registry does not define any Zenodo creators")
    if remote_creators != expected_creators:
        raise ZenodoError("Zenodo draft creators do not match the paper registry")
    zenodo = publication.get("zenodo")
    zenodo = zenodo if isinstance(zenodo, Mapping) else {}
    reserved = str(zenodo.get("reserved_version_doi") or "")
    remote_reserved = _reserved_version_doi(deposition)
    if reserved and remote_reserved != reserved:
        raise ZenodoError("Zenodo draft reserved DOI does not match the paper registry")
    return _receipt_metadata(metadata)


def _normalized_creators(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    creators: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        creator = {
            field: str(item[field]).strip()
            for field in ("name", "affiliation", "orcid")
            if item.get(field) is not None and str(item[field]).strip()
        }
        if creator:
            creators.append(creator)
    return creators


def _receipt_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return the public, release-critical metadata frozen into a draft receipt."""

    snapshot = {
        field: value[field]
        for field in ZENODO_IDENTITY_FIELDS
        if value.get(field) is not None
    }
    snapshot["creators"] = _normalized_creators(value.get("creators"))
    return snapshot


def _json_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _verify_archive_sources(
    archive_result: Mapping[str, Any],
    source_paths: Iterable[Path],
    root: Path,
) -> None:
    entries = archive_result.get("files")
    if not isinstance(entries, list):
        raise ZenodoError("Support archive manifest is missing its source file list")
    paper_id = str(archive_result.get("paper_id") or "").strip()
    display_id = str(archive_result.get("display_id") or "").strip()
    paper_version = str(archive_result.get("paper_version") or "").strip()
    if not paper_id or not display_id or not paper_version:
        raise ZenodoError("Support archive manifest is missing paper identity fields")
    archive_root = f"{display_id}-support-v{_safe_archive_component(paper_version)}"
    manifest_files: dict[str, Mapping[str, Any]] = {}
    for item in entries:
        if not isinstance(item, Mapping):
            raise ZenodoError("Support archive manifest contains an invalid file entry")
        archive_path = str(item.get("archive_path") or "")
        if not archive_path or archive_path in manifest_files:
            raise ZenodoError("Support archive manifest contains duplicate or empty archive paths")
        manifest_files[archive_path] = item
    current_files = {
        f"{archive_root}/{_support_archive_relative_path(path.resolve(), root, paper_id)}": path.resolve()
        for path in source_paths
    }
    if set(manifest_files) != set(current_files):
        raise ZenodoError("Current support source list differs from the prepared archive manifest")
    for archive_path, path in current_files.items():
        item = manifest_files[archive_path]
        if item.get("size") != path.stat().st_size or item.get("sha256") != sha256_file(path):
            raise ZenodoError(
                f"Support source changed after the Zenodo draft was prepared: {archive_path}"
            )


def _safe_archive_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._") or "release"


def _support_archive_relative_path(path: Path, root: Path, paper_id: str) -> str:
    relative = path.relative_to(root.resolve())
    workspace = Path("papers") / paper_id
    try:
        return relative.relative_to(workspace).as_posix()
    except ValueError:
        return (Path("repository") / relative).as_posix()


def _remote_checksum(value: Any) -> tuple[str, str]:
    if isinstance(value, Mapping):
        algorithm = str(value.get("type") or value.get("algorithm") or "").casefold()
        digest = str(value.get("value") or value.get("checksum") or "").casefold()
    else:
        raw = str(value or "").strip().casefold()
        if ":" in raw:
            algorithm, digest = raw.split(":", 1)
        elif len(raw) == 32:
            algorithm, digest = "md5", raw
        elif len(raw) == 64:
            algorithm, digest = "sha256", raw
        else:
            algorithm, digest = "", raw
    if algorithm not in {"md5", "sha256"}:
        raise ZenodoError("Zenodo file checksum is missing or uses an unsupported algorithm")
    expected_length = 32 if algorithm == "md5" else 64
    if len(digest) != expected_length or any(character not in "0123456789abcdef" for character in digest):
        raise ZenodoError("Zenodo file checksum is malformed")
    return algorithm, digest


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ZenodoError(f"Zenodo release path must stay inside the repository: {path}") from exc


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _environment(environment: str) -> Mapping[str, str]:
    if environment not in ZENODO_ENVIRONMENTS:
        raise ZenodoError(f"Unknown Zenodo environment: {environment}")
    return ZENODO_ENVIRONMENTS[environment]


def _api_url(environment: str) -> str:
    configured = os.environ.get("ZENODO_API_URL", "").strip()
    return configured.rstrip("/") if configured else str(_environment(environment)["api_url"])


def _anonymous_name(value: str) -> bool:
    folded = value.casefold()
    return any(token in folded for token in ("anonymous", "blind review", "匿名"))


def _zenodo_person_name(value: str) -> str:
    normalized = " ".join(value.split())
    if "," in normalized:
        return normalized
    parts = normalized.split()
    return f"{parts[-1]}, {' '.join(parts[:-1])}" if len(parts) > 1 else normalized


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
